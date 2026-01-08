"""
Symbol and Reference Extraction

Extracts definitions (symbols) and uses (references) from parsed AST.
Populates the symbols and refs tables for cross-reference analysis.

DESIGN PHILOSOPHY:
- Extract EVERY top-level block as a symbol (exhaustive, not whitelisted)
- Infer symbol type from file path when possible
- Use 'definition' as fallback for unknown paths
- Extract scripted values (@name = value) everywhere
- Better to have "too many" symbols than miss definitions
"""

import sqlite3
import json
import logging
import re
from typing import Optional, List, Dict, Any, Tuple, Set, Iterator
from dataclasses import dataclass
from pathlib import Path

from ck3raven.db.models import Symbol, Reference

logger = logging.getLogger(__name__)


# Path patterns for type inference (used for hints, NOT for filtering)
# Maps path fragments to symbol types
PATH_TYPE_HINTS = {
    # Scripted code
    'common/scripted_effects': 'scripted_effect',
    'common/scripted_triggers': 'scripted_trigger',
    'common/scripted_modifiers': 'scripted_modifier',
    'common/script_values': 'script_value',
    'common/on_action': 'on_action',
    
    # Character-related
    'common/traits': 'trait',
    'common/character_interactions': 'interaction',
    'common/schemes': 'scheme',
    'common/lifestyle': 'lifestyle',
    'common/focuses': 'focus',
    'common/perks': 'perk',
    'common/nicknames': 'nickname',
    'common/relations': 'relation',
    
    # Culture & Religion
    'common/culture/traditions': 'tradition',
    'common/culture/pillars': 'cultural_pillar',
    'common/culture/eras': 'cultural_era',
    'common/culture/innovations': 'innovation',
    'common/religion/religions': 'religion',
    'common/religion/holy_sites': 'holy_site',
    'common/religion/doctrines': 'doctrine',
    'common/religion/fervor_modifiers': 'fervor_modifier',
    
    # Realm & Titles
    'common/landed_titles': 'title',
    'common/governments': 'government',
    'common/laws': 'law',
    'common/succession_election': 'election',
    'common/vassal_contracts': 'vassal_contract',
    'common/holdings': 'holding',
    
    # Buildings & Economy
    'common/buildings': 'building',
    'common/terrain_types': 'terrain',
    'common/province_terrain': 'province_terrain',
    'common/economic_values': 'economic_value',
    
    # Military
    'common/men_at_arms_types': 'maa_type',
    'common/combat_phase_events': 'combat_event',
    'common/casus_belli_types': 'cb_type',
    'common/war_goals': 'war_goal',
    
    # Court & Activities
    'common/activities': 'activity',
    'common/council_positions': 'council_position',
    'common/court_positions': 'court_position',
    'common/court_types': 'court_type',
    'common/diarchies': 'diarchy',
    'common/domiciles': 'domicile',
    
    # Artifacts & Items
    'common/artifacts': 'artifact',
    'common/inspiration_types': 'inspiration',
    
    # Dynasties & Legacies
    'common/dynasties': 'dynasty',
    'common/dynasty_perks': 'dynasty_perk',
    'common/dynasty_legacies': 'dynasty_legacy',
    'common/dynasty_houses': 'dynasty_house',
    
    # Decisions & Events
    'common/decisions': 'decision',
    'common/important_actions': 'important_action',
    'events': 'event',
    
    # UI & Graphics (still useful to track)
    'common/event_backgrounds': 'event_background',
    'common/event_themes': 'event_theme',
    'common/customizable_localization': 'custom_loc',
    'common/flavorization': 'flavorization',
    'common/named_colors': 'named_color',
    'gfx/portraits/portrait_modifiers': 'portrait_modifier',
    'gfx/coat_of_arms': 'coa',
    
    # Modifiers
    'common/modifiers': 'modifier',
    'common/static_modifiers': 'static_modifier',
    'common/triggered_modifiers': 'triggered_modifier',
    'common/opinion_modifiers': 'opinion_modifier',
    'common/event_modifiers': 'event_modifier',
    
    # Defines
    'common/defines': 'define',
    
    # Misc
    'common/bookmark_portraits': 'bookmark_portrait',
    'common/bookmarks': 'bookmark',
    'common/game_rules': 'game_rule',
    'common/achievements': 'achievement',
    'common/story_cycles': 'story_cycle',
    'common/secret_types': 'secret_type',
    'common/hooks': 'hook',
    'common/travel': 'travel',
    'common/struggle': 'struggle',
    
    # History (useful for reference)
    'history/characters': 'historical_character',
    'history/provinces': 'province_history',
    'history/titles': 'title_history',
    
    # Localization
    'localization': 'localization_key',
    
    # GUI (for completeness)
    'gui': 'gui_element',
}

# Keys that trigger effects/triggers
EFFECT_TRIGGER_KEYS = {
    'effect', 'limit', 'trigger', 'modifier', 'show_as_tooltip',
    'on_action', 'on_activate', 'on_complete', 'on_start', 'on_death',
    'ai_will_do', 'is_shown', 'is_valid', 'cost', 'potential',
    'success', 'failure', 'effect_on_target', 'effect_on_actor',
    'on_accept', 'on_decline', 'can_send', 'can_be_picked',
}

# Keys that reference other definitions
REFERENCE_KEYS = {
    'has_trait': 'trait',
    'add_trait': 'trait',
    'remove_trait': 'trait',
    'trait': 'trait',
    'has_perk': 'perk',
    'add_perk': 'perk',
    'perk': 'perk',
    'has_focus': 'focus',
    'set_focus': 'focus',
    'focus': 'focus',
    'has_culture': 'culture',
    'culture': 'culture',
    'has_religion': 'religion',
    'religion': 'religion',
    'faith': 'faith',
    'government_type': 'government',
    'has_government': 'government',
    'add_artifact': 'artifact',
    'has_artifact': 'artifact',
    'create_artifact': 'artifact',
    'trigger_event': 'event',
    'random_events_list': 'event',
    'add_building': 'building',
    'has_building': 'building',
    'building': 'building',
    'has_building_or_higher': 'building',
    'create_title_and_vassal_change': 'title',
    'title': 'title',
    'has_title': 'title',
    'has_cb': 'cb_type',
    'casus_belli': 'cb_type',
    'cb_type': 'cb_type',
    'has_law': 'law',
    'add_law': 'law',
    'run_interaction': 'interaction',
    'has_tradition': 'tradition',
    'can_have_tradition': 'tradition',
    'start_scheme': 'scheme',
    'scheme_type': 'scheme',
    'has_activity_type': 'activity',
    'activity_type': 'activity',
    'has_lifestyle': 'lifestyle',
    'lifestyle': 'lifestyle',
}

# Keys whose values are scripted effects/triggers
SCRIPT_REFERENCE_KEYS = {
    'run_scripted_effect': 'scripted_effect',
    'scripted_effect': 'scripted_effect',
    'run_scripted_trigger': 'scripted_trigger',
    'scripted_trigger': 'scripted_trigger',
}


@dataclass
class ExtractedSymbol:
    """Temporary holder for extracted symbol data."""
    name: str
    kind: str
    line: int
    column: int
    scope: Optional[str] = None
    signature: Optional[str] = None
    doc: Optional[str] = None


@dataclass
class ExtractedRef:
    """Temporary holder for extracted reference data."""
    name: str
    kind: str
    line: int
    column: int
    context: str


# Regex patterns for invalid symbol names
_DATE_PATTERN = re.compile(r'^\d+\.\d+(\.\d+)?$')  # e.g., 867.1.1, 1066.9.15
_NUMERIC_PATTERN = re.compile(r'^\.?\d+\.?\d*$')  # Pure numbers/decimals including .1, 1., 1.5

# CK3 keywords that shouldn't be extracted as symbols
_RESERVED_KEYWORDS = {
    'namespace', 'yes', 'no', 'true', 'false', 'null', 'none',
    'if', 'else', 'limit', 'trigger', 'effect', 'modifier',
    'AND', 'OR', 'NOT', 'NOR', 'NAND',
    'macro', 'scripted_trigger', 'scripted_effect',  # These are wrapper keywords, not symbols
    'first_valid', 'random_valid', 'fallback',  # Localization wrappers
    # GFX/portrait structural blocks (anonymous containers, not definitions)
    'pattern_textures', 'pattern_layout', 'variation', 'object', 'cubemap',
    'environment', 'lights', 'camera', 'assets', 'characters', 'artifacts',
    'shadows_fade', 'shadows_strength', 'default_camera', 'visual_culture_level',
    'support_type', 'audio_culture',
    # GFX lighting/shader settings
    'tonemap_function', 'layer', 'exposure_function', 'bright_threshold',
    'bloom_width', 'bloom_scale', 'exposure', 'cubemap_intensity',
    # History wrappers (actual ID is inside as name = "...")
    'war', 'character',
    # Common structural keys that appear in multiple contexts
    'category',
    # COA atlas configuration (anonymous repeated blocks)
    'atlas',
    # GFX post-effect and map object structural blocks
    'posteffect_values', 'game_object_locator',
}


def _is_valid_symbol_name(name) -> bool:
    """
    Check if a name is a valid symbol (not garbage like dates or numeric fragments).
    
    Filters out:
    - Non-string values (lists, dicts, etc.)
    - Pure numbers: 123, 45.67
    - Date patterns: 867.1.1, 1066.9.15
    - Empty or very short names: "", "a"
    - Reserved CK3 keywords: namespace, yes, no, etc.
    """
    # Must be a string
    if not isinstance(name, str):
        return False
    
    if not name or len(name) < 2:
        return False
    
    # Skip reserved keywords
    if name in _RESERVED_KEYWORDS:
        return False
    
    # Skip date patterns (common in history files)
    if _DATE_PATTERN.match(name):
        return False
    
    # Skip pure numeric values
    if _NUMERIC_PATTERN.match(name):
        return False
    
    return True


def get_symbol_kind_from_path(relpath: str) -> str:
    """
    Determine symbol kind based on file path.
    
    Returns the most specific type hint found, or 'definition' as fallback.
    NEVER returns None - we always extract symbols.
    """
    relpath_normalized = relpath.replace('\\', '/').lower()
    
    # Find the most specific (longest) matching pattern
    best_match = None
    best_length = 0
    
    for pattern, kind in PATH_TYPE_HINTS.items():
        if pattern in relpath_normalized:
            if len(pattern) > best_length:
                best_match = kind
                best_length = len(pattern)
    
    if best_match:
        return best_match
    
    # Fallback: try to infer from path structure
    if '/common/' in relpath_normalized:
        # Extract the subfolder under common/
        parts = relpath_normalized.split('/common/')
        if len(parts) > 1:
            subfolder = parts[1].split('/')[0]
            return subfolder.rstrip('s')  # e.g., 'traits' -> 'trait'
    
    # Generic fallback
    return 'definition'


def extract_symbols_from_ast(
    ast_dict: Dict[str, Any],
    relpath: str,
    content_hash: str
) -> Iterator[ExtractedSymbol]:
    """
    Extract symbol definitions from serialized AST.
    
    EXHAUSTIVE EXTRACTION:
    - Every top-level block is a symbol
    - Scripted values (@name = value) are symbols
    - Type is inferred from path, never filtered
    """
    # Skip non-game-content files
    relpath_lower = relpath.replace('\\', '/').lower()
    skip_patterns = [
        'checksum_manifest.txt',
        'credit_portraits.txt',  # Credits metadata
        'gfx/court_scene/',  # All court scene files (settings, environment, etc.)
        'gfx/portraits/accessory_variations/',  # Anonymous texture blocks
        'gfx/map/environment/',  # Map lighting/shader settings
        'gfx/map/map_object_data/',  # Map object locators (anonymous repeated blocks)
        'gfx/map/post_effects/',  # Post-effect settings (anonymous configuration)
    ]
    for pattern in skip_patterns:
        if pattern in relpath_lower:
            return  # Skip this file entirely
    
    # Get type hint from path (never None)
    kind = get_symbol_kind_from_path(relpath)
    
    # Process children of root
    children = ast_dict.get('children', [])
    
    for child in children:
        child_type = child.get('_type')
        
        if child_type == 'block':
            # Use _name (the block's identifier) not 'name' (which can be overwritten
            # by nested name = {...} assignments creating a list collision)
            name = child.get('_name') or child.get('name')
            line = child.get('line', 0)
            column = child.get('column', 0)
            
            if name and _is_valid_symbol_name(name):
                # Skip internal/namespace blocks that aren't real definitions
                # (blocks inside other blocks are handled by reference extraction)
                
                # Try to extract signature/doc from children
                signature = None
                doc = None
                
                block_children = child.get('children', [])
                for bc in block_children:
                    if bc.get('_type') == 'assignment':
                        key = bc.get('key')
                        if key in ('desc', 'description', 'title'):
                            val = bc.get('value', {})
                            if val.get('_type') == 'value':
                                doc = str(val.get('value', ''))
                                break
                
                yield ExtractedSymbol(
                    name=name,
                    kind=kind,
                    line=line,
                    column=column,
                    signature=signature,
                    doc=doc
                )
        
        elif child_type == 'assignment':
            # Top-level assignments are symbols too
            key = child.get('key')
            line = child.get('line', 0)
            column = child.get('column', 0)
            
            if key and _is_valid_symbol_name(key):
                value = child.get('value', {})
                
                # Skip @scripted_values - these are FILE-LOCAL constants, not global symbols
                # Each file can define @my_var = 5 without conflicting with other files
                if key.startswith('@'):
                    continue
                
                # Determine specific type
                if kind == 'define':
                    sym_kind = 'define'
                    sym_name = key
                else:
                    # Could be namespace assignment, variable, etc.
                    sym_kind = kind
                    sym_name = key
                
                # Get value as signature if it's simple
                val_str = None
                if value.get('_type') == 'value':
                    val_str = str(value.get('value', ''))
                
                yield ExtractedSymbol(
                    name=sym_name,
                    kind=sym_kind,
                    line=line,
                    column=column,
                    signature=val_str
                )


def extract_refs_from_ast(
    ast_dict: Dict[str, Any],
    relpath: str,
    content_hash: str
) -> Iterator[ExtractedRef]:
    """
    Extract references from serialized AST.
    
    References are uses of symbols defined elsewhere.
    """
    
    def walk_node(node: Dict[str, Any], context: str = '') -> Iterator[ExtractedRef]:
        node_type = node.get('_type')
        
        if node_type == 'assignment':
            key = node.get('key', '')
            line = node.get('line', 0)
            column = node.get('column', 0)
            value = node.get('value', {})
            
            # Check if this key references another symbol
            if key in REFERENCE_KEYS:
                ref_kind = REFERENCE_KEYS[key]
                if value.get('_type') == 'value':
                    ref_name = str(value.get('value', ''))
                    if ref_name and not ref_name.startswith('$'):  # Skip variables
                        yield ExtractedRef(
                            name=ref_name,
                            kind=ref_kind,
                            line=value.get('line', line),
                            column=value.get('column', column),
                            context=context or key
                        )
            
            elif key in SCRIPT_REFERENCE_KEYS:
                ref_kind = SCRIPT_REFERENCE_KEYS[key]
                if value.get('_type') == 'value':
                    ref_name = str(value.get('value', ''))
                    if ref_name:
                        yield ExtractedRef(
                            name=ref_name,
                            kind=ref_kind,
                            line=value.get('line', line),
                            column=value.get('column', column),
                            context=context or key
                        )
            
            # Update context for nested structures
            new_context = key if key in EFFECT_TRIGGER_KEYS else context
            
            # Recurse into value
            yield from walk_node(value, new_context)
        
        elif node_type == 'block':
            name = node.get('name', '')
            new_context = name if name in EFFECT_TRIGGER_KEYS else context
            
            for child in node.get('children', []):
                yield from walk_node(child, new_context)
        
        elif node_type == 'list':
            for item in node.get('items', []):
                yield from walk_node(item, context)
        
        elif node_type == 'root':
            for child in node.get('children', []):
                yield from walk_node(child, context)
    
    yield from walk_node(ast_dict)


def store_symbols_batch(
    conn: sqlite3.Connection,
    file_id: int,
    content_hash: str,
    ast_id: int,
    symbols: List[ExtractedSymbol]
) -> int:
    """
    Store multiple symbols in batch.
    
    Returns:
        Number of symbols stored
    """
    if not symbols:
        return 0
    
    # Delete existing symbols for this file
    conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
    
    # Insert new symbols
    rows = [
        (file_id, content_hash, ast_id, s.name, s.kind, s.line, s.column, 
         s.scope, s.signature, s.doc)
        for s in symbols
    ]
    
    conn.executemany("""
        INSERT INTO symbols 
        (file_id, content_hash, ast_id, name, kind, line, column, scope, signature, doc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    
    conn.commit()
    return len(rows)


def store_refs_batch(
    conn: sqlite3.Connection,
    file_id: int,
    content_hash: str,
    ast_id: int,
    refs: List[ExtractedRef]
) -> int:
    """
    Store multiple references in batch.
    
    Returns:
        Number of refs stored
    """
    if not refs:
        return 0
    
    # Delete existing refs for this file
    conn.execute("DELETE FROM refs WHERE file_id = ?", (file_id,))
    
    # Insert new refs
    rows = [
        (file_id, content_hash, ast_id, r.name, r.kind, r.line, r.column, r.context)
        for r in refs
    ]
    
    conn.executemany("""
        INSERT INTO refs 
        (file_id, content_hash, ast_id, name, kind, line, column, context)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    
    conn.commit()
    return len(rows)


def extract_and_store(
    conn: sqlite3.Connection,
    file_id: int,
    content_hash: str,
    ast_id: int,
    ast_dict: Dict[str, Any],
    relpath: str
) -> Tuple[int, int]:
    """
    Extract and store both symbols and references for a file.
    
    Returns:
        (symbol_count, ref_count)
    """
    symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
    refs = list(extract_refs_from_ast(ast_dict, relpath, content_hash))
    
    sym_count = store_symbols_batch(conn, file_id, content_hash, ast_id, symbols)
    ref_count = store_refs_batch(conn, file_id, content_hash, ast_id, refs)
    
    return sym_count, ref_count


def find_symbol_by_name(
    conn: sqlite3.Connection,
    name: str,
    kind: Optional[str] = None
) -> List[Symbol]:
    """Find symbols by exact name match."""
    if kind:
        rows = conn.execute("""
            SELECT * FROM symbols WHERE name = ? AND kind = ?
        """, (name, kind)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM symbols WHERE name = ?
        """, (name,)).fetchall()
    
    return [Symbol.from_row(r) for r in rows]


def find_symbols_fts(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 50
) -> List[Symbol]:
    """Full-text search for symbols."""
    rows = conn.execute("""
        SELECT s.* FROM symbols s
        JOIN symbols_fts fts ON s.symbol_id = fts.rowid
        WHERE symbols_fts MATCH ?
        LIMIT ?
    """, (query, limit)).fetchall()
    
    return [Symbol.from_row(r) for r in rows]


def find_refs_to_symbol(
    conn: sqlite3.Connection,
    name: str,
    kind: Optional[str] = None
) -> List[Reference]:
    """Find all references to a symbol."""
    if kind:
        rows = conn.execute("""
            SELECT * FROM refs WHERE name = ? AND kind = ?
        """, (name, kind)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM refs WHERE name = ?
        """, (name,)).fetchall()
    
    return [Reference.from_row(r) for r in rows]


def find_refs_fts(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 50
) -> List[Reference]:
    """Full-text search for references."""
    rows = conn.execute("""
        SELECT r.* FROM refs r
        JOIN refs_fts fts ON r.ref_id = fts.rowid
        WHERE refs_fts MATCH ?
        LIMIT ?
    """, (query, limit)).fetchall()
    
    return [Reference.from_row(r) for r in rows]


def get_symbol_stats(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Get statistics about symbols and references."""
    stats = {}
    
    # Total counts
    row = conn.execute("SELECT COUNT(*) as cnt FROM symbols").fetchone()
    stats['total_symbols'] = row['cnt']
    
    row = conn.execute("SELECT COUNT(*) as cnt FROM refs").fetchone()
    stats['total_refs'] = row['cnt']
    
    # By kind
    rows = conn.execute("""
        SELECT kind, COUNT(*) as cnt FROM symbols GROUP BY kind ORDER BY cnt DESC
    """).fetchall()
    stats['symbols_by_kind'] = {r['kind']: r['cnt'] for r in rows}
    
    rows = conn.execute("""
        SELECT kind, COUNT(*) as cnt FROM refs GROUP BY kind ORDER BY cnt DESC
    """).fetchall()
    stats['refs_by_kind'] = {r['kind']: r['cnt'] for r in rows}
    
    return stats


def find_unused_symbols(
    conn: sqlite3.Connection,
    kind: Optional[str] = None
) -> List[Symbol]:
    """
    Find symbols that are never referenced.
    
    Useful for finding dead code.
    """
    if kind:
        rows = conn.execute("""
            SELECT s.* FROM symbols s
            LEFT JOIN refs r ON s.name = r.name AND s.kind = r.kind
            WHERE r.ref_id IS NULL AND s.kind = ?
        """, (kind,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT s.* FROM symbols s
            LEFT JOIN refs r ON s.name = r.name AND s.kind = r.kind
            WHERE r.ref_id IS NULL
        """).fetchall()
    
    return [Symbol.from_row(r) for r in rows]


def find_undefined_refs(
    conn: sqlite3.Connection,
    kind: Optional[str] = None
) -> List[Reference]:
    """
    Find references that don't have a matching symbol.
    
    Useful for finding broken references.
    """
    if kind:
        rows = conn.execute("""
            SELECT r.* FROM refs r
            LEFT JOIN symbols s ON r.name = s.name AND r.kind = s.kind
            WHERE s.symbol_id IS NULL AND r.kind = ?
        """, (kind,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT r.* FROM refs r
            LEFT JOIN symbols s ON r.name = s.name AND r.kind = s.kind
            WHERE s.symbol_id IS NULL
        """).fetchall()
    
    return [Reference.from_row(r) for r in rows]

# =============================================================================
# Incremental Extraction Functions
# =============================================================================

def extract_symbols_incremental(
    conn: sqlite3.Connection,
    batch_size: int = 500,
    progress_callback: Optional[callable] = None,
    force_rebuild: bool = False
) -> Dict[str, int]:
    """
    Incrementally extract symbols from ASTs that don't have symbols yet.

    This is the PREFERRED method for symbol extraction as it:
    1. Only processes ASTs without existing symbols (unless force_rebuild=True)
    2. Doesn't delete existing valid symbols (unless force_rebuild=True)
    3. Uses centralized skip rules to filter non-definition files
    4. Supports progress callbacks for long-running operations
    5. Maintains full source traceability (file_id, line_number, ast_id)

    Args:
        conn: Database connection
        batch_size: Number of ASTs to process per batch
        progress_callback: Optional callback(processed, total, symbols_extracted)
        force_rebuild: If True, delete all existing symbols first and rebuild

    Returns:
        Dict with 'processed', 'symbols', 'errors', 'skipped' counts
    """
    import json
    from ck3raven.db.file_routes import should_skip_for_symbols, get_symbol_file_filter_sql

    # Handle force rebuild
    if force_rebuild:
        logger.info("Force rebuild: clearing all existing symbols...")
        conn.execute("DELETE FROM symbols")
        conn.commit()
        logger.info("Symbols cleared")

    # Get SQL filter for symbol-eligible files
    file_filter = get_symbol_file_filter_sql()

    # Count ASTs needing symbols (only from symbol-eligible files)
    # Uses symbols_processed_at IS NULL instead of NOT EXISTS to correctly handle
    # ASTs that yield 0 symbols (e.g., empty/comment-only files)
    count_sql = f"""
        SELECT COUNT(DISTINCT a.ast_id)
        FROM asts a
        JOIN files f ON a.content_hash = f.content_hash
        WHERE a.parse_ok = 1
        AND a.symbols_processed_at IS NULL
        AND {file_filter}
    """
    total_row = conn.execute(count_sql).fetchone()
    total_pending = total_row[0]

    if total_pending == 0:
        logger.info("No ASTs need symbol extraction")
        return {'processed': 0, 'symbols_extracted': 0, 'symbols_inserted': 0, 'duplicates': 0, 'errors': 0, 'files_skipped': 0}

    logger.info(f"Extracting symbols from {total_pending} symbol-eligible ASTs...")

    processed = 0
    symbols_extracted = 0
    symbols_inserted = 0  
    errors = 0
    files_skipped = 0

    while processed < total_pending:
        # Get batch of ASTs needing symbols (filtered by skip rules)
        batch_sql = f"""
            SELECT
                a.ast_id,
                a.content_hash,
                a.ast_blob,
                f.file_id,
                f.relpath
            FROM asts a
            JOIN files f ON a.content_hash = f.content_hash
            WHERE a.parse_ok = 1
            AND a.symbols_processed_at IS NULL
            AND {file_filter}
            GROUP BY a.ast_id
            LIMIT ?
        """
        rows = conn.execute(batch_sql, (batch_size,)).fetchall()

        if not rows:
            break

        batch_extracted = 0
        batch_inserted = 0

        for ast_id, content_hash, ast_blob, file_id, relpath in rows:
            # Double-check with Python skip rules (SQL filter is approximate)
            skip, reason = should_skip_for_symbols(relpath)
            if skip:
                files_skipped += 1
                processed += 1
                continue

            try:
                # Decode AST
                ast_dict = json.loads(ast_blob.decode('utf-8'))

                # Extract symbols
                symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))

                # Store symbols with full source traceability
                for sym in symbols:
                    cursor = conn.execute("""
                        INSERT OR IGNORE INTO symbols
                        (symbol_type, name, scope, defining_ast_id, defining_file_id,
                         content_version_id, line_number, metadata_json)
                        VALUES (?, ?, ?, ?, ?,
                                (SELECT content_version_id FROM files WHERE file_id = ?),
                                ?, ?)
                    """, (
                        sym.kind, sym.name, sym.scope, ast_id, file_id,
                        file_id, sym.line, None
                    ))
                    if cursor.rowcount > 0:
                        batch_inserted += 1
                        symbols_inserted += 1

                symbols_extracted += len(symbols)
                
            except Exception as e:
                errors += 1
                if errors <= 10:
                    logger.warning(f"Error extracting symbols from {relpath}: {e}")
            
            # Mark AST as processed ALWAYS (even if 0 symbols or error)
            # This prevents infinite re-processing of empty/comment-only files
            conn.execute(
                "UPDATE asts SET symbols_processed_at = datetime('now') WHERE ast_id = ?",
                (ast_id,)
            )
            processed += 1
        
        conn.commit()
        
        if progress_callback:
            progress_callback(processed, total_pending, symbols_inserted)
        
        logger.debug(f"Batch complete: {processed}/{total_pending}, +{batch_inserted} new symbols")
    
    duplicates = symbols_extracted - symbols_inserted
    logger.info(f"Symbol extraction complete: {processed} ASTs, {symbols_extracted} extracted, {symbols_inserted} new, {duplicates} duplicates, {errors} errors")

    return {
        'processed': processed,
        'symbols_extracted': symbols_extracted,
        'symbols_inserted': symbols_inserted,
        'duplicates': duplicates,
        'errors': errors,
        'files_skipped': files_skipped
    }


def extract_refs_incremental(
    conn: sqlite3.Connection,
    batch_size: int = 500,
    progress_callback: Optional[callable] = None
) -> Dict[str, int]:
    """
    Incrementally extract references from ASTs that do not have refs yet.

    Similar to extract_symbols_incremental but for references.

    Args:
        conn: Database connection
        batch_size: Number of ASTs to process per batch
        progress_callback: Optional callback(processed, total, refs_extracted)

    Returns:
        Dict with 'processed', 'refs', 'errors' counts
    """
    import json
    
    # Count ASTs needing refs
    total_row = conn.execute("""
        SELECT COUNT(*)
        FROM asts a
        WHERE a.parse_ok = 1
        AND NOT EXISTS (
            SELECT 1 FROM refs r
            WHERE r.defining_ast_id = a.ast_id
        )
    """).fetchone()
    total_pending = total_row[0]
    
    if total_pending == 0:
        logger.info("No ASTs need reference extraction")
        return {'processed': 0, 'refs': 0, 'errors': 0}
    
    logger.info(f"Extracting references from {total_pending} ASTs...")
    
    processed = 0
    total_refs = 0
    errors = 0
    
    while processed < total_pending:
        rows = conn.execute("""
            SELECT 
                a.ast_id,
                a.content_hash,
                a.ast_blob,
                f.file_id,
                f.relpath
            FROM asts a
            JOIN files f ON a.content_hash = f.content_hash
            WHERE a.parse_ok = 1
            AND f.deleted = 0
            AND NOT EXISTS (
                SELECT 1 FROM refs r
                WHERE r.defining_ast_id = a.ast_id
            )
            GROUP BY a.ast_id
            LIMIT ?
        """, (batch_size,)).fetchall()
        
        if not rows:
            break
        
        batch_refs = 0
        
        for ast_id, content_hash, ast_blob, file_id, relpath in rows:
            try:
                ast_dict = json.loads(ast_blob.decode('utf-8'))
                refs = list(extract_refs_from_ast(ast_dict, relpath, content_hash))
                
                for ref in refs:
                    conn.execute("""
                        INSERT OR IGNORE INTO refs
                        (ref_type, name, defining_ast_id, defining_file_id, 
                         line_number, content_version_id)
                        VALUES (?, ?, ?, ?, ?, 
                                (SELECT content_version_id FROM files WHERE file_id = ?))
                    """, (
                        ref.kind, ref.name, ast_id, file_id, ref.line, file_id
                    ))
                
                batch_refs += len(refs)
                total_refs += len(refs)
                
            except Exception as e:
                errors += 1
                if errors <= 10:
                    logger.warning(f"Error extracting refs from {relpath}: {e}")
            
            processed += 1
        
        conn.commit()
        
        if progress_callback:
            progress_callback(processed, total_pending, total_refs)
    
    logger.info(f"Reference extraction complete: {processed} ASTs, {total_refs} refs, {errors} errors")
    
    return {
        'processed': processed,
        'refs': total_refs,
        'errors': errors
    }