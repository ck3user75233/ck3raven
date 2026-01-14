"""
ck3raven - CK3 Game State Emulator

A Python toolkit for parsing, merging, and resolving mod conflicts in Crusader Kings III.

Modules:
    parser - 100% regex-free PDX script parser
    resolver - Merge policies and conflict resolution
    db - SQLite database with content-addressed storage
    emulator - Game state building from playsets
    tools - Analysis and development utilities
"""

__version__ = "0.1.0"
__author__ = "ck3raven contributors"

# Core parser functions (most commonly used)
from ck3raven.parser import parse_file, parse_source

# Re-export key classes for convenience
from ck3raven.resolver import MergePolicy, CONTENT_TYPES
from ck3raven.db import init_database

# NOTE: ingest_vanilla/ingest_mod removed - qbuilder/discovery.py is the canonical ingestion path

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
