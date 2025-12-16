"""
PDX Semantic Diff Tool

Compares PDX/CK3 script files or blocks semantically, ignoring formatting.
Shows actual structural differences rather than textual noise.

Usage:
    python -m ck3raven.tools.diff <file1> <file2>               # Diff two files
    python -m ck3raven.tools.diff <file1> <file2> --block NAME  # Diff specific block
    python -m ck3raven.tools.diff <file1> <file2> --json        # Output as JSON
    python -m ck3raven.tools.diff <file1> <file2> --side-by-side # Side-by-side view
"""

import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import OrderedDict

from ..parser import parse_file, parse_source
from ..parser.parser import RootNode, BlockNode, AssignmentNode, ValueNode, ListNode


class DiffType(Enum):
    """Types of differences found."""
    ADDED = "added"       # Present in right, not in left
    REMOVED = "removed"   # Present in left, not in right
    CHANGED = "changed"   # Different value
    MOVED = "moved"       # Same content, different position (future)


@dataclass
class DiffItem:
    """A single difference between two ASTs."""
    diff_type: DiffType
    path: str                    # Path to the difference (e.g., "is_shown.OR.scope:character")
    left_value: Any = None       # Value in left file (if applicable)
    right_value: Any = None      # Value in right file (if applicable)
    left_line: int = 0           # Line number in left file
    right_line: int = 0          # Line number in right file
    
    def __str__(self):
        if self.diff_type == DiffType.ADDED:
            return f"+ {self.path}: {self._format_value(self.right_value)}"
        elif self.diff_type == DiffType.REMOVED:
            return f"- {self.path}: {self._format_value(self.left_value)}"
        elif self.diff_type == DiffType.CHANGED:
            return f"~ {self.path}:\n    - {self._format_value(self.left_value)}\n    + {self._format_value(self.right_value)}"
        return f"? {self.path}"
    
    def _format_value(self, value: Any) -> str:
        if isinstance(value, dict):
            if len(str(value)) > 60:
                return f"{{ {len(value)} keys... }}"
            return str(value)
        elif isinstance(value, list):
            if len(value) > 5:
                return f"[{len(value)} items...]"
            return str(value)
        return str(value)


@dataclass
class DiffResult:
    """Result of comparing two files/blocks."""
    left_file: str
    right_file: str
    left_block: Optional[str] = None
    right_block: Optional[str] = None
    identical: bool = False
    differences: List[DiffItem] = field(default_factory=list)
    
    @property
    def added_count(self) -> int:
        return sum(1 for d in self.differences if d.diff_type == DiffType.ADDED)
    
    @property
    def removed_count(self) -> int:
        return sum(1 for d in self.differences if d.diff_type == DiffType.REMOVED)
    
    @property
    def changed_count(self) -> int:
        return sum(1 for d in self.differences if d.diff_type == DiffType.CHANGED)
    
    def summary(self) -> str:
        if self.identical:
            return "Files are identical"
        parts = []
        if self.added_count:
            parts.append(f"+{self.added_count}")
        if self.removed_count:
            parts.append(f"-{self.removed_count}")
        if self.changed_count:
            parts.append(f"~{self.changed_count}")
        return f"{len(self.differences)} differences: {', '.join(parts)}"


class PDXDiffer:
    """
    Compares PDX files semantically by diffing their AST representations.
    """
    
    def __init__(self, ignore_order: bool = False):
        """
        Args:
            ignore_order: If True, treat blocks with same keys as equal regardless of order
        """
        self.ignore_order = ignore_order
    
    def diff_files(self, left_path: Path, right_path: Path, 
                   block_name: str = None) -> DiffResult:
        """Diff two files."""
        left_ast = parse_file(str(left_path))
        right_ast = parse_file(str(right_path))
        
        left_name = str(left_path)
        right_name = str(right_path)
        
        if block_name:
            left_block = left_ast.get_block(block_name)
            right_block = right_ast.get_block(block_name)
            
            if not left_block:
                return DiffResult(
                    left_file=left_name,
                    right_file=right_name,
                    left_block=block_name,
                    right_block=block_name,
                    identical=False,
                    differences=[DiffItem(
                        diff_type=DiffType.REMOVED,
                        path=block_name,
                        left_value=None,
                        right_value="entire block"
                    )]
                )
            
            if not right_block:
                return DiffResult(
                    left_file=left_name,
                    right_file=right_name,
                    left_block=block_name,
                    right_block=block_name,
                    identical=False,
                    differences=[DiffItem(
                        diff_type=DiffType.ADDED,
                        path=block_name,
                        left_value="entire block",
                        right_value=None
                    )]
                )
            
            return self._diff_blocks(left_block, right_block, 
                                     left_name, right_name, block_name)
        
        return self._diff_roots(left_ast, right_ast, left_name, right_name)
    
    def diff_strings(self, left: str, right: str,
                     left_name: str = "left", right_name: str = "right") -> DiffResult:
        """Diff two strings of PDX content."""
        left_ast = parse_source(left, left_name)
        right_ast = parse_source(right, right_name)
        return self._diff_roots(left_ast, right_ast, left_name, right_name)
    
    def _diff_roots(self, left: RootNode, right: RootNode,
                    left_name: str, right_name: str) -> DiffResult:
        """Diff two root nodes."""
        differences = []
        
        # Build dictionaries of top-level blocks/assignments
        left_items = self._collect_items(left)
        right_items = self._collect_items(right)
        
        all_keys = set(left_items.keys()) | set(right_items.keys())
        
        for key in sorted(all_keys):
            if key not in left_items:
                differences.append(DiffItem(
                    diff_type=DiffType.ADDED,
                    path=key,
                    right_value=self._summarize_node(right_items[key]),
                    right_line=right_items[key].line
                ))
            elif key not in right_items:
                differences.append(DiffItem(
                    diff_type=DiffType.REMOVED,
                    path=key,
                    left_value=self._summarize_node(left_items[key]),
                    left_line=left_items[key].line
                ))
            else:
                # Both exist - compare them
                sub_diffs = self._diff_nodes(left_items[key], right_items[key], key)
                differences.extend(sub_diffs)
        
        return DiffResult(
            left_file=left_name,
            right_file=right_name,
            identical=len(differences) == 0,
            differences=differences
        )
    
    def _diff_blocks(self, left: BlockNode, right: BlockNode,
                     left_name: str, right_name: str,
                     block_name: str) -> DiffResult:
        """Diff two specific blocks."""
        differences = self._diff_nodes(left, right, block_name)
        
        return DiffResult(
            left_file=left_name,
            right_file=right_name,
            left_block=block_name,
            right_block=block_name,
            identical=len(differences) == 0,
            differences=differences
        )
    
    def _diff_nodes(self, left, right, path: str = "") -> List[DiffItem]:
        """Recursively diff two AST nodes."""
        differences = []
        
        # Convert to comparable dictionaries
        left_dict = self._node_to_dict(left)
        right_dict = self._node_to_dict(right)
        
        differences.extend(self._diff_dicts(left_dict, right_dict, path,
                                            getattr(left, 'line', 0),
                                            getattr(right, 'line', 0)))
        
        return differences
    
    def _diff_dicts(self, left: Dict, right: Dict, path: str,
                    left_line: int = 0, right_line: int = 0) -> List[DiffItem]:
        """Recursively diff two dictionaries."""
        differences = []
        
        # Get all keys (excluding internal metadata)
        left_keys = {k for k in left.keys() if not k.startswith('_')}
        right_keys = {k for k in right.keys() if not k.startswith('_')}
        all_keys = left_keys | right_keys
        
        for key in sorted(all_keys):
            current_path = f"{path}.{key}" if path else key
            
            if key not in left:
                differences.append(DiffItem(
                    diff_type=DiffType.ADDED,
                    path=current_path,
                    right_value=right[key],
                    right_line=right_line
                ))
            elif key not in right:
                differences.append(DiffItem(
                    diff_type=DiffType.REMOVED,
                    path=current_path,
                    left_value=left[key],
                    left_line=left_line
                ))
            else:
                left_val = left[key]
                right_val = right[key]
                
                if isinstance(left_val, dict) and isinstance(right_val, dict):
                    # Recurse into nested dicts
                    differences.extend(self._diff_dicts(
                        left_val, right_val, current_path,
                        left_line, right_line
                    ))
                elif isinstance(left_val, list) and isinstance(right_val, list):
                    # Compare lists
                    if self.ignore_order:
                        left_set = set(str(x) for x in left_val)
                        right_set = set(str(x) for x in right_val)
                        if left_set != right_set:
                            differences.append(DiffItem(
                                diff_type=DiffType.CHANGED,
                                path=current_path,
                                left_value=left_val,
                                right_value=right_val,
                                left_line=left_line,
                                right_line=right_line
                            ))
                    else:
                        if left_val != right_val:
                            differences.append(DiffItem(
                                diff_type=DiffType.CHANGED,
                                path=current_path,
                                left_value=left_val,
                                right_value=right_val,
                                left_line=left_line,
                                right_line=right_line
                            ))
                elif left_val != right_val:
                    differences.append(DiffItem(
                        diff_type=DiffType.CHANGED,
                        path=current_path,
                        left_value=left_val,
                        right_value=right_val,
                        left_line=left_line,
                        right_line=right_line
                    ))
        
        return differences
    
    def _collect_items(self, root: RootNode) -> Dict[str, Any]:
        """Collect all top-level items from a root node."""
        items = {}
        for child in root.children:
            if isinstance(child, BlockNode):
                items[child.name] = child
            elif isinstance(child, AssignmentNode):
                items[child.key] = child
        return items
    
    def _node_to_dict(self, node) -> Dict[str, Any]:
        """Convert an AST node to a dictionary for comparison."""
        if isinstance(node, BlockNode):
            return node.to_dict()
        elif isinstance(node, AssignmentNode):
            if isinstance(node.value, BlockNode):
                return node.value.to_dict()
            elif isinstance(node.value, ValueNode):
                return {"_value": node.value.value}
            elif isinstance(node.value, ListNode):
                return {"_list": [self._node_to_dict(i) for i in node.value.items]}
            return {"_value": str(node.value)}
        elif isinstance(node, ValueNode):
            return {"_value": node.value}
        elif isinstance(node, ListNode):
            return {"_list": [self._node_to_dict(i) for i in node.items]}
        return {}
    
    def _summarize_node(self, node) -> str:
        """Get a short summary of a node."""
        if isinstance(node, BlockNode):
            return f"{{ {len(node.children)} children }}"
        elif isinstance(node, AssignmentNode):
            return f"{node.key} = ..."
        elif isinstance(node, ValueNode):
            return node.value
        return str(node)


def diff_files(left: Path, right: Path, block: str = None) -> DiffResult:
    """Convenience function to diff two files."""
    differ = PDXDiffer()
    return differ.diff_files(left, right, block)


def format_side_by_side(result: DiffResult, width: int = 80) -> str:
    """Format diff result as side-by-side comparison."""
    lines = []
    half = width // 2 - 2
    
    # Header
    left_header = Path(result.left_file).name[:half]
    right_header = Path(result.right_file).name[:half]
    lines.append(f"{'─' * half}┬{'─' * half}")
    lines.append(f"{left_header:<{half}}│{right_header:<{half}}")
    lines.append(f"{'─' * half}┼{'─' * half}")
    
    if result.identical:
        lines.append(f"{'(identical)':<{half}}│{'(identical)':<{half}}")
    else:
        for diff in result.differences:
            if diff.diff_type == DiffType.ADDED:
                left_text = ""
                right_text = f"+ {diff.path}"
            elif diff.diff_type == DiffType.REMOVED:
                left_text = f"- {diff.path}"
                right_text = ""
            else:
                left_text = f"~ {diff.path}"
                right_text = f"~ {diff.path}"
            
            lines.append(f"{left_text[:half]:<{half}}│{right_text[:half]:<{half}}")
    
    lines.append(f"{'─' * half}┴{'─' * half}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Semantic diff for PDX/CK3 files")
    parser.add_argument("left", type=Path, help="First file to compare")
    parser.add_argument("right", type=Path, help="Second file to compare")
    parser.add_argument("--block", "-b", help="Compare specific block by name")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--side-by-side", "-s", action="store_true",
                       help="Side-by-side view")
    parser.add_argument("--ignore-order", action="store_true",
                       help="Ignore order of list items")
    parser.add_argument("--quiet", "-q", action="store_true",
                       help="Only show summary")
    
    args = parser.parse_args()
    
    if not args.left.exists():
        print(f"Error: {args.left} not found", file=sys.stderr)
        sys.exit(1)
    if not args.right.exists():
        print(f"Error: {args.right} not found", file=sys.stderr)
        sys.exit(1)
    
    differ = PDXDiffer(ignore_order=args.ignore_order)
    result = differ.diff_files(args.left, args.right, args.block)
    
    if args.json:
        import json
        output = {
            "left_file": result.left_file,
            "right_file": result.right_file,
            "identical": result.identical,
            "summary": result.summary(),
            "differences": [
                {
                    "type": d.diff_type.value,
                    "path": d.path,
                    "left_value": str(d.left_value) if d.left_value else None,
                    "right_value": str(d.right_value) if d.right_value else None,
                    "left_line": d.left_line,
                    "right_line": d.right_line
                }
                for d in result.differences
            ]
        }
        print(json.dumps(output, indent=2))
    
    elif args.side_by_side:
        print(format_side_by_side(result))
    
    elif args.quiet:
        print(result.summary())
    
    else:
        # Default: detailed view
        print(f"Comparing:")
        print(f"  Left:  {result.left_file}")
        print(f"  Right: {result.right_file}")
        if result.left_block:
            print(f"  Block: {result.left_block}")
        print()
        
        if result.identical:
            print("✓ Files are semantically identical")
        else:
            print(f"{result.summary()}\n")
            for diff in result.differences:
                print(diff)
                print()
    
    # Exit code: 0 if identical, 1 if different
    sys.exit(0 if result.identical else 1)


if __name__ == "__main__":
    main()
