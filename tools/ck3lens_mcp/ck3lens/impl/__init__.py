"""
CK3 Lens Implementation Package

Shared implementation modules for CK3 Lens operations.
Used by both MCP server (server.py) and VS Code extension bridge.

These modules provide pure functions that:
1. Take explicit parameters (db connection, CVID lists, paths)
2. Avoid reliance on global state
3. Do NOT use playset_mods table (BANNED per CANONICAL_ARCHITECTURE.md)
4. Can be imported safely without FastMCP side effects

Architecture:
- MCP server.py imports from here and wraps with FastMCP decorators
- Bridge server.py imports from here directly
- Both get consistent behavior without import issues

Usage from bridge:
    from ck3lens.impl import playset_ops, search_ops
    
    # Get active playset mods
    mods = playset_ops.get_playset_mods()
    
    # Search symbols with CVID filtering
    cvids = {m['content_version_id'] for m in mods.get('mods', [])}
    results = search_ops.search_symbols(conn, query, cvids)

Modules:
- playset_ops: Playset JSON file operations (list, switch, get mods)
- search_ops: Symbol search with FTS5 and CVID filtering
- file_ops: File listing and retrieval with CVID filtering
- conflict_ops: Conflict detection with CVID filtering
"""

from . import playset_ops
from . import search_ops
from . import file_ops
from . import conflict_ops

__all__ = [
    'playset_ops',
    'search_ops', 
    'file_ops',
    'conflict_ops',
]
