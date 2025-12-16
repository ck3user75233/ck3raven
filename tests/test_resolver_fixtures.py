"""
Test resolver with controlled fixture files.

Run: python -m tests.test_resolver_fixtures
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.parser import parse_file
from ck3raven.parser.parser import BlockNode, AssignmentNode
from dataclasses import dataclass, field
from typing import List, Dict, Any


FIXTURES = Path(__file__).parent / "fixtures"


# =============================================================================
# AST PRETTY PRINTER
# =============================================================================

def ast_to_dict(node, depth=0) -> dict:
    """Convert AST node to inspectable dict."""
    if isinstance(node, BlockNode):
        return {
            "type": "Block",
            "name": node.name,
            "line": node.line,
            "children": [ast_to_dict(c, depth+1) for c in node.children]
        }
    elif isinstance(node, AssignmentNode):
        return {
            "type": "Assignment",
            "key": node.key,
            "op": node.operator,
            "value": ast_to_dict(node.value, depth+1) if hasattr(node.value, 'children') else str(node.value)
        }
    elif hasattr(node, 'value'):
        return {"type": "Value", "value": str(node.value)}
    elif hasattr(node, 'children'):
        return {"type": "Container", "children": [ast_to_dict(c, depth+1) for c in node.children]}
    else:
        return {"type": "Unknown", "repr": repr(node)}


def print_block_summary(block: BlockNode, indent=0):
    """Print a summary of a block's structure."""
    prefix = "  " * indent
    print(f"{prefix}{block.name} (line {block.line}):")
    for child in block.children:
        if isinstance(child, BlockNode):
            print(f"{prefix}  {child.name} = {{ ... }}")
        elif isinstance(child, AssignmentNode):
            val = child.value
            if isinstance(val, BlockNode):
                print(f"{prefix}  {child.key} = {{ ... }}")
            else:
                print(f"{prefix}  {child.key} = {val}")


# =============================================================================
# TRADITIONS TEST (OVERRIDE POLICY)
# =============================================================================

def test_traditions():
    print("=" * 70)
    print("TRADITIONS TEST - OVERRIDE POLICY")
    print("=" * 70)
    print("\nExpected behavior: Last definition wins completely")
    print("-" * 70)
    
    traditions_dir = FIXTURES / "traditions"
    files = sorted(traditions_dir.glob("*.txt"))
    
    # Parse each file and show contents
    all_definitions = {}  # key -> [(source, block), ...]
    
    for file_path in files:
        print(f"\n>>> Parsing: {file_path.name}")
        ast = parse_file(str(file_path))
        
        for child in ast.children:
            if isinstance(child, BlockNode) and child.name.startswith("tradition_"):
                key = child.name
                if key not in all_definitions:
                    all_definitions[key] = []
                all_definitions[key].append((file_path.name, child))
                print_block_summary(child, indent=1)
    
    # Resolve using OVERRIDE
    print("\n" + "=" * 70)
    print("RESOLUTION (OVERRIDE - Last Wins)")
    print("=" * 70)
    
    resolved = {}
    conflicts = {}
    
    for key, definitions in all_definitions.items():
        if len(definitions) > 1:
            conflicts[key] = definitions
        # Last wins
        winner_source, winner_block = definitions[-1]
        resolved[key] = (winner_source, winner_block)
    
    print(f"\nTotal traditions: {len(resolved)}")
    print(f"Conflicts (multiple definitions): {len(conflicts)}")
    
    for key, defs in sorted(conflicts.items()):
        winner_source, _ = resolved[key]
        print(f"\n  {key}:")
        for i, (src, block) in enumerate(defs):
            marker = " <- WINNER" if src == winner_source else " (overridden)"
            print(f"    [{i+1}] {src}{marker}")
    
    print("\n" + "-" * 70)
    print("FINAL RESOLVED STATE:")
    print("-" * 70)
    for key, (source, block) in sorted(resolved.items()):
        print(f"\n  {key} (from {source}):")
        print_block_summary(block, indent=2)


# =============================================================================
# ON_ACTIONS TEST (CONTAINER_MERGE POLICY)
# =============================================================================

@dataclass
class OnActionMerged:
    key: str
    events: List[str] = field(default_factory=list)
    on_actions: List[str] = field(default_factory=list)
    random_events: List[tuple] = field(default_factory=list)
    trigger_sources: List[str] = field(default_factory=list)
    effect_sources: List[str] = field(default_factory=list)
    trigger_winner: BlockNode = None
    effect_winner: BlockNode = None
    sources: List[str] = field(default_factory=list)


def extract_list_items(block: BlockNode) -> List[str]:
    """Extract event/on_action names from a list block."""
    items = []
    for child in block.children:
        if isinstance(child, AssignmentNode):
            # Format: weight = event_name
            items.append(f"{child.key}={child.value}")
        elif hasattr(child, 'value'):
            items.append(str(child.value))
        elif hasattr(child, 'name'):
            items.append(child.name)
    return items


def test_on_actions():
    print("\n" + "=" * 70)
    print("ON_ACTIONS TEST - CONTAINER_MERGE POLICY")
    print("=" * 70)
    print("\nExpected behavior:")
    print("  - events/on_actions/random_events: APPEND from all sources")
    print("  - trigger/effect: CONFLICT, last definition wins")
    print("-" * 70)
    
    on_actions_dir = FIXTURES / "on_actions"
    files = sorted(on_actions_dir.glob("*.txt"))
    
    # Parse each file and show contents
    all_definitions = {}  # key -> [(source, block), ...]
    
    for file_path in files:
        print(f"\n>>> Parsing: {file_path.name}")
        ast = parse_file(str(file_path))
        
        for child in ast.children:
            if isinstance(child, BlockNode) and child.name.startswith("on_"):
                key = child.name
                if key not in all_definitions:
                    all_definitions[key] = []
                all_definitions[key].append((file_path.name, child))
                print_block_summary(child, indent=1)
    
    # Resolve using CONTAINER_MERGE
    print("\n" + "=" * 70)
    print("RESOLUTION (CONTAINER_MERGE)")
    print("=" * 70)
    
    resolved = {}
    
    for key, definitions in all_definitions.items():
        merged = OnActionMerged(key=key)
        
        for source, block in definitions:
            merged.sources.append(source)
            
            for child in block.children:
                if isinstance(child, BlockNode):
                    if child.name == "events":
                        items = extract_list_items(child)
                        merged.events.extend(items)
                    elif child.name == "on_actions":
                        items = extract_list_items(child)
                        merged.on_actions.extend(items)
                    elif child.name == "random_events":
                        items = extract_list_items(child)
                        merged.random_events.extend(items)
                    elif child.name == "trigger":
                        merged.trigger_sources.append(source)
                        merged.trigger_winner = child
                    elif child.name == "effect":
                        merged.effect_sources.append(source)
                        merged.effect_winner = child
        
        resolved[key] = merged
    
    print(f"\nTotal on_actions: {len(resolved)}")
    
    # Show detailed results
    for key, merged in sorted(resolved.items()):
        has_conflict = len(merged.trigger_sources) > 1 or len(merged.effect_sources) > 1
        multi_source = len(merged.sources) > 1
        
        if multi_source or has_conflict:
            print(f"\n  {key}:")
            print(f"    Sources: {merged.sources}")
            
            if merged.events:
                print(f"    Merged events ({len(merged.events)}): {merged.events}")
            if merged.on_actions:
                print(f"    Merged on_actions: {merged.on_actions}")
            if merged.random_events:
                print(f"    Merged random_events: {merged.random_events}")
            
            if len(merged.trigger_sources) > 1:
                print(f"    TRIGGER CONFLICT: {merged.trigger_sources}")
                print(f"      Winner: {merged.trigger_sources[-1]}")
            elif merged.trigger_sources:
                print(f"    Trigger from: {merged.trigger_sources[0]}")
                
            if len(merged.effect_sources) > 1:
                print(f"    EFFECT CONFLICT: {merged.effect_sources}")
                print(f"      Winner: {merged.effect_sources[-1]}")
            elif merged.effect_sources:
                print(f"    Effect from: {merged.effect_sources[0]}")
    
    print("\n" + "-" * 70)
    print("SINGLE-SOURCE ON_ACTIONS (no merge needed):")
    print("-" * 70)
    for key, merged in sorted(resolved.items()):
        if len(merged.sources) == 1:
            print(f"  {key} (from {merged.sources[0]})")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    test_traditions()
    test_on_actions()
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
