"""
Audit Trail and Enforcement Logging

This module provides structured logging for policy enforcement decisions.
Every enforcement decision is logged to enable:
- Analytics on enforcement patterns
- Debugging policy issues
- Compliance auditing
- Workaround detection

Log Schema:
All enforcement events have a consistent structure for easy analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Optional, TypedDict
from datetime import datetime


# =============================================================================
# LOG EVENT SCHEMAS
# =============================================================================

class EventCategory(str, Enum):
    """Categories of audit events."""
    ENFORCEMENT = "enforcement"
    CONTRACT = "contract"
    TOKEN = "token"
    GIT = "git"
    FILE = "file"
    EXEC = "exec"
    LENSWORLD = "lensworld"


class EnforcementEventV1(TypedDict, total=False):
    """
    Schema V1 for enforcement log events.
    
    All fields are snake_case for JSON serialization.
    """
    # Required fields
    event_version: int          # Schema version (1)
    event_category: str         # EventCategory value
    timestamp: str              # ISO 8601 timestamp
    session_id: str             # Session identifier
    
    # Enforcement context
    operation_type: str         # OperationType.name
    mode: str                   # "ck3lens" or "ck3raven-dev"
    tool_name: str              # MCP tool that triggered enforcement
    
    # Decision
    decision: str               # Reply type ("S", "D", "E") from enforcement
    reason: str                 # Human-readable reason
    
    # Auth context (optional)
    contract_id: Optional[str]
    token_id: Optional[str]
    required_token_type: Optional[str]
    
    # Scope context (optional)
    target_path: Optional[str]
    target_paths: Optional[list[str]]
    mod_name: Optional[str]
    command: Optional[str]
    
    # Git-specific (optional)
    branch: Optional[str]
    staged_files: Optional[list[str]]
    safe_push_autogrant: Optional[bool]
    
    # Scope check details (optional)
    scope_check: Optional[dict[str, Any]]
    
    # LensWorld context (optional)
    lens_path_type: Optional[str]      # "inside" or "outside"
    lens_resolution_result: Optional[str]  # "found" or "not_found"


@dataclass
class EnforcementLogEntry:
    """
    Structured enforcement log entry.
    
    This is the standard format for logging enforcement decisions.
    """
    event_version: int
    event_category: str
    timestamp: str
    session_id: str
    
    operation_type: str
    mode: str
    tool_name: str
    
    decision: str
    reason: str
    
    contract_id: Optional[str] = None
    token_id: Optional[str] = None
    required_token_type: Optional[str] = None
    
    target_path: Optional[str] = None
    target_paths: Optional[list[str]] = None
    mod_name: Optional[str] = None
    command: Optional[str] = None
    
    branch: Optional[str] = None
    staged_files: Optional[list[str]] = None
    safe_push_autogrant: Optional[bool] = None
    
    scope_check: Optional[dict[str, Any]] = None
    
    lens_path_type: Optional[str] = None
    lens_resolution_result: Optional[str] = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        d = asdict(self)
        # Remove None values for cleaner logs
        return {k: v for k, v in d.items() if v is not None}


# =============================================================================
# AUDIT LOGGER
# =============================================================================

class AuditLogger:
    """
    Audit logger for enforcement decisions.
    
    Wraps ToolTrace to provide structured enforcement logging.
    """
    
    def __init__(self, trace, session_id: str):
        """
        Initialize the audit logger.
        
        Args:
            trace: ToolTrace instance
            session_id: Current session identifier
        """
        self.trace = trace
        self.session_id = session_id
    
    def log_enforcement(
        self,
        operation_type: str,
        mode: str,
        tool_name: str,
        decision: str,
        reason: str,
        *,
        contract_id: Optional[str] = None,
        token_id: Optional[str] = None,
        required_token_type: Optional[str] = None,
        target_path: Optional[str] = None,
        target_paths: Optional[list[str]] = None,
        mod_name: Optional[str] = None,
        command: Optional[str] = None,
        branch: Optional[str] = None,
        staged_files: Optional[list[str]] = None,
        safe_push_autogrant: Optional[bool] = None,
        scope_check: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Log an enforcement decision.
        
        This is the primary logging method for all enforcement decisions.
        """
        entry = EnforcementLogEntry(
            event_version=1,
            event_category=EventCategory.ENFORCEMENT.value,
            timestamp=datetime.utcnow().isoformat() + "Z",
            session_id=self.session_id,
            operation_type=operation_type,
            mode=mode,
            tool_name=tool_name,
            decision=decision,
            reason=reason,
            contract_id=contract_id,
            token_id=token_id,
            required_token_type=required_token_type,
            target_path=target_path,
            target_paths=target_paths,
            mod_name=mod_name,
            command=command,
            branch=branch,
            staged_files=staged_files,
            safe_push_autogrant=safe_push_autogrant,
            scope_check=scope_check,
        )
        
        # Log to trace
        self.trace.log(
            f"audit.{EventCategory.ENFORCEMENT.value}",
            entry.to_dict(),
            {"decision": decision},
        )
    
    def log_contract_event(
        self,
        event_type: str,  # "opened", "closed", "cancelled", "expired"
        contract_id: str,
        intent: Optional[str] = None,
        domains: Optional[list[str]] = None,
        duration_seconds: Optional[float] = None,
    ) -> None:
        """Log a contract lifecycle event."""
        self.trace.log(
            f"audit.{EventCategory.CONTRACT.value}",
            {
                "event_version": 1,
                "event_category": EventCategory.CONTRACT.value,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "session_id": self.session_id,
                "event_type": event_type,
                "contract_id": contract_id,
                "intent": intent,
                "domains": domains,
                "duration_seconds": duration_seconds,
            },
            {"event_type": event_type, "contract_id": contract_id},
        )
    
    def log_token_event(
        self,
        event_type: str,  # "requested", "granted", "used", "expired", "revoked"
        token_type: str,
        token_id: Optional[str] = None,
        contract_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Log a token lifecycle event."""
        self.trace.log(
            f"audit.{EventCategory.TOKEN.value}",
            {
                "event_version": 1,
                "event_category": EventCategory.TOKEN.value,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "session_id": self.session_id,
                "event_type": event_type,
                "token_type": token_type,
                "token_id": token_id,
                "contract_id": contract_id,
                "reason": reason,
            },
            {"event_type": event_type, "token_type": token_type},
        )
    
    def log_lensworld_resolution(
        self,
        path: str,
        path_type: str,  # "inside" or "outside"
        result: str,     # "found" or "not_found"
        mode: str,
    ) -> None:
        """Log a LensWorld path resolution event."""
        self.trace.log(
            f"audit.{EventCategory.LENSWORLD.value}",
            {
                "event_version": 1,
                "event_category": EventCategory.LENSWORLD.value,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "session_id": self.session_id,
                "path": path,
                "path_type": path_type,
                "result": result,
                "mode": mode,
            },
            {"path_type": path_type, "result": result},
        )


# =============================================================================
# SINGLETON ACCESSOR
# =============================================================================

_audit_logger: Optional[AuditLogger] = None


def get_audit_logger(trace, session_id: str) -> AuditLogger:
    """
    Get or create the audit logger singleton.
    
    Args:
        trace: ToolTrace instance
        session_id: Current session identifier
        
    Returns:
        AuditLogger instance
    """
    global _audit_logger
    if _audit_logger is None or _audit_logger.session_id != session_id:
        _audit_logger = AuditLogger(trace, session_id)
    return _audit_logger


def reset_audit_logger() -> None:
    """Reset the audit logger singleton (for testing)."""
    global _audit_logger
    _audit_logger = None


# =============================================================================
# ANALYTICS HELPERS
# =============================================================================

def count_decisions_by_type(events: list[dict]) -> dict[str, int]:
    """
    Count enforcement decisions by type from trace events.
    
    Args:
        events: List of trace events
        
    Returns:
        Dict mapping decision type to count
    """
    counts: dict[str, int] = {}
    for event in events:
        if event.get("tool", "").startswith("audit.enforcement"):
            decision = event.get("result", {}).get("decision")
            if decision:
                counts[decision] = counts.get(decision, 0) + 1
    return counts


def get_denied_operations(events: list[dict]) -> list[dict]:
    """
    Get all DENY decisions from trace events.
    
    Args:
        events: List of trace events
        
    Returns:
        List of denied operation events
    """
    return [
        event for event in events
        if event.get("tool", "").startswith("audit.enforcement")
        and event.get("result", {}).get("decision") == "DENY"
    ]


def get_safe_push_grants(events: list[dict]) -> list[dict]:
    """
    Get all SAFE PUSH auto-grant events.
    
    Args:
        events: List of trace events
        
    Returns:
        List of safe push events
    """
    return [
        event for event in events
        if event.get("tool", "").startswith("audit.enforcement")
        and event.get("args", {}).get("safe_push_autogrant") is True
    ]
