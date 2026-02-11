"""
Enforcement — THE single gate for all policy decisions.

Canonical Architecture Rule 1: only this module may deny operations.

Walks the capability matrix:
  1. Guard: root must be resolved
  2. Lookup: cap = get_capability(...)
  3. Gate: operation in cap.operations, all cap.conditions pass → allowed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

# OperationType lives in capability_matrix (the matrix's vocabulary).
# Re-exported here so consumers can keep importing from enforcement.
from ..capability_matrix import OperationType as OperationType  # noqa: PLC0414

if TYPE_CHECKING:
    from ..capability_matrix import Capability
    from ..world_adapter import ResolutionResult


@dataclass(frozen=True)
class EnforcementResult:
    """Reply-System-compatible enforcement result (S, D, E — never I)."""
    reply_type: Literal["S", "D", "E"]
    code: str
    data: dict[str, Any] = field(default_factory=dict)


def _gate(cap: "Capability", operation: OperationType, **context: Any) -> str | None:
    """
    Evaluate capability against operation and conditions.

    Returns None if allowed, or the first applicable denial code.
    """
    if operation not in cap.operations:
        return "EN-WRITE-D-001"
    return next((c.denial for c in cap.conditions if not c.check(**context)), None)


def enforce(
    mode: str,
    operation: OperationType,
    resolved: "ResolutionResult",
    has_contract: bool,
) -> EnforcementResult:
    """Single enforcement entry point."""
    from ..capability_matrix import get_capability

    if resolved.root_category is None:
        return EnforcementResult("D", "EN-GATE-D-001", {"detail": "unresolved root category"})

    cap = get_capability(mode, resolved.root_category, resolved.subdirectory, resolved.relative_path)
    denial = _gate(cap, operation, has_contract=has_contract)

    if denial:
        return EnforcementResult("D", denial, {"operation": operation.name, "root": resolved.root_category.name})

    return EnforcementResult("S", "EN-WRITE-S-001")
