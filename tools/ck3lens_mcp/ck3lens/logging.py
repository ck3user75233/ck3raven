"""Canonical structured logging for MCP server.

This module provides fail-safe JSONL logging with:
- ISO 8601 UTC timestamps
- Instance ID for multi-window isolation
- Trace ID correlation for cross-component debugging
- Sensitive data redaction
- Graceful degradation on failure

See docs/CANONICAL_LOGS.md for full specification.

Usage:
    from ck3lens.logging import info, debug, error, warn, set_trace_id

    # Normal logging
    info("mcp.init", "Mode initialized", mode="ck3raven-dev")

    # With trace ID from MCP params
    set_trace_id(params.get("_trace_id", "no-trace"))
    info("mcp.tool", "Processing request", tool="ck3_file")

    # Bootstrap phase (before full init)
    bootstrap("Starting MCP server")
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Configuration
_LOG_DIR = Path.home() / ".ck3raven" / "logs"
_LOG_FILE = _LOG_DIR / "ck3raven-mcp.log"
_INSTANCE_ID = os.environ.get("CK3LENS_INSTANCE_ID", "default")
_LOG_LEVEL = os.environ.get("CK3LENS_LOG_LEVEL", "INFO").upper()

# Level ordering for filtering
_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}

# Initialization state
_initialized = False

# Thread-local trace_id context
_trace_context = threading.local()


def set_trace_id(trace_id: str) -> None:
    """Set trace ID for current operation context.
    
    Call this at the start of each MCP tool invocation with the
    _trace_id parameter from the request. This enables correlation
    of logs across extension → MCP → QBuilder.
    """
    _trace_context.trace_id = trace_id


def get_trace_id() -> str:
    """Get current trace ID or 'no-trace'."""
    return getattr(_trace_context, "trace_id", "no-trace")


def clear_trace_id() -> None:
    """Clear trace ID after operation completes."""
    _trace_context.trace_id = "no-trace"


def _ensure_log_dir() -> None:
    """Create log directory if it doesn't exist. Fail silently."""
    global _initialized
    if not _initialized:
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            _initialized = True
        except Exception:
            pass  # Fail silently - will use stderr fallback


def _should_log(level: str) -> bool:
    """Check if this level should be logged based on configured level."""
    return _LEVEL_ORDER.get(level, 1) >= _LEVEL_ORDER.get(_LOG_LEVEL, 1)


def _sanitize(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Remove or mask sensitive data.
    
    - Masks fields containing 'key', 'token', or 'secret'
    - Truncates strings longer than 1000 chars
    """
    if not data:
        return data
    
    sanitized = {}
    for k, v in data.items():
        key_lower = k.lower()
        # Mask API keys, tokens, secrets
        if "key" in key_lower or "token" in key_lower or "secret" in key_lower:
            sanitized[k] = "***REDACTED***"
        # Truncate large values
        elif isinstance(v, str) and len(v) > 1000:
            sanitized[k] = v[:1000] + "...[truncated]"
        else:
            sanitized[k] = v
    return sanitized


def _format_timestamp() -> str:
    """Format current time as ISO 8601 UTC with milliseconds."""
    now = datetime.now(timezone.utc)
    # Format: YYYY-MM-DDTHH:MM:SS.mmmZ
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def log(
    level: str,
    category: str,
    msg: str,
    data: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> None:
    """Write structured log entry with fail-safe behavior.
    
    This is the core logging function. Use the convenience wrappers
    (debug, info, warn, error) for cleaner code.
    
    Args:
        level: DEBUG, INFO, WARN, or ERROR
        category: Dot-separated category (e.g., "mcp.init", "contract.open")
        msg: Human-readable message
        data: Optional structured context (will be sanitized)
        trace_id: Optional override for trace ID (uses context if not provided)
    """
    if not _should_log(level):
        return

    _ensure_log_dir()

    entry: dict[str, Any] = {
        "ts": _format_timestamp(),
        "level": level,
        "cat": category,
        "inst": _INSTANCE_ID,
        "trace_id": trace_id or get_trace_id(),
        "msg": msg,
    }
    if data:
        entry["data"] = _sanitize(data)

    line = json.dumps(entry) + "\n"

    # Fail-safe: try file, fall back to stderr
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # Graceful degradation - don't crash the app
        try:
            sys.stderr.write(f"[LOG FALLBACK] {line}")
        except Exception:
            pass  # Last resort: silently drop


def debug(category: str, msg: str, **data: Any) -> None:
    """Log at DEBUG level. Use for detailed diagnostic info."""
    log("DEBUG", category, msg, data or None)


def info(category: str, msg: str, **data: Any) -> None:
    """Log at INFO level. Use for normal operations."""
    log("INFO", category, msg, data or None)


def warn(category: str, msg: str, **data: Any) -> None:
    """Log at WARN level. Use for recoverable issues."""
    log("WARN", category, msg, data or None)


def error(category: str, msg: str, **data: Any) -> None:
    """Log at ERROR level. Use for failures."""
    log("ERROR", category, msg, data or None)


def bootstrap(msg: str) -> None:
    """Log during bootstrap phase (before full init).
    
    Always writes to stderr, bypasses all log configuration.
    Use this for very early initialization messages.
    """
    ts = _format_timestamp()
    try:
        sys.stderr.write(f"[BOOTSTRAP {ts}] {msg}\n")
    except Exception:
        pass  # Truly last resort


def set_instance_id(instance_id: str) -> None:
    """Override the instance ID (normally set from environment).
    
    Call this early in initialization if you need to set the instance ID
    programmatically rather than via CK3LENS_INSTANCE_ID environment variable.
    """
    global _INSTANCE_ID
    _INSTANCE_ID = instance_id


def get_log_file() -> Path:
    """Get the path to the log file (for testing/debugging)."""
    return _LOG_FILE


def get_log_level() -> str:
    """Get the current log level (for testing/debugging)."""
    return _LOG_LEVEL
