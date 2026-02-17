"""
Leak Detector — Host-path leakage prevention for v2 tool output.

Sprint 0 defensive gate. Scans Reply data dicts for host-absolute path
patterns before they reach the agent. If a host path is detected, the
tool returns a terminal Error instead of leaking.

Directive: Canonical Addressing Refactor Directive (Authoritative)
"""
from __future__ import annotations

import re
from typing import Any

# Patterns that indicate a host-absolute path leaked into output.
# These should NEVER appear in agent-visible Reply data.
_HOST_PATH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[A-Za-z]:\\"),          # Windows drive (C:\)
    re.compile(r"\\\\[A-Za-z]"),         # UNC path (\\server)
    re.compile(r"/Users/[A-Za-z]"),      # macOS home
    re.compile(r"/home/[A-Za-z]"),       # Linux home
    re.compile(r"/mnt/[A-Za-z]"),        # WSL/mount
]


class HostPathLeakError(ValueError):
    """Raised when a host-absolute path is detected in tool output."""
    pass


def check_no_host_paths(data: Any, context: str = "") -> None:
    """
    Recursively scan a data structure for host-absolute path patterns.

    Raises HostPathLeakError if any host-absolute path string is found.
    Call this on Reply.data and Reply.message before returning from v2 tools.

    Args:
        data: The data structure to scan (dict, list, str, etc.)
        context: Human-readable context for error messages (e.g. "ck3_dir.list")
    """
    _scan(data, path="", context=context)


def _scan(obj: Any, path: str, context: str) -> None:
    """Recursive scanner."""
    if isinstance(obj, str):
        for pattern in _HOST_PATH_PATTERNS:
            if pattern.search(obj):
                prefix = f"in {context} " if context else ""
                truncated = obj[:80] + ("..." if len(obj) > 80 else "")
                raise HostPathLeakError(
                    f"Host-absolute path leaked {prefix}at {path}: {truncated}"
                )
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _scan(v, path=f"{path}.{k}", context=context)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _scan(v, path=f"{path}[{i}]", context=context)
    # None, int, float, bool — no leak risk, skip silently
