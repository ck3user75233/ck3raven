"""
Policy module for agent validation and CLI wrapping.

CANONICAL SOURCES (Jan 2026):
- enforcement.py: THE single gate for all policy/permission decisions
- WorldAdapter.is_visible(): THE single source for path visibility
- tools/compliance/tokens.py: Canonical token types (NST, LXE only)

Supporting modules:
- loader.py: Policy file loading
- validator.py: Policy validation logic
- ck3lens_rules.py: CK3Lens-specific validation rules (POST-HOC, calls enforcement.py)
- wip_workspace.py: WIP workspace lifecycle management
- contract_v1.py: Contract V1 schema validation
- audit.py: Structured audit logging

DEPRECATED (Jan 2026):
- tokens.py: Legacy token system - deprecated in favor of tools/compliance/tokens.py
  - Only canonical tokens remain: NST (New Symbol Token), LXE (Lint Exception Token)
  - All deprecated token types removed (GIT_PUSH, FS_DELETE, etc.)

ARCHIVED (see archive/deprecated_policy/):
- clw.py: Command Line Wrapper - oracle functions archived
- hard_gates.py: Superseded by enforcement.py
- script_sandbox.py: Moved to tools layer
- lensworld_sandbox.py: Merged into WorldAdapter
"""
from .types import (
    Severity,
    AgentMode,
    Violation,
    ToolCall,
    ValidationContext,
    PolicyOutcome,
    # Scope domains
    ScopeDomain,
    Ck3RavenDevScopeDomain,
    # WIP workspace
    WipWorkspaceInfo,
    get_wip_workspace_path,
    get_ck3lens_wip_path,
    get_ck3raven_dev_wip_path,
    # Git command classification
    GIT_COMMANDS_SAFE,
    GIT_COMMANDS_RISKY,
    GIT_COMMANDS_NEEDS_APPROVAL,
)
from .loader import load_policy, get_policy
from .validator import validate_policy, validate_for_mode, server_delivery_gate

# DEPRECATED: tokens.py exports removed (Jan 2026)
# The deprecated token system has been replaced by tools/compliance/tokens.py
# Only NST (New Symbol Token) and LXE (Lint Exception Token) are canonical tokens

from .wip_workspace import (
    WipWorkspaceState,
    get_workspace_state,
    initialize_workspace,
    cleanup_stale_files,
    is_wip_path,
    is_any_wip_path,
    resolve_wip_path,
    write_wip_file,
    read_wip_file,
    delete_wip_file,
    ScriptValidation,
    compute_script_hash,
    validate_script_syntax,
    ScriptDeclaration,
    validate_script_declarations,
)
from .ck3lens_rules import (
    validate_ck3lens_rules,
    classify_path_domain,
    CK3_ALLOWED_EXTENSIONS,
    CK3LENS_FORBIDDEN_PATHS,
    CK3LENS_FORBIDDEN_EXTENSIONS,
    WIP_ONLY_EXTENSIONS,
)

# =============================================================================
# Centralized Enforcement Gate (Phase 1)
# =============================================================================
from .enforcement import (
    # Operation types
    OperationType,
    TokenTier,
    Decision as EnforcementDecision,
    # Request/Result
    EnforcementRequest,
    EnforcementResult,
    # Branch protection
    PROTECTED_BRANCHES,
    is_protected_branch,
    is_agent_branch,
    # Main enforcement function
    enforce_policy as enforce_policy_gate,
    log_enforcement_decision,
    enforce_and_log,
    # Shell command classification
    CommandCategory,
    SAFE_COMMANDS,
    BLOCKED_COMMANDS,
    TOKEN_REQUIRED_PATTERNS,
    GIT_MODIFY_PATTERNS,
    classify_command,
    check_path_in_contract_scope,
)

# =============================================================================
# Structured Audit Logging (Phase 1)
# =============================================================================
from .audit import (
    EventCategory,
    EnforcementLogEntry,
    AuditLogger,
    get_audit_logger,
    reset_audit_logger,
    # Analytics helpers
    count_decisions_by_type,
    get_denied_operations,
    get_safe_push_grants,
)

__all__ = [
    # Policy validation types
    "Severity",
    "AgentMode", 
    "Violation",
    "ToolCall",
    "ValidationContext",
    "PolicyOutcome",
    "load_policy",
    "get_policy",
    "validate_policy",
    "validate_for_mode",
    "server_delivery_gate",
    # Scope domains
    "ScopeDomain",
    "Ck3RavenDevScopeDomain",
    # WIP Workspace
    "WipWorkspaceInfo",
    "get_wip_workspace_path",
    "get_ck3lens_wip_path",
    "get_ck3raven_dev_wip_path",
    "WipWorkspaceState",
    "get_workspace_state",
    "initialize_workspace",
    "cleanup_stale_files",
    "is_wip_path",
    "is_any_wip_path",
    "resolve_wip_path",
    "write_wip_file",
    "read_wip_file",
    "delete_wip_file",
    "ScriptValidation",
    "compute_script_hash",
    "validate_script_syntax",
    "ScriptDeclaration",
    "validate_script_declarations",
    # Git command classification
    "GIT_COMMANDS_SAFE",
    "GIT_COMMANDS_RISKY",
    "GIT_COMMANDS_NEEDS_APPROVAL",
    # CK3Lens Rules
    "validate_ck3lens_rules",
    "classify_path_domain",
    "CK3_ALLOWED_EXTENSIONS",
    "CK3LENS_FORBIDDEN_PATHS",
    "CK3LENS_FORBIDDEN_EXTENSIONS",
    "WIP_ONLY_EXTENSIONS",
    # Centralized Enforcement (Phase 1)
    "OperationType",
    "TokenTier",
    "EnforcementDecision",
    "EnforcementRequest",
    "EnforcementResult",
    "PROTECTED_BRANCHES",
    "is_protected_branch",
    "is_agent_branch",
    "enforce_policy_gate",
    "log_enforcement_decision",
    "enforce_and_log",
    # Shell command classification
    "CommandCategory",
    "SAFE_COMMANDS",
    "BLOCKED_COMMANDS",
    "TOKEN_REQUIRED_PATTERNS",
    "GIT_MODIFY_PATTERNS",
    "classify_command",
    "check_path_in_contract_scope",
    # Structured Audit Logging (Phase 1)
    "EventCategory",
    "EnforcementLogEntry",
    "AuditLogger",
    "get_audit_logger",
    "reset_audit_logger",
    "count_decisions_by_type",
    "get_denied_operations",
    "get_safe_push_grants",
]
