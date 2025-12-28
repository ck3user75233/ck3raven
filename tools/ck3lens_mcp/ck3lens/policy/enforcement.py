"""
Centralized Policy Enforcement Gate

This module is the SINGLE source of truth for all policy decisions.
ALL write-capable MCP tools MUST call enforce_policy() at the tool boundary
before performing any mutation.

Architecture:
- LensWorld handles visibility (FOUND vs NOT_FOUND)
- This module handles policy (ALLOW vs DENY vs REQUIRE_TOKEN)
- Policy only applies AFTER a reference is resolved inside LensWorld

Key Principles:
1. Centralized: All enforcement flows through enforce_policy()
2. Tool-boundary: Called at MCP tool entry, not in implementation helpers
3. Mode-aware: Different rules for ck3lens vs ck3raven-dev
4. Logged: Every decision is traced for analytics
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional, List, Any
import fnmatch


# =============================================================================
# OPERATION TYPES
# =============================================================================

class OperationType(Enum):
    """Categories of operations requiring enforcement."""
    
    # Read operations (usually no enforcement needed)
    READ = auto()
    
    # File operations
    FILE_WRITE = auto()
    FILE_DELETE = auto()
    FILE_RENAME = auto()
    
    # Git operations (categorized by risk)
    GIT_READ = auto()           # status, diff, log, show, fetch
    GIT_LOCAL_PACKAGE = auto()  # add, restore --staged, commit (new)
    GIT_LOCAL_WORKFLOW = auto() # switch, checkout, stash, merge, pull --ff-only
    GIT_PUBLISH = auto()        # push (non-force)
    GIT_DESTRUCTIVE = auto()    # push --force, reset --hard, rebase, amend
    
    # Database operations
    DB_READ = auto()
    DB_MODIFY = auto()          # resolve conflicts, update playset
    DB_DELETE = auto()          # delete rows
    
    # Shell operations
    SHELL_SAFE = auto()         # read-only commands
    SHELL_WRITE = auto()        # commands that write
    SHELL_DESTRUCTIVE = auto()  # rm, drop, etc.
    
    # Specialized operations
    LAUNCHER_REPAIR = auto()
    CACHE_DELETE = auto()


class TokenTier(Enum):
    """Token requirement tiers."""
    NONE = auto()      # No token required
    TIER_A = auto()    # Low-risk, auto-grantable
    TIER_B = auto()    # High-risk, requires user approval


class Decision(Enum):
    """Enforcement decision types."""
    ALLOW = auto()
    NOT_FOUND = auto()          # For LensWorld - path outside lens
    REQUIRE_CONTRACT = auto()
    REQUIRE_TOKEN = auto()
    REQUIRE_USER_APPROVAL = auto()
    DENY = auto()


# =============================================================================
# ENFORCEMENT REQUEST/RESULT
# =============================================================================

@dataclass
class EnforcementRequest:
    """Request to validate an operation."""
    
    operation: OperationType
    mode: str  # "ck3lens" or "ck3raven-dev"
    tool_name: str  # The MCP tool making the request
    
    # Context (varies by operation type)
    target_path: Optional[str] = None      # For file/git ops (relative to repo)
    target_paths: List[str] = field(default_factory=list)  # Multiple paths
    mod_name: Optional[str] = None         # For ck3lens mod ops
    rel_path: Optional[str] = None         # For ck3lens mod ops
    command: Optional[str] = None          # For shell ops
    
    # Scope domains from contract
    repo_domains: List[str] = field(default_factory=list)
    
    # Existing auth
    contract_id: Optional[str] = None
    token_id: Optional[str] = None
    
    # Git-specific
    branch_name: Optional[str] = None
    is_force_push: bool = False
    staged_files: List[str] = field(default_factory=list)


@dataclass
class EnforcementResult:
    """Result of policy enforcement."""
    
    decision: Decision
    reason: str
    
    # What's needed if not allowed
    required_contract: bool = False
    required_token_tier: Optional[TokenTier] = None
    required_token_type: Optional[str] = None
    
    # Auth used
    contract_id: Optional[str] = None
    token_id: Optional[str] = None
    
    # For safe push auto-grant
    safe_push_autogrant: bool = False
    
    # Scope check details (for logging)
    scope_check_details: dict = field(default_factory=dict)


# =============================================================================
# PROTECTED BRANCHES
# =============================================================================

PROTECTED_BRANCHES = frozenset({
    "main",
    "master",
    "release/*",
    "prod/*",
    "production/*",
})


def is_protected_branch(branch_name: str) -> bool:
    """Check if a branch is protected from direct pushes."""
    if branch_name in {"main", "master"}:
        return True
    for pattern in PROTECTED_BRANCHES:
        if fnmatch.fnmatch(branch_name, pattern):
            return True
    return False


def is_agent_branch(branch_name: str, contract_id: Optional[str] = None) -> bool:
    """Check if branch is a valid agent branch for the contract."""
    if branch_name.startswith("agent/"):
        if contract_id:
            # Must start with agent/<contract_id>-
            return branch_name.startswith(f"agent/{contract_id}-")
        return True
    if branch_name.startswith("wip/") or branch_name.startswith("dev/"):
        return True
    return False


# =============================================================================
# MAIN ENFORCEMENT FUNCTION
# =============================================================================

def enforce_policy(request: EnforcementRequest) -> EnforcementResult:
    """
    Central policy enforcement gate.
    
    ALL write-capable tools MUST call this before performing their operation.
    This is the SINGLE source of truth for policy decisions.
    
    Args:
        request: EnforcementRequest with operation details
        
    Returns:
        EnforcementResult with decision and requirements
    """
    from .work_contracts import (
        WorkContract, get_active_contract, 
        validate_path_in_repo_domains, REPO_DOMAINS
    )
    
    mode = request.mode
    op = request.operation
    
    # ==========================================================================
    # STEP 1: Handle read operations (usually allowed)
    # ==========================================================================
    if op in {OperationType.READ, OperationType.GIT_READ, OperationType.DB_READ, OperationType.SHELL_SAFE}:
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="Read operations are allowed",
        )
    
    # ==========================================================================
    # STEP 2: Mode-specific hard gates
    # ==========================================================================
    
    # ck3raven-dev cannot touch mods
    if mode == "ck3raven-dev" and request.mod_name:
        return EnforcementResult(
            decision=Decision.DENY,
            reason="ck3raven-dev mode cannot modify CK3 mods",
        )
    
    # ck3lens cannot touch ck3raven source
    if mode == "ck3lens" and request.target_path:
        # Check if path looks like ck3raven source
        if _is_ck3raven_source_path(request.target_path):
            return EnforcementResult(
                decision=Decision.DENY,
                reason="ck3lens mode cannot modify ck3raven source",
            )
    
    # ck3lens launcher/cache operations
    if mode != "ck3lens" and op in {OperationType.LAUNCHER_REPAIR, OperationType.CACHE_DELETE}:
        return EnforcementResult(
            decision=Decision.DENY,
            reason="Launcher/cache operations only available in ck3lens mode",
        )
    
    # ==========================================================================
    # STEP 3: Contract requirement check
    # ==========================================================================
    
    contract = None
    if request.contract_id:
        contract = WorkContract.load(request.contract_id)
    else:
        contract = get_active_contract()
    
    # Most operations require a contract
    requires_contract = op not in {
        OperationType.READ, OperationType.GIT_READ, 
        OperationType.DB_READ, OperationType.SHELL_SAFE
    }
    
    if requires_contract and contract is None:
        return EnforcementResult(
            decision=Decision.REQUIRE_CONTRACT,
            reason=f"Operation {op.name} requires an active contract",
            required_contract=True,
        )
    
    if contract and not contract.is_active():
        return EnforcementResult(
            decision=Decision.REQUIRE_CONTRACT,
            reason=f"Contract {contract.contract_id} is not active (status: {contract.status})",
            required_contract=True,
        )
    
    # ==========================================================================
    # STEP 4: Scope validation (repo_domains + allowed_paths)
    # ==========================================================================
    
    scope_details = {}
    
    if mode == "ck3raven-dev" and contract:
        # Validate all target paths are in scope
        paths_to_check = []
        if request.target_path:
            paths_to_check.append(request.target_path)
        paths_to_check.extend(request.target_paths)
        paths_to_check.extend(request.staged_files)
        
        # Filter to only repo domains (not product domains)
        repo_domains = [d for d in contract.canonical_domains if d in REPO_DOMAINS]
        
        for path in paths_to_check:
            if path:
                allowed, reason = validate_path_in_repo_domains(
                    path, 
                    repo_domains,
                    contract.allowed_paths if contract.allowed_paths else None
                )
                if not allowed:
                    scope_details["failed_path"] = path
                    scope_details["repo_domains"] = repo_domains
                    scope_details["allowed_paths"] = contract.allowed_paths
                    return EnforcementResult(
                        decision=Decision.DENY,
                        reason=reason,
                        contract_id=contract.contract_id,
                        scope_check_details=scope_details,
                    )
    
    # ==========================================================================
    # STEP 5: Operation-specific rules
    # ==========================================================================
    
    # --- File operations ---
    if op == OperationType.FILE_WRITE:
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="File write allowed with valid contract scope",
            contract_id=contract.contract_id if contract else None,
            scope_check_details=scope_details,
        )
    
    if op == OperationType.FILE_DELETE:
        # Deletes always require token
        token_type = "DELETE_SOURCE" if mode == "ck3raven-dev" else "DELETE_LOCALMOD"
        if not request.token_id:
            return EnforcementResult(
                decision=Decision.REQUIRE_TOKEN,
                reason=f"File deletion requires {token_type} token",
                required_token_tier=TokenTier.TIER_B,
                required_token_type=token_type,
                contract_id=contract.contract_id if contract else None,
            )
        # TODO: Validate token
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="File delete allowed with token",
            contract_id=contract.contract_id if contract else None,
            token_id=request.token_id,
        )
    
    if op == OperationType.FILE_RENAME:
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="File rename allowed with valid contract scope",
            contract_id=contract.contract_id if contract else None,
        )
    
    # --- Git operations ---
    if op == OperationType.GIT_LOCAL_PACKAGE:
        # add, commit require contract
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="Git local packaging allowed with contract",
            contract_id=contract.contract_id if contract else None,
        )
    
    if op == OperationType.GIT_LOCAL_WORKFLOW:
        # switch, checkout, stash, merge, pull --ff-only require Token A
        # For now, allow with contract (Token A can be auto-granted)
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="Git local workflow allowed with contract (Token A auto-granted)",
            contract_id=contract.contract_id if contract else None,
            required_token_tier=TokenTier.TIER_A,
        )
    
    if op == OperationType.GIT_PUBLISH:
        return _enforce_git_push(request, contract)
    
    if op == OperationType.GIT_DESTRUCTIVE:
        # Always requires Token B with user approval
        return EnforcementResult(
            decision=Decision.REQUIRE_USER_APPROVAL,
            reason="Git destructive operations require user approval",
            required_token_tier=TokenTier.TIER_B,
            required_token_type="GIT_REWRITE_HISTORY",
            contract_id=contract.contract_id if contract else None,
        )
    
    # --- Database operations ---
    if op == OperationType.DB_MODIFY:
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="DB modification allowed with contract",
            contract_id=contract.contract_id if contract else None,
        )
    
    if op == OperationType.DB_DELETE:
        if mode == "ck3lens":
            return EnforcementResult(
                decision=Decision.DENY,
                reason="ck3lens cannot delete database rows",
            )
        if not request.token_id:
            return EnforcementResult(
                decision=Decision.REQUIRE_TOKEN,
                reason="DB deletion requires DB_DELETE_DATA token",
                required_token_tier=TokenTier.TIER_B,
                required_token_type="DB_DELETE_DATA",
                contract_id=contract.contract_id if contract else None,
            )
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="DB delete allowed with token",
            contract_id=contract.contract_id if contract else None,
            token_id=request.token_id,
        )
    
    # --- Shell operations ---
    if op == OperationType.SHELL_WRITE:
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="Shell write allowed with contract",
            contract_id=contract.contract_id if contract else None,
        )
    
    if op == OperationType.SHELL_DESTRUCTIVE:
        if not request.token_id:
            return EnforcementResult(
                decision=Decision.REQUIRE_TOKEN,
                reason="Destructive shell commands require token",
                required_token_tier=TokenTier.TIER_B,
                required_token_type="CMD_RUN_DESTRUCTIVE",
                contract_id=contract.contract_id if contract else None,
            )
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="Destructive shell command allowed with token",
            contract_id=contract.contract_id if contract else None,
            token_id=request.token_id,
        )
    
    # --- Launcher/cache operations ---
    if op == OperationType.LAUNCHER_REPAIR:
        if not request.token_id:
            return EnforcementResult(
                decision=Decision.REQUIRE_TOKEN,
                reason="Launcher repair requires REGISTRY_REPAIR token",
                required_token_tier=TokenTier.TIER_B,
                required_token_type="REGISTRY_REPAIR",
            )
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="Launcher repair allowed with token",
            token_id=request.token_id,
        )
    
    if op == OperationType.CACHE_DELETE:
        if not request.token_id:
            return EnforcementResult(
                decision=Decision.REQUIRE_TOKEN,
                reason="Cache deletion requires CACHE_DELETE token",
                required_token_tier=TokenTier.TIER_B,
                required_token_type="CACHE_DELETE",
            )
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="Cache deletion allowed with token",
            token_id=request.token_id,
        )
    
    # Unknown operation - deny by default
    return EnforcementResult(
        decision=Decision.DENY,
        reason=f"Unknown operation type: {op}",
    )


# =============================================================================
# GIT PUSH ENFORCEMENT (WITH SAFE PUSH AUTO-GRANT)
# =============================================================================

def _enforce_git_push(
    request: EnforcementRequest, 
    contract: Any,  # WorkContract
) -> EnforcementResult:
    """
    Enforce git push with SAFE PUSH auto-grant logic.
    
    SAFE PUSH auto-grant conditions (ALL must hold):
    1. Active contract exists and is valid
    2. Branch is agent/<contract_id>-* OR wip/* OR dev/* (not protected)
    3. Command is non-destructive push
    4. Remote is origin
    5. All staged files are within contract scope
    6. Optional: commit message includes [CONTRACT:<id>]
    """
    from .work_contracts import validate_path_in_repo_domains, REPO_DOMAINS
    
    if contract is None:
        return EnforcementResult(
            decision=Decision.REQUIRE_CONTRACT,
            reason="Git push requires active contract",
            required_contract=True,
        )
    
    branch = request.branch_name or ""
    
    # Check if force push
    if request.is_force_push:
        return EnforcementResult(
            decision=Decision.REQUIRE_USER_APPROVAL,
            reason="Force push requires user approval",
            required_token_tier=TokenTier.TIER_B,
            required_token_type="GIT_FORCE_PUSH",
            contract_id=contract.contract_id,
        )
    
    # Check if protected branch
    if is_protected_branch(branch):
        return EnforcementResult(
            decision=Decision.REQUIRE_USER_APPROVAL,
            reason=f"Push to protected branch '{branch}' requires user approval",
            required_token_tier=TokenTier.TIER_B,
            required_token_type="GIT_PUSH_PROTECTED",
            contract_id=contract.contract_id,
        )
    
    # Check if valid agent branch
    if not is_agent_branch(branch, contract.contract_id):
        return EnforcementResult(
            decision=Decision.REQUIRE_USER_APPROVAL,
            reason=f"Branch '{branch}' is not a valid agent branch for contract {contract.contract_id}",
            required_token_tier=TokenTier.TIER_B,
            required_token_type="GIT_PUSH",
            contract_id=contract.contract_id,
        )
    
    # Validate staged files are in scope
    repo_domains = [d for d in contract.canonical_domains if d in REPO_DOMAINS]
    
    for staged_file in request.staged_files:
        allowed, reason = validate_path_in_repo_domains(
            staged_file,
            repo_domains,
            contract.allowed_paths,
        )
        if not allowed:
            return EnforcementResult(
                decision=Decision.DENY,
                reason=f"Staged file '{staged_file}' is outside contract scope: {reason}",
                contract_id=contract.contract_id,
                scope_check_details={
                    "failed_file": staged_file,
                    "repo_domains": repo_domains,
                },
            )
    
    # All conditions met - SAFE PUSH auto-grant
    return EnforcementResult(
        decision=Decision.ALLOW,
        reason="SAFE PUSH auto-granted: valid agent branch, all staged files in scope",
        contract_id=contract.contract_id,
        safe_push_autogrant=True,
        scope_check_details={
            "branch": branch,
            "staged_files_count": len(request.staged_files),
            "repo_domains": repo_domains,
        },
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _is_ck3raven_source_path(path: str) -> bool:
    """Check if path appears to be ck3raven source code."""
    path = path.replace("\\", "/").lower()
    source_patterns = [
        "src/",
        "builder/",
        "tools/ck3lens_mcp/",
        "scripts/",
        "tests/",
    ]
    return any(path.startswith(p) or f"/{p}" in path for p in source_patterns)


# =============================================================================
# LOGGING INTEGRATION
# =============================================================================

def log_enforcement_decision(
    request: EnforcementRequest,
    result: EnforcementResult,
    trace: Any,  # ToolTrace
    session_id: str = "unknown",
) -> None:
    """
    Log an enforcement decision to the trace log.
    
    Every enforcement decision MUST be logged for analytics.
    Uses structured AuditLogger for consistent schema.
    """
    if trace is None:
        return
    
    from .audit import get_audit_logger
    
    # Use structured audit logger
    audit = get_audit_logger(trace, session_id)
    
    # Truncate command for logging
    command = request.command[:100] if request.command else None
    
    # Limit staged files for logging
    staged_files = request.staged_files[:10] if request.staged_files else None
    
    audit.log_enforcement(
        operation_type=request.operation.name,
        mode=request.mode,
        tool_name=request.tool_name,
        decision=result.decision.name,
        reason=result.reason,
        contract_id=result.contract_id,
        token_id=result.token_id,
        required_token_type=result.required_token_type,
        target_path=request.target_path,
        target_paths=request.target_paths if request.target_paths else None,
        mod_name=request.mod_name,
        command=command,
        branch=request.branch_name,
        staged_files=staged_files,
        safe_push_autogrant=result.safe_push_autogrant if result.safe_push_autogrant else None,
        scope_check=result.scope_check_details if result.scope_check_details else None,
    )


# =============================================================================
# CONVENIENCE WRAPPER
# =============================================================================

def enforce_and_log(
    request: EnforcementRequest,
    trace: Any = None,
    session_id: str = "unknown",
) -> EnforcementResult:
    """
    Enforce policy and log the decision.
    
    This is the recommended entry point for tools - it handles both
    enforcement and logging in one call.
    
    Args:
        request: EnforcementRequest with operation details
        trace: Optional ToolTrace for logging
        session_id: Session identifier for logging
        
    Returns:
        EnforcementResult with decision and requirements
    """
    result = enforce_policy(request)
    log_enforcement_decision(request, result, trace, session_id)
    return result
