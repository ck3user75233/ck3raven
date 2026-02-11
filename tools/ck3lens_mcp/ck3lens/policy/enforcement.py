"""
Enforcement Module - Single gate for all policy decisions.

This is THE single enforcement boundary (Canonical Architecture Rule 1).
All "can I do X?" questions go through enforce().

CRITICAL: No permission checks may exist outside this module.

SCOPE:
  Enforcement gates WRITE and DELETE operations only.
  READ visibility is WorldAdapter's domain (WA-RES-I-003).
  Enforcement is not called for reads.

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
    """Canonical operation types for capability matrix lookup."""
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

    Gates WRITE and DELETE operations against the capability matrix.
    READ is not enforcement's domain (WorldAdapter handles visibility).

    Flow:
      1. Resolve root_category — deny if None
      2. Look up Capability from matrix via get_capability()
      3. Check cap.write (for WRITE) or cap.delete (for DELETE)
      4. Check cap.contract_required — matrix-driven, not hardcoded
      5. Return S or D

    Returns:
        EnforcementResult with reply_type ("S", "D", "E") and code.
        Consumers use code to determine specific denial reason
        (e.g., EN-OPEN-D-001 = contract required).
    """
    from ..capability_matrix import get_capability

    # ==========================================================================
    # GUARD: Unresolved root_category is always DENY
    # ==========================================================================
    if resolved.root_category is None:
        return EnforcementResult(
            reply_type="D",
            code="EN-GATE-D-001",
            data={"detail": "unresolved root category"},
        )

    # Local binding — Pylance knows root is RootCategory, not Optional
    root = resolved.root_category

    # ==========================================================================
    # Look up capability from matrix (always returns Capability, never None)
    # ==========================================================================
    cap = get_capability(mode, root, resolved.subdirectory, resolved.relative_path)

    # ==========================================================================
    # Gate: operation allowed by matrix?
    #
    # cap.write = matrix says writes are possible for this (mode, root, subdir)
    # cap.delete = matrix says deletes are possible for this (mode, root, subdir)
    # These are separate flags because some entries allow write but not delete.
    # ==========================================================================
    if operation == OperationType.WRITE and not cap.write:
        return EnforcementResult(
            reply_type="D",
            code="EN-WRITE-D-001",
            data={"detail": f"write not permitted for ({mode}, {root.name})"},
        )

    if operation == OperationType.DELETE and not cap.delete:
        return EnforcementResult(
            reply_type="D",
            code="EN-WRITE-D-001",
            data={"detail": f"delete not permitted for ({mode}, {root.name})"},
        )

    # ==========================================================================
    # Gate: contract required? (matrix-driven via cap.contract_required)
    #
    # cap.contract_required comes from get_capability() — the matrix entry.
    # WIP entries have contract_required=False; most others have True.
    # EN-OPEN-D-001 = "CONTRACT_REQUIRED" — OPEN area is contract lifecycle.
    # ==========================================================================
    if operation in {OperationType.WRITE, OperationType.DELETE}:
        if cap.contract_required and not has_contract:
            return EnforcementResult(
                reply_type="D",
                code="EN-OPEN-D-001",
                data={"root": root.name},
            )

    # ==========================================================================
    # Authorized
    # ==========================================================================
    return EnforcementResult(reply_type="S", code="EN-WRITE-S-001")
