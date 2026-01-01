"""
Playset Loader

Loads playsets from the database. A playset is a list of content_version_ids
in load order that defines what the game sees.

The emulator works entirely from the database:
1. Ingest vanilla/mods into database (files + ASTs cached)
2. Create playset referencing content_version_ids
3. Emulator queries ASTs from database, applies merge policies
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from ck3raven.db.models import Playset, ContentVersion, FileRecord
# EXPUNGED 2025-01-02: playsets.py deleted - file-based now
# Loader needs to be updated to work with file-based playsets
# For now, stub functions that raise NotImplementedError

def get_playset(*args, **kwargs):
    raise NotImplementedError("Database playsets EXPUNGED - use file-based playsets")

def get_playset_load_order(*args, **kwargs):
    raise NotImplementedError("Database playsets EXPUNGED - use file-based playsets")

def get_playset_mods(*args, **kwargs):
    raise NotImplementedError("Database playsets EXPUNGED - use file-based playsets")


@dataclass
class LoadedPlayset:
    """A playset loaded from the database with all content versions resolved."""
    playset_id: int
    name: str
    vanilla_version_id: int
    content_versions: List[int]  # In load order (vanilla first, then mods)
    
    def __repr__(self):
        return f"LoadedPlayset({self.name}, versions={len(self.content_versions)})"


def load_playset_from_db(conn: sqlite3.Connection, playset_id: int) -> LoadedPlayset:
    """
    Load a playset from the database.
    
    Returns a LoadedPlayset with content_version_ids in load order.
    """
    playset = get_playset(conn, playset_id)
    if not playset:
        raise ValueError(f"Playset {playset_id} not found")
    
    # Get vanilla content version
    row = conn.execute("""
        SELECT content_version_id FROM content_versions
        WHERE vanilla_version_id = ? AND kind = 'vanilla'
    """, (playset.vanilla_version_id,)).fetchone()
    
    if not row:
        raise ValueError(f"No content version found for vanilla {playset.vanilla_version_id}")
    
    vanilla_cv_id = row['content_version_id']
    
    # Get mod content versions in load order
    mod_cv_ids = get_playset_load_order(conn, playset_id, enabled_only=True)
    
    # Combine: vanilla first, then mods in order
    all_versions = [vanilla_cv_id] + mod_cv_ids
    
    return LoadedPlayset(
        playset_id=playset_id,
        name=playset.name,
        vanilla_version_id=playset.vanilla_version_id,
        content_versions=all_versions
    )


def get_files_for_folder(
    conn: sqlite3.Connection,
    content_version_id: int,
    folder_pattern: str
) -> List[FileRecord]:
    """
    Get all files in a content version matching a folder pattern.
    
    Args:
        conn: Database connection
        content_version_id: Which version to query
        folder_pattern: Folder prefix like "common/culture/traditions"
    
    Returns:
        List of FileRecord objects
    """
    # Normalize pattern
    pattern = folder_pattern.replace("\\", "/")
    if not pattern.endswith("/"):
        pattern += "/"
    
    rows = conn.execute("""
        SELECT * FROM files
        WHERE content_version_id = ?
          AND relpath LIKE ?
          AND file_type = 'script'
          AND deleted = 0
    """, (content_version_id, pattern + "%")).fetchall()
    
    return [FileRecord.from_row(r) for r in rows]


def get_all_folders_in_playset(
    conn: sqlite3.Connection,
    loaded_playset: LoadedPlayset
) -> List[str]:
    """
    Get all unique folder paths that contain script files across all versions in playset.
    
    Returns normalized folder paths like "common/culture/traditions".
    """
    folders = set()
    
    for cv_id in loaded_playset.content_versions:
        rows = conn.execute("""
            SELECT DISTINCT 
                CASE 
                    WHEN instr(relpath, '/') > 0 
                    THEN substr(relpath, 1, length(relpath) - length(replace(relpath, '/', '')) - instr(reverse(relpath), '/') + 1)
                    ELSE ''
                END as folder
            FROM files
            WHERE content_version_id = ?
              AND file_type = 'script'
              AND deleted = 0
        """, (cv_id,)).fetchall()
        
        for row in rows:
            folder = row['folder'].rstrip('/')
            if folder:
                folders.add(folder)
    
    return sorted(folders)

