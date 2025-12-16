"""
Symbol and Reference Extraction

Extracts definitions (symbols) and uses (references) from parsed AST.
Populates the symbols and refs tables for cross-reference analysis.
"""

import sqlite3
import json
import logging
from typing import Optional, List, Dict, Any, Tuple, Set, Iterator
from dataclasses import dataclass
from pathlib import Path

from ck3raven.db.models import Symbol, Reference

logger = logging.getLogger(__name__)


# Pattern to identify scripted values/effects/triggers by path
PATH_SYMBOL_PATTERNS = {
    'common/scripted_effects': 'scripted_effect',
    'common/scripted_triggers': 'scripted_trigger',
    'common/scripted_modifiers': 'scripted_modifier',
    'common/on_action': 'on_action',
    'common/buildings': 'building',
    'common/decisions': 'decision',
    'common/character_interactions': 'interaction',
    'common/activities': 'activity',
    'common/schemes': 'scheme',
    'common/traits': 'trait',
    'common/culture/traditions': 'tradition',
    'common/religion/religions': 'religion',
    'common/dynasties': 'dynasty',
    'common/landed_titles': 'title',
    'common/governments': 'government',
    'common/laws': 'law',
    'common/men_at_arms_types': 'maa_type',
    'common/artifacts': 'artifact',
    'common/important_actions': 'important_action',
    'common/casus_belli_types': 'cb_type',
    'common/lifestyles': 'lifestyle',
    'common/focuses': 'focus',
    'common/perks': 'perk',
    'common/event_backgrounds': 'event_background',
    'common/court_positions': 'court_position',
    'common/defines': 'define',
    'events': 'event',
    'gfx/portraits/portrait_modifiers': 'portrait_modifier',
    'localization': 'localization_key',
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


def get_symbol_kind_from_path(relpath: str) -> Optional[str]:
    """Determine symbol kind based on file path."""
    relpath_normalized = relpath.replace('\\', '/')
    for pattern, kind in PATH_SYMBOL_PATTERNS.items():
        if pattern in relpath_normalized:
            return kind
    return None


def extract_symbols_from_ast(
    ast_dict: Dict[str, Any],
    relpath: str,
    content_hash: str
) -> Iterator[ExtractedSymbol]:
    """
    Extract symbol definitions from serialized AST.
    
    Symbols are top-level definitions like events, decisions, traits, etc.
    """
    kind = get_symbol_kind_from_path(relpath)
    if kind is None:
        return
    
    # Process children of root
    children = ast_dict.get('children', [])
    
    for child in children:
        child_type = child.get('_type')
        
        if child_type == 'block':
            name = child.get('name')
            line = child.get('line', 0)
            column = child.get('column', 0)
            
            if name:
                # Try to extract signature/doc from children
                signature = None
                doc = None
                
                block_children = child.get('children', [])
                for bc in block_children:
                    if bc.get('_type') == 'assignment':
                        key = bc.get('key')
                        if key in ('desc', 'description'):
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
            # Top-level assignments can be symbols (defines, scripted values)
            key = child.get('key')
            line = child.get('line', 0)
            column = child.get('column', 0)
            
            if kind == 'define' and key:
                value = child.get('value', {})
                val_str = str(value.get('value', '')) if value.get('_type') == 'value' else None
                
                yield ExtractedSymbol(
                    name=key,
                    kind='define',
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
