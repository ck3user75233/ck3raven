"""
Specialized Lookup Extractors for QBuilder.

These extractors parse lookup data files directly WITHOUT using the full AST parser.
Lookup files are essentially data tables - parsing them into ASTs is wasteful.

Supported lookup types:
- Characters: history/characters/*.txt -> character_lookup
- Provinces: history/provinces/*.txt -> province_lookup
- Names: common/culture/name_lists/*.txt -> name_lookup
- Holy Sites: common/religion/holy_sites/*.txt -> holy_site_lookup
- Dynasties: common/dynasties/*.txt -> dynasty_lookup
"""

import re
import sqlite3
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class CharacterRecord:
    """Extracted character data."""
    character_id: int
    name: Optional[str] = None
    dynasty_id: Optional[int] = None
    culture: Optional[str] = None
    religion: Optional[str] = None
    father_id: Optional[int] = None
    mother_id: Optional[int] = None
    birth_date: Optional[str] = None
    death_date: Optional[str] = None


@dataclass
class ProvinceRecord:
    """Extracted province data."""
    province_id: int
    culture: Optional[str] = None
    religion: Optional[str] = None
    holding_type: Optional[str] = None


@dataclass
class NameRecord:
    """Extracted name data."""
    name_list_id: str
    name: str
    gender: str  # "male" or "female"


@dataclass
class HolySiteRecord:
    """Extracted holy site data."""
    site_key: str
    county: Optional[str] = None
    barony: Optional[str] = None
    flag: Optional[str] = None


@dataclass
class DynastyRecord:
    """Extracted dynasty data."""
    dynasty_id: int
    name_key: Optional[str] = None
    prefix: Optional[str] = None
    culture: Optional[str] = None


# =============================================================================
# Character Extractor
# =============================================================================

def extract_characters(content: str, file_id: int, cvid: int, conn: sqlite3.Connection) -> int:
    """
    Extract characters from a history/characters file.
    
    Format:
        12345 = {
            name = "Charlemagne"
            dynasty = 25061
            culture = "frankish"
            religion = "catholic"
            father = 12300
            851.1.1 = { birth = yes }
            814.1.28 = { death = yes }
        }
    
    Returns count of characters extracted.
    """
    # Pattern to match character blocks: ID = { ... }
    char_pattern = re.compile(r'^(\d+)\s*=\s*\{', re.MULTILINE)
    
    count = 0
    for match in char_pattern.finditer(content):
        char_id = int(match.group(1))
        start = match.end()
        
        # Find matching closing brace (simple brace counting)
        block = _extract_block(content, start)
        if not block:
            continue
        
        record = CharacterRecord(character_id=char_id)
        
        # Extract simple fields
        record.name = _extract_value(block, 'name')
        record.culture = _extract_value(block, 'culture')
        record.religion = _extract_value(block, 'religion')
        
        dynasty_str = _extract_value(block, 'dynasty')
        if dynasty_str and dynasty_str.isdigit():
            record.dynasty_id = int(dynasty_str)
        
        father_str = _extract_value(block, 'father')
        if father_str and father_str.isdigit():
            record.father_id = int(father_str)
        
        mother_str = _extract_value(block, 'mother')
        if mother_str and mother_str.isdigit():
            record.mother_id = int(mother_str)
        
        # Extract birth/death dates from dated blocks
        record.birth_date = _extract_dated_event(block, 'birth')
        record.death_date = _extract_dated_event(block, 'death')
        
        # Insert into lookup table
        conn.execute("""
            INSERT OR REPLACE INTO character_lookup
            (character_id, name, dynasty_id, culture, religion, 
             father_id, mother_id, birth_date, death_date, content_version_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (record.character_id, record.name, record.dynasty_id,
              record.culture, record.religion, record.father_id,
              record.mother_id, record.birth_date, record.death_date, cvid))
        count += 1
    
    return count


# =============================================================================
# Province Extractor
# =============================================================================

def extract_provinces(content: str, file_id: int, cvid: int, conn: sqlite3.Connection) -> int:
    """
    Extract provinces from a history/provinces file.
    
    Format:
        9472 = {
            culture = tuyuhun
            religion = tengri_pagan
            holding = tribal_holding
        }
    
    Returns count of provinces extracted.
    """
    prov_pattern = re.compile(r'^(\d+)\s*=\s*\{', re.MULTILINE)
    
    count = 0
    for match in prov_pattern.finditer(content):
        prov_id = int(match.group(1))
        start = match.end()
        
        block = _extract_block(content, start)
        if not block:
            continue
        
        record = ProvinceRecord(province_id=prov_id)
        record.culture = _extract_value(block, 'culture')
        record.religion = _extract_value(block, 'religion')
        record.holding_type = _extract_value(block, 'holding')
        
        conn.execute("""
            INSERT OR REPLACE INTO province_lookup
            (province_id, culture, religion, holding_type, content_version_id)
            VALUES (?, ?, ?, ?, ?)
        """, (record.province_id, record.culture, record.religion,
              record.holding_type, cvid))
        count += 1
    
    return count


# =============================================================================
# Name List Extractor
# =============================================================================

def extract_names(content: str, file_id: int, cvid: int, conn: sqlite3.Connection) -> int:
    """
    Extract names from a common/culture/name_lists file.
    
    Format:
        name_list_bedouin = {
            male_names = {
                Abu-Bakr Muhammad Ali Umar
            }
            female_names = {
                Fatima Aisha Khadija
            }
        }
    
    Returns count of names extracted.
    """
    # First, ensure name_lookup table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS name_lookup (
            id INTEGER PRIMARY KEY,
            name_list_id TEXT NOT NULL,
            name TEXT NOT NULL,
            gender TEXT NOT NULL,
            content_version_id INTEGER,
            UNIQUE(name_list_id, name, gender)
        )
    """)
    
    # Pattern to match name_list blocks
    list_pattern = re.compile(r'^(name_list_\w+)\s*=\s*\{', re.MULTILINE)
    
    count = 0
    for match in list_pattern.finditer(content):
        name_list_id = match.group(1)
        start = match.end()
        
        block = _extract_block(content, start)
        if not block:
            continue
        
        # Extract male_names block
        male_names = _extract_name_block(block, 'male_names')
        for name in male_names:
            conn.execute("""
                INSERT OR IGNORE INTO name_lookup
                (name_list_id, name, gender, content_version_id)
                VALUES (?, ?, 'male', ?)
            """, (name_list_id, name, cvid))
            count += 1
        
        # Extract female_names block
        female_names = _extract_name_block(block, 'female_names')
        for name in female_names:
            conn.execute("""
                INSERT OR IGNORE INTO name_lookup
                (name_list_id, name, gender, content_version_id)
                VALUES (?, ?, 'female', ?)
            """, (name_list_id, name, cvid))
            count += 1
    
    return count


# =============================================================================
# Holy Site Extractor
# =============================================================================

def extract_holy_sites(content: str, file_id: int, cvid: int, conn: sqlite3.Connection) -> int:
    """
    Extract holy sites from common/religion/holy_sites file.
    
    Format:
        jerusalem = {
            county = c_jerusalem
            barony = b_temple_mount
            flag = jerusalem_conversion_bonus
        }
    
    Returns count of holy sites extracted.
    """
    # Pattern to match holy site blocks (identifier = { ... })
    site_pattern = re.compile(r'^([a-z_][a-z0-9_]*)\s*=\s*\{', re.MULTILINE)
    
    count = 0
    for match in site_pattern.finditer(content):
        site_key = match.group(1)
        start = match.end()
        
        block = _extract_block(content, start)
        if not block:
            continue
        
        record = HolySiteRecord(site_key=site_key)
        record.county = _extract_value(block, 'county')
        record.barony = _extract_value(block, 'barony')
        record.flag = _extract_value(block, 'flag')
        
        # Only insert if it has a county (real holy site, not other block type)
        if record.county:
            conn.execute("""
                INSERT OR REPLACE INTO holy_site_lookup
                (holy_site_key, county_key, flag, content_version_id)
                VALUES (?, ?, ?, ?)
            """, (record.site_key, record.county, record.flag, cvid))
            count += 1
    
    return count


# =============================================================================
# Dynasty Extractor
# =============================================================================

def extract_dynasties(content: str, file_id: int, cvid: int, conn: sqlite3.Connection) -> int:
    """
    Extract dynasties from common/dynasties file.
    
    Format:
        25061 = {
            name = "dynn_Karling"
            prefix = "dynnp_de"
            culture = "frankish"
        }
    
    Returns count of dynasties extracted.
    """
    dyn_pattern = re.compile(r'^(\d+)\s*=\s*\{', re.MULTILINE)
    
    count = 0
    for match in dyn_pattern.finditer(content):
        dyn_id = int(match.group(1))
        start = match.end()
        
        block = _extract_block(content, start)
        if not block:
            continue
        
        record = DynastyRecord(dynasty_id=dyn_id)
        record.name_key = _extract_value(block, 'name')
        record.prefix = _extract_value(block, 'prefix')
        record.culture = _extract_value(block, 'culture')
        
        conn.execute("""
            INSERT OR REPLACE INTO dynasty_lookup
            (dynasty_id, name_key, prefix, culture, content_version_id)
            VALUES (?, ?, ?, ?, ?)
        """, (record.dynasty_id, record.name_key, record.prefix,
              record.culture, cvid))
        count += 1
    
    return count


# =============================================================================
# Helper Functions
# =============================================================================

def _extract_block(content: str, start: int) -> Optional[str]:
    """Extract content between braces starting at position."""
    depth = 1
    i = start
    while i < len(content) and depth > 0:
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
        i += 1
    
    if depth == 0:
        return content[start:i-1]
    return None


def _extract_value(block: str, key: str) -> Optional[str]:
    """Extract simple value: key = value or key = "value"."""
    # Try quoted value first
    pattern = re.compile(rf'{key}\s*=\s*"([^"]*)"', re.IGNORECASE)
    match = pattern.search(block)
    if match:
        return match.group(1)
    
    # Try unquoted value
    pattern = re.compile(rf'{key}\s*=\s*(\S+)', re.IGNORECASE)
    match = pattern.search(block)
    if match:
        return match.group(1)
    
    return None


def _extract_dated_event(block: str, event: str) -> Optional[str]:
    """Extract date from dated event block like 851.1.1 = { birth = yes }."""
    pattern = re.compile(rf'(\d+\.\d+\.\d+)\s*=\s*\{{[^}}]*{event}\s*=\s*yes', re.IGNORECASE)
    match = pattern.search(block)
    if match:
        return match.group(1)
    return None


def _extract_name_block(block: str, list_name: str) -> list:
    """Extract names from a male_names or female_names block."""
    # Find the block
    pattern = re.compile(rf'{list_name}\s*=\s*\{{', re.IGNORECASE)
    match = pattern.search(block)
    if not match:
        return []
    
    start = match.end()
    name_block = _extract_block(block, start)
    if not name_block:
        return []
    
    # Extract individual names (space-separated, may be quoted)
    names = []
    # Match quoted names
    for m in re.finditer(r'"([^"]+)"', name_block):
        names.append(m.group(1))
    # Match unquoted names (simple identifiers)
    for m in re.finditer(r'\b([A-Za-z_][A-Za-z0-9_]*)\b', name_block):
        name = m.group(1)
        # Skip keywords
        if name.lower() not in ('yes', 'no', 'if', 'else'):
            names.append(name)
    
    return names


# =============================================================================
# Executor Registry
# =============================================================================

LOOKUP_EXECUTORS = {
    "extract_characters": extract_characters,
    "extract_provinces": extract_provinces,
    "extract_names": extract_names,
    "extract_holy_sites": extract_holy_sites,
    "extract_dynasties": extract_dynasties,
}
