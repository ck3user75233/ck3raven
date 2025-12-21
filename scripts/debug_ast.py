#!/usr/bin/env python3
"""Debug AST structure and round-trip rendering."""
import sys
import sqlite3
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from ck3raven.parser import parse_source

DB_PATH = Path.home() / '.ck3raven/ck3raven.db'


def render_compound_name(name):
    """Render a name that might be a compound (list) like ['change_variable', {...}]."""
    if isinstance(name, str):
        return name
    
    if isinstance(name, list):
        # Compound name like ['change_variable', {value object}]
        parts = []
        for part in name:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                # Extract the value from a value node
                if part.get('_type') == 'value':
                    parts.append(str(part.get('value', '')))
                elif 'v' in part:
                    parts.append(str(part['v']))
                else:
                    parts.append(str(part))
            else:
                parts.append(str(part))
        return ':'.join(parts)
    
    return str(name)


def render_ast_to_script(node, indent=0):
    """Render AST back to CK3 script format."""
    if not isinstance(node, dict):
        return str(node)
    
    node_type = node.get('_type', '')
    ind = '    ' * indent
    
    if node_type == 'root':
        lines = [render_ast_to_script(c, indent) for c in node.get('children', [])]
        return '\n'.join(lines)
    
    elif node_type == 'block':
        name = node.get('name', '')
        name_str = render_compound_name(name)
        children = node.get('children', [])
        child_lines = [render_ast_to_script(c, indent + 1) for c in children]
        if child_lines:
            return f'{ind}{name_str} = {{\n' + '\n'.join(child_lines) + f'\n{ind}}}'
        return f'{ind}{name_str} = {{ }}'
    
    elif node_type == 'assignment':
        key = node.get('key', '')
        key_str = render_compound_name(key)
        op = node.get('operator', '=')
        value_str = render_value(node.get('value', {}), indent)
        return f'{ind}{key_str} {op} {value_str}'
    
    elif node_type == 'assign':
        # Alternate format with 'op' instead of 'operator'
        key = node.get('key', '')
        key_str = render_compound_name(key)
        op = node.get('op', '=')
        value_str = render_value(node.get('value', {}), indent)
        return f'{ind}{key_str} {op} {value_str}'
    
    elif node_type == 'list':
        # List can contain either values or full nodes (assignments, etc.)
        items = node.get('items', [])
        if not items:
            return f'{ind}{{ }}'
        
        # Check if items are complex (assignments) or simple values
        first = items[0] if items else {}
        if isinstance(first, dict) and first.get('_type') in ('assign', 'assignment', 'block'):
            # Multi-line list with complex items
            child_lines = [render_ast_to_script(item, indent + 1) for item in items]
            return f'{ind}{{\n' + '\n'.join(child_lines) + f'\n{ind}}}'
        else:
            # Simple value list
            item_strs = [render_item(item, indent) for item in items]
            return f'{ind}{{ ' + ' '.join(item_strs) + ' }'
    
    elif node_type == 'condition':
        cond = node.get('condition', '')
        op = node.get('operator', '')
        children = node.get('children', [])
        child_lines = [render_ast_to_script(c, indent + 1) for c in children]
        if child_lines:
            return f'{ind}{cond} {op} {{\n' + '\n'.join(child_lines) + f'\n{ind}}}'
        return f'{ind}{cond} {op} {{ }}'
    
    elif node_type == 'call':
        return f'{ind}{node.get("name", "")}'
    
    return f'{ind}# UNKNOWN: {node_type}'


def render_item(val, indent=0):
    """Render a single item that could be a value or a node."""
    if not isinstance(val, dict):
        return str(val)
    
    # If it has a node type that's not 'value', render as node
    node_type = val.get('_type', '')
    if node_type and node_type not in ('value', 'list'):
        # Strip the indent since we're inline
        return render_ast_to_script(val, 0).strip()
    
    return render_value(val, indent)


def render_value(val, indent=0):
    """Render a value node."""
    if not isinstance(val, dict):
        return str(val)
    
    # Standard value node: {_type: "value", value: X, value_type: "identifier"|"number"|"string"|"bool"}
    if val.get('_type') == 'value':
        v = val.get('value', '')
        vt = val.get('value_type', 'identifier')
        if vt == 'string':
            return f'"{v}"'
        return str(v)
    
    # Alternate format with 'v' and 't'
    if 'v' in val and 't' in val:
        v = val['v']
        t = val['t']
        if t == 'string':
            return f'"{v}"'
        return str(v)
    
    # List node with items
    if val.get('_type') == 'list':
        items = val.get('items', [])
        if not items:
            return '{ }'
        # Check if items are complex
        first = items[0] if items else {}
        if isinstance(first, dict) and first.get('_type') in ('assign', 'assignment', 'block'):
            ind = '    ' * indent
            child_lines = [render_ast_to_script(item, indent + 1) for item in items]
            return '{\n' + '\n'.join(child_lines) + f'\n{ind}}}'
        else:
            item_strs = [render_item(item, indent) for item in items]
            return '{ ' + ' '.join(item_strs) + ' }'
    
    # Assignment or assign node in value position (inline)
    if val.get('_type') in ('assign', 'assignment'):
        return render_ast_to_script(val, 0).strip()
    
    # Nested block in value position
    if val.get('_type') == 'block':
        children = val.get('children', [])
        ind = '    ' * indent
        child_lines = [render_ast_to_script(c, indent + 1) for c in children]
        if child_lines:
            return '{\n' + '\n'.join(child_lines) + f'\n{ind}}}'
        return '{ }'
    
    # Inline block with children (anonymous block)
    if 'children' in val:
        ind = '    ' * indent
        child_lines = [render_ast_to_script(c, indent + 1) for c in val['children']]
        return '{\n' + '\n'.join(child_lines) + f'\n{ind}}}'
    
    return str(val)


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    
    # Comprehensive round-trip test on 500 random files
    print("=== COMPREHENSIVE ROUND-TRIP TEST (500 files) ===")
    
    cursor = conn.execute('''
        SELECT f.relpath, fc.content_text, a.ast_blob
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        JOIN asts a ON fc.content_hash = a.content_hash
        WHERE a.parse_ok = 1 
        ORDER BY RANDOM()
        LIMIT 500
    ''')
    
    passed = 0
    failed = 0
    failures = []
    
    for row in cursor:
        relpath = row['relpath']
        ast = json.loads(row['ast_blob'])
        
        try:
            rendered = render_ast_to_script(ast)
            result = parse_source(rendered, 'test.txt')
            
            if hasattr(result, 'children'):
                passed += 1
            else:
                failed += 1
                failures.append((relpath, "No children in result"))
        except Exception as e:
            failed += 1
            failures.append((relpath, str(e)))
    
    print(f"\nResults: {passed}/500 passed, {failed} failed")
    
    if failures:
        print(f"\n=== FIRST 5 FAILURES ===")
        for relpath, error in failures[:5]:
            print(f"  {relpath}")
            print(f"    Error: {error[:100]}")
            print()
    
    # Show pass rate
    pass_rate = passed / (passed + failed) * 100
    print(f"Pass rate: {pass_rate:.1f}%")
    
    return passed, failed, failures


def collect_types(node, type_examples, depth=0):
    """Collect all unique _type values and their keys."""
    if not isinstance(node, dict):
        return
    
    t = node.get('_type', 'unknown')
    if t not in type_examples:
        type_examples[t] = {}
    
    for key in node.keys():
        if key not in type_examples[t]:
            type_examples[t][key] = True
    
    for key, val in node.items():
        if isinstance(val, dict):
            collect_types(val, type_examples, depth + 1)
        elif isinstance(val, list):
            for item in val:
                collect_types(item, type_examples, depth + 1)


if __name__ == '__main__':
    main()
