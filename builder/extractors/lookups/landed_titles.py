"""
Landed Titles Lookup Extractor

Extracts SIMPLE lookup data from common/landed_titles/*.txt files.
Uses parsed ASTs (landed_titles are in SCRIPT route due to scripted blocks).

This extracts only the simple, non-scripted properties:
- Title key and tier (e.g., k_france → tier 'k')
- Capital (county or province ID)
- De jure hierarchy (parent-child relationships)
- Color and simple flags (landless, definite_form)

Does NOT extract scripted content like:
- can_create triggers
- ai_primary_priority script values
- effect blocks

Format example:
    k_france = {
        color = { 20 50 160 }
        capital = c_paris          # ← Extracted
        definite_form = yes        # ← Extracted
        can_create = { ... }       # ← NOT extracted (scripted)
        
        d_normandy = {             # ← De jure child
            capital = c_rouen
            c_rouen = {
                b_rouen = { province = 75 }  # ← Province ID extracted
            }
        }
    }
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass


@dataclass
class TitleData:
    """Title data extracted from landed_titles files."""
    title_key: str  # e.g., "k_france"
    tier: str  # 'e', 'k', 'd', 'c', 'b', 'h' (hegemony)
    capital_county: Optional[str] = None
    capital_province_id: Optional[int] = None
    de_jure_liege: Optional[str] = None
    color_r: Optional[int] = None
    color_g: Optional[int] = None
    color_b: Optional[int] = None
    definite_form: bool = False
    landless: bool = False


def _get_tier_from_key(title_key: str) -> str:
    """Determine tier from title key prefix."""
    if title_key.startswith('e_'):
        return 'e'
    elif title_key.startswith('k_'):
        return 'k'
    elif title_key.startswith('d_'):
        return 'd'
    elif title_key.startswith('c_'):
        return 'c'
    elif title_key.startswith('b_'):
        return 'b'
    elif title_key.startswith('h_'):
        return 'h'  # Hegemony titles
    return 'u'  # Unknown


def extract_titles_from_ast(
    conn: sqlite3.Connection,
    content_version_id: int,
) -> Dict[str, int]:
    """
    Extract title data from already-parsed ASTs in the database.
    
    Landed titles are nested - we need to walk the tree recursively.
    
    Args:
        conn: Database connection
        content_version_id: Content version to filter by
        
    Returns:
        {'inserted': N, 'skipped': N, 'errors': N}
    """
    stats = {'inserted': 0, 'skipped': 0, 'errors': 0}
    
    # Get all ASTs from common/landed_titles/ files
    rows = conn.execute("""
        SELECT a.ast_id, a.ast_blob, f.file_id, f.relpath
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        JOIN asts a ON a.content_hash = fc.content_hash
        WHERE f.content_version_id = ?
        AND f.relpath LIKE '%common/landed_titles/%'
        AND f.relpath LIKE '%.txt'
        AND f.deleted = 0
        AND a.parse_ok = 1
    """, (content_version_id,)).fetchall()
    
    batch = []
    batch_size = 500
    
    for ast_id, ast_blob, file_id, relpath in rows:
        try:
            ast_dict = json.loads(ast_blob.decode('utf-8') if isinstance(ast_blob, bytes) else ast_blob)
            
            # Recursively extract titles from nested structure
            titles = _extract_titles_recursive(ast_dict, parent_title=None)
            
            for title_data in titles:
                batch.append(_title_to_row(title_data, content_version_id))
                
                if len(batch) >= batch_size:
                    _insert_title_batch(conn, batch, stats)
                    batch = []
                        
        except Exception as e:
            stats['errors'] += 1
    
    # Final batch
    if batch:
        _insert_title_batch(conn, batch, stats)
    
    conn.commit()
    return stats


def _extract_titles_recursive(node: Dict, parent_title: Optional[str]) -> List[TitleData]:
    """
    Recursively extract titles from nested landed_titles structure.
    
    Titles can contain other titles (de jure hierarchy).
    """
    titles = []
    
    for child in node.get('children', []):
        if child.get('_type') != 'block':
            continue
        
        name = child.get('name', '')
        tier = _get_tier_from_key(name)
        
        # Skip non-title blocks (like 'can_create', 'ai_primary_priority', etc.)
        if tier == 'u':
            continue
        
        title = TitleData(title_key=name, tier=tier, de_jure_liege=parent_title)
        
        # Parse title properties
        for inner in child.get('children', []):
            if inner.get('_type') == 'assignment':
                key = inner.get('key', '')
                value = inner.get('value', {})
                val = value.get('value', '')
                
                if key == 'capital':
                    title.capital_county = str(val)
                elif key == 'definite_form':
                    title.definite_form = val == 'yes'
                elif key == 'landless':
                    title.landless = val == 'yes'
                elif key == 'province':
                    try:
                        title.capital_province_id = int(val)
                    except ValueError:
                        pass
            
            elif inner.get('_type') == 'block':
                block_name = inner.get('name', '')
                
                # Parse color block
                if block_name == 'color':
                    colors = _parse_color_block(inner)
                    if colors:
                        title.color_r, title.color_g, title.color_b = colors
        
        titles.append(title)
        
        # Recurse into child titles
        child_titles = _extract_titles_recursive(child, parent_title=name)
        titles.extend(child_titles)
    
    return titles


def _parse_color_block(block: Dict) -> Optional[Tuple[int, int, int]]:
    """Parse a color = { r g b } block."""
    values = []
    for child in block.get('children', []):
        if child.get('_type') == 'value':
            try:
                values.append(int(float(child.get('value', 0))))
            except ValueError:
                pass
    
    if len(values) >= 3:
        return values[0], values[1], values[2]
    return None


def _title_to_row(title: TitleData, content_version_id: int) -> tuple:
    """Convert TitleData to database row tuple."""
    return (
        title.title_key,
        title.tier,
        title.capital_county,
        title.capital_province_id,
        title.de_jure_liege,
        title.color_r,
        title.color_g,
        title.color_b,
        1 if title.definite_form else 0,
        1 if title.landless else 0,
        content_version_id,
    )


def _insert_title_batch(conn: sqlite3.Connection, batch: List[tuple], stats: Dict[str, int]):
    """Insert a batch of title records."""
    for row in batch:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO title_lookup
                (title_key, tier, capital_county, capital_province_id, de_jure_liege,
                 color_r, color_g, color_b, definite_form, landless, content_version_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, row)
            stats['inserted'] += 1
        except Exception as e:
            stats['errors'] += 1


def extract_landed_titles(
    conn: sqlite3.Connection,
    content_version_id: int,
    progress_callback=None,
) -> Dict[str, int]:
    """
    Main entry point for landed titles extraction.
    
    Uses AST-based extraction from parsed common/landed_titles/ files.
    Landed titles are in SCRIPT route (they have scripted blocks), but
    we extract only simple lookup data: tier, capital, de jure hierarchy.
    """
    return extract_titles_from_ast(conn, content_version_id)


# Alias for backwards compatibility
extract_titles = extract_landed_titles
