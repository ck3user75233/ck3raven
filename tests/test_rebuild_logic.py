#!/usr/bin/env python3
"""
Test that mimics exactly what rebuild_database.py phase_symbol_extraction does.

This will help identify where the disconnect is.
"""

import sys
import sqlite3
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.parser import parse_source
from ck3raven.db.symbols import extract_symbols_from_ast

DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"


def test_rebuild_logic():
    """Replicate the exact logic from phase_symbol_extraction."""
    print("Testing rebuild_database.py phase_symbol_extraction logic")
    print("=" * 70)
    
    conn = sqlite3.connect(str(DB_PATH))
    
    # This is the EXACT query from rebuild_database.py
    cursor = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, fc.content_text
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.deleted = 0
        AND f.relpath LIKE '%.txt'
        AND fc.content_text IS NOT NULL
    """)
    
    total_symbols = 0
    processed = 0
    errors = 0
    batch_size = 100
    error_types = {}
    zero_symbol_files = []
    success_files = []
    
    print(f"\nProcessing first 200 files...")
    
    # Fetch first 200 to test
    rows = cursor.fetchmany(200)
    
    for file_id, relpath, content_hash, content in rows:
        try:
            ast = parse_source(content, relpath)
            # Convert AST node to dict for extract_symbols_from_ast
            ast_dict = ast.to_dict() if hasattr(ast, 'to_dict') else ast
            symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
            
            total_symbols += len(symbols)
            processed += 1
            
            if len(symbols) == 0:
                zero_symbol_files.append(relpath)
            else:
                success_files.append((relpath, len(symbols)))
                
        except Exception as e:
            errors += 1
            error_type = type(e).__name__
            error_types[error_type] = error_types.get(error_type, 0) + 1
            if errors <= 5:
                print(f"  Error in {relpath}: {error_type}: {str(e)[:80]}")
    
    print(f"\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Files processed successfully: {processed}")
    print(f"Parse errors: {errors}")
    print(f"Total symbols extracted: {total_symbols}")
    
    print(f"\nError breakdown:")
    for etype, count in sorted(error_types.items(), key=lambda x: -x[1]):
        print(f"  {etype}: {count}")
    
    print(f"\nFiles with 0 symbols: {len(zero_symbol_files)}")
    for f in zero_symbol_files[:10]:
        print(f"  - {f}")
    if len(zero_symbol_files) > 10:
        print(f"  ... and {len(zero_symbol_files) - 10} more")
    
    print(f"\nFiles with symbols (first 20):")
    for f, count in success_files[:20]:
        print(f"  {count:4d} symbols: {f}")
    
    conn.close()
    
    # Now test if the issue is in INSERT
    print("\n" + "=" * 70)
    print("TESTING INSERT LOGIC")
    print("=" * 70)
    
    # Get one file and try the exact insert logic
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, fc.content_text 
        FROM files f 
        JOIN file_contents fc ON f.content_hash = fc.content_hash 
        WHERE f.deleted = 0 
        AND f.relpath LIKE '%common/traits/00_traits.txt'
        LIMIT 1
    """).fetchone()
    
    if row:
        file_id, relpath, content_hash, content = row
        ast = parse_source(content, relpath)
        ast_dict = ast.to_dict()
        symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
        
        print(f"Testing INSERT with {len(symbols)} symbols from {relpath}")
        
        # Check symbols table structure
        schema = conn.execute("PRAGMA table_info(symbols)").fetchall()
        print(f"\nSymbols table schema:")
        for col in schema:
            print(f"  {col[1]} ({col[2]})")
        
        # Try the exact INSERT logic from rebuild
        inserted = 0
        insert_errors = 0
        for sym in symbols[:5]:  # Just test first 5
            try:
                # This is the EXACT insert from rebuild_database.py
                conn.execute("""
                    INSERT OR IGNORE INTO symbols 
                    (name, symbol_type, defining_file_id, line_number, metadata_json)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    sym.name if hasattr(sym, 'name') else sym['name'],
                    sym.kind if hasattr(sym, 'kind') else sym.get('symbol_type', 'unknown'),
                    file_id,
                    sym.line if hasattr(sym, 'line') else sym.get('line', 0),
                    json.dumps({'signature': getattr(sym, 'signature', None), 
                               'doc': getattr(sym, 'doc', None)} if hasattr(sym, 'signature') else sym.get('context', {}))
                ))
                inserted += 1
            except Exception as e:
                insert_errors += 1
                print(f"  INSERT error: {e}")
        
        conn.rollback()  # Don't actually modify the db
        print(f"\nInsert test: {inserted} succeeded, {insert_errors} failed")
    
    conn.close()
    return total_symbols > 0


if __name__ == "__main__":
    success = test_rebuild_logic()
    print("\n" + "=" * 70)
    if success:
        print("✓ TEST PASSED - Symbol extraction logic works correctly")
    else:
        print("✗ TEST FAILED - Something is wrong")
    sys.exit(0 if success else 1)
