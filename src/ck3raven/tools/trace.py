"""
Key Tracing Tool

Trace a specific key through the entire game state emulation pipeline.
Shows exactly what happens from playset loading → parsing → resolution.

Usage:
    python -m ck3raven.tools.trace <key> --type traditions
    python -m ck3raven.tools.trace <key> --mods "MSC,VanillaPatch"
"""

import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..parser import parse_source, parse_file
from ..parser.parser import BlockNode
from ..resolver import MergePolicy, CONTENT_TYPES


def trace_key_in_files(key: str, file_paths: List[Path]) -> List[Dict[str, Any]]:
    """Trace a key's definitions across multiple files."""
    definitions = []
    
    for file_path in file_paths:
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()
            
            # Quick check before parsing
            if f"{key} =" not in content and f"{key}=" not in content:
                continue
            
            ast = parse_source(content, str(file_path))
            
            for child in ast.children:
                if isinstance(child, BlockNode) and child.name == key:
                    definitions.append({
                        'file': file_path,
                        'line': child.line,
                        'block': child,
                        'content_preview': _get_block_preview(child)
                    })
                    break
                    
        except Exception as e:
            definitions.append({
                'file': file_path,
                'error': str(e)
            })
    
    return definitions


def _get_block_preview(block: BlockNode) -> Dict[str, Any]:
    """Get a preview of block contents."""
    preview = {}
    
    for child in block.children:
        if hasattr(child, 'key'):
            key = child.key
            if hasattr(child.value, 'value'):
                preview[key] = child.value.value
            else:
                preview[key] = "(block)"
        elif hasattr(child, 'name'):
            preview[child.name] = "(block)"
    
    return preview


def format_trace_result(key: str, definitions: List[Dict], policy: MergePolicy) -> str:
    """Format trace results for display."""
    lines = []
    lines.append("=" * 80)
    lines.append(f"TRACE: {key}")
    lines.append("=" * 80)
    lines.append(f"Total definitions found: {len(definitions)}")
    lines.append(f"Merge policy: {policy.name}")
    lines.append("")
    
    if not definitions:
        lines.append("No definitions found!")
        return "\n".join(lines)
    
    lines.append("Definitions in load order:")
    for i, d in enumerate(definitions, 1):
        is_winner = (i == len(definitions)) if policy == MergePolicy.OVERRIDE else (i == 1)
        status = "★ WINNER ★" if is_winner else "OVERRIDDEN"
        
        if 'error' in d:
            lines.append(f"\n  [{i}] ERROR")
            lines.append(f"      File: {d['file']}")
            lines.append(f"      Error: {d['error']}")
        else:
            lines.append(f"\n  [{i}] {status}")
            lines.append(f"      File: {d['file'].name}")
            lines.append(f"      Line: {d['line']}")
            if d.get('content_preview'):
                lines.append(f"      Preview: {d['content_preview']}")
    
    if len(definitions) > 1:
        lines.append("")
        lines.append("⚠️  CONFLICT DETECTED!")
        lines.append(f"   {len(definitions) - 1} definition(s) are being silently overridden!")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Trace a key through the mod pipeline")
    parser.add_argument("key", help="The key to trace (e.g., tradition_roman_legacy)")
    parser.add_argument("--type", "-t", default="traditions",
                       help="Content type to search")
    parser.add_argument("--paths", "-p", nargs="+", type=Path,
                       help="Paths to search (files or directories)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Show detailed output")
    
    args = parser.parse_args()
    
    # Build list of files to search
    files_to_check = []
    
    if args.paths:
        for p in args.paths:
            if p.is_file():
                files_to_check.append(p)
            elif p.is_dir():
                files_to_check.extend(p.rglob("*.txt"))
    else:
        print("Please provide --paths to search")
        sys.exit(1)
    
    # Get merge policy
    content_config = CONTENT_TYPES.get(args.type.rstrip('s'))  # Handle "traditions" -> "tradition"
    policy = content_config.policy if content_config else MergePolicy.OVERRIDE
    
    # Trace the key
    definitions = trace_key_in_files(args.key, sorted(files_to_check))
    
    # Output
    print(format_trace_result(args.key, definitions, policy))


if __name__ == "__main__":
    main()
