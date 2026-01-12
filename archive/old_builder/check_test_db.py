#!/usr/bin/env python3
"""Check test DB status with block statistics."""
import sqlite3
from pathlib import Path

TEST_DB = Path.home() / ".ck3raven" / "test_block_logging.db"

if not TEST_DB.exists():
    print("Test DB does not exist yet")
else:
    conn = sqlite3.connect(TEST_DB)
    conn.row_factory = sqlite3.Row
    
    print("="*70)
    print("TEST DATABASE STATUS")
    print("="*70)
    
    # Basic counts
    files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    logs = conn.execute("SELECT COUNT(*) FROM ingest_log").fetchone()[0]
    blocks = conn.execute("SELECT COUNT(*) FROM ingest_blocks").fetchone()[0]
    asts = conn.execute("SELECT COUNT(*) FROM asts WHERE parse_ok=1").fetchone()[0]
    
    print(f"\nFiles: {files:,}")
    print(f"ASTs: {asts:,}")
    print(f"Log entries: {logs:,}")
    print(f"Blocks: {blocks:,}")
    
    # Blocks by phase
    print("\n" + "-"*70)
    print("BLOCKS BY PHASE")
    print("-"*70)
    cursor = conn.execute("""
        SELECT phase, 
               COUNT(*) as block_count,
               SUM(files_processed + files_skipped + files_errored) as total_files,
               SUM(bytes_scanned) as total_raw,
               SUM(bytes_stored) as total_stored,
               AVG(duration_sec) as avg_duration,
               MIN(block_number) as first_block,
               MAX(block_number) as last_block
        FROM ingest_blocks 
        GROUP BY phase
        ORDER BY phase
    """)
    
    for row in cursor:
        raw_mb = (row['total_raw'] or 0) / 1024 / 1024
        stored_mb = (row['total_stored'] or 0) / 1024 / 1024
        print(f"\n  {row['phase']}:")
        print(f"    Blocks: {row['block_count']} (#{row['first_block']}-#{row['last_block']})")
        print(f"    Files: {row['total_files'] or 0:,}")
        print(f"    Size: {raw_mb:.1f} MB raw, {stored_mb:.1f} MB stored")
        print(f"    Avg duration: {row['avg_duration'] or 0:.2f}s per block")
    
    # Sample block details
    print("\n" + "-"*70)
    print("RECENT BLOCKS (last 5)")
    print("-"*70)
    cursor = conn.execute("""
        SELECT block_id, phase, block_number, files_processed, files_skipped, files_errored,
               bytes_scanned, duration_sec, block_hash
        FROM ingest_blocks 
        ORDER BY block_id DESC 
        LIMIT 5
    """)
    
    for row in cursor:
        raw_kb = (row['bytes_scanned'] or 0) / 1024
        hash_short = row['block_hash'][:16] + "..." if row['block_hash'] else "None"
        total = row['files_processed'] + row['files_skipped'] + row['files_errored']
        errors = f" ({row['files_errored']} err)" if row['files_errored'] else ""
        print(f"  #{row['block_number']:3d} {row['phase']:20s} | {total:4d} files | {raw_kb:8.1f} KB | {row['duration_sec'] or 0:5.1f}s | {hash_short}{errors}")
    
    # Log entries by phase
    print("\n" + "-"*70)
    print("LOG ENTRIES BY PHASE")
    print("-"*70)
    cursor = conn.execute("""
        SELECT phase, 
               COUNT(*) as count,
               SUM(CASE WHEN status='processed' THEN 1 ELSE 0 END) as processed,
               SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors
        FROM ingest_log 
        GROUP BY phase
        ORDER BY phase
    """)
    
    for row in cursor:
        err_str = f" ({row['errors']} errors)" if row['errors'] else ""
        print(f"  {row['phase']:20s}: {row['count']:,} entries, {row['processed']:,} processed{err_str}")
    
    # Builder runs
    print("\n" + "-"*70)
    print("BUILD RUNS")
    print("-"*70)
    try:
        cursor = conn.execute("""
            SELECT build_id, status, started_at, ended_at, error_message
            FROM builder_runs 
            ORDER BY started_at DESC 
            LIMIT 3
        """)
        for row in cursor:
            build_short = row['build_id'][:8] + "..."
            err = f" - {row['error_message'][:50]}" if row['error_message'] else ""
            print(f"  {build_short} | {row['status']:10s} | {row['started_at']}{err}")
    except:
        print("  (no builder_runs table)")
    
    print("\n" + "="*70)
    conn.close()
