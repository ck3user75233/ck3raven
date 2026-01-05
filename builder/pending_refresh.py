"""
Ephemeral pending refresh log for deferred file processing.

When the MCP server writes files while the builder daemon is running,
instead of blocking on DB lock, it appends to this log. The builder
processes the log after completing its main phases.

Log format (one entry per line):
    WRITE|mod_name|rel_path
    DELETE|mod_name|rel_path

The log file is atomic-append safe and cleared after processing.
"""

from pathlib import Path
import os

# Log location - same dir as other daemon files
PENDING_REFRESH_LOG = Path.home() / ".ck3raven" / "daemon" / "pending_refresh.log"


def append_pending_write(mod_name: str, rel_path: str) -> bool:
    """
    Append a write operation to the pending refresh log.
    
    Thread/process safe via file locking.
    Returns True if successfully appended.
    """
    try:
        PENDING_REFRESH_LOG.parent.mkdir(parents=True, exist_ok=True)
        
        entry = f"WRITE|{mod_name}|{rel_path}\n"
        
        # Atomic append with lock
        with open(PENDING_REFRESH_LOG, "a", encoding="utf-8") as f:
            # On Windows, use msvcrt; on Unix, use fcntl
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    f.write(entry)
                finally:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.write(entry)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        
        return True
    except Exception:
        return False


def append_pending_delete(mod_name: str, rel_path: str) -> bool:
    """
    Append a delete operation to the pending refresh log.
    
    Thread/process safe via file locking.
    Returns True if successfully appended.
    """
    try:
        PENDING_REFRESH_LOG.parent.mkdir(parents=True, exist_ok=True)
        
        entry = f"DELETE|{mod_name}|{rel_path}\n"
        
        # Atomic append with lock
        with open(PENDING_REFRESH_LOG, "a", encoding="utf-8") as f:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    f.write(entry)
                finally:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.write(entry)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        
        return True
    except Exception:
        return False


def read_and_clear_pending() -> list[tuple[str, str, str]]:
    """
    Read all pending entries and clear the log.
    
    Returns list of (operation, mod_name, rel_path) tuples.
    Atomic read-and-clear to prevent double-processing.
    """
    if not PENDING_REFRESH_LOG.exists():
        return []
    
    entries = []
    
    try:
        # Read and truncate atomically
        with open(PENDING_REFRESH_LOG, "r+", encoding="utf-8") as f:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    content = f.read()
                    f.seek(0)
                    f.truncate()
                finally:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    content = f.read()
                    f.seek(0)
                    f.truncate()
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        
        # Parse entries
        for line in content.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                entries.append((parts[0], parts[1], parts[2]))
    
    except Exception:
        pass
    
    return entries


def has_pending() -> bool:
    """Check if there are pending refresh entries."""
    if not PENDING_REFRESH_LOG.exists():
        return False
    try:
        return PENDING_REFRESH_LOG.stat().st_size > 0
    except Exception:
        return False


def get_pending_count() -> int:
    """Get count of pending entries without clearing."""
    if not PENDING_REFRESH_LOG.exists():
        return 0
    try:
        content = PENDING_REFRESH_LOG.read_text(encoding="utf-8")
        return len([l for l in content.strip().split("\n") if l])
    except Exception:
        return 0
