#!/usr/bin/env python3
"""Interactive AST bloat diagnostic - parse block by block and show expansion."""

import sqlite3
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.parser.parser import parse_source

def get_problem_file(db_path: Path, file_id: int = None):
    """Get the worst bloat file or a specific one."""
    conn = sqlite3.connect(str(db_path))
    
    if file_id:
        row = conn.execute('''
            SELECT f.file_id, f.relpath, fc.content_text
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE f.file_id = ?
        ''', (file_id,)).fetchone()
    else:
        # Get the worst one (by AST/source ratio)
        row = conn.execute('''
            SELECT f.file_id, f.relpath, fc.content_text
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            JOIN asts a ON a.content_hash = fc.content_hash
            WHERE fc.content_text IS NOT NULL AND a.ast_blob IS NOT NULL
            ORDER BY LENGTH(a.ast_blob) * 1.0 / LENGTH(fc.content_text) DESC
            LIMIT 1
        ''').fetchone()
    
    conn.close()
    return row

def extract_top_level_blocks(content: str):
    """Extract top-level blocks from CK3 script content."""
    blocks = []
    current_block_start = None
    current_block_name = None
    brace_depth = 0
    i = 0
    lines = content.split('\n')
    
    for line_num, line in enumerate(lines):
        # Skip comments
        code = line.split('#')[0]
        
        # Look for block start: name = {
        if brace_depth == 0 and '=' in code and '{' in code:
            # This starts a new top-level block
            name_part = code.split('=')[0].strip()
            if name_part and not name_part.startswith('#'):
                current_block_name = name_part
                current_block_start = line_num
        
        # Count braces
        brace_depth += code.count('{')
        brace_depth -= code.count('}')
        
        # Block ended
        if brace_depth == 0 and current_block_start is not None:
            block_content = '\n'.join(lines[current_block_start:line_num + 1])
            blocks.append({
                'name': current_block_name,
                'start_line': current_block_start + 1,
                'end_line': line_num + 1,
                'content': block_content
            })
            current_block_start = None
            current_block_name = None
    
    return blocks

def analyze_ast_structure(ast_node, depth=0, max_depth=3):
    """Show AST structure to understand bloat."""
    if depth > max_depth:
        return "..."
    
    if isinstance(ast_node, dict):
        result = "{\n"
        for k, v in list(ast_node.items())[:5]:  # First 5 keys only
            result += "  " * (depth + 1) + f'"{k}": {analyze_ast_structure(v, depth + 1, max_depth)},\n'
        if len(ast_node) > 5:
            result += "  " * (depth + 1) + f"... ({len(ast_node)} total keys)\n"
        result += "  " * depth + "}"
        return result
    elif isinstance(ast_node, list):
        if len(ast_node) == 0:
            return "[]"
        result = f"[  # {len(ast_node)} items\n"
        for item in ast_node[:2]:
            result += "  " * (depth + 1) + analyze_ast_structure(item, depth + 1, max_depth) + ",\n"
        if len(ast_node) > 2:
            result += "  " * (depth + 1) + f"... ({len(ast_node)} total items)\n"
        result += "  " * depth + "]"
        return result
    else:
        return repr(ast_node)[:50]

def main():
    db_path = Path.home() / '.ck3raven' / 'ck3raven.db'
    
    # Get the worst file
    print("=== AST BLOAT DIAGNOSTIC ===\n")
    
    file_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    row = get_problem_file(db_path, file_id)
    
    if not row:
        print("No file found!")
        return
    
    file_id, relpath, content = row
    print(f"File: {relpath}")
    print(f"Source size: {len(content):,} bytes ({len(content)/1024:.1f} KB)")
    print()
    
    # First, parse the ENTIRE file and show the AST structure
    print("=== PARSING ENTIRE FILE ===")
    try:
        full_ast = parse(content)
        full_ast_json = json.dumps(full_ast)
        print(f"Full AST JSON size: {len(full_ast_json):,} bytes ({len(full_ast_json)/1024/1024:.1f} MB)")
        print(f"Expansion ratio: {len(full_ast_json) / len(content):.0f}x")
        print()
        print("AST structure preview:")
        print(analyze_ast_structure(full_ast))
        print()
    except Exception as e:
        print(f"Parse error: {e}")
        return
    
    # Now extract blocks
    blocks = extract_top_level_blocks(content)
    print(f"\nFound {len(blocks)} top-level blocks")
    print()
    
    # Parse each block
    cumulative_source = 0
    cumulative_ast = 0
    
    for i, block in enumerate(blocks):
        block_content = block['content']
        block_size = len(block_content)
        cumulative_source += block_size
        
        try:
            ast = parse(block_content)
            ast_json = json.dumps(ast)
            ast_size = len(ast_json)
            cumulative_ast += ast_size
            ratio = ast_size / block_size if block_size > 0 else 0
            
            print(f"Block {i+1}/{len(blocks)}: {block['name']}")
            print(f"  Lines {block['start_line']}-{block['end_line']}")
            print(f"  Source: {block_size:,} bytes ({block_size/1024:.1f} KB)")
            print(f"  AST:    {ast_size:,} bytes ({ast_size/1024:.1f} KB)")
            print(f"  Ratio:  {ratio:.0f}x")
            print(f"  Cumulative: src={cumulative_source/1024:.1f}KB ast={cumulative_ast/1024:.1f}KB ({cumulative_ast/cumulative_source:.0f}x)")
            
            # If ratio is > 100x, this is suspicious - show AST structure
            if ratio > 100:
                print(f"\n  !!! HIGH RATIO - AST structure:")
                print("  " + analyze_ast_structure(ast).replace("\n", "\n  "))
            
            print()
            
        except Exception as e:
            print(f"Block {i+1}: {block['name']} - PARSE ERROR: {e}")
            print()
        
        # Ask to continue
        if i < len(blocks) - 1:
            response = input("Continue? [Y/n/q] ").strip().lower()
            if response == 'n' or response == 'q':
                print("Stopped.")
                break
            print()

if __name__ == "__main__":
    main()
