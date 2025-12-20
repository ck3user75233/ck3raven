#!/usr/bin/env python3
"""
Database Content Integrity Tests

Verifies:
1. Raw file contents are stored correctly in database
2. AST parsing works on stored content
3. Symbol extraction works on parsed AST
"""

import sys
import sqlite3
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.parser import parse_source
from ck3raven.db.symbols import extract_symbols_from_ast

DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"


def test_database_exists():
    """Test 1: Database file exists"""
    print(f"Test 1: Database exists at {DB_PATH}")
    assert DB_PATH.exists(), f"Database not found at {DB_PATH}"
    print("  [PASS] Database file exists")
    return True


def test_file_contents_table():
    """Test 2: file_contents table has data"""
    print("\nTest 2: file_contents table structure and data")
    conn = sqlite3.connect(str(DB_PATH))
    
    # Check table exists
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='file_contents'"
    ).fetchone()
    assert tables, "file_contents table doesn't exist"
    print("  [PASS] file_contents table exists")
    
    # Check row count
    count = conn.execute("SELECT COUNT(*) FROM file_contents").fetchone()[0]
    print(f"  Total rows in file_contents: {count}")
    assert count > 0, "file_contents table is empty"
    print("  [PASS] file_contents has data")
    
    # Check content_text is populated
    with_content = conn.execute(
        "SELECT COUNT(*) FROM file_contents WHERE content_text IS NOT NULL"
    ).fetchone()[0]
    print(f"  Rows with content_text: {with_content}")
    assert with_content > 0, "No rows have content_text"
    print("  [PASS] content_text is populated")
    
    conn.close()
    return True


def test_files_table():
    """Test 3: files table has data and links to content"""
    print("\nTest 3: files table structure and joins")
    conn = sqlite3.connect(str(DB_PATH))
    
    # Check files count
    files_count = conn.execute("SELECT COUNT(*) FROM files WHERE deleted = 0").fetchone()[0]
    print(f"  Non-deleted files: {files_count}")
    assert files_count > 0, "No files in database"
    
    # Check txt files with content
    txt_with_content = conn.execute("""
        SELECT COUNT(*) FROM files f 
        JOIN file_contents fc ON f.content_hash = fc.content_hash 
        WHERE f.deleted = 0 
        AND f.relpath LIKE '%.txt'
        AND fc.content_text IS NOT NULL
    """).fetchone()[0]
    print(f"  TXT files with content: {txt_with_content}")
    assert txt_with_content > 0, "No txt files have content"
    print("  [PASS] files table has txt files with content")
    
    conn.close()
    return True


def test_sample_file_content_integrity():
    """Test 4: Sample a known file and verify content looks correct"""
    print("\nTest 4: Sample file content integrity")
    conn = sqlite3.connect(str(DB_PATH))
    
    # Get a traits file (we know this should have symbols)
    row = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, fc.content_text 
        FROM files f 
        JOIN file_contents fc ON f.content_hash = fc.content_hash 
        WHERE f.deleted = 0 
        AND f.relpath LIKE '%common/traits/00_traits.txt'
        AND fc.content_text IS NOT NULL
        LIMIT 1
    """).fetchone()
    
    if not row:
        # Try any traits file
        row = conn.execute("""
            SELECT f.file_id, f.relpath, f.content_hash, fc.content_text 
            FROM files f 
            JOIN file_contents fc ON f.content_hash = fc.content_hash 
            WHERE f.deleted = 0 
            AND f.relpath LIKE '%common/traits%'
            AND fc.content_text IS NOT NULL
            LIMIT 1
        """).fetchone()
    
    assert row, "No traits file found in database"
    
    file_id, relpath, content_hash, content = row
    print(f"  Testing file: {relpath}")
    print(f"  File ID: {file_id}")
    print(f"  Content hash: {content_hash[:16]}...")
    print(f"  Content length: {len(content)} chars")
    
    # Verify content looks like CK3 script
    assert len(content) > 100, "Content too short"
    print("  [PASS] Content length is reasonable")
    
    # Check for expected CK3 patterns
    has_equals = '=' in content
    has_braces = '{' in content and '}' in content
    print(f"  Has '=' signs: {has_equals}")
    print(f"  Has braces: {has_braces}")
    assert has_equals and has_braces, "Content doesn't look like CK3 script"
    print("  [PASS] Content looks like valid CK3 script")
    
    conn.close()
    return row  # Return for use in next test


def test_ast_parsing(sample_row):
    """Test 5: Parse the sample file to AST"""
    print("\nTest 5: AST parsing")
    
    file_id, relpath, content_hash, content = sample_row
    print(f"  Parsing: {relpath}")
    
    try:
        ast = parse_source(content, relpath)
        print("  [PASS] Parsing succeeded")
    except Exception as e:
        print(f"  [FAIL] Parsing failed: {type(e).__name__}: {e}")
        return None
    
    # Check AST structure
    print(f"  AST type: {type(ast).__name__}")
    assert hasattr(ast, 'to_dict'), "AST doesn't have to_dict method"
    print("  [PASS] AST has to_dict method")
    
    return ast, content_hash, relpath


def test_ast_to_dict(ast_result):
    """Test 6: Convert AST to dict"""
    print("\nTest 6: AST to_dict conversion")
    
    ast, content_hash, relpath = ast_result
    
    try:
        ast_dict = ast.to_dict()
        print("  [PASS] to_dict() succeeded")
    except Exception as e:
        print(f"  [FAIL] to_dict() failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    # Check dict structure
    print(f"  Dict type: {type(ast_dict)}")
    assert isinstance(ast_dict, dict), "to_dict() didn't return a dict"
    print("  [PASS] Returns a dict")
    
    children = ast_dict.get('children', [])
    print(f"  Number of children: {len(children)}")
    assert len(children) > 0, "AST has no children"
    print("  [PASS] AST has children")
    
    # Show first few children
    print(f"\n  First 3 children:")
    for i, child in enumerate(children[:3]):
        child_type = child.get('_type', 'unknown')
        child_name = child.get('_name') or child.get('name') or child.get('key', '?')
        print(f"    [{i}] type={child_type}, name={child_name}")
    
    return ast_dict, content_hash, relpath


def test_symbol_extraction(dict_result):
    """Test 7: Extract symbols from AST dict"""
    print("\nTest 7: Symbol extraction")
    
    ast_dict, content_hash, relpath = dict_result
    
    try:
        symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
        print(f"  [PASS] Extraction succeeded")
    except Exception as e:
        print(f"  [FAIL] Extraction failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    print(f"  Symbols extracted: {len(symbols)}")
    assert len(symbols) > 0, "No symbols extracted"
    print("  [PASS] Got symbols")
    
    # Show first few symbols
    print(f"\n  First 5 symbols:")
    for sym in symbols[:5]:
        print(f"    {sym.kind}: {sym.name} at line {sym.line}")
    
    return symbols


def test_database_insert_format(symbols):
    """Test 8: Verify symbols can be inserted into database"""
    print("\nTest 8: Database insert format")
    
    # Check each symbol has required fields
    for i, sym in enumerate(symbols[:10]):
        assert hasattr(sym, 'name'), f"Symbol {i} missing 'name'"
        assert hasattr(sym, 'kind'), f"Symbol {i} missing 'kind'"
        assert hasattr(sym, 'line'), f"Symbol {i} missing 'line'"
        assert isinstance(sym.name, str), f"Symbol {i} name is not str: {type(sym.name)}"
        assert isinstance(sym.kind, str), f"Symbol {i} kind is not str: {type(sym.kind)}"
    
    print("  [PASS] All symbols have required fields")
    print("  [PASS] Field types are correct")
    return True


def run_all_tests():
    """Run all tests in sequence"""
    print("=" * 70)
    print("DATABASE CONTENT INTEGRITY TESTS")
    print("=" * 70)
    
    results = {}
    
    # Test 1: Database exists
    try:
        results['db_exists'] = test_database_exists()
    except AssertionError as e:
        print(f"  [FAIL]: {e}")
        results['db_exists'] = False
        return results
    
    # Test 2: file_contents table
    try:
        results['file_contents'] = test_file_contents_table()
    except AssertionError as e:
        print(f"  [FAIL]: {e}")
        results['file_contents'] = False
        return results
    
    # Test 3: files table
    try:
        results['files_table'] = test_files_table()
    except AssertionError as e:
        print(f"  [FAIL]: {e}")
        results['files_table'] = False
        return results
    
    # Test 4: Sample content integrity
    try:
        sample_row = test_sample_file_content_integrity()
        results['content_integrity'] = True
    except AssertionError as e:
        print(f"  [FAIL]: {e}")
        results['content_integrity'] = False
        return results
    
    # Test 5: AST parsing
    try:
        ast_result = test_ast_parsing(sample_row)
        results['ast_parsing'] = ast_result is not None
    except Exception as e:
        print(f"  [FAIL]: {e}")
        results['ast_parsing'] = False
        return results
    
    if not ast_result:
        return results
    
    # Test 6: AST to_dict
    try:
        dict_result = test_ast_to_dict(ast_result)
        results['ast_to_dict'] = dict_result is not None
    except Exception as e:
        print(f"  [FAIL]: {e}")
        results['ast_to_dict'] = False
        return results
    
    if not dict_result:
        return results
    
    # Test 7: Symbol extraction
    try:
        symbols = test_symbol_extraction(dict_result)
        results['symbol_extraction'] = symbols is not None
    except Exception as e:
        print(f"  [FAIL]: {e}")
        results['symbol_extraction'] = False
        return results
    
    if not symbols:
        return results
    
    # Test 8: Insert format
    try:
        results['insert_format'] = test_database_insert_format(symbols)
    except AssertionError as e:
        print(f"  [FAIL]: {e}")
        results['insert_format'] = False
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    for name, result in results.items():
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status}: {name}")
    
    return results


if __name__ == "__main__":
    results = run_all_tests()
    sys.exit(0 if all(results.values()) else 1)
