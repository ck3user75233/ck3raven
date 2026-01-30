"""Log rotation for MCP server logs.

Daily rotation with 7-day retention. Call rotate_logs() at server startup.

See docs/CANONICAL_LOGS.md for full specification.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

_LOG_DIR = Path.home() / ".ck3raven" / "logs"
_LOG_FILE = _LOG_DIR / "ck3raven-mcp.log"
_RETENTION_DAYS = 7


def rotate_logs() -> bool:
    """Rotate logs if current log is from a previous day.
    
    Returns True if rotation occurred, False otherwise.
    Never raises - fails silently to avoid blocking startup.
    """
    if not _LOG_FILE.exists():
        return False

    try:
        # Check if log file is from a previous day
        log_mtime = datetime.fromtimestamp(_LOG_FILE.stat().st_mtime, tz=timezone.utc)
        if log_mtime.date() >= datetime.now(timezone.utc).date():
            # Log is from today, no rotation needed
            return False

        # Rotate existing logs (newest = .1, oldest = .7)
        # Delete oldest if at retention limit
        for i in range(_RETENTION_DAYS - 1, 0, -1):
            old = _LOG_DIR / f"ck3raven-mcp.log.{i}"
            new = _LOG_DIR / f"ck3raven-mcp.log.{i + 1}"
            if old.exists():
                if i == _RETENTION_DAYS - 1:
                    # Delete oldest (would become .8)
                    old.unlink()
                else:
                    old.rename(new)

        # Rotate current log to .1
        _LOG_FILE.rename(_LOG_DIR / "ck3raven-mcp.log.1")
        return True

    except Exception:
        # Don't fail startup due to rotation issues
        return False


def cleanup_old_logs() -> int:
    """Delete log files older than retention period.
    
    Returns count of files deleted.
    """
    if not _LOG_DIR.exists():
        return 0

    deleted = 0
    try:
        cutoff = datetime.now(timezone.utc).timestamp() - (_RETENTION_DAYS * 24 * 60 * 60)
        
        for log_file in _LOG_DIR.glob("ck3raven-mcp.log.*"):
            try:
                if log_file.stat().st_mtime < cutoff:
                    log_file.unlink()
                    deleted += 1
            except Exception:
                continue
    except Exception:
        pass

    return deleted


def get_all_log_files() -> list[Path]:
    """Get all MCP log files in order (current first, then .1, .2, etc.)."""
    files = []
    
    if _LOG_FILE.exists():
        files.append(_LOG_FILE)
    
    for i in range(1, _RETENTION_DAYS + 1):
        rotated = _LOG_DIR / f"ck3raven-mcp.log.{i}"
        if rotated.exists():
            files.append(rotated)
    
    return files


def get_log_size_bytes() -> int:
    """Get total size of all MCP log files in bytes."""
    total = 0
    for f in get_all_log_files():
        try:
            total += f.stat().st_size
        except Exception:
            continue
    return total
