#!/usr/bin/env python3
"""Quick database health check."""
import sqlite3
import os

db_path = os.path.expanduser("~/.ck3raven/ck3raven.db")
print(f"Database: {db_path}")
print(f"Size: {os.path.getsize(db_path) / (1024*1024):.1f} MB")

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# List tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print(f"\nTables: {tables}")

# Count rows in each table
for table in tables:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        print(f"  {table}: {count:,} rows")
    except Exception as e:
        print(f"  {table}: ERROR - {e}")

# Check content table size
cur.execute("SELECT SUM(LENGTH(raw_text)) FROM content WHERE raw_text IS NOT NULL")
raw_size = cur.fetchone()[0] or 0
print(f"\nRaw text total: {raw_size / (1024*1024):.1f} MB")

cur.execute("SELECT SUM(LENGTH(parsed_ast)) FROM content WHERE parsed_ast IS NOT NULL")
ast_size = cur.fetchone()[0] or 0
print(f"Parsed AST total: {ast_size / (1024*1024):.1f} MB")

conn.close()
print("\nDatabase check complete.")
