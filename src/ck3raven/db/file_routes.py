"""
Centralized File Processing Rules for CK3 Database Builder

This module defines HOW each file type should be processed.
All builder functions use these rules for consistency.

ARCHITECTURE:
┌─────────────────────────────────────────────────────────────────┐
│                    FILE PROCESSING ROUTES                        │
├─────────────────────────────────────────────────────────────────┤
│ Route 1: SCRIPT                                                  │
│   .txt in common/, events/ (most files)                          │
│   → Parse with script parser → AST → symbol extraction           │
│                                                                  │
│ Route 2: LOCALIZATION                                            │
│   .yml in localization/                                           │
│   → Parse with loc parser → localization_entries table (no AST)  │
│                                                                  │
│ Route 3: LOOKUPS (future - currently ingest only)                │
│   history/characters/, history/provinces/, history/titles/       │
│   names/, coat_of_arms/coat_of_arms/, dynasties/                 │
│   → Currently: ingest + skip further processing                  │
│   → Future: specialized extractors → lookup tables               │
│                                                                  │
│ Route 4: SKIP                                                     │
│   Binary files, docs, deferred content                           │
│   → No processing, just store in file_contents                   │
└─────────────────────────────────────────────────────────────────┘

DESIGN PRINCIPLES:
1. If a file gets an AST, it's eligible for symbol extraction (no separate skip)
2. Files with special parsers don't go through AST pipeline
3. Reference tables (provinces, titles, characters) enable validation
4. All rules in ONE place - no scattered skip logic

Usage:
    from ck3raven.db.file_routes import (
        get_file_route,
        FileRoute,
        should_process_with_script_parser,
        should_process_with_loc_parser,
    )
"""

from enum import Enum
from typing import Tuple, List, Optional
from pathlib import Path


class FileRoute(Enum):
    """How a file should be processed."""
    SCRIPT = "script"              # Parse → AST → symbols
    LOCALIZATION = "localization"  # Parse → localization_entries table
    LOOKUPS = "lookups"            # Future: Specialized extractors → lookup tables (currently ingest only)
    SKIP = "skip"                  # No processing


# =============================================================================
# Route Definitions
# =============================================================================

# Files processed by SCRIPT_PARSER (AST + symbols)
# These are the "normal" CK3 script files
SCRIPT_PARSER_FOLDERS: List[str] = [
    'common/traits',
    'common/decisions',
    'common/scripted_effects',
    'common/scripted_triggers',
    'common/on_action',
    'common/character_interactions',
    'common/script_values',
    'common/buildings',
    'common/culture',
    'common/religion',
    'common/governments',
    'common/laws',
    'common/casus_belli_types',
    'common/schemes',
    'common/activities',
    'common/artifacts',
    'common/dynasty_perks',
    'common/lifestyle',
    'common/focuses',
    'common/perks',
    'common/men_at_arms_types',
    'common/modifiers',
    'common/customizable_localization',  # Valid script, not yml
    'common/flavorization',
    'common/game_rules',
    'common/important_actions',
    'common/nicknames',
    'common/bookmark_portraits',
    'common/landed_titles',  # Has symbols (title definitions)
    'common/accolade_names',  # Has scripted triggers - needs full AST
    'events/',
]

# Files processed by LOCALIZATION_PARSER (no AST, populate loc_keys table)
LOCALIZATION_PATTERNS: List[str] = [
    'localization/',
]

# Files destined for LOOKUP TABLES (future specialized extractors)
# Currently: ingest only, no further processing in build phases
# Future: each type gets a specialized extractor (no full AST needed)
LOOKUPS_PATTERNS: List[str] = [
    # Province data - needed to validate province:1234 references
    'history/provinces/',
    
    # Character history - needed to validate character:12345 references  
    'history/characters/',
    
    # Title history - needed to validate title holder references
    'history/titles/',
    
    # Dynasty definitions - dynasty ID lookups
    'common/dynasties/',
    
    # Name lists - name validation
    'name_lists/',
    '/names/',
    
    # Coat of arms definitions - CoA ID lookups
    'coat_of_arms/coat_of_arms/',
]

# Files to SKIP entirely (binary, docs, deferred)
SKIP_PATTERNS: List[str] = [
    # =========================================================================
    # BINARY/NON-SCRIPT - Not parseable at all
    # =========================================================================
    'gfx/',
    '/fonts/',
    '/sounds/',
    '/music/',
    '/licenses/',
    '#backup/',
    '/generated/',
    'checksum_manifest.txt',
    '.mod',
    
    # Documentation files
    'notes.txt',
    'to do.txt',
    'todo.txt',
    'readme.txt',
    'readme.md',
    'changelog.txt',
    'changelog.md',
    'credits.txt',
    'description.txt',
    'steam_description.txt',
    'ibl-description',
    'me-ibl_description',
    
    # License files
    'ofl.txt',
    'license.txt',
    'license.md',
    
    # =========================================================================
    # DEFERRED - Valid script but not in current scope
    # See DATABASE_BUILDER.md for details on each
    # =========================================================================
    
    # GUI - Different syntax (.gui files), rare .txt
    'gui/',
    
    # Map data - Coordinates, terrain assignments
    'map_data/',
    'terrain/',
    'adjacencies',
    'positions.txt',
    
    # Interface definitions
    'interface/',
    
    # Test files in production mods
    'tests/',
    'test_',
    '_test.txt',
]


# =============================================================================
# Route Resolution
# =============================================================================

def _matches_any(relpath: str, patterns: List[str]) -> bool:
    """Check if relpath matches any pattern (case-insensitive substring)."""
    # Normalize path separators to forward slash for consistent matching
    relpath_normalized = relpath.replace('\\', '/').lower()
    return any(pattern.lower() in relpath_normalized for pattern in patterns)


def get_file_route(relpath: str) -> Tuple[FileRoute, str]:
    """
    Determine how a file should be processed.
    
    Args:
        relpath: Relative path within mod/vanilla (e.g., "common/traits/00_traits.txt")
        
    Returns:
        (route, reason) - The processing route and explanation
    """
    # Normalize path separators
    relpath = relpath.replace('\\', '/')
    
    # Check extension first
    ext = Path(relpath).suffix.lower()
    
    # YML files in localization → LOC parser
    if ext == '.yml':
        if _matches_any(relpath, LOCALIZATION_PATTERNS):
            return FileRoute.LOCALIZATION, "localization file"
        return FileRoute.SKIP, "yml file outside localization folder"
    
    # Non-.txt files are skipped (we only parse .txt with script parser)
    if ext != '.txt':
        return FileRoute.SKIP, f"non-txt extension: {ext}"
    
    # Check skip patterns first (most specific)
    if _matches_any(relpath, SKIP_PATTERNS):
        return FileRoute.SKIP, "in skip list"
    
    # Check lookups patterns - these are ingested but not parsed further
    if _matches_any(relpath, LOOKUPS_PATTERNS):
        # Return LOOKUPS - currently treated same as SKIP for processing
        # but tagged differently in file_type for future extractors
        return FileRoute.LOOKUPS, "lookup data (ingest only, future: specialized extractors)"
    
    # Check if in a known script folder
    if _matches_any(relpath, SCRIPT_PARSER_FOLDERS):
        return FileRoute.SCRIPT, "script file in known folder"
    
    # Default: If it's a .txt in common/ or events/, parse it
    if relpath.startswith('common/') or relpath.startswith('events/'):
        return FileRoute.SCRIPT, "txt file in common/ or events/"
    
    # Unknown location - skip to be safe
    return FileRoute.SKIP, "unknown file location"


def should_process_with_script_parser(relpath: str) -> bool:
    """Quick check if file should go through script parser → AST → symbols."""
    route, _ = get_file_route(relpath)
    return route == FileRoute.SCRIPT


def should_process_with_loc_parser(relpath: str) -> bool:
    """Quick check if file should go through localization parser."""
    route, _ = get_file_route(relpath)
    return route == FileRoute.LOCALIZATION


def is_lookup_data(relpath: str) -> bool:
    """Quick check if file is lookup data (ingest only, no parsing)."""
    route, _ = get_file_route(relpath)
    return route == FileRoute.LOOKUPS


def should_skip(relpath: str) -> Tuple[bool, str]:
    """
    Check if file should be skipped entirely.
    
    For backward compatibility with existing code.
    """
    route, reason = get_file_route(relpath)
    if route == FileRoute.SKIP:
        return True, reason
    return False, ""


# =============================================================================
# SQL Helpers
# =============================================================================

def get_script_file_filter_sql() -> str:
    """
    SQL WHERE clause for files eligible for script parsing.
    
    Assumes table alias 'f' for files table.
    """
    # Build exclusion list from SKIP_PATTERNS
    exclusions = []
    for pattern in SKIP_PATTERNS + LOCALIZATION_PATTERNS + LOOKUPS_PATTERNS:
        # Convert pattern to SQL LIKE
        if pattern.endswith('/'):
            exclusions.append(f"f.relpath NOT LIKE '{pattern}%'")
        else:
            exclusions.append(f"f.relpath NOT LIKE '%{pattern}%'")
    
    return f"""
        f.deleted = 0
        AND f.relpath LIKE '%.txt'
        AND ({' AND '.join(exclusions)})
    """


def get_localization_file_filter_sql() -> str:
    """
    SQL WHERE clause for localization files.
    
    Assumes table alias 'f' for files table.
    """
    return """
        f.deleted = 0
        AND f.relpath LIKE 'localization/%.yml'
    """


# =============================================================================
# Statistics
# =============================================================================

def categorize_files(relpaths: List[str]) -> dict:
    """
    Categorize files by their processing route.
    
    Returns dict with counts per route and skip reasons.
    """
    result = {
        'script': 0,
        'localization': 0,
        'lookups': 0,
        'skip': 0,
        'skip_reasons': {},
    }
    
    for relpath in relpaths:
        route, reason = get_file_route(relpath)
        
        if route == FileRoute.SCRIPT:
            result['script'] += 1
        elif route == FileRoute.LOCALIZATION:
            result['localization'] += 1
        elif route == FileRoute.LOOKUPS:
            result['lookups'] += 1
        else:
            result['skip'] += 1
            result['skip_reasons'][reason] = result['skip_reasons'].get(reason, 0) + 1
    
    return result


# =============================================================================
# Compatibility Aliases (for migration from skip_rules.py)
# =============================================================================

def should_skip_for_ast(relpath: str) -> Tuple[bool, str]:
    """
    Legacy API: Check if file should be skipped for AST generation.
    
    Deprecated: Use should_process_with_script_parser() instead.
    """
    route, reason = get_file_route(relpath)
    if route == FileRoute.SCRIPT:
        return False, ""
    return True, reason


def should_skip_for_symbols(relpath: str) -> Tuple[bool, str]:
    """
    Legacy API: Check if file should be skipped for symbol extraction.
    
    Deprecated: Use should_process_with_script_parser() instead.
    Symbol extraction follows from AST generation - if it has an AST, it has symbols.
    """
    return should_skip_for_ast(relpath)


def get_symbol_file_filter_sql() -> str:
    """
    Legacy API: SQL WHERE clause for symbol-eligible files.
    
    Deprecated: Use get_script_file_filter_sql() instead.
    """
    return get_script_file_filter_sql()
