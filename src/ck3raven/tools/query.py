"""
AST Query Tool

Search and query AST structures from parsed PDX files.

Usage:
    python -m ck3raven.tools.query <file> --key <name>     # Find block by key
    python -m ck3raven.tools.query <file> --path <dotpath> # Navigate to path
    python -m ck3raven.tools.query <file> --search <text>  # Search for values
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..parser import parse_file, parse_source
from ..parser.parser import RootNode, BlockNode, AssignmentNode, ValueNode, ListNode


def find_blocks_by_name(root: RootNode, name: str) -> List[BlockNode]:
    """Find all blocks with given name."""
    results = []
    
    def walk(node):
        if isinstance(node, BlockNode):
            if node.name == name:
                results.append(node)
            for child in node.children:
                walk(child)
        elif isinstance(node, RootNode):
            for child in node.children:
                walk(child)
        elif isinstance(node, AssignmentNode):
            if node.value:
                walk(node.value)
    
    walk(root)
    return results


def find_by_path(root: RootNode, path: str) -> Optional[Any]:
    """Navigate to a specific path like 'tradition_foo.is_shown.OR'."""
    parts = path.split('.')
    current = root
    
    for part in parts:
        found = None
        
        if isinstance(current, RootNode):
            for child in current.children:
                if isinstance(child, BlockNode) and child.name == part:
                    found = child
                    break
                elif isinstance(child, AssignmentNode) and child.key == part:
                    found = child.value
                    break
        
        elif isinstance(current, BlockNode):
            for child in current.children:
                if isinstance(child, BlockNode) and child.name == part:
                    found = child
                    break
                elif isinstance(child, AssignmentNode) and child.key == part:
                    found = child.value
                    break
        
        if found is None:
            return None
        current = found
    
    return current


def search_values(root: RootNode, search_text: str) -> List[Dict[str, Any]]:
    """Search for nodes containing search_text in their values."""
    results = []
    search_lower = search_text.lower()
    
    def walk(node, path=""):
        if isinstance(node, ValueNode):
            if search_lower in str(node.value).lower():
                results.append({
                    "path": path,
                    "value": node.value,
                    "line": node.line
                })
        elif isinstance(node, BlockNode):
            current_path = f"{path}.{node.name}" if path else node.name
            for child in node.children:
                walk(child, current_path)
        elif isinstance(node, AssignmentNode):
            current_path = f"{path}.{node.key}" if path else node.key
            if node.value:
                walk(node.value, current_path)
        elif isinstance(node, RootNode):
            for child in node.children:
                walk(child, path)
    
    walk(root)
    return results


def get_all_keys(root: RootNode) -> List[str]:
    """Get all top-level block/assignment keys."""
    keys = []
    for child in root.children:
        if isinstance(child, BlockNode):
            keys.append(child.name)
        elif isinstance(child, AssignmentNode):
            keys.append(child.key)
    return keys


def format_node(node: Any, indent: int = 0) -> str:
    """Format a node for display."""
    ind = "  " * indent
    
    if isinstance(node, ValueNode):
        return f"{ind}{node.value}"
    elif isinstance(node, BlockNode):
        lines = [f"{ind}{node.name} = {{"]
        for child in node.children:
            lines.append(format_node(child, indent + 1))
        lines.append(f"{ind}}}")
        return "\n".join(lines)
    elif isinstance(node, AssignmentNode):
        if isinstance(node.value, (BlockNode, ListNode)):
            return f"{ind}{node.key} = {format_node(node.value, indent).lstrip()}"
        else:
            val = node.value.value if isinstance(node.value, ValueNode) else node.value
            return f"{ind}{node.key} = {val}"
    elif isinstance(node, ListNode):
        if not node.items:
            return "{ }"
        lines = ["{"]
        for item in node.items:
            lines.append(format_node(item, indent + 1))
        lines.append(f"{'  ' * indent}}}")
        return "\n".join(lines)
    return str(node)


def main():
    parser = argparse.ArgumentParser(description="Query PDX AST structures")
    parser.add_argument("file", type=Path, help="File to query")
    parser.add_argument("--key", "-k", help="Find block by key name")
    parser.add_argument("--path", "-p", help="Navigate to dot-separated path")
    parser.add_argument("--search", "-s", help="Search for values containing text")
    parser.add_argument("--list", "-l", action="store_true", help="List top-level keys")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    args = parser.parse_args()
    
    if not args.file.exists():
        print(f"Error: {args.file} not found", file=sys.stderr)
        sys.exit(1)
    
    try:
        ast = parse_file(str(args.file))
    except Exception as e:
        print(f"Parse error: {e}", file=sys.stderr)
        sys.exit(1)
    
    if args.list:
        keys = get_all_keys(ast)
        if args.json:
            print(json.dumps(keys, indent=2))
        else:
            for key in keys:
                print(key)
    
    elif args.key:
        blocks = find_blocks_by_name(ast, args.key)
        if not blocks:
            print(f"No blocks found with name '{args.key}'")
            sys.exit(1)
        
        for i, block in enumerate(blocks):
            if args.json:
                print(json.dumps(block.to_dict(), indent=2))
            else:
                if i > 0:
                    print("\n" + "="*60 + "\n")
                print(format_node(block))
    
    elif args.path:
        result = find_by_path(ast, args.path)
        if result is None:
            print(f"Path not found: {args.path}")
            sys.exit(1)
        
        if args.json:
            if hasattr(result, 'to_dict'):
                print(json.dumps(result.to_dict(), indent=2))
            else:
                print(json.dumps(str(result)))
        else:
            print(format_node(result))
    
    elif args.search:
        results = search_values(ast, args.search)
        if not results:
            print(f"No values found containing '{args.search}'")
            sys.exit(1)
        
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            for r in results:
                print(f"Line {r['line']}: {r['path']} = {r['value']}")
    
    else:
        # Default: show top-level structure
        keys = get_all_keys(ast)
        print(f"File: {args.file}")
        print(f"Top-level entries: {len(keys)}")
        print()
        for key in keys[:20]:
            print(f"  - {key}")
        if len(keys) > 20:
            print(f"  ... and {len(keys) - 20} more")


if __name__ == "__main__":
    main()
