"""
Policy Types

Core data types for the agent policy validation system.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
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
# GIT COMMAND CLASSIFICATION
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

# Git commands requiring user approval (via ck3_git tool enforcement)
# These go through _enforce_git_push() which implements SAFE PUSH auto-grant
GIT_COMMANDS_NEEDS_APPROVAL = frozenset({
    "push",           # Requires contract + valid branch + staged files in scope
    "push --force",   # Requires user approval (never auto-granted)
    "rebase",         # Requires user approval
    "reset --hard",   # Requires user approval
    "commit --amend", # Requires user approval
})


# =============================================================================
# WIP WORKSPACE
# =============================================================================

def get_wip_workspace_path(mode: AgentMode = AgentMode.CK3LENS) -> Path:
    """
    Get the WIP workspace path for the specified mode.
    
    ck3lens mode:       ~/.ck3raven/wip/  (general purpose)
    ck3raven-dev mode:  Uses ROOT_REPO/.wip/ via paths.py
    
    Args:
        mode: Agent mode to get WIP path for
    
    Returns:
        Path to WIP workspace directory
    """
    if mode == AgentMode.CK3RAVEN_DEV:
        from ..paths import ROOT_REPO
        if ROOT_REPO is None:
            raise RuntimeError("ROOT_REPO not configured - run paths_doctor")
        return ROOT_REPO / ".wip"
    else:
        return Path.home() / ".ck3raven" / "wip"


def get_ck3lens_wip_path() -> Path:
    """Get the ck3lens WIP workspace path (~/.ck3raven/wip/)."""
    return Path.home() / ".ck3raven" / "wip"


def get_ck3raven_dev_wip_path() -> Path:
    """
    Get the ck3raven-dev WIP workspace path (<repo>/.wip/).
    
    This location is:
    - Git-ignored
    - Strictly constrained to analysis/staging only
    - Cannot substitute for proper code fixes
    """
    from ..paths import ROOT_REPO
    if ROOT_REPO is None:
        raise RuntimeError("ROOT_REPO not configured - run paths_doctor")
    return ROOT_REPO / ".wip"


@dataclass
class WipWorkspaceInfo:
    """Information about the WIP workspace state."""
    path: Path
    exists: bool
    mode: AgentMode = AgentMode.CK3LENS
    file_count: int = 0
    last_wiped: Optional[float] = None  # timestamp
    
    @classmethod
    def get_current(cls, mode: AgentMode = AgentMode.CK3LENS) -> "WipWorkspaceInfo":
        """Get current WIP workspace state for the specified mode."""
        wip_path = get_wip_workspace_path(mode)
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
    
    # local_mods_folder boundary (mods here are editable)
    local_mods_folder: Optional[Path] = None
    
    # Contract context (for write operations)
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
                - local_mods_folder
                
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
        if scope.get("local_mods_folder") is not None:
            self.local_mods_folder = Path(scope["local_mods_folder"])
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
