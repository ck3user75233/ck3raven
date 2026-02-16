#!/usr/bin/env python
"""Check database schema status."""
import sqlite3
from pathlib import Path

db_path = Path.home() / '.ck3raven' / 'ck3raven.db'
print(f'DB exists: {db_path.exists()}')
print(f'DB size: {db_path.stat().st_size if db_path.exists() else 0} bytes')

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Check schema version
try:
    row = conn.execute("SELECT value FROM db_metadata WHERE key = 'schema_version'").fetchone()
    print(f'Schema version: {row["value"] if row else "NOT SET"}')
except Exception as e:
    print(f'Schema version: ERROR - {e}')

# List all tables
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print(f'\nTables ({len(tables)}):')
for t in tables:
    print(f'  - {t["name"]}')

# Check key table counts
for table in ['files', 'content_versions']:
    try:
        row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
        print(f'{table}: {row["cnt"]}')
    except Exception as e:
        print(f'{table}: ERROR - {e}')
