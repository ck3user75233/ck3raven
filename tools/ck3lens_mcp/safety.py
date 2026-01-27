"""
MCP Safety Wrapper - Canonical Reply System enforcement.

This module provides the @mcp_safe_tool decorator that wraps all MCP tool handlers
to enforce the Reply contract:

1. Generate trace_id per invocation
2. Attach session_id
3. Set trace_info in context variable (accessible via get_current_trace_info())
4. Catch exceptions -> MCP-SYS-E-001
5. Enforce Reply return type (non-Reply -> MCP-SYS-E-003)
6. Serialize Reply to dict for transport

Usage:
    @mcp.tool()
    @mcp_safe_tool
    def ck3_my_tool(param: str) -> Reply:
        trace_info = get_current_trace_info()
        rb = ReplyBuilder(trace_info, tool='ck3_my_tool')
        return rb.success('CODE', data={...})
"""
from __future__ import annotations

import contextvars
import functools
import traceback
from typing import Any, Callable, Dict, TypeVar, ParamSpec, Optional

from ck3raven.core.reply import Reply, TraceInfo, MetaInfo
from ck3raven.core.trace import generate_trace_id, get_or_create_session_id


P = ParamSpec('P')
T = TypeVar('T')

# Context variable for current trace_info (set by decorator, read by tool)
_current_trace_info: contextvars.ContextVar[Optional[TraceInfo]] = contextvars.ContextVar(
    'current_trace_info', default=None
)


def get_current_trace_info() -> TraceInfo:
    """
    Get the current TraceInfo from context.
    
    Call this from within a @mcp_safe_tool decorated function.
    Raises RuntimeError if called outside of a tool context.
    """
    trace_info = _current_trace_info.get()
    if trace_info is None:
        raise RuntimeError('get_current_trace_info() called outside of @mcp_safe_tool context')
    return trace_info


def mcp_safe_tool(func: Callable[P, Reply]) -> Callable[P, Dict[str, Any]]:
    """
    Decorator that wraps MCP tool handlers for safety and Reply enforcement.
    
    Responsibilities:
    1. Generate unique trace_id per invocation
    2. Get/create session_id
    3. Set trace_info in context variable (access via get_current_trace_info())
    4. Catch ALL exceptions and convert to MCP-SYS-E-001
    5. Enforce that tool returns Reply (non-Reply -> MCP-SYS-E-003)
    6. Serialize Reply to dict for MCP transport
    
    IMPORTANT: Do NOT add trace_info to the function signature. Use
    get_current_trace_info() inside the function to access it.
    """
    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Dict[str, Any]:
        # Generate trace context
        trace_id = generate_trace_id()
        session_id = get_or_create_session_id()
        trace_info = TraceInfo(trace_id=trace_id, session_id=session_id)
        
        tool_name = func.__name__
        
        # Set trace_info in context variable
        token = _current_trace_info.set(trace_info)
        
        try:
            result = func(*args, **kwargs)
            
            # Enforce Reply return type
            if not isinstance(result, Reply):
                actual_type = type(result).__name__
                error_reply = Reply.error(
                    code='MCP-SYS-E-003',
                    message=f'Tool returned {actual_type}, expected Reply.',
                    data={
                        'actual_type': actual_type,
                        'tool': tool_name,
                    },
                    trace=trace_info,
                    meta=MetaInfo(layer='MCP', tool=tool_name),
                )
                return error_reply.to_dict()
            
            return result.to_dict()
            
        except Exception as e:
            # Catch-all: convert to MCP-SYS-E-001
            error_msg = str(e)
            stack_trace = traceback.format_exc()
            
            # Log to disk for debugging
            _log_exception(trace_id, tool_name, e, stack_trace)
            
            error_reply = Reply.error(
                code='MCP-SYS-E-001',
                message=f'Unhandled exception: {error_msg}',
                data={
                    'error': error_msg,
                    'error_type': type(e).__name__,
                    'tool': tool_name,
                },
                trace=trace_info,
                meta=MetaInfo(layer='MCP', tool=tool_name),
            )
            return error_reply.to_dict()
        finally:
            # Reset context variable
            _current_trace_info.reset(token)
    
    return wrapper


def _log_exception(trace_id: str, tool_name: str, exc: Exception, stack_trace: str) -> None:
    """
    Log exception details to disk for debugging.
    """
    import sys
    from datetime import datetime, timezone
    
    ts = datetime.now(timezone.utc).isoformat()
    print(
        f'[{ts}] EXCEPTION trace_id={trace_id} tool={tool_name}\n'
        f'  {type(exc).__name__}: {exc}\n'
        f'{stack_trace}',
        file=sys.stderr,
    )


# ===========================================================================
# Helper for creating Replies with automatic trace injection
# ===========================================================================

class ReplyBuilder:
    """
    Helper class for building Reply objects with pre-set trace and meta.
    
    Usage in tool handlers:
        @mcp.tool()
        @mcp_safe_tool
        def ck3_my_tool(param: str) -> Reply:
            trace_info = get_current_trace_info()
            rb = ReplyBuilder(trace_info, tool='ck3_my_tool')
            
            if not param:
                return rb.denied('MCP-SYS-D-902', {'missing': ['param']})
            
            return rb.success('MCP-SYS-S-900', {'result': 'ok'})
    """
    
    def __init__(
        self,
        trace_info: TraceInfo,
        tool: str,
        layer: str = 'MCP',
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
