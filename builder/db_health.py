"""
Database Health Recovery for ck3raven

Automatic detection and recovery from:
1. Stale daemon lock files (daemon crashed without cleanup)
2. Large uncommitted WAL files (from crashed builds)
3. Orphaned status files showing "running" for dead processes

This module runs on MCP server startup and can be called manually.
"""

import sqlite3
import logging
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Paths
DAEMON_DIR = Path.home() / ".ck3raven" / "daemon"
DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"
WAL_PATH = DB_PATH.with_suffix(".db-wal")

# Thresholds
STALE_HEARTBEAT_SECONDS = 300  # 5 minutes - if heartbeat older than this, daemon is dead
MAX_WAL_SIZE_BYTES = 50 * 1024 * 1024  # 50MB - WAL larger than this suggests crash
WAL_CHECKPOINT_TIMEOUT = 30  # Seconds to wait for checkpoint


def check_and_recover() -> Dict[str, Any]:
    """
    Check database health and recover from stale state.
    
    Should be called:
    - On MCP server startup
    - On VS Code extension activation
    - Before any database write operation that's timing out
    
    Returns:
        {
            "healthy": bool,
            "actions_taken": list[str],
            "errors": list[str],
            "wal_size_before": int,
            "wal_size_after": int,
            "stale_daemon_detected": bool,
        }
    """
    result = {
        "healthy": True,
        "actions_taken": [],
        "errors": [],
        "wal_size_before": 0,
        "wal_size_after": 0,
        "stale_daemon_detected": False,
    }
    
    try:
        # Step 1: Check for stale daemon state
        stale_result = _check_stale_daemon()
        if stale_result["is_stale"]:
            result["stale_daemon_detected"] = True
            result["actions_taken"].append(f"Detected stale daemon: {stale_result['reason']}")
            
            # Clean up stale files
            cleanup_result = _cleanup_stale_daemon()
            result["actions_taken"].extend(cleanup_result["cleaned"])
        
        # Step 2: Check WAL size
        if WAL_PATH.exists():
            result["wal_size_before"] = WAL_PATH.stat().st_size
            
            if result["wal_size_before"] > MAX_WAL_SIZE_BYTES:
                result["actions_taken"].append(
                    f"Large WAL detected: {result['wal_size_before'] / 1024 / 1024:.1f}MB"
                )
                
                # Try to checkpoint
                checkpoint_result = _try_checkpoint()
                if checkpoint_result["success"]:
                    result["actions_taken"].append("WAL checkpoint successful")
                    result["wal_size_after"] = WAL_PATH.stat().st_size if WAL_PATH.exists() else 0
                else:
                    result["errors"].append(f"Checkpoint failed: {checkpoint_result['error']}")
                    result["healthy"] = False
        
        # Step 3: Update status if we recovered from a crash
        if result["stale_daemon_detected"]:
            _mark_build_as_crashed()
            result["actions_taken"].append("Marked stale build as 'failed'")
        
    except Exception as e:
        result["errors"].append(f"Health check failed: {e}")
        result["healthy"] = False
        logger.exception("Database health check failed")
    
    if result["actions_taken"]:
        logger.info(f"Database health recovery: {result['actions_taken']}")
    
    return result


def _check_stale_daemon() -> Dict[str, Any]:
    """Check if daemon state is stale (crashed without cleanup)."""
    heartbeat_file = DAEMON_DIR / "heartbeat"
    status_file = DAEMON_DIR / "rebuild_status.json"
    pid_file = DAEMON_DIR / "rebuild.pid"
    
    result = {"is_stale": False, "reason": None}
    
    # Check 1: Status says "running" but heartbeat is stale
    if status_file.exists() and heartbeat_file.exists():
        try:
            status = json.loads(status_file.read_text())
            if status.get("state") == "running":
                heartbeat_time = float(heartbeat_file.read_text().strip())
                age = time.time() - heartbeat_time
                
                if age > STALE_HEARTBEAT_SECONDS:
                    result["is_stale"] = True
                    result["reason"] = f"Heartbeat stale ({age/3600:.1f}h old), state still 'running'"
                    return result
        except (json.JSONDecodeError, ValueError):
            pass
    
    # Check 2: PID file exists but process is dead
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            if not _is_process_alive(pid):
                result["is_stale"] = True
                result["reason"] = f"PID file exists but process {pid} is dead"
                return result
        except ValueError:
            result["is_stale"] = True
            result["reason"] = "Invalid PID file"
            return result
    
    return result


def _is_process_alive(pid: int) -> bool:
    """Check if a process with given PID is still running."""
    import ctypes
    try:
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False


def _cleanup_stale_daemon() -> Dict[str, Any]:
    """Clean up stale daemon files."""
    result = {"cleaned": []}
    
    files_to_clean = [
        DAEMON_DIR / "rebuild.lock",
        DAEMON_DIR / "rebuild.pid",
    ]
    
    for f in files_to_clean:
        if f.exists():
            try:
                f.unlink()
                result["cleaned"].append(f"Removed {f.name}")
            except Exception as e:
                logger.warning(f"Failed to remove {f}: {e}")
    
    return result


def _try_checkpoint() -> Dict[str, Any]:
    """Try to checkpoint the WAL file."""
    try:
        # Use a short timeout - if we can't get lock quickly, don't block
        conn = sqlite3.connect(str(DB_PATH), timeout=WAL_CHECKPOINT_TIMEOUT)
        try:
            result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            # Result is (blocked, wal_pages, checkpointed_pages)
            # blocked=0 means success
            if result[0] == 0:
                return {"success": True, "pages_checkpointed": result[2]}
            else:
                return {"success": False, "error": f"Checkpoint blocked (code {result[0]})"}
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _mark_build_as_crashed() -> None:
    """Update status file to show build crashed."""
    status_file = DAEMON_DIR / "rebuild_status.json"
    
    if not status_file.exists():
        return
    
    try:
        status = json.loads(status_file.read_text())
        if status.get("state") == "running":
            status["state"] = "failed"
            status["error"] = "Build interrupted - daemon crashed (auto-recovered)"
            status["updated_at"] = datetime.now().isoformat()
            status_file.write_text(json.dumps(status, indent=2))
    except Exception as e:
        logger.warning(f"Failed to update status file: {e}")


def get_health_status() -> Dict[str, Any]:
    """
    Get current database health status without taking recovery actions.
    
    Useful for UI display.
    """
    status = {
        "db_exists": DB_PATH.exists(),
        "db_size_mb": 0,
        "wal_size_mb": 0,
        "wal_healthy": True,
        "daemon_state": "unknown",
        "daemon_stale": False,
    }
    
    if DB_PATH.exists():
        status["db_size_mb"] = round(DB_PATH.stat().st_size / 1024 / 1024, 1)
    
    if WAL_PATH.exists():
        wal_size = WAL_PATH.stat().st_size
        status["wal_size_mb"] = round(wal_size / 1024 / 1024, 1)
        status["wal_healthy"] = wal_size < MAX_WAL_SIZE_BYTES
    
    status_file = DAEMON_DIR / "rebuild_status.json"
    if status_file.exists():
        try:
            daemon_status = json.loads(status_file.read_text())
            status["daemon_state"] = daemon_status.get("state", "unknown")
        except Exception:
            pass
    
    stale_check = _check_stale_daemon()
    status["daemon_stale"] = stale_check["is_stale"]
    if stale_check["is_stale"]:
        status["stale_reason"] = stale_check["reason"]
    
    return status
