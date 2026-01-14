"""
QBuilder API — Public interface for MCP tools and external callers.

This module provides the canonical API for:
- Enqueuing files for processing (flash updates and batch)
- Checking build status
- Waiting for completion
- Starting background builds

All operations go through the build_queue. No bypass mode.

Priority levels:
- 0 (NORMAL): Batch discovery, full rebuilds
- 1 (FLASH): Single-file updates after agent mutations

Hard rules (from spec):
- No parallel "immediate pipeline" — all work goes through queue
- No stage-scan scheduling — no "missing AST/symbol/ref" decisions
- Correctness is fingerprint-based, not row-existence-based
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from qbuilder.schema import init_qbuilder_schema
from qbuilder.discovery import get_envelope_for_file, get_routing_table


# Priority levels
PRIORITY_NORMAL = 0
PRIORITY_FLASH = 1

# Default database path
DEFAULT_DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"

# Polling intervals
WAIT_POLL_INTERVAL = 0.05  # 50ms between polls
WAIT_MAX_TIME = 30.0  # Max wait time for wait_for_completion


@dataclass
class EnqueueResult:
    """Result of enqueue_file operation."""
    success: bool
    build_id: Optional[int]
    file_id: Optional[int]
    message: str
    already_queued: bool = False


@dataclass
class BuildStatus:
    """Status of a build queue item."""
    build_id: int
    status: str  # pending, processing, completed, error
    priority: int
    file_id: int
    relpath: Optional[str]
    error_message: Optional[str]


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Get a database connection with standard settings."""
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def enqueue_file(
    mod_name: str,
    rel_path: str,
    content: Optional[str] = None,
    priority: int = PRIORITY_FLASH,
    db_path: Optional[Path] = None,
) -> EnqueueResult:
    """
    Enqueue a file for processing.
    
    This is the primary API for flash updates after agent mutations.
    The file is added to build_queue with the given priority.
    
    Args:
        mod_name: Mod name (maps to content_version via mod_packages)
        rel_path: Relative path within the mod
        content: Optional file content (if None, reads from disk)
        priority: 0=normal, 1=flash (default=flash for mutations)
        db_path: Optional database path override
    
    Returns:
        EnqueueResult with build_id if enqueued, or error message
    """
    conn = get_connection(db_path)
    
    try:
        # Initialize schema (ensures priority column exists)
        init_qbuilder_schema(conn)
        
        # Find the file_id for this (mod_name, rel_path)
        row = conn.execute("""
            SELECT f.file_id, f.file_mtime, f.file_size, f.file_hash,
                   mp.source_path
            FROM files f
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE mp.name = ? AND f.relpath = ?
        """, (mod_name, rel_path)).fetchone()
        
        if not row:
            # File not in DB yet - need to create it
            # First find the mod
            mod_row = conn.execute("""
                SELECT mp.mod_package_id, mp.source_path, cv.content_version_id
                FROM mod_packages mp
                JOIN content_versions cv ON mp.mod_package_id = cv.mod_package_id
                WHERE mp.name = ?
            """, (mod_name,)).fetchone()
            
            if not mod_row:
                return EnqueueResult(
                    success=False,
                    build_id=None,
                    file_id=None,
                    message=f"Mod not found: {mod_name}"
                )
            
            mod_package_id, source_path, cvid = mod_row
            abspath = Path(source_path) / rel_path
            
            if not abspath.exists():
                return EnqueueResult(
                    success=False,
                    build_id=None,
                    file_id=None,
                    message=f"File not found: {abspath}"
                )
            
            # Get fingerprint
            stat = abspath.stat()
            mtime = stat.st_mtime
            size = stat.st_size
            
            if content is None:
                content = abspath.read_text(encoding='utf-8', errors='replace')
            file_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
            
            # Determine file type from extension
            ext = Path(rel_path).suffix.lower()
            file_type = {
                '.txt': 'script',
                '.yml': 'localization',
                '.gui': 'gui',
                '.gfx': 'gfx',
                '.dds': 'texture',
            }.get(ext, 'other')
            
            # Insert file record
            cursor = conn.execute("""
                INSERT INTO files (content_version_id, relpath, content_hash, file_type,
                                   file_mtime, file_size, file_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (content_version_id, relpath) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    file_type = excluded.file_type,
                    file_mtime = excluded.file_mtime,
                    file_size = excluded.file_size,
                    file_hash = excluded.file_hash
                RETURNING file_id
            """, (cvid, rel_path, file_hash, file_type, mtime, size, file_hash))
            
            file_id = cursor.fetchone()[0]
            conn.commit()
        else:
            file_id = row['file_id']
            source_path = row['source_path']
            abspath = Path(source_path) / rel_path
            
            # Re-fingerprint from current content
            if content is None:
                if not abspath.exists():
                    return EnqueueResult(
                        success=False,
                        build_id=None,
                        file_id=file_id,
                        message=f"File not found: {abspath}"
                    )
                content = abspath.read_text(encoding='utf-8', errors='replace')
            
            stat = abspath.stat()
            mtime = stat.st_mtime
            size = stat.st_size
            file_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
            
            # Update files table with new fingerprint
            conn.execute("""
                UPDATE files SET file_mtime = ?, file_size = ?, file_hash = ?
                WHERE file_id = ?
            """, (mtime, size, file_hash, file_id))
        
        # Get envelope from routing table
        routing_table = get_routing_table()
        envelope = get_envelope_for_file(rel_path, routing_table)
        
        # Enqueue with priority
        now = time.time()
        cursor = conn.execute("""
            INSERT INTO build_queue 
                (file_id, envelope, priority, work_file_mtime, work_file_size, 
                 work_file_hash, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            ON CONFLICT (file_id, envelope, work_file_mtime, work_file_size, 
                         COALESCE(work_file_hash, '')) 
            DO NOTHING
            RETURNING build_id
        """, (file_id, envelope, priority, mtime, size, file_hash, now))
        
        result = cursor.fetchone()
        conn.commit()
        
        if result:
            return EnqueueResult(
                success=True,
                build_id=result[0],
                file_id=file_id,
                message=f"Enqueued with priority={priority}"
            )
        else:
            # Already queued with same fingerprint
            row = conn.execute("""
                SELECT build_id FROM build_queue
                WHERE file_id = ? AND envelope = ? 
                  AND work_file_mtime = ? AND work_file_size = ?
                  AND COALESCE(work_file_hash, '') = COALESCE(?, '')
            """, (file_id, envelope, mtime, size, file_hash)).fetchone()
            
            return EnqueueResult(
                success=True,
                build_id=row[0] if row else None,
                file_id=file_id,
                message="Already queued with same fingerprint",
                already_queued=True
            )
    finally:
        conn.close()


def delete_file(
    mod_name: str,
    rel_path: str,
    db_path: Optional[Path] = None,
) -> dict:
    """
    Remove a file and its artifacts from the database.
    
    This handles file deletion after an agent removes a mod file.
    Cascades to remove ASTs, symbols, refs for this file.
    
    Args:
        mod_name: Mod name
        rel_path: Relative path within the mod
        db_path: Optional database path override
    
    Returns:
        Dict with success status and counts
    """
    conn = get_connection(db_path)
    
    try:
        # Find file_id
        row = conn.execute("""
            SELECT f.file_id
            FROM files f
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE mp.name = ? AND f.relpath = ?
        """, (mod_name, rel_path)).fetchone()
        
        if not row:
            return {"success": True, "message": "File not in database", "deleted": 0}
        
        file_id = row[0]
        
        # Delete from build_queue first (no FK constraint, just cleanup)
        conn.execute("DELETE FROM build_queue WHERE file_id = ?", (file_id,))
        
        # Delete artifacts (these may have FK constraints or write protection)
        # Use BuilderSession if needed
        try:
            from src.ck3raven.db.schema import BuilderSession
            with BuilderSession(conn, f"delete_file:{file_id}"):
                conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
                conn.execute("DELETE FROM refs WHERE file_id = ?", (file_id,))
                conn.commit()
        except ImportError:
            # No BuilderSession available, try direct
            conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
            conn.execute("DELETE FROM refs WHERE file_id = ?", (file_id,))
        
        conn.execute("DELETE FROM asts WHERE file_id = ?", (file_id,))
        conn.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
        conn.commit()
        
        return {
            "success": True,
            "message": f"Deleted file_id={file_id}",
            "file_id": file_id,
            "deleted": 1
        }
    finally:
        conn.close()


def get_build_status(build_id: int, db_path: Optional[Path] = None) -> Optional[BuildStatus]:
    """
    Get status of a specific build queue item.
    
    Args:
        build_id: The build queue ID
        db_path: Optional database path override
    
    Returns:
        BuildStatus or None if not found
    """
    conn = get_connection(db_path)
    
    try:
        row = conn.execute("""
            SELECT b.build_id, b.status, b.priority, b.file_id, 
                   b.error_message, f.relpath
            FROM build_queue b
            LEFT JOIN files f ON b.file_id = f.file_id
            WHERE b.build_id = ?
        """, (build_id,)).fetchone()
        
        if not row:
            return None
        
        return BuildStatus(
            build_id=row['build_id'],
            status=row['status'],
            priority=row['priority'] or 0,
            file_id=row['file_id'],
            relpath=row['relpath'],
            error_message=row['error_message']
        )
    finally:
        conn.close()


def wait_for_completion(
    build_id: int,
    timeout: float = WAIT_MAX_TIME,
    poll_interval: float = WAIT_POLL_INTERVAL,
    db_path: Optional[Path] = None,
) -> BuildStatus:
    """
    Wait for a build queue item to complete.
    
    Polls the database until the item reaches 'completed' or 'error' status,
    or until timeout is reached.
    
    Args:
        build_id: The build queue ID to wait for
        timeout: Maximum seconds to wait
        poll_interval: Seconds between polls
        db_path: Optional database path override
    
    Returns:
        Final BuildStatus (may still be 'pending' or 'processing' if timeout)
    """
    start = time.time()
    
    while True:
        status = get_build_status(build_id, db_path)
        
        if status is None:
            raise ValueError(f"Build ID not found: {build_id}")
        
        if status.status in ('completed', 'error'):
            return status
        
        if time.time() - start > timeout:
            return status
        
        time.sleep(poll_interval)


def is_build_running(db_path: Optional[Path] = None) -> bool:
    """
    Check if there are pending or processing items in the build queue.
    
    Returns:
        True if there's work in progress
    """
    conn = get_connection(db_path)
    
    try:
        row = conn.execute("""
            SELECT COUNT(*) FROM build_queue
            WHERE status IN ('pending', 'processing')
        """).fetchone()
        
        return row[0] > 0
    finally:
        conn.close()


def get_queue_stats(db_path: Optional[Path] = None) -> dict:
    """
    Get build queue statistics.
    
    Returns:
        Dict with counts by status and priority
    """
    conn = get_connection(db_path)
    
    try:
        # By status
        rows = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM build_queue
            GROUP BY status
        """).fetchall()
        
        by_status = {row['status']: row['count'] for row in rows}
        
        # By priority (pending only)
        rows = conn.execute("""
            SELECT priority, COUNT(*) as count
            FROM build_queue
            WHERE status = 'pending'
            GROUP BY priority
        """).fetchall()
        
        by_priority = {f"priority_{row['priority']}": row['count'] for row in rows}
        
        # Total
        total_pending = by_status.get('pending', 0)
        total_processing = by_status.get('processing', 0)
        total_completed = by_status.get('completed', 0)
        total_error = by_status.get('error', 0)
        
        return {
            "pending": total_pending,
            "processing": total_processing,
            "completed": total_completed,
            "error": total_error,
            "flash_pending": by_priority.get('priority_1', 0),
            "normal_pending": by_priority.get('priority_0', 0),
            "has_work": total_pending > 0 or total_processing > 0,
        }
    finally:
        conn.close()


def check_playset_build_status(playset_data: dict, db_path: Optional[Path] = None) -> dict:
    """
    Check which mods in a playset are fully built.
    
    Args:
        playset_data: Playset dict with 'mods' list
        db_path: Optional database path override
    
    Returns:
        Dict with mod statuses and overall readiness
    """
    conn = get_connection(db_path)
    
    try:
        mods = playset_data.get('mods', [])
        vanilla_path = playset_data.get('vanilla_path')
        
        results = []
        ready_count = 0
        pending_count = 0
        missing_count = 0
        missing_names = []
        
        # Check each mod
        for mod in mods:
            mod_name = mod.get('name', 'Unknown')
            mod_path = mod.get('path') or mod.get('source_path')
            
            # Check if mod exists on disk
            exists_on_disk = mod_path and Path(mod_path).exists()
            
            if not exists_on_disk:
                results.append({
                    "name": mod_name,
                    "status": "missing",
                    "exists_on_disk": False,
                })
                missing_count += 1
                missing_names.append(mod_name)
                continue
            
            # Check if mod has files in DB
            row = conn.execute("""
                SELECT COUNT(*) as file_count,
                       (SELECT COUNT(*) FROM build_queue bq 
                        JOIN files f ON bq.file_id = f.file_id
                        JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                        JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                        WHERE mp.name = ? AND bq.status = 'pending') as pending_count
                FROM files f
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE mp.name = ?
            """, (mod_name, mod_name)).fetchone()
            
            file_count = row['file_count'] if row else 0
            pending = row['pending_count'] if row else 0
            
            if file_count == 0:
                status = "not_indexed"
                pending_count += 1
            elif pending > 0:
                status = "pending_build"
                pending_count += 1
            else:
                status = "ready"
                ready_count += 1
            
            results.append({
                "name": mod_name,
                "status": status,
                "exists_on_disk": True,
                "file_count": file_count,
                "pending_builds": pending,
            })
        
        # Overall status
        playset_valid = len(mods) == 0 or (len(mods) - missing_count) > 0
        needs_build = pending_count > 0
        
        return {
            "playset_valid": playset_valid,
            "total_mods": len(mods),
            "ready_mods": ready_count,
            "pending_mods": pending_count,
            "missing_mods": missing_count,
            "missing_mod_names": missing_names,
            "needs_build": needs_build,
            "mods": results,
            "build_command": "python -m qbuilder.cli build" if needs_build else None,
        }
    finally:
        conn.close()


def start_background_build(
    db_path: Optional[Path] = None,
    max_items: Optional[int] = None,
    log_file: Optional[Path] = None,
) -> dict:
    """
    Start a background build subprocess.
    
    Runs `python -m qbuilder.cli build` in the background.
    Uses subprocess to survive MCP server restart.
    
    Args:
        db_path: Optional database path override
        max_items: Optional limit on items to process
        log_file: Optional log file path
    
    Returns:
        Dict with subprocess info (pid, log_file)
    """
    # Build command
    cmd = [sys.executable, "-m", "qbuilder.cli", "build"]
    
    if db_path:
        cmd.extend(["--db", str(db_path)])
    
    if max_items:
        cmd.extend(["--max-items", str(max_items)])
    
    # Default log file
    if log_file is None:
        log_file = Path.home() / ".ck3raven" / "qbuilder_build.log"
    
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Start subprocess
    with open(log_file, 'a') as log:
        log.write(f"\n\n=== Build started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        log.write(f"Command: {' '.join(cmd)}\n")
        log.flush()
        
        # Start detached subprocess
        if os.name == 'nt':
            # Windows: use CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                cwd=Path(__file__).parent.parent,  # ck3raven root
            )
        else:
            # Unix: use start_new_session
            proc = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                cwd=Path(__file__).parent.parent,
            )
    
    return {
        "success": True,
        "pid": proc.pid,
        "log_file": str(log_file),
        "command": " ".join(cmd),
        "message": "Background build started"
    }


# Convenience aliases for MCP tool compatibility
def refresh_file(mod_name: str, rel_path: str, content: Optional[str] = None) -> dict:
    """Alias for enqueue_file with flash priority. Returns dict for MCP compatibility."""
    result = enqueue_file(mod_name, rel_path, content, priority=PRIORITY_FLASH)
    return {
        "success": result.success,
        "build_id": result.build_id,
        "file_id": result.file_id,
        "message": result.message,
        "already_queued": result.already_queued,
    }


def mark_file_deleted(mod_name: str, rel_path: str) -> dict:
    """Alias for delete_file. Returns dict for MCP compatibility."""
    return delete_file(mod_name, rel_path)


# ============================================================================
# Health Check Functions
# ============================================================================

# Thresholds
WAL_SIZE_THRESHOLD = 50 * 1024 * 1024  # 50MB - large WAL suggests crash


def check_and_recover(db_path: Optional[Path] = None) -> dict:
    """
    Check database health and recover from stale state.
    
    For qbuilder, this is simplified:
    - Check WAL size and checkpoint if large
    - Check for stale build queue items (stuck in 'processing')
    - Reset stale items to 'pending' for reprocessing
    
    Returns:
        {
            "healthy": bool,
            "actions_taken": list[str],
            "errors": list[str],
            "wal_size_before": int,
            "wal_size_after": int,
        }
    """
    db_path = db_path or DEFAULT_DB_PATH
    wal_path = db_path.with_suffix(".db-wal")
    
    result = {
        "healthy": True,
        "actions_taken": [],
        "errors": [],
        "wal_size_before": 0,
        "wal_size_after": 0,
    }
    
    try:
        conn = get_connection(db_path)
        
        # Check WAL size
        if wal_path.exists():
            result["wal_size_before"] = wal_path.stat().st_size
            
            if result["wal_size_before"] > WAL_SIZE_THRESHOLD:
                result["actions_taken"].append(
                    f"Large WAL detected: {result['wal_size_before'] / 1024 / 1024:.1f}MB"
                )
                
                # Try to checkpoint
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    result["actions_taken"].append("WAL checkpoint successful")
                    result["wal_size_after"] = wal_path.stat().st_size if wal_path.exists() else 0
                except Exception as e:
                    result["errors"].append(f"Checkpoint failed: {e}")
                    result["healthy"] = False
        
        # Check for stale 'processing' items (stuck for > 5 minutes)
        stale_threshold = time.time() - 300  # 5 minutes ago
        stale_rows = conn.execute("""
            SELECT build_id FROM build_queue 
            WHERE status = 'processing' AND started_at < ?
        """, (stale_threshold,)).fetchall()
        
        if stale_rows:
            stale_ids = [row[0] for row in stale_rows]
            conn.execute("""
                UPDATE build_queue 
                SET status = 'pending', started_at = NULL, completed_at = NULL,
                    error_message = 'Reset from stale processing state'
                WHERE build_id IN ({})
            """.format(','.join('?' * len(stale_ids))), stale_ids)
            conn.commit()
            result["actions_taken"].append(f"Reset {len(stale_ids)} stale processing items")
        
    except Exception as e:
        result["errors"].append(f"Health check failed: {e}")
        result["healthy"] = False
    
    return result


def get_health_status(db_path: Optional[Path] = None) -> dict:
    """
    Get current database health status without taking recovery actions.
    
    Returns:
        {
            "healthy": bool,
            "wal_size_mb": float,
            "stale_processing": int,
            "queue_stats": dict,
            "daemon_stale": bool,
            "stale_reason": str | None,
        }
    """
    db_path = db_path or DEFAULT_DB_PATH
    wal_path = db_path.with_suffix(".db-wal")
    
    result = {
        "healthy": True,
        "wal_size_mb": 0.0,
        "stale_processing": 0,
        "queue_stats": {},
        "daemon_stale": False,
        "stale_reason": None,
    }
    
    try:
        # Check WAL
        if wal_path.exists():
            result["wal_size_mb"] = wal_path.stat().st_size / 1024 / 1024
            if result["wal_size_mb"] > 50:
                result["healthy"] = False
                result["stale_reason"] = f"Large WAL: {result['wal_size_mb']:.1f}MB"
        
        # Check queue
        result["queue_stats"] = get_queue_stats(db_path)
        
        # Check stale processing
        conn = get_connection(db_path)
        stale_threshold = time.time() - 300
        stale_count = conn.execute("""
            SELECT COUNT(*) FROM build_queue 
            WHERE status = 'processing' AND started_at < ?
        """, (stale_threshold,)).fetchone()[0]
        
        result["stale_processing"] = stale_count
        if stale_count > 0:
            result["healthy"] = False
            result["daemon_stale"] = True
            result["stale_reason"] = f"{stale_count} items stuck in processing"
        
    except Exception as e:
        result["healthy"] = False
        result["stale_reason"] = str(e)
    
    return result

