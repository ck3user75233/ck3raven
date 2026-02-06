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

SCHEMA v6 COLUMN NAMES (January 2026):
- symbols: ast_id, line_number, column_number, symbol_type, node_hash_norm
- refs: ast_id, line_number, column_number, ref_type
"""

import sqlite3
import json
import logging
import re
import hashlib
from typing import Optional, List, Dict, Any, Tuple, Set, Iterator, Callable
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
    'common/culture/cultures': 'culture',  # Individual culture definitions
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
    # Node identity for conflict detection (Phase 0, January 2026)
    # These are NOT NULL in schema - extraction must always provide them
    node_hash_norm: str = ""  # SHA-256 of normalized node text
    node_start_offset: int = 0  # Character offset (Python string index)
    node_end_offset: int = 0  # Character offset (exclusive)


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


# Regex for stripping comments and normalizing whitespace
_COMMENT_PATTERN = re.compile(r'#[^\n]*')  # Line comments
_WHITESPACE_PATTERN = re.compile(r'[ \t]+')  # Horizontal whitespace runs


def normalize_node_text(text: str) -> str:
    """
    Normalize CK3 script text for hashing.
    
    Normalization ensures identical semantic content produces the same hash
    regardless of cosmetic differences like trailing whitespace or comment style.
    
    Steps:
    1. Normalize line endings to \n
    2. Remove comments (# to end of line)
    3. Collapse horizontal whitespace runs to single space
    4. Strip leading/trailing whitespace from each line
    5. Remove empty lines
    6. Strip leading/trailing whitespace from result
    
    Args:
        text: Raw source text of the symbol node
        
    Returns:
        Normalized text suitable for hashing
    """
    # 1. Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # 2. Remove comments
    text = _COMMENT_PATTERN.sub('', text)
    
    # 3. Process line by line
    lines = []
    for line in text.split('\n'):
        # Collapse whitespace runs
        line = _WHITESPACE_PATTERN.sub(' ', line)
        # Strip leading/trailing
        line = line.strip()
        # Keep non-empty lines
        if line:
            lines.append(line)
    
    return '\n'.join(lines)


def compute_node_hash(text: str) -> str:
    """
    Compute SHA-256 hash of normalized node text.
    
    Args:
        text: Raw source text of the symbol node
        
    Returns:
        Hex-encoded SHA-256 hash of normalized text
    """
    normalized = normalize_node_text(text)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


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


def _extract_nested_block_symbols(
    parent_block: Dict[str, Any],
    nested_block_name: str,
    symbol_kind: str,
    source_text: str,
    content_hash: str
) -> Iterator[ExtractedSymbol]:
    """
    Extract symbols from a named nested block within a parent block.
    
    Used for: faiths inside religion blocks (faiths = { catholic = {...} })
    
    The parser may represent "faiths = { ... }" as either:
    - An assignment with key="faiths" and value=block
    - A block with name="faiths"
    
    This function handles both cases.
    
    Args:
        parent_block: The parent AST block (e.g., christianity_religion)
        nested_block_name: Name of the nested container block (e.g., "faiths")
        symbol_kind: Symbol type for extracted items (e.g., "faith")
        source_text: Original source text for hash computation
        content_hash: Fallback hash if offsets unavailable
    """
    for child in parent_block.get('children', []):
        container_block = None
        
        # Case 1: assignment (key = { ... })
        if child.get('_type') == 'assignment':
            key = child.get('key')
            if key == nested_block_name:
                value = child.get('value', {})
                if value.get('_type') == 'block':
                    container_block = value
        
        # Case 2: block with name (name = { ... } parsed as block)
        elif child.get('_type') == 'block':
            block_name = child.get('_name') or child.get('name')
            if block_name == nested_block_name:
                container_block = child
        
        # Extract children from the container block
        if container_block:
            for nested_child in container_block.get('children', []):
                if nested_child.get('_type') == 'block':
                    name = nested_child.get('_name') or nested_child.get('name')
                    if name and _is_valid_symbol_name(name):
                        line = nested_child.get('line', 0)
                        column = nested_child.get('column', 0)
                        start_offset = nested_child.get('start_offset', 0)
                        end_offset = nested_child.get('end_offset', 0)
                        
                        if source_text and end_offset > start_offset:
                            node_span = source_text[start_offset:end_offset]
                            node_hash = compute_node_hash(node_span)
                        else:
                            node_hash = content_hash
                        
                        yield ExtractedSymbol(
                            name=name,
                            kind=symbol_kind,
                            line=line,
                            column=column,
                            signature=None,
                            doc=None,
                            node_hash_norm=node_hash,
                            node_start_offset=start_offset,
                            node_end_offset=end_offset
                        )


def _extract_title_hierarchy(
    block: Dict[str, Any],
    source_text: str,
    content_hash: str,
    depth: int = 0
) -> Iterator[ExtractedSymbol]:
    """
    Recursively extract title symbols from landed_titles hierarchy.
    
    CK3 title hierarchy: empire > kingdom > duchy > county > barony
    All nested blocks with valid title prefixes (e_, k_, d_, c_, b_) are titles.
    
    Args:
        block: AST block node (title block)
        source_text: Original source text for hash computation
        content_hash: Fallback hash if offsets unavailable
        depth: Recursion depth (for debugging, max ~5 levels)
    """
    # Safety limit - CK3 titles never go deeper than 5 levels
    if depth > 6:
        return
    
    for child in block.get('children', []):
        if child.get('_type') == 'block':
            name = child.get('_name') or child.get('name')
            if name and _is_valid_symbol_name(name):
                # Check if it's a title (starts with standard prefix)
                # Also accept names without prefix as potential modded titles
                is_title = (
                    name.startswith(('e_', 'k_', 'd_', 'c_', 'b_')) or
                    # Some mods/vanilla use non-prefixed names
                    depth > 0  # If we're inside a title, nested blocks are likely titles
                )
                
                if is_title:
                    line = child.get('line', 0)
                    column = child.get('column', 0)
                    start_offset = child.get('start_offset', 0)
                    end_offset = child.get('end_offset', 0)
                    
                    if source_text and end_offset > start_offset:
                        node_span = source_text[start_offset:end_offset]
                        node_hash = compute_node_hash(node_span)
                    else:
                        node_hash = content_hash
                    
                    yield ExtractedSymbol(
                        name=name,
                        kind='title',
                        line=line,
                        column=column,
                        signature=None,
                        doc=None,
                        node_hash_norm=node_hash,
                        node_start_offset=start_offset,
                        node_end_offset=end_offset
                    )
                    
                    # Recurse into this title's children
                    yield from _extract_title_hierarchy(
                        child, source_text, content_hash, depth + 1
                    )


def extract_symbols_from_ast(
    ast_dict: Dict[str, Any],
    relpath: str,
    content_hash: str,
    source_text: str = ""
) -> Iterator[ExtractedSymbol]:
    """
    Extract symbol definitions from serialized AST.
    
    EXHAUSTIVE EXTRACTION:
    - Every top-level block is a symbol
    - Scripted values (@name = value) are symbols
    - Type is inferred from path, never filtered
    
    Args:
        ast_dict: Serialized AST (from RootNode.to_dict())
        relpath: Relative path of the source file
        content_hash: Hash of the original content
        source_text: Original source text for node span extraction and hashing
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
                
                # Extract offsets and compute hash
                start_offset = child.get('start_offset', 0)
                end_offset = child.get('end_offset', 0)
                
                if source_text and end_offset > start_offset:
                    node_span = source_text[start_offset:end_offset]
                    node_hash = compute_node_hash(node_span)
                else:
                    # Fallback: use content_hash as placeholder
                    node_hash = content_hash
                
                yield ExtractedSymbol(
                    name=name,
                    kind=kind,
                    line=line,
                    column=column,
                    signature=signature,
                    doc=doc,
                    node_hash_norm=node_hash,
                    node_start_offset=start_offset,
                    node_end_offset=end_offset
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
                
                # Extract offsets and compute hash
                start_offset = child.get('start_offset', 0)
                end_offset = child.get('end_offset', 0)
                
                if source_text and end_offset > start_offset:
                    node_span = source_text[start_offset:end_offset]
                    node_hash = compute_node_hash(node_span)
                else:
                    # Fallback: use content_hash as placeholder
                    node_hash = content_hash
                
                yield ExtractedSymbol(
                    name=sym_name,
                    kind=sym_kind,
                    line=line,
                    column=column,
                    signature=val_str,
                    node_hash_norm=node_hash,
                    node_start_offset=start_offset,
                    node_end_offset=end_offset
                )
    
    # ==========================================================================
    # NESTED SYMBOL EXTRACTION
    # Some content types have important nested structures that aren't top-level
    # ==========================================================================
    
    # Extract faiths from religion files
    # Structure: religion_name = { faiths = { faith_name = {...} } }
    if kind == 'religion':
        for child in children:
            if child.get('_type') == 'block':
                yield from _extract_nested_block_symbols(
                    parent_block=child,
                    nested_block_name='faiths',
                    symbol_kind='faith',
                    source_text=source_text,
                    content_hash=content_hash
                )
    
    # Extract full title hierarchy from landed_titles
    # Structure: e_empire = { k_kingdom = { d_duchy = { c_county = { b_barony = {...} } } } }
    if kind == 'title':
        for child in children:
            if child.get('_type') == 'block':
                # Top-level is already extracted, recurse into nested titles
                yield from _extract_title_hierarchy(
                    block=child,
                    source_text=source_text,
                    content_hash=content_hash,
                    depth=1  # Start at 1 since top-level already extracted
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
    ast_id: int,
    symbols: List[ExtractedSymbol]
) -> int:
    """
    Store multiple symbols in batch, keyed to AST (content identity).
    
    CONTENT-KEYED (January 2026 Flag Day):
    - Binds to ast_id ONLY
    - NO file_id or content_version_id
    - Deletes existing symbols for this AST before inserting
    
    Returns:
        Number of symbols stored
    """
    if not symbols:
        return 0
    
    # Delete existing symbols for this AST (content)
    conn.execute("DELETE FROM symbols WHERE ast_id = ?", (ast_id,))
    
    # Insert new symbols
    rows = [
        (ast_id, s.line, s.column,
         s.name, s.kind, s.scope,
         json.dumps({"signature": s.signature, "doc": s.doc}) if s.signature or s.doc else None)
        for s in symbols
    ]
    
    conn.executemany("""
        INSERT INTO symbols 
        (ast_id, line_number, column_number,
         name, symbol_type, scope, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows)
    
    conn.commit()
    return len(rows)


def store_refs_batch(
    conn: sqlite3.Connection,
    ast_id: int,
    refs: List[ExtractedRef]
) -> int:
    """
    Store multiple references in batch, keyed to AST (content identity).
    
    CONTENT-KEYED (January 2026 Flag Day):
    - Binds to ast_id ONLY
    - NO file_id or content_version_id
    - Deletes existing refs for this AST before inserting
    
    Returns:
        Number of refs stored
    """
    if not refs:
        return 0
    
    # Delete existing refs for this AST (content)
    conn.execute("DELETE FROM refs WHERE ast_id = ?", (ast_id,))
    
    # Insert new refs
    rows = [
        (ast_id, r.line, r.column,
         r.name, r.kind, r.context, 'unresolved')
        for r in refs
    ]
    
    conn.executemany("""
        INSERT INTO refs 
        (ast_id, line_number, column_number,
         name, ref_type, context, resolution_status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows)
    
    conn.commit()
    return len(rows)


def extract_and_store(
    conn: sqlite3.Connection,
    ast_id: int,
    ast_dict: Dict[str, Any],
    relpath: str
) -> Tuple[int, int]:
    """
    Extract and store both symbols and references for an AST.
    
    CONTENT-KEYED (January 2026 Flag Day):
    - Takes ast_id only (content identity)
    - NO file_id or content_version_id
    
    Returns:
        (symbol_count, ref_count)
    """
    symbols = list(extract_symbols_from_ast(ast_dict, relpath, ""))
    refs = list(extract_refs_from_ast(ast_dict, relpath, ""))
    
    sym_count = store_symbols_batch(conn, ast_id, symbols)
    ref_count = store_refs_batch(conn, ast_id, refs)
    
    return sym_count, ref_count


def find_symbol_by_name(
    conn: sqlite3.Connection,
    name: str,
    symbol_type: Optional[str] = None
) -> List[Symbol]:
    """Find symbols by exact name match."""
    if symbol_type:
        rows = conn.execute("""
            SELECT * FROM symbols WHERE name = ? AND symbol_type = ?
        """, (name, symbol_type)).fetchall()
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
    ref_type: Optional[str] = None
) -> List[Reference]:
    """Find all references to a symbol."""
    if ref_type:
        rows = conn.execute("""
            SELECT * FROM refs WHERE name = ? AND ref_type = ?
        """, (name, ref_type)).fetchall()
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
    
    # By type (using correct column names)
    rows = conn.execute("""
        SELECT symbol_type, COUNT(*) as cnt FROM symbols GROUP BY symbol_type ORDER BY cnt DESC
    """).fetchall()
    stats['symbols_by_type'] = {r['symbol_type']: r['cnt'] for r in rows}
    
    rows = conn.execute("""
        SELECT ref_type, COUNT(*) as cnt FROM refs GROUP BY ref_type ORDER BY cnt DESC
    """).fetchall()
    stats['refs_by_type'] = {r['ref_type']: r['cnt'] for r in rows}
    
    return stats


def find_unused_symbols(
    conn: sqlite3.Connection,
    symbol_type: Optional[str] = None
) -> List[Symbol]:
    """
    Find symbols that are never referenced.
    
    Useful for finding dead code.
    """
    if symbol_type:
        rows = conn.execute("""
            SELECT s.* FROM symbols s
            LEFT JOIN refs r ON s.name = r.name AND s.symbol_type = r.ref_type
            WHERE r.ref_id IS NULL AND s.symbol_type = ?
        """, (symbol_type,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT s.* FROM symbols s
            LEFT JOIN refs r ON s.name = r.name AND s.symbol_type = r.ref_type
            WHERE r.ref_id IS NULL
        """).fetchall()
    
    return [Symbol.from_row(r) for r in rows]


def find_undefined_refs(
    conn: sqlite3.Connection,
    ref_type: Optional[str] = None
) -> List[Reference]:
    """
    Find references that don't have a matching symbol.
    
    Useful for finding broken references.
    """
    if ref_type:
        rows = conn.execute("""
            SELECT r.* FROM refs r
            LEFT JOIN symbols s ON r.name = s.name AND r.ref_type = s.symbol_type
            WHERE s.symbol_id IS NULL AND r.ref_type = ?
        """, (ref_type,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT r.* FROM refs r
            LEFT JOIN symbols s ON r.name = s.name AND r.ref_type = s.symbol_type
            WHERE s.symbol_id IS NULL
        """).fetchall()
    
    return [Reference.from_row(r) for r in rows]


# =============================================================================
# Incremental Extraction Functions
# =============================================================================

def extract_symbols_incremental(
    conn: sqlite3.Connection,
    batch_size: int = 500,
    progress_callback: Optional[Callable] = None,
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

    Schema v4 column names: file_id, ast_id, content_version_id, line_number, column_number, symbol_type

    Args:
        conn: Database connection
        batch_size: Number of ASTs to process per batch
        progress_callback: Optional callback(processed, total, symbols_extracted)
        force_rebuild: If True, delete all existing symbols first and rebuild

    Returns:
        Dict with 'processed', 'symbols', 'errors', 'skipped' counts
    """
    from ck3raven.db.file_routes import should_skip_for_symbols, get_script_file_filter_sql

    # Handle force rebuild
    if force_rebuild:
        logger.info("Force rebuild: clearing all existing symbols...")
        conn.execute("DELETE FROM symbols")
        conn.commit()
        logger.info("Symbols cleared")

    # Get SQL filter for symbol-eligible files
    file_filter = get_script_file_filter_sql()

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
                f.relpath,
                f.content_version_id
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

        for row in rows:
            ast_id = row[0]
            content_hash = row[1]
            ast_blob = row[2]
            file_id = row[3]
            relpath = row[4]
            content_version_id = row[5]
            
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

                # Store symbols with full source traceability (schema v4 column names)
                for sym in symbols:
                    cursor = conn.execute("""
                        INSERT OR IGNORE INTO symbols
                        (symbol_type, name, scope, ast_id, file_id,
                         content_version_id, line_number, column_number, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        sym.kind, sym.name, sym.scope, ast_id, file_id,
                        content_version_id, sym.line, sym.column, None
                    ))
                    if cursor.rowcount > 0:
                        batch_inserted += 1
                        symbols_inserted += 1
                    else:
                        # Duplicate definition - record as a reference for conflict tracking
                        # This enables ck3_conflicts to detect when multiple mods define the same symbol
                        conn.execute("""
                            INSERT OR IGNORE INTO refs
                            (ref_type, name, ast_id, file_id, content_version_id,
                             line_number, column_number, context, resolution_status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            sym.kind,  # ref_type matches symbol_type for cross-reference
                            sym.name,
                            ast_id,
                            file_id,
                            content_version_id,
                            sym.line,
                            sym.column,
                            'duplicate_definition',
                            'resolved'
                        ))

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
    progress_callback: Optional[Callable] = None
) -> Dict[str, int]:
    """
    Incrementally extract references from ASTs that do not have refs yet.

    Similar to extract_symbols_incremental but for references.

    Schema v4 column names: file_id, ast_id, content_version_id, line_number, column_number, ref_type

    Args:
        conn: Database connection
        batch_size: Number of ASTs to process per batch
        progress_callback: Optional callback(processed, total, refs_extracted)

    Returns:
        Dict with 'processed', 'refs', 'errors' counts
    """
    # Count ASTs needing refs (using correct column name: ast_id)
    total_row = conn.execute("""
        SELECT COUNT(*)
        FROM asts a
        WHERE a.parse_ok = 1
        AND NOT EXISTS (
            SELECT 1 FROM refs r
            WHERE r.ast_id = a.ast_id
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
                f.relpath,
                f.content_version_id
            FROM asts a
            JOIN files f ON a.content_hash = f.content_hash
            WHERE a.parse_ok = 1
            AND f.deleted = 0
            AND NOT EXISTS (
                SELECT 1 FROM refs r
                WHERE r.ast_id = a.ast_id
            )
            GROUP BY a.ast_id
            LIMIT ?
        """, (batch_size,)).fetchall()
        
        if not rows:
            break
        
        batch_refs = 0
        
        for row in rows:
            ast_id = row[0]
            content_hash = row[1]
            ast_blob = row[2]
            file_id = row[3]
            relpath = row[4]
            content_version_id = row[5]
            
            try:
                ast_dict = json.loads(ast_blob.decode('utf-8'))
                refs = list(extract_refs_from_ast(ast_dict, relpath, content_hash))
                
                for ref in refs:
                    conn.execute("""
                        INSERT OR IGNORE INTO refs
                        (ref_type, name, ast_id, file_id, 
                         line_number, column_number, content_version_id, resolution_status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'unknown')
                    """, (
                        ref.kind, ref.name, ast_id, file_id, 
                        ref.line, ref.column, content_version_id
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
