#!/usr/bin/env python
"""Visual inspection of the database: ASTs, symbols, refs."""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("=" * 80)
    print("DATABASE VISUAL INSPECTION")
    print("=" * 80)

    # 1. Summary counts
    print("\n### SUMMARY COUNTS")
    print("-" * 40)
    for table in ['files', 'asts', 'symbols', 'refs', 'localization_entries']:
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            print(f"  {table:25} {row[0]:>10,}")
        except:
            pass

    # 2. ASTs
    print("\n### ASTs (10 most recent)")
    print("-" * 80)
    rows = conn.execute('''
        SELECT a.ast_id, a.file_id, f.relpath, a.parse_ok, a.node_count, 
               length(a.ast_blob) as blob_size
        FROM asts a
        LEFT JOIN files f ON a.file_id = f.file_id
        ORDER BY a.ast_id DESC
        LIMIT 10
    ''').fetchall()

    header = f"{'ID':>5} {'file_id':>8} {'ok':>3} {'nodes':>6} {'size':>8}  path"
    print(header)
    for r in rows:
        relpath = (r['relpath'] or 'unknown')[:45]
        print(f"{r['ast_id']:>5} {r['file_id'] or 0:>8} {r['parse_ok']:>3} {r['node_count'] or 0:>6} {r['blob_size']:>8}  {relpath}")

    # 3. Symbols
    print("\n### SYMBOLS (first 25)")
    print("-" * 80)
    rows = conn.execute('''
        SELECT s.symbol_id, s.name, s.symbol_type, s.line_number, f.relpath
        FROM symbols s
        JOIN files f ON s.file_id = f.file_id
        ORDER BY s.symbol_id
        LIMIT 25
    ''').fetchall()

    if rows:
        print(f"{'ID':>6} {'type':20} {'line':>5}  name")
        for r in rows:
            print(f"{r['symbol_id']:>6} {r['symbol_type']:20} {r['line_number'] or 0:>5}  {r['name']}")
    else:
        print("(no symbols extracted yet)")

    # 4. Refs
    print("\n### REFS (first 25)")
    print("-" * 80)
    rows = conn.execute('''
        SELECT r.ref_id, r.name, r.ref_type, r.line_number, f.relpath
        FROM refs r
        JOIN files f ON r.file_id = f.file_id
        ORDER BY r.ref_id
        LIMIT 25
    ''').fetchall()

    if rows:
        print(f"{'ID':>6} {'type':20} {'line':>5}  name")
        for r in rows:
            print(f"{r['ref_id']:>6} {r['ref_type']:20} {r['line_number'] or 0:>5}  {r['name']}")
    else:
        print("(no refs extracted yet)")

    # 5. Sample AST content - DETAILED
    print("\n### DETAILED AST STRUCTURE (first AST, first 5 blocks)")
    print("-" * 80)
    row = conn.execute('''
        SELECT a.ast_blob, f.relpath 
        FROM asts a
        JOIN files f ON a.file_id = f.file_id
        LIMIT 1
    ''').fetchone()
    
    if row:
        print(f"File: {row['relpath']}")
        print()
        ast = json.loads(row['ast_blob'])
        
        # Show top-level structure
        print(f"Root type: {ast.get('_type')}")
        print(f"Children: {len(ast.get('children', []))}")
        print()
        
        # Show first few blocks in detail
        for i, child in enumerate(ast.get('children', [])[:1]):
            print(f"--- Top-level block: {child.get('name', 'unnamed')} ---")
            print(f"  Type: {child.get('_type')}")
            print(f"  Line: {child.get('line')}")
            print(f"  Children: {len(child.get('children', []))}")
            
            # Show first few children of this block
            for j, subchild in enumerate(child.get('children', [])[:8]):
                sub_type = subchild.get('_type')
                if sub_type == 'block':
                    print(f"    [{j}] block: {subchild.get('name')} ({len(subchild.get('children', []))} children)")
                elif sub_type == 'assignment':
                    val = subchild.get('value', {})
                    val_str = val.get('value', '') if isinstance(val, dict) else str(val)
                    if len(str(val_str)) > 30:
                        val_str = str(val_str)[:30] + "..."
                    print(f"    [{j}] {subchild.get('key')} = {val_str}")
                else:
                    print(f"    [{j}] {sub_type}")
            
            if len(child.get('children', [])) > 8:
                print(f"    ... and {len(child.get('children', [])) - 8} more")
    else:
        print("(no ASTs yet)")

    # 6. Build queue sample
    print("\n### BUILD QUEUE (10 recent completed)")
    print("-" * 80)
    rows = conn.execute('''
        SELECT b.build_id, b.envelope, b.status, f.relpath
        FROM build_queue b
        JOIN files f ON b.file_id = f.file_id
        WHERE b.status = 'completed'
        ORDER BY b.completed_at DESC
        LIMIT 10
    ''').fetchall()
    
    if rows:
        print(f"{'build_id':>10} {'envelope':12} {'status':12} path")
        for r in rows:
            relpath = r['relpath'][:45] if len(r['relpath']) > 45 else r['relpath']
            print(f"{r['build_id']:>10} {r['envelope']:12} {r['status']:12} {relpath}")
    else:
        print("(no completed builds)")

    conn.close()
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
