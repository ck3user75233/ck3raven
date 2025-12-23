"""
Lookup Table Extractors (TBC - To Be Completed)

This module extracts structured reference data from stored ASTs into 
denormalized lookup tables for easy querying.

This is NOT a different parse - it's a deterministic extraction pass over
ASTs that have already been parsed and stored. The goal is to make commonly
needed game data (trait properties, event types, decision flags) easily
searchable without traversing full AST structures.

Design Pattern (from CWTools/jomini analysis):
1. Parser (generic): text → AST  (already done)
2. Extractor (domain-specific): AST → reference rows  (this module)

Status: PROVISIONAL - basic trait extraction implemented, others TBC.
"""

import json
import sqlite3
from typing import Dict, Any, List, Optional, Iterator
from dataclasses import dataclass, field


@dataclass
class TraitLookup:
    """Extracted trait data for lookup table."""
    symbol_id: int
    name: str
    category: Optional[str] = None
    trait_group: Optional[str] = None
    level: Optional[int] = None
    is_genetic: bool = False
    is_physical: bool = False
    is_health: bool = False
    is_fame: bool = False
    opposites: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)
    modifiers: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EventLookup:
    """Extracted event data for lookup table."""
    symbol_id: int
    event_name: str
    namespace: Optional[str] = None
    event_type: Optional[str] = None
    is_hidden: bool = False
    theme: Optional[str] = None


@dataclass
class DecisionLookup:
    """Extracted decision data for lookup table."""
    symbol_id: int
    name: str
    major: bool = False
    ai_check_interval: Optional[int] = None


# =============================================================================
# AST TRAVERSAL HELPERS
# =============================================================================

def get_ast_value(node: Dict, key: str) -> Optional[Any]:
    """Get a simple value from an AST block's children."""
    if 'children' not in node:
        return None
    
    for child in node['children']:
        if child.get('_type') == 'assignment' and child.get('key') == key:
            value_node = child.get('value', {})
            return value_node.get('value')
    return None


def get_ast_values(node: Dict, key: str) -> List[str]:
    """Get all values for a repeated key (like 'flag = X' appearing multiple times)."""
    if 'children' not in node:
        return []
    
    values = []
    for child in node['children']:
        if child.get('_type') == 'assignment' and child.get('key') == key:
            value_node = child.get('value', {})
            val = value_node.get('value')
            if val is not None:
                values.append(str(val))
    return values


def get_ast_block(node: Dict, name: str) -> Optional[Dict]:
    """Get a named child block."""
    if 'children' not in node:
        return None
    
    for child in node['children']:
        if child.get('_type') == 'block' and child.get('name') == name:
            return child
    return None


# =============================================================================
# TRAIT EXTRACTOR
# =============================================================================

def extract_trait_from_ast(ast_block: Dict, symbol_id: int, name: str) -> TraitLookup:
    """
    Extract trait lookup data from an AST block.
    
    Example AST structure for a trait:
    {
        "_type": "block",
        "name": "brave",
        "children": [
            {"_type": "assignment", "key": "category", "value": {"value": "personality"}},
            {"_type": "assignment", "key": "group", "value": {"value": "courage"}},
            {"_type": "assignment", "key": "genetic", "value": {"value": "yes"}},
            {"_type": "assignment", "key": "flag", "value": {"value": "some_flag"}},
            ...
        ]
    }
    """
    lookup = TraitLookup(symbol_id=symbol_id, name=name)
    
    # Simple value extractions
    lookup.category = get_ast_value(ast_block, 'category')
    lookup.trait_group = get_ast_value(ast_block, 'group')
    
    level_val = get_ast_value(ast_block, 'level')
    if level_val is not None:
        try:
            lookup.level = int(level_val)
        except (ValueError, TypeError):
            pass
    
    # Boolean flags
    lookup.is_genetic = get_ast_value(ast_block, 'genetic') == 'yes'
    lookup.is_physical = get_ast_value(ast_block, 'physical') == 'yes'
    lookup.is_health = get_ast_value(ast_block, 'health_trait') == 'yes'
    lookup.is_fame = get_ast_value(ast_block, 'fame') == 'yes'
    
    # Repeated values
    lookup.flags = get_ast_values(ast_block, 'flag')
    lookup.opposites = get_ast_values(ast_block, 'opposite')
    
    # Extract modifiers (numeric assignments that look like stat modifiers)
    # TBC: More sophisticated modifier extraction
    modifier_keys = [
        'diplomacy', 'martial', 'stewardship', 'intrigue', 'learning', 'prowess',
        'health', 'fertility', 'attraction_opinion', 'same_opinion', 'opposite_opinion',
        'vassal_opinion', 'general_opinion', 'clergy_opinion', 'dynasty_opinion',
        'monthly_piety', 'monthly_prestige', 'stress_gain_mult', 'stress_loss_mult',
    ]
    
    for key in modifier_keys:
        val = get_ast_value(ast_block, key)
        if val is not None:
            try:
                lookup.modifiers[key] = float(val) if '.' in str(val) else int(val)
            except (ValueError, TypeError):
                lookup.modifiers[key] = val
    
    return lookup


# =============================================================================
# EVENT EXTRACTOR
# =============================================================================

def extract_event_from_ast(ast_block: Dict, symbol_id: int, event_name: str) -> EventLookup:
    """Extract event lookup data from an AST block."""
    lookup = EventLookup(symbol_id=symbol_id, event_name=event_name)
    
    # Extract namespace from event name (e.g., "blackmail.0001" -> "blackmail")
    if '.' in event_name:
        lookup.namespace = event_name.split('.')[0]
    
    lookup.event_type = get_ast_value(ast_block, 'type')
    lookup.theme = get_ast_value(ast_block, 'theme')
    lookup.is_hidden = get_ast_value(ast_block, 'hidden') == 'yes'
    
    return lookup


# =============================================================================
# DECISION EXTRACTOR
# =============================================================================

def extract_decision_from_ast(ast_block: Dict, symbol_id: int, name: str) -> DecisionLookup:
    """Extract decision lookup data from an AST block."""
    lookup = DecisionLookup(symbol_id=symbol_id, name=name)
    
    lookup.major = get_ast_value(ast_block, 'major') == 'yes'
    
    ai_interval = get_ast_value(ast_block, 'ai_check_interval')
    if ai_interval is not None:
        try:
            lookup.ai_check_interval = int(ai_interval)
        except (ValueError, TypeError):
            pass
    
    return lookup


# =============================================================================
# BATCH EXTRACTION
# =============================================================================

def extract_lookups_from_symbols(
    conn: sqlite3.Connection,
    symbol_type: str,
    batch_size: int = 500,
    progress_callback=None
) -> Dict[str, int]:
    """
    Extract lookup data for all symbols of a given type.
    
    Joins symbols with their ASTs and extracts structured data.
    
    Args:
        conn: Database connection
        symbol_type: 'trait', 'event', 'decision'
        batch_size: How many to process at a time
        progress_callback: Optional (processed, total) callback
        
    Returns:
        {'extracted': N, 'skipped': N, 'errors': N}
    """
    # Get symbols with their AST data
    query = """
        SELECT s.symbol_id, s.name, a.ast_blob, f.relpath
        FROM symbols s
        JOIN asts a ON s.defining_ast_id = a.ast_id
        JOIN files f ON s.defining_file_id = f.file_id
        WHERE s.symbol_type = ?
        AND s.symbol_id NOT IN (
            SELECT symbol_id FROM trait_lookups
            UNION SELECT symbol_id FROM event_lookups
            UNION SELECT symbol_id FROM decision_lookups
        )
    """
    
    cursor = conn.execute(query, (symbol_type,))
    
    stats = {'extracted': 0, 'skipped': 0, 'errors': 0}
    batch = []
    
    for row in cursor:
        symbol_id, name, ast_blob, relpath = row
        
        try:
            # Parse the full AST
            ast_dict = json.loads(ast_blob.decode('utf-8'))
            
            # Find the block for this symbol in the AST
            symbol_block = None
            for child in ast_dict.get('children', []):
                if child.get('_type') == 'block' and child.get('name') == name:
                    symbol_block = child
                    break
            
            if symbol_block is None:
                stats['skipped'] += 1
                continue
            
            # Extract based on type
            if symbol_type == 'trait':
                lookup = extract_trait_from_ast(symbol_block, symbol_id, name)
                batch.append(('trait', lookup))
            elif symbol_type == 'event':
                lookup = extract_event_from_ast(symbol_block, symbol_id, name)
                batch.append(('event', lookup))
            elif symbol_type == 'decision':
                lookup = extract_decision_from_ast(symbol_block, symbol_id, name)
                batch.append(('decision', lookup))
            
            stats['extracted'] += 1
            
            # Flush batch
            if len(batch) >= batch_size:
                _insert_lookup_batch(conn, batch)
                batch = []
                
        except Exception as e:
            stats['errors'] += 1
    
    # Final batch
    if batch:
        _insert_lookup_batch(conn, batch)
    
    conn.commit()
    return stats


def _insert_lookup_batch(conn: sqlite3.Connection, batch: List[tuple]):
    """Insert a batch of lookup records."""
    for lookup_type, lookup in batch:
        if lookup_type == 'trait':
            conn.execute("""
                INSERT OR REPLACE INTO trait_lookups
                (symbol_id, name, category, trait_group, level, 
                 is_genetic, is_physical, is_health, is_fame,
                 opposites_json, flags_json, modifiers_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                lookup.symbol_id, lookup.name, lookup.category, lookup.trait_group,
                lookup.level, int(lookup.is_genetic), int(lookup.is_physical),
                int(lookup.is_health), int(lookup.is_fame),
                json.dumps(lookup.opposites) if lookup.opposites else None,
                json.dumps(lookup.flags) if lookup.flags else None,
                json.dumps(lookup.modifiers) if lookup.modifiers else None,
            ))
        elif lookup_type == 'event':
            conn.execute("""
                INSERT OR REPLACE INTO event_lookups
                (symbol_id, event_name, namespace, event_type, is_hidden, theme)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                lookup.symbol_id, lookup.event_name, lookup.namespace,
                lookup.event_type, int(lookup.is_hidden), lookup.theme,
            ))
        elif lookup_type == 'decision':
            conn.execute("""
                INSERT OR REPLACE INTO decision_lookups
                (symbol_id, name, major, ai_check_interval)
                VALUES (?, ?, ?, ?)
            """, (
                lookup.symbol_id, lookup.name, int(lookup.major),
                lookup.ai_check_interval,
            ))


def extract_all_lookups(conn: sqlite3.Connection, progress_callback=None) -> Dict[str, Dict]:
    """
    Extract all lookup data for supported symbol types.
    
    Returns:
        {'traits': {...stats...}, 'events': {...}, 'decisions': {...}}
    """
    results = {}
    
    for symbol_type in ['trait', 'event', 'decision']:
        results[symbol_type + 's'] = extract_lookups_from_symbols(
            conn, symbol_type, progress_callback=progress_callback
        )
    
    return results
