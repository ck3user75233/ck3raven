"""
Database Cleanup Utilities

Handles:
- Removing orphaned content (ASTs, symbols, refs not linked to active files)
- Pruning old content_versions
- Cleaning up deleted files
"""

import sqlite3
import logging
from typing import Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CleanupStats:
    """Statistics from a cleanup operation."""
    orphaned_asts: int = 0
    orphaned_symbols: int = 0
    orphaned_refs: int = 0
    orphaned_localization: int = 0
    orphaned_content: int = 0
    deleted_files_purged: int = 0


def find_orphaned_content_hashes(conn: sqlite3.Connection) -> list:
    """
    Find content_hashes in file_contents that are no longer referenced
    by any active file.
    
    Returns:
        List of orphaned content_hashes
    """
    rows = conn.execute("""
        SELECT fc.content_hash
        FROM file_contents fc
        WHERE NOT EXISTS (
            SELECT 1 FROM files f
            WHERE f.content_hash = fc.content_hash
            AND f.deleted = 0
        )
    """).fetchall()
    
    return [row[0] for row in rows]


def cleanup_orphaned_asts(conn: sqlite3.Connection) -> int:
    """
    Delete ASTs for content_hashes that are no longer referenced.
    
    Returns:
        Number of AST records deleted
    """
    cursor = conn.execute("""
        DELETE FROM asts
        WHERE content_hash NOT IN (
            SELECT DISTINCT content_hash
            FROM files
            WHERE deleted = 0
        )
    """)
    return cursor.rowcount


def cleanup_orphaned_symbols(conn: sqlite3.Connection) -> int:
    """
    Delete symbols for content_hashes that are no longer referenced.
    
    Returns:
        Number of symbol records deleted
    """
    cursor = conn.execute("""
        DELETE FROM symbols
        WHERE content_hash NOT IN (
            SELECT DISTINCT content_hash
            FROM files
            WHERE deleted = 0
        )
    """)
    return cursor.rowcount


def cleanup_orphaned_refs(conn: sqlite3.Connection) -> int:
    """
    Delete refs for content_hashes that are no longer referenced.
    
    Returns:
        Number of ref records deleted
    """
    cursor = conn.execute("""
        DELETE FROM refs
        WHERE content_hash NOT IN (
            SELECT DISTINCT content_hash
            FROM files
            WHERE deleted = 0
        )
    """)
    return cursor.rowcount


def cleanup_orphaned_localization(conn: sqlite3.Connection) -> int:
    """
    Delete localization entries for content_hashes that are no longer referenced.
    
    Returns:
        Number of localization records deleted
    """
    # First delete localization refs
    conn.execute("""
        DELETE FROM localization_refs
        WHERE loc_id IN (
            SELECT loc_id FROM localization_entries
            WHERE content_hash NOT IN (
                SELECT DISTINCT content_hash
                FROM files
                WHERE deleted = 0
            )
        )
    """)
    
    # Then delete localization entries
    cursor = conn.execute("""
        DELETE FROM localization_entries
        WHERE content_hash NOT IN (
            SELECT DISTINCT content_hash
            FROM files
            WHERE deleted = 0
        )
    """)
    return cursor.rowcount


def cleanup_orphaned_content(conn: sqlite3.Connection) -> int:
    """
    Delete file_contents that are no longer referenced by any file.
    
    This should be run AFTER cleaning up ASTs, symbols, refs, and localization.
    
    Returns:
        Number of content records deleted
    """
    cursor = conn.execute("""
        DELETE FROM file_contents
        WHERE content_hash NOT IN (
            SELECT DISTINCT content_hash FROM files
        )
    """)
    return cursor.rowcount


def purge_deleted_files(conn: sqlite3.Connection) -> int:
    """
    Permanently remove files marked as deleted.
    
    Call cleanup_orphaned_* functions first to remove dependent data.
    
    Returns:
        Number of file records deleted
    """
    cursor = conn.execute("DELETE FROM files WHERE deleted = 1")
    return cursor.rowcount


def full_cleanup(conn: sqlite3.Connection, dry_run: bool = False) -> CleanupStats:
    """
    Perform full database cleanup.
    
    Order of operations:
    1. Delete orphaned ASTs
    2. Delete orphaned symbols
    3. Delete orphaned refs
    4. Delete orphaned localization
    5. Delete orphaned content
    6. Purge deleted files
    
    Args:
        conn: Database connection
        dry_run: If True, report counts without deleting
        
    Returns:
        CleanupStats with counts
    """
    stats = CleanupStats()
    
    if dry_run:
        # Count what would be deleted
        stats.orphaned_asts = conn.execute("""
            SELECT COUNT(*) FROM asts
            WHERE content_hash NOT IN (
                SELECT DISTINCT content_hash FROM files WHERE deleted = 0
            )
        """).fetchone()[0]
        
        stats.orphaned_symbols = conn.execute("""
            SELECT COUNT(*) FROM symbols
            WHERE content_hash NOT IN (
                SELECT DISTINCT content_hash FROM files WHERE deleted = 0
            )
        """).fetchone()[0]
        
        stats.orphaned_refs = conn.execute("""
            SELECT COUNT(*) FROM refs
            WHERE content_hash NOT IN (
                SELECT DISTINCT content_hash FROM files WHERE deleted = 0
            )
        """).fetchone()[0]
        
        stats.orphaned_localization = conn.execute("""
            SELECT COUNT(*) FROM localization_entries
            WHERE content_hash NOT IN (
                SELECT DISTINCT content_hash FROM files WHERE deleted = 0
            )
        """).fetchone()[0]
        
        stats.orphaned_content = conn.execute("""
            SELECT COUNT(*) FROM file_contents
            WHERE content_hash NOT IN (SELECT DISTINCT content_hash FROM files)
        """).fetchone()[0]
        
        stats.deleted_files_purged = conn.execute(
            "SELECT COUNT(*) FROM files WHERE deleted = 1"
        ).fetchone()[0]
        
    else:
        # Actually delete
        stats.orphaned_asts = cleanup_orphaned_asts(conn)
        stats.orphaned_symbols = cleanup_orphaned_symbols(conn)
        stats.orphaned_refs = cleanup_orphaned_refs(conn)
        stats.orphaned_localization = cleanup_orphaned_localization(conn)
        stats.orphaned_content = cleanup_orphaned_content(conn)
        stats.deleted_files_purged = purge_deleted_files(conn)
        
        conn.commit()
    
    logger.info(f"Cleanup stats: {stats}")
    return stats


def get_cleanup_stats(conn: sqlite3.Connection) -> CleanupStats:
    """
    Get cleanup statistics without actually deleting anything.
    
    Same as full_cleanup(conn, dry_run=True).
    """
    return full_cleanup(conn, dry_run=True)
