#!/usr/bin/env python3
"""
Test block logging on a fresh database.

Creates a test database, runs vanilla-only ingest, and verifies
that ingest_log and ingest_blocks tables are populated correctly.

Usage:
    python builder/test_block_logging.py
"""

import sys
import sqlite3
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

TEST_DB_PATH = Path.home() / ".ck3raven" / "test_block_logging.db"


def setup_test_db():
    """Create fresh test database with schema."""
    print(f"Creating test database: {TEST_DB_PATH}")
    
    # Delete if exists
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
        print("  Deleted existing test database")
    
    # Ensure parent directory exists
    TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Clear any cached connections before creating new DB
    from ck3raven.db.schema import close_all_connections
    close_all_connections()
    
    print("  Schema will be initialized by daemon")
    return TEST_DB_PATH


def run_vanilla_build(db_path: Path):
    """Run daemon rebuild with vanilla only."""
    print("\nRunning vanilla-only rebuild...")
    print("  This may take a few minutes for ~80k files\n")
    
    from builder.daemon import run_rebuild, DaemonLogger, StatusWriter, DAEMON_DIR
    
    # Create test-specific log files
    test_log = DAEMON_DIR / "test_block_logging.log"
    test_status = DAEMON_DIR / "test_block_status.json"
    
    logger = DaemonLogger(test_log, also_print=True)
    status = StatusWriter(test_status)
    
    run_rebuild(
        db_path=db_path,
        force=True,  # Full rebuild
        logger=logger,
        status=status,
        symbols_only=False,
        vanilla_path=None,  # Use default
        skip_mods=True,     # Vanilla only
        use_active_playset=False,
        incremental=False,
        dry_run=False,
        check_file_changes=False
    )
    
    print("\n[OK] Rebuild complete")


def verify_logging(db_path: Path):
    """Check ingest_log and ingest_blocks tables."""
    print("\n" + "="*60)
    print("VERIFYING BLOCK LOGGING")
    print("="*60)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Check ingest_log
    print("\n--- ingest_log table ---")
    cursor = conn.execute("SELECT COUNT(*) as cnt FROM ingest_log")
    total_logs = cursor.fetchone()['cnt']
    print(f"Total log entries: {total_logs}")
    
    cursor = conn.execute("""
        SELECT phase, COUNT(*) as cnt, 
               SUM(size_raw) as total_raw,
               SUM(size_stored) as total_stored
        FROM ingest_log 
        GROUP BY phase
        ORDER BY phase
    """)
    for row in cursor:
        raw_mb = (row['total_raw'] or 0) / 1024 / 1024
        stored_mb = (row['total_stored'] or 0) / 1024 / 1024
        print(f"  {row['phase']}: {row['cnt']} files, {raw_mb:.1f}MB raw, {stored_mb:.1f}MB stored")
    
    # Check for errors
    cursor = conn.execute("""
        SELECT COUNT(*) as cnt FROM ingest_log WHERE status = 'error'
    """)
    errors = cursor.fetchone()['cnt']
    print(f"  Errors: {errors}")
    
    # Check ingest_blocks
    print("\n--- ingest_blocks table ---")
    cursor = conn.execute("SELECT COUNT(*) as cnt FROM ingest_blocks")
    total_blocks = cursor.fetchone()['cnt']
    print(f"Total blocks: {total_blocks}")
    
    cursor = conn.execute("""
        SELECT phase, COUNT(*) as block_count,
               SUM(files_count) as total_files,
               SUM(bytes_raw) as total_raw
        FROM ingest_blocks 
        GROUP BY phase
        ORDER BY phase
    """)
    for row in cursor:
        raw_mb = (row['total_raw'] or 0) / 1024 / 1024
        print(f"  {row['phase']}: {row['block_count']} blocks, {row['total_files']} files, {raw_mb:.1f}MB")
    
    # Sample a block
    print("\n--- Sample block ---")
    cursor = conn.execute("""
        SELECT * FROM ingest_blocks 
        ORDER BY block_id DESC LIMIT 1
    """)
    row = cursor.fetchone()
    if row:
        print(f"  Block #{row['block_number']} ({row['phase']})")
        print(f"    Files: {row['files_count']} ({row['files_processed']} processed, {row['files_error']} errors)")
        print(f"    Bytes: {row['bytes_raw']} raw, {row['bytes_stored']} stored")
        print(f"    Merkle hash: {row['merkle_hash'][:32] if row['merkle_hash'] else 'None'}...")
        print(f"    Log range: {row['log_id_start']} - {row['log_id_end']}")
    else:
        print("  No blocks found!")
    
    conn.close()
    
    # Summary
    print("\n" + "="*60)
    if total_logs > 0 and total_blocks > 0:
        print("[PASS] Block logging is working!")
        print(f"  {total_logs} log entries across {total_blocks} blocks")
    elif total_logs > 0 and total_blocks == 0:
        print("[PARTIAL] Log entries exist but no blocks reconstructed")
        print("  Check reconstruct_blocks() was called")
    else:
        print("[FAIL] No log entries found")
        print("  Check log_phase_delta_*() calls in daemon")
    print("="*60)


def main():
    print("="*60)
    print("BLOCK LOGGING TEST")
    print("="*60)
    
    try:
        db_path = setup_test_db()
        run_vanilla_build(db_path)
        verify_logging(db_path)
        
        print(f"\nTest database preserved at: {db_path}")
        print("Run sqlite3 queries manually to explore further.")
        
    except Exception as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
