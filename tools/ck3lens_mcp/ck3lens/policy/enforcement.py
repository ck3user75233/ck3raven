"""
Enforcement Module - Single gate for all policy decisions.

This is THE single enforcement boundary (Canonical Architecture Rule 1).
All "can I do X?" questions go through enforce().

CRITICAL: No permission checks may exist outside this module.

Operations: READ, WRITE, DELETE
- READ: can read from this location
- WRITE: any mutation (write/rename/execute/git/db) with contract
- DELETE: deletion with token confirmation
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..world_adapter import ResolutionResult

# =============================================================================
# DECISION TYPES
# =============================================================================

class Decision(Enum):
    """Enforcement decision outcomes."""
    ALLOW = auto()          # Operation permitted
    DENY = auto()           # Operation forbidden
    REQUIRE_TOKEN = auto()  # Needs confirmation token
    REQUIRE_CONTRACT = auto()  # Needs active contract


class OperationType(Enum):
    """
    Canonical operation types for capability matrix lookup.
    
    READ = can read
    WRITE = any mutation (requires contract except WIP)
    DELETE = deletion (requires token)
    """
    READ = auto()
    WRITE = auto()
    DELETE = auto()


@dataclass
class EnforcementResult:
    """Result of an enforcement check."""
    decision: Decision
    reason: str
    requires_contract: bool = False
    requires_token: bool = False
    # For diagnostic failures (Reply I instead of D)
    is_diagnostic_failure: bool = False
    diagnostic_code: str | None = None


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
    
    Args:
        mode: Agent mode ("ck3lens" or "ck3raven-dev")
        operation: READ, WRITE, or DELETE
        resolved: ResolutionResult from WorldAdapter.resolve()
        has_contract: Whether an active contract exists
        
    Returns:
        EnforcementResult with decision and reason
        
    LOUD FAILURE POLICY:
        If resolution is missing subdirectory for a root that requires it,
        this returns DENY with is_diagnostic_failure=True and a clear error code.
        This MUST be surfaced as Reply(I), not silently denied.
    """
    from ..paths import RootCategory
    from ..capability_matrix import get_capability
    
    # ==========================================================================
    # INVARIANT 1: ROOT_EXTERNAL is always DENY
    # ==========================================================================
    if resolved.root_category == RootCategory.ROOT_EXTERNAL:
        return EnforcementResult(
            decision=Decision.DENY,
            reason=f"Path '{resolved.absolute_path}' is outside all known roots",
        )
    
    # ==========================================================================
    # INVARIANT 2: Database paths are never writable by tools
    # ==========================================================================
    if resolved.root_category == RootCategory.ROOT_CK3RAVEN_DATA:
        if resolved.subdirectory in {"db", "daemon"}:
            if operation in {OperationType.WRITE, OperationType.DELETE}:
                return EnforcementResult(
                    decision=Decision.DENY,
                    reason="Database and daemon files are owned by QBuilder daemon",
                )
    
    # ==========================================================================
    # LOUD FAILURE: Missing subdirectory for subdirectory-aware roots
    # ==========================================================================
    # This catches the bug where WorldAdapter.resolve() doesn't set subdirectory
    # for roots that have subdirectory-specific capability entries.
    if operation in {OperationType.WRITE, OperationType.DELETE}:
        subdir_aware = _get_subdirectory_aware_roots()
        if (mode, resolved.root_category) in subdir_aware and resolved.subdirectory is None:
            return EnforcementResult(
                decision=Decision.DENY,
                reason=(
                    f"Resolution missing subdirectory for {resolved.root_category.name}. "
                    f"WorldAdapter.resolve() must set subdirectory field for this root. "
                    f"Path: {resolved.absolute_path}"
                ),
                is_diagnostic_failure=True,
                diagnostic_code="EN-SUBDIR-I-001",
            )
    
    # ==========================================================================
    # STEP 1: Look up capability from matrix
    # ==========================================================================
    # NOTE: .mod file protection is handled by subfolders_writable in capability_matrix.
    # Files directly in mod/ (like *.mod) are protected because subfolders_writable
    # only allows writes to paths with 3+ components (e.g., mod/MyMod/file.txt).
    cap = get_capability(mode, resolved.root_category, resolved.subdirectory, resolved.relative_path)
    
    if cap is None:
        return EnforcementResult(
            decision=Decision.DENY,
            reason=f"No capability for ({mode}, {resolved.root_category.name}, {resolved.subdirectory})",
        )
    
    # ==========================================================================
    # STEP 2: Check operation against capability
    # ==========================================================================
    
    # READ
    if operation == OperationType.READ:
        if cap.read:
            return EnforcementResult(
                decision=Decision.ALLOW,
                reason="Read allowed",
            )
        return EnforcementResult(
            decision=Decision.DENY,
            reason=f"Read not permitted for ({mode}, {resolved.root_category.name})",
        )
    
    # WRITE (any mutation)
    if operation == OperationType.WRITE:
        if not cap.write:
            return EnforcementResult(
                decision=Decision.DENY,
                reason=f"Write not permitted for ({mode}, {resolved.root_category.name})",
            )
        
        # WIP workspace: no contract required
        # WIP is ROOT_CK3RAVEN_DATA with subdirectory "wip"
        if resolved.root_category == RootCategory.ROOT_CK3RAVEN_DATA and resolved.subdirectory == "wip":
            return EnforcementResult(
                decision=Decision.ALLOW,
                reason="Write to WIP allowed (no contract required)",
            )
        
        # All other writes require contract
        if not has_contract:
            return EnforcementResult(
                decision=Decision.REQUIRE_CONTRACT,
                reason=f"Write to {resolved.root_category.name} requires contract",
                requires_contract=True,
            )
        
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="Write allowed with contract",
        )
    
    # DELETE
    if operation == OperationType.DELETE:
        if not cap.delete:
            return EnforcementResult(
                decision=Decision.DENY,
                reason=f"Delete not permitted for ({mode}, {resolved.root_category.name})",
            )
        
        # WIP workspace: no contract required (same as write)
        if resolved.root_category == RootCategory.ROOT_CK3RAVEN_DATA and resolved.subdirectory == "wip":
            return EnforcementResult(
                decision=Decision.ALLOW,
                reason="Delete in WIP allowed (no contract required)",
            )
        
        # All other deletes require contract (same as write)
        if not has_contract:
            return EnforcementResult(
                decision=Decision.REQUIRE_CONTRACT,
                reason=f"Delete from {resolved.root_category.name} requires contract",
                requires_contract=True,
            )
        
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="Delete allowed with contract",
        )
    
    # Unknown
    return EnforcementResult(
        decision=Decision.DENY,
        reason=f"Unknown operation: {operation}",
    )
