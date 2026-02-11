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

    Walks the capability matrix and returns S or D:
      1. Guard: root_category must be resolved
      2. cap = get_capability(mode, root, subdir, relpath)
      3. cap.allows(operation) → EN-WRITE-D-001 if not
      4. cap.contract_required → EN-WRITE-D-002 if no contract
      5. EN-WRITE-S-001

    Returns:
        EnforcementResult with reply_type and code.
    """
    from ..capability_matrix import get_capability

    # Guard: unresolved root_category
    if resolved.root_category is None:
        return EnforcementResult(
            reply_type="D",
            code="EN-GATE-D-001",
            data={"detail": "unresolved root category"},
        )

    root = resolved.root_category

    # Walk the matrix
    cap = get_capability(mode, root, resolved.subdirectory, resolved.relative_path)

    # Operation allowed?
    if not cap.allows(operation):
        return EnforcementResult(
            reply_type="D",
            code="EN-WRITE-D-001",
            data={"detail": f"{operation.name} not permitted for ({mode}, {root.name})"},
        )

    # Contract required?
    if cap.contract_required and not has_contract:
        return EnforcementResult(
            reply_type="D",
            code="EN-WRITE-D-002",
            data={"root": root.name},
        )

    return EnforcementResult(reply_type="S", code="EN-WRITE-S-001")
