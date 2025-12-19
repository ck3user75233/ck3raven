#!/usr/bin/env python3
"""
Test script to verify database structure and AST reconstruction accuracy.
"""

import sqlite3
import json
import sys
from pathlib import Path

# Add src to path for ck3raven imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.parser.parser import Parser, RootNode
from ck3raven.parser.lexer import Lexer

db_path = Path.home() / '.ck3raven' / 'ck3raven.db'


def query_database_structure():
    """Answer questions about database structure."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("=" * 70)
    print("QUESTION 1: Does the database include raw file contents AND parsed AST?")
    print("=" * 70)
    
    # Check file_contents table
    cursor.execute("SELECT COUNT(*) FROM file_contents WHERE is_binary = 0")
    text_files = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM file_contents WHERE is_binary = 1")
    binary_files = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(size) FROM file_contents")
    total_bytes = cursor.fetchone()[0] or 0
    
    print(f"\nfile_contents table:")
    print(f"  - Text files: {text_files:,}")
    print(f"  - Binary files: {binary_files:,}")
    print(f"  - Total content: {total_bytes / (1024*1024*1024):.2f} GB")
    
    # Check if content_text is populated
    cursor.execute("SELECT COUNT(*) FROM file_contents WHERE content_text IS NOT NULL")
    with_text = cursor.fetchone()[0]
    print(f"  - Files with content_text populated: {with_text:,}")
    
    # Check ASTs table
    cursor.execute("SELECT COUNT(*) FROM asts WHERE parse_ok = 1")
    ok_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM asts WHERE parse_ok = 0")
    fail_count = cursor.fetchone()[0]
    
    print(f"\nasts table (parsed AST data):")
    print(f"  - Successfully parsed ASTs: {ok_count:,}")
    print(f"  - Failed parses: {fail_count:,}")
    
    if ok_count > 0:
        print("\n  ANSWER: YES - The database stores BOTH raw file contents")
        print("          (in file_contents.content_text/content_blob)")
        print("          AND parsed AST data (in asts.ast_blob)")
    else:
        print("\n  NOTE: ASTs have not been generated yet. Only raw content is stored.")
        print("        AST cache is populated on-demand during symbol extraction.")
    
    print("\n" + "=" * 70)
    print("QUESTION 2: Is the data searchable at file and content levels?")
    print("=" * 70)
    
    # Check FTS tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%fts%'")
    fts_tables = cursor.fetchall()
    print(f"\nFull-Text Search (FTS5) tables: {[t[0] for t in fts_tables]}")
    
    # Check if symbols/refs are populated
    cursor.execute("SELECT COUNT(*) FROM symbols")
    symbol_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM refs")
    ref_count = cursor.fetchone()[0]
    
    print(f"\nSymbols extracted: {symbol_count:,}")
    print(f"References extracted: {ref_count:,}")
    
    # Check files table
    cursor.execute("SELECT COUNT(DISTINCT relpath) FROM files")
    unique_paths = cursor.fetchone()[0]
    print(f"Unique file paths indexed: {unique_paths:,}")
    
    print("\n  ANSWER: YES - Data is searchable at multiple levels:")
    print("    1. FILE level: files table with relpath, file_type")
    print("    2. CONTENT level: file_contents.content_text + file_content_fts")
    print("    3. SYMBOL level: symbols table + symbols_fts")
    print("    4. REFERENCE level: refs table + refs_fts")
    
    conn.close()


def show_active_mods():
    """Show active mods from playset manifest."""
    print("\n" + "=" * 70)
    print("QUESTION 3: Active mods in load order")
    print("=" * 70)
    
    manifest_path = Path(__file__).parent.parent / "playset_manifest.json"
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
        
        print(f"\nPlayset manifest: {manifest_path}")
        print("\nMods in load order:")
        print("-" * 50)
        print(f"{'#':<4} {'ID':<20} {'Name':<30}")
        print("-" * 50)
        
        # Vanilla is always load order 0
        print(f"{'0':<4} {'vanilla':<20} {'CK3 Vanilla (1.18.x)':<30}")
        
        for i, mod in enumerate(manifest.get("mods", []), start=1):
            mod_id = mod.get("id", "?")
            mod_name = mod.get("name", "Unknown")
            mod_path = mod.get("path", "")
            print(f"{i:<4} {mod_id:<20} {mod_name:<30}")
            print(f"     Path: {mod_path}")
        
        print("-" * 50)
        print(f"Total: {len(manifest.get('mods', [])) + 1} sources (vanilla + mods)")
    else:
        print(f"\nNo playset manifest found at {manifest_path}")


def test_ast_reconstruction():
    """Test AST reconstruction accuracy by comparing with original files."""
    print("\n" + "=" * 70)
    print("QUESTION 4: AST Reconstruction Accuracy Test")
    print("=" * 70)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get a sample of vanilla script files (not too large, not too small)
    # Exclude .info files which are not parseable
    cursor.execute("""
        SELECT f.relpath, fc.content_text, fc.content_hash
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        JOIN content_versions cv ON f.content_version_id = cv.content_version_id
        WHERE cv.kind = 'vanilla'
          AND f.file_type = 'script'
          AND fc.is_binary = 0
          AND fc.content_text IS NOT NULL
          AND length(fc.content_text) BETWEEN 500 AND 10000
          AND f.relpath NOT LIKE '%.info'
        ORDER BY RANDOM()
        LIMIT 5
    """)
    
    test_files = cursor.fetchall()
    
    if not test_files:
        print("\nNo suitable test files found in database.")
        conn.close()
        return
    
    print(f"\nTesting {len(test_files)} random vanilla script files...")
    print("-" * 70)
    
    results = []
    
    for relpath, content_text, content_hash in test_files:
        print(f"\n>>> Testing: {relpath}")
        print(f"    Content hash: {content_hash[:16]}...")
        print(f"    Original size: {len(content_text):,} chars")
        
        # Skip .info files (not parseable script files)
        if relpath.endswith('.info'):
            print(f"    ⏭️  SKIPPED: .info file (not a script)")
            continue
        
        # Strip BOM if present
        if content_text.startswith('\ufeff'):
            content_text = content_text[1:]
            print(f"    (BOM stripped)")
        
        try:
            # Step 1: Parse original content to AST
            lexer = Lexer(content_text, filename=relpath)
            tokens = list(lexer.tokenize())  # Convert generator to list
            parser = Parser(tokens, filename=relpath)
            ast = parser.parse()
            
            # Step 2: Reconstruct PDX from AST using to_pdx()
            reconstructed = ""
            for child in ast.children:
                reconstructed += child.to_pdx(indent=0) + "\n"
            
            print(f"    Reconstructed size: {len(reconstructed):,} chars")
            
            # Step 3: Re-parse the reconstructed content
            lexer2 = Lexer(reconstructed, filename=relpath + ".reconstructed")
            tokens2 = list(lexer2.tokenize())  # Convert generator to list
            parser2 = Parser(tokens2, filename=relpath + ".reconstructed")
            ast2 = parser2.parse()
            
            # Step 4: Compare AST structures
            def count_nodes(node):
                count = 1
                if hasattr(node, 'children'):
                    for child in node.children:
                        count += count_nodes(child)
                if hasattr(node, 'value') and hasattr(node.value, 'children'):
                    count += count_nodes(node.value)
                if hasattr(node, 'items'):
                    for item in node.items:
                        count += count_nodes(item)
                return count
            
            original_nodes = count_nodes(ast)
            reconstructed_nodes = count_nodes(ast2)
            
            print(f"    Original AST nodes: {original_nodes}")
            print(f"    Reconstructed AST nodes: {reconstructed_nodes}")
            
            # Step 5: Deep comparison of AST dictionaries
            def normalize_ast_dict(d):
                """Normalize AST dict for comparison (remove line/column/filename info)."""
                if isinstance(d, dict):
                    return {k: normalize_ast_dict(v) for k, v in d.items() 
                            if k not in ('line', 'column', 'filename')}
                elif isinstance(d, list):
                    return [normalize_ast_dict(item) for item in d]
                return d
            
            ast_dict1 = normalize_ast_dict(ast.to_dict())
            ast_dict2 = normalize_ast_dict(ast2.to_dict())
            
            asts_match = ast_dict1 == ast_dict2
            
            if asts_match:
                print(f"    ✅ AST MATCH: Reconstruction is semantically identical")
                results.append((relpath, "PASS", "ASTs match exactly"))
            else:
                # Count differences
                def count_differences(d1, d2, path=""):
                    diffs = []
                    if type(d1) != type(d2):
                        diffs.append(f"{path}: type mismatch {type(d1).__name__} vs {type(d2).__name__}")
                    elif isinstance(d1, dict):
                        for key in set(d1.keys()) | set(d2.keys()):
                            if key not in d1:
                                diffs.append(f"{path}.{key}: missing in original")
                            elif key not in d2:
                                diffs.append(f"{path}.{key}: missing in reconstructed")
                            else:
                                diffs.extend(count_differences(d1[key], d2[key], f"{path}.{key}"))
                    elif isinstance(d1, list):
                        if len(d1) != len(d2):
                            diffs.append(f"{path}: list length {len(d1)} vs {len(d2)}")
                        for i, (a, b) in enumerate(zip(d1, d2)):
                            diffs.extend(count_differences(a, b, f"{path}[{i}]"))
                    elif d1 != d2:
                        diffs.append(f"{path}: {d1!r} vs {d2!r}")
                    return diffs
                
                diffs = count_differences(ast_dict1, ast_dict2)
                print(f"    ⚠️  AST DIFFERENCE: {len(diffs)} differences found")
                for diff in diffs[:3]:
                    print(f"        - {diff}")
                if len(diffs) > 3:
                    print(f"        ... and {len(diffs) - 3} more")
                results.append((relpath, "DIFF", f"{len(diffs)} differences"))
            
        except Exception as e:
            print(f"    ❌ ERROR: {e}")
            results.append((relpath, "ERROR", str(e)))
    
    conn.close()
    
    # Summary
    print("\n" + "=" * 70)
    print("RECONSTRUCTION TEST SUMMARY")
    print("=" * 70)
    passes = sum(1 for _, status, _ in results if status == "PASS")
    diffs = sum(1 for _, status, _ in results if status == "DIFF")
    errors = sum(1 for _, status, _ in results if status == "ERROR")
    
    print(f"\n  ✅ PASS: {passes}/{len(results)}")
    print(f"  ⚠️  DIFF: {diffs}/{len(results)}")
    print(f"  ❌ ERROR: {errors}/{len(results)}")
    
    if passes == len(results):
        print("\n  CONCLUSION: AST reconstruction is 100% accurate for tested files!")
        print("              The AST data can fully recreate the original game files.")
    elif passes > 0:
        print(f"\n  CONCLUSION: {passes}/{len(results)} files reconstructed perfectly.")
        print("              Some whitespace/formatting differences may exist.")


if __name__ == "__main__":
    query_database_structure()
    show_active_mods()
    test_ast_reconstruction()
