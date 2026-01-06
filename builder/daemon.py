#!/usr/bin/env python3
"""
Standalone rebuild daemon that runs completely detached from terminals.

This script is designed to be launched and then forgotten - it will:
1. Detach from the parent process completely
2. Write all progress to log files
3. Handle database locks with retries
4. Create a PID file for monitoring
5. Write periodic heartbeats for liveness checking

Usage:
    python rebuild_daemon.py start [--force] [--db PATH]
    python rebuild_daemon.py status
    python rebuild_daemon.py stop
    python rebuild_daemon.py logs [-f]
"""

import sys
import os
import json
import time
import sqlite3
import hashlib
import subprocess
import argparse
import traceback
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

# Paths
DEFAULT_DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"
DAEMON_DIR = Path.home() / ".ck3raven" / "daemon"
PLAYSETS_DIR = Path(__file__).parent.parent / "playsets"
PLAYSET_MANIFEST = PLAYSETS_DIR / "playset_manifest.json"
PID_FILE = DAEMON_DIR / "rebuild.pid"
LOCK_FILE = DAEMON_DIR / "rebuild.lock"
STATUS_FILE = DAEMON_DIR / "rebuild_status.json"
LOG_FILE = DAEMON_DIR / "rebuild.log"
HEARTBEAT_FILE = DAEMON_DIR / "heartbeat"
DEBUG_OUTPUT_FILE = DAEMON_DIR / "debug_output.json"

# Folders that are pure data structures with no script references
# These have large AST node counts but yield 0 refs - skip for performance
# Based on analysis: landed_titles has 100k nodes but 0 refs, etc.
REF_EXTRACTION_SKIP_FOLDERS = (
    'common/landed_titles',      # 100k+ nodes, 0 refs - title hierarchy
    'common/bookmark_portraits', # 600k+ nodes - portrait definitions
    'common/genes',              # 200k+ nodes - gene definitions
    'common/culture/name_equivalency',  # Pure name mappings
    'common/event_backgrounds',  # Background definitions
    'map_data',                  # Map terrain data
    'gfx',                       # Graphics definitions
    'fonts',                     # Font definitions
)

# Ensure daemon directory exists
DAEMON_DIR.mkdir(parents=True, exist_ok=True)


class DaemonLogger:
    """File-based logger that doesn't use stdout/stderr."""
    
    def __init__(self, log_path: Path, also_print: bool = False):
        self.log_path = log_path
        self.also_print = also_print
        self._ensure_file()
    
    def _ensure_file(self):
        if not self.log_path.exists():
            self.log_path.write_text("")
    
    def log(self, level: str, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}\n"
        # Always write to file first (primary output)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line)
        # Console output is optional - may fail if terminal closed/redirected
        if self.also_print:
            try:
                print(line.rstrip())
            except OSError:
                pass  # Console unavailable, continue silently
    
    def info(self, message: str):
        self.log("INFO", message)
    
    def error(self, message: str):
        self.log("ERROR", message)
    
    def warning(self, message: str):
        self.log("WARN", message)
    
    def debug(self, message: str):
        self.log("DEBUG", message)


class StatusWriter:
    """Writes status to a JSON file for external monitoring."""
    
    def __init__(self, status_path: Path):
        self.status_path = status_path
        self._status = {
            "state": "initializing",
            "phase": None,
            "phase_number": 0,
            "total_phases": 7,
            "progress": 0.0,
            "message": "",
            "started_at": None,
            "updated_at": None,
            "error": None,
            "stats": {}
        }
    
    def update(self, **kwargs):
        self._status.update(kwargs)
        self._status["updated_at"] = datetime.now().isoformat()
        self._write()
    
    def _write(self):
        try:
            # Write atomically
            tmp_path = self.status_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(self._status, indent=2))
            tmp_path.replace(self.status_path)
        except Exception:
            pass  # Best effort
    
    def get(self) -> dict:
        return self._status.copy()


class DatabaseWrapper:
    """Database connection wrapper with lock handling and retries."""
    
    def __init__(self, db_path: Path, logger: DaemonLogger, max_retries: int = 10, base_delay: float = 1.0):
        self.db_path = db_path
        self.logger = logger
        self.max_retries = max_retries
        self.base_delay = base_delay
        self._conn: Optional[sqlite3.Connection] = None
    
    def connect(self) -> sqlite3.Connection:
        """Connect with retry logic for locked databases."""
        for attempt in range(self.max_retries):
            try:
                conn = sqlite3.connect(
                    str(self.db_path),
                    timeout=30.0,  # Wait up to 30s for locks
                    isolation_level=None  # Autocommit mode
                )
                # Enable WAL mode for better concurrency
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=30000")  # 30s busy timeout
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.row_factory = sqlite3.Row
                self._conn = conn
                self.logger.info(f"Database connected: {self.db_path}")
                return conn
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    delay = self.base_delay * (2 ** attempt)
                    self.logger.warning(f"Database locked, retry {attempt + 1}/{self.max_retries} in {delay:.1f}s")
                    time.sleep(delay)
                else:
                    raise
        
        raise RuntimeError(f"Failed to connect to database after {self.max_retries} retries")
    
    def checkpoint(self):
        """Force WAL checkpoint to consolidate changes."""
        if self._conn:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self.logger.debug("WAL checkpoint completed")
            except Exception as e:
                self.logger.warning(f"WAL checkpoint failed: {e}")
    
    def close(self):
        """Close connection cleanly."""
        if self._conn:
            try:
                self.checkpoint()
                self._conn.close()
                self.logger.info("Database connection closed")
            except Exception as e:
                self.logger.warning(f"Error closing database: {e}")
            finally:
                self._conn = None


# =============================================================================
# BUILD TRACKING
# =============================================================================

BUILDER_VERSION = "1.0.0"
MANIFEST_FILE = DAEMON_DIR / "build_manifest.json"


@dataclass
class StepStats:
    """Statistics for a single build step."""
    rows_in: int = 0
    rows_out: int = 0
    rows_skipped: int = 0
    rows_errored: int = 0


# Build phases in execution order
BUILD_PHASES = [
    "vanilla_ingest",
    "mod_ingest", 
    "ast_generation",
    "symbol_extraction",
    "ref_extraction",
    "localization_parsing",
    "lookup_extraction",
]


class BuildTracker:
    """
    Tracks build progress and records to builder_runs/builder_steps tables.
    
    Ensures every build is recorded and produces a manifest on completion.
    
    Note: builder_steps is an AUDIT LOG, not a source of truth.
    Each phase function checks DATABASE STATE to determine what work is needed.
    Phases that find no work to do complete quickly (no need to "skip" them).
    """
    
    def __init__(self, conn: sqlite3.Connection, logger: DaemonLogger, 
                 vanilla_path: Optional[str] = None, playset_id: Optional[int] = None,
                 force: bool = False):
        self.conn = conn
        self.logger = logger
        self.vanilla_path = vanilla_path
        self.playset_id = playset_id
        self.force = force
        self.started_at = datetime.now().isoformat()
        self._current_step: Optional[str] = None
        self._current_step_start: Optional[float] = None
        self._step_number = 0
        self._steps: Dict[str, dict] = {}
        
        # Try to get git commit
        self.git_commit = self._get_git_commit()
        
        # Always start a new build - phases will self-skip based on DB state
        self.build_id = str(uuid.uuid4())
        self._init_build()
    
    def _get_git_commit(self) -> Optional[str]:
        """Get current git commit hash if in a git repo."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=Path(__file__).parent.parent
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None
    
    def _init_build(self):
        """Record build start in database."""
        from ck3raven.db.schema import DATABASE_VERSION
        
        try:
            self.conn.execute("""
                INSERT INTO builder_runs 
                (build_id, builder_version, git_commit, schema_version, started_at, 
                 vanilla_path, playset_id, force_rebuild)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self.build_id, BUILDER_VERSION, self.git_commit, DATABASE_VERSION,
                self.started_at, self.vanilla_path, self.playset_id, int(self.force)
            ))
            self.conn.commit()
            self.logger.info(f"Build started: {self.build_id}")
        except Exception as e:
            self.logger.warning(f"Failed to record build start: {e}")
    
    def acquire_lock(self) -> bool:
        """Try to acquire build lock. Returns True if acquired."""
        try:
            # Check for existing lock
            existing = self.conn.execute(
                "SELECT build_id, heartbeat_at, pid FROM build_lock WHERE lock_id = 1"
            ).fetchone()
            
            if existing:
                # Check if lock is stale (>2 minutes old)
                last_heartbeat = datetime.fromisoformat(existing['heartbeat_at'])
                age = (datetime.now() - last_heartbeat).total_seconds()
                if age < 120:
                    self.logger.error(f"Build lock held by {existing['build_id']} (pid {existing['pid']})")
                    return False
                # Stale lock - take it over
                self.logger.warning(f"Taking over stale lock from {existing['build_id']}")
            
            # Acquire or update lock
            self.conn.execute("""
                INSERT OR REPLACE INTO build_lock (lock_id, build_id, acquired_at, heartbeat_at, pid)
                VALUES (1, ?, ?, ?, ?)
            """, (self.build_id, datetime.now().isoformat(), datetime.now().isoformat(), os.getpid()))
            self.conn.commit()
            self.logger.info("Build lock acquired")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to acquire build lock: {e}")
            return False
    
    def release_lock(self):
        """Release build lock."""
        try:
            self.conn.execute("DELETE FROM build_lock WHERE build_id = ?", (self.build_id,))
            self.conn.commit()
            self.logger.info("Build lock released")
        except Exception as e:
            self.logger.warning(f"Failed to release build lock: {e}")
    
    def update_lock_heartbeat(self):
        """Update lock heartbeat to prevent takeover."""
        try:
            self.conn.execute(
                "UPDATE build_lock SET heartbeat_at = ? WHERE build_id = ?",
                (datetime.now().isoformat(), self.build_id)
            )
        except Exception:
            pass
    
    def start_step(self, step_name: str, step_version: str = "1.0"):
        """Start tracking a build step."""
        self._step_number += 1
        self._current_step = step_name
        self._current_step_start = time.time()
        
        try:
            self.conn.execute("""
                INSERT INTO builder_steps
                (build_id, step_name, step_version, step_number, started_at, state)
                VALUES (?, ?, ?, ?, ?, 'running')
            """, (self.build_id, step_name, step_version, self._step_number, 
                  datetime.now().isoformat()))
            self.conn.commit()
        except Exception as e:
            self.logger.warning(f"Failed to record step start: {e}")
    
    def end_step(self, step_name: str, stats: StepStats, success: bool = True, error: str = None):
        """Complete tracking a build step."""
        duration = time.time() - self._current_step_start if self._current_step_start else 0
        state = 'complete' if success else 'failed'
        
        self._steps[step_name] = {
            'duration_sec': duration,
            'state': state,
            'rows_in': stats.rows_in,
            'rows_out': stats.rows_out,
            'rows_skipped': stats.rows_skipped,
            'rows_errored': stats.rows_errored,
            'error': error
        }
        
        try:
            self.conn.execute("""
                UPDATE builder_steps
                SET completed_at = ?, duration_sec = ?, state = ?, error_message = ?,
                    rows_in = ?, rows_out = ?, rows_skipped = ?, rows_errored = ?
                WHERE build_id = ? AND step_name = ?
            """, (
                datetime.now().isoformat(), duration, state, error,
                stats.rows_in, stats.rows_out, stats.rows_skipped, stats.rows_errored,
                self.build_id, step_name
            ))
            self.conn.commit()
        except Exception as e:
            self.logger.warning(f"Failed to record step end: {e}")
        
        self._current_step = None
        self._current_step_start = None
    
    def skip_step(self, step_name: str, reason: str = "skipped"):
        """Mark a step as skipped."""
        self._step_number += 1
        try:
            self.conn.execute("""
                INSERT INTO builder_steps
                (build_id, step_name, step_number, started_at, completed_at, 
                 duration_sec, state, error_message)
                VALUES (?, ?, ?, ?, ?, 0, 'skipped', ?)
            """, (self.build_id, step_name, self._step_number, 
                  datetime.now().isoformat(), datetime.now().isoformat(), reason))
            self.conn.commit()
        except Exception as e:
            self.logger.warning(f"Failed to record step skip: {e}")
    
    def complete(self, counts: Dict[str, int]):
        """Mark build as complete and generate manifest."""
        try:
            self.conn.execute("""
                UPDATE builder_runs
                SET completed_at = ?, state = 'complete',
                    files_ingested = ?, asts_produced = ?, symbols_extracted = ?,
                    refs_extracted = ?, localization_rows = ?, lookup_rows = ?
                WHERE build_id = ?
            """, (
                datetime.now().isoformat(),
                counts.get('files', 0), counts.get('asts', 0), counts.get('symbols', 0),
                counts.get('refs', 0), counts.get('localization', 0), counts.get('lookups', 0),
                self.build_id
            ))
            self.conn.commit()
            self.logger.info(f"Build completed: {self.build_id}")
        except Exception as e:
            self.logger.warning(f"Failed to record build completion: {e}")
        
        # Generate manifest
        self._write_manifest(counts)
        self.release_lock()
    
    def fail(self, error: str):
        """Mark build as failed."""
        try:
            self.conn.execute("""
                UPDATE builder_runs
                SET completed_at = ?, state = 'failed', error_message = ?
                WHERE build_id = ?
            """, (datetime.now().isoformat(), error, self.build_id))
            self.conn.commit()
            self.logger.error(f"Build failed: {self.build_id} - {error}")
        except Exception as e:
            self.logger.warning(f"Failed to record build failure: {e}")
        
        self.release_lock()
    
    def _write_manifest(self, counts: Dict[str, int]):
        """Write build_manifest.json."""
        from ck3raven.db.schema import DATABASE_VERSION
        
        manifest = {
            "build_id": self.build_id,
            "builder_version": BUILDER_VERSION,
            "git_commit": self.git_commit,
            "schema_version": DATABASE_VERSION,
            "started_at": self.started_at,
            "completed_at": datetime.now().isoformat(),
            "inputs": {
                "vanilla_path": self.vanilla_path,
                "playset_id": self.playset_id,
                "force_rebuild": self.force
            },
            "counts": counts,
            "steps": [
                {
                    "name": name,
                    "duration_sec": info['duration_sec'],
                    "state": info['state'],
                    "rows_in": info['rows_in'],
                    "rows_out": info['rows_out'],
                    "rows_skipped": info['rows_skipped'],
                    "rows_errored": info['rows_errored']
                }
                for name, info in self._steps.items()
            ],
            "total_duration_sec": sum(s['duration_sec'] for s in self._steps.values())
        }
        
        try:
            MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))
            self.logger.info(f"Manifest written: {MANIFEST_FILE}")
        except Exception as e:
            self.logger.warning(f"Failed to write manifest: {e}")
    
    # =========================================================================
    # INGEST LOGGING - Per-file logging with block reconstruction
    # =========================================================================
    
    def log_file(
        self,
        phase: str,
        relpath: str,
        status: str,
        file_id: int = None,
        content_version_id: int = None,
        size_raw: int = None,
        size_stored: int = None,
        content_hash: str = None,
        error_type: str = None,
        error_msg: str = None
    ) -> None:
        """Log a file operation in the ingest_log table.
        
        Args:
            phase: Phase name (e.g., "ingest", "ast_generation")
            relpath: Relative path of the file
            status: One of 'processed', 'skipped_routing', 'skipped_uptodate', 'error'
            file_id: FK to files table (if file is in DB)
            content_version_id: FK to content_versions
            size_raw: Original file size in bytes
            size_stored: Bytes written to DB
            content_hash: SHA256 of file content
            error_type: Error class name if status='error'
            error_msg: Error message (truncated) if status='error'
        """
        try:
            self.conn.execute("""
                INSERT INTO ingest_log 
                (build_id, phase, timestamp, file_id, relpath, content_version_id,
                 status, size_raw, size_stored, content_hash, error_type, error_msg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self.build_id, phase, time.time(), file_id, relpath, content_version_id,
                status, size_raw, size_stored, content_hash, 
                error_type, error_msg[:500] if error_msg else None
            ))
        except Exception as e:
            # Don't let logging failures break the build
            self.logger.debug(f"Failed to log file: {e}")
    
    def log_files_bulk(self, phase: str, entries: list) -> None:
        """Bulk insert file log entries for efficiency.
        
        Args:
            phase: Phase name
            entries: List of dicts with keys matching log_file() parameters
        """
        if not entries:
            return
            
        try:
            self.conn.executemany("""
                INSERT INTO ingest_log 
                (build_id, phase, timestamp, file_id, relpath, content_version_id,
                 status, size_raw, size_stored, content_hash, error_type, error_msg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    self.build_id, phase, time.time(), 
                    e.get('file_id'), e.get('relpath', ''), e.get('content_version_id'),
                    e.get('status', 'processed'), e.get('size_raw'), e.get('size_stored'),
                    e.get('content_hash'), e.get('error_type'), 
                    (e.get('error_msg') or '')[:500] or None
                )
                for e in entries
            ])
        except Exception as e:
            self.logger.debug(f"Failed to bulk log files: {e}")
    
    def reconstruct_blocks(self, phase: str, file_threshold: int = 500, byte_threshold: int = 50_000_000) -> int:
        """Reconstruct blocks from ingest_log entries for a completed phase.
        
        Called automatically after log_phase_delta() or log_phase_delta_ingest()
        to create ingest_blocks records. Only processes log entries not yet 
        assigned to a block.
        
        Args:
            phase: Phase to process
            file_threshold: Max files per block (default 500)
            byte_threshold: Max bytes per block (default 50MB)
            
        Returns:
            Number of blocks created
        """
        import hashlib
        
        # Find the highest block number for this phase (to continue numbering)
        cursor = self.conn.execute("""
            SELECT COALESCE(MAX(block_number), 0) as max_block,
                   COALESCE(MAX(log_id_end), 0) as last_log_id
            FROM ingest_blocks
            WHERE build_id = ? AND phase = ?
        """, (self.build_id, phase))
        row = cursor.fetchone()
        start_block_number = (row['max_block'] or 0) + 1
        last_processed_log_id = row['last_log_id'] or 0
        
        # Fetch only NEW log entries (after the last processed log_id)
        cursor = self.conn.execute("""
            SELECT log_id, timestamp, relpath, status, size_raw, size_stored, content_hash
            FROM ingest_log
            WHERE build_id = ? AND phase = ? AND log_id > ?
            ORDER BY log_id
        """, (self.build_id, phase, last_processed_log_id))
        
        logs = cursor.fetchall()
        if not logs:
            return 0
        
        # Chunk into blocks
        blocks = []
        current_block = []
        current_bytes = 0
        
        for log in logs:
            current_block.append(log)
            current_bytes += log['size_raw'] or 0
            
            if len(current_block) >= file_threshold or current_bytes >= byte_threshold:
                blocks.append(current_block)
                current_block = []
                current_bytes = 0
        
        # Don't forget the last partial block
        if current_block:
            blocks.append(current_block)
        
        # Create block records
        for i, block_logs in enumerate(blocks):
            block_number = start_block_number + i
            # Compute Merkle root from content hashes
            hashes = [log['content_hash'] for log in block_logs if log['content_hash']]
            if hashes:
                # Simple Merkle: hash of concatenated hashes
                combined = ''.join(sorted(hashes))
                block_hash = hashlib.sha256(combined.encode()).hexdigest()[:32]
            else:
                block_hash = None
            
            # Aggregate stats
            files_processed = sum(1 for l in block_logs if l['status'] == 'processed')
            files_skipped = sum(1 for l in block_logs if l['status'].startswith('skipped'))
            files_errored = sum(1 for l in block_logs if l['status'] == 'error')
            bytes_scanned = sum(l['size_raw'] or 0 for l in block_logs)
            bytes_stored = sum(l['size_stored'] or 0 for l in block_logs)
            
            # Timing
            started_at = block_logs[0]['timestamp']
            ended_at = block_logs[-1]['timestamp']
            duration_sec = ended_at - started_at
            
            block_id = f"blk-{self.build_id[:8]}-{phase[:4]}-{block_number:03d}"
            
            try:
                self.conn.execute("""
                    INSERT INTO ingest_blocks
                    (block_id, build_id, phase, block_number, started_at, ended_at, duration_sec,
                     files_processed, files_skipped, files_errored, bytes_scanned, bytes_stored,
                     block_hash, log_id_start, log_id_end)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    block_id, self.build_id, phase, block_number, started_at, ended_at, duration_sec,
                    files_processed, files_skipped, files_errored, bytes_scanned, bytes_stored,
                    block_hash, block_logs[0]['log_id'], block_logs[-1]['log_id']
                ))
            except Exception as e:
                self.logger.warning(f"Failed to create block {block_id}: {e}")
        
        try:
            self.conn.commit()
        except Exception:
            pass
        
        return len(blocks)
    
    def get_phase_errors(self, phase: str, limit: int = 50) -> list:
        """Get error entries from a phase for reporting.
        
        Returns:
            List of dicts with relpath, error_type, error_msg
        """
        cursor = self.conn.execute("""
            SELECT relpath, error_type, error_msg
            FROM ingest_log
            WHERE build_id = ? AND phase = ? AND status = 'error'
            ORDER BY log_id
            LIMIT ?
        """, (self.build_id, phase, limit))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def log_phase_delta_ingest(self, phase: str) -> int:
        """Log files ingested during ingest phases by querying what's new in the DB.
        
        For 'vanilla_ingest' and 'mod_ingest' phases, logs files from files table
        that were just ingested (created during this build).
        
        Returns:
            Number of files logged
        """
        # Get files that were added/updated during this build
        # We look at files table entries based on content_versions ingested_at
        cursor = self.conn.execute("""
            SELECT f.file_id, f.relpath, f.content_version_id, f.content_hash,
                   fc.size as size_raw
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE f.deleted = 0
              AND NOT EXISTS (
                  SELECT 1 FROM ingest_log il 
                  WHERE il.build_id = ? AND il.phase = ? AND il.file_id = f.file_id
              )
        """, (self.build_id, phase))
        
        rows = cursor.fetchall()
        if not rows:
            return 0
        
        entries = [{
            'file_id': row['file_id'],
            'relpath': row['relpath'],
            'content_version_id': row['content_version_id'],
            'status': 'processed',
            'size_raw': row['size_raw'],
            'content_hash': row['content_hash'],
        } for row in rows]
        
        self.log_files_bulk(phase, entries)
        return len(entries)
    
    # Phase configurations for log_phase_delta()
    # Each config defines how to query derived data for that phase
    PHASE_CONFIGS = {
        'ast_generation': {
            'table': 'asts',
            'alias': 'a',
            'join_col': 'content_hash',
            'join_type': 'content_hash',  # JOIN on f.content_hash = a.content_hash
            'count_col': 'ast_id',
            'where': 'a.parse_ok = 1',
            'size_stored_expr': 'LENGTH(a.ast_blob)',
            'needs_group_by': False,
        },
        'symbol_extraction': {
            'table': 'symbols',
            'alias': 's',
            'join_col': 'defining_file_id',
            'join_type': 'file_id',  # JOIN on f.file_id = s.defining_file_id
            'count_col': 'symbol_id',
            'where': None,
            'size_stored_expr': None,  # Will use COUNT
            'needs_group_by': True,
        },
        'ref_extraction': {
            'table': 'refs',
            'alias': 'r',
            'join_col': 'using_file_id',
            'join_type': 'file_id',
            'count_col': 'ref_id',
            'where': None,
            'size_stored_expr': None,
            'needs_group_by': True,
        },
        'localization_parsing': {
            'table': 'localization_entries',
            'alias': 'l',
            'join_col': 'content_hash',
            'join_type': 'content_hash',
            'count_col': 'loc_id',
            'where': None,
            'size_stored_expr': None,
            'needs_group_by': True,
        },
        'lookup_extraction': {
            'table': 'symbols',
            'alias': 's',
            'join_col': 'defining_file_id',
            'join_type': 'file_id',
            'count_col': 'symbol_id',
            'where': "s.symbol_type IN ('trait', 'event', 'decision', 'dynasty', 'house', 'religion', 'faith', 'culture', 'culture_pillar')",
            'size_stored_expr': None,
            'needs_group_by': True,
        },
    }
    
    def log_phase_delta(self, phase: str) -> int:
        """Log files processed during a build phase by querying derived data.
        
        This is a unified function that handles all phases that produce derived
        data (ASTs, symbols, refs, localization, lookups). For ingest phases,
        use log_phase_delta_ingest() instead.
        
        The function queries the appropriate derived table to find files that
        have been processed but not yet logged for this phase/build.
        
        Args:
            phase: Phase name. Must be one of:
                - ast_generation
                - symbol_extraction
                - ref_extraction
                - localization_parsing
                - lookup_extraction
        
        Returns:
            Number of files logged
            
        Raises:
            ValueError: If phase is not in PHASE_CONFIGS
        """
        config = self.PHASE_CONFIGS.get(phase)
        if not config:
            raise ValueError(
                f"Unknown phase '{phase}'. Use log_phase_delta_ingest() for ingest phases, "
                f"or add config to PHASE_CONFIGS. Valid phases: {list(self.PHASE_CONFIGS.keys())}"
            )
        
        table = config['table']
        alias = config['alias']
        join_col = config['join_col']
        count_col = config['count_col']
        where_clause = config.get('where') or ''
        size_stored_expr = config.get('size_stored_expr')
        needs_group_by = config.get('needs_group_by', False)
        
        # Build JOIN expression
        if config['join_type'] == 'file_id':
            join_expr = f"f.file_id = {alias}.{join_col}"
        else:  # content_hash
            join_expr = f"f.content_hash = {alias}.{join_col}"
        
        # Build size_stored expression (either explicit or COUNT)
        if size_stored_expr:
            stored_select = f"{size_stored_expr} as size_stored"
        else:
            stored_select = f"COUNT({alias}.{count_col}) as size_stored"
        
        # Build WHERE clause
        where_parts = [
            f"""NOT EXISTS (
                SELECT 1 FROM ingest_log il 
                WHERE il.build_id = ? AND il.phase = ? AND il.file_id = f.file_id
            )"""
        ]
        if where_clause:
            where_parts.append(where_clause)
        
        full_where = " AND ".join(where_parts)
        group_by = "GROUP BY f.file_id" if needs_group_by else ""
        
        sql = f"""
            SELECT f.file_id, f.relpath, f.content_version_id, f.content_hash,
                   LENGTH(COALESCE(fc.content_blob, '')) as size_raw,
                   {stored_select}
            FROM files f
            JOIN {table} {alias} ON {join_expr}
            LEFT JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE {full_where}
            {group_by}
        """
        
        cursor = self.conn.execute(sql, (self.build_id, phase))
        rows = cursor.fetchall()
        if not rows:
            return 0
        
        entries = [{
            'file_id': row['file_id'],
            'relpath': row['relpath'],
            'content_version_id': row['content_version_id'],
            'status': 'processed',
            'size_raw': row['size_raw'],
            'size_stored': row['size_stored'],
            'content_hash': row['content_hash'],
        } for row in rows]
        
        self.log_files_bulk(phase, entries)
        return len(entries)


def write_heartbeat():
    """Write current timestamp to heartbeat file."""
    try:
        HEARTBEAT_FILE.write_text(str(time.time()))
    except Exception:
        pass


def is_daemon_running() -> bool:
    """Check if daemon is already running."""
    if not PID_FILE.exists():
        return False
    
    try:
        pid = int(PID_FILE.read_text().strip())
        # Check if process exists (Windows-compatible)
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            # Also check heartbeat freshness (process might be hung)
            if HEARTBEAT_FILE.exists():
                last_heartbeat = float(HEARTBEAT_FILE.read_text().strip())
                if time.time() - last_heartbeat > 120:  # 2 minutes stale
                    return False  # Daemon is hung
            return True
        return False
    except Exception:
        return False


def acquire_exclusive_lock() -> bool:
    """
    Acquire exclusive lock to prevent multiple daemon instances.
    
    Uses a lockfile with exclusive access. This is more robust than just
    PID checking because:
    1. The lock is held by the OS, not just a file we created
    2. If the process crashes, the OS releases the lock automatically
    3. Prevents race conditions between checking and starting
    
    Returns:
        True if lock acquired, False if another instance is running
    """
    import msvcrt
    
    try:
        # Open lockfile for exclusive access
        lock_fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR)
        
        try:
            # Try to acquire exclusive lock (non-blocking)
            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
            
            # Write our PID to the lock file
            os.write(lock_fd, str(os.getpid()).encode())
            os.fsync(lock_fd)
            
            # Keep the file descriptor open (held until process exits)
            # Store in module global so it doesn't get garbage collected
            global _lock_fd
            _lock_fd = lock_fd
            return True
            
        except (IOError, OSError):
            # Lock is held by another process
            os.close(lock_fd)
            return False
            
    except Exception as e:
        print(f"Lock acquisition error: {e}")
        return False


def release_exclusive_lock():
    """Release the exclusive lock if we hold it."""
    global _lock_fd
    try:
        if '_lock_fd' in globals() and _lock_fd is not None:
            import msvcrt
            try:
                msvcrt.locking(_lock_fd, msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            os.close(_lock_fd)
            _lock_fd = None
    except Exception:
        pass


# Module global for lock file descriptor
_lock_fd = None


def write_pid():
    """Write current process PID."""
    PID_FILE.write_text(str(os.getpid()))


def cleanup_pid():
    """Remove PID file and release lock."""
    try:
        PID_FILE.unlink(missing_ok=True)
        release_exclusive_lock()
    except Exception:
        pass


def run_rebuild(db_path: Path, force: bool, logger: DaemonLogger, status: StatusWriter, symbols_only: bool = False, vanilla_path: str = None, skip_mods: bool = False, use_active_playset: bool = True, incremental: bool = True, dry_run: bool = False, check_file_changes: bool = True):
    """Main rebuild logic - runs in the detached process.
    
    Args:
        db_path: Path to the SQLite database
        force: If True, clear all data and rebuild from scratch
        logger: DaemonLogger instance
        status: StatusWriter instance
        symbols_only: If True, skip ingest and only re-extract symbols/refs
        vanilla_path: Optional custom path to vanilla CK3 files
        skip_mods: If True, skip mod ingestion (vanilla only)
        use_active_playset: If True, only ingest mods from active playset
        incremental: If True, only process mods/files that need updating (default)
        dry_run: If True, only report what would be done without making changes
        check_file_changes: If True, check for changed files in already-indexed mods (default True)
    """
    
    status.update(state="starting", started_at=datetime.now().isoformat())
    write_heartbeat()
    
    # Add the ck3raven package to path
    src_path = Path(__file__).parent.parent / "src"
    if src_path.exists():
        sys.path.insert(0, str(src_path))
    
    # Add the ck3raven project root to path (for builder package)
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    
    build_tracker = None
    
    try:
        # Import after path setup
        from ck3raven.db.schema import init_database, get_connection
        from ck3raven.db.ingest import ingest_vanilla, ingest_mod
        
        logger.info(f"Starting rebuild with db={db_path}, force={force}, symbols_only={symbols_only}")
        
        # Connect with retry logic
        db_wrapper = DatabaseWrapper(db_path, logger)
        
        status.update(state="connecting", message="Connecting to database...")
        write_heartbeat()
        
        # Initialize schema first (this creates tables if needed)
        logger.info("Initializing database schema...")
        init_database(db_path)
        
        conn = db_wrapper.connect()
        
        # Initialize build tracking
        build_tracker = BuildTracker(
            conn, logger, 
            vanilla_path=str(vanilla_path) if vanilla_path else None,
            playset_id=None,
            force=force
        )
        
        # Acquire build lock
        if not build_tracker.acquire_lock():
            raise RuntimeError("Failed to acquire build lock - another build may be in progress")
        
        if force and not symbols_only:
            status.update(state="clearing", message="Clearing existing data...")
            write_heartbeat()
            logger.info("Force mode: clearing tables...")
            
            for table in ["symbols", "refs", "files", "file_contents", "content_versions", 
                          "builder_steps", "trait_lookups", "event_lookups", "decision_lookups"]:
                try:
                    conn.execute(f"DELETE FROM {table}")
                    logger.debug(f"Cleared table: {table}")
                except Exception as e:
                    logger.debug(f"Table {table} clear skipped: {e}")
            
            logger.info("Tables cleared")
        
        # Aggregate counts for final manifest
        build_counts = {
            'files': 0, 'asts': 0, 'symbols': 0, 
            'refs': 0, 'localization': 0, 'lookups': 0
        }
        
        if not symbols_only:
            # Phase 1: Vanilla ingest
            build_tracker.start_step("vanilla_ingest")
            status.update(
                state="running",
                phase="vanilla_ingest",
                phase_number=1,
                message="Ingesting vanilla CK3 files..."
            )
            write_heartbeat()
            build_tracker.update_lock_heartbeat()
            
            if vanilla_path:
                vanilla_path = Path(vanilla_path).resolve()
            else:
                # Use config for default path
                from builder.config import get_config
                config = get_config()
                vanilla_path = config.vanilla_path
            if not vanilla_path.exists():
                raise RuntimeError(f"Vanilla path not found: {vanilla_path}")
            
            logger.info(f"Ingesting vanilla from {vanilla_path}")
            
            # Use chunked ingest with progress reporting and periodic block logging
            version, result = ingest_vanilla_chunked(conn, vanilla_path, "1.18.x", logger, status, build_tracker)
            
            vanilla_files = result.stats.files_scanned if hasattr(result, 'stats') else 0
            build_counts['files'] += vanilla_files
            
            logger.info(f"Vanilla ingest complete: {result}")
            status.update(stats={"vanilla_files": vanilla_files})
            
            # Final log of any remaining files and create final blocks
            logged = build_tracker.log_phase_delta_ingest("vanilla_ingest")
            if logged > 0:
                blocks = build_tracker.reconstruct_blocks(phase="vanilla_ingest")
                logger.info(f"Final: logged {logged} vanilla files -> {blocks} blocks")
            
            build_tracker.end_step("vanilla_ingest", StepStats(rows_out=vanilla_files))
            
            # Checkpoint after vanilla
            db_wrapper.checkpoint()
            write_heartbeat()
            
            # Phase 2: Mod ingest - playset mods only if playset_file provided, else ALL mods
            if not skip_mods:
                build_tracker.start_step("mod_ingest")
                if use_active_playset:
                    status.update(
                        phase="mod_ingest",
                        phase_number=2,
                        message="Ingesting active playset mods..."
                    )
                else:
                    status.update(
                        phase="mod_ingest",
                        phase_number=2,
                        message="Ingesting all discovered mods..."
                    )
                write_heartbeat()
                build_tracker.update_lock_heartbeat()

                # Use incremental mode unless force or full-rebuild is set
                use_incremental = incremental and not force
                mod_files = ingest_all_mods(
                    conn, logger, status, 
                    use_active_playset=use_active_playset,
                    incremental=use_incremental,
                    dry_run=dry_run,
                    check_file_changes=check_file_changes
                )
                build_counts['files'] += mod_files if isinstance(mod_files, int) else 0
                mod_file_count = mod_files if isinstance(mod_files, int) else 0
                
                # Log ingested files and reconstruct blocks immediately
                logged = build_tracker.log_phase_delta_ingest("mod_ingest")
                if logged > 0:
                    blocks = build_tracker.reconstruct_blocks(phase="mod_ingest")
                    logger.info(f"Logged {logged} mod files -> {blocks} blocks")
                
                build_tracker.end_step("mod_ingest", StepStats(rows_out=mod_file_count))
                db_wrapper.checkpoint()
            else:
                build_tracker.skip_step("mod_ingest", "test mode with skip_mods=True")
                logger.info("Skipping mod ingestion (test mode with skip_mods=True)")
        else:
            # symbols_only mode - skip ingest phases, go straight to symbols/refs
            build_tracker.skip_step("vanilla_ingest", "symbols_only mode")
            build_tracker.skip_step("mod_ingest", "symbols_only mode")
            logger.info("Symbols-only mode: skipping ingest, extracting symbols incrementally...")
        
        # Phase 3: AST generation - parse files and store ASTs
        build_tracker.start_step("ast_generation")
        status.update(
            phase="ast_generation",
            phase_number=3,
            message="Generating ASTs..."
        )
        write_heartbeat()
        build_tracker.update_lock_heartbeat()
        
        ast_stats = generate_missing_asts(conn, logger, status, force=force)
        ast_count = ast_stats.get('generated', 0) if isinstance(ast_stats, dict) else 0
        build_counts['asts'] = ast_count
        
        # Log AST generation results and reconstruct blocks immediately
        logged = build_tracker.log_phase_delta("ast_generation")
        if logged > 0:
            blocks = build_tracker.reconstruct_blocks(phase="ast_generation")
            logger.info(f"Logged {logged} AST files -> {blocks} blocks")
        
        build_tracker.end_step("ast_generation", StepStats(
            rows_out=ast_count,
            rows_skipped=ast_stats.get('skipped', 0) if isinstance(ast_stats, dict) else 0,
            rows_errored=ast_stats.get('errors', 0) if isinstance(ast_stats, dict) else 0
        ))
        db_wrapper.checkpoint()
        
        # Phases 4-7 write to protected tables (symbols, refs, lookups, localization)
        # These require an active builder session
        from ck3raven.db.schema import BuilderSession
        
        with BuilderSession(conn, purpose="daemon rebuild phases 4-7", ttl_minutes=120):
            # Phase 4: Symbol extraction from stored ASTs
            build_tracker.start_step("symbol_extraction")
            status.update(
                phase="symbol_extraction", 
                phase_number=4,
                message="Extracting symbols..."
            )
            write_heartbeat()
            build_tracker.update_lock_heartbeat()
            
            symbol_stats = extract_symbols_from_stored_asts(conn, logger, status)
            symbol_count = symbol_stats.get('extracted', 0) if isinstance(symbol_stats, dict) else 0
            build_counts['symbols'] = symbol_count
            
            # Log symbol extraction results and reconstruct blocks immediately
            logged = build_tracker.log_phase_delta("symbol_extraction")
            if logged > 0:
                blocks = build_tracker.reconstruct_blocks(phase="symbol_extraction")
                logger.info(f"Logged {logged} files with symbols -> {blocks} blocks")
            
            build_tracker.end_step("symbol_extraction", StepStats(rows_out=symbol_count))
            db_wrapper.checkpoint()
            
            # Phase 5: Ref extraction from stored ASTs
            build_tracker.start_step("ref_extraction")
            status.update(
                phase="ref_extraction",
                phase_number=5, 
                message="Extracting references..."
            )
            write_heartbeat()
            build_tracker.update_lock_heartbeat()
            
            ref_stats = extract_refs_from_stored_asts(conn, logger, status)
            ref_count = ref_stats.get('extracted', 0) if isinstance(ref_stats, dict) else 0
            build_counts['refs'] = ref_count
            
            # Log ref extraction results and reconstruct blocks immediately
            logged = build_tracker.log_phase_delta("ref_extraction")
            if logged > 0:
                blocks = build_tracker.reconstruct_blocks(phase="ref_extraction")
                logger.info(f"Logged {logged} files with refs -> {blocks} blocks")
            
            build_tracker.end_step("ref_extraction", StepStats(rows_out=ref_count))
            db_wrapper.checkpoint()
            
            # Phase 6: Localization parsing
            build_tracker.start_step("localization_parsing")
            status.update(
                phase="localization_parsing",
                phase_number=6,
                message="Parsing localization files..."
            )
            write_heartbeat()
            build_tracker.update_lock_heartbeat()
            
            loc_stats = parse_localization_files(conn, logger, status, force=force)
            loc_count = loc_stats.get('entries', 0) if isinstance(loc_stats, dict) else 0
            build_counts['localization'] = loc_count
            
            # Log localization parsing results and reconstruct blocks immediately
            logged = build_tracker.log_phase_delta("localization_parsing")
            if logged > 0:
                blocks = build_tracker.reconstruct_blocks(phase="localization_parsing")
                logger.info(f"Logged {logged} loc files -> {blocks} blocks")
            
            build_tracker.end_step("localization_parsing", StepStats(rows_out=loc_count))
            db_wrapper.checkpoint()
            
            # Phase 7: Lookup table extraction (TBC - provisional)
            build_tracker.start_step("lookup_extraction")
            status.update(
                phase="lookup_extraction",
                phase_number=7,
                message="Extracting lookup tables..."
            )
            write_heartbeat()
            build_tracker.update_lock_heartbeat()
            
            lookup_stats = extract_lookup_tables(conn, logger, status)
            lookup_count = lookup_stats.get('total', 0) if isinstance(lookup_stats, dict) else 0
            build_counts['lookups'] = lookup_count
            
            # Log lookup extraction results and reconstruct blocks immediately
            logged = build_tracker.log_phase_delta("lookup_extraction")
            if logged > 0:
                blocks = build_tracker.reconstruct_blocks(phase="lookup_extraction")
                logger.info(f"Logged {logged} files with lookups -> {blocks} blocks")
            
            build_tracker.end_step("lookup_extraction", StepStats(rows_out=lookup_count))
            db_wrapper.checkpoint()
        
        # Process any pending file refreshes from MCP writes during build
        pending_count = _process_pending_refreshes(conn, logger, status)
        if pending_count > 0:
            build_counts['pending_refreshed'] = pending_count
            db_wrapper.checkpoint()
        
        # Done - record build completion
        # (blocks were already created after each phase via reconstruct_blocks)
        build_tracker.complete(build_counts)
        
        status.update(
            state="complete",
            phase="done",
            phase_number=8,
            progress=100.0,
            message="Rebuild complete!"
        )
        
        db_wrapper.close()
        logger.info("Rebuild completed successfully!")
        
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(f"Rebuild failed: {error_msg}")
        logger.error(traceback.format_exc())
        
        # Record build failure
        if build_tracker:
            build_tracker.fail(error_msg)
        
        status.update(
            state="error",
            error=error_msg,
            message=f"Failed: {error_msg}"
        )
        raise


def _process_pending_refreshes(conn, logger: DaemonLogger, status: StatusWriter) -> int:
    """Process any pending file refreshes queued during build.
    
    When MCP writes files while daemon is running, they're logged to
    pending_refresh.log instead of blocking. This processes that queue.
    
    Returns count of entries processed.
    """
    from builder.pending_refresh import read_and_clear_pending, has_pending
    from builder.incremental import refresh_single_file, mark_file_deleted
    
    if not has_pending():
        return 0
    
    entries = read_and_clear_pending()
    if not entries:
        return 0
    
    logger.info(f"Processing {len(entries)} pending file refresh(es)...")
    status.update(message=f"Processing {len(entries)} pending refreshes...")
    
    processed = 0
    for op, mod_name, rel_path in entries:
        try:
            if op == "DELETE":
                mark_file_deleted(conn, mod_name, rel_path)
            else:  # WRITE
                refresh_single_file(conn, mod_name, rel_path)
            processed += 1
        except Exception as e:
            logger.warning(f"Failed to refresh {mod_name}/{rel_path}: {e}")
    
    logger.info(f"Processed {processed}/{len(entries)} pending refreshes")
    return processed


def ingest_vanilla_chunked(conn, vanilla_path: Path, version: str, logger: DaemonLogger, status: StatusWriter, build_tracker: 'BuildTracker' = None):
    """Ingest vanilla files with progress reporting via callback.
    
    If build_tracker is provided, also logs ingested files and creates blocks
    periodically during the ingest.
    """
    from ck3raven.db.ingest import ingest_vanilla
    
    # Track how many files we've logged so far
    last_logged_count = [0]  # Use list to allow mutation in closure
    
    def progress_callback(done, total):
        write_heartbeat()
        if total > 0:
            pct = (done / total) * 100
            status.update(progress=pct, message=f"Vanilla ingest: {done}/{total} files ({pct:.1f}%)")
            if done % 5000 == 0:
                logger.info(f"Vanilla progress: {done}/{total} ({pct:.1f}%)")
            
            # Periodic block logging - every 5000 files
            if build_tracker and done >= last_logged_count[0] + 5000:
                logged = build_tracker.log_phase_delta_ingest("vanilla_ingest")
                if logged > 0:
                    blocks = build_tracker.reconstruct_blocks(phase="vanilla_ingest")
                    logger.debug(f"Block checkpoint: logged {logged} files -> {blocks} blocks")
                last_logged_count[0] = done
    
    # The updated ingest_vanilla now accepts progress_callback
    return ingest_vanilla(conn, vanilla_path, version, progress_callback=progress_callback)


# =============================================================================
# MOD DISCOVERY AND INGESTION
# =============================================================================

def load_mods_from_active_playset(logger: DaemonLogger) -> List[Dict]:
    """
    Load mod list from the ACTIVE playset (canonical source).
    
    Reads from playsets/playset_manifest.json to get active playset name,
    then loads mods[] from playsets/{active}.json.
    
    Returns list of dicts: {name, path, workshop_id, load_order}
    """
    import json
    
    # Step 1: Read manifest to get active playset
    if not PLAYSET_MANIFEST.exists():
        logger.error(f"Playset manifest not found: {PLAYSET_MANIFEST}")
        logger.info("Run 'ck3_playset switch' to set an active playset")
        return []
    
    try:
        manifest = json.loads(PLAYSET_MANIFEST.read_text(encoding='utf-8'))
    except Exception as e:
        logger.error(f"Failed to parse manifest: {e}")
        return []
    
    active_filename = manifest.get('active')
    if not active_filename:
        logger.error("No active playset set in manifest")
        logger.info("Run 'ck3_playset switch' to set an active playset")
        return []
    
    # Step 2: Load the active playset file
    playset_path = PLAYSETS_DIR / active_filename
    if not playset_path.exists():
        logger.error(f"Active playset file not found: {playset_path}")
        return []
    
    try:
        data = json.loads(playset_path.read_text(encoding='utf-8'))
    except Exception as e:
        logger.error(f"Failed to parse playset: {e}")
        return []
    
    playset_name = data.get('playset_name', 'Unknown')
    
    # CANONICAL: Use 'mods' key only. Legacy 'paths' format is BANNED.
    mod_entries = data.get('mods', [])
    if not mod_entries:
        logger.warning(f"Playset '{playset_name}' has no mods")
        return []
    
    mods = []
    for entry in mod_entries:
        if not entry.get('enabled', True):
            continue  # Skip disabled mods
        
        mod_path = Path(entry.get('path', ''))
        if not mod_path.exists():
            logger.warning(f"Mod path not found: {mod_path}")
            continue
        
        mods.append({
            "name": entry.get('name', mod_path.name),
            "path": mod_path,
            "workshop_id": entry.get('steam_id') or None,
            "load_order": entry.get('load_order', 999)
        })
    
    # Sort by load order
    mods.sort(key=lambda m: m.get('load_order', 999))
    
    workshop_count = sum(1 for m in mods if m['workshop_id'])
    local_count = len(mods) - workshop_count
    logger.info(f"Active playset: '{playset_name}' with {len(mods)} mods ({workshop_count} workshop, {local_count} local)")
    
    return mods


def discover_all_mods(logger: DaemonLogger) -> List[Dict]:
    """
    Discover all mods from Steam Workshop and local mods folders.
    
    Returns list of dicts: {name, path, workshop_id}
    """
    from builder.config import get_config
    config = get_config()
    
    mods = []
    
    # Steam Workshop mods
    workshop_base = config.workshop_path
    if workshop_base.exists():
        for mod_dir in workshop_base.iterdir():
            if mod_dir.is_dir():
                workshop_id = mod_dir.name
                # Try to get name from descriptor
                descriptor = mod_dir / "descriptor.mod"
                name = f"Workshop_{workshop_id}"  # Default
                if descriptor.exists():
                    try:
                        content = descriptor.read_text(encoding='utf-8', errors='ignore')
                        for line in content.splitlines():
                            if line.strip().startswith('name='):
                                name = line.split('=', 1)[1].strip().strip('"')
                                break
                    except Exception:
                        pass
                mods.append({
                    "name": name,
                    "path": mod_dir,
                    "workshop_id": workshop_id
                })
    else:
        logger.warning(f"Workshop path not found: {workshop_base}")
    
    # Local mods
    local_mods_base = config.local_mods_path
    if local_mods_base.exists():
        for item in local_mods_base.iterdir():
            # Only directories that look like mod folders
            if item.is_dir() and not item.name.endswith('.mod'):
                # Check if it has actual mod content (descriptor or common folder)
                has_descriptor = (item / "descriptor.mod").exists()
                has_common = (item / "common").exists()
                has_events = (item / "events").exists()
                has_localization = (item / "localization").exists()
                
                if has_descriptor or has_common or has_events or has_localization:
                    name = item.name
                    # Try to get name from descriptor
                    descriptor = item / "descriptor.mod"
                    if descriptor.exists():
                        try:
                            content = descriptor.read_text(encoding='utf-8', errors='ignore')
                            for line in content.splitlines():
                                if line.strip().startswith('name='):
                                    name = line.split('=', 1)[1].strip().strip('"')
                                    break
                        except Exception:
                            pass
                    mods.append({
                        "name": name,
                        "path": item,
                        "workshop_id": None  # Local mod
                    })
    else:
        logger.warning(f"Local mods path not found: {local_mods_base}")
    
    logger.info(f"Discovered {len(mods)} mods ({sum(1 for m in mods if m['workshop_id'])} workshop, {sum(1 for m in mods if not m['workshop_id'])} local)")
    return mods


def ingest_all_mods(conn, logger: DaemonLogger, status: StatusWriter, use_active_playset: bool = True, incremental: bool = True, dry_run: bool = False, check_file_changes: bool = True):
    """Ingest mods with progress tracking.
    
    If use_active_playset is True (default), ingest mods from active playset.
    Otherwise, discover and ingest ALL mods from workshop + local.
    
    If incremental is True (default), only ingest mods that need processing.
    If dry_run is True, only report what would be done without making changes.
    If check_file_changes is True (default), detect changed files in already-indexed mods.
    """
    from ck3raven.db.ingest import ingest_mod
    from builder.incremental import get_mods_needing_rebuild
    
    if use_active_playset:
        mods = load_mods_from_active_playset(logger)
    else:
        mods = discover_all_mods(logger)
    
    if not mods:
        logger.warning("No mods found to ingest")
        return
    
    # Check which mods need processing (incremental mode)
    if incremental:
        rebuild_info = get_mods_needing_rebuild(conn, mods, check_file_changes=check_file_changes)
        
        logger.info(f"Incremental check: {rebuild_info['summary']}")
        logger.info(f"  - New mods: {len(rebuild_info['mods_needing_ingest'])}")
        logger.info(f"  - Need symbols: {len(rebuild_info['mods_needing_symbols'])}")
        logger.info(f"  - Already ready: {len(rebuild_info['mods_ready'])}")
        
        if rebuild_info['mods_missing']:
            for m in rebuild_info['mods_missing']:
                logger.warning(f"  - Missing on disk: {m['name']} ({m['path']})")
        
        if dry_run:
            logger.info("DRY RUN: Would ingest the following mods:")
            for m in rebuild_info['mods_needing_ingest']:
                logger.info(f"  - {m['name']} (new mod)")
            for m in rebuild_info['mods_needing_symbols']:
                logger.info(f"  - {m['name']} (needs symbols)")
            return
        
        if not rebuild_info['needs_rebuild']:
            logger.info("All mods already processed - nothing to do")
            return
        
        # Only ingest mods that need it
        mods_to_ingest = rebuild_info['mods_needing_ingest']
        mods_for_symbols = rebuild_info['mods_needing_symbols']
        
        # Store mods_for_symbols for symbol extraction phase
        status.update(progress=0, message=f"Incremental: {len(mods_to_ingest)} mods to ingest")
    else:
        # Full rebuild - ingest all mods
        mods_to_ingest = mods
        mods_for_symbols = []
    
    total = len(mods_to_ingest)
    if total == 0:
        logger.info("No new mods to ingest (some may need symbol extraction only)")
        return
    
    ingested = 0
    skipped = 0
    errors = 0
    total_files = 0
    
    for i, mod in enumerate(mods_to_ingest):
        write_heartbeat()
        
        # Handle mod dict format from get_mods_needing_rebuild
        if 'path' in mod and isinstance(mod['path'], str):
            mod_path = Path(mod['path'])
        else:
            mod_path = mod.get('path', mod)
        mod_name = mod.get('name', 'Unknown')
        workshop_id = mod.get('workshop_id')
        
        pct = ((i + 1) / total) * 100
        status.update(
            progress=pct,
            message=f"Mod ingest: {i+1}/{total} - {mod_name[:30]}"
        )
        
        try:
            mod_package, result = ingest_mod(
                conn=conn,
                mod_path=mod_path,
                name=mod_name,
                workshop_id=workshop_id,
                force=False  # Rely on content hash for dedup
            )
            
            files_added = result.stats.files_new if hasattr(result, 'stats') else 0
            total_files += files_added
            ingested += 1
            
            if i % 20 == 0:
                logger.info(f"Mod {i+1}/{total}: {mod_name} - {files_added} files")
                conn.commit()  # Commit every 20 mods
            
        except Exception as e:
            errors += 1
            logger.warning(f"Failed to ingest mod {mod_name}: {e}")
    
    conn.commit()
    logger.info(f"Mod ingest complete: {ingested} mods, {total_files} files, {errors} errors")


# =============================================================================
# AST GENERATION AND STORAGE
# =============================================================================

def get_or_create_parser_version(conn, version_string: str = "1.0.0") -> int:
    """Get or create a parser version record."""
    row = conn.execute(
        "SELECT parser_version_id FROM parsers WHERE version_string = ?",
        (version_string,)
    ).fetchone()
    
    if row:
        return row[0]
    
    cursor = conn.execute(
        "INSERT INTO parsers (version_string, description) VALUES (?, ?)",
        (version_string, "CK3 Parser v1.0")
    )
    conn.commit()
    return cursor.lastrowid


def generate_missing_asts(conn, logger: DaemonLogger, status: StatusWriter, force: bool = False):
    """
    Parse files and store ASTs in the database.
    
    If force=True, clears all ASTs and regenerates.
    Otherwise, only generates ASTs for files missing them.
    """
    from ck3raven.parser import parse_source
    import json
    
    parser_version_id = get_or_create_parser_version(conn)
    
    if force:
        logger.info("Force mode: clearing all ASTs...")
        conn.execute("DELETE FROM asts")
        conn.commit()
    
    # Find files that need AST generation
    # A file needs AST if:
    # 1. Its content_hash doesn't have an AST entry for this parser version
    # 2. It's a .txt file (CK3 script) or .yml file (localization)
    
    # Skip files larger than 5MB - they're usually generated data or massive title files
    # that take too long to parse and aren't useful for symbol extraction
    MAX_FILE_SIZE = 5_000_000
    
    query = """
        SELECT DISTINCT fc.content_hash, fc.content_text, f.relpath
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        LEFT JOIN asts a ON fc.content_hash = a.content_hash 
            AND a.parser_version_id = ?
        WHERE f.deleted = 0
        AND f.relpath LIKE '%.txt'
        AND f.relpath NOT LIKE 'localization/%'
        AND fc.content_text IS NOT NULL
        AND a.ast_id IS NULL
        AND LENGTH(fc.content_text) < ?
        -- Exclude non-script paths at SQL level for efficiency
        AND f.relpath NOT LIKE 'gfx/%'
        AND f.relpath NOT LIKE 'common/ethnicities/%'
        AND f.relpath NOT LIKE 'common/dna_data/%'
        AND f.relpath NOT LIKE 'common/coat_of_arms/%'
        AND f.relpath NOT LIKE 'history/characters/%'
        AND f.relpath NOT LIKE '%/names/character_names%'
        AND f.relpath NOT LIKE '%_names_l_%'
    """
    
    # First count
    count_query = f"""
        SELECT COUNT(DISTINCT fc.content_hash)
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        LEFT JOIN asts a ON fc.content_hash = a.content_hash 
            AND a.parser_version_id = ?
        WHERE f.deleted = 0
        AND f.relpath LIKE '%.txt'
        AND f.relpath NOT LIKE 'localization/%'
        AND LENGTH(fc.content_text) < ?
        AND fc.content_text IS NOT NULL
        AND a.ast_id IS NULL
    """
    
    total_count = conn.execute(count_query, (parser_version_id, MAX_FILE_SIZE)).fetchone()[0]
    
    if total_count == 0:
        logger.info("All files already have ASTs - nothing to do")
        return {'generated': 0, 'skipped': 0, 'errors': 0}
    
    logger.info(f"Generating ASTs for {total_count} unique content hashes...")
    
    # Process in chunks
    chunk_size = 500
    processed = 0
    errors = 0
    
    # We need to process all results, so fetch in chunks via OFFSET
    offset = 0
    
    while True:
        write_heartbeat()
        
        rows = conn.execute(
            query + " LIMIT ? OFFSET ?",
            (parser_version_id, MAX_FILE_SIZE, chunk_size, offset)
        ).fetchall()
        
        if not rows:
            break
        
        for idx, (content_hash, content, relpath) in enumerate(rows):
            # Write heartbeat every 50 files to prevent stale detection
            if idx % 50 == 0:
                write_heartbeat()
            
            if not content or len(content) > 2_000_000:
                continue
            
            # Skip non-script files (graphics data, generated content, etc.)
            # Only common/, events/, history/, localization/, gui/ are CK3 script folders
            skip_patterns = [
                # Graphics and assets - NOT scripts
                'gfx/',           # ALL graphics - tree transforms, cameras, meshes
                '/fonts/', '/licenses/', '/sounds/', '/music/',
                
                # Generated/backup content
                '#backup/', '/generated/',
                'guids.txt', 'credits.txt', 'readme', 'changelog',
                'checksum', '.dds', '.png', '.tga',
                
                # Portrait/DNA data - huge files with no useful symbols
                'common/ethnicities/',   # 3000+ portrait ethnicity files
                'common/dna_data/',      # DNA appearance data
                'common/coat_of_arms/',  # Procedural coat of arms
                'history/characters/',   # Massive character history files
                
                # Name databases - localization but no symbols
                'moreculturalnames', 'cultural_names_l_',
                '/names/character_names',  # Character name databases
                '_names_l_',  # Name localization files
            ]
            if any(skip in relpath.lower() for skip in skip_patterns):
                continue
            
            try:
                # Use timeout for parsing (some files can hang the parser)
                import signal
                import threading
                
                parse_result = [None]
                parse_error = [None]
                
                def parse_with_timeout():
                    try:
                        parse_result[0] = parse_source(content, relpath)
                    except Exception as e:
                        parse_error[0] = e
                
                parse_thread = threading.Thread(target=parse_with_timeout)
                parse_thread.daemon = True
                parse_thread.start()
                parse_thread.join(timeout=30)  # 30 second timeout per file
                
                if parse_thread.is_alive():
                    # Timeout - skip this file
                    errors += 1
                    if errors <= 30:
                        logger.warning(f"Parse timeout (30s) for {relpath}")
                    continue
                
                if parse_error[0]:
                    raise parse_error[0]
                
                ast = parse_result[0]
                
                if ast:
                    # Convert to dict/JSON
                    ast_dict = ast.to_dict() if hasattr(ast, 'to_dict') else ast
                    ast_json = json.dumps(ast_dict, separators=(',', ':'))
                    
                    # Count nodes (rough estimate from keys)
                    node_count = ast_json.count('{')
                    
                    conn.execute("""
                        INSERT OR REPLACE INTO asts
                        (content_hash, parser_version_id, ast_blob, ast_format, parse_ok, node_count)
                        VALUES (?, ?, ?, 'json', 1, ?)
                    """, (content_hash, parser_version_id, ast_json.encode('utf-8'), node_count))
                else:
                    # Parse returned None - store as failed
                    conn.execute("""
                        INSERT OR REPLACE INTO asts
                        (content_hash, parser_version_id, ast_blob, ast_format, parse_ok, diagnostics_json)
                        VALUES (?, ?, ?, 'json', 0, ?)
                    """, (content_hash, parser_version_id, b'null', json.dumps({"error": "Parse returned None"})))
                
                processed += 1
                
            except Exception as e:
                errors += 1
                # Store the error
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO asts
                        (content_hash, parser_version_id, ast_blob, ast_format, parse_ok, diagnostics_json)
                        VALUES (?, ?, ?, 'json', 0, ?)
                    """, (content_hash, parser_version_id, b'null', json.dumps({"error": str(e)[:500]})))
                except Exception:
                    pass
                
                if errors <= 20:
                    logger.warning(f"Parse error in {relpath}: {e}")
        
        conn.commit()
        offset += len(rows)
        
        pct = min(100, (offset / total_count) * 100)
        status.update(
            progress=pct,
            message=f"AST generation: {offset}/{total_count} ({pct:.1f}%)"
        )
        
        if offset % 2000 == 0:
            logger.info(f"AST progress: {offset}/{total_count} ({pct:.1f}%), {errors} errors")
    
    logger.info(f"AST generation complete: {processed} ASTs, {errors} errors")
    return {'generated': processed, 'skipped': total_count - processed - errors, 'errors': errors}


# =============================================================================
# LOCALIZATION PARSING
# =============================================================================

def parse_localization_files(conn, logger: DaemonLogger, status: StatusWriter, force: bool = False):
    """
    Parse localization files and store entries in localization_entries table.
    
    This handles .yml files in localization/ folders using the Paradox localization parser.
    Unlike AST generation, localization uses a different format (pseudo-YAML).
    
    If force=True, clears all localization entries and re-parses.
    Otherwise, only parses files that don't have entries yet.
    """
    from ck3raven.parser.localization import parse_localization, LocalizationFile
    
    parser_version_id = get_or_create_parser_version(conn)
    
    if force:
        logger.info("Force mode: clearing all localization entries...")
        conn.execute("DELETE FROM localization_entries")
        conn.execute("DELETE FROM localization_refs")
        conn.commit()
    
    # Find localization files that need parsing
    # A file needs parsing if:
    # 1. Its content_hash doesn't have localization entries for this parser version
    # 2. It's a .yml file in a localization folder
    
    query = """
        SELECT DISTINCT fc.content_hash, fc.content_text, f.relpath
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        LEFT JOIN localization_entries le ON fc.content_hash = le.content_hash 
            AND le.parser_version_id = ?
        WHERE f.deleted = 0
        AND (f.relpath LIKE 'localization/%%.yml' OR f.relpath LIKE '%/localization/%%.yml')
        AND fc.content_text IS NOT NULL
        AND le.loc_id IS NULL
    """
    
    # Count first
    count_query = """
        SELECT COUNT(DISTINCT fc.content_hash)
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        LEFT JOIN localization_entries le ON fc.content_hash = le.content_hash 
            AND le.parser_version_id = ?
        WHERE f.deleted = 0
        AND (f.relpath LIKE 'localization/%%.yml' OR f.relpath LIKE '%/localization/%%.yml')
        AND fc.content_text IS NOT NULL
        AND le.loc_id IS NULL
    """
    
    total_count = conn.execute(count_query, (parser_version_id,)).fetchone()[0]
    
    if total_count == 0:
        logger.info("All localization files already parsed - nothing to do")
        return {'files': 0, 'entries': 0, 'refs': 0, 'errors': 0}
    
    logger.info(f"Parsing {total_count} localization files...")
    
    # Process in chunks
    chunk_size = 100  # Smaller chunks since loc files can have many entries
    processed = 0
    total_entries = 0
    total_refs = 0
    errors = 0
    
    offset = 0
    
    while True:
        write_heartbeat()
        
        rows = conn.execute(
            query + " LIMIT ? OFFSET ?",
            (parser_version_id, chunk_size, offset)
        ).fetchall()
        
        if not rows:
            break
        
        for idx, (content_hash, content, relpath) in enumerate(rows):
            if idx % 20 == 0:
                write_heartbeat()
            
            if not content:
                continue
            
            try:
                # Parse the localization file
                result: LocalizationFile = parse_localization(content, relpath)
                
                # Insert entries
                for entry in result.entries:
                    # Insert the localization entry
                    cursor = conn.execute("""
                        INSERT INTO localization_entries
                        (content_hash, language, loc_key, version, raw_value, 
                         plain_text, line_number, parser_version_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        content_hash,
                        result.language,
                        entry.key,
                        entry.version,
                        entry.raw_value,
                        entry.plain_text,
                        entry.line_number,
                        parser_version_id
                    ))
                    
                    loc_id = cursor.lastrowid
                    total_entries += 1
                    
                    # Insert references (scripted, variable, icon)
                    for ref in entry.scripted_refs:
                        conn.execute("""
                            INSERT INTO localization_refs (loc_id, ref_type, ref_value)
                            VALUES (?, 'scripted', ?)
                        """, (loc_id, ref))
                        total_refs += 1
                    
                    for ref in entry.variable_refs:
                        conn.execute("""
                            INSERT INTO localization_refs (loc_id, ref_type, ref_value)
                            VALUES (?, 'variable', ?)
                        """, (loc_id, ref))
                        total_refs += 1
                    
                    for ref in entry.icon_refs:
                        conn.execute("""
                            INSERT INTO localization_refs (loc_id, ref_type, ref_value)
                            VALUES (?, 'icon', ?)
                        """, (loc_id, ref))
                        total_refs += 1
                
                processed += 1
                
            except Exception as e:
                errors += 1
                if errors <= 20:
                    logger.warning(f"Localization parse error in {relpath}: {e}")
        
        conn.commit()
        offset += len(rows)
        
        pct = min(100, (offset / total_count) * 100)
        status.update(
            progress=pct,
            message=f"Localization: {offset}/{total_count} files ({pct:.1f}%)"
        )
        
        if offset % 500 == 0:
            logger.info(f"Localization progress: {offset}/{total_count}, {total_entries} entries, {errors} errors")
    
    logger.info(f"Localization parsing complete: {processed} files, {total_entries} entries, {total_refs} refs, {errors} errors")
    return {'files': processed, 'entries': total_entries, 'refs': total_refs, 'errors': errors}


def extract_lookup_tables(conn, logger: DaemonLogger, status: StatusWriter):
    """
    Extract ID-keyed lookup data into denormalized tables.
    
    This is Phase 7: Lookup Extraction.
    
    Lookups are for OPAQUE NUMERIC IDs that need resolution to names:
    - province_lookup: province ID → name, RGB, culture, religion
    - character_lookup: character ID → name, dynasty, dates
    - dynasty_lookup: dynasty ID → name key, culture
    - title_lookup: title key → tier, capital, colors
    
    Note: traits, events, decisions are STRING-KEYED and use symbols table.
    """
    from pathlib import Path
    from builder.config import get_config
    
    logger.info("Starting ID-keyed lookup table extraction...")
    
    total_extracted = 0
    total_errors = 0
    results = {}
    
    # Get vanilla content_version_id
    vanilla_cv_row = conn.execute("""
        SELECT cv.content_version_id 
        FROM content_versions cv
        WHERE cv.kind = 'vanilla'
        ORDER BY cv.content_version_id DESC
        LIMIT 1
    """).fetchone()
    
    if not vanilla_cv_row:
        logger.warning("No vanilla content_version found, skipping lookups")
        return {'total': 0, 'errors': 0, 'status': 'no_vanilla'}
    
    vanilla_cv_id = vanilla_cv_row[0]
    config = get_config()
    vanilla_path = config.vanilla_path
    
    # 1. Province lookup (from definition.csv)
    write_heartbeat()
    status.update(message="Extracting province lookups from definition.csv...")
    try:
        from builder.extractors.lookups.province import extract_provinces
        stats = extract_provinces(conn, vanilla_path, vanilla_cv_id)
        logger.info(f"  provinces: inserted={stats['inserted']}, errors={stats['errors']}")
        results['provinces'] = stats
        total_extracted += stats['inserted']
        total_errors += stats['errors']
    except Exception as e:
        logger.warning(f"  province extraction failed: {e}")
        total_errors += 1
    
    # 2. Dynasty lookup (from common/dynasties/ ASTs)
    write_heartbeat()
    status.update(message="Extracting dynasty lookups...")
    try:
        from builder.extractors.lookups.dynasty import extract_dynasties
        stats = extract_dynasties(conn, vanilla_cv_id)
        logger.info(f"  dynasties: inserted={stats['inserted']}, errors={stats['errors']}")
        results['dynasties'] = stats
        total_extracted += stats['inserted']
        total_errors += stats['errors']
    except Exception as e:
        logger.warning(f"  dynasty extraction failed: {e}")
        total_errors += 1
    
    # 3. Character lookup (from history/characters/ ASTs)
    write_heartbeat()
    status.update(message="Extracting character lookups...")
    try:
        from builder.extractors.lookups.character import extract_characters
        stats = extract_characters(conn, vanilla_cv_id)
        logger.info(f"  characters: inserted={stats['inserted']}, errors={stats['errors']}")
        results['characters'] = stats
        total_extracted += stats['inserted']
        total_errors += stats['errors']
    except Exception as e:
        logger.warning(f"  character extraction failed: {e}")
        total_errors += 1
    
    # 4. Title lookup (from common/landed_titles/ ASTs)
    write_heartbeat()
    status.update(message="Extracting landed title lookups...")
    try:
        from builder.extractors.lookups.landed_titles import extract_landed_titles
        stats = extract_landed_titles(conn, vanilla_cv_id)
        logger.info(f"  landed_titles: inserted={stats['inserted']}, errors={stats['errors']}")
        results['landed_titles'] = stats
        total_extracted += stats['inserted']
        total_errors += stats['errors']
    except Exception as e:
        logger.warning(f"  landed_titles extraction failed: {e}")
        total_errors += 1
    
    logger.info(f"Lookup extraction complete: {total_extracted} records, {total_errors} errors")
    return {'total': total_extracted, 'errors': total_errors, 'details': results}

# =============================================================================
# SYMBOL/REF EXTRACTION FROM STORED ASTs
# =============================================================================

def extract_symbols_from_stored_asts(conn, logger: DaemonLogger, status: StatusWriter, force_rebuild: bool = False):
    """Extract symbols from stored ASTs using the library's incremental function.
    
    Delegates to ck3raven.db.symbols.extract_symbols_incremental which:
    - Only processes ASTs that don't have symbols yet (unless force_rebuild)
    - Doesn't delete existing valid symbols (unless force_rebuild)
    - Uses centralized file routing from file_routes.py
    - Maintains full source traceability
    
    Enhanced logging:
    - Progress every 50 ASTs with timing
    - Bloat file tracking (large ASTs)
    - File routing verification
    """
    from ck3raven.db.symbols import extract_symbols_incremental
    from ck3raven.db.file_routes import get_file_route, FileRoute
    import json as _json

    logger.info("Starting incremental symbol extraction...")
    
    # Track timing and bloat files
    start_time = time.time()
    last_log_time = start_time
    last_log_count = 0
    bloat_files = []  # Files with large ASTs or many symbols
    
    # Verify file routing is working - sample check
    sample_routes = conn.execute("""
        SELECT relpath, 
               CASE WHEN relpath LIKE 'localization/%' THEN 'localization'
                    WHEN relpath LIKE 'gfx/%' OR relpath LIKE 'gui/%' THEN 'skip'
                    ELSE 'script' END as expected_route
        FROM files WHERE deleted = 0
        ORDER BY RANDOM() LIMIT 5
    """).fetchall()
    
    logger.info("File routing spot-check:")
    for relpath, expected in sample_routes:
        actual_route, reason = get_file_route(relpath)
        match = "[OK]" if actual_route.value == expected else "[X]"
        logger.info(f"  {match} {relpath[:60]} -> {actual_route.value} (expected {expected})")

    def progress_callback(processed, total, symbols):
        nonlocal last_log_time, last_log_count
        write_heartbeat()
        pct = (processed / total * 100) if total > 0 else 0
        status.update(
            progress=pct,
            message=f"Symbols: {processed}/{total} ASTs, {symbols} symbols"
        )
        
        # Log every 50 ASTs with timing info
        if processed - last_log_count >= 50 or processed == total:
            now = time.time()
            elapsed_batch = now - last_log_time
            elapsed_total = now - start_time
            rate = (processed - last_log_count) / elapsed_batch if elapsed_batch > 0 else 0
            avg_rate = processed / elapsed_total if elapsed_total > 0 else 0
            eta_sec = (total - processed) / avg_rate if avg_rate > 0 else 0
            eta_min = eta_sec / 60
            
            logger.info(
                f"Symbol progress: {processed}/{total} ({pct:.1f}%) | "
                f"{symbols} symbols | {rate:.1f} AST/s (avg {avg_rate:.1f}) | "
                f"ETA: {eta_min:.1f}min"
            )
            last_log_time = now
            last_log_count = processed

    result = extract_symbols_incremental(
        conn,
        batch_size=50,  # Smaller batches for more frequent logging
        progress_callback=progress_callback,
        force_rebuild=force_rebuild
    )
    
    total_time = time.time() - start_time

    logger.info(
        f"Symbol extraction complete in {total_time:.1f}s: "
        f"extracted={result['symbols_extracted']}, "
        f"inserted={result['symbols_inserted']}, duplicates={result['duplicates']}, "
        f"errors={result['errors']}, skipped={result.get('files_skipped', 0)}"
    )
    
    # Report bloat files (top 10 largest ASTs by symbol count)
    bloat_query = conn.execute("""
        SELECT f.relpath, COUNT(s.symbol_id) as sym_count
        FROM symbols s
        JOIN files f ON s.defining_file_id = f.file_id
        GROUP BY f.file_id
        ORDER BY sym_count DESC
        LIMIT 10
    """).fetchall()
    
    if bloat_query:
        logger.info("Top 10 files by symbol count (bloat check):")
        for relpath, sym_count in bloat_query:
            logger.info(f"  {sym_count:5d} symbols: {relpath[:70]}")
    
    return {'extracted': result['symbols_extracted'], 'inserted': result['symbols_inserted'], 
            'duplicates': result['duplicates'], 'errors': result['errors']}


def extract_refs_from_stored_asts(conn, logger: DaemonLogger, status: StatusWriter):
    """Extract references from stored ASTs (not re-parsing).
    
    Optimized for performance:
    - Batch inserts instead of individual INSERTs
    - Pre-fetch content_version_id to avoid subquery per ref
    - Process in larger batches
    """
    from ck3raven.db.symbols import extract_refs_from_ast
    import json
    
    logger.info("Starting reference extraction from stored ASTs...")
    
    # Track timing
    start_time = time.time()
    last_log_time = start_time
    last_log_count = 0
    
    # Clear old refs
    conn.execute("DELETE FROM refs")
    conn.commit()
    
    # Build file_id -> content_version_id lookup for performance
    logger.info("Building content_version_id lookup...")
    cv_lookup = {}
    cv_rows = conn.execute("SELECT file_id, content_version_id FROM files WHERE deleted = 0").fetchall()
    for file_id, cv_id in cv_rows:
        cv_lookup[file_id] = cv_id
    logger.info(f"Cached {len(cv_lookup)} file -> content_version mappings")
    
    # Build skip clause for data-only folders (no script refs)
    skip_clauses = " AND ".join([f"f.relpath NOT LIKE '{folder}/%'" for folder in REF_EXTRACTION_SKIP_FOLDERS])
    logger.info(f"Skipping {len(REF_EXTRACTION_SKIP_FOLDERS)} data-only folders for ref extraction")
    
    # Query files that have ASTs (excluding data-only folders)
    count_sql = f"""
        SELECT COUNT(*) FROM files f
        JOIN asts a ON f.content_hash = a.content_hash
        WHERE f.deleted = 0 AND a.parse_ok = 1
        AND f.relpath LIKE '%.txt'
        AND {skip_clauses}
    """
    total_count = conn.execute(count_sql).fetchone()[0]
    
    logger.info(f"Processing {total_count} files for refs")
    
    chunk_size = 100  # Larger chunks for better performance
    offset = 0
    total_refs = 0
    errors = 0
    batch_refs = []  # Accumulate refs for batch insert
    
    # Pre-build the main query with skip clauses
    main_query = f"""
        SELECT f.file_id, f.relpath, f.content_hash, a.ast_id, a.ast_blob
        FROM files f
        JOIN asts a ON f.content_hash = a.content_hash
        WHERE f.deleted = 0 AND a.parse_ok = 1
        AND f.relpath LIKE '%.txt'
        AND {skip_clauses}
        ORDER BY f.file_id
        LIMIT ? OFFSET ?
    """
    
    while offset < total_count:
        write_heartbeat()
        
        rows = conn.execute(main_query, (chunk_size, offset)).fetchall()
        
        if not rows:
            break
        
        for file_id, relpath, content_hash, ast_id, ast_blob in rows:
            try:
                # Decode AST from blob
                ast_dict = json.loads(ast_blob.decode('utf-8'))
                
                refs = list(extract_refs_from_ast(ast_dict, relpath, content_hash))
                
                # Use cached content_version_id instead of subquery per ref
                cv_id = cv_lookup.get(file_id)
                if cv_id is None:
                    # Fallback query if not in cache (shouldn't happen)
                    row = conn.execute(
                        "SELECT content_version_id FROM files WHERE file_id = ?", (file_id,)
                    ).fetchone()
                    cv_id = row[0] if row else None
                
                if cv_id is not None:
                    for ref in refs:
                        batch_refs.append((
                            ref.kind, ref.name, file_id, ast_id, 
                            ref.line, ref.context, cv_id
                        ))
                
                total_refs += len(refs)
                
            except Exception as e:
                errors += 1
        
        # Batch insert all refs from this chunk
        if batch_refs:
            conn.executemany("""
                INSERT OR IGNORE INTO refs
                (ref_type, name, using_file_id, using_ast_id, line_number, context, content_version_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, batch_refs)
            batch_refs = []  # Reset for next chunk
        
        conn.commit()
        offset += len(rows)
        
        pct = (offset / total_count) * 100
        status.update(
            progress=pct,
            message=f"Refs: {offset}/{total_count} files, {total_refs} refs"
        )
        
        # Log every 50 files with timing
        if offset - last_log_count >= 50 or offset >= total_count:
            now = time.time()
            elapsed_batch = now - last_log_time
            elapsed_total = now - start_time
            rate = (offset - last_log_count) / elapsed_batch if elapsed_batch > 0 else 0
            avg_rate = offset / elapsed_total if elapsed_total > 0 else 0
            eta_sec = (total_count - offset) / avg_rate if avg_rate > 0 else 0
            eta_min = eta_sec / 60
            
            logger.info(
                f"Ref progress: {offset}/{total_count} ({pct:.1f}%) | "
                f"{total_refs} refs | {rate:.1f} files/s (avg {avg_rate:.1f}) | "
                f"ETA: {eta_min:.1f}min"
            )
            last_log_time = now
            last_log_count = offset
    
    total_time = time.time() - start_time
    logger.info(f"Ref extraction complete in {total_time:.1f}s: {total_refs} refs, {errors} errors")
    return {'extracted': total_refs, 'errors': errors}


def debug_daemon_phase(db_path: Path, phase: str, limit: int = 10) -> Path:
    """
    Debug any daemon phase using DebugSession architecture.
    
    Uses the unified DebugSession for phase-agnostic instrumentation.
    Outputs:
        - ~/.ck3raven/daemon/debug_trace.jsonl (JSONL event stream)
        - ~/.ck3raven/daemon/debug_summary.json (aggregated stats)
    
    Supported phases:
        - "all": Run all phases sequentially
        - "ingest": File discovery and content storage timing
        - "parse": Content → AST parsing 
        - "symbols": AST → symbol extraction
        - "refs": AST → reference extraction
        - "localization": YML → localization_entries extraction
        - "lookups": Symbol → lookup table extraction
    
    Args:
        db_path: Path to database
        phase: Which phase to debug
        limit: Number of files to process
        
    Returns:
        Path to output directory containing debug_trace.jsonl and debug_summary.json
    """
    import sqlite3
    from builder.debug import DebugSession
    
    conn = sqlite3.connect(db_path)
    
    # Determine which phases to run
    if phase == "all":
        phases = ["ingest", "parse", "symbols", "refs", "localization", "lookups"]
    else:
        phases = [phase]
    
    # Create debug session
    with DebugSession.from_config(
        output_dir=DAEMON_DIR,
        enabled=True,
        sample_limit=limit,
        phase_filter=phases if phase != "all" else None,
    ) as debug:
        
        for p in phases:
            debug.phase_start(p)
            
            try:
                if p == "ingest":
                    _debug_ingest_with_session(conn, debug, limit)
                elif p == "parse":
                    _debug_parse_with_session(conn, debug, limit)
                elif p == "symbols":
                    _debug_symbols_with_session(conn, debug, limit)
                elif p == "refs":
                    _debug_refs_with_session(conn, debug, limit)
                elif p == "localization":
                    _debug_localization_with_session(conn, debug, limit)
                elif p == "lookups":
                    _debug_lookups_with_session(conn, debug, limit)
                else:
                    debug.emit("error", message=f"Unknown phase: {p}")
            except Exception as e:
                debug.emit("error", message=str(e), phase=p)
            
            debug.phase_end(p)
        
    conn.close()
    
    # Also write legacy format for backwards compatibility
    _write_legacy_debug_output(db_path, phase, limit)
    
    return DAEMON_DIR


def _debug_ingest_with_session(conn, debug, limit: int):
    """Debug ingest phase using DebugSession."""
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, fc.size, fc.is_binary
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        LIMIT ?
    """, (limit,)).fetchall()
    
    for file_id, relpath, content_hash, size, is_binary in rows:
        with debug.span("file", phase="ingest", path=relpath) as s:
            s.add(
                file_id=file_id,
                input_bytes=size,
                is_binary=bool(is_binary),
                output_count=1,  # One file stored
            )


def _debug_parse_with_session(conn, debug, limit: int):
    """Debug parse phase using DebugSession."""
    from ck3raven.parser import parse_source
    import json as json_mod
    
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, fc.content_text
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.relpath LIKE '%.txt'
        AND fc.content_text IS NOT NULL
        AND LENGTH(fc.content_text) < 500000
        LIMIT ?
    """, (limit,)).fetchall()
    
    for file_id, relpath, content_text in rows:
        with debug.span("file", phase="parse", path=relpath) as s:
            input_bytes = len(content_text) if content_text else 0
            s.add(input_bytes=input_bytes)
            
            try:
                ast = parse_source(content_text, relpath)
                if ast:
                    ast_dict = ast.to_dict() if hasattr(ast, 'to_dict') else ast
                    ast_json = json_mod.dumps(ast_dict, separators=(',', ':'))
                    s.add(
                        output_bytes=len(ast_json),
                        output_count=ast_json.count('{'),  # node count estimate
                        ok=True,
                    )
                else:
                    s.add(ok=False, output_count=0)
            except Exception as e:
                s.add(ok=False, error=str(e)[:100])
                debug.emit("error", phase="parse", path=relpath, message=str(e)[:200])


def _debug_symbols_with_session(conn, debug, limit: int):
    """Debug symbols phase using DebugSession."""
    from ck3raven.db.symbols import extract_symbols_from_ast
    import json as json_mod
    
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, a.ast_blob, a.ast_id
        FROM files f
        JOIN asts a ON f.content_hash = a.content_hash
        WHERE a.parse_ok = 1
        LIMIT ?
    """, (limit,)).fetchall()
    
    for file_id, relpath, content_hash, ast_blob, ast_id in rows:
        with debug.span("file", phase="symbols", path=relpath) as s:
            s.add(input_bytes=len(ast_blob) if ast_blob else 0, ast_id=ast_id)
            
            try:
                ast_dict = json_mod.loads(ast_blob.decode('utf-8'))
                symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
                s.add(output_count=len(symbols), ok=True)
            except Exception as e:
                s.add(ok=False, error=str(e)[:100])
                debug.emit("error", phase="symbols", path=relpath, message=str(e)[:200])


def _debug_refs_with_session(conn, debug, limit: int):
    """Debug refs phase using DebugSession."""
    from ck3raven.db.symbols import extract_refs_from_ast
    import json as json_mod
    
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, a.ast_blob, a.ast_id
        FROM files f
        JOIN asts a ON f.content_hash = a.content_hash
        WHERE a.parse_ok = 1
        LIMIT ?
    """, (limit,)).fetchall()
    
    for file_id, relpath, content_hash, ast_blob, ast_id in rows:
        with debug.span("file", phase="refs", path=relpath) as s:
            s.add(input_bytes=len(ast_blob) if ast_blob else 0, ast_id=ast_id)
            
            try:
                ast_dict = json_mod.loads(ast_blob.decode('utf-8'))
                refs = list(extract_refs_from_ast(ast_dict, relpath, content_hash))
                s.add(output_count=len(refs), ok=True)
            except Exception as e:
                s.add(ok=False, error=str(e)[:100])
                debug.emit("error", phase="refs", path=relpath, message=str(e)[:200])


def _debug_localization_with_session(conn, debug, limit: int):
    """Debug localization phase using DebugSession."""
    from ck3raven.parser.localization import parse_localization
    
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, fc.content_text
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.relpath LIKE '%_l_english.yml'
        AND fc.content_text IS NOT NULL
        LIMIT ?
    """, (limit,)).fetchall()
    
    for file_id, relpath, content_text in rows:
        with debug.span("file", phase="localization", path=relpath) as s:
            s.add(input_bytes=len(content_text) if content_text else 0)
            
            try:
                loc_file = parse_localization(content_text, relpath)
                s.add(output_count=len(loc_file.entries), ok=True)
            except Exception as e:
                s.add(ok=False, error=str(e)[:100])
                debug.emit("error", phase="localization", path=relpath, message=str(e)[:200])


def _debug_lookups_with_session(conn, debug, limit: int):
    """Debug lookups phase using DebugSession."""
    tables = ["trait_lookups", "event_lookups", "decision_lookups"]
    
    for table in tables:
        with debug.span("file", phase="lookups", path=table) as s:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                s.add(output_count=count, ok=True)
            except Exception as e:
                s.add(ok=False, error=str(e)[:100])


def _write_legacy_debug_output(db_path: Path, phase: str, limit: int):
    """Write legacy debug_output.json format for backwards compatibility."""
    import sqlite3
    
    conn = sqlite3.connect(db_path)
    
    output = {
        "started_at": datetime.now().isoformat(),
        "phase": phase,
        "limit": limit,
        "db_path": str(db_path),
        "files": [],
        "blocks": {},
        "summary": {},
        "errors": []
    }
    
    try:
        if phase == "all":
            phases = ["ingest", "parse", "symbols", "refs", "localization", "lookups"]
            output["phases"] = {}
            for p in phases:
                phase_output = {"files": [], "summary": {}, "errors": []}
                try:
                    if p == "ingest":
                        _debug_ingest_phase(conn, phase_output, limit)
                    elif p == "parse":
                        _debug_parse_phase(conn, phase_output, limit)
                    elif p == "symbols":
                        _debug_symbols_phase(conn, phase_output, limit)
                    elif p == "refs":
                        _debug_refs_phase(conn, phase_output, limit)
                    elif p == "localization":
                        _debug_localization_phase(conn, phase_output, limit)
                    elif p == "lookups":
                        _debug_lookups_phase(conn, phase_output, limit)
                except Exception as e:
                    phase_output["errors"].append(str(e))
                output["phases"][p] = phase_output
            output["summary"] = {"phases_run": len(phases)}
        else:
            if phase == "ingest":
                _debug_ingest_phase(conn, output, limit)
            elif phase == "parse":
                _debug_parse_phase(conn, output, limit)
            elif phase == "symbols":
                _debug_symbols_phase(conn, output, limit)
            elif phase == "refs":
                _debug_refs_phase(conn, output, limit)
            elif phase == "localization":
                _debug_localization_phase(conn, output, limit)
            elif phase == "lookups":
                _debug_lookups_phase(conn, output, limit)
    except Exception as e:
        output["errors"].append(str(e))
    finally:
        conn.close()
    
    output["completed_at"] = datetime.now().isoformat()
    _write_debug_output(output)


# Legacy debug functions - kept for backwards compatibility
def _debug_ingest_phase(conn: sqlite3.Connection, output: dict, limit: int):
    """Debug file ingestion - measure file discovery and content storage."""
    
    # Get sample of files with their content
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, fc.size, fc.is_binary
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        LIMIT ?
    """, (limit,)).fetchall()
    
    if not rows:
        output["errors"].append("No files found in database")
        return
    
    total_size = 0
    for file_id, relpath, content_hash, size, is_binary in rows:
        file_result = {
            "file": relpath,
            "file_id": file_id,
            "content_hash": content_hash[:16] + "...",
            "size_bytes": size,
            "is_binary": bool(is_binary)
        }
        output["files"].append(file_result)
        total_size += size or 0
    
    output["summary"] = {
        "files_sampled": len(rows),
        "total_size_bytes": total_size,
        "avg_size_bytes": round(total_size / len(rows), 0) if rows else 0,
        "note": "Ingest timing requires running actual ingest - this shows stored data stats"
    }


def _debug_parse_phase(conn: sqlite3.Connection, output: dict, limit: int):
    """Debug parsing - measure content → AST timing."""
    from ck3raven.parser import parse_source_recovering
    
    # Get files that need parsing (have content but no AST, or sample existing)
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, fc.content_text
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE fc.is_binary = 0 AND fc.content_text IS NOT NULL
        AND f.relpath LIKE '%.txt'
        LIMIT ?
    """, (limit,)).fetchall()
    
    if not rows:
        output["errors"].append("No parseable files found")
        return
    
    total_parse_ms = 0
    total_size = 0
    parsed_count = 0
    
    for file_id, relpath, content_hash, content_text in rows:
        file_result = {
            "file": relpath,
            "file_id": file_id,
            "input_size_bytes": len(content_text) if content_text else 0
        }
        
        try:
            # Time the parsing - use recovering parser to get error info
            t0 = time.time()
            result = parse_source_recovering(content_text, filename=relpath)
            parse_ms = (time.time() - t0) * 1000
            
            file_result["parse_ms"] = round(parse_ms, 2)
            file_result["parse_ok"] = result.success
            file_result["error_count"] = len([d for d in result.diagnostics if d.severity == "error"])
            
            if result.ast:
                file_result["node_count"] = _count_ast_nodes(result.ast.to_dict())
                # Measure AST bloat
                ast_json = json.dumps(result.ast.to_dict())
                file_result["output_size_bytes"] = len(ast_json)
                file_result["bloat_ratio"] = round(len(ast_json) / max(1, len(content_text)), 2)
            
            total_parse_ms += parse_ms
            total_size += len(content_text) if content_text else 0
            parsed_count += 1
            
        except Exception as e:
            file_result["error"] = str(e)
            output["errors"].append({"file": relpath, "error": str(e)})
        
        output["files"].append(file_result)
    
    if parsed_count > 0:
        avg_ms = total_parse_ms / parsed_count
        output["summary"] = {
            "files_parsed": parsed_count,
            "total_parse_ms": round(total_parse_ms, 2),
            "avg_parse_ms": round(avg_ms, 2),
            "projected_rate_per_sec": round(1000 / avg_ms, 1) if avg_ms > 0 else 0,
            "total_input_bytes": total_size,
            "avg_input_bytes": round(total_size / parsed_count, 0)
        }


def _debug_symbols_phase(conn: sqlite3.Connection, output: dict, limit: int):
    """Debug symbol extraction - measure AST → symbols timing."""
    from ck3raven.db.symbols import extract_symbols_from_ast
    
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, a.ast_blob, a.ast_id
        FROM asts a
        JOIN files f ON a.content_hash = f.content_hash
        WHERE a.parse_ok = 1
        LIMIT ?
    """, (limit,)).fetchall()
    
    if not rows:
        output["errors"].append("No ASTs found in database")
        return
    
    total_extract_ms = 0
    total_symbols = 0
    
    for file_id, relpath, content_hash, ast_blob, ast_id in rows:
        file_result = {
            "file": relpath,
            "file_id": file_id,
            "ast_id": ast_id,
            "ast_size_bytes": len(ast_blob) if ast_blob else 0
        }
        
        try:
            # Decode AST
            t0 = time.time()
            ast_dict = json.loads(ast_blob.decode('utf-8'))
            decode_ms = (time.time() - t0) * 1000
            file_result["decode_ms"] = round(decode_ms, 2)
            
            # Extract symbols
            t1 = time.time()
            symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
            extract_ms = (time.time() - t1) * 1000
            file_result["extract_ms"] = round(extract_ms, 2)
            file_result["symbols_count"] = len(symbols)
            file_result["total_ms"] = round(decode_ms + extract_ms, 2)
            
            total_extract_ms += decode_ms + extract_ms
            total_symbols += len(symbols)
            
        except Exception as e:
            file_result["error"] = str(e)
            output["errors"].append({"file": relpath, "error": str(e)})
        
        output["files"].append(file_result)
    
    valid = [f for f in output["files"] if "total_ms" in f]
    if valid:
        avg_ms = sum(f["total_ms"] for f in valid) / len(valid)
        output["summary"] = {
            "files_processed": len(valid),
            "total_symbols": total_symbols,
            "avg_ms_per_file": round(avg_ms, 2),
            "projected_rate_per_sec": round(1000 / avg_ms, 1) if avg_ms > 0 else 0
        }


def _debug_refs_phase(conn: sqlite3.Connection, output: dict, limit: int):
    """Debug ref extraction - measure AST → refs timing."""
    from ck3raven.db.symbols import extract_refs_from_ast
    
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, a.ast_blob, a.ast_id
        FROM asts a
        JOIN files f ON a.content_hash = f.content_hash
        WHERE a.parse_ok = 1
        LIMIT ?
    """, (limit,)).fetchall()
    
    if not rows:
        output["errors"].append("No ASTs found in database")
        return
    
    total_decode_ms = 0
    total_extract_ms = 0
    total_refs = 0
    
    for file_id, relpath, content_hash, ast_blob, ast_id in rows:
        file_result = {
            "file": relpath,
            "file_id": file_id,
            "ast_id": ast_id,
            "ast_size_bytes": len(ast_blob) if ast_blob else 0
        }
        
        try:
            # Block 1: Decode AST
            t0 = time.time()
            ast_dict = json.loads(ast_blob.decode('utf-8'))
            decode_ms = (time.time() - t0) * 1000
            file_result["decode_ms"] = round(decode_ms, 2)
            total_decode_ms += decode_ms
            
            file_result["ast_node_count"] = _count_ast_nodes(ast_dict)
            
            # Block 2: Extract refs
            t1 = time.time()
            refs = list(extract_refs_from_ast(ast_dict, relpath, content_hash))
            extract_ms = (time.time() - t1) * 1000
            file_result["extract_ms"] = round(extract_ms, 2)
            file_result["refs_count"] = len(refs)
            total_refs += len(refs)
            total_extract_ms += extract_ms
            
            file_result["total_ms"] = round(decode_ms + extract_ms, 2)
            
            if file_result["ast_size_bytes"] > 0:
                file_result["refs_per_kb"] = round(
                    len(refs) / (file_result["ast_size_bytes"] / 1024), 2
                )
                
        except Exception as e:
            file_result["error"] = str(e)
            output["errors"].append({"file": relpath, "error": str(e)})
        
        output["files"].append(file_result)
    
    valid = [f for f in output["files"] if "total_ms" in f]
    if valid:
        times = [f["total_ms"] for f in valid]
        sizes = [f["ast_size_bytes"] for f in valid]
        avg_ms = sum(times) / len(times)
        
        output["summary"] = {
            "files_processed": len(valid),
            "total_refs": total_refs,
            "total_decode_ms": round(total_decode_ms, 2),
            "total_extract_ms": round(total_extract_ms, 2),
            "avg_ms_per_file": round(avg_ms, 2),
            "min_ms": round(min(times), 2),
            "max_ms": round(max(times), 2),
            "projected_rate_per_sec": round(1000 / avg_ms, 1) if avg_ms > 0 else 0,
            "total_ast_bytes": sum(sizes),
            "bloat_indicator": round(sum(sizes) / (total_refs + 1), 2)
        }


def _debug_localization_phase(conn: sqlite3.Connection, output: dict, limit: int):
    """Debug localization extraction - measure YML → loc entries timing."""
    from ck3raven.parser.localization import parse_localization
    
    # Get YML files
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, fc.content_text
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.relpath LIKE '%_l_english.yml'
        AND fc.content_text IS NOT NULL
        LIMIT ?
    """, (limit,)).fetchall()
    
    if not rows:
        output["errors"].append("No localization files found")
        return
    
    total_parse_ms = 0
    total_entries = 0
    
    for file_id, relpath, content_text in rows:
        file_result = {
            "file": relpath,
            "file_id": file_id,
            "input_size_bytes": len(content_text) if content_text else 0
        }
        
        try:
            t0 = time.time()
            loc_file = parse_localization(content_text, relpath)
            parse_ms = (time.time() - t0) * 1000
            
            file_result["parse_ms"] = round(parse_ms, 2)
            file_result["entries_count"] = len(loc_file.entries)
            file_result["entries_per_kb"] = round(
                len(loc_file.entries) / max(1, len(content_text) / 1024), 2
            )
            
            total_parse_ms += parse_ms
            total_entries += len(loc_file.entries)
            
        except Exception as e:
            file_result["error"] = str(e)
            output["errors"].append({"file": relpath, "error": str(e)})
        
        output["files"].append(file_result)
    
    valid = [f for f in output["files"] if "parse_ms" in f]
    if valid:
        avg_ms = total_parse_ms / len(valid)
        output["summary"] = {
            "files_processed": len(valid),
            "total_entries": total_entries,
            "avg_ms_per_file": round(avg_ms, 2),
            "projected_rate_per_sec": round(1000 / avg_ms, 1) if avg_ms > 0 else 0
        }


def _debug_lookups_phase(conn: sqlite3.Connection, output: dict, limit: int):
    """Debug lookup extraction - show current lookup table stats."""
    
    # This phase doesn't process files individually, so just show stats
    tables = ["trait_lookups", "event_lookups", "decision_lookups"]
    
    table_stats = {}
    for table in tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            table_stats[table] = {"count": count}
        except Exception as e:
            table_stats[table] = {"error": str(e)}
    
    # Sample some lookups
    try:
        traits = conn.execute("SELECT name, category FROM trait_lookups LIMIT ?", (limit,)).fetchall()
        output["files"] = [{"name": t[0], "category": t[1]} for t in traits]
        output["summary"] = {
            "note": "Lookups phase builds aggregate tables from symbols",
            "tables": table_stats
        }
    except Exception as e:
        output["errors"].append({"phase": "lookups", "error": str(e)})


def _count_ast_nodes(node, depth=0) -> int:
    """Count nodes in AST for bloat measurement."""
    if depth > 100:  # Prevent infinite recursion
        return 1
    
    if isinstance(node, dict):
        count = 1
        for v in node.values():
            count += _count_ast_nodes(v, depth + 1)
        return count
    elif isinstance(node, list):
        return sum(_count_ast_nodes(item, depth + 1) for item in node)
    else:
        return 1


def _write_debug_output(output: dict):
    """Write debug output to JSON file."""
    DEBUG_OUTPUT_FILE.write_text(json.dumps(output, indent=2))


def start_detached(db_path: Path, force: bool, symbols_only: bool = False, ingest_all: bool = False, full_rebuild: bool = False, dry_run: bool = False, skip_file_check: bool = False):
    """Launch the rebuild as a completely detached process."""
    
    # Create the command to run ourselves in daemon mode
    script_path = Path(__file__).resolve()
    
    # Use pythonw.exe on Windows to avoid any console
    python_exe = sys.executable
    pythonw = Path(python_exe).parent / "pythonw.exe"
    if pythonw.exists():
        python_exe = str(pythonw)
    
    args = [
        python_exe,
        str(script_path),
        "_run_daemon",
        "--db", str(db_path),
    ]
    if force:
        args.append("--force")
    if symbols_only:
        args.append("--symbols-only")
    if ingest_all:
        args.append("--ingest-all")
    if full_rebuild:
        args.append("--full-rebuild")
    if dry_run:
        args.append("--dry-run")
    if skip_file_check:
        args.append("--skip-file-check")
    
    # Launch completely detached
    # DETACHED_PROCESS = 0x00000008
    # CREATE_NEW_PROCESS_GROUP = 0x00000200
    # CREATE_NO_WINDOW = 0x08000000
    creationflags = 0x00000008 | 0x00000200 | 0x08000000
    
    # Clear old status
    if STATUS_FILE.exists():
        STATUS_FILE.unlink()
    if LOG_FILE.exists():
        # Rotate old log
        old_log = LOG_FILE.with_suffix(".log.old")
        LOG_FILE.replace(old_log)
    
    subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=True
    )
    
    print(f"Rebuild daemon started. Monitor with: python {script_path.name} status")
    print(f"Logs: {LOG_FILE}")


def show_status(verbose: bool = False, format_json: bool = False):
    """Show current daemon status.
    
    Args:
        verbose: Show error details from ingest_log
        format_json: Output as JSON instead of text
    """
    
    running = is_daemon_running()
    
    # Collect status data
    status_data = {
        "daemon_running": running,
        "pid": None,
        "heartbeat_age_sec": None,
        "current_phase": None,
        "progress": 0,
        "message": "",
    }
    
    if PID_FILE.exists():
        status_data["pid"] = int(PID_FILE.read_text().strip())
    
    if HEARTBEAT_FILE.exists():
        try:
            last = float(HEARTBEAT_FILE.read_text().strip())
            status_data["heartbeat_age_sec"] = time.time() - last
        except Exception:
            pass
    
    if STATUS_FILE.exists():
        try:
            status = json.loads(STATUS_FILE.read_text())
            status_data["state"] = status.get('state', 'unknown')
            status_data["current_phase"] = status.get('phase', 'unknown')
            status_data["phase_number"] = status.get('phase_number', 0)
            status_data["total_phases"] = status.get('total_phases', 7)
            status_data["progress"] = status.get('progress', 0)
            status_data["message"] = status.get('message', '')
            status_data["error"] = status.get('error')
            status_data["started_at"] = status.get('started_at', 'unknown')
            status_data["updated_at"] = status.get('updated_at', 'unknown')
        except Exception:
            pass
    
    # Try to get recent build info from database
    try:
        from ck3raven.db.schema import get_connection
        conn = get_connection(DEFAULT_DB_PATH)
        # Get most recent build
        build = conn.execute("""
            SELECT build_id, started_at, completed_at, state, 
                   files_ingested, asts_produced, symbols_extracted
            FROM builder_runs 
            ORDER BY started_at DESC LIMIT 1
        """).fetchone()
        if build:
            status_data["last_build"] = {
                "build_id": build['build_id'],
                "started_at": build['started_at'],
                "completed_at": build['completed_at'],
                "state": build['state'],
                "files": build['files_ingested'],
                "asts": build['asts_produced'],
                "symbols": build['symbols_extracted'],
            }
    except Exception:
        pass  # Table might not exist yet
    
    # Output
    if format_json:
        print(json.dumps(status_data, indent=2, default=str))
        return
    
    # Text output
    print(f"Daemon running: {running}")
    
    if status_data.get("pid"):
        print(f"PID: {status_data['pid']}")
    
    if status_data.get("heartbeat_age_sec") is not None:
        print(f"Last heartbeat: {status_data['heartbeat_age_sec']:.1f}s ago")
    
    if STATUS_FILE.exists():
        try:
            status = json.loads(STATUS_FILE.read_text())
            print(f"\nCurrent Status:")
            print(f"  State: {status.get('state', 'unknown')}")
            print(f"  Phase: {status.get('phase', 'unknown')} ({status.get('phase_number', 0)}/{status.get('total_phases', 7)})")
            print(f"  Progress: {status.get('progress', 0):.1f}%")
            print(f"  Message: {status.get('message', '')}")
            if status.get('error'):
                print(f"  Error: {status.get('error')}")
            print(f"  Started: {status.get('started_at', 'unknown')}")
            print(f"  Updated: {status.get('updated_at', 'unknown')}")
        except Exception as e:
            print(f"Error reading status: {e}")
    else:
        print("No status file found")
    
    # Show last build info
    if status_data.get("last_build"):
        build = status_data["last_build"]
        print(f"\nLast Build ({build['build_id'][:8]}...):")
        print(f"  State: {build['state']}")
        print(f"  Started: {build['started_at']}")
        print(f"  Completed: {build['completed_at'] or 'in progress'}")
        print(f"  Files: {build['files']}, ASTs: {build['asts']}, Symbols: {build['symbols']}")
        
        if verbose:
            # Show errors from ingest_log if any
            try:
                from ck3raven.db.schema import get_connection
                conn = get_connection(DEFAULT_DB_PATH)
                errors = conn.execute("""
                    SELECT phase, relpath, error_type, error_msg
                    FROM ingest_log 
                    WHERE build_id = ? AND status = 'error'
                    LIMIT 10
                """, (build['build_id'],)).fetchall()
                if errors:
                    print(f"\n  Recent Errors:")
                    for err in errors:
                        print(f"    [{err['phase']}] {err['relpath']}: {err['error_type']}")
            except Exception:
                pass


def show_logs(follow: bool = False):
    """Show daemon logs."""
    if not LOG_FILE.exists():
        print("No log file found")
        return
    
    if follow:
        # Tail -f equivalent
        print(f"Following {LOG_FILE} (Ctrl+C to stop)...")
        with open(LOG_FILE, "r") as f:
            # Go to end
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    print(line, end="")
                else:
                    time.sleep(0.5)
    else:
        # Just print last 50 lines
        lines = LOG_FILE.read_text().splitlines()
        for line in lines[-50:]:
            print(line)


def stop_daemon():
    """Stop the running daemon."""
    if not is_daemon_running():
        print("Daemon is not running")
        return
    
    try:
        pid = int(PID_FILE.read_text().strip())
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_TERMINATE = 0x0001
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if handle:
            kernel32.TerminateProcess(handle, 1)
            kernel32.CloseHandle(handle)
            print(f"Daemon (PID {pid}) terminated")
        cleanup_pid()
    except Exception as e:
        print(f"Error stopping daemon: {e}")


def main():
    # Ensure paths are set up early for detached process
    src_path = Path(__file__).parent.parent / "src"
    if src_path.exists() and str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
        
    parser = argparse.ArgumentParser(description="CK3Raven rebuild daemon")
    parser.add_argument("command", choices=["start", "status", "stop", "logs", "_run_daemon"],
                        help="Command to execute")
    parser.add_argument("--force", action="store_true", help="Force complete rebuild")
    parser.add_argument("--symbols-only", action="store_true", help="Only run symbol/ref extraction (skip ingest)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Database path")
    parser.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    
    # Debug mode options - unified for any phase
    parser.add_argument("--debug", type=str, metavar="PHASE",
                        choices=["all", "ingest", "parse", "symbols", "refs", "localization", "lookups"],
                        help="Debug daemon phase(s) with detailed timing. Use 'all' for all phases. Output to ~/.ck3raven/daemon/debug_output.json")
    parser.add_argument("--debug-limit", type=int, default=10, metavar="N",
                        help="Number of files to process in debug mode (default: 10)")
    
    # Test mode options
    parser.add_argument("--test", action="store_true", 
                        help="Run synchronously with verbose output (for testing)")
    parser.add_argument("--vanilla-path", type=Path, 
                        help="Custom vanilla path (for testing with fixtures)")
    parser.add_argument("--skip-mods", action="store_true",
                        help="Skip mod ingestion (for vanilla-only testing)")
    parser.add_argument("--ingest-all", action="store_true",
                        help="Ingest ALL mods (workshop + local) instead of just active playset")
    
    # Incremental rebuild options
    parser.add_argument("--full-rebuild", action="store_true",
                        help="Force full rebuild of all mods (overrides incremental)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be rebuilt without making changes")
    parser.add_argument("--skip-file-check", action="store_true",
                        help="Skip checking for changed files in already-indexed mods (faster but may miss changes)")
    
    # Status command options
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed status including error manifests from recent blocks")
    parser.add_argument("--format", choices=["text", "json"], default="text",
                        help="Output format for status command (default: text)")
    
    args = parser.parse_args()
    
    if args.command == "start":
        if args.debug:
            # Debug a specific phase - outputs to file, not terminal
            print(f"Running {args.debug} phase debug on {args.debug_limit} files...")
            print(f"Output will be written to: {DAEMON_DIR}")
            output_dir = debug_daemon_phase(args.db, args.debug, args.debug_limit)
            print(f"\nDebug complete. Results saved to: {output_dir}")
            
            # Print summary from the new debug_summary.json
            summary_file = output_dir / "debug_summary.json"
            legacy_file = output_dir / "debug_output.json"
            
            try:
                if summary_file.exists():
                    result = json.loads(summary_file.read_text())
                    print(f"\n=== DebugSession Summary ===")
                    print(f"Run ID: {result.get('run_id', 'N/A')}")
                    print(f"Duration: {result.get('duration_sec', 0):.1f}s")
                    for phase_name, phase_stats in result.get("phases", {}).items():
                        print(f"\n{phase_name}:")
                        print(f"  Files: {phase_stats.get('files_processed', 0)}")
                        print(f"  Rate: {phase_stats.get('rate_per_sec', 0):.1f} files/sec")
                        print(f"  Errors: {phase_stats.get('errors', 0)}")
                
                # Also show legacy format summary
                if legacy_file.exists():
                    legacy = json.loads(legacy_file.read_text())
                    if legacy.get("summary"):
                        s = legacy["summary"]
                        print(f"\n=== Legacy Summary ===")
                        for key, value in s.items():
                            if isinstance(value, float):
                                print(f"  {key}: {value:.1f}")
                            else:
                                print(f"  {key}: {value}")
                    if legacy.get("errors"):
                        print(f"\nErrors: {len(legacy['errors'])}")
                        for err in legacy["errors"][:3]:
                            print(f"  - {err}")
                            
            except Exception as e:
                print(f"Error reading output: {e}")
            sys.exit(0)
        
        if args.test:
            # Run synchronously for testing - no daemon, no duplicate check
            print(f"Running in TEST mode (synchronous, verbose)")
            print(f"  Database: {args.db}")
            print(f"  Vanilla: {args.vanilla_path or 'default'}")
            print(f"  Skip mods: {args.skip_mods}")
            print(f"  Ingest all mods: {args.ingest_all}")
            print(f"  Incremental: {not args.full_rebuild}")
            print(f"  Dry run: {args.dry_run}")
            logger = DaemonLogger(LOG_FILE, also_print=True)
            status = StatusWriter(STATUS_FILE)
            run_rebuild(
                args.db, args.force, logger, status, args.symbols_only,
                vanilla_path=args.vanilla_path,
                skip_mods=args.skip_mods,
                use_active_playset=not args.ingest_all,
                incremental=not args.full_rebuild,
                dry_run=args.dry_run,
                check_file_changes=not args.skip_file_check
            )
            sys.exit(0)
        
        # Check for running instance using both PID check and exclusive lock
        if is_daemon_running():
            print("Daemon is already running (PID check). Use 'stop' first.")
            sys.exit(1)
        
        start_detached(
            args.db, args.force, args.symbols_only, 
            ingest_all=args.ingest_all,
            full_rebuild=args.full_rebuild,
            dry_run=args.dry_run,
            skip_file_check=args.skip_file_check
        )
    
    elif args.command == "status":
        show_status(verbose=args.verbose, format_json=(args.format == "json"))
    
    elif args.command == "stop":
        stop_daemon()
    
    elif args.command == "logs":
        show_logs(args.follow)
    
    elif args.command == "_run_daemon":
        # Internal: actually run the daemon
        # Try to acquire exclusive lock first
        if not acquire_exclusive_lock():
            # Another daemon has the lock - exit silently
            sys.exit(1)
        
        write_pid()
        logger = DaemonLogger(LOG_FILE)
        status = StatusWriter(STATUS_FILE)
        
        try:
            run_rebuild(
                args.db, args.force, logger, status, args.symbols_only, 
                use_active_playset=not args.ingest_all,
                incremental=not args.full_rebuild,
                dry_run=args.dry_run,
                check_file_changes=not args.skip_file_check
            )
        except Exception as e:
            logger.error(f"Daemon crashed: {e}")
            logger.error(traceback.format_exc())
        finally:
            cleanup_pid()


if __name__ == "__main__":
    main()

