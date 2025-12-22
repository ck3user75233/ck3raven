#!/usr/bin/env python3
"""
Localization Ingestion Script

Parses all localization files (.yml) in the database and populates
the localization_entries and localization_refs tables.

This can be run independently of the main rebuild, or as part of
the builder wizard for selective re-parsing.

Usage:
    python ingest_localization.py                    # Full ingestion
    python ingest_localization.py --status           # Show current status
    python ingest_localization.py --clear            # Clear existing entries
    python ingest_localization.py --language english # Only english files
"""

import sys
import time
import logging
import argparse
from pathlib import Path
from typing import Optional, Iterator, Tuple

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import sqlite3
from ck3raven.db.schema import DEFAULT_DB_PATH
from ck3raven.parser.localization import parse_localization, LocalizationEntry


def get_write_connection(db_path=DEFAULT_DB_PATH):
    """Get a connection configured for writing with proper timeout."""
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 60000")  # 60 second timeout
    return conn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# Localization parser version - bump when parser changes
# v1.0.1: Fixed regex to allow dots in key names (e.g., event.0001.t)
# v1.0.2: Fixed regex to allow keys starting with digits (e.g., 6540_modifier)
LOC_PARSER_VERSION = "loc-1.0.2"


def get_or_create_parser_version(conn: sqlite3.Connection, version_string: str) -> int:
    """Get or create parser version ID."""
    row = conn.execute(
        "SELECT parser_version_id FROM parsers WHERE version_string = ?",
        (version_string,)
    ).fetchone()
    
    if row:
        return row[0]
    
    cursor = conn.execute(
        "INSERT INTO parsers (version_string, description) VALUES (?, ?)",
        (version_string, "Localization parser for Paradox .yml format")
    )
    conn.commit()
    return cursor.lastrowid


def iter_localization_files(conn: sqlite3.Connection, language_filter: Optional[str] = None) -> Iterator[Tuple[str, str, str]]:
    """
    Yield (content_hash, relpath, content_text) for all localization files.
    
    Uses a separate read connection to avoid transaction conflicts.
    
    Args:
        conn: Database connection (for path only)
        language_filter: Optional language to filter by (e.g., 'english')
    """
    # Use a separate read-only connection
    read_conn = sqlite3.connect(str(DEFAULT_DB_PATH), timeout=30.0)
    read_conn.execute("PRAGMA query_only = ON")  # Read-only mode
    
    query = """
        SELECT f.content_hash, f.relpath, fc.content_text
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.relpath LIKE 'localization/%'
        AND f.relpath LIKE '%.yml'
        AND f.deleted = 0
    """
    
    if language_filter:
        query += f" AND f.relpath LIKE 'localization/{language_filter}/%'"
    
    cursor = read_conn.execute(query)
    while True:
        rows = cursor.fetchmany(100)
        if not rows:
            break
        for row in rows:
            yield row[0], row[1], row[2]
    
    read_conn.close()


def ingest_localization_file(
    conn: sqlite3.Connection,
    content_hash: str,
    relpath: str,
    content: str,
    parser_version_id: int
) -> Tuple[int, int]:
    """
    Parse and ingest a single localization file.
    
    Returns (entries_count, refs_count).
    """
    # Check if already parsed with this parser version
    existing = conn.execute(
        "SELECT COUNT(*) FROM localization_entries WHERE content_hash = ? AND parser_version_id = ?",
        (content_hash, parser_version_id)
    ).fetchone()[0]
    
    if existing > 0:
        return 0, 0  # Already parsed
    
    # Parse the file
    result = parse_localization(content, relpath)
    
    entries_count = 0
    refs_count = 0
    
    for entry in result.entries:
        # Insert entry
        cursor = conn.execute("""
            INSERT OR IGNORE INTO localization_entries 
            (content_hash, language, loc_key, version, raw_value, plain_text, line_number, parser_version_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            content_hash,
            result.language,
            entry.key,
            entry.version,
            entry.raw_value,
            entry.plain_text,
            entry.line_number,
            parser_version_id
        ))
        
        if cursor.rowcount > 0:
            entries_count += 1
            loc_id = cursor.lastrowid
            
            # Insert refs
            for ref in entry.scripted_refs:
                conn.execute(
                    "INSERT INTO localization_refs (loc_id, ref_type, ref_value) VALUES (?, 'scripted', ?)",
                    (loc_id, ref)
                )
                refs_count += 1
            
            for ref in entry.variable_refs:
                conn.execute(
                    "INSERT INTO localization_refs (loc_id, ref_type, ref_value) VALUES (?, 'variable', ?)",
                    (loc_id, ref)
                )
                refs_count += 1
            
            for ref in entry.icon_refs:
                conn.execute(
                    "INSERT INTO localization_refs (loc_id, ref_type, ref_value) VALUES (?, 'icon', ?)",
                    (loc_id, ref)
                )
                refs_count += 1
    
    return entries_count, refs_count


def show_status(conn: sqlite3.Connection):
    """Show current localization ingestion status."""
    total_files = conn.execute("""
        SELECT COUNT(DISTINCT f.content_hash)
        FROM files f
        WHERE f.relpath LIKE 'localization/%'
        AND f.relpath LIKE '%.yml'
        AND f.deleted = 0
    """).fetchone()[0]
    
    parsed_files = conn.execute("""
        SELECT COUNT(DISTINCT content_hash)
        FROM localization_entries
    """).fetchone()[0]
    
    total_entries = conn.execute("SELECT COUNT(*) FROM localization_entries").fetchone()[0]
    total_refs = conn.execute("SELECT COUNT(*) FROM localization_refs").fetchone()[0]
    
    # By language
    by_lang = conn.execute("""
        SELECT language, COUNT(*) as cnt
        FROM localization_entries
        GROUP BY language
        ORDER BY cnt DESC
    """).fetchall()
    
    print(f"\n=== Localization Ingestion Status ===")
    print(f"Files: {parsed_files}/{total_files} parsed")
    print(f"Entries: {total_entries:,}")
    print(f"References: {total_refs:,}")
    
    if by_lang:
        print(f"\nBy language:")
        for lang, cnt in by_lang:
            print(f"  {lang}: {cnt:,}")
    
    pct = (parsed_files / total_files * 100) if total_files > 0 else 0
    print(f"\nProgress: {pct:.1f}%")


def clear_localization(conn: sqlite3.Connection, parser_version_id: Optional[int] = None):
    """Clear localization entries (optionally only for specific parser version)."""
    if parser_version_id:
        conn.execute("DELETE FROM localization_refs WHERE loc_id IN (SELECT loc_id FROM localization_entries WHERE parser_version_id = ?)", (parser_version_id,))
        conn.execute("DELETE FROM localization_entries WHERE parser_version_id = ?", (parser_version_id,))
    else:
        conn.execute("DELETE FROM localization_refs")
        conn.execute("DELETE FROM localization_entries")
    conn.commit()
    logger.info("Cleared localization entries")


def main():
    parser = argparse.ArgumentParser(description="Localization Ingestion")
    parser.add_argument("--status", action="store_true", help="Show ingestion status")
    parser.add_argument("--clear", action="store_true", help="Clear existing entries")
    parser.add_argument("--language", type=str, help="Filter by language (e.g., 'english')")
    parser.add_argument("--batch-size", type=int, default=50, help="Commit every N files")
    args = parser.parse_args()
    
    conn = get_write_connection(DEFAULT_DB_PATH)
    
    if args.status:
        show_status(conn)
        return
    
    if args.clear:
        clear_localization(conn)
        return
    
    # Get parser version
    parser_version_id = get_or_create_parser_version(conn, LOC_PARSER_VERSION)
    logger.info(f"Using parser version: {LOC_PARSER_VERSION} (id={parser_version_id})")
    
    # Count files
    total_files = conn.execute("""
        SELECT COUNT(DISTINCT f.content_hash)
        FROM files f
        WHERE f.relpath LIKE 'localization/%'
        AND f.relpath LIKE '%.yml'
        AND f.deleted = 0
    """).fetchone()[0]
    
    logger.info(f"Found {total_files} localization files to process")
    
    # Process files
    start_time = time.time()
    files_processed = 0
    total_entries = 0
    total_refs = 0
    
    for content_hash, relpath, content in iter_localization_files(conn, args.language):
        try:
            entries, refs = ingest_localization_file(
                conn, content_hash, relpath, content, parser_version_id
            )
            total_entries += entries
            total_refs += refs
            files_processed += 1
            
            if files_processed % args.batch_size == 0:
                conn.commit()
                elapsed = time.time() - start_time
                rate = files_processed / elapsed
                pct = files_processed / total_files * 100
                logger.info(f"Progress: {files_processed}/{total_files} ({pct:.1f}%) - {rate:.1f} files/sec - {total_entries:,} entries")
        
        except Exception as e:
            logger.error(f"Error processing {relpath}: {e}")
    
    conn.commit()
    
    elapsed = time.time() - start_time
    logger.info(f"\n=== Complete ===")
    logger.info(f"Files: {files_processed}")
    logger.info(f"Entries: {total_entries:,}")
    logger.info(f"References: {total_refs:,}")
    logger.info(f"Time: {elapsed:.1f}s")
    
    show_status(conn)


if __name__ == "__main__":
    main()
