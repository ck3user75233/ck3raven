"""
DebugSession - Unified debug infrastructure for the daemon pipeline.

Usage:
    from builder.debug import DebugSession, DebugConfig
    
    debug = DebugSession.from_config(output_dir, sample_limit=100)
    
    with debug.span("file", phase="parse", path=path) as s:
        ast = parse(content)
        s.add(ast_bytes=len(blob), nodes=count)
    
    debug.close()
"""
from .session import DebugSession, DebugConfig, SpanContext, PhaseStats

__all__ = ["DebugSession", "DebugConfig", "SpanContext", "PhaseStats"]
