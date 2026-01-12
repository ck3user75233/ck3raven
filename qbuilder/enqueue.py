"""
QBuilder Enqueue - Assign envelopes and queue files for processing.

This module reads all files from the database and assigns each one
an envelope from the routing table, then inserts them into the queue.
"""

from __future__ import annotations
import sqlite3
import time
from typing import Optional

from qbuilder.routing import get_router
from qbuilder.schema import init_qbuilder_schema


def enqueue_all_files(
    conn: sqlite3.Connection,
    content_version_id: Optional[int] = None,
) -> dict:
    """
    Enqueue all files from the database with their assigned envelopes.
    
    This is idempotent - files already in queue are skipped.
    Files with SKIP envelope are not queued.
    
    Args:
        conn: Database connection
        content_version_id: Optional filter to specific content version
        
    Returns:
        Stats dict with counts
    """
    router = get_router()
    
    # Ensure queue table exists
    init_qbuilder_schema(conn)
    
    # Build query
    query = """
        SELECT 
            f.file_id,
            f.content_version_id,
            f.relpath,
            f.content_hash
        FROM files f
        WHERE f.deleted = 0
    """
    params = []
    
    if content_version_id is not None:
        query += " AND f.content_version_id = ?"
        params.append(content_version_id)
    
    query += " ORDER BY f.file_id"
    
    # Track stats
    stats = {
        "total_files": 0,
        "queued": 0,
        "skipped_envelope": 0,
        "already_queued": 0,
    }
    
    now = time.time()
    batch = []
    batch_size = 1000
    
    for row in conn.execute(query, params):
        stats["total_files"] += 1
        
        relpath = row["relpath"]
        result = router.route(relpath)
        
        # Skip files with SKIP envelope
        if result.should_skip:
            stats["skipped_envelope"] += 1
            continue
        
        batch.append((
            row["file_id"],
            row["content_version_id"],
            relpath,
            result.envelope,
            now,
            row["content_hash"],
        ))
        
        if len(batch) >= batch_size:
            inserted = _insert_batch(conn, batch)
            stats["queued"] += inserted
            stats["already_queued"] += len(batch) - inserted
            batch = []
    
    # Insert remaining
    if batch:
        inserted = _insert_batch(conn, batch)
        stats["queued"] += inserted
        stats["already_queued"] += len(batch) - inserted
    
    conn.commit()
    return stats


def _insert_batch(conn: sqlite3.Connection, batch: list) -> int:
    """Insert batch of queue items, ignoring duplicates. Returns count inserted."""
    cursor = conn.executemany("""
        INSERT OR IGNORE INTO qbuilder_queue 
            (file_id, content_version_id, relpath, envelope, created_at, content_hash)
        VALUES (?, ?, ?, ?, ?, ?)
    """, batch)
    return cursor.rowcount


def clear_queue(conn: sqlite3.Connection) -> int:
    """Clear all items from the queue."""
    cursor = conn.execute("DELETE FROM qbuilder_queue")
    conn.commit()
    return cursor.rowcount


def get_queue_summary(conn: sqlite3.Connection) -> dict:
    """Get summary of queue state."""
    stats = conn.execute("""
        SELECT 
            status,
            envelope,
            COUNT(*) as count
        FROM qbuilder_queue
        GROUP BY status, envelope
        ORDER BY status, envelope
    """).fetchall()
    
    by_status = {}
    by_envelope = {}
    
    for row in stats:
        status = row["status"]
        envelope = row["envelope"]
        count = row["count"]
        
        by_status[status] = by_status.get(status, 0) + count
        by_envelope[envelope] = by_envelope.get(envelope, 0) + count
    
    return {
        "by_status": by_status,
        "by_envelope": by_envelope,
        "total": sum(by_status.values()),
    }
