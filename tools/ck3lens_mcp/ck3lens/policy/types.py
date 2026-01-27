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
    Structural domains for ck3lens mode.
    
    These are purely structural classifications - NOT permission decisions.
    Enforcement.py makes all allow/deny decisions at execution time.
    
    For mod files, there is just mods[] - no categories or qualifiers.
    """
    PLAYSET_DB = "playset_db"  # Indexed content from active playset
    VANILLA_GAME = "vanilla_game"
    CK3_UTILITY_FILES = "ck3_utility_files"
    CK3RAVEN_SOURCE = "ck3raven_source"
    WIP_WORKSPACE = "wip_workspace"
    LAUNCHER_REGISTRY = "launcher_registry"


# IntentType REMOVED - BANNED per CANONICAL CONTRACT SYSTEM
# Authorization is based solely on root_category, not intent semantics
# See contract_v1.py for the canonical contract schema


# AcceptanceTest REMOVED - Part of legacy contract schema
# Contract V1 uses work_declaration for audit, not acceptance tests


# =============================================================================
# TOKEN TYPES
# =============================================================================
# DEPRECATED: Token types have been moved to the canonical system.
# See tools/compliance/tokens.py for canonical NST/LXE tokens.
# The deprecated token types below are kept as comments for reference during migration.
#
# CK3LensTokenType (deprecated):
#   DELETE_LOCALMOD, READ_INACTIVE_MOD, REGISTRY_REPAIR, CACHE_DELETE, SCRIPT_EXECUTE
#
# Ck3RavenDevTokenType (deprecated):
#   TEST_EXECUTE, SCRIPT_RUN_WIP, READ_SAFE (Tier A)
#   DELETE_SOURCE, GIT_PUSH, GIT_FORCE_PUSH, GIT_HISTORY_REWRITE, DB_MIGRATION_DESTRUCTIVE (Tier B)
#
# All operations that previously required deprecated tokens now use:
# - Active contract for write operations
# - token_id parameter for explicit confirmation (any value)
# - Phase 2 will implement proper approval flows


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


# Ck3RavenDevIntentType REMOVED - BANNED per CANONICAL CONTRACT SYSTEM
# Authorization is based solely on root_category, not intent semantics
# Intent is declared as free-text in work_declaration (for audit only)

# Ck3RavenDevWipIntent REMOVED - BANNED per Phase 1 cleanup (January 2026)
# WIP workspace constraints are documented in policy, not enforced via enum

# Ck3RavenDevTokenType REMOVED - DEPRECATED January 2026
# See tools/compliance/tokens.py for canonical NST/LXE tokens


# =============================================================================
# CK3RAVEN-DEV GIT COMMAND CLASSIFICATION
# =============================================================================

# Safe git commands (always allowed - per policy doc Section 9)
GIT_COMMANDS_SAFE = frozenset({
    "status", "diff", "log", "show",  # Read-only inspection
    "add", "commit",  # Local staging/committing (allowed without approval)
    "fetch", "pull",  # Read-like remote operations
    "branch -a", "branch -v", "branch --list",  # Branch listing
    "remote", "remote -v",  # Remote listing
    "stash list", "stash show",  # Stash inspection
})

# Risky git commands (require contract - local modifications)
GIT_COMMANDS_RISKY = frozenset({
    "stash", "stash push", "stash pop", "stash drop",  # Stash modifications
    "checkout", "switch",  # Branch switching
    "merge",  # Merging
    "branch",  # Creating/deleting branches (without -a/-v/-l flags)
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
    
    # local_mods_folder boundary (mods here are editable)
    local_mods_folder: Optional[Path] = None
    
    # CK3Raven root path (for source read detection)
    ck3raven_root: Optional[Path] = None
    
    # Contract context (for write operations)
    # intent_type REMOVED - BANNED per canonical spec
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
        if scope.get("local_mods_folder") is not None:
            self.local_mods_folder = Path(scope["local_mods_folder"])
        if scope.get("ck3raven_root") is not None:
            self.ck3raven_root = Path(scope["ck3raven_root"])
        return self
    
    # with_contract REMOVED - IntentType is BANNED per CANONICAL CONTRACT SYSTEM
    # Contract context is now handled via contract_id only


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
