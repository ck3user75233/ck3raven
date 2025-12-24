"""
Dynasty Lookup Extractor

Extracts dynasty data from common/dynasties/*.txt files.
These files define dynasties with their IDs, names, cultures, and prefixes.

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

import json
import sqlite3
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass


@dataclass
class DynastyData:
    """Dynasty data extracted from dynasty files."""
    dynasty_id: int
    name_key: str  # e.g., "dynn_Orsini"
    prefix: Optional[str] = None  # e.g., "dynnp_de"
    culture: Optional[str] = None
    motto: Optional[str] = None


def extract_dynasties_from_ast(
    conn: sqlite3.Connection,
    content_version_id: int,
) -> Dict[str, int]:
    """
    Extract dynasty data from already-parsed ASTs in the database.
    
    Args:
        conn: Database connection
        content_version_id: Content version to filter by
        
    Returns:
        {'inserted': N, 'skipped': N, 'errors': N}
    """
    stats = {'inserted': 0, 'skipped': 0, 'errors': 0}
    
    # Get all ASTs from common/dynasties/ files
    rows = conn.execute("""
        SELECT a.ast_id, a.ast_blob, f.file_id, f.relpath
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        JOIN asts a ON a.content_hash = fc.content_hash
        WHERE f.content_version_id = ?
        AND f.relpath LIKE '%common/dynasties/%'
        AND f.relpath LIKE '%.txt'
        AND f.deleted = 0
        AND a.parse_ok = 1
    """, (content_version_id,)).fetchall()
    
    batch = []
    batch_size = 500
    
    for ast_id, ast_blob, file_id, relpath in rows:
        try:
            ast_dict = json.loads(ast_blob.decode('utf-8') if isinstance(ast_blob, bytes) else ast_blob)
            
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
    Uses AST-based extraction from parsed common/dynasties/ files.
    """
    return extract_dynasties_from_ast(conn, content_version_id)
