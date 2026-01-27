"""
MCP Safety Wrapper - Canonical Reply System enforcement.

This module provides the @mcp_safe_tool decorator that wraps all MCP tool handlers
to enforce the Reply contract:

1. Generate trace_id per invocation
2. Attach session_id
3. Catch exceptions -> MCP-SYS-E-001
4. Enforce Reply return type (non-Reply -> MCP-SYS-E-003)
5. Serialize Reply to dict for transport

Usage:
    @mcp_safe_tool
    def ck3_my_tool(param: str) -> Reply:
        ...
        return Reply.success(...)
"""
from __future__ import annotations

import functools
import traceback
from typing import Any, Callable, Dict, TypeVar, ParamSpec

from ck3raven.core.reply import Reply, TraceInfo, MetaInfo
from ck3raven.core.trace import generate_trace_id, get_or_create_session_id


P = ParamSpec("P")
T = TypeVar("T")


def mcp_safe_tool(func: Callable[P, Reply]) -> Callable[P, Dict[str, Any]]:
    """
    Decorator that wraps MCP tool handlers for safety and Reply enforcement.
    
    Responsibilities:
    1. Generate unique trace_id per invocation
    2. Get/create session_id
    3. Catch ALL exceptions and convert to MCP-SYS-E-001
    4. Enforce that tool returns Reply (non-Reply -> MCP-SYS-E-003)
    5. Serialize Reply to dict for MCP transport
    
    The wrapped function receives injected 'trace_info' kwarg if it accepts one.
    """
    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Dict[str, Any]:
        # Generate trace context
        trace_id = generate_trace_id()
        session_id = get_or_create_session_id()
        trace_info = TraceInfo(trace_id=trace_id, session_id=session_id)
        
        # Inject trace_info if function accepts it
        import inspect
        sig = inspect.signature(func)
        if "trace_info" in sig.parameters:
            kwargs["trace_info"] = trace_info
        
        tool_name = func.__name__
        
        try:
            result = func(*args, **kwargs)
            
            # Enforce Reply return type
            if not isinstance(result, Reply):
                actual_type = type(result).__name__
                error_reply = Reply.error(
                    code="MCP-SYS-E-003",
                    message=f"Tool returned {actual_type}, expected Reply.",
                    data={
                        "actual_type": actual_type,
                        "tool": tool_name,
                    },
                    trace=trace_info,
                    meta=MetaInfo(layer="MCP", tool=tool_name),
                )
                return error_reply.to_dict()
            
            return result.to_dict()
            
        except Exception as e:
            # Catch-all: convert to MCP-SYS-E-001
            error_msg = str(e)
            stack_trace = traceback.format_exc()
            
            # Log to disk for debugging (optional - can be enhanced later)
            _log_exception(trace_id, tool_name, e, stack_trace)
            
            error_reply = Reply.error(
                code="MCP-SYS-E-001",
                message=f"Unhandled exception: {error_msg}",
                data={
                    "error": error_msg,
                    "error_type": type(e).__name__,
                    "tool": tool_name,
                },
                trace=trace_info,
                meta=MetaInfo(layer="MCP", tool=tool_name),
            )
            return error_reply.to_dict()
    
    return wrapper


def _log_exception(trace_id: str, tool_name: str, exc: Exception, stack_trace: str) -> None:
    """
    Log exception details to disk for debugging.
    
    This is a placeholder for proper structured logging integration.
    Currently writes to stderr to avoid silent failures.
    """
    import sys
    from datetime import datetime, timezone
    
    ts = datetime.now(timezone.utc).isoformat()
    print(
        f"[{ts}] EXCEPTION trace_id={trace_id} tool={tool_name}\n"
        f"  {type(exc).__name__}: {exc}\n"
        f"{stack_trace}",
        file=sys.stderr,
    )


# =============================================================================
# Helper for creating Replies with automatic trace injection
# =============================================================================

class ReplyBuilder:
    """
    Helper class for building Reply objects with pre-set trace and meta.
    
    Usage in tool handlers:
        def ck3_my_tool(param: str, *, trace_info: TraceInfo) -> Reply:
            rb = ReplyBuilder(trace_info, tool="ck3_my_tool")
            
            if not param:
                return rb.denied("MCP-SYS-D-902", {"missing": ["param"]})
            
            return rb.success("MCP-SYS-S-900", {"result": "ok"})
    """
    
    def __init__(
        self,
        trace_info: TraceInfo,
        tool: str,
        layer: str = "MCP",
        contract_id: str | None = None,
    ):
        self.trace_info = trace_info
        self.tool = tool
        self.layer = layer
        self.contract_id = contract_id
    
    def _meta(self, layer: str | None = None) -> MetaInfo:
        """Create MetaInfo with optional layer override."""
        return MetaInfo(
            layer=layer or self.layer,  # type: ignore
            tool=self.tool,
            contract_id=self.contract_id,
        )
    
    def success(
        self,
        code: str,
        data: Dict[str, Any],
        message: str | None = None,
        layer: str | None = None,
    ) -> Reply:
        """Create a Success reply."""
        from ck3raven.core.reply_registry import get_message
        return Reply.success(
            code=code,
            message=message or get_message(code, **data),
            data=data,
            trace=self.trace_info,
            meta=self._meta(layer),
        )
    
    def info(
        self,
        code: str,
        data: Dict[str, Any],
        message: str | None = None,
        layer: str | None = None,
    ) -> Reply:
        """Create an Info reply."""
        from ck3raven.core.reply_registry import get_message
        return Reply.info(
            code=code,
            message=message or get_message(code, **data),
            data=data,
            trace=self.trace_info,
            meta=self._meta(layer),
        )
    
    def denied(
        self,
        code: str,
        data: Dict[str, Any],
        message: str | None = None,
        layer: str | None = None,
    ) -> Reply:
        """Create a Denied reply."""
        from ck3raven.core.reply_registry import get_message
        return Reply.denied(
            code=code,
            message=message or get_message(code, **data),
            data=data,
            trace=self.trace_info,
            meta=self._meta(layer),
        )
    
    def error(
        self,
        code: str,
        data: Dict[str, Any],
        message: str | None = None,
        layer: str | None = None,
    ) -> Reply:
        """Create an Error reply."""
        from ck3raven.core.reply_registry import get_message
        return Reply.error(
            code=code,
            message=message or get_message(code, **data),
            data=data,
            trace=self.trace_info,
            meta=self._meta(layer),
        )
