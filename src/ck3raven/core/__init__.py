"""
ck3raven.core - Cross-cutting primitives for the ck3raven system.

This package contains foundational types used across all layers:
- Reply: Canonical response type for all tool boundaries
- Trace: Request correlation (trace_id, session_id)
"""
from ck3raven.core.reply import Reply
from ck3raven.core.trace import TraceContext, generate_trace_id, generate_session_id

__all__ = [
    "Reply",
    "TraceContext",
    "generate_trace_id",
    "generate_session_id",
]
