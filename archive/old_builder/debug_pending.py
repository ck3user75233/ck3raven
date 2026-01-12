#!/usr/bin/env python3
"""Debug script to check pending work."""
import sqlite3
from pathlib import Path

conn = sqlite3.connect(str(Path.home() / '.ck3raven' / 'ck3raven.db'))
conn.row_factory = sqlite3.Row

# Check how many rows the SQL query returns
count = conn.execute("""
    SELECT COUNT(*) as c
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
      AND (a.ast_id IS NULL OR s.symbol_id IS NULL OR r.ref_id IS NULL)
""").fetchone()["c"]
print(f'SQL query returns {count} rows')

# Check how many actually pass routing
from builder.routing import get_processing_envelope, ProcessingStage

rows = conn.execute("""
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
      AND (a.ast_id IS NULL OR s.symbol_id IS NULL OR r.ref_id IS NULL)
    ORDER BY f.file_id
    LIMIT 100
""").fetchall()

skipped_routing = 0
skipped_no_work = 0
yielded = 0

for row in rows:
    env = get_processing_envelope(row["relpath"])
    if env is None:
        skipped_routing += 1
        continue
    
    expected_stages = env.stages
    needs_parse = False
    needs_symbols = False
    needs_refs = False
    
    if ProcessingStage.PARSE in expected_stages:
        needs_parse = bool(row["needs_ast"])
    
    if ProcessingStage.SYMBOLS in expected_stages:
        needs_symbols = bool(row["needs_symbols"]) and not bool(row["needs_ast"])
    
    if ProcessingStage.REFS in expected_stages:
        needs_refs = bool(row["needs_refs"]) and not bool(row["needs_ast"])
    
    if not any([needs_parse, needs_symbols, needs_refs]):
        skipped_no_work += 1
        if skipped_no_work <= 5:
            print(f'No work needed: {row["relpath"][:60]}')
            print(f'  needs_ast={row["needs_ast"]}, needs_sym={row["needs_symbols"]}, needs_ref={row["needs_refs"]}')
            print(f'  PARSE in stages={ProcessingStage.PARSE in expected_stages}')
        continue
    
    yielded += 1

print(f'\nOf first 100 rows:')
print(f'  Skipped (routing): {skipped_routing}')
print(f'  Skipped (no work): {skipped_no_work}')
print(f'  Yielded: {yielded}')



