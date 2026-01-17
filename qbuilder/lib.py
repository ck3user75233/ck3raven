"""
QBuilder Library API — Unified entry point for MCP integration.

This module provides the canonical library API for qbuilder operations.
MCP tools should import from here instead of using subprocess calls.

Design principles:
- Queue-based coordination: Safe for multiple MCP servers to call concurrently
- No blocking long-running operations: discover/build return after enqueuing
- Single database connection source: Uses ck3raven.db.schema.get_connection()
- Stateless functions: Each call is independent

Thread safety:
- All operations use SQLite with WAL mode and proper locking
- Multiple processes/threads can safely enqueue work
- Workers use lease-based claiming to prevent double-processing

Usage from MCP:
    from qbuilder.lib import (
        get_queue_status,
        enqueue_discovery,
        reset_queues,
        enqueue_file,
    )
    
    # Check status
    status = get_queue_status()
    
    # Enqueue discovery (fast - just inserts tasks)
    enqueue_discovery()
    
    # Enqueue a single file for flash update
    enqueue_file(mod_name="MyMod", rel_path="common/traits/fix.txt")
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Literal

# Central database access - THE canonical source
from ck3raven.db.schema import DEFAULT_DB_PATH, get_connection as _get_central_connection

# QBuilder internals
from .schema import init_qbuilder_schema, reset_qbuilder_tables, get_queue_counts
from .discovery import enqueue_playset_roots, run_discovery, get_envelope_for_file, get_routing_table
from .worker import run_build_worker


# =============================================================================
# Connection Management
# =============================================================================

def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Get database connection using central ck3raven connection factory.
    
    This wraps the central get_connection to ensure consistent settings
    and proper QBuilder schema initialization.
    """
    conn = _get_central_connection(db_path or DEFAULT_DB_PATH)
    # Ensure QBuilder tables exist
    init_qbuilder_schema(conn)
    return conn


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class QueueStatus:
    """Status of build queues."""
    discovery_pending: int
    discovery_processing: int
    discovery_completed: int
    discovery_error: int
    
    build_pending: int
    build_processing: int
    build_completed: int
    build_error: int
    
    # Database counts
    files: int
    asts: int
    symbols: int
    refs: int
    
    @property
    def has_pending_work(self) -> bool:
        """True if there's work in progress or pending."""
        return (
            self.discovery_pending > 0 or
            self.discovery_processing > 0 or
            self.build_pending > 0 or
            self.build_processing > 0
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "discovery": {
                "pending": self.discovery_pending,
                "processing": self.discovery_processing,
                "completed": self.discovery_completed,
                "error": self.discovery_error,
            },
            "build": {
                "pending": self.build_pending,
                "processing": self.build_processing,
                "completed": self.build_completed,
                "error": self.build_error,
            },
            "database": {
                "files": self.files,
                "asts": self.asts,
                "symbols": self.symbols,
                "refs": self.refs,
            },
            "has_pending_work": self.has_pending_work,
        }


@dataclass
class EnqueueResult:
    """Result of an enqueue operation."""
    success: bool
    message: str
    tasks_enqueued: int = 0
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        result = {
            "success": self.success,
            "message": self.message,
            "tasks_enqueued": self.tasks_enqueued,
        }
        if self.error:
            result["error"] = self.error
        return result


# =============================================================================
# Public API Functions
# =============================================================================

def get_queue_status(db_path: Optional[Path] = None) -> QueueStatus:
    """
    Get current queue and database status.
    
    This is a fast, read-only operation that returns current counts.
    Safe to call frequently for polling.
    """
    conn = get_connection(db_path)
    
    try:
        # Get queue counts using the schema function
        counts = get_queue_counts(conn)
        
        # Get database counts
        db_counts = {}
        for table in ['files', 'asts', 'symbols', 'refs']:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                db_counts[table] = row[0] if row else 0
            except sqlite3.OperationalError:
                db_counts[table] = 0
        
        return QueueStatus(
            discovery_pending=counts.get('discovery_pending', 0),
            discovery_processing=counts.get('discovery_processing', 0),
            discovery_completed=counts.get('discovery_completed', 0),
            discovery_error=counts.get('discovery_error', 0),
            build_pending=counts.get('build_pending', 0),
            build_processing=counts.get('build_processing', 0),
            build_completed=counts.get('build_completed', 0),
            build_error=counts.get('build_error', 0),
            files=db_counts.get('files', 0),
            asts=db_counts.get('asts', 0),
            symbols=db_counts.get('symbols', 0),
            refs=db_counts.get('refs', 0),
        )
    finally:
        conn.close()


def enqueue_discovery(
    playset_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> EnqueueResult:
    """
    Enqueue discovery tasks for the active playset.
    
    This is a fast operation that only inserts tasks into the queue.
    It does NOT run discovery workers - call run_discovery_batch() for that.
    
    Args:
        playset_path: Path to playset JSON file (uses active playset if None)
        db_path: Database path override
    
    Returns:
        EnqueueResult with count of tasks enqueued
    """
    conn = get_connection(db_path)
    
    try:
        # Get playset path
        if playset_path is None:
            playset_path = _get_active_playset_file()
        
        if playset_path is None or not playset_path.exists():
            return EnqueueResult(
                success=False,
                message="No active playset found",
                error=f"Playset file not found: {playset_path}",
            )
        
        # Enqueue discovery tasks
        count = enqueue_playset_roots(conn, playset_path)
        
        return EnqueueResult(
            success=True,
            message=f"Enqueued {count} discovery tasks",
            tasks_enqueued=count,
        )
    except Exception as e:
        return EnqueueResult(
            success=False,
            message="Failed to enqueue discovery",
            error=str(e),
        )
    finally:
        conn.close()


def run_discovery_batch(
    max_tasks: Optional[int] = None,
    db_path: Optional[Path] = None,
) -> dict:
    """
    Run discovery workers on pending tasks.
    
    This processes pending discovery queue items up to max_tasks.
    Safe to call from multiple processes - uses lease-based claiming.
    
    Args:
        max_tasks: Maximum tasks to process (None = all pending)
        db_path: Database path override
    
    Returns:
        Dict with tasks_processed, files_discovered counts
    """
    conn = get_connection(db_path)
    
    try:
        result = run_discovery(conn, max_tasks=max_tasks)
        return {
            "success": True,
            "tasks_processed": result.get("tasks_processed", 0),
            "files_discovered": result.get("files_discovered", 0),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
    finally:
        conn.close()


def run_build_batch(
    max_tasks: Optional[int] = None,
    db_path: Optional[Path] = None,
) -> dict:
    """
    Run build workers on pending tasks.
    
    This processes pending build queue items up to max_tasks.
    Safe to call from multiple processes - uses lease-based claiming.
    
    Args:
        max_tasks: Maximum tasks to process (None = process until queue empty)
        db_path: Database path override
    
    Returns:
        Dict with tasks_processed, success/error counts
    """
    conn = get_connection(db_path)
    
    try:
        result = run_build_worker(conn, max_tasks=max_tasks)
        return {
            "success": True,
            "tasks_processed": result.get("tasks_processed", 0),
            "tasks_succeeded": result.get("tasks_succeeded", 0),
            "tasks_failed": result.get("tasks_failed", 0),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
    finally:
        conn.close()


def reset_queues(
    fresh: bool = False,
    db_path: Optional[Path] = None,
) -> EnqueueResult:
    """
    Reset build queues.
    
    Args:
        fresh: If True, also clear database tables (files, asts, symbols, refs)
        db_path: Database path override
    
    Returns:
        EnqueueResult indicating success/failure
    """
    conn = get_connection(db_path)
    
    try:
        reset_qbuilder_tables(conn, fresh=fresh)
        conn.commit()
        
        message = "Queues reset (fresh rebuild)" if fresh else "Queues reset"
        return EnqueueResult(
            success=True,
            message=message,
        )
    except Exception as e:
        return EnqueueResult(
            success=False,
            message="Failed to reset queues",
            error=str(e),
        )
    finally:
        conn.close()


def enqueue_file(
    mod_name: str,
    rel_path: str,
    content: Optional[str] = None,
    priority: int = 1,  # 1 = flash priority
    db_path: Optional[Path] = None,
) -> dict:
    """
    Enqueue a single file for flash update.
    
    This is the primary API for single-file updates after agent mutations.
    Uses PRIORITY_FLASH (1) by default for fast processing.
    
    Args:
        mod_name: Mod name (maps to content_version via mod_packages)
        rel_path: Relative path within the mod
        content: Optional file content (if None, reads from disk)
        priority: 0=normal, 1=flash (default=flash)
        db_path: Database path override
    
    Returns:
        Dict with success, build_id, file_id, message
    """
    # Import here to avoid circular dependency
    from .api import enqueue_file as _enqueue_file, EnqueueResult as ApiResult
    
    result: ApiResult = _enqueue_file(
        mod_name=mod_name,
        rel_path=rel_path,
        content=content,
        priority=priority,
        db_path=db_path,
    )
    
    return {
        "success": result.success,
        "build_id": result.build_id,
        "file_id": result.file_id,
        "message": result.message,
        "already_queued": result.already_queued,
    }


# =============================================================================
# Helper Functions
# =============================================================================

def _get_playsets_dir() -> Path:
    """Get playsets directory."""
    return Path(__file__).parent.parent / 'playsets'


def _get_playset_manifest_path() -> Path:
    """Get active playset manifest path."""
    return _get_playsets_dir() / 'playset_manifest.json'


def _get_active_playset_file() -> Optional[Path]:
    """Get the active playset JSON file path."""
    manifest_path = _get_playset_manifest_path()
    if not manifest_path.exists():
        return None
    
    with open(manifest_path, 'r', encoding='utf-8-sig') as f:
        manifest = json.load(f)
    
    active_file = manifest.get('active')
    if not active_file:
        return None
    
    return _get_playsets_dir() / active_file
