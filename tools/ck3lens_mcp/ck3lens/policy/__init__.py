"""
Policy module - Enforcement and WIP workspace management.

CANONICAL SOURCES (Feb 2026):
- enforcement.py: THE single gate for all policy/permission decisions
- WorldAdapter.classify_path(): THE single source for path classification → RootCategory
- tools/compliance/tokens.py: Canonical token types (NST, LXE only)

Supporting modules:
- loader.py: Policy file loading
- wip_workspace.py: WIP workspace lifecycle management
- contract_v1.py: Contract V1 schema validation
- audit.py: Structured audit logging

DELETED (Feb 2026):
- ScopeDomain / Ck3RavenDevScopeDomain: Parallel to RootCategory - deleted
- classify_path_domain(): Parallel to WorldAdapter.classify_path() - deleted
- enforce_ck3lens_file_restrictions(): Enforcement outside enforcement.py - deleted
- validator.py: Unused quality validation - deleted (revisit in Phase 2)
- ck3lens_rules.py: Unused validation rules - deleted (revisit in Phase 2)
- ck3raven_dev_rules.py: Unused validation rules - deleted (revisit in Phase 2)

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
    # WIP workspace
    WipWorkspaceInfo,
    # Git command classification
    GIT_COMMANDS_SAFE,
    GIT_COMMANDS_RISKY,
    GIT_COMMANDS_NEEDS_APPROVAL,
)
from .loader import load_policy, get_policy

from .wip_workspace import (
    WipWorkspaceState,
    get_workspace_state,
    initialize_workspace,
    cleanup_stale_files,
    ScriptValidation,
    compute_script_hash,
    validate_script_syntax,
    ScriptDeclaration,
    validate_script_declarations,
)

# =============================================================================
# Centralized Enforcement Gate (Clean API)
# =============================================================================
from .enforcement import (
    # Operation types
    OperationType,
    Decision,
    # Result type
    EnforcementResult,
    # Main enforcement function
    enforce,
)

# =============================================================================
# Structured Audit Logging
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
    # Policy types
    "Severity",
    "AgentMode", 
    "Violation",
    "ToolCall",
    "ValidationContext",
    "PolicyOutcome",
    "load_policy",
    "get_policy",
    # WIP Workspace
    "WipWorkspaceInfo",
    "WipWorkspaceState",
    "get_workspace_state",
    "initialize_workspace",
    "cleanup_stale_files",
    "ScriptValidation",
    "compute_script_hash",
    "validate_script_syntax",
    "ScriptDeclaration",
    "validate_script_declarations",
    # Git command classification
    "GIT_COMMANDS_SAFE",
    "GIT_COMMANDS_RISKY",
    "GIT_COMMANDS_NEEDS_APPROVAL",
    # Centralized Enforcement (Clean API)
    "OperationType",
    "Decision",
    "EnforcementResult",
    "enforce",
    # Structured Audit Logging
    "EventCategory",
    "EnforcementLogEntry",
    "AuditLogger",
    "get_audit_logger",
    "reset_audit_logger",
    "count_decisions_by_type",
    "get_denied_operations",
    "get_safe_push_grants",
]
