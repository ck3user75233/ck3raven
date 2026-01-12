#!/usr/bin/env python
"""Dump complete database schema."""
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"

conn = sqlite3.connect(DB_PATH)

# Get all tables
tables = conn.execute("""
    SELECT name FROM sqlite_master 
    WHERE type='table' AND name NOT LIKE 'sqlite_%'
    ORDER BY name
""").fetchall()

print("=" * 80)
print("COMPLETE DATABASE SCHEMA")
print(f"Database: {DB_PATH}")
print(f"Total tables: {len(tables)}")
print("=" * 80)
print()

for (table_name,) in tables:
    print(f"### {table_name}")
    print()
    
    # Get table schema
    schema = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    
    print(f"| {'Column':<30} | {'Type':<15} | {'Constraints':<30} |")
    print(f"|{'-'*32}|{'-'*17}|{'-'*32}|")
    
    for col in schema:
        cid, name, dtype, notnull, default, pk = col
        flags = []
        if pk: flags.append("PRIMARY KEY")
        if notnull: flags.append("NOT NULL")
        if default is not None: flags.append(f"DEFAULT {default}")
        flag_str = ", ".join(flags) if flags else ""
        print(f"| {name:<30} | {dtype:<15} | {flag_str:<30} |")
    
    # Get row count
    count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    print()
    print(f"**Row count:** {count:,}")
    print()
    print()

conn.close()
