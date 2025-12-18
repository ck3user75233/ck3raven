#!/usr/bin/env python3
"""
Test Symbol Extraction on a small subset of files.
Validates the logic is correct before running on full database.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.db.schema import get_connection, DEFAULT_DB_PATH
from ck3raven.parser import parse_source
from ck3raven.db.symbols import extract_symbols_from_ast

def test_file(conn, relpath_pattern: str, max_files: int = 1):
    """Test symbol extraction on files matching pattern."""
    
    cursor = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash
        FROM files f
        WHERE f.deleted = 0
        AND f.relpath LIKE ?
        LIMIT ?
    """, (relpath_pattern, max_files))
    
    files = cursor.fetchall()
    
    for file_row in files:
        file_id = file_row['file_id']
        relpath = file_row['relpath']
        content_hash = file_row['content_hash']
        
        print(f"\n{'='*60}")
        print(f"FILE: {relpath}")
        print(f"{'='*60}")
        
        # Get content
        content_row = conn.execute(
            "SELECT COALESCE(content_text, content_blob) as content FROM file_contents WHERE content_hash = ?",
            (content_hash,)
        ).fetchone()
        
        if not content_row:
            print("  [NO CONTENT]")
            continue
        
        content_bytes = content_row['content']
        if isinstance(content_bytes, bytes):
            content = content_bytes.decode('utf-8', errors='replace')
        else:
            content = content_bytes
        
        # Strip BOM
        if content.startswith('\ufeff'):
            content = content[1:]
            print("  [Stripped BOM]")
        
        print(f"  Content size: {len(content)} bytes")
        print(f"  First 200 chars: {content[:200]!r}")
        
        # Parse
        try:
            ast = parse_source(content, filename=relpath)
            ast_dict = ast.to_dict() if hasattr(ast, 'to_dict') else {}
        except Exception as e:
            print(f"  [PARSE ERROR]: {e}")
            continue
        
        print(f"  Parse OK, {len(ast_dict.get('children', []))} top-level children")
        
        # Extract symbols
        try:
            symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
        except Exception as e:
            print(f"  [EXTRACTION ERROR]: {e}")
            continue
        
        print(f"  Extracted {len(symbols)} symbols:")
        for sym in symbols[:10]:  # Show first 10
            print(f"    - {sym.kind}: {sym.name}")
        if len(symbols) > 10:
            print(f"    ... and {len(symbols) - 10} more")


def main():
    conn = get_connection(DEFAULT_DB_PATH)
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    
    print("Testing symbol extraction on specific file types...")
    
    # Test 1: Vanilla traits (should have many trait symbols)
    print("\n" + "="*70)
    print("TEST 1: Vanilla traits file (common/traits/00_traits.txt)")
    print("="*70)
    test_file(conn, '%common/traits/00_traits.txt', 1)
    
    # Test 2: A decision file 
    print("\n" + "="*70)
    print("TEST 2: Decision file")
    print("="*70)
    test_file(conn, '%common/decisions/%', 1)
    
    # Test 3: Localization file (should have 0 symbols with current logic)
    print("\n" + "="*70)
    print("TEST 3: Localization file (should be skipped or have 0 symbols)")
    print("="*70)
    test_file(conn, '%localization/english/%', 1)
    
    # Test 4: History/titles file
    print("\n" + "="*70)
    print("TEST 4: History titles file")
    print("="*70)
    test_file(conn, '%history/titles/%', 1)
    
    # Test 5: Event file
    print("\n" + "="*70)
    print("TEST 5: Event file")
    print("="*70)
    test_file(conn, '%events/%', 1)
    
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
