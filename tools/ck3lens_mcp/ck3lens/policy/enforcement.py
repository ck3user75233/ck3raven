"""
Enforcement Module - Single gate for all policy decisions.

This is THE single enforcement boundary (Canonical Architecture Rule 1).
All "can I do X?" questions go through enforce().

CRITICAL: No permission checks may exist outside this module.

Returns Reply-System-compatible results (Canonical Reply System §4):
  EN layer may emit: S, D, E (never I).
  Consumers branch on reply_type and code, never on message text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ..world_adapter import ResolutionResult


# =============================================================================
# OPERATION TYPES
# =============================================================================

class OperationType(Enum):
    """
    Canonical operation types for capability matrix lookup.

    READ = can read
    WRITE = any mutation (may require contract per matrix)
    DELETE = deletion (may require contract per matrix)
    """
    READ = auto()
    WRITE = auto()
    DELETE = auto()


# =============================================================================
# ENFORCEMENT RESULT (Reply-compatible)
# =============================================================================

@dataclass(frozen=True)
class EnforcementResult:
    """
    Reply-System-compatible enforcement result.

    EN layer may emit: S, D, E (never I per Canonical Reply System §4).
    Consumers branch on reply_type and code, not on message text.

    Codes are registered in reply_codes.py (Codes class).
    """
    reply_type: Literal["S", "D", "E"]
    code: str
    data: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# HELPER: Detect subdirectory-aware roots
# =============================================================================

def _get_subdirectory_aware_roots() -> set:
    """
    Return set of (mode, root) pairs that have subdirectory-specific entries.

    These roots require subdirectory to be set for proper capability lookup.
    If subdirectory is None for these roots during write/delete, it's a bug.
    """
    from ..capability_matrix import CAPABILITY_MATRIX

    subdir_roots = set()
    for (mode, root, subdir) in CAPABILITY_MATRIX.keys():
        if subdir is not None:
            subdir_roots.add((mode, root))
    return subdir_roots


# =============================================================================
# MAIN ENFORCEMENT FUNCTION
# =============================================================================

def enforce(
    mode: str,
    operation: OperationType,
    resolved: "ResolutionResult",
    has_contract: bool,
) -> EnforcementResult:
    """
    Single enforcement entry point.

    This is THE canonical enforcement function (Canonical Architecture Rule 1).
    All permission decisions flow through here.

    Returns:
        EnforcementResult with reply_type ("S", "D", "E") and code.
        Consumers use code to determine specific denial reason
        (e.g., EN-OPEN-D-001 = contract required).
    """
    from ..paths import RootCategory
    from ..capability_matrix import get_capability

    # ==========================================================================
    # GUARD: Unresolved root_category is always DENY
    # ==========================================================================
    if resolved.root_category is None:
        return EnforcementResult(
            reply_type="D",
            code="EN-GATE-D-001",
            data={"path": str(resolved.absolute_path), "detail": "unresolved root category"},
        )

    # Local binding — Pylance now knows root is RootCategory, not Optional
    root = resolved.root_category

    # ==========================================================================
    # INVARIANT 1: ROOT_EXTERNAL is always DENY
    # ==========================================================================
    if root == RootCategory.ROOT_EXTERNAL:
        return EnforcementResult(
            reply_type="D",
            code="EN-GATE-D-001",
            data={"path": str(resolved.absolute_path), "detail": "outside all known roots"},
        )

    # ==========================================================================
    # INVARIANT 2: Database paths are never writable by tools
    # ==========================================================================
    if root == RootCategory.ROOT_CK3RAVEN_DATA:
        if resolved.subdirectory in {"db", "daemon"}:
            if operation in {OperationType.WRITE, OperationType.DELETE}:
                return EnforcementResult(
                    reply_type="D",
                    code="EN-WRITE-D-001",
                    data={"detail": "database and daemon files are owned by QBuilder daemon"},
                )

    # ==========================================================================
    # LOUD FAILURE: Missing subdirectory for subdirectory-aware roots
    # ==========================================================================
    if operation in {OperationType.WRITE, OperationType.DELETE}:
        subdir_aware = _get_subdirectory_aware_roots()
        if (mode, root) in subdir_aware and resolved.subdirectory is None:
            return EnforcementResult(
                reply_type="D",
                code="EN-GATE-D-001",
                data={
                    "path": str(resolved.absolute_path),
                    "detail": f"resolution missing subdirectory for {root.name}",
                    "diagnostic": True,
                },
            )

    # ==========================================================================
    # STEP 1: Look up capability from matrix
    # ==========================================================================
    cap = get_capability(mode, root, resolved.subdirectory, resolved.relative_path)

    if cap is None:
        return EnforcementResult(
            reply_type="D",
            code="EN-GATE-D-001",
            data={"detail": f"no capability for ({mode}, {root.name}, {resolved.subdirectory})"},
        )

    # ==========================================================================
    # STEP 2: Check operation against capability
    # ==========================================================================

    # READ
    if operation == OperationType.READ:
        if cap.read:
            return EnforcementResult(reply_type="S", code="EN-READ-S-001")
        return EnforcementResult(
            reply_type="D",
            code="EN-READ-D-001",
            data={"detail": f"read not permitted for ({mode}, {root.name})"},
        )

    # WRITE
    if operation == OperationType.WRITE:
        if not cap.write:
            return EnforcementResult(
                reply_type="D",
                code="EN-WRITE-D-001",
                data={"detail": f"write not permitted for ({mode}, {root.name})"},
            )
        if cap.contract_required and not has_contract:
            return EnforcementResult(
                reply_type="D",
                code="EN-OPEN-D-001",
                data={"root": root.name},
            )
        return EnforcementResult(reply_type="S", code="EN-WRITE-S-001")

    # DELETE
    if operation == OperationType.DELETE:
        if not cap.delete:
            return EnforcementResult(
                reply_type="D",
                code="EN-WRITE-D-001",
                data={"detail": f"delete not permitted for ({mode}, {root.name})"},
            )
        if cap.contract_required and not has_contract:
            return EnforcementResult(
                reply_type="D",
                code="EN-OPEN-D-001",
                data={"root": root.name},
            )
        return EnforcementResult(reply_type="S", code="EN-WRITE-S-001")

    # Unknown operation
    return EnforcementResult(
        reply_type="D",
        code="EN-GATE-D-001",
        data={"detail": f"unknown operation: {operation}"},
    )
