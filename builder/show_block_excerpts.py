#!/usr/bin/env python3
"""Show excerpts from block logging data."""
import sqlite3
from pathlib import Path

TEST_DB = Path.home() / ".ck3raven" / "test_block_logging.db"

conn = sqlite3.connect(TEST_DB)
conn.row_factory = sqlite3.Row

print("="*80)
print("SAMPLE INGEST_LOG ENTRIES (first 10)")
print("="*80)
for row in conn.execute('SELECT log_id, phase, relpath, status, size_raw, content_hash FROM ingest_log ORDER BY log_id LIMIT 10'):
    hash_short = row['content_hash'][:12] + '...' if row['content_hash'] else 'None'
    size = row['size_raw'] or 0
    relpath = row['relpath'][:50] if row['relpath'] else ''
    print(f"{row['log_id']:5d} | {row['phase']:18s} | {row['status']:10s} | {size:8d} | {relpath}")

print()
print("="*80)
print("INGEST_BLOCKS (all 32)")
print("="*80)
for row in conn.execute('''
    SELECT block_id, phase, block_number, files_processed, files_skipped, files_errored, 
           bytes_scanned, bytes_stored, block_hash, log_id_start, log_id_end
    FROM ingest_blocks ORDER BY block_id
'''):
    hash_short = row['block_hash'][:16] + '...' if row['block_hash'] else 'None'
    total_files = row['files_processed'] + row['files_skipped'] + row['files_errored']
    raw_kb = (row['bytes_scanned'] or 0) / 1024
    stored_kb = (row['bytes_stored'] or 0) / 1024
    print(f"#{row['block_number']:2d} {row['phase']:18s} | {total_files:4d} files ({row['files_errored']} err) | {raw_kb:8.1f} KB raw | {stored_kb:8.1f} KB stored | logs {row['log_id_start']}-{row['log_id_end']}")

print()
print("="*80)
print("SAMPLE LOG ENTRIES FROM AST PHASE")
print("="*80)
for row in conn.execute('''
    SELECT log_id, relpath, status, size_raw, size_stored 
    FROM ingest_log 
    WHERE phase = 'ast_generation' 
    ORDER BY log_id LIMIT 10
'''):
    size_raw = row['size_raw'] or 0
    size_stored = row['size_stored'] or 0
    relpath = row['relpath'][:55] if row['relpath'] else ''
    print(f"{row['log_id']:5d} | {row['status']:10s} | {size_raw:8d} raw | {size_stored:8d} stored | {relpath}")

conn.close()
