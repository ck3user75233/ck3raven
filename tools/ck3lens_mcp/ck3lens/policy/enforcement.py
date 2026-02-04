"""
Centralized Policy Enforcement Gate

This module is the SINGLE source of truth for all policy decisions.
ALL write-capable MCP tools MUST call enforce_policy() at the tool boundary
before performing any mutation.

Architecture:
- WorldAdapter handles visibility + root_category classification (FOUND vs NOT_FOUND)
- This module handles policy via capability_matrix.is_authorized() (ALLOW vs DENY)
- Policy only applies AFTER a reference is resolved by WorldAdapter

Key Principles:
1. Centralized: All enforcement flows through enforce_policy()
2. Tool-boundary: Called at MCP tool entry, not in implementation helpers
3. Mode-aware: Different rules for ck3lens vs ck3raven-dev
4. Matrix-driven: Decisions based on capability_matrix.is_authorized()
5. Logged: Every decision is traced for analytics
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional, List, Any

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


# =============================================================================
# SHELL COMMAND CLASSIFICATION (migrated from clw.py Dec 2025)
# =============================================================================

class CommandCategory(Enum):
    """Categories of shell commands by risk level."""
    READ_ONLY = auto()          # Safe read operations
    WRITE_IN_SCOPE = auto()     # Write within contract scope
    WRITE_OUT_OF_SCOPE = auto() # Write outside contract scope
    DESTRUCTIVE = auto()        # File deletion, data loss
    GIT_SAFE = auto()           # git status, log, diff
    GIT_MODIFY = auto()         # git commit, branch
    GIT_DANGEROUS = auto()      # git push, rebase, force
    NETWORK = auto()            # curl, wget, etc.
    SYSTEM = auto()             # System commands
    BLOCKED = auto()            # Never allowed


# Commands that are always allowed (no contract/token needed)
SAFE_COMMANDS = frozenset({
    # File reading
    "cat", "type", "more", "less", "head", "tail", "bat",
    # Directory listing
    "ls", "dir", "tree", "find", "fd", "rg", "grep",
    # Git safe operations (per policy doc Section 9)
    "git status", "git log", "git diff", "git show", "git branch -a",
    "git remote -v", "git stash list",
    "git add", "git commit",  # Allowed without approval per policy
    "git fetch", "git pull",  # Read-like remote operations
    # Python/tools - NOTE: "python -c" REMOVED (Phase 1.5 remediation)
    # python -c is now handled by classify_python_inline() with scanning
    "python -m pytest", "python -m mypy",
    # Info commands
    "pwd", "echo", "which", "where", "whoami",
    # PowerShell read-only commands (Get-* cmdlets are non-mutating)
    "get-process", "get-childitem", "get-content", "get-item", "get-location",
    "get-service", "get-command", "get-help", "get-date", "get-host",
    "get-eventlog", "get-wmiobject", "get-ciminstance", "get-acl",
    "select-object", "format-table", "format-list", "where-object",
    "test-path", "resolve-path", "split-path", "join-path",
})

# Commands that are NEVER allowed (hard deny)
BLOCKED_COMMANDS = frozenset({
    # System modification (require exact patterns to avoid false positives)
    "rm -rf /", "del /s /q c:\\",
    # format as a standalone command (disk formatting), NOT format-* PowerShell cmdlets
    "diskpart", "shutdown", "reboot",
    # Package management (risky)
    "pip uninstall", "npm uninstall",
    # History rewriting
    "git filter-branch", "git reset --hard origin",
    # Destructive force
    "git push --force origin main", "git push -f origin main",
})

# Patterns requiring tokens, keyed by token type
TOKEN_REQUIRED_PATTERNS: dict[str, list[str]] = {
    "FS_DELETE_CODE": [
        r"rm\s+.*\.py",
        r"del\s+.*\.py",
        r"rmdir",
        r"rm\s+-r",
        r"rd\s+/s",
    ],
    "CMD_RUN_DESTRUCTIVE": [
        r"drop\s+table",
        r"truncate\s+table",
        r"delete\s+from",
    ],
    "GIT_PUSH": [
        r"git\s+push(?!\s+--force)",
    ],
    "GIT_FORCE_PUSH": [
        r"git\s+push\s+(--force|-f)",
    ],
    "GIT_REWRITE_HISTORY": [
        r"git\s+rebase",
        r"git\s+reset\s+--hard",
        r"git\s+cherry-pick",
    ],
    "CMD_RUN_ARBITRARY": [
        r"curl\s+.*\|\s*(bash|sh|python)",
        r"wget\s+.*-O-\s*\|",
        r"powershell\s+-c",
        r"cmd\s+/c",
    ],
}

# Git commands that modify local state (require contract)
GIT_MODIFY_PATTERNS = [
    r"git\s+stash(?!\s+list)",  # stash list is safe, stash push/pop is modify
    r"git\s+checkout",
    r"git\s+switch",
    r"git\s+merge",
    r"git\s+branch\s+(?!-a|-v|-l|--list)",  # Creating/deleting branches
]


def classify_command(command: str) -> CommandCategory:
    """
    Classify a shell command into a risk category.
    
    This is structural classification for enforcement decisions.
    The category is then mapped to OperationType for enforce_and_log().
    
    Args:
        command: The shell command string
    
    Returns:
        CommandCategory indicating risk level
    """
    cmd_lower = command.lower()
    
    # ==========================================================================
    # PHASE 1.5: python -c special handling
    # python -c is NOT in SAFE_COMMANDS. It's analyzed by the inline scanner.
    # ==========================================================================
    from .python_inline_scanner import classify_python_inline, InlineIntentType
    
    is_python_c, intent = classify_python_inline(command)
    if is_python_c and intent is not None:
        if intent.intent == InlineIntentType.SAFE:
            # Matches safe allowlist (env checks, prints)
            return CommandCategory.READ_ONLY
        elif intent.intent == InlineIntentType.READ_ONLY:
            # No mutations detected - still allow as read-only
            return CommandCategory.READ_ONLY
        elif intent.intent == InlineIntentType.DESTRUCTIVE:
            # Deletes, removes, etc.
            return CommandCategory.DESTRUCTIVE
        else:
            # POTENTIALLY_WRITE - requires enforcement
            return CommandCategory.WRITE_IN_SCOPE
    
    # Check safe commands FIRST - PowerShell Get-* cmdlets should not be blocked
    for safe in SAFE_COMMANDS:
        if cmd_lower.startswith(safe):
            return CommandCategory.READ_ONLY
    
    # Check blocked - use startswith for most, contains only for compound patterns
    for blocked in BLOCKED_COMMANDS:
        # For compound patterns like "git push --force origin main", use contains
        if " " in blocked:
            if blocked in cmd_lower:
                return CommandCategory.BLOCKED
        # For single-word patterns, require startswith to avoid false positives
        else:
            if cmd_lower.startswith(blocked) or cmd_lower.startswith("./" + blocked) or f" {blocked}" in cmd_lower:
                return CommandCategory.BLOCKED
    
    # Git classification
    if cmd_lower.startswith("git "):
        if any(re.search(p, cmd_lower) for p in [r"push.*--force", r"push.*-f"]):
            return CommandCategory.GIT_DANGEROUS
        if "push" in cmd_lower or "rebase" in cmd_lower or "reset --hard" in cmd_lower:
            return CommandCategory.GIT_DANGEROUS
        if any(re.search(p, cmd_lower) for p in GIT_MODIFY_PATTERNS):
            return CommandCategory.GIT_MODIFY
        return CommandCategory.GIT_SAFE
    
    # Destructive patterns
    if any(re.search(p, cmd_lower) for patterns in TOKEN_REQUIRED_PATTERNS.values() 
           for p in patterns if "rm" in p or "del" in p or "drop" in p):
        return CommandCategory.DESTRUCTIVE
    
    # Network
    if any(x in cmd_lower for x in ["curl", "wget", "invoke-webrequest"]):
        return CommandCategory.NETWORK
    
    # Write operations (heuristic)
    if any(x in cmd_lower for x in [">", ">>", "| tee", "out-file"]):
        return CommandCategory.WRITE_OUT_OF_SCOPE
    
    # Default to system
    return CommandCategory.SYSTEM


# =============================================================================
# CONTRACT PATH SCOPE
# =============================================================================

def check_path_in_contract_scope(
    path: str,
    contract_paths: list[str],
) -> bool:
    """
    Check if a path is within the contract's allowed scope.
    
    
    
    Args:
        path: Path to check
        contract_paths: List of allowed path patterns from contract
    
    Returns:
        True if path is in scope
    """
    if not contract_paths:
        return True  # No restriction
    
    path = path.replace("\\", "/")
    
    for pattern in contract_paths:
        pattern = pattern.replace("\\", "/")
        if fnmatch.fnmatch(path, pattern):
            return True
        # Also check if path is under a directory pattern
        if pattern.endswith("/*") or pattern.endswith("/**"):
            dir_pattern = pattern.rstrip("/*")
            if path.startswith(dir_pattern):
                return True
    
    return False


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
    """Request to validate an operation.
    
    The `root_category` field is the resolved RootCategory from WorldAdapter.
    Enforcement uses this to check the capability matrix - it does NOT re-check paths.
    
    Root categories are geographic locations (from capability_matrix.py):
    - ROOT_WIP → always allowed (both modes)
    - ROOT_USER_DOCS → local mods (ck3lens: write, ck3raven-dev: read)
    - ROOT_STEAM → workshop mods (read only)
    - ROOT_GAME → vanilla (read only)
    - ROOT_REPO → ck3raven source (ck3raven-dev: write, ck3lens: read)
    - ROOT_LAUNCHER → launcher registry (ck3lens: write with token)
    - ROOT_CK3RAVEN_DATA → ~/.ck3raven/ (both modes: read+write)
    """
    
    operation: OperationType
    mode: str  # "ck3lens" or "ck3raven-dev"
    tool_name: str  # The MCP tool making the request
    
    # RootCategory from WorldAdapter resolution (THE source of truth)
    root_category: Optional[str] = None  # RootCategory value (ROOT_WIP, ROOT_USER_DOCS, etc.)
    
    # Context (varies by operation type)
    target_path: Optional[str] = None      # Canonical address (e.g., "wip:/test.py", "mod:MyMod/file.txt")
    target_paths: List[str] = field(default_factory=list)  # Multiple paths
    mod_name: Optional[str] = None         # For ck3lens mod ops (from resolution)
    rel_path: Optional[str] = None         # For ck3lens mod ops (from resolution)
    command: Optional[str] = None          # For shell ops
    
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
# PATH NORMALIZATION (CRITICAL - Applied once for all tools)
# =============================================================================

def _get_repo_root() -> Path:
    """Get the ck3raven repository root."""
    return Path(__file__).parent.parent.parent.parent.parent


def _normalize_path_to_relative(path_str: str) -> str:
    """Convert absolute path to repo-relative path."""
    if not path_str:
        return path_str
    path = Path(path_str)
    if not path.is_absolute():
        return str(path).replace("\\", "/")
    repo_root = _get_repo_root()
    try:
        rel_path = path.resolve().relative_to(repo_root.resolve())
        return str(rel_path).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _normalize_request_paths(request: EnforcementRequest) -> None:
    """Normalize all paths in EnforcementRequest in-place."""
    if request.target_path:
        request.target_path = _normalize_path_to_relative(request.target_path)
    if request.target_paths:
        request.target_paths = [_normalize_path_to_relative(p) for p in request.target_paths]
    if request.staged_files:
        request.staged_files = [_normalize_path_to_relative(p) for p in request.staged_files]


# =============================================================================
# MAIN ENFORCEMENT FUNCTION
# =============================================================================

def enforce_policy(request: EnforcementRequest) -> EnforcementResult:
    """
    Central policy enforcement gate.
    
    ALL write-capable tools MUST call this before performing their operation.
    This is the SINGLE source of truth for policy decisions.
    
    Uses capability_matrix.is_authorized() as THE source of authorization truth.
    
    Args:
        request: EnforcementRequest with operation details
        
    Returns:
        EnforcementResult with decision and requirements
    """
    # Import from contract_v1 for new schema
    from .contract_v1 import get_active_contract, ContractV1, load_contract
    from .capability_matrix import RootCategory, Operation, AgentMode, is_authorized
    
    # STEP 0: Normalize all paths ONCE at entry point
    _normalize_request_paths(request)
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
    # STEP 2: Capability Matrix Check (THE source of authorization truth)
    # ==========================================================================
    
    # Map operation type for matrix lookup
    if op in {OperationType.FILE_WRITE, OperationType.FILE_DELETE, OperationType.FILE_RENAME}:
        matrix_op = Operation.WRITE
    elif op == OperationType.GIT_PUBLISH:
        matrix_op = Operation.GIT_WRITE
    elif op == OperationType.DB_WRITE:
        matrix_op = Operation.DB_WRITE
    else:
        matrix_op = Operation.WRITE  # Default for other mutations
    
    # Get root_category from request (set by WorldAdapter resolution)
    if request.root_category:
        try:
            root = RootCategory(request.root_category) if isinstance(request.root_category, str) else request.root_category
        except ValueError:
            return EnforcementResult(
                decision=Decision.DENY,
                reason=f"Unknown root category: {request.root_category}",
            )
        
        # Check capability matrix - this is the SINGLE authorization check
        if not is_authorized(mode, root, matrix_op):
            return EnforcementResult(
                decision=Decision.DENY,
                reason=f"{mode} mode cannot {matrix_op.value} in {root.value}",
            )
    else:
        # No root_category = fail closed (path was not resolved)
        return EnforcementResult(
            decision=Decision.DENY,
            reason="No root_category provided - path not resolved through WorldAdapter",
        )
    
    # ck3lens launcher/cache operations (mode-specific operation types)
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
        contract = load_contract(request.contract_id)
    else:
        contract = get_active_contract()
    
    # Most operations require a contract (except WIP which is always allowed by matrix)
    requires_contract = op not in {
        OperationType.READ, OperationType.GIT_READ, 
        OperationType.DB_READ, OperationType.SHELL_SAFE
    }
    
    # WIP doesn't require contract - already allowed by matrix
    if request.root_category == "ROOT_WIP":
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="Write to WIP workspace allowed (no contract required)",
        )
    
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
    # STEP 4: Scope validation via contract targets
    # ==========================================================================
    
    scope_details = {}
    
    if mode == "ck3raven-dev" and contract:
        # Validate all target paths are in scope using contract.targets
        paths_to_check = []
        if request.target_path:
            paths_to_check.append(request.target_path)
        paths_to_check.extend(request.target_paths)
        paths_to_check.extend(request.staged_files)
        
        # Get allowed paths from contract targets
        allowed_paths = [t.path for t in contract.targets] if contract.targets else None
        
        if allowed_paths:
            for path in paths_to_check:
                if path:
                    # Extract relative path from canonical address
                    rel_path = path.split(':/', 1)[1] if ':/' in path and not (len(path) > 2 and path[1] == ':') else path
                    
                    # Check if path matches any target pattern
                    if not check_path_in_contract_scope(rel_path, allowed_paths):
                        scope_details['out_of_scope_path'] = rel_path
                        return EnforcementResult(
                            decision=Decision.DENY,
                            reason=f"Path '{rel_path}' is outside contract target scope",
                            contract_id=contract.contract_id,
                            scope_check_details=scope_details,
                        )

    # ==========================================================================
    # STEP 5: Operation-specific rules
    # ==========================================================================
    
    # --- File operations ---
    # Capability matrix already checked in STEP 2, just return ALLOW
    if op == OperationType.FILE_WRITE:
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="File write allowed (authorized by capability matrix)",
            contract_id=contract.contract_id if contract else None,
        )
    
    if op == OperationType.FILE_DELETE:
        # Deletes require explicit confirmation via token_id
        # Phase 2 will implement proper approval flow
        if not request.token_id:
            return EnforcementResult(
                decision=Decision.REQUIRE_TOKEN,
                reason="File deletion requires explicit confirmation (provide token_id)",
                required_token_tier=TokenTier.TIER_B,
                contract_id=contract.contract_id if contract else None,
            )
        
        # Token provided = user confirmed
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="File delete allowed with confirmation",
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
        # Always requires user approval (Phase 2 will implement proper flow)
        return EnforcementResult(
            decision=Decision.REQUIRE_USER_APPROVAL,
            reason="Git destructive operations require user approval",
            required_token_tier=TokenTier.TIER_B,
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
                reason="DB deletion requires explicit confirmation (provide token_id)",
                required_token_tier=TokenTier.TIER_B,
                contract_id=contract.contract_id if contract else None,
            )
        
        # Token provided = user confirmed
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="DB delete allowed with confirmation",
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
        # Destructive shell commands require confirmation
        # Phase 2 will implement proper approval flow
        if not request.token_id:
            return EnforcementResult(
                decision=Decision.REQUIRE_TOKEN,
                reason="Destructive command requires explicit confirmation (provide token_id)",
                required_token_tier=TokenTier.TIER_B,
                contract_id=contract.contract_id if contract else None,
            )
        
        # Token provided = user confirmed
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="Destructive command allowed with confirmation",
            contract_id=contract.contract_id if contract else None,
            token_id=request.token_id,
        )
    
    # --- Launcher/cache operations ---
    if op == OperationType.LAUNCHER_REPAIR:
        if not request.token_id:
            return EnforcementResult(
                decision=Decision.REQUIRE_TOKEN,
                reason="Launcher repair requires explicit confirmation (provide token_id)",
                required_token_tier=TokenTier.TIER_B,
            )
        
        # Token provided = user confirmed
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="Launcher repair allowed with confirmation",
            token_id=request.token_id,
        )
    
    if op == OperationType.CACHE_DELETE:
        if not request.token_id:
            return EnforcementResult(
                decision=Decision.REQUIRE_TOKEN,
                reason="Cache deletion requires explicit confirmation (provide token_id)",
                required_token_tier=TokenTier.TIER_B,
            )
        
        # Token provided = user confirmed
        return EnforcementResult(
            decision=Decision.ALLOW,
            reason="Cache deletion allowed with confirmation",
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
            contract_id=contract.contract_id,
        )
    
    # Check if protected branch
    if is_protected_branch(branch):
        return EnforcementResult(
            decision=Decision.REQUIRE_USER_APPROVAL,
            reason=f"Push to protected branch '{branch}' requires user approval",
            required_token_tier=TokenTier.TIER_B,
            contract_id=contract.contract_id,
        )
    
    # Check if valid agent branch
    if not is_agent_branch(branch, contract.contract_id):
        return EnforcementResult(
            decision=Decision.REQUIRE_USER_APPROVAL,
            reason=f"Branch '{branch}' is not a valid agent branch for contract {contract.contract_id}",
            required_token_tier=TokenTier.TIER_B,
            contract_id=contract.contract_id,
        )
    
    # Get allowed paths from contract targets
    allowed_paths = [t.path for t in contract.targets] if contract.targets else None
    
    # Validate staged files are in contract scope
    for staged_file in request.staged_files:
        if allowed_paths and not check_path_in_contract_scope(staged_file, allowed_paths):
            return EnforcementResult(
                decision=Decision.DENY,
                reason=f"Staged file '{staged_file}' is outside contract target scope",
                contract_id=contract.contract_id,
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
            # repo_domains removed - was undefined variable
        },
    )


def _is_launcher_registry_path(path: str) -> bool:
    """Check if path is the CK3 launcher registry."""
    path_lower = path.replace("\\", "/").lower()
    return "launcher-v2.sqlite" in path_lower or "launcher-v2_openbeta.sqlite" in path_lower


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _is_ck3raven_source_path(path: str) -> bool:
    """Check if path appears to be ck3raven source code."""
    path = path.replace("\\", "/").lower()
    source_patterns = [
        "src/",
        "qbuilder/",           # Queue-based builder (was incorrectly "builder/")
        "tools/ck3lens_mcp/",
        "tools/ck3lens-explorer/",
        "scripts/",
        "tests/",
        "docs/",
        "playsets/",
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
