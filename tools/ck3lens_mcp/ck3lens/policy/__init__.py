"""
Policy module for agent validation and CLI wrapping.

CANONICAL SOURCES (Dec 2025):
- enforcement.py: THE single gate for all policy/permission decisions
- WorldAdapter.is_visible(): THE single source for path visibility

Supporting modules:
- types.py: Core types for policy validation (includes ScopeDomain, IntentType, etc.)
- loader.py: Policy file loading
- validator.py: Policy validation logic
- tokens.py: HMAC-signed approval tokens for risky operations
- ck3lens_rules.py: CK3Lens-specific validation rules (POST-HOC, calls enforcement.py)
- wip_workspace.py: WIP workspace lifecycle management
- contract_schema.py: Contract schema validation
- audit.py: Structured audit logging

ARCHIVED (see archive/deprecated_policy/):
- clw.py: Command Line Wrapper - oracle functions archived, classification migrated to enforcement.py
- hard_gates.py: Superseded by enforcement.py - all gate logic consolidated there
- script_sandbox.py: Moved to tools/script_sandbox.py (tool layer)
- lensworld_sandbox.py: Merged into WorldAdapter
"""
from .types import (
    Severity,
    AgentMode,
    Violation,
    ToolCall,
    ValidationContext,
    PolicyOutcome,
    # CK3LENS types (from CK3LENS_POLICY_ARCHITECTURE)
    ScopeDomain,
    IntentType,
    AcceptanceTest,
    CK3LensTokenType,
    CK3LENS_TOKEN_TTLS,
    WipWorkspaceInfo,
    get_wip_workspace_path,
    get_ck3lens_wip_path,
    get_ck3raven_dev_wip_path,
    # CK3RAVEN-DEV types (from CK3RAVEN_DEV_POLICY_ARCHITECTURE)
    Ck3RavenDevScopeDomain,
    Ck3RavenDevIntentType,
    Ck3RavenDevWipIntent,
    Ck3RavenDevTokenType,
    CK3RAVEN_DEV_TOKEN_TIER_A,
    CK3RAVEN_DEV_TOKEN_TIER_B,
    CK3RAVEN_DEV_TOKEN_TTLS,
    GIT_COMMANDS_SAFE,
    GIT_COMMANDS_RISKY,
    GIT_COMMANDS_DANGEROUS,
)
from .loader import load_policy, get_policy
from .validator import validate_policy, validate_for_mode, server_delivery_gate
from .tokens import (
    ApprovalToken,
    TOKEN_TYPES,
    CK3LENS_TOKEN_TYPES,
    issue_token,
    validate_token,
    consume_token,
    revoke_token,
    list_tokens,
    cleanup_expired_tokens,
    # CK3Lens-specific token helpers
    issue_delete_token,
    issue_inactive_mod_token,
    issue_script_execute_token,
    issue_git_push_mod_token,
    validate_script_token,
    check_user_prompt_required,
    check_script_hash_required,
)
# ARCHIVED: clw.py (Dec 2025)
# All CLW functionality migrated to enforcement.py
# - CommandCategory, classify_command, check_path_in_contract_scope -> enforcement.py
# - evaluate_policy, can_execute -> DELETED (banned oracle functions)
# - CommandRequest, PolicyResult, Decision -> use enforcement.py types
# See archive/deprecated_policy/clw.py for original code

# REMOVED: hard_gates imports (Dec 2025)
# hard_gates.py was archived - all enforcement now goes through enforcement.py
# See docs/PLAYSET_ARCHITECTURE.md for canonical sources
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
from .contract_schema import (
    ContractTarget,
    BeforeAfterSnippet,
    WriteContract,
    ResearchContract,
    ScriptContract,
    create_contract,
    validate_contract,
)
from .ck3lens_rules import (
    validate_ck3lens_rules,
    classify_path_domain,
    CK3_ALLOWED_EXTENSIONS,
    CK3LENS_FORBIDDEN_PATHS,
    CK3LENS_FORBIDDEN_EXTENSIONS,
    WIP_ONLY_EXTENSIONS,
)

# DEPRECATED: script_sandbox moved to ck3lens.tools.script_sandbox
# The old policy/script_sandbox.py has been archived.
# Use the tools-layer sandbox instead:
#   from ck3lens.tools.script_sandbox import run_script_sandboxed

# =============================================================================
# NEW: Centralized Enforcement Gate (Phase 1)
# =============================================================================
from .enforcement import (
    # Operation types
    OperationType,
    TokenTier,
    Decision as EnforcementDecision,  # Aliased to avoid conflict with old clw.Decision
    # Request/Result
    EnforcementRequest,
    EnforcementResult,
    # Branch protection
    PROTECTED_BRANCHES,
    is_protected_branch,
    is_agent_branch,
    # Main enforcement function
    enforce_policy as enforce_policy_gate,  # Aliased to distinguish from validator.validate_policy
    log_enforcement_decision,
    enforce_and_log,
    # Shell command classification (migrated from clw.py Dec 2025)
    CommandCategory,
    SAFE_COMMANDS,
    BLOCKED_COMMANDS,
    TOKEN_REQUIRED_PATTERNS,
    GIT_MODIFY_PATTERNS,
    classify_command,
    get_required_token_type,
    check_path_in_contract_scope,
)

# =============================================================================
# NEW: Structured Audit Logging (Phase 1)
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
    # CK3Lens scope and intent types
    "ScopeDomain",
    "IntentType",
    "AcceptanceTest",
    "CK3LensTokenType",
    "CK3LENS_TOKEN_TTLS",
    "WipWorkspaceInfo",
    "get_wip_workspace_path",
    "get_ck3lens_wip_path",
    "get_ck3raven_dev_wip_path",
    # CK3Raven-dev scope and intent types
    "Ck3RavenDevScopeDomain",
    "Ck3RavenDevIntentType",
    "Ck3RavenDevWipIntent",
    "Ck3RavenDevTokenType",
    "CK3RAVEN_DEV_TOKEN_TIER_A",
    "CK3RAVEN_DEV_TOKEN_TIER_B",
    "CK3RAVEN_DEV_TOKEN_TTLS",
    "GIT_COMMANDS_SAFE",
    "GIT_COMMANDS_RISKY",
    "GIT_COMMANDS_DANGEROUS",
    # Approval tokens
    "ApprovalToken",
    "TOKEN_TYPES",
    "CK3LENS_TOKEN_TYPES",
    "issue_token",
    "validate_token",
    "consume_token",
    "revoke_token",
    "list_tokens",
    "cleanup_expired_tokens",
    # CK3Lens token helpers
    "issue_delete_token",
    "issue_inactive_mod_token",
    "issue_script_execute_token",
    "issue_git_push_mod_token",
    "validate_script_token",
    "check_user_prompt_required",
    "check_script_hash_required",
    # CLW Classification (migrated to enforcement.py Dec 2025)
    "CommandCategory",
    "SAFE_COMMANDS",
    "BLOCKED_COMMANDS",
    "TOKEN_REQUIRED_PATTERNS",
    "GIT_MODIFY_PATTERNS",
    "classify_command",
    "get_required_token_type",
    "check_path_in_contract_scope",
    # ARCHIVED: clw.py (Dec 2025)
    # - evaluate_policy, can_execute -> DELETED (banned oracle functions)
    # - CommandRequest, PolicyResult, Decision -> use enforcement.py types
    # REMOVED: Hard gates exports (Dec 2025) - use enforcement.py instead
    # WIP Workspace
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
    # Contract Schema
    "ContractTarget",
    "BeforeAfterSnippet",
    "WriteContract",
    "ResearchContract",
    "ScriptContract",
    "create_contract",
    "validate_contract",
    # CK3Lens Rules
    "validate_ck3lens_rules",
    "classify_path_domain",
    "CK3_ALLOWED_EXTENSIONS",
    "CK3LENS_FORBIDDEN_PATHS",
    "CK3LENS_FORBIDDEN_EXTENSIONS",
    "WIP_ONLY_EXTENSIONS",
    # Script Sandbox - DEPRECATED (moved to ck3lens.tools.script_sandbox)
    # =============================================================================
    # NEW: Centralized Enforcement (Phase 1)
    # =============================================================================
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
    # =============================================================================
    # NEW: Structured Audit Logging (Phase 1)
    # =============================================================================
    "EventCategory",
    "EnforcementLogEntry",
    "AuditLogger",
    "get_audit_logger",
    "reset_audit_logger",
    "count_decisions_by_type",
    "get_denied_operations",
    "get_safe_push_grants",
]
