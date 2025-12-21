#!/usr/bin/env python3
"""
Extract symbols from existing ASTs in the database.

This script reads the 71K+ ASTs already stored in the database and extracts
symbols from them, rather than re-parsing files from scratch.
"""
import sqlite3
import json
import sys
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Iterator
from dataclasses import dataclass

# Add ck3raven to path
SCRIPT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPT_DIR / "src"))

from ck3raven.db.schema import DEFAULT_DB_PATH

# Files to skip entirely
SKIP_PATTERNS = [
    'checksum_manifest.txt',
    'credit_portraits.txt',
    'gfx/court_scene/',
    'gfx/portraits/accessory_variations/',
    'gfx/map/environment/',
    'gfx/map/map_object_data/',
    'gfx/map/post_effects/',
]

# Symbol type hints by folder path (longest prefix wins)
PATH_TYPE_HINTS = {
    "common/traits": "trait",
    "common/decisions": "decision",
    "common/scripted_effects": "scripted_effect",
    "common/scripted_triggers": "scripted_trigger",
    "common/scripted_modifiers": "scripted_modifier",
    "common/on_actions": "on_action",
    "common/script_values": "script_value",
    "common/modifiers": "modifier",
    "common/static_modifiers": "static_modifier",
    "common/event_modifiers": "event_modifier",
    "common/opinion_modifiers": "opinion_modifier",
    "common/triggered_modifiers": "triggered_modifier",
    "common/religions": "religion",
    "common/faiths": "faith",
    "common/culture": "tradition",
    "common/culture/traditions": "tradition",
    "common/culture/pillars": "cultural_pillar",
    "common/culture/innovations": "innovation",
    "common/culture/eras": "cultural_era",
    "common/buildings": "building",
    "common/holding_types": "holding",
    "common/governments": "government",
    "common/laws": "law",
    "common/court_positions": "court_position",
    "common/council_positions": "council_position",
    "common/court_types": "court_type",
    "common/dynasties": "dynasty",
    "common/dynasty_perks": "dynasty_perk",
    "common/dynasty_legacies": "dynasty_legacy",
    "common/dynasty_houses": "dynasty_house",
    "common/artifacts": "artifact",
    "common/artifact_templates": "artifact",
    "common/inspirations": "inspiration",
    "common/activities": "activity",
    "common/activity_types": "activity",
    "common/schemes": "scheme",
    "common/character_interactions": "interaction",
    "common/lifestyles": "lifestyle",
    "common/focuses": "focus",
    "common/perks": "perk",
    "common/nicknames": "nickname",
    "common/relations": "relation",
    "common/secret_types": "secret_type",
    "common/hook_types": "hook",
    "common/important_actions": "important_action",
    "common/men_at_arms_types": "maa_type",
    "common/casus_belli_types": "cb_type",
    "common/doctrines": "doctrine",
    "common/holy_sites": "holy_site",
    "common/terrains": "terrain",
    "common/defines": "define",
    "common/game_rules": "game_rule",
    "common/bookmarks": "bookmark",
    "common/landed_titles": "title",
    "common/succession_election": "election",
    "common/vassal_contracts": "vassal_contract",
    "common/diarchies": "diarchy",
    "common/domiciles": "domicile",
    "common/accolades": "accolade",
    "common/acccolade_types": "accolade_type",
    "common/travel": "travel",
    "common/combat_effects": "combat_effect",
    "common/flavorization": "flavorization",
    "common/struggle": "struggle",
    "common/legitimacy": "legitimacy",
    "common/vassal_stances": "vassal_stance",
    "events": "event",
    "history/titles": "title_history",
    "history/characters": "historical_character",
    "history/provinces": "province_history",
}

# Reserved keywords that aren't valid symbol names
_RESERVED_KEYWORDS = {
    'namespace', 'yes', 'no', 'true', 'false', 'null', 'none',
    'if', 'else', 'limit', 'trigger', 'effect', 'modifier',
    'AND', 'OR', 'NOT', 'NOR', 'NAND',
    'war', 'character',  # History wrappers
    'category', 'atlas', 'types', 'template', 'textbox',
}

_DATE_PATTERN = re.compile(r'^\d+\.\d+(\.\d+)?$')  # 867.1.1
_NUMERIC_PATTERN = re.compile(r'^\.?\d+\.?\d*$')  # .1, 1., 1.5


def _is_valid_symbol_name(name) -> bool:
    """Check if name is a valid symbol name."""
    if not isinstance(name, str) or len(name) < 2:
        return False
    if name in _RESERVED_KEYWORDS:
        return False
    if _DATE_PATTERN.match(name) or _NUMERIC_PATTERN.match(name):
        return False
    return True


def _should_skip_file(relpath: str) -> bool:
    """Check if file should be skipped."""
    relpath_lower = relpath.replace("\\", "/").lower()
    for pattern in SKIP_PATTERNS:
        if pattern in relpath_lower:
            return True
    return False


def get_symbol_kind(relpath: str) -> str:
    """Determine symbol type from file path."""
    relpath_lower = relpath.replace("\\", "/").lower()
    
    # Find longest matching prefix
    best_match = None
    best_len = 0
    for prefix, symbol_type in PATH_TYPE_HINTS.items():
        if prefix.lower() in relpath_lower and len(prefix) > best_len:
            best_match = symbol_type
            best_len = len(prefix)
    
    if best_match:
        return best_match
    
    # Fallback: if under common/, try to infer from folder name
    if "common/" in relpath_lower:
        parts = relpath_lower.split("/")
        for i, p in enumerate(parts):
            if p == "common" and i + 1 < len(parts):
                folder = parts[i + 1]
                # Singularize
                if folder.endswith("ies"):
                    return folder[:-3] + "y"
                elif folder.endswith("s"):
                    return folder[:-1]
                return folder
    
    return "definition"


@dataclass
class ExtractedSymbol:
    name: str
    kind: str
    line: int
    column: int = 0
    scope: Optional[str] = None


def extract_symbols_from_ast(ast_dict: Dict, relpath: str) -> Iterator[ExtractedSymbol]:
    """Extract symbols from an AST dictionary."""
    kind = get_symbol_kind(relpath)
    
    for child in ast_dict.get('children', []):
        child_type = child.get('_type')
        
        if child_type == 'block':
            # Use _name (canonical name) over name to avoid collisions
            name = child.get('_name') or child.get('name')
            if name and _is_valid_symbol_name(name):
                yield ExtractedSymbol(
                    name=str(name),
                    kind=kind,
                    line=child.get('line', 0),
                    column=child.get('column', 0)
                )
                
        elif child_type == 'assignment':
            key = child.get('key')
            if isinstance(key, str) and not key.startswith('@') and _is_valid_symbol_name(key):
                yield ExtractedSymbol(
                    name=key,
                    kind=kind,
                    line=child.get('line', 0),
                    column=child.get('column', 0)
                )
                
        elif child_type == 'assign':
            # Alternate assignment format
            name = child.get('name')
            if isinstance(name, str) and not name.startswith('@') and _is_valid_symbol_name(name):
                yield ExtractedSymbol(
                    name=name,
                    kind=kind,
                    line=child.get('line', 0),
                    column=child.get('column', 0)
                )


def main():
    print("=" * 60)
    print("Symbol Extraction from Existing ASTs")
    print("=" * 60)
    
    db_path = DEFAULT_DB_PATH
    print(f"\nDatabase: {db_path}")
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    # Get count of ASTs
    ast_count = conn.execute("SELECT COUNT(*) FROM asts").fetchone()[0]
    print(f"ASTs in database: {ast_count:,}")
    
    # Current symbol count
    symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    print(f"Current symbols: {symbol_count:,}")
    
    confirm = input("\nClear existing symbols and extract fresh? (y/n): ")
    if confirm.lower() != 'y':
        print("Aborted.")
        return
    
    # Clear existing symbols and FTS
    print("\nClearing existing symbols...")
    conn.execute("DELETE FROM symbols")
    conn.commit()
    
    # Drop and recreate FTS table (simpler than trying to delete from it)
    print("Rebuilding FTS structure...")
    try:
        conn.execute("DROP TABLE IF EXISTS symbols_fts")
        conn.execute("""
            CREATE VIRTUAL TABLE symbols_fts USING fts5(
                name, symbol_type,
                content='symbols',
                content_rowid='symbol_id'
            )
        """)
        conn.commit()
    except Exception as e:
        print(f"  Note: FTS rebuild: {e}")
    
    # Get all ASTs with file info
    print("\nLoading ASTs...")
    
    # AST is stored as ast_blob (compressed or raw JSON)
    # Need to join through content_hash to get file info
    rows = conn.execute("""
        SELECT a.ast_id, a.ast_blob, a.content_hash, a.parse_ok,
               f.file_id, f.relpath, f.content_version_id
        FROM asts a
        JOIN files f ON a.content_hash = f.content_hash
        WHERE a.ast_blob IS NOT NULL AND a.parse_ok = 1
    """).fetchall()
    
    print(f"Processing {len(rows):,} ASTs...")
    
    total_symbols = 0
    by_type = {}
    errors = 0
    skipped = 0
    
    for i, row in enumerate(rows):
        if i % 5000 == 0:
            print(f"  Progress: {i:,}/{len(rows):,} ({i*100//len(rows)}%)")
        
        relpath = row["relpath"]
        ast_id = row["ast_id"]
        file_id = row["file_id"]
        content_version_id = row["content_version_id"]
        
        # Skip certain files
        if _should_skip_file(relpath):
            skipped += 1
            continue
        
        try:
            # Decode AST blob - may be raw JSON or compressed
            ast_blob = row["ast_blob"]
            if ast_blob is None:
                continue
                
            # Try to decompress if it looks like compressed data
            try:
                import zlib
                ast_json = zlib.decompress(ast_blob).decode('utf-8')
            except:
                # Not compressed, treat as raw bytes/string
                if isinstance(ast_blob, bytes):
                    ast_json = ast_blob.decode('utf-8')
                else:
                    ast_json = ast_blob
            
            ast = json.loads(ast_json)
            
            for sym in extract_symbols_from_ast(ast, relpath):
                conn.execute("""
                    INSERT INTO symbols (
                        symbol_type, name, scope, defining_ast_id, 
                        defining_file_id, content_version_id, 
                        ast_node_path, line_number, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sym.kind, sym.name, sym.scope, ast_id,
                    file_id, content_version_id,
                    None, sym.line, None
                ))
                
                by_type[sym.kind] = by_type.get(sym.kind, 0) + 1
                total_symbols += 1
                
        except json.JSONDecodeError as e:
            errors += 1
            if errors < 5:
                print(f"  JSON error in AST {ast_id}: {e}")
        except Exception as e:
            errors += 1
            if errors < 10:
                print(f"  Error processing AST {ast_id}: {e}")
    
    conn.commit()
    
    # Rebuild FTS index
    print("\nRebuilding FTS index...")
    try:
        conn.execute("INSERT INTO symbols_fts(symbols_fts) VALUES('rebuild')")
        conn.commit()
    except Exception as e:
        print(f"  FTS rebuild error: {e}")
        # Fallback: insert directly
        print("  Trying direct insert...")
        rows = conn.execute("SELECT symbol_id, name, symbol_type FROM symbols").fetchall()
        for r in rows:
            conn.execute("INSERT INTO symbols_fts(rowid, name, symbol_type) VALUES (?, ?, ?)",
                        (r[0], r[1], r[2]))
        conn.commit()
    
    # Verify FTS
    fts_count = conn.execute("SELECT COUNT(*) FROM symbols_fts").fetchone()[0]
    print(f"FTS entries: {fts_count:,}")
    
    # Final stats
    print("\n" + "=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Total symbols extracted: {total_symbols:,}")
    print(f"Files skipped: {skipped:,}")
    print(f"Errors: {errors}")
    print("\nSymbols by type:")
    for sym_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {sym_type}: {count:,}")
    
    conn.close()


if __name__ == "__main__":
    main()
