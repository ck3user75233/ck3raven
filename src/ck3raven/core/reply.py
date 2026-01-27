"""
Canonical Reply System - Core Reply Dataclass

This module defines the Reply type used across all tool boundaries.
Every MCP tool must return a Reply object (which is serialized to dict for transport).

Reply Types:
    S (Success)  - Operation completed successfully
    I (Info)     - Operation completed with informational outcome (e.g., nothing to do)
    D (Denied)   - Caller not permitted / precondition not met / refused by governance
    E (Error)    - Unexpected failure (bug, exception, corruption)

Code Format: LAYER-SUBSYSTEM-REPLYTYPE-NNN
    Layers: MCP, WA, EN, CT, DB, PARSE, LEARN, GIT

Canonical Wire Shape:
    {
        "reply_type": "S|I|D|E",
        "code": "NAMESPACE-CAT-SEV-NNN",
        "message": "English human-readable message",
        "data": {...},
        "trace": {"trace_id": "...", "session_id": "..."},
        "meta": {"contract_id": "...", "tool": "...", "layer": "..."}
    }
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional


ReplyType = Literal["S", "I", "D", "E"]
Layer = Literal["MCP", "WA", "EN", "CT", "DB", "PARSE", "LEARN", "GIT"]


@dataclass(frozen=True)
class TraceInfo:
    """Trace correlation identifiers."""
    trace_id: str
    session_id: str
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
        }


@dataclass(frozen=True)
class MetaInfo:
    """Metadata about the reply origin."""
    layer: Layer
    tool: str
    contract_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "layer": self.layer,
            "tool": self.tool,
        }
        if self.contract_id is not None:
            result["contract_id"] = self.contract_id
        return result


@dataclass(frozen=True)
class Reply:
    """
    Canonical reply type for all tool boundaries.
    
    This is a frozen (immutable) dataclass. Use factory methods to create instances.
    """
    reply_type: ReplyType
    code: str
    message: str
    data: Dict[str, Any]
    trace: TraceInfo
    meta: MetaInfo
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to canonical wire format."""
        return {
            "reply_type": self.reply_type,
            "code": self.code,
            "message": self.message,
            "data": self.data,
            "trace": self.trace.to_dict(),
            "meta": self.meta.to_dict(),
        }
    
    # =========================================================================
    # Factory Methods
    # =========================================================================
    
    @classmethod
    def success(
        cls,
        code: str,
        message: str,
        data: Dict[str, Any],
        trace: TraceInfo,
        meta: MetaInfo,
    ) -> Reply:
        """Create a Success reply."""
        return cls(
            reply_type="S",
            code=code,
            message=message,
            data=data,
            trace=trace,
            meta=meta,
        )
    
    @classmethod
    def info(
        cls,
        code: str,
        message: str,
        data: Dict[str, Any],
        trace: TraceInfo,
        meta: MetaInfo,
    ) -> Reply:
        """Create an Info reply."""
        return cls(
            reply_type="I",
            code=code,
            message=message,
            data=data,
            trace=trace,
            meta=meta,
        )
    
    @classmethod
    def denied(
        cls,
        code: str,
        message: str,
        data: Dict[str, Any],
        trace: TraceInfo,
        meta: MetaInfo,
    ) -> Reply:
        """Create a Denied reply."""
        return cls(
            reply_type="D",
            code=code,
            message=message,
            data=data,
            trace=trace,
            meta=meta,
        )
    
    @classmethod
    def error(
        cls,
        code: str,
        message: str,
        data: Dict[str, Any],
        trace: TraceInfo,
        meta: MetaInfo,
    ) -> Reply:
        """Create an Error reply."""
        return cls(
            reply_type="E",
            code=code,
            message=message,
            data=data,
            trace=trace,
            meta=meta,
        )
    
    # =========================================================================
    # Predicates
    # =========================================================================
    
    @property
    def is_success(self) -> bool:
        """True if this is a success reply."""
        return self.reply_type == "S"
    
    @property
    def is_info(self) -> bool:
        """True if this is an info reply."""
        return self.reply_type == "I"
    
    @property
    def is_denied(self) -> bool:
        """True if this is a denied reply."""
        return self.reply_type == "D"
    
    @property
    def is_error(self) -> bool:
        """True if this is an error reply."""
        return self.reply_type == "E"
    
    @property
    def is_ok(self) -> bool:
        """True if this is success or info (operation completed)."""
        return self.reply_type in ("S", "I")
    
    @property
    def is_failure(self) -> bool:
        """True if this is denied or error (operation did not complete)."""
        return self.reply_type in ("D", "E")
