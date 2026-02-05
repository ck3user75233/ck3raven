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
    # INVARIANT 3: ROOT_LAUNCHER modifications need token
    # ==========================================================================
    if resolved.root_category == RootCategory.ROOT_LAUNCHER:
        if operation in {OperationType.WRITE, OperationType.DELETE}:
            return EnforcementResult(
                decision=Decision.REQUIRE_TOKEN,
                reason="Launcher registry modification requires confirmation",
                requires_token=True,
            )
    
    # ==========================================================================
    # STEP 1: Look up capability from matrix
    # ==========================================================================
    # NOTE: .mod file protection is handled by subfolders_writable in capability_matrix.
    # Files directly in mod/ (like *.mod) are protected because subfolders_writable
    # only allows writes to paths with 2+ components (e.g., mod/MyMod/file.txt).
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
        
        # All deletes require token
        return EnforcementResult(
            decision=Decision.REQUIRE_TOKEN,
            reason="Delete requires confirmation token",
            requires_token=True,
        )
    
    # Unknown
    return EnforcementResult(
        decision=Decision.DENY,
        reason=f"Unknown operation: {operation}",
    )
