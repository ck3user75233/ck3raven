"""
Policy Types

Core data types for the agent policy validation system.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional
from pathlib import Path


class Severity(str, Enum):
    """Violation severity levels."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class AgentMode(str, Enum):
    """Supported agent modes."""
    CK3LENS = "ck3lens"
    CK3RAVEN_DEV = "ck3raven-dev"


# =============================================================================
# CK3LENS SCOPE DOMAINS (From CK3LENS_POLICY_ARCHITECTURE.md)
# =============================================================================

class ScopeDomain(str, Enum):
    """
    Scope domains for ck3lens mode access control.
    
    Each domain has specific visibility, read, write, and delete permissions.
    """
    # Always visible, DB-search enabled
    ACTIVE_PLAYSET_DB = "active_playset_db"      # Read only (DB view)
    ACTIVE_LOCAL_MODS = "active_local_mods"      # Read + Write (contract) + Delete (approval)
    ACTIVE_WORKSHOP_MODS = "active_workshop_mods"  # Read only
    VANILLA_GAME = "vanilla_game"                # Read only
    
    # Invisible by default, require explicit user request
    INACTIVE_WORKSHOP_MODS = "inactive_workshop_mods"  # User-prompt + token for read
    INACTIVE_LOCAL_MODS = "inactive_local_mods"        # User-prompt + token for read
    
    # Special domains
    CK3_UTILITY_FILES = "ck3_utility_files"      # Logs, saves, debug files (read only)
    CK3RAVEN_SOURCE = "ck3raven_source"          # Read-only, never writable
    WIP_WORKSPACE = "wip_workspace"              # Session-local, full access
    LAUNCHER_REGISTRY = "launcher_registry"      # Via ck3_repair only


class IntentType(str, Enum):
    """
    Intent types for ck3lens contracts.
    
    Every contract must declare exactly one intent_type.
    Missing intent_type → AUTO_DENY.
    """
    # Write intents
    COMPATCH = "compatch"                # Modify active local mods for compatibility
    BUGPATCH = "bugpatch"                # Patch a bug in another mod via local override
    
    # Read-only intents
    RESEARCH_MOD_ISSUES = "research_mod_issues"    # Research mod conflicts/errors
    RESEARCH_BUGREPORT = "research_bugreport"      # Research to file bug report
    
    # Script intents
    SCRIPT_WIP = "script_wip"            # Draft/run scripts in WIP workspace


class AcceptanceTest(str, Enum):
    """Acceptance tests that can be required for contract completion."""
    DIFF_SANITY = "diff_sanity"          # Proposed scope matches actual touched files (MANDATORY)
    VALIDATION = "validation"            # CK3 syntax/reference validation (best-effort)


# =============================================================================
# TOKEN TYPES FOR CK3LENS (Tier B - Approval Required)
# =============================================================================

class CK3LensTokenType(str, Enum):
    """
    Token types available in ck3lens mode.
    
    All are Tier B (require explicit approval).
    No Tier A (auto-grant) tokens for ck3lens.
    """
    DELETE_LOCALMOD = "DELETE_LOCALMOD"          # Delete files in active local mods (15 min)
    READ_INACTIVE_MOD = "READ_INACTIVE_MOD"      # Read inactive mod (30 min)
    REGISTRY_REPAIR = "REGISTRY_REPAIR"          # Repair mod registry (15 min)
    CACHE_DELETE = "CACHE_DELETE"                # Delete launcher cache (15 min)
    SCRIPT_EXECUTE = "SCRIPT_EXECUTE"            # Execute WIP script (60 min, reusable per hash)


# Token TTLs in minutes
CK3LENS_TOKEN_TTLS = {
    CK3LensTokenType.DELETE_LOCALMOD: 15,
    CK3LensTokenType.READ_INACTIVE_MOD: 30,
    CK3LensTokenType.REGISTRY_REPAIR: 15,
    CK3LensTokenType.CACHE_DELETE: 15,
    CK3LensTokenType.SCRIPT_EXECUTE: 60,
}


# =============================================================================
# CK3RAVEN-DEV SCOPE DOMAINS (From CK3RAVEN_DEV_POLICY_ARCHITECTURE.md)
# =============================================================================

class Ck3RavenDevScopeDomain(str, Enum):
    """
    Scope domains for ck3raven-dev mode access control.
    
    ck3raven-dev is for infrastructure development of the CK3 Lens tooling itself.
    It has NO write access to any mod files (absolute prohibition).
    """
    # Infrastructure source code (primary working area)
    CK3RAVEN_SOURCE = "ck3raven_source"              # Full read/write for code
    CK3LENS_MCP_SOURCE = "ck3lens_mcp_source"        # Full read/write for MCP tools
    CK3LENS_EXPLORER_SOURCE = "ck3lens_explorer_source"  # Full read/write for VS Code ext
    
    # Mod filesystem access (read-only for parser/ingestion development)
    MOD_FILESYSTEM = "mod_filesystem"                # Read-only (parser testing)
    VANILLA_FILESYSTEM = "vanilla_filesystem"        # Read-only (parser testing)
    
    # Database (write with migration requirements)
    CK3RAVEN_DATABASE = "ck3raven_database"          # Read + write (migration context required)
    
    # WIP workspace (strictly constrained, repo-local)
    WIP_WORKSPACE = "wip_workspace"                  # <repo>/.wip/ - analysis/staging only
    
    # System logs and debug info
    CK3_UTILITY_FILES = "ck3_utility_files"          # Read-only (logs, saves, debug)


class Ck3RavenDevIntentType(str, Enum):
    """
    Intent types for ck3raven-dev contracts.
    
    These declare the PURPOSE of infrastructure work.
    Every contract must declare exactly one intent_type.
    """
    BUGFIX = "bugfix"              # Fix a bug in ck3raven infrastructure
    REFACTOR = "refactor"          # Refactor/reorganize code structure
    FEATURE = "feature"            # Implement new feature/capability
    MIGRATION = "migration"        # Database or config migration
    TEST_ONLY = "test_only"        # Add/modify tests only
    DOCS_ONLY = "docs_only"        # Documentation changes only


class Ck3RavenDevWipIntent(str, Enum):
    """
    Intent types for WIP workspace scripts in ck3raven-dev mode.
    
    These are STRICTLY constrained - WIP scripts cannot substitute
    for proper code fixes.
    
    Key constraints:
    - ANALYSIS_ONLY: Read-only analysis, no side effects
    - REFACTOR_ASSIST: Generate refactoring patches (requires core_change_plan)
    - MIGRATION_HELPER: Generate migration scripts (requires core_change_plan)
    """
    ANALYSIS_ONLY = "analysis_only"          # Read-only analysis, no writes
    REFACTOR_ASSIST = "refactor_assist"      # Generate patches for review
    MIGRATION_HELPER = "migration_helper"    # Generate migration scripts


class Ck3RavenDevTokenType(str, Enum):
    """
    Token types for ck3raven-dev mode.
    
    Tier A (Auto-Grant with Logging):
    - Low-risk, high-frequency operations
    - Auto-granted but logged for audit
    
    Tier B (Approval Required):
    - Higher risk operations
    - Require explicit user approval
    """
    # Tier A: Auto-Grant (low-risk, logged)
    TEST_EXECUTE = "TEST_EXECUTE"            # Run pytest/test suite (5 min TTL)
    SCRIPT_RUN_WIP = "SCRIPT_RUN_WIP"        # Execute WIP analysis script (15 min, scope-limited)
    READ_SAFE = "READ_SAFE"                  # Read non-sensitive paths (60 min)
    
    # Tier B: Approval Required (higher risk)
    DELETE_SOURCE = "DELETE_SOURCE"          # Delete source files (15 min)
    GIT_PUSH = "GIT_PUSH"                    # git push (15 min)
    GIT_FORCE_PUSH = "GIT_FORCE_PUSH"        # git push --force (5 min)
    GIT_HISTORY_REWRITE = "GIT_HISTORY_REWRITE"  # rebase, amend (15 min)
    DB_MIGRATION_DESTRUCTIVE = "DB_MIGRATION_DESTRUCTIVE"  # Schema destructive ops (30 min)


# Tier classification for ck3raven-dev tokens
CK3RAVEN_DEV_TOKEN_TIER_A = {
    Ck3RavenDevTokenType.TEST_EXECUTE,
    Ck3RavenDevTokenType.SCRIPT_RUN_WIP,
    Ck3RavenDevTokenType.READ_SAFE,
}

CK3RAVEN_DEV_TOKEN_TIER_B = {
    Ck3RavenDevTokenType.DELETE_SOURCE,
    Ck3RavenDevTokenType.GIT_PUSH,
    Ck3RavenDevTokenType.GIT_FORCE_PUSH,
    Ck3RavenDevTokenType.GIT_HISTORY_REWRITE,
    Ck3RavenDevTokenType.DB_MIGRATION_DESTRUCTIVE,
}

# Token TTLs in minutes for ck3raven-dev
CK3RAVEN_DEV_TOKEN_TTLS = {
    # Tier A
    Ck3RavenDevTokenType.TEST_EXECUTE: 5,
    Ck3RavenDevTokenType.SCRIPT_RUN_WIP: 15,
    Ck3RavenDevTokenType.READ_SAFE: 60,
    # Tier B
    Ck3RavenDevTokenType.DELETE_SOURCE: 15,
    Ck3RavenDevTokenType.GIT_PUSH: 15,
    Ck3RavenDevTokenType.GIT_FORCE_PUSH: 5,
    Ck3RavenDevTokenType.GIT_HISTORY_REWRITE: 15,
    Ck3RavenDevTokenType.DB_MIGRATION_DESTRUCTIVE: 30,
}


# =============================================================================
# CK3RAVEN-DEV GIT COMMAND CLASSIFICATION
# =============================================================================

# Safe git commands (always allowed in ck3raven-dev)
GIT_COMMANDS_SAFE = frozenset({
    "status", "diff", "log", "show", "branch", "remote",
    "stash", "stash list", "stash show",
    "fetch", "pull",  # Read-like operations
})

# Risky git commands (require token or contract)
GIT_COMMANDS_RISKY = frozenset({
    "add", "commit",  # Changes but doesn't push
})

# Dangerous git commands (require explicit token)
GIT_COMMANDS_DANGEROUS = frozenset({
    "push",           # Requires GIT_PUSH token
    "push --force",   # Requires GIT_FORCE_PUSH token
    "rebase",         # Requires GIT_HISTORY_REWRITE token
    "reset --hard",   # Requires GIT_HISTORY_REWRITE token
    "commit --amend", # Requires GIT_HISTORY_REWRITE token
})


# =============================================================================
# WIP WORKSPACE (Common + Mode-Specific)
# =============================================================================

def get_wip_workspace_path(mode: AgentMode = AgentMode.CK3LENS, repo_root: Path | None = None) -> Path:
    """
    Get the WIP workspace path for the specified mode.
    
    ck3lens mode:       ~/.ck3raven/wip/  (general purpose)
    ck3raven-dev mode:  <repo>/.wip/      (strictly constrained)
    
    Args:
        mode: Agent mode to get WIP path for
        repo_root: Repository root (required for ck3raven-dev mode)
    
    Returns:
        Path to WIP workspace directory
    """
    if mode == AgentMode.CK3RAVEN_DEV:
        if repo_root is None:
            # Default to finding the repo root from this file's location
            repo_root = Path(__file__).parents[5]  # Up from policy/types.py to ck3raven root
        return repo_root / ".wip"
    else:
        return Path.home() / ".ck3raven" / "wip"


def get_ck3lens_wip_path() -> Path:
    """Get the ck3lens WIP workspace path (~/.ck3raven/wip/)."""
    return Path.home() / ".ck3raven" / "wip"


def get_ck3raven_dev_wip_path(repo_root: Path | None = None) -> Path:
    """
    Get the ck3raven-dev WIP workspace path (<repo>/.wip/).
    
    This location is:
    - Git-ignored
    - Strictly constrained to analysis/staging only
    - Cannot substitute for proper code fixes
    """
    if repo_root is None:
        repo_root = Path(__file__).parents[5]  # Up from policy/types.py to ck3raven root
    return repo_root / ".wip"


@dataclass
class WipWorkspaceInfo:
    """Information about the WIP workspace state."""
    path: Path
    exists: bool
    mode: AgentMode = AgentMode.CK3LENS
    file_count: int = 0
    last_wiped: Optional[float] = None  # timestamp
    
    @classmethod
    def get_current(cls, mode: AgentMode = AgentMode.CK3LENS, repo_root: Path | None = None) -> "WipWorkspaceInfo":
        """Get current WIP workspace state for the specified mode."""
        wip_path = get_wip_workspace_path(mode, repo_root)
        exists = wip_path.exists()
        file_count = 0
        if exists:
            file_count = sum(1 for _ in wip_path.rglob("*") if _.is_file())
        return cls(path=wip_path, exists=exists, mode=mode, file_count=file_count)


# =============================================================================
# VIOLATION
# =============================================================================

@dataclass
class Violation:
    """A policy violation detected during validation."""
    severity: Severity
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class ToolCall:
    """
    Normalized trace event from the MCP server.
    
    This represents a single tool invocation with its arguments and result metadata.
    """
    name: str
    args: dict[str, Any]
    result_meta: dict[str, Any]
    timestamp_ms: int
    
    @classmethod
    def from_trace_event(cls, event: dict[str, Any]) -> ToolCall:
        """Create from a raw trace event dict."""
        return cls(
            name=event.get("tool", ""),
            args=event.get("args", {}),
            result_meta=event.get("result", {}),
            timestamp_ms=int(event.get("ts", 0) * 1000),  # Convert seconds to ms
        )


@dataclass
class ValidationContext:
    """
    Context for policy validation.
    
    Contains all information needed to validate agent behavior against policy.
    Session scope fields are auto-populated from _get_session_scope() in server.py.
    """
    mode: AgentMode
    policy: dict[str, Any]
    trace: list[ToolCall] = field(default_factory=list)
    
    # Session scope (auto-populated from server session state)
    playset_id: Optional[int] = None
    vanilla_version_id: Optional[str] = None
    
    # Active playset details (auto-populated from server session state)
    active_mod_ids: Optional[set[str]] = None
    active_roots: Optional[set[str]] = None
    vanilla_root: Optional[str] = None
    
    # Local mods whitelist (folder names that are editable)
    local_mods: Optional[set[str]] = None
    
    # CK3Raven root path (for source read detection)
    ck3raven_root: Optional[Path] = None
    
    # Contract context (for write operations)
    intent_type: Optional[IntentType] = None
    contract_id: Optional[str] = None
    
    @classmethod
    def for_mode(cls, mode: str, policy: dict[str, Any], trace: list[ToolCall] | None = None) -> ValidationContext:
        """Create context for a specific mode."""
        try:
            agent_mode = AgentMode(mode)
        except ValueError:
            # Default to ck3lens for unknown modes
            agent_mode = AgentMode.CK3LENS
        
        return cls(
            mode=agent_mode,
            policy=policy,
            trace=trace or [],
        )
    
    def with_session_scope(self, scope: dict[str, Any]) -> "ValidationContext":
        """
        Populate scope fields from session data.
        
        Args:
            scope: Dict from _get_session_scope() containing:
                - playset_id
                - vanilla_version_id
                - active_mod_ids
                - active_roots
                - vanilla_root
                - local_mods
                - ck3raven_root
        
        Returns:
            Self for chaining
        """
        if scope.get("playset_id") is not None:
            self.playset_id = scope["playset_id"]
        if scope.get("vanilla_version_id") is not None:
            self.vanilla_version_id = scope["vanilla_version_id"]
        if scope.get("active_mod_ids") is not None:
            self.active_mod_ids = scope["active_mod_ids"]
        if scope.get("active_roots") is not None:
            self.active_roots = scope["active_roots"]
        if scope.get("vanilla_root") is not None:
            self.vanilla_root = scope["vanilla_root"]
        if scope.get("local_mods") is not None:
            self.local_mods = scope["local_mods"]
        if scope.get("ck3raven_root") is not None:
            self.ck3raven_root = Path(scope["ck3raven_root"])
        return self
    
    def with_contract(self, intent_type: IntentType | str, contract_id: str) -> "ValidationContext":
        """Add contract context."""
        if isinstance(intent_type, str):
            try:
                self.intent_type = IntentType(intent_type)
            except ValueError:
                self.intent_type = None  # Invalid intent will trigger hard gate
        else:
            self.intent_type = intent_type
        self.contract_id = contract_id
        return self


@dataclass
class PolicyOutcome:
    """Result of policy validation."""
    deliverable: bool
    violations: list[Violation] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "deliverable": self.deliverable,
            "violations": [v.to_dict() for v in self.violations],
            "summary": self.summary,
        }
    
    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.ERROR)
    
    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.WARNING)
