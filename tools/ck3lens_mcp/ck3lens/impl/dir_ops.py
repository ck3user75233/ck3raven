"""
ck3_dir implementation — directory navigation for canonical addressing v2.

Sprint 0 vertical slice. Consumer of WorldAdapterV2.

Commands:
    pwd   — return current session home root
    cd    — change session home root (root category only, no subdirs)
    list  — list immediate children of a directory
    tree  — recursive directory listing (dirs only, depth-limited)

Session navigation state (_session_home_root) is module-level.
WA2 remains stateless. Migrate to SessionContext in Sprint 1.

Directive: Canonical Addressing Refactor Directive (Authoritative)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal, Optional

from ck3lens.leak_detector import HostPathLeakError, check_no_host_paths
from ck3lens.capability_matrix_v2 import VALID_ROOT_KEYS
from ck3lens.world_adapter_v2 import (
    VisibilityRef,
    WorldAdapterV2,
)

logger = logging.getLogger(__name__)

# ============================================================================
# Session Navigation State (Sprint 0: module-level, migrate Sprint 1)
# ============================================================================

_session_home_root: str = "ck3raven_data"  # v2 root key, not RootCategory enum


def get_session_home_root() -> str:
    """Get the current session home root key."""
    return _session_home_root


def set_session_home_root(key: str) -> None:
    """Set session home root. Validates key is in VALID_ROOT_KEYS."""
    global _session_home_root
    if key not in VALID_ROOT_KEYS:
        raise ValueError(f"Unknown root key: {key!r}. Valid: {sorted(VALID_ROOT_KEYS)}")
    _session_home_root = key


# ============================================================================
# ck3_dir implementation
# ============================================================================

def ck3_dir_impl(
    command: Literal["pwd", "cd", "list", "tree"],
    path: str | None = None,
    depth: int = 3,
    *,
    wa2: WorldAdapterV2,
    rb: Any = None,
) -> dict:
    """
    Implementation for the ck3_dir MCP tool.

    Returns a dict suitable for Reply.data. Raises HostPathLeakError if
    the leak detector catches a host path in the output.

    Args:
        wa2: WorldAdapterV2 instance
        rb: ReplyBuilder for constructing Reply (passed through to wa2.resolve)
    """
    if command == "pwd":
        return _cmd_pwd()
    elif command == "cd":
        return _cmd_cd(path)
    elif command == "list":
        return _cmd_list(path, wa2=wa2, rb=rb)
    elif command == "tree":
        return _cmd_tree(path, depth=depth, wa2=wa2, rb=rb)
    else:
        raise ValueError(f"Unknown ck3_dir command: {command!r}")


# ============================================================================
# Command implementations
# ============================================================================

def _cmd_pwd() -> dict:
    """Return current session home root."""
    home = _session_home_root
    return {
        "home": f"root:{home}/",
        "root_category": home,
    }


def _cmd_cd(path: str | None) -> dict:
    """Change session home root (root category only, no subdirectory homing)."""
    if not path:
        raise ValueError("cd requires a path argument (e.g. 'root:repo')")

    # Accept both 'root:repo' and bare 'repo'
    key = path
    if key.startswith("root:"):
        key = key[5:]

    # Strip trailing slash
    key = key.rstrip("/")

    # Reject subdirectory homing (Sprint 0 restriction)
    if "/" in key:
        raise ValueError(
            f"Subdirectory homing not allowed in Sprint 0. "
            f"Use a root key only: {sorted(VALID_ROOT_KEYS)}"
        )

    if key not in VALID_ROOT_KEYS:
        raise ValueError(f"Unknown root key: {key!r}. Valid: {sorted(VALID_ROOT_KEYS)}")

    set_session_home_root(key)
    return {
        "home": f"root:{key}/",
        "root_category": key,
    }


def _cmd_list(path: str | None, *, wa2: WorldAdapterV2, rb: Any = None) -> dict:
    """List immediate children of a directory."""
    address = _resolve_with_home(path)
    reply, ref = wa2.resolve(address, require_exists=True, rb=rb)

    if ref is None:
        raise ValueError(reply.message or "Invalid path / not found")

    host = wa2.host_path(ref)
    if host is None:
        raise ValueError("Token lookup failed (internal error)")

    if not host.is_dir():
        raise ValueError(f"Not a directory: {ref.session_abs}")

    entries = []
    for child in sorted(host.iterdir()):
        child_name = child.name
        is_dir = child.is_dir()
        child_session_abs = f"{ref.session_abs}/{child_name}"
        entries.append({
            "name": child_name,
            "path": child_session_abs + ("/" if is_dir else ""),
            "type": "dir" if is_dir else "file",
        })

    data = {
        "target": ref.session_abs,
        "entries": entries,
        "count": len(entries),
    }

    # Leak gate — safety net
    check_no_host_paths(data, context="ck3_dir.list")
    return data


def _cmd_tree(
    path: str | None, *, depth: int, wa2: WorldAdapterV2, rb: Any = None,
) -> dict:
    """Recursive directory listing (directories only)."""
    address = _resolve_with_home(path)
    reply, ref = wa2.resolve(address, require_exists=True, rb=rb)

    if ref is None:
        raise ValueError(reply.message or "Invalid path / not found")

    host = wa2.host_path(ref)
    if host is None:
        raise ValueError("Token lookup failed (internal error)")

    if not host.is_dir():
        raise ValueError(f"Not a directory: {ref.session_abs}")

    dirs = _walk_dirs(host, ref.session_abs, depth)

    data = {
        "target": ref.session_abs,
        "depth": depth,
        "directories": dirs,
    }

    check_no_host_paths(data, context="ck3_dir.tree")
    return data


# ============================================================================
# Helpers
# ============================================================================

def _resolve_with_home(path: str | None) -> str:
    """
    If path is None or empty, return the session home root address.
    If path is a bare relative path (no colon), prepend the home root.
    Otherwise return as-is (canonical or legacy address).
    """
    if not path or path.strip() == "":
        return f"root:{_session_home_root}"

    path = path.strip()

    # Already a canonical or legacy address
    if ":" in path:
        return path

    # Bare relative path → prepend home root
    return f"root:{_session_home_root}/{path}"


def _walk_dirs(
    host_path: Path, session_abs: str, remaining_depth: int,
) -> list[dict]:
    """
    Recursively walk directories, returning a tree structure.

    Only includes directories (files excluded from tree output).
    Uses session-absolute paths exclusively — no host paths in output.
    """
    if remaining_depth <= 0:
        return []

    result = []
    try:
        children = sorted(host_path.iterdir())
    except PermissionError:
        return []

    for child in children:
        if child.is_dir():
            child_session = f"{session_abs}/{child.name}"
            subtree = _walk_dirs(child, child_session, remaining_depth - 1)
            result.append({
                "name": child.name,
                "path": child_session + "/",
                "children": subtree,
            })

    return result
