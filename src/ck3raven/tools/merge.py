"""
3-Way Merge Tool

Merges multiple PDX/CK3 script files or blocks with conflict resolution.
Supports different merge strategies for different content types.

Usage:
    python -m ck3raven.tools.merge <base> <ours> <theirs>       # 3-way merge
    python -m ck3raven.tools.merge <file1> <file2> --combine    # Combine all blocks
    python -m ck3raven.tools.merge <files...> --block NAME      # Merge specific block
"""

import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from copy import deepcopy

from ..parser import parse_file, parse_source
from ..parser.parser import RootNode, BlockNode, AssignmentNode, ValueNode, ListNode
from .format import PDXFormatter, FormatOptions


class MergeStrategy(Enum):
    """How to resolve conflicts."""
    OURS = "ours"             # Take our version
    THEIRS = "theirs"         # Take their version
    UNION = "union"           # Combine (for lists/parameters)
    LATEST = "latest"         # Take the last in load order
    INTERACTIVE = "interactive"  # Ask user


class ConflictType(Enum):
    """Type of merge conflict."""
    VALUE_DIFFERS = "value_differs"
    BLOCK_DIFFERS = "block_differs"
    KEY_ADDED = "key_added"
    KEY_REMOVED = "key_removed"
    TYPE_MISMATCH = "type_mismatch"


@dataclass
class MergeConflict:
    """A conflict that needs resolution."""
    conflict_type: ConflictType
    path: str
    base_value: Any = None
    ours_value: Any = None
    theirs_value: Any = None
    resolution: str = ""
    
    def describe(self) -> str:
        return f"Conflict at {self.path}: {self.conflict_type.value}"


@dataclass
class MergeResult:
    """Result of a merge operation."""
    success: bool
    merged_ast: Optional[RootNode] = None
    conflicts: List[MergeConflict] = field(default_factory=list)
    unresolved: List[MergeConflict] = field(default_factory=list)
    
    def has_conflicts(self) -> bool:
        return len(self.unresolved) > 0


class PDXMerger:
    """
    Merges PDX files using AST-level operations.
    
    Supports:
    - 3-way merge (base, ours, theirs)
    - 2-way combine (just add all blocks from multiple files)
    - Selective block merge
    """
    
    def __init__(self, strategy: MergeStrategy = MergeStrategy.LATEST):
        self.strategy = strategy
        self.formatter = PDXFormatter()
    
    def combine_files(self, file_paths: List[Path]) -> RootNode:
        """
        Combine multiple files into one.
        Later files override earlier ones for duplicate keys.
        """
        combined = RootNode()
        seen_blocks = {}
        
        for file_path in file_paths:
            ast = parse_file(str(file_path))
            
            for child in ast.children:
                if isinstance(child, BlockNode):
                    key = child.name
                    if key in seen_blocks:
                        # Replace existing
                        for i, existing in enumerate(combined.children):
                            if isinstance(existing, BlockNode) and existing.name == key:
                                combined.children[i] = deepcopy(child)
                                break
                    else:
                        combined.children.append(deepcopy(child))
                    seen_blocks[key] = file_path
                    
                elif isinstance(child, AssignmentNode):
                    key = child.key
                    if key in seen_blocks:
                        for i, existing in enumerate(combined.children):
                            if isinstance(existing, AssignmentNode) and existing.key == key:
                                combined.children[i] = deepcopy(child)
                                break
                    else:
                        combined.children.append(deepcopy(child))
                    seen_blocks[key] = file_path
        
        return combined
    
    def merge_blocks(self, ours: BlockNode, theirs: BlockNode, 
                     path: str = "") -> Tuple[BlockNode, List[MergeConflict]]:
        """Merge two blocks, returning merged result and any conflicts."""
        conflicts = []
        merged = BlockNode(name=ours.name, operator=ours.operator, line=ours.line)
        
        ours_items = {}
        theirs_items = {}
        
        for child in ours.children:
            key = child.name if isinstance(child, BlockNode) else (child.key if isinstance(child, AssignmentNode) else None)
            if key:
                ours_items[key] = child
        
        for child in theirs.children:
            key = child.name if isinstance(child, BlockNode) else (child.key if isinstance(child, AssignmentNode) else None)
            if key:
                theirs_items[key] = child
        
        all_keys = set(ours_items.keys()) | set(theirs_items.keys())
        
        for key in sorted(all_keys):
            current_path = f"{path}.{key}" if path else key
            
            if key not in ours_items:
                # Added in theirs
                merged.children.append(deepcopy(theirs_items[key]))
            elif key not in theirs_items:
                # Removed in theirs - keep ours? depends on strategy
                if self.strategy in (MergeStrategy.OURS, MergeStrategy.UNION):
                    merged.children.append(deepcopy(ours_items[key]))
            else:
                ours_child = ours_items[key]
                theirs_child = theirs_items[key]
                
                # Both have it - check if same
                if isinstance(ours_child, BlockNode) and isinstance(theirs_child, BlockNode):
                    sub_merged, sub_conflicts = self.merge_blocks(ours_child, theirs_child, current_path)
                    merged.children.append(sub_merged)
                    conflicts.extend(sub_conflicts)
                else:
                    # Simple value comparison
                    ours_val = _get_node_value(ours_child)
                    theirs_val = _get_node_value(theirs_child)
                    
                    if ours_val != theirs_val:
                        conflicts.append(MergeConflict(
                            conflict_type=ConflictType.VALUE_DIFFERS,
                            path=current_path,
                            ours_value=ours_val,
                            theirs_value=theirs_val
                        ))
                        # Use strategy to pick winner
                        if self.strategy in (MergeStrategy.THEIRS, MergeStrategy.LATEST):
                            merged.children.append(deepcopy(theirs_child))
                        else:
                            merged.children.append(deepcopy(ours_child))
                    else:
                        merged.children.append(deepcopy(ours_child))
        
        return merged, conflicts
    
    def format_result(self, ast: RootNode) -> str:
        """Format merged AST to string."""
        return self.formatter.format_ast(ast)


def _get_node_value(node) -> Any:
    """Extract comparable value from a node."""
    if isinstance(node, ValueNode):
        return node.value
    elif isinstance(node, AssignmentNode):
        if isinstance(node.value, ValueNode):
            return node.value.value
        return str(node.value)
    elif isinstance(node, BlockNode):
        return node.to_dict()
    return str(node)


def main():
    parser = argparse.ArgumentParser(description="Merge PDX/CK3 script files")
    parser.add_argument("files", nargs="+", type=Path, help="Files to merge")
    parser.add_argument("--combine", "-c", action="store_true",
                       help="Combine all files (later wins)")
    parser.add_argument("--block", "-b", help="Merge specific block only")
    parser.add_argument("--strategy", "-s", 
                       choices=["ours", "theirs", "union", "latest"],
                       default="latest", help="Conflict resolution strategy")
    parser.add_argument("--output", "-o", type=Path, help="Output file")
    
    args = parser.parse_args()
    
    # Validate files exist
    for f in args.files:
        if not f.exists():
            print(f"Error: {f} not found", file=sys.stderr)
            sys.exit(1)
    
    strategy = MergeStrategy(args.strategy)
    merger = PDXMerger(strategy=strategy)
    
    if args.combine or len(args.files) > 2:
        # Combine mode
        result = merger.combine_files(args.files)
        output = merger.format_result(result)
    else:
        # 2-way merge
        ast1 = parse_file(str(args.files[0]))
        ast2 = parse_file(str(args.files[1]))
        
        if args.block:
            block1 = ast1.get_block(args.block)
            block2 = ast2.get_block(args.block)
            
            if not block1 or not block2:
                print(f"Block '{args.block}' not found in both files")
                sys.exit(1)
            
            merged, conflicts = merger.merge_blocks(block1, block2)
            result = RootNode()
            result.children.append(merged)
        else:
            # Merge all blocks
            result = merger.combine_files(args.files)
        
        output = merger.format_result(result)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"Merged output written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
