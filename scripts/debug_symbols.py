#!/usr/bin/env python3
"""Debug symbol extraction."""

import sqlite3
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.parser import parse_source
from ck3raven.db.symbols import extract_symbols_from_ast

DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"
conn = sqlite3.connect(str(DB_PATH))

# Get sample files
query = """
    SELECT f.file_id, f.relpath, fc.content_text
    FROM files f
    JOIN file_contents fc ON f.content_hash = fc.content_hash
    WHERE f.deleted = 0
    AND f.relpath LIKE '%.txt'
    AND fc.content_text IS NOT NULL
    LIMIT 20
"""

cursor = conn.execute(query)
rows = cursor.fetchall()

print(f"Got {len(rows)} files")

for file_id, relpath, content in rows:
    try:
        ast = parse_source(content, relpath)
        syms = extract_symbols_from_ast(ast, relpath)
        print(f"OK: {relpath} -> {len(syms)} symbols")
    except Exception as e:
        print(f"ERR: {relpath} -> {e}")
