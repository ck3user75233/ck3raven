"""
Tests for OVERRIDE merge policy (traditions, events, decisions, etc.)
"""

import pytest
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Tuple

from ck3raven.parser import parse_file
from ck3raven.parser.parser import BlockNode, AssignmentNode, RootNode
from ck3raven.resolver import MergePolicy, get_policy_for_path


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def extract_block_keys(ast: RootNode, prefix: str = None) -> list:
    """Extract all top-level block names from an AST."""
    keys = []
    for child in ast.children:
        if isinstance(child, BlockNode):
            if prefix is None or child.name.startswith(prefix):
                keys.append(child.name)
    return keys


def get_block_by_name(ast: RootNode, name: str) -> BlockNode:
    """Find a specific block by name in an AST."""
    for child in ast.children:
        if isinstance(child, BlockNode) and child.name == name:
            return child
    return None


def get_assignment_value(block: BlockNode, key: str):
    """Get the value of an assignment within a block."""
    for child in block.children:
        if isinstance(child, AssignmentNode) and child.key == key:
            return child.value
    return None


def get_sub_block(block: BlockNode, name: str) -> BlockNode:
    """Get a sub-block by name within a block."""
    for child in block.children:
        if isinstance(child, BlockNode) and child.name == name:
            return child
    return None


# =============================================================================
# OVERRIDE RESOLVER IMPLEMENTATION
# =============================================================================

@dataclass
class ResolvedDefinition:
    """A resolved definition with provenance."""
    key: str
    source: str  # filename
    block: BlockNode
    overridden_by: List[str] = None  # list of sources that were overridden
    
    def __post_init__(self):
        if self.overridden_by is None:
            self.overridden_by = []


def resolve_override(file_asts: Dict[str, 'RootNode'], key_prefix: str = None) -> Dict[str, ResolvedDefinition]:
    """
    Resolve definitions using OVERRIDE policy.
    
    Args:
        file_asts: Dict of {filename: parsed_ast} in load order
        key_prefix: Optional prefix filter (e.g., "tradition_")
    
    Returns:
        Dict of {key: ResolvedDefinition}
    """
    all_definitions = {}  # key -> [(source, block), ...]
    
    # Collect all definitions in order
    for filename, ast in file_asts.items():
        for child in ast.children:
            if isinstance(child, BlockNode):
                if key_prefix is None or child.name.startswith(key_prefix):
                    key = child.name
                    if key not in all_definitions:
                        all_definitions[key] = []
                    all_definitions[key].append((filename, child))
    
    # Resolve: last wins
    resolved = {}
    for key, definitions in all_definitions.items():
        winner_source, winner_block = definitions[-1]
        overridden = [src for src, _ in definitions[:-1]]
        resolved[key] = ResolvedDefinition(
            key=key,
            source=winner_source,
            block=winner_block,
            overridden_by=overridden
        )
    
    return resolved


# =============================================================================
# TESTS
# =============================================================================

class TestOverridePolicy:
    """Test OVERRIDE merge policy configuration."""
    
    def test_traditions_use_override(self):
        """Traditions folder should use OVERRIDE policy."""
        policy = get_policy_for_path("common/culture/traditions/test.txt")
        assert policy == MergePolicy.OVERRIDE
    
    def test_events_use_override(self):
        """Events folder should use OVERRIDE policy."""
        policy = get_policy_for_path("events/test.txt")
        assert policy == MergePolicy.OVERRIDE
    
    def test_decisions_use_override(self):
        """Decisions folder should use OVERRIDE policy."""
        policy = get_policy_for_path("common/decisions/test.txt")
        assert policy == MergePolicy.OVERRIDE
    
    def test_traits_use_override(self):
        """Traits folder should use OVERRIDE policy."""
        policy = get_policy_for_path("common/traits/test.txt")
        assert policy == MergePolicy.OVERRIDE


class TestOverrideResolution:
    """Test OVERRIDE resolution logic."""
    
    def test_single_definition_kept(self, parsed_traditions):
        """A single definition should be kept as-is."""
        resolved = resolve_override(parsed_traditions, "tradition_")
        
        # tradition_seafaring only appears in vanilla
        seafaring = resolved.get("tradition_seafaring")
        assert seafaring is not None
        assert seafaring.source == "01_vanilla_traditions.txt"
        assert len(seafaring.overridden_by) == 0
    
    def test_last_definition_wins(self, parsed_traditions):
        """When multiple definitions exist, last should win."""
        resolved = resolve_override(parsed_traditions, "tradition_")
        
        # tradition_mountain_homes appears in all 3 files
        mountain = resolved.get("tradition_mountain_homes")
        assert mountain is not None
        assert mountain.source == "03_mod_b_traditions.txt"  # Last wins
    
    def test_overridden_sources_tracked(self, parsed_traditions):
        """Should track which sources were overridden."""
        resolved = resolve_override(parsed_traditions, "tradition_")
        
        mountain = resolved.get("tradition_mountain_homes")
        assert len(mountain.overridden_by) == 2
        assert "01_vanilla_traditions.txt" in mountain.overridden_by
        assert "02_mod_a_traditions.txt" in mountain.overridden_by
    
    def test_two_source_override(self, parsed_traditions):
        """Two-source conflict should pick the later one."""
        resolved = resolve_override(parsed_traditions, "tradition_")
        
        # tradition_warrior_culture: vanilla + mod_b
        warrior = resolved.get("tradition_warrior_culture")
        assert warrior is not None
        assert warrior.source == "03_mod_b_traditions.txt"
        assert warrior.overridden_by == ["01_vanilla_traditions.txt"]
    
    def test_new_mod_definition_included(self, parsed_traditions):
        """New definitions from mods should be included."""
        resolved = resolve_override(parsed_traditions, "tradition_")
        
        # tradition_mod_a_new only in mod A
        mod_a_new = resolved.get("tradition_mod_a_new")
        assert mod_a_new is not None
        assert mod_a_new.source == "02_mod_a_traditions.txt"
        assert len(mod_a_new.overridden_by) == 0
    
    def test_total_resolved_count(self, parsed_traditions):
        """Should have correct total count of unique traditions."""
        resolved = resolve_override(parsed_traditions, "tradition_")
        
        # 3 from vanilla + 1 new from mod_a = 4 unique
        assert len(resolved) == 4
        expected_keys = {
            "tradition_mountain_homes",
            "tradition_warrior_culture", 
            "tradition_seafaring",
            "tradition_mod_a_new"
        }
        assert set(resolved.keys()) == expected_keys


class TestOverrideBlockContent:
    """Test that the winning block has correct content."""
    
    def test_winner_has_mod_b_content(self, parsed_traditions):
        """Winner block should have Mod B's content, not vanilla."""
        resolved = resolve_override(parsed_traditions, "tradition_")
        
        mountain = resolved["tradition_mountain_homes"]
        
        # Mod B added a cost block that vanilla doesn't have
        cost = get_sub_block(mountain.block, "cost")
        assert cost is not None, "Mod B's cost block should be present"
    
    def test_winner_has_modified_values(self, parsed_traditions):
        """Winner block should have Mod B's modified values."""
        resolved = resolve_override(parsed_traditions, "tradition_")
        
        mountain = resolved["tradition_mountain_homes"]
        province_mod = get_sub_block(mountain.block, "province_modifier")
        assert province_mod is not None
        
        # Mod B set defender_advantage = 8
        defender = get_assignment_value(province_mod, "defender_advantage")
        assert defender is not None
        assert "8" in str(defender)  # Mod B value
    
    def test_warrior_culture_has_nerf(self, parsed_traditions):
        """Mod B's nerfed warrior_culture should win."""
        resolved = resolve_override(parsed_traditions, "tradition_")
        
        warrior = resolved["tradition_warrior_culture"]
        char_mod = get_sub_block(warrior.block, "character_modifier")
        
        # Mod B nerfed prowess from 2 to 1
        prowess = get_assignment_value(char_mod, "prowess")
        assert prowess is not None
        assert "1" in str(prowess)  # Nerfed value


class TestOverrideLoadOrder:
    """Test that load order determines winner."""
    
    def test_file_sort_order_matters(self, traditions_dir):
        """Files are processed in sorted order (01, 02, 03)."""
        files = sorted(traditions_dir.glob("*.txt"))
        names = [f.name for f in files]
        
        assert names[0].startswith("01_")
        assert names[1].startswith("02_")
        assert names[2].startswith("03_")
    
    def test_zzz_prefix_loads_last(self):
        """In real CK3, zzz_ prefix ensures loading last."""
        # This is why compatibility patches use zzz_ prefixes
        files = ["00_vanilla.txt", "mod_stuff.txt", "zzz_override.txt"]
        sorted_files = sorted(files)
        assert sorted_files[-1] == "zzz_override.txt"
