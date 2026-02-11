"""
Enforcement Module - Single gate for all policy decisions.

This is THE single enforcement boundary (Canonical Architecture Rule 1).
All "can I do X?" questions go through enforce().

SCOPE:
  Gates WRITE and DELETE via the capability matrix.
  READ visibility is WorldAdapter's domain.

Reply-System-compatible (EN layer emits S, D, E — never I).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

# OperationType lives in capability_matrix (the matrix's vocabulary).
# Re-exported here so consumers can keep importing from enforcement.
from ..capability_matrix import OperationType as OperationType  # noqa: PLC0414

if TYPE_CHECKING:
    from ..world_adapter import ResolutionResult


@dataclass(frozen=True)
class EnforcementResult:
    """Reply-System-compatible enforcement result."""
    reply_type: Literal["S", "D", "E"]
    code: str
    data: dict[str, Any] = field(default_factory=dict)


def enforce(
    mode: str,
    operation: OperationType,
    resolved: "ResolutionResult",
    has_contract: bool,
) -> EnforcementResult:
    """
    Single enforcement entry point.

    Guard null root → cap.gate(operation, ...) → denial or success.
    """
    from ..capability_matrix import get_capability

    if resolved.root_category is None:
        return EnforcementResult("D", "EN-GATE-D-001", {"detail": "unresolved root category"})

    cap = get_capability(mode, resolved.root_category, resolved.subdirectory, resolved.relative_path)
    denial = cap.gate(operation, has_contract=has_contract)

    if denial:
        return EnforcementResult("D", denial, {"operation": operation.name, "root": resolved.root_category.name})

    return EnforcementResult("S", "EN-WRITE-S-001")
