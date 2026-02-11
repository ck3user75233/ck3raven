"""
Enforcement — THE single gate for all policy decisions.

Canonical Architecture Rule 1: only this module may deny operations.

Walks the capability matrix:
  1. Guard: root must be resolved
  2. Lookup: cap = get_capability(...)
  3. Gate: operation in cap.operations AND all conditions pass → ALLOW
     Otherwise → DENY with every failure listed

Returns Reply (the canonical type), never a parallel concept.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ck3raven.core.reply import Reply

# OperationType lives in capability_matrix (the matrix's vocabulary).
# Re-exported here so consumers can keep importing from enforcement.
from ..capability_matrix import OperationType as OperationType  # noqa: PLC0414

if TYPE_CHECKING:
    from ..capability_matrix import Capability
    from ..world_adapter import ResolutionResult


def _gate(cap: "Capability", operation: OperationType, **context: Any) -> list[str]:
    """
    Evaluate capability against operation and all conditions.

    Returns empty list if allowed, or every applicable denial code.
    """
    denials = [c.denial for c in cap.conditions if not c.check(**context)]
    if operation not in cap.operations:
        denials.insert(0, "EN-WRITE-D-001")
    return denials


def enforce(
    rb: Any,  # ReplyBuilder — passed from tool handler, constructs Reply with trace/meta
    mode: str,
    operation: OperationType,
    resolved: "ResolutionResult",
    has_contract: bool,
) -> Reply:
    """Single enforcement entry point. Returns Reply directly."""
    from ..capability_matrix import get_capability

    if resolved.root_category is None:
        return rb.denied("EN-GATE-D-001", {"detail": "unresolved root category"})

    cap = get_capability(mode, resolved.root_category, resolved.subdirectory, resolved.relative_path)
    denials = _gate(cap, operation, has_contract=has_contract)

    if denials:
        return rb.denied(denials[0], {
            "denials": denials,
            "operation": operation.name,
            "root": resolved.root_category.name,
        })

    return rb.success("EN-WRITE-S-001", {})
