"""
Trace Context - Request correlation identifiers.

Provides trace_id (per-invocation) and session_id (per-session) for correlating
operations across tool calls and layers.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Optional


def generate_trace_id() -> str:
    """Generate a unique trace ID for a single tool invocation."""
    return uuid.uuid4().hex[:16]


def generate_session_id() -> str:
    """Generate a unique session ID (stable across multiple calls in a session)."""
    return uuid.uuid4().hex[:16]


# Thread-local storage for trace context
_context = threading.local()


@dataclass
class TraceContext:
    """
    Context for trace/session IDs.
    
    Usage:
        # At session start
        ctx = TraceContext(session_id=generate_session_id())
        ctx.set_current()
        
        # In tool handler
        trace_id = generate_trace_id()
        current_ctx = TraceContext.get_current()
        session_id = current_ctx.session_id if current_ctx else "unknown"
    """
    session_id: str
    trace_id: Optional[str] = None
    
    def set_current(self) -> None:
        """Set this context as current for the thread."""
        _context.current = self
    
    @classmethod
    def get_current(cls) -> Optional[TraceContext]:
        """Get the current context for this thread, or None if not set."""
        return getattr(_context, "current", None)
    
    @classmethod
    def clear_current(cls) -> None:
        """Clear the current context."""
        if hasattr(_context, "current"):
            delattr(_context, "current")
    
    def with_trace_id(self, trace_id: str) -> TraceContext:
        """Return a new context with the given trace_id."""
        return TraceContext(session_id=self.session_id, trace_id=trace_id)


def get_or_create_session_id() -> str:
    """Get current session ID, or create one if none exists."""
    ctx = TraceContext.get_current()
    if ctx is not None:
        return ctx.session_id
    
    # Create new session context
    session_id = generate_session_id()
    ctx = TraceContext(session_id=session_id)
    ctx.set_current()
    return session_id


def get_trace_context(trace_id: Optional[str] = None) -> TraceContext:
    """
    Get a trace context for the current operation.
    
    If trace_id is not provided, generates a new one.
    Uses the current session_id if available, otherwise creates a new session.
    """
    session_id = get_or_create_session_id()
    return TraceContext(
        session_id=session_id,
        trace_id=trace_id or generate_trace_id(),
    )
