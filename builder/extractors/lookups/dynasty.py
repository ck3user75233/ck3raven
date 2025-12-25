"""
Dynasty Lookup Extractor

Extracts dynasty data from common/dynasties/*.txt files.
These files define dynasties with their IDs, names, cultures, and prefixes.

ARCHITECTURE NOTE:
Dynasty files follow the LOOKUPS route in file_routes.py.
They do NOT get ASTs - we parse raw content directly here.
This is a specialized extractor per the file routing table.

Format example:
    2 = {
        name = "dynn_Orsini"
        culture = "italian"
    }
    3 = {
        prefix = "dynnp_de"
        name = "dynn_Villeneuve"
        culture = "norman"
    }
"""

import sqlite3
from typing import Dict, Optional, List
from dataclasses import dataclass

# Use the shared parser
from ck3raven.parser import parse_source


@dataclass
class DynastyData:
    """Dynasty data extracted from dynasty files."""
    dynasty_id: int
    name_key: str  # e.g., "dynn_Orsini"
    prefix: Optional[str] = None  # e.g., "dynnp_de"
    culture: Optional[str] = None
    motto: Optional[str] = None


def extract_dynasties_from_raw_content(
    conn: sqlite3.Connection,
    content_version_id: int,
    progress_callback=None,
) -> Dict[str, int]:
    """
    Extract dynasty data from raw file content in the database.
    
    Per file routing table, dynasty files (common/dynasties/*.txt) are
    LOOKUPS route - they don't get ASTs. We parse raw content directly.
    
    Args:
        conn: Database connection
        content_version_id: Content version to filter by
        progress_callback: Optional (processed, total) callback
        
    Returns:
        {'inserted': N, 'skipped': N, 'errors': N}
    """
    stats = {'inserted': 0, 'skipped': 0, 'errors': 0}
    
    # Get raw file content for dynasty files (no AST join - they don't have ASTs)
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, fc.content_text
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.content_version_id = ?
        AND f.relpath LIKE '%common/dynasties/%'
        AND f.relpath LIKE '%.txt'
        AND f.deleted = 0
        AND fc.content_text IS NOT NULL
    """, (content_version_id,)).fetchall()
    
    if not rows:
        return {'inserted': 0, 'skipped': 0, 'errors': 0, 'note': 'no dynasty files found'}
    
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
            
            # Each top-level block is a dynasty: dynasty_id = { ... }
            for child in ast_dict.get('children', []):
                if child.get('_type') != 'block':
                    continue
                
                try:
                    dynasty_id = int(child.get('name', '0'))
                except ValueError:
                    continue
                
                if dynasty_id == 0:
                    continue
                
                dynasty_data = _parse_dynasty_block(dynasty_id, child)
                if dynasty_data:
                    batch.append(_dynasty_to_row(dynasty_data, content_version_id))
                    
                    if len(batch) >= batch_size:
                        _insert_dynasty_batch(conn, batch, stats)
                        batch = []
                        
        except Exception as e:
            stats['errors'] += 1
        
        if progress_callback:
            progress_callback(i + 1, total_files)
    
    # Final batch
    if batch:
        _insert_dynasty_batch(conn, batch, stats)
    
    conn.commit()
    return stats


def _parse_dynasty_block(dynasty_id: int, block: Dict) -> Optional[DynastyData]:
    """Parse a dynasty block into DynastyData."""
    dynasty = DynastyData(dynasty_id=dynasty_id, name_key="unknown")
    
    for child in block.get('children', []):
        if child.get('_type') != 'assignment':
            continue
        
        key = child.get('key', '')
        value = child.get('value', {}).get('value', '')
        
        if key == 'name':
            dynasty.name_key = str(value).strip('"')
        elif key == 'prefix':
            dynasty.prefix = str(value).strip('"')
        elif key == 'culture':
            dynasty.culture = str(value).strip('"')
        elif key == 'motto':
            dynasty.motto = str(value).strip('"')
    
    return dynasty


def _dynasty_to_row(dynasty: DynastyData, content_version_id: int) -> tuple:
    """Convert DynastyData to database row tuple."""
    return (
        dynasty.dynasty_id,
        dynasty.name_key,
        dynasty.prefix,
        dynasty.culture,
        dynasty.motto,
        content_version_id,
    )


def _insert_dynasty_batch(conn: sqlite3.Connection, batch: List[tuple], stats: Dict[str, int]):
    """Insert a batch of dynasty records."""
    for row in batch:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO dynasty_lookup
                (dynasty_id, name_key, prefix, culture, motto, content_version_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, row)
            stats['inserted'] += 1
        except Exception as e:
            stats['errors'] += 1


def extract_dynasties(
    conn: sqlite3.Connection,
    content_version_id: int,
    progress_callback=None,
) -> Dict[str, int]:
    """
    Main entry point for dynasty extraction.
    Parses raw content directly (LOOKUPS route - no ASTs).
    """
    return extract_dynasties_from_raw_content(conn, content_version_id, progress_callback)
