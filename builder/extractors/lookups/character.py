"""
Character Lookup Extractor

Extracts character data from history/characters/*.txt files.
These files define historical characters with their IDs, names, dynasties,
birth/death dates, traits, and family relationships.

ARCHITECTURE NOTE:
Character files follow the LOOKUPS route in file_routes.py.
They do NOT get ASTs - we parse raw content directly here.
This is a specialized extractor per the file routing table.

Format example:
    98 = {
        name = "Eadgar"
        dynasty_house = house_british_isles_wessex
        culture = anglo_saxon
        religion = "catholic"
        trait = honest
        father = 102
        943.8.7 = { birth = yes }
        975.7.8 = { death = yes }
    }
"""

import sqlite3
from typing import Dict, Optional, List
from dataclasses import dataclass, field

# Use the shared parser
from ck3raven.parser import parse_source


@dataclass
class CharacterData:
    """Character data extracted from history files."""
    character_id: int
    name: str
    dynasty_id: Optional[int] = None
    dynasty_house: Optional[str] = None
    culture: Optional[str] = None
    religion: Optional[str] = None
    birth_date: Optional[str] = None
    death_date: Optional[str] = None
    father_id: Optional[int] = None
    mother_id: Optional[int] = None
    traits: List[str] = field(default_factory=list)


def extract_characters_from_raw_content(
    conn: sqlite3.Connection,
    content_version_id: int,
    progress_callback=None,
) -> Dict[str, int]:
    """
    Extract character data from raw file content in the database.
    
    Per file routing table, character files (history/characters/*.txt) are
    LOOKUPS route - they don't get ASTs. We parse raw content directly.
    
    Args:
        conn: Database connection  
        content_version_id: Content version to filter by
        progress_callback: Optional (processed, total) callback
        
    Returns:
        {'inserted': N, 'skipped': N, 'errors': N}
    """
    stats = {'inserted': 0, 'skipped': 0, 'errors': 0}
    
    # Get raw file content for character files (no AST join - they don't have ASTs)
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, fc.content_text
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.content_version_id = ?
        AND f.relpath LIKE '%history/characters/%'
        AND f.relpath LIKE '%.txt'
        AND f.deleted = 0
        AND fc.content_text IS NOT NULL
    """, (content_version_id,)).fetchall()
    
    if not rows:
        return {'inserted': 0, 'skipped': 0, 'errors': 0, 'note': 'no character files found'}
    
    batch = []
    batch_size = 500
    total_files = len(rows)
    
    for i, (file_id, relpath, content_text) in enumerate(rows):
        try:
            # Parse raw content directly using shared parser
            ast_dict = parse_source(content_text, filename=relpath)
            
            if ast_dict is None:
                stats['errors'] += 1
                continue
            
            # Each top-level block is a character: char_id = { ... }
            for child in ast_dict.get('children', []):
                if child.get('_type') != 'block':
                    continue
                
                try:
                    char_id = int(child.get('name', '0'))
                except ValueError:
                    continue
                
                if char_id == 0:
                    continue
                
                char_data = _parse_character_block(char_id, child)
                if char_data:
                    batch.append(_character_to_row(char_data, content_version_id))
                    
                    if len(batch) >= batch_size:
                        _insert_character_batch(conn, batch, stats)
                        batch = []
                        
        except Exception as e:
            stats['errors'] += 1
        
        if progress_callback:
            progress_callback(i + 1, total_files)
    
    # Final batch
    if batch:
        _insert_character_batch(conn, batch, stats)
    
    conn.commit()
    return stats


def _parse_character_block(char_id: int, block: Dict) -> Optional[CharacterData]:
    """Parse a character block into CharacterData."""
    char = CharacterData(character_id=char_id, name="Unknown")
    
    for child in block.get('children', []):
        if child.get('_type') != 'assignment':
            # Check for date blocks (birth/death dates)
            if child.get('_type') == 'block':
                block_name = child.get('name', '')
                # Date format like "943.8.7"
                if '.' in block_name and block_name.replace('.', '').isdigit():
                    for inner in child.get('children', []):
                        if inner.get('_type') == 'assignment':
                            key = inner.get('key', '')
                            if key == 'birth':
                                char.birth_date = block_name
                            elif key == 'death':
                                char.death_date = block_name
            continue
        
        key = child.get('key', '')
        value = child.get('value', {}).get('value', '')
        
        if key == 'name':
            char.name = str(value).strip('"')
        elif key == 'dynasty':
            try:
                char.dynasty_id = int(value)
            except ValueError:
                pass
        elif key == 'dynasty_house':
            char.dynasty_house = str(value)
        elif key == 'culture':
            char.culture = str(value).strip('"')
        elif key == 'religion':
            char.religion = str(value).strip('"')
        elif key == 'father':
            try:
                char.father_id = int(value)
            except ValueError:
                pass
        elif key == 'mother':
            try:
                char.mother_id = int(value)
            except ValueError:
                pass
        elif key == 'trait':
            char.traits.append(str(value))
    
    return char


def _character_to_row(char: CharacterData, content_version_id: int) -> tuple:
    """Convert CharacterData to database row tuple."""
    import json
    return (
        char.character_id,
        char.name,
        char.dynasty_id,
        char.dynasty_house,
        char.culture,
        char.religion,
        char.birth_date,
        char.death_date,
        char.father_id,
        char.mother_id,
        json.dumps(char.traits) if char.traits else None,
        content_version_id,
    )


def _insert_character_batch(conn: sqlite3.Connection, batch: List[tuple], stats: Dict[str, int]):
    """Insert a batch of character records."""
    for row in batch:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO character_lookup
                (character_id, name, dynasty_id, dynasty_house, culture, religion,
                 birth_date, death_date, father_id, mother_id, traits_json, content_version_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, row)
            stats['inserted'] += 1
        except Exception as e:
            stats['errors'] += 1


def extract_characters(
    conn: sqlite3.Connection,
    content_version_id: int,
    progress_callback=None,
) -> Dict[str, int]:
    """
    Main entry point for character extraction.
    Parses raw content directly (LOOKUPS route - no ASTs).
    """
    return extract_characters_from_raw_content(conn, content_version_id, progress_callback)
