"""
Command Line Wrapper (CLW) Policy Engine

This module classifies commands and enforces policy decisions:
- ALLOW: Command can proceed without token
- DENY: Command is blocked (never allowed)
- REQUIRE_TOKEN: Command needs approval token

Policy enforcement integrates with:
- Work Contracts: Active contract provides scope
- Approval Tokens: HMAC-signed tokens for risky operations
- Canonical Domains: Code-diff guard classification
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Literal, Optional

from .tokens import validate_token


# ============================================================================
# Enums and Types
# ============================================================================

class Decision(Enum):
    """Policy decision for a command."""
    ALLOW = auto()      # Command can proceed
    DENY = auto()       # Command is blocked
    REQUIRE_TOKEN = auto()  # Command needs approval token


class CommandCategory(Enum):
    """Categories of commands by risk level."""
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


# ============================================================================
# Command Patterns
# ============================================================================

# Commands that are always allowed
SAFE_COMMANDS = {
    # File reading
    "cat", "type", "more", "less", "head", "tail", "bat",
    # Directory listing
    "ls", "dir", "tree", "find", "fd", "rg", "grep",
    # Git safe operations (per policy doc Section 9)
    "git status", "git log", "git diff", "git show", "git branch -a",
    "git remote -v", "git stash list",
    "git add", "git commit",  # Allowed without approval per policy
    "git fetch", "git pull",  # Read-like remote operations
    # Python/tools
    "python -c", "python -m pytest", "python -m mypy",
    # Info commands
    "pwd", "echo", "which", "where", "whoami",
}

# Commands that are NEVER allowed
BLOCKED_COMMANDS = {
    # System modification
    "rm -rf /", "del /s /q c:\\",
    "format", "diskpart", "shutdown", "reboot",
    # Package management (risky)
    "pip uninstall", "npm uninstall",
    # History rewriting
    "git filter-branch", "git reset --hard origin",
    # Destructive force
    "git push --force origin main", "git push -f origin main",
}

# Patterns requiring tokens by token type
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

# Git commands that modify local state (require contract or token)
# NOTE: git add and git commit are in SAFE_COMMANDS per policy doc Section 9
GIT_MODIFY_PATTERNS = [
    r"git\s+stash(?!\s+list)",  # stash list is safe, stash push/pop is modify
    r"git\s+checkout",
    r"git\s+switch",
    r"git\s+merge",
    r"git\s+branch\s+(?!-a|-v|-l|--list)",  # Creating/deleting branches (listing is safe)
]


# ============================================================================
# Command Request
# ============================================================================

@dataclass
class CommandRequest:
    """
    A command request to be evaluated by the policy engine.
    """
    command: str
    working_dir: str
    target_paths: list[str] = field(default_factory=list)  # Files being affected
    
    # Context
    contract_id: Optional[str] = None
    token_id: Optional[str] = None
    mode: Optional[str] = None  # "ck3lens" or "ck3raven-dev" for mode-aware policy
    
    def __post_init__(self):
        self.command = self.command.strip()


@dataclass
class PolicyResult:
    """
    Result of policy evaluation.
    """
    decision: Decision
    reason: str
    required_token_type: Optional[str] = None
    category: Optional[CommandCategory] = None
    
    # For audit
    command: str = ""
    contract_id: Optional[str] = None
    token_id: Optional[str] = None


# ============================================================================
# Policy Engine
# ============================================================================

def _evaluate_mode_restrictions(request: CommandRequest, category: CommandCategory) -> Optional[PolicyResult]:
    """
    Evaluate mode-specific restrictions.
    
    Mode Hard Gates:
    - ck3lens: Cannot write to ck3raven source code
    - ck3raven-dev: Cannot write to mod files (ABSOLUTE PROHIBITION)
    
    Args:
        request: CommandRequest with mode set
        category: Already-classified command category
    
    Returns:
        PolicyResult if mode restriction applies, None otherwise
    """
    mode = request.mode
    cmd = request.command.lower()
    
    if mode == "ck3lens":
        # ck3lens mode: Writes to ck3raven source are blocked
        # (visibility checks should have already happened via WorldAdapter)
        # This is a backup policy check
        if category in (CommandCategory.WRITE_IN_SCOPE, CommandCategory.WRITE_OUT_OF_SCOPE, 
                        CommandCategory.DESTRUCTIVE):
            for path in request.target_paths:
                if "ck3raven" in path.lower() and "mod" not in path.lower():
                    return PolicyResult(
                        decision=Decision.DENY,
                        reason="ck3lens mode: Cannot modify ck3raven source code",
                        category=category,
                        command=request.command,
                    )
    
    elif mode == "ck3raven-dev":
        # ck3raven-dev mode: Writes to mod files are ABSOLUTELY PROHIBITED
        # This is the hard gate from CK3RAVEN_DEV_POLICY_ARCHITECTURE.md
        if category in (CommandCategory.WRITE_IN_SCOPE, CommandCategory.WRITE_OUT_OF_SCOPE,
                        CommandCategory.DESTRUCTIVE, CommandCategory.GIT_MODIFY, 
                        CommandCategory.GIT_DANGEROUS):
            # Check target paths for mod directories
            mod_indicators = ["\\mod\\", "/mod/", "paradox interactive", "workshop"]
            for path in request.target_paths:
                path_lower = path.lower()
                if any(indicator in path_lower for indicator in mod_indicators):
                    return PolicyResult(
                        decision=Decision.DENY,
                        reason="ck3raven-dev mode: ABSOLUTE PROHIBITION on mod file writes",
                        category=category,
                        command=request.command,
                    )
            
            # Check working_dir for mod directories
            if request.working_dir:
                working_dir_lower = request.working_dir.lower()
                if any(indicator in working_dir_lower for indicator in mod_indicators):
                    return PolicyResult(
                        decision=Decision.DENY,
                        reason="ck3raven-dev mode: ABSOLUTE PROHIBITION on mod file operations",
                        category=category,
                        command=request.command,
                    )
    
    return None  # No mode restriction applies


def classify_command(command: str) -> CommandCategory:
    """
    Classify a command into a risk category.
    
    Args:
        command: The command string
    
    Returns:
        CommandCategory
    """
    cmd_lower = command.lower()
    
    # Check blocked first
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return CommandCategory.BLOCKED
    
    # Check safe commands
    for safe in SAFE_COMMANDS:
        if cmd_lower.startswith(safe):
            return CommandCategory.READ_ONLY
    
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


def evaluate_policy(request: CommandRequest) -> PolicyResult:
    """
    DEPRECATED: This is an oracle function. Use enforcement.py instead.
    
    Policy decisions now route through enforcement.enforce_and_log().
    This function is kept for backwards compatibility but will be removed.
    
    Use instead:
        from ck3lens.policy.enforcement import enforce_and_log, EnforcementRequest, OperationType
        from ck3lens.policy.clw import classify_command, CommandCategory
        
        category = classify_command(command)
        op_type = map_category_to_operation(category)  # SHELL_SAFE, SHELL_WRITE, etc.
        result = enforce_and_log(EnforcementRequest(
            operation=op_type,
            mode=...,
            tool_name="ck3_exec",
            command=...,
        ))
    """
    import warnings
    warnings.warn(
        "evaluate_policy is deprecated. Use enforcement.enforce_and_log() instead. "
        "See docs/CANONICAL_ARCHITECTURE.md for the NO-ORACLE pattern.",
        DeprecationWarning,
        stacklevel=2,
    )
    
    cmd = request.command
    category = classify_command(cmd)
    
    # BLOCKED is always denied
    if category == CommandCategory.BLOCKED:
        return PolicyResult(
            decision=Decision.DENY,
            reason="Command is in blocked list",
            category=category,
            command=cmd,
        )
    
    # Mode-specific restrictions (before other checks)
    if request.mode:
        mode_result = _evaluate_mode_restrictions(request, category)
        if mode_result is not None:
            return mode_result
    
    # READ_ONLY and GIT_SAFE are always allowed
    if category in (CommandCategory.READ_ONLY, CommandCategory.GIT_SAFE):
        return PolicyResult(
            decision=Decision.ALLOW,
            reason="Safe command",
            category=category,
            command=cmd,
        )
    
    # Check if command requires token
    for token_type, patterns in TOKEN_REQUIRED_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, cmd, re.IGNORECASE):
                # Token is required - check if provided and valid
                if request.token_id:
                    # Determine capability from token type
                    capability = token_type
                    valid, msg = validate_token(
                        request.token_id,
                        capability,
                        path=request.target_paths[0] if request.target_paths else None,
                        command=cmd,
                    )
                    if valid:
                        return PolicyResult(
                            decision=Decision.ALLOW,
                            reason=f"Token validated: {msg}",
                            category=category,
                            command=cmd,
                            token_id=request.token_id,
                        )
                    else:
                        return PolicyResult(
                            decision=Decision.DENY,
                            reason=f"Token invalid: {msg}",
                            required_token_type=token_type,
                            category=category,
                            command=cmd,
                        )
                else:
                    return PolicyResult(
                        decision=Decision.REQUIRE_TOKEN,
                        reason=f"Command requires {token_type} token",
                        required_token_type=token_type,
                        category=category,
                        command=cmd,
                    )
    
    # GIT_MODIFY is allowed within contract OR with token
    if category == CommandCategory.GIT_MODIFY:
        if request.contract_id:
            return PolicyResult(
                decision=Decision.ALLOW,
                reason="Git modification allowed within contract",
                category=category,
                command=cmd,
                contract_id=request.contract_id,
            )
        # Check if a valid GIT_PUSH token was provided
        if request.token_id:
            valid, msg = validate_token(
                request.token_id,
                "GIT_PUSH",
                command=cmd,
            )
            if valid:
                return PolicyResult(
                    decision=Decision.ALLOW,
                    reason=f"Git modification allowed with token: {msg}",
                    category=category,
                    command=cmd,
                    token_id=request.token_id,
                )
        # No contract or valid token - require token
        return PolicyResult(
            decision=Decision.REQUIRE_TOKEN,
            reason="Git modification requires active contract or token",
            required_token_type="GIT_PUSH",
            category=category,
            command=cmd,
        )
    
    # WRITE_OUT_OF_SCOPE needs contract or token
    if category == CommandCategory.WRITE_OUT_OF_SCOPE:
        return PolicyResult(
            decision=Decision.REQUIRE_TOKEN,
            reason="Write operation outside contract scope",
            required_token_type="FS_WRITE_OUTSIDE_CONTRACT",
            category=category,
            command=cmd,
        )
    
    # NETWORK is allowed with warning
    if category == CommandCategory.NETWORK:
        return PolicyResult(
            decision=Decision.ALLOW,
            reason="Network command allowed (logged)",
            category=category,
            command=cmd,
        )
    
    # SYSTEM commands - allow by default but log
    return PolicyResult(
        decision=Decision.ALLOW,
        reason="System command allowed (logged)",
        category=category,
        command=cmd,
    )


def check_path_in_scope(
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


# ============================================================================
# DEPRECATED: Oracle functions removed in NO-ORACLE refactor (Dec 2025)
# 
# Policy decisions now route through enforcement.py, not clw.py.
# This module now provides CLASSIFICATION ONLY via classify_command().
# 
# For shell command enforcement, use:
#   from ck3lens.policy.enforcement import enforce_and_log, EnforcementRequest, OperationType
#   result = enforce_and_log(EnforcementRequest(operation=OperationType.SHELL_*, ...))
# ============================================================================

def can_execute(
    command: str,
    working_dir: str = ".",
    target_paths: Optional[list[str]] = None,
    contract_id: Optional[str] = None,
    token_id: Optional[str] = None,
) -> tuple[bool, str, Optional[str]]:
    """
    DEPRECATED: This is a banned oracle function.
    
    Use enforcement.py instead:
        from ck3lens.policy.enforcement import enforce_and_log, EnforcementRequest, OperationType
        result = enforce_and_log(EnforcementRequest(
            operation=OperationType.SHELL_SAFE,  # or SHELL_WRITE, SHELL_DESTRUCTIVE
            mode=...,
            tool_name="ck3_exec",
            command=...,
        ))
    
    This function will be removed in a future version.
    """
    import warnings
    warnings.warn(
        "can_execute is deprecated. Use enforcement.enforce_and_log() instead. "
        "See docs/CANONICAL_ARCHITECTURE.md for the NO-ORACLE pattern.",
        DeprecationWarning,
        stacklevel=2,
    )
    
    request = CommandRequest(
        command=command,
        working_dir=working_dir,
        target_paths=target_paths or [],
        contract_id=contract_id,
        token_id=token_id,
    )
    
    result = evaluate_policy(request)
    
    if result.decision == Decision.ALLOW:
        return True, result.reason, None
    elif result.decision == Decision.DENY:
        return False, result.reason, None
    else:  # REQUIRE_TOKEN
        return False, result.reason, result.required_token_type
