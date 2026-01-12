#!/usr/bin/env python3
"""Check log entries and blocks after test."""
import sqlite3
from pathlib import Path

db_path = Path.home() / '.ck3raven' / 'test_block_logging.db'
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

# Count log entries by phase
print('Log entries by phase:')
for row in conn.execute('''
    SELECT phase, COUNT(*) as cnt, COUNT(DISTINCT build_id) as builds
    FROM ingest_log
    GROUP BY phase
    ORDER BY phase
''').fetchall():
    print(f"  {row['phase']}: {row['cnt']} entries across {row['builds']} build(s)")

# Count blocks by phase  
print('\nBlocks by phase:')
for row in conn.execute('''
    SELECT phase, COUNT(*) as cnt
    FROM ingest_blocks
    GROUP BY phase
    ORDER BY phase
''').fetchall():
    print(f"  {row['phase']}: {row['cnt']} blocks")

# Total stats
total_logs = conn.execute('SELECT COUNT(*) FROM ingest_log').fetchone()[0]
total_blocks = conn.execute('SELECT COUNT(*) FROM ingest_blocks').fetchone()[0]
print(f'\nTotals: {total_logs} log entries, {total_blocks} blocks')

conn.close()
