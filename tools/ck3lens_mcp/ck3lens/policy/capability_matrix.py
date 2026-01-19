"""
Capability Matrix — Constitutional Law for Contract Authorization

This module defines THE authoritative truth table for all authorization decisions.
It is a standalone module that:
- Does NOT inspect files
- Does NOT inspect targets
- Does NOT inspect intent
- ONLY evaluates capability feasibility based on (mode, root_category, operation)

Authority: CANONICAL CONTRACT SYSTEM, Appendix A
Status: HARD LAW - No heuristics, no exceptions

Usage:
    from ck3lens.policy.capability_matrix import is_authorized, RootCategory, Operation, AgentMode
    
    result = is_authorized(
        mode=AgentMode.CK3LENS,
        root=RootCategory.ROOT_USER_DOCS,
        operation=Operation.WRITE,
    )
    # Returns: True (allowed) or False (denied)
"""
from __future__ import annotations

from enum import Enum
from typing import NamedTuple


# =============================================================================
# ENUMS (Exact values from CANONICAL CONTRACT SYSTEM)
# =============================================================================

class AgentMode(str, Enum):
    """Agent modes. These differ in what they may request, not how rules are interpreted."""
    CK3LENS = "ck3lens"           # Operational mode (controlled mutation)
    CK3RAVEN_DEV = "ck3raven-dev" # Diagnostic mode (non-operational)


class RootCategory(str, Enum):
    """
    Geographic root categories.
    
    Every contract operates within exactly ONE geographic root.
    Roots define enforcement domain. Multi-root work requires multiple contracts.
    """
    ROOT_REPO = "ROOT_REPO"           # CK3Raven tool source
    ROOT_USER_DOCS = "ROOT_USER_DOCS" # User-authored mod content
    ROOT_WIP = "ROOT_WIP"             # Scratch / experimental workspace
    ROOT_STEAM = "ROOT_STEAM"         # Steam Workshop content
    ROOT_GAME = "ROOT_GAME"           # Vanilla CK3 installation
    ROOT_UTILITIES = "ROOT_UTILITIES" # Runtime logs & diagnostics
    ROOT_LAUNCHER = "ROOT_LAUNCHER"   # Paradox launcher registry


class Operation(str, Enum):
    """
    Operations describe requested capability, not execution method.
    """
    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"
    RENAME = "RENAME"
    EXECUTE = "EXECUTE"
    DB_WRITE = "DB_WRITE"
    GIT_WRITE = "GIT_WRITE"


# =============================================================================
# CAPABILITY MATRIX (Constitutional Truth Table)
# =============================================================================

class _Capability(NamedTuple):
    """Internal: capability specification for a (mode, root) pair."""
    read: bool
    write: bool  # Includes DELETE, RENAME for file operations


# The canonical matrix from Appendix A
# Key: (AgentMode, RootCategory) -> _Capability(read, write)
_MATRIX: dict[tuple[AgentMode, RootCategory], _Capability] = {
    # ck3lens mode capabilities
    (AgentMode.CK3LENS, RootCategory.ROOT_REPO): _Capability(read=True, write=False),
    (AgentMode.CK3LENS, RootCategory.ROOT_USER_DOCS): _Capability(read=True, write=True),
    (AgentMode.CK3LENS, RootCategory.ROOT_WIP): _Capability(read=True, write=True),
    (AgentMode.CK3LENS, RootCategory.ROOT_STEAM): _Capability(read=True, write=False),
    (AgentMode.CK3LENS, RootCategory.ROOT_GAME): _Capability(read=True, write=False),
    (AgentMode.CK3LENS, RootCategory.ROOT_UTILITIES): _Capability(read=True, write=False),
    (AgentMode.CK3LENS, RootCategory.ROOT_LAUNCHER): _Capability(read=True, write=True),  # Repair-only
    
    # ck3raven-dev mode capabilities
    (AgentMode.CK3RAVEN_DEV, RootCategory.ROOT_REPO): _Capability(read=True, write=True),
    (AgentMode.CK3RAVEN_DEV, RootCategory.ROOT_USER_DOCS): _Capability(read=True, write=False),
    (AgentMode.CK3RAVEN_DEV, RootCategory.ROOT_WIP): _Capability(read=True, write=True),
    (AgentMode.CK3RAVEN_DEV, RootCategory.ROOT_STEAM): _Capability(read=True, write=False),
    (AgentMode.CK3RAVEN_DEV, RootCategory.ROOT_GAME): _Capability(read=True, write=False),
    (AgentMode.CK3RAVEN_DEV, RootCategory.ROOT_UTILITIES): _Capability(read=True, write=False),
    (AgentMode.CK3RAVEN_DEV, RootCategory.ROOT_LAUNCHER): _Capability(read=True, write=False),
}


# =============================================================================
# AUTHORIZATION API
# =============================================================================

def is_authorized(
    mode: AgentMode | str,
    root: RootCategory | str,
    operation: Operation | str,
) -> bool:
    """
    Check if an operation is authorized for the given mode and root.
    
    This is the SOLE source of authorization truth.
    
    Args:
        mode: Agent mode (ck3lens or ck3raven-dev)
        root: Geographic root category
        operation: Requested operation
    
    Returns:
        True if authorized, False if denied
    
    Raises:
        ValueError: If mode, root, or operation is invalid
    """
    # Normalize to enums
    if isinstance(mode, str):
        mode = AgentMode(mode)
    if isinstance(root, str):
        root = RootCategory(root)
    if isinstance(operation, str):
        operation = Operation(operation)
    
    # Lookup capability
    key = (mode, root)
    cap = _MATRIX.get(key)
    
    if cap is None:
        # Unknown combination = denied
        return False
    
    # Map operation to capability
    if operation == Operation.READ:
        return cap.read
    elif operation in {Operation.WRITE, Operation.DELETE, Operation.RENAME}:
        return cap.write
    elif operation == Operation.EXECUTE:
        # EXECUTE only allowed in WIP
        return root == RootCategory.ROOT_WIP and cap.write
    elif operation == Operation.DB_WRITE:
        # DB_WRITE only allowed for daemon (ck3raven-dev with ROOT_REPO)
        return mode == AgentMode.CK3RAVEN_DEV and root == RootCategory.ROOT_REPO
    elif operation == Operation.GIT_WRITE:
        # GIT_WRITE follows write permission
        return cap.write
    else:
        # Unknown operation = denied
        return False


def get_capability(
    mode: AgentMode | str,
    root: RootCategory | str,
) -> tuple[bool, bool]:
    """
    Get (read, write) capability for a mode/root pair.
    
    Returns:
        (read_allowed, write_allowed)
    """
    if isinstance(mode, str):
        mode = AgentMode(mode)
    if isinstance(root, str):
        root = RootCategory(root)
    
    cap = _MATRIX.get((mode, root))
    if cap is None:
        return (False, False)
    return (cap.read, cap.write)


def validate_operations(
    mode: AgentMode | str,
    root: RootCategory | str,
    operations: list[Operation | str],
) -> tuple[bool, list[str]]:
    """
    Validate a list of operations against the capability matrix.
    
    Args:
        mode: Agent mode
        root: Geographic root
        operations: List of requested operations
    
    Returns:
        (all_valid: bool, denied_operations: list[str])
    """
    denied = []
    
    for op in operations:
        if not is_authorized(mode, root, op):
            op_str = op.value if isinstance(op, Operation) else op
            denied.append(op_str)
    
    return (len(denied) == 0, denied)


# =============================================================================
# DEBUG / INTROSPECTION
# =============================================================================

def dump_matrix() -> dict:
    """
    Dump the capability matrix for debugging/documentation.
    
    Returns:
        Dict representation of the full matrix
    """
    result = {}
    for (mode, root), cap in _MATRIX.items():
        mode_key = mode.value
        if mode_key not in result:
            result[mode_key] = {}
        result[mode_key][root.value] = {
            "read": cap.read,
            "write": cap.write,
        }
    return result
