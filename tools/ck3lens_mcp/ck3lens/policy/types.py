"""
Policy Types

Core data types for the agent policy validation system.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    """Violation severity levels."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class AgentMode(str, Enum):
    """Supported agent modes."""
    CK3LENS = "ck3lens"
    CK3RAVEN_DEV = "ck3raven-dev"


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
