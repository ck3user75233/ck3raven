#!/usr/bin/env python3
"""
AST Differ Core - Schema-Agnostic Structural Diffing

This module provides deterministic diffing of ck3raven AST structures.
It is symbol-type agnostic - it knows nothing about MAA, buildings, traits, etc.

The differ walks two AST structures and emits flat change records with json_path
addressing, enabling SQL-based pattern discovery.

Input: Two AST dicts (from ck3_parse_content or database)
Output: List of ChangeRecord objects

Design Principles:
- No hardcoded field lists
- No symbol-specific logic
- Deterministic path generation
- Handles arbitrary nesting depth
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Optional
import json


class ChangeType(Enum):
    """Type of change detected."""
    MODIFIED = "modified"
    ADDED = "added"
    REMOVED = "removed"


class ValueType(Enum):
    """Classification of value types."""
    NUMBER = "number"
    STRING = "string"
    IDENTIFIER = "identifier"  # Reference token (e.g., trait names)
    BLOCK = "block"
    MISSING = "missing"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ChangeRecord:
    """
    A single atomic change between two AST versions.
    
    Attributes:
        json_path: Dot-separated path to the changed element (e.g., "terrain_bonus.plains.damage")
        old_value: Value in baseline AST (None if ADDED)
        new_value: Value in compare AST (None if REMOVED)
        old_type: ValueType of old_value
        new_type: ValueType of new_value
        change_type: MODIFIED, ADDED, or REMOVED
    """
    json_path: str
    old_value: Optional[str]
    new_value: Optional[str]
    old_type: ValueType
    new_type: ValueType
    change_type: ChangeType
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "json_path": self.json_path,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "old_type": self.old_type.value,
            "new_type": self.new_type.value,
            "change_type": self.change_type.value,
        }


@dataclass
class DiffResult:
    """
    Result of diffing two AST structures.
    
    Attributes:
        symbol_name: Name of the symbol being compared
        symbol_type: Type inferred from context (optional)
        baseline_source: Identifier for baseline (e.g., "vanilla")
        compare_source: Identifier for comparison (e.g., "kgd")
        changes: List of ChangeRecord objects
    """
    symbol_name: str
    baseline_source: str
    compare_source: str
    changes: list[ChangeRecord] = field(default_factory=list)
    symbol_type: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "symbol_name": self.symbol_name,
            "symbol_type": self.symbol_type,
            "baseline_source": self.baseline_source,
            "compare_source": self.compare_source,
            "change_count": len(self.changes),
            "changes": [c.to_dict() for c in self.changes],
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


def classify_value_type(value_node: dict) -> ValueType:
    """
    Classify the type of a value node.
    
    Args:
        value_node: AST node with _type="value"
        
    Returns:
        ValueType classification
    """
    if value_node is None:
        return ValueType.MISSING
    
    node_type = value_node.get("_type")
    
    if node_type == "block":
        return ValueType.BLOCK
    
    if node_type == "value":
        vtype = value_node.get("value_type", "")
        if vtype == "number":
            return ValueType.NUMBER
        elif vtype == "string":
            return ValueType.STRING
        elif vtype == "identifier":
            return ValueType.IDENTIFIER
        else:
            return ValueType.UNKNOWN
    
    return ValueType.UNKNOWN


def extract_value(value_node: dict) -> Optional[str]:
    """
    Extract the string representation of a value.
    
    Args:
        value_node: AST node
        
    Returns:
        String representation of the value, or None
    """
    if value_node is None:
        return None
    
    node_type = value_node.get("_type")
    
    if node_type == "value":
        return str(value_node.get("value", ""))
    
    if node_type == "block":
        # For blocks, we don't extract a simple value
        # The block's children will be diffed recursively
        return "<block>"
    
    return None


def build_child_index(children: list[dict]) -> dict[str, list[dict]]:
    """
    Build an index of children by their key/name.
    
    PDX files can have repeated keys. This groups them for ordered comparison.
    
    Args:
        children: List of AST child nodes (assignments or blocks)
        
    Returns:
        Dict mapping key -> list of nodes with that key (preserving order)
    """
    index: dict[str, list[dict]] = {}
    
    for child in children:
        node_type = child.get("_type")
        
        if node_type == "assignment":
            key = child.get("key", "")
        elif node_type == "block":
            key = child.get("name", "")
        else:
            continue  # Skip unknown node types
        
        if key not in index:
            index[key] = []
        index[key].append(child)
    
    return index


def diff_nodes(
    baseline: Optional[dict],
    compare: Optional[dict],
    path: str,
) -> Iterator[ChangeRecord]:
    """
    Recursively diff two AST nodes.
    
    Args:
        baseline: AST node from baseline version (may be None)
        compare: AST node from compare version (may be None)
        path: Current json_path prefix
        
    Yields:
        ChangeRecord objects for each detected change
    """
    # Handle missing nodes
    if baseline is None and compare is None:
        return
    
    if baseline is None:
        # Entire node was added
        yield from emit_added(compare, path)
        return
    
    if compare is None:
        # Entire node was removed
        yield from emit_removed(baseline, path)
        return
    
    # Both exist - compare them
    baseline_type = baseline.get("_type")
    compare_type = compare.get("_type")
    
    # If types differ, treat as remove + add
    if baseline_type != compare_type:
        yield from emit_removed(baseline, path)
        yield from emit_added(compare, path)
        return
    
    if baseline_type == "assignment":
        yield from diff_assignments(baseline, compare, path)
    elif baseline_type == "block":
        yield from diff_blocks(baseline, compare, path)
    elif baseline_type == "value":
        yield from diff_values(baseline, compare, path)


def diff_assignments(
    baseline: dict,
    compare: dict,
    path: str,
) -> Iterator[ChangeRecord]:
    """
    Diff two assignment nodes.
    
    An assignment has a key and a value.
    """
    baseline_val = baseline.get("value")
    compare_val = compare.get("value")
    
    # If value is a nested block, recurse
    if baseline_val and baseline_val.get("_type") == "block":
        yield from diff_blocks(baseline_val, compare_val, path)
    elif compare_val and compare_val.get("_type") == "block":
        yield from diff_blocks(baseline_val, compare_val, path)
    else:
        yield from diff_values(baseline_val, compare_val, path)


def diff_values(
    baseline: Optional[dict],
    compare: Optional[dict],
    path: str,
) -> Iterator[ChangeRecord]:
    """
    Diff two value nodes (leaf comparison).
    """
    old_val = extract_value(baseline)
    new_val = extract_value(compare)
    old_type = classify_value_type(baseline)
    new_type = classify_value_type(compare)
    
    if baseline is None and compare is not None:
        yield ChangeRecord(
            json_path=path,
            old_value=None,
            new_value=new_val,
            old_type=ValueType.MISSING,
            new_type=new_type,
            change_type=ChangeType.ADDED,
        )
    elif baseline is not None and compare is None:
        yield ChangeRecord(
            json_path=path,
            old_value=old_val,
            new_value=None,
            old_type=old_type,
            new_type=ValueType.MISSING,
            change_type=ChangeType.REMOVED,
        )
    elif old_val != new_val:
        yield ChangeRecord(
            json_path=path,
            old_value=old_val,
            new_value=new_val,
            old_type=old_type,
            new_type=new_type,
            change_type=ChangeType.MODIFIED,
        )


def diff_blocks(
    baseline: Optional[dict],
    compare: Optional[dict],
    path: str,
) -> Iterator[ChangeRecord]:
    """
    Diff two block nodes by comparing their children.
    
    Handles repeated keys by matching positionally within each key group.
    """
    if baseline is None and compare is not None:
        yield from emit_added(compare, path)
        return
    
    if baseline is not None and compare is None:
        yield from emit_removed(baseline, path)
        return
    
    baseline_children = baseline.get("children", [])
    compare_children = compare.get("children", [])
    
    baseline_index = build_child_index(baseline_children)
    compare_index = build_child_index(compare_children)
    
    all_keys = set(baseline_index.keys()) | set(compare_index.keys())
    
    for key in sorted(all_keys):  # Sorted for deterministic output
        baseline_nodes = baseline_index.get(key, [])
        compare_nodes = compare_index.get(key, [])
        
        child_path = f"{path}.{key}" if path else key
        
        # Match nodes positionally
        max_len = max(len(baseline_nodes), len(compare_nodes))
        
        for i in range(max_len):
            b_node = baseline_nodes[i] if i < len(baseline_nodes) else None
            c_node = compare_nodes[i] if i < len(compare_nodes) else None
            
            # For repeated keys, append index to path
            indexed_path = f"{child_path}[{i}]" if max_len > 1 else child_path
            
            yield from diff_nodes(b_node, c_node, indexed_path)


def emit_added(node: dict, path: str) -> Iterator[ChangeRecord]:
    """
    Emit ADDED records for a node and all its descendants.
    """
    node_type = node.get("_type")
    
    if node_type == "assignment":
        value_node = node.get("value")
        if value_node and value_node.get("_type") == "block":
            # Recurse into block
            yield from emit_added(value_node, path)
        else:
            yield ChangeRecord(
                json_path=path,
                old_value=None,
                new_value=extract_value(value_node),
                old_type=ValueType.MISSING,
                new_type=classify_value_type(value_node),
                change_type=ChangeType.ADDED,
            )
    
    elif node_type == "block":
        children = node.get("children", [])
        if not children:
            # Empty block added
            yield ChangeRecord(
                json_path=path,
                old_value=None,
                new_value="<block>",
                old_type=ValueType.MISSING,
                new_type=ValueType.BLOCK,
                change_type=ChangeType.ADDED,
            )
        else:
            child_index = build_child_index(children)
            for key in sorted(child_index.keys()):
                nodes = child_index[key]
                for i, child in enumerate(nodes):
                    child_path = f"{path}.{key}" if path else key
                    if len(nodes) > 1:
                        child_path = f"{child_path}[{i}]"
                    yield from emit_added(child, child_path)
    
    elif node_type == "value":
        yield ChangeRecord(
            json_path=path,
            old_value=None,
            new_value=extract_value(node),
            old_type=ValueType.MISSING,
            new_type=classify_value_type(node),
            change_type=ChangeType.ADDED,
        )


def emit_removed(node: dict, path: str) -> Iterator[ChangeRecord]:
    """
    Emit REMOVED records for a node and all its descendants.
    """
    node_type = node.get("_type")
    
    if node_type == "assignment":
        value_node = node.get("value")
        if value_node and value_node.get("_type") == "block":
            yield from emit_removed(value_node, path)
        else:
            yield ChangeRecord(
                json_path=path,
                old_value=extract_value(value_node),
                new_value=None,
                old_type=classify_value_type(value_node),
                new_type=ValueType.MISSING,
                change_type=ChangeType.REMOVED,
            )
    
    elif node_type == "block":
        children = node.get("children", [])
        if not children:
            yield ChangeRecord(
                json_path=path,
                old_value="<block>",
                new_value=None,
                old_type=ValueType.BLOCK,
                new_type=ValueType.MISSING,
                change_type=ChangeType.REMOVED,
            )
        else:
            child_index = build_child_index(children)
            for key in sorted(child_index.keys()):
                nodes = child_index[key]
                for i, child in enumerate(nodes):
                    child_path = f"{path}.{key}" if path else key
                    if len(nodes) > 1:
                        child_path = f"{child_path}[{i}]"
                    yield from emit_removed(child, child_path)
    
    elif node_type == "value":
        yield ChangeRecord(
            json_path=path,
            old_value=extract_value(node),
            new_value=None,
            old_type=classify_value_type(node),
            new_type=ValueType.MISSING,
            change_type=ChangeType.REMOVED,
        )


def diff_symbol_asts(
    baseline_ast: dict,
    compare_ast: dict,
    symbol_name: str,
    baseline_source: str = "baseline",
    compare_source: str = "compare",
    symbol_type: Optional[str] = None,
) -> DiffResult:
    """
    Diff two symbol AST blocks.
    
    This is the main entry point for comparing symbols.
    
    Args:
        baseline_ast: AST dict for the baseline symbol (a block node)
        compare_ast: AST dict for the compare symbol (a block node)
        symbol_name: Name of the symbol being compared
        baseline_source: Label for baseline (e.g., "vanilla", "v1.18")
        compare_source: Label for compare (e.g., "kgd", "mod_x")
        symbol_type: Optional symbol type (e.g., "maa_type", "building")
        
    Returns:
        DiffResult containing all change records
    """
    result = DiffResult(
        symbol_name=symbol_name,
        baseline_source=baseline_source,
        compare_source=compare_source,
        symbol_type=symbol_type,
    )
    
    # Diff the block contents (skip the root wrapper)
    for change in diff_blocks(baseline_ast, compare_ast, ""):
        result.changes.append(change)
    
    return result


def extract_symbol_block(root_ast: dict, symbol_name: str) -> Optional[dict]:
    """
    Extract a named symbol block from a root AST.
    
    Args:
        root_ast: Root AST (from ck3_parse_content)
        symbol_name: Name of the symbol to extract
        
    Returns:
        The block node for the symbol, or None if not found
    """
    if root_ast.get("_type") != "root":
        return None
    
    for child in root_ast.get("children", []):
        if child.get("_type") == "block" and child.get("name") == symbol_name:
            return child
    
    return None


def diff_parsed_content(
    baseline_content: str,
    compare_content: str,
    symbol_name: str,
    baseline_source: str = "baseline",
    compare_source: str = "compare",
    parser_func=None,
) -> DiffResult:
    """
    Parse and diff two PDX content strings.
    
    This is a convenience function for testing. In production, use
    diff_symbol_asts with pre-parsed ASTs from the database.
    
    Args:
        baseline_content: PDX script content for baseline
        compare_content: PDX script content for compare
        symbol_name: Name of the symbol to extract and compare
        baseline_source: Label for baseline
        compare_source: Label for compare
        parser_func: Function to parse content (for testing without MCP)
        
    Returns:
        DiffResult containing all change records
    """
    if parser_func is None:
        raise ValueError("parser_func required - provide a parse function")
    
    baseline_ast = parser_func(baseline_content)
    compare_ast = parser_func(compare_content)
    
    baseline_block = extract_symbol_block(baseline_ast, symbol_name)
    compare_block = extract_symbol_block(compare_ast, symbol_name)
    
    if baseline_block is None:
        raise ValueError(f"Symbol '{symbol_name}' not found in baseline")
    if compare_block is None:
        raise ValueError(f"Symbol '{symbol_name}' not found in compare")
    
    return diff_symbol_asts(
        baseline_block,
        compare_block,
        symbol_name,
        baseline_source,
        compare_source,
    )


# ============================================================================
# Demo / Testing
# ============================================================================

def demo():
    """
    Demonstrate the differ with sample AST structures.
    
    This uses hardcoded AST dicts to avoid MCP dependency in standalone testing.
    """
    # Sample baseline AST (simulating vanilla heavy_infantry)
    baseline = {
        "_type": "block",
        "name": "heavy_infantry",
        "children": [
            {"_type": "assignment", "key": "type", "value": {"_type": "value", "value": "heavy_infantry", "value_type": "identifier"}},
            {"_type": "assignment", "key": "damage", "value": {"_type": "value", "value": "35", "value_type": "number"}},
            {"_type": "assignment", "key": "toughness", "value": {"_type": "value", "value": "25", "value_type": "number"}},
            {"_type": "block", "name": "terrain_bonus", "children": [
                {"_type": "block", "name": "plains", "children": [
                    {"_type": "assignment", "key": "damage", "value": {"_type": "value", "value": "10", "value_type": "number"}},
                ]},
                {"_type": "block", "name": "hills", "children": [
                    {"_type": "assignment", "key": "damage", "value": {"_type": "value", "value": "-5", "value_type": "number"}},
                ]},
            ]},
            {"_type": "block", "name": "counters", "children": [
                {"_type": "assignment", "key": "light_cavalry", "value": {"_type": "value", "value": "1.5", "value_type": "number"}},
            ]},
        ]
    }
    
    # Sample compare AST (simulating KGD heavy_infantry - modified)
    compare = {
        "_type": "block",
        "name": "heavy_infantry",
        "children": [
            {"_type": "assignment", "key": "type", "value": {"_type": "value", "value": "heavy_infantry", "value_type": "identifier"}},
            {"_type": "assignment", "key": "damage", "value": {"_type": "value", "value": "30", "value_type": "number"}},  # Changed
            {"_type": "assignment", "key": "toughness", "value": {"_type": "value", "value": "28", "value_type": "number"}},  # Changed
            {"_type": "assignment", "key": "pursuit", "value": {"_type": "value", "value": "5", "value_type": "number"}},  # Added
            {"_type": "block", "name": "terrain_bonus", "children": [
                {"_type": "block", "name": "plains", "children": [
                    {"_type": "assignment", "key": "damage", "value": {"_type": "value", "value": "15", "value_type": "number"}},  # Changed
                ]},
                # hills removed
                {"_type": "block", "name": "forest", "children": [  # Added
                    {"_type": "assignment", "key": "damage", "value": {"_type": "value", "value": "-10", "value_type": "number"}},
                ]},
            ]},
            {"_type": "block", "name": "counters", "children": [
                {"_type": "assignment", "key": "light_cavalry", "value": {"_type": "value", "value": "2.0", "value_type": "number"}},  # Changed
                {"_type": "assignment", "key": "pikemen", "value": {"_type": "value", "value": "0.5", "value_type": "number"}},  # Added
            ]},
        ]
    }
    
    result = diff_symbol_asts(
        baseline,
        compare,
        symbol_name="heavy_infantry",
        baseline_source="vanilla",
        compare_source="kgd",
        symbol_type="maa_type",
    )
    
    print("=" * 70)
    print("AST Differ Demo - heavy_infantry (vanilla vs kgd)")
    print("=" * 70)
    print(f"\nSymbol: {result.symbol_name}")
    print(f"Type: {result.symbol_type}")
    print(f"Changes found: {len(result.changes)}")
    print("\n" + "-" * 70)
    
    for change in result.changes:
        print(f"\n{change.change_type.value.upper()}: {change.json_path}")
        if change.old_value is not None:
            print(f"  Old: {change.old_value} ({change.old_type.value})")
        if change.new_value is not None:
            print(f"  New: {change.new_value} ({change.new_type.value})")
    
    print("\n" + "=" * 70)
    print("JSON Output:")
    print("=" * 70)
    print(result.to_json())


if __name__ == "__main__":
    demo()
