"""
Change detector for queue-based build daemon.

Detects files that need processing by checking database state:
- Files without ASTs
- Files without symbols (that should have them)
- Files without refs (that should have them)

This is O(n) complexity using EXISTS subqueries.

Usage:
    from builder.change_detector import find_pending_work
    
    for work_item in find_pending_work(conn, content_version_id):
        queue_work(conn, work_item)
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator
import sqlite3

from builder.routing import ProcessingStage, get_processing_envelope


@dataclass(frozen=True)
class PendingWork:
    """A file that needs processing."""
    file_id: int
    content_version_id: int
    relpath: str
    content_hash: str
    needs_parse: bool
    needs_symbols: bool
    needs_refs: bool
    needs_localization: bool
    needs_lookups: bool
    
    @property
    def processing_mask(self) -> int:
        """Get the processing stages needed as a mask."""
        mask = 0
        if self.needs_parse:
            mask |= ProcessingStage.PARSE
        if self.needs_symbols:
            mask |= ProcessingStage.SYMBOLS
        if self.needs_refs:
            mask |= ProcessingStage.REFS
        if self.needs_localization:
            mask |= ProcessingStage.LOCALIZATION
        if self.needs_lookups:
            mask |= ProcessingStage.LOOKUPS
        return mask


def find_pending_work(
    conn: sqlite3.Connection,
    content_version_id: int | None = None,
    *,
    limit: int | None = None,
) -> Iterator[PendingWork]:
    """
    Find files that need processing.
    
    Checks what stages are needed for each file based on:
    1. File routing table (what stages apply)
    2. Database state (what's already done)
    
    Args:
        conn: Database connection
        content_version_id: Optional filter to specific content version
        limit: Max files to return
        
    Yields:
        PendingWork objects for files needing processing
    """
    # Build query to find files needing work
    # Uses EXISTS subqueries for efficiency (not O(n*m))
    
    base_query = """
        SELECT 
            f.file_id,
            f.content_version_id,
            f.relpath,
            f.content_hash,
            CASE WHEN a.ast_id IS NULL THEN 1 ELSE 0 END as needs_ast,
            CASE WHEN s.symbol_id IS NULL THEN 1 ELSE 0 END as needs_symbols,
            CASE WHEN r.ref_id IS NULL THEN 1 ELSE 0 END as needs_refs
        FROM files f
        LEFT JOIN asts a ON f.content_hash = a.content_hash
        LEFT JOIN (
            SELECT DISTINCT defining_file_id as file_id, 1 as symbol_id 
            FROM symbols
        ) s ON f.file_id = s.file_id
        LEFT JOIN (
            SELECT DISTINCT using_file_id as file_id, 1 as ref_id 
            FROM refs
        ) r ON f.file_id = r.file_id
        WHERE f.deleted = 0
    """
    
    params = []
    
    if content_version_id is not None:
        base_query += " AND f.content_version_id = ?"
        params.append(content_version_id)
    
    # Only get files that actually need something done
    base_query += """
        AND (a.ast_id IS NULL OR s.symbol_id IS NULL OR r.ref_id IS NULL)
    """
    
    base_query += " ORDER BY f.file_id"

    # NOTE: LIMIT is applied in Python after filtering, not in SQL
    # This ensures we get exactly `limit` items that need work,
    # not `limit` items where most get filtered out.
    
    yielded = 0
    for row in conn.execute(base_query, params):
        relpath = row["relpath"]
        
        # Get expected processing from routing table
        envelope = get_processing_envelope(relpath)
        expected_stages = envelope.stages
        
        # Determine what's actually needed
        needs_parse = False
        needs_symbols = False
        needs_refs = False
        needs_localization = False
        needs_lookups = False
        
        if ProcessingStage.PARSE in expected_stages:
            needs_parse = bool(row["needs_ast"])
        
        if ProcessingStage.SYMBOLS in expected_stages:
            needs_symbols = bool(row["needs_symbols"]) and not bool(row["needs_ast"])
        
        if ProcessingStage.REFS in expected_stages:
            needs_refs = bool(row["needs_refs"]) and not bool(row["needs_ast"])
        
        if ProcessingStage.LOCALIZATION in expected_stages:
            # TODO: Check if localization already parsed
            needs_localization = False  # Skip for now
        
        if ProcessingStage.LOOKUPS in expected_stages:
            # TODO: Check if lookups already extracted
            needs_lookups = False  # Skip for now
        
        # Skip if nothing needed
        if not any([needs_parse, needs_symbols, needs_refs, needs_localization, needs_lookups]):
            continue
        
        yield PendingWork(
            file_id=row["file_id"],
            content_version_id=row["content_version_id"],
            relpath=relpath,
            content_hash=row["content_hash"],
            needs_parse=needs_parse,
            needs_symbols=needs_symbols,
            needs_refs=needs_refs,
            needs_localization=needs_localization,
            needs_lookups=needs_lookups,
        )
        
        yielded += 1
        if limit is not None and yielded >= limit:
            return


def find_pending_work_for_playset(
    conn: sqlite3.Connection,
    playset_id: int,
    *,
    limit: int | None = None,
) -> Iterator[PendingWork]:
    """
    Find pending work across all content versions in a playset.
    
    Args:
        conn: Database connection
        playset_id: Playset to check
        limit: Optional total limit across all CVs
        
    Yields:
        PendingWork objects
    """
    # Get all content versions in playset
    rows = conn.execute("""
        SELECT content_version_id 
        FROM playset_content_versions
        WHERE playset_id = ?
        ORDER BY load_order
    """, (playset_id,)).fetchall()
    
    yielded = 0
    for row in rows:
        cvid = row["content_version_id"]
        if limit is not None:
            remaining = limit - yielded
            if remaining <= 0:
                return
            for work in find_pending_work(conn, cvid, limit=remaining):
                yield work
                yielded += 1
        else:
            yield from find_pending_work(conn, cvid)


def get_work_summary(conn: sqlite3.Connection, content_version_id: int | None = None) -> dict:
    """
    Get summary of pending work.
    
    Returns:
        Dict with counts of files needing each type of processing
    """
    base_query = """
        SELECT 
            COUNT(*) as total_files,
            SUM(CASE WHEN a.ast_id IS NULL THEN 1 ELSE 0 END) as needs_ast,
            SUM(CASE WHEN s.symbol_id IS NULL THEN 1 ELSE 0 END) as needs_symbols
        FROM files f
        LEFT JOIN asts a ON f.content_hash = a.content_hash
        LEFT JOIN (
            SELECT DISTINCT defining_file_id as file_id, 1 as symbol_id 
            FROM symbols
        ) s ON f.file_id = s.file_id
        WHERE f.deleted = 0
    """
    
    params = []
    if content_version_id is not None:
        base_query += " AND f.content_version_id = ?"
        params.append(content_version_id)
    
    row = conn.execute(base_query, params).fetchone()
    
    return {
        "total_files": row["total_files"],
        "needs_ast": row["needs_ast"],
        "needs_symbols": row["needs_symbols"],
    }


# --- Self-test ---
if __name__ == "__main__":
    print("Change detector module loaded successfully")
    print(f"PendingWork fields: {list(PendingWork.__dataclass_fields__.keys())}")
