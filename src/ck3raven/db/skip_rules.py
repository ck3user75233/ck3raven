"""
Centralized Skip Rules for CK3 Database Builder

This module defines which files should be skipped for various processing phases.
Having centralized rules ensures consistency across all builder functions.

DESIGN PHILOSOPHY:
- Skip rules are defined ONCE here
- All builder functions import and use these rules
- Changes to skip rules apply everywhere automatically
- Rules are documented with rationale

Usage:
    from ck3raven.db.skip_rules import (
        should_skip_for_ast,
        should_skip_for_symbols,
        should_skip_for_localization,
        get_ast_file_filter_sql,
        get_symbol_file_filter_sql,
    )
"""

import re
from typing import Set, List, Tuple
from pathlib import Path


# =============================================================================
# Skip Patterns by Category
# =============================================================================

# Files that should NEVER be parsed with the script parser
# These are not CK3 script files at all
BINARY_AND_NON_SCRIPT_PATTERNS: List[str] = [
    # Graphics and assets
    'gfx/',
    '/fonts/',
    '/sounds/',
    '/music/',
    '/licenses/',
    
    # Generated/backup content
    '#backup/',
    '/generated/',
    
    # Non-script data files  
    'checksum_manifest.txt',
    '.mod',  # Mod descriptor files
]

# Folders that contain localization (use localization parser, not script parser)
LOCALIZATION_PATTERNS: List[str] = [
    'localization/',
]

# Files that CAN be parsed but produce no meaningful symbols
# These are data files, not definition files
NO_SYMBOL_PATTERNS: List[str] = [
    # Name databases - just string lists, no definitions
    '/names/',
    'accolade_names/',
    'coat_of_arms/',
    'cultural_names',
    'moreculturalnames',
    '_names_l_',
    
    # Map and terrain data - coordinate data, not definitions
    'map_data/',
    'terrain/',
    'adjacencies',
    'default.map',
    'positions.txt',
    'definition.csv',
    
    # History files - instance data, not type definitions
    'history/characters/',
    'history/provinces/',
    'history/titles/',
    
    # GUI definitions - different structure
    'gui/',
    'interface/',
    
    # Test and config files
    'tests/',
    'test_',
    '_test.txt',
    'readme',
    'credits',
    'notes',
]

# Files that might parse but shouldn't have refs extracted
# (they reference things but aren't primary definition sources)
NO_REF_PATTERNS: List[str] = [
    # History files reference symbols but don't define relationships we track
    'history/',
]


# =============================================================================
# Skip Rule Functions
# =============================================================================

def _matches_any_pattern(relpath: str, patterns: List[str]) -> bool:
    """Check if relpath matches any of the patterns (case-insensitive)."""
    relpath_lower = relpath.lower()
    for pattern in patterns:
        if pattern.lower() in relpath_lower:
            return True
    return False


def should_skip_for_ast(relpath: str) -> Tuple[bool, str]:
    """
    Check if a file should be skipped for AST generation.
    
    Args:
        relpath: Relative path within mod/vanilla
        
    Returns:
        (should_skip, reason) - reason is empty string if not skipped
    """
    # Must be a .txt file for script parsing
    if not relpath.endswith('.txt'):
        return True, "not a .txt file"
    
    # Skip binary/non-script
    if _matches_any_pattern(relpath, BINARY_AND_NON_SCRIPT_PATTERNS):
        return True, "binary or non-script file"
    
    # Skip localization folder (uses different parser)
    if _matches_any_pattern(relpath, LOCALIZATION_PATTERNS):
        return True, "localization file (uses localization parser)"
    
    return False, ""


def should_skip_for_symbols(relpath: str) -> Tuple[bool, str]:
    """
    Check if a file should be skipped for symbol extraction.
    
    Some files can be parsed (have valid AST) but don't contain
    meaningful symbol definitions.
    
    Args:
        relpath: Relative path within mod/vanilla
        
    Returns:
        (should_skip, reason)
    """
    # First check AST skip rules
    skip, reason = should_skip_for_ast(relpath)
    if skip:
        return skip, reason
    
    # Then check symbol-specific skip patterns
    if _matches_any_pattern(relpath, NO_SYMBOL_PATTERNS):
        return True, "data file with no symbol definitions"
    
    return False, ""


def should_skip_for_refs(relpath: str) -> Tuple[bool, str]:
    """
    Check if a file should be skipped for reference extraction.
    
    Args:
        relpath: Relative path within mod/vanilla
        
    Returns:
        (should_skip, reason)
    """
    # First check symbol skip rules (refs need symbols)
    skip, reason = should_skip_for_symbols(relpath)
    if skip:
        return skip, reason
    
    # Then check ref-specific patterns
    if _matches_any_pattern(relpath, NO_REF_PATTERNS):
        return True, "history/data file"
    
    return False, ""


def should_skip_for_localization(relpath: str) -> Tuple[bool, str]:
    """
    Check if a file should be processed by the localization parser.
    
    Returns True if it SHOULD be skipped (not a localization file).
    
    Args:
        relpath: Relative path within mod/vanilla
        
    Returns:
        (should_skip, reason)
    """
    # Must be a .yml file
    if not relpath.endswith('.yml'):
        return True, "not a .yml file"
    
    # Must be in localization folder
    if not _matches_any_pattern(relpath, LOCALIZATION_PATTERNS):
        return True, "not in localization folder"
    
    return False, ""


# =============================================================================
# SQL Filter Fragments
# =============================================================================

def get_ast_file_filter_sql() -> str:
    """
    Get SQL WHERE clause fragment for filtering files eligible for AST generation.
    
    Use like: SELECT ... FROM files f WHERE {get_ast_file_filter_sql()}
    
    Assumes table alias 'f' for files table.
    """
    return """
        f.deleted = 0
        AND f.relpath LIKE '%.txt'
        AND f.relpath NOT LIKE 'localization/%'
        AND f.relpath NOT LIKE 'gfx/%'
        AND f.relpath NOT LIKE '%/fonts/%'
        AND f.relpath NOT LIKE '%/sounds/%'
        AND f.relpath NOT LIKE '%/music/%'
        AND f.relpath NOT LIKE '%#backup/%'
        AND f.relpath NOT LIKE '%/generated/%'
    """


def get_symbol_file_filter_sql() -> str:
    """
    Get SQL WHERE clause fragment for filtering files eligible for symbol extraction.
    
    This is more restrictive than AST filter - excludes data files.
    
    Assumes table alias 'f' for files table.
    """
    base = get_ast_file_filter_sql()
    additional = """
        AND f.relpath NOT LIKE '%/names/%'
        AND f.relpath NOT LIKE '%accolade_names/%'
        AND f.relpath NOT LIKE '%coat_of_arms/%'
        AND f.relpath NOT LIKE '%map_data/%'
        AND f.relpath NOT LIKE 'history/characters/%'
        AND f.relpath NOT LIKE 'history/provinces/%'
        AND f.relpath NOT LIKE 'history/titles/%'
        AND f.relpath NOT LIKE '%/tests/%'
        AND f.relpath NOT LIKE '%gui/%'
        AND f.relpath NOT LIKE '%interface/%'
    """
    return base + additional


def get_localization_file_filter_sql() -> str:
    """
    Get SQL WHERE clause fragment for localization files.
    
    Assumes table alias 'f' for files table.
    """
    return """
        f.deleted = 0
        AND f.relpath LIKE 'localization/%.yml'
    """


# =============================================================================
# Statistics and Debugging
# =============================================================================

def categorize_files(relpaths: List[str]) -> dict:
    """
    Categorize a list of files by what processing they're eligible for.
    
    Useful for debugging and understanding file distribution.
    
    Returns dict with counts:
        - eligible_ast: Can have AST generated
        - eligible_symbols: Can have symbols extracted
        - eligible_refs: Can have refs extracted
        - eligible_localization: Is a localization file
        - skipped: Skipped for all processing
    """
    result = {
        'eligible_ast': 0,
        'eligible_symbols': 0,
        'eligible_refs': 0,
        'eligible_localization': 0,
        'skipped': 0,
        'skip_reasons': {},
    }
    
    for relpath in relpaths:
        # Check each category
        skip_ast, reason_ast = should_skip_for_ast(relpath)
        skip_sym, reason_sym = should_skip_for_symbols(relpath)
        skip_ref, reason_ref = should_skip_for_refs(relpath)
        skip_loc, reason_loc = should_skip_for_localization(relpath)
        
        if not skip_ast:
            result['eligible_ast'] += 1
        if not skip_sym:
            result['eligible_symbols'] += 1
        if not skip_ref:
            result['eligible_refs'] += 1
        if not skip_loc:
            result['eligible_localization'] += 1
        
        # If skipped for everything
        if skip_ast and skip_loc:
            result['skipped'] += 1
            reason = reason_ast or reason_loc
            result['skip_reasons'][reason] = result['skip_reasons'].get(reason, 0) + 1
    
    return result


def get_symbol_eligible_folders() -> List[str]:
    """
    Get list of folder prefixes that typically contain symbol definitions.
    
    Useful for documentation and quick filtering.
    """
    return [
        'common/traits',
        'common/decisions',
        'common/scripted_effects',
        'common/scripted_triggers',
        'common/on_action',
        'common/script_values',
        'common/character_interactions',
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
        'events/',
    ]
