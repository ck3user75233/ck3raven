"""
Province Lookup Extractor

Extracts province data from:
1. map_data/definition.csv - Province IDs, names, RGB colors
2. history/provinces/*.txt - Culture, religion, holdings (NOT YET IMPLEMENTED)

The definition.csv provides the core mapping from province ID to name.
History files provide the game state at various dates (more complex).
"""

import csv
import sqlite3
from pathlib import Path
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass


@dataclass
class ProvinceData:
    """Province data extracted from definition.csv."""
    province_id: int
    name: str
    rgb_r: int
    rgb_g: int
    rgb_b: int
    # These come from history/provinces/ - not yet implemented
    culture: Optional[str] = None
    religion: Optional[str] = None
    holding_type: Optional[str] = None
    terrain: Optional[str] = None


def parse_definition_csv(csv_path: Path) -> List[ProvinceData]:
    """
    Parse map_data/definition.csv to extract province data.
    
    Format: province_id;r;g;b;name;x;
    First line (0;0;0;0;x;x;) is a header/placeholder.
    
    Args:
        csv_path: Path to definition.csv
        
    Returns:
        List of ProvinceData (excluding province_id 0)
    """
    provinces = []
    
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f, delimiter=';')
        for row in reader:
            if len(row) < 5:
                continue
            
            try:
                province_id = int(row[0])
            except ValueError:
                continue
            
            # Skip province 0 (placeholder/ocean)
            if province_id == 0:
                continue
            
            try:
                provinces.append(ProvinceData(
                    province_id=province_id,
                    name=row[4].strip() if row[4] else f"Province {province_id}",
                    rgb_r=int(row[1]),
                    rgb_g=int(row[2]),
                    rgb_b=int(row[3]),
                ))
            except (ValueError, IndexError) as e:
                # Skip malformed rows
                continue
    
    return provinces


def extract_provinces(
    conn: sqlite3.Connection,
    vanilla_path: Path,
    content_version_id: int,
    progress_callback=None,
) -> Dict[str, int]:
    """
    Extract province data into province_lookup table.
    
    Currently only extracts from definition.csv.
    TODO: Also parse history/provinces/*.txt for culture/religion/holdings.
    
    Args:
        conn: Database connection
        vanilla_path: Path to game/ directory
        content_version_id: Content version for vanilla
        progress_callback: Optional (processed, total) callback
        
    Returns:
        {'inserted': N, 'skipped': N, 'errors': N}
    """
    definition_csv = vanilla_path / "map_data" / "definition.csv"
    
    if not definition_csv.exists():
        return {'inserted': 0, 'skipped': 0, 'errors': 1, 'error_msg': 'definition.csv not found'}
    
    provinces = parse_definition_csv(definition_csv)
    
    stats = {'inserted': 0, 'skipped': 0, 'errors': 0}
    
    # Batch insert for performance
    batch = []
    batch_size = 500
    
    for i, prov in enumerate(provinces):
        batch.append((
            prov.province_id,
            prov.name,
            prov.rgb_r,
            prov.rgb_g,
            prov.rgb_b,
            prov.culture,
            prov.religion,
            prov.holding_type,
            prov.terrain,
            content_version_id,
        ))
        
        if len(batch) >= batch_size:
            _insert_province_batch(conn, batch, stats)
            batch = []
            if progress_callback:
                progress_callback(i + 1, len(provinces))
    
    # Final batch
    if batch:
        _insert_province_batch(conn, batch, stats)
    
    conn.commit()
    return stats


def _insert_province_batch(conn: sqlite3.Connection, batch: List[tuple], stats: Dict[str, int]):
    """Insert a batch of province records."""
    for row in batch:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO province_lookup
                (province_id, name, rgb_r, rgb_g, rgb_b, 
                 culture, religion, holding_type, terrain, content_version_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, row)
            stats['inserted'] += 1
        except Exception as e:
            stats['errors'] += 1
