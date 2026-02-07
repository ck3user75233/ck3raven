"""
ck3raven - CK3 Game State Emulator

A Python toolkit for parsing, merging, and resolving mod conflicts in Crusader Kings III.

Modules:
    parser - 100% regex-free PDX script parser
    resolver - Merge policies and conflict resolution
    db - SQLite database with content-addressed storage
    emulator - Game state building from playsets
    tools - Analysis and development utilities

IMPORT ARCHITECTURE:
This module uses LAZY imports to avoid loading heavy dependencies (DB, resolver)
when only the parser is needed. Subprocess parsing imports only parser modules.
"""

__version__ = "0.1.0"
__author__ = "ck3raven contributors"


def __getattr__(name: str):
    """Lazy import for heavy dependencies - only loads when accessed."""
    if name == "parse_file":
        from ck3raven.parser import parse_file
        return parse_file
    elif name == "parse_source":
        from ck3raven.parser import parse_source
        return parse_source
    elif name == "MergePolicy":
        from ck3raven.resolver import MergePolicy
        return MergePolicy
    elif name == "CONTENT_TYPES":
        from ck3raven.resolver import CONTENT_TYPES
        return CONTENT_TYPES
    elif name == "init_database":
        from ck3raven.db import init_database
        return init_database
    raise AttributeError(f"module 'ck3raven' has no attribute {name!r}")


__all__ = [
    # Parser
    "parse_file",
    "parse_source",
    # Resolver
    "MergePolicy", 
    "CONTENT_TYPES",
    # Database
    "init_database",
]
