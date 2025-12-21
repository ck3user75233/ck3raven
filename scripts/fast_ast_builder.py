#!/usr/bin/env python3
"""
Fast AST builder using keyset pagination instead of OFFSET.
This avoids the O(n²) scanning problem with OFFSET.
"""

import sys
import os
import sqlite3
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import orjson
    def json_dumps(obj):
        return orjson.dumps(obj)
    USE_ORJSON = True
except ImportError:
    import json
    def json_dumps(obj):
        return json.dumps(obj, separators=(',', ':')).encode('utf-8')
    USE_ORJSON = False

DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"

SKIP_PATTERNS = [
    'gfx/', '/fonts/', '/licenses/', '/sounds/', '/music/',
    '#backup/', '/generated/',
    'guids.txt', 'credits.txt', 'readme', 'changelog',
    'common/ethnicities/', 'common/dna_data/', 'common/coat_of_arms/',
    'history/characters/',
    'moreculturalnames', 'cultural_names_l_',
    '/names/character_names', '_names_l_',
]

def should_skip(relpath: str) -> bool:
    lower = relpath.lower()
    return any(p in lower for p in SKIP_PATTERNS)

def get_parser_version(conn) -> int:
    row = conn.execute("SELECT parser_version_id FROM parsers WHERE version_string = '0.1.0'").fetchone()
    if row:
        return row[0]
    conn.execute("INSERT INTO parsers (version_string) VALUES ('0.1.0')")
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

def main():
    print(f"[INFO] Fast AST builder with keyset pagination", flush=True)
    print(f"[INFO] orjson: {USE_ORJSON}", flush=True)
    
    from ck3raven.parser import parse_source
    
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")  # 64MB
    
    parser_version_id = get_parser_version(conn)
    print(f"[INFO] Parser version: {parser_version_id}", flush=True)
    
    # Count remaining (this is O(n) but only once)
    total = conn.execute("""
        SELECT COUNT(*)
        FROM file_contents fc
        WHERE NOT EXISTS (
            SELECT 1 FROM asts a 
            WHERE a.content_hash = fc.content_hash 
            AND a.parser_version_id = ?
        )
        AND fc.content_text IS NOT NULL
        AND LENGTH(fc.content_text) < 5000000
    """, (parser_version_id,)).fetchone()[0]
    
    print(f"[INFO] Need to process: {total}", flush=True)
    
    if total == 0:
        print("[INFO] All done!", flush=True)
        return
    
    start_time = time.time()
    processed = 0
    errors = 0
    skipped = 0
    batch_size = 500
    
    results_buffer = []
    errors_buffer = []
    
    # Use keyset pagination - get all content hashes that need processing
    # Then process in order by content_hash (which is already indexed)
    last_hash = ""
    
    while True:
        # Keyset pagination: WHERE content_hash > last_hash ORDER BY content_hash LIMIT N
        # This is O(1) per query instead of O(offset)
        rows = conn.execute("""
            SELECT fc.content_hash, fc.content_text, 
                   (SELECT f.relpath FROM files f WHERE f.content_hash = fc.content_hash LIMIT 1) as relpath
            FROM file_contents fc
            WHERE fc.content_hash > ?
            AND NOT EXISTS (
                SELECT 1 FROM asts a 
                WHERE a.content_hash = fc.content_hash 
                AND a.parser_version_id = ?
            )
            AND fc.content_text IS NOT NULL
            AND LENGTH(fc.content_text) < 5000000
            ORDER BY fc.content_hash
            LIMIT ?
        """, (last_hash, parser_version_id, batch_size)).fetchall()
        
        if not rows:
            break
        
        last_hash = rows[-1][0]  # Remember last hash for next query
        
        for content_hash, content, relpath in rows:
            if not relpath:
                skipped += 1
                continue
                
            if should_skip(relpath):
                skipped += 1
                continue
            
            if not content or len(content) > 2_000_000:
                skipped += 1
                continue
            
            try:
                ast = parse_source(content, relpath)
                if ast:
                    ast_dict = ast.to_dict() if hasattr(ast, 'to_dict') else ast
                    ast_json = json_dumps(ast_dict)
                    node_count = ast_json.count(b'{') if isinstance(ast_json, bytes) else ast_json.count('{')
                    results_buffer.append((content_hash, parser_version_id, ast_json, 'json', 1, node_count))
                else:
                    errors_buffer.append((content_hash, parser_version_id, b'null', 'json', 0, '{"error":"None"}'))
                processed += 1
            except Exception as e:
                errors += 1
                errors_buffer.append((content_hash, parser_version_id, b'null', 'json', 0, f'{{"error":"{str(e)[:100]}"}}'))
        
        # Batch insert
        if results_buffer:
            conn.executemany("""
                INSERT OR REPLACE INTO asts 
                (content_hash, parser_version_id, ast_blob, ast_format, parse_ok, node_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, results_buffer)
            results_buffer.clear()
        
        if errors_buffer:
            conn.executemany("""
                INSERT OR REPLACE INTO asts 
                (content_hash, parser_version_id, ast_blob, ast_format, parse_ok, diagnostics_json)
                VALUES (?, ?, ?, ?, ?, ?)
            """, errors_buffer)
            errors_buffer.clear()
        
        conn.commit()
        
        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        done_count = processed + skipped + errors
        pct = min(100, done_count / total * 100) if total > 0 else 100
        eta = (total - done_count) / rate / 60 if rate > 0 else 0
        
        print(f"[PROGRESS] {done_count}/{total} ({pct:.1f}%) | {rate:.0f}/s | ETA: {eta:.1f}m | Err: {errors} Skip: {skipped}", flush=True)
    
    total_time = time.time() - start_time
    print(f"[DONE] {processed} ASTs in {total_time:.1f}s ({processed/total_time:.0f}/s)", flush=True)
    conn.close()

if __name__ == "__main__":
    main()
