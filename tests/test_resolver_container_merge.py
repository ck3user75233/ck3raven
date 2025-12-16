"""
Tests for CONTAINER_MERGE policy (on_actions).
"""

import pytest
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from ck3raven.parser import parse_file
from ck3raven.parser.parser import BlockNode, AssignmentNode, RootNode
from ck3raven.resolver import MergePolicy, get_policy_for_path


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_block_by_name(ast: RootNode, name: str) -> BlockNode:
    """Find a specific block by name in an AST."""
    for child in ast.children:
        if isinstance(child, BlockNode) and child.name == name:
            return child
    return None


def get_sub_block(block: BlockNode, name: str) -> BlockNode:
    """Get a sub-block by name within a block."""
    for child in block.children:
        if isinstance(child, BlockNode) and child.name == name:
            return child
    return None


# =============================================================================
# CONTAINER_MERGE RESOLVER IMPLEMENTATION
# =============================================================================

# Sub-block policies
APPEND_BLOCKS = {'events', 'on_actions', 'random_events', 'random_on_actions',
                 'first_valid', 'first_valid_on_action'}
SINGLE_SLOT_BLOCKS = {'effect', 'trigger', 'weight_multiplier', 'fallback'}


@dataclass
class MergedOnAction:
    """Result of merging an on_action across multiple sources."""
    key: str
    sources: List[str] = field(default_factory=list)
    
    # Appended lists
    events: List[str] = field(default_factory=list)
    on_actions: List[str] = field(default_factory=list)
    random_events: List[str] = field(default_factory=list)
    
    # Single-slot blocks (last wins)
    trigger_sources: List[str] = field(default_factory=list)
    effect_sources: List[str] = field(default_factory=list)
    trigger_block: Optional[BlockNode] = None
    effect_block: Optional[BlockNode] = None
    
    @property
    def has_trigger_conflict(self) -> bool:
        return len(self.trigger_sources) > 1
    
    @property
    def has_effect_conflict(self) -> bool:
        return len(self.effect_sources) > 1
    
    @property
    def trigger_winner(self) -> Optional[str]:
        return self.trigger_sources[-1] if self.trigger_sources else None
    
    @property
    def effect_winner(self) -> Optional[str]:
        return self.effect_sources[-1] if self.effect_sources else None


def extract_list_items(block: BlockNode) -> List[str]:
    """Extract items from a list block like events = { evt.1 evt.2 }."""
    items = []
    for child in block.children:
        if isinstance(child, AssignmentNode):
            # Weighted format: 100 = event_name
            items.append(f"{child.key}={child.value}")
        elif hasattr(child, 'value'):
            items.append(str(child.value))
        elif hasattr(child, 'name'):
            items.append(child.name)
    return items


def resolve_container_merge(file_asts: Dict[str, 'RootNode'], key_prefix: str = "on_") -> Dict[str, MergedOnAction]:
    """
    Resolve on_actions using CONTAINER_MERGE policy.
    
    Args:
        file_asts: Dict of {filename: parsed_ast} in load order
        key_prefix: Prefix for matching keys (default "on_")
    
    Returns:
        Dict of {key: MergedOnAction}
    """
    all_definitions = {}  # key -> [(source, block), ...]
    
    # Collect all definitions in order
    for filename, ast in file_asts.items():
        for child in ast.children:
            if isinstance(child, BlockNode):
                if child.name.startswith(key_prefix):
                    key = child.name
                    if key not in all_definitions:
                        all_definitions[key] = []
                    all_definitions[key].append((filename, child))
    
    # Merge each on_action
    resolved = {}
    for key, definitions in all_definitions.items():
        merged = MergedOnAction(key=key)
        
        for source, block in definitions:
            merged.sources.append(source)
            
            for child in block.children:
                if isinstance(child, BlockNode):
                    name = child.name
                    
                    if name == "events":
                        items = extract_list_items(child)
                        merged.events.extend(items)
                    elif name == "on_actions":
                        items = extract_list_items(child)
                        merged.on_actions.extend(items)
                    elif name == "random_events":
                        items = extract_list_items(child)
                        merged.random_events.extend(items)
                    elif name == "trigger":
                        merged.trigger_sources.append(source)
                        merged.trigger_block = child
                    elif name == "effect":
                        merged.effect_sources.append(source)
                        merged.effect_block = child
        
        resolved[key] = merged
    
    return resolved


# =============================================================================
# TESTS
# =============================================================================

class TestContainerMergePolicy:
    """Test CONTAINER_MERGE policy configuration."""
    
    def test_on_actions_use_container_merge(self):
        """on_action folder should use CONTAINER_MERGE policy."""
        policy = get_policy_for_path("common/on_action/test.txt")
        assert policy == MergePolicy.CONTAINER_MERGE


class TestContainerMergeAppendLists:
    """Test that list blocks are appended correctly."""
    
    def test_events_appended_from_all_sources(self, parsed_on_actions):
        """Events from all sources should be appended together."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        birthday = resolved["on_birthday"]
        
        # Vanilla: birthday.0001, birthday.0002
        # Mod A: mod_a_birthday.0001, mod_a_birthday.0002, mod_a_birthday.0003
        # Mod B: mod_b_birthday.0001
        assert len(birthday.events) == 6
        
        # Check order (vanilla first, then mods in order)
        assert "birthday.0001" in birthday.events[0]
        assert "mod_b_birthday" in birthday.events[-1]
    
    def test_on_actions_sublists_appended(self, parsed_on_actions):
        """on_actions sublists should be appended."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        death = resolved["on_death"]
        
        # Vanilla: on_heir_inherits
        # Mod A: mod_a_special_inheritance
        assert len(death.on_actions) == 2
        assert "on_heir_inherits" in death.on_actions[0]
        assert "mod_a_special_inheritance" in death.on_actions[1]
    
    def test_random_events_appended(self, parsed_on_actions):
        """random_events should be appended."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        birthday = resolved["on_birthday"]
        
        # Only Mod B has random_events
        assert len(birthday.random_events) == 2
    
    def test_events_from_two_sources(self, parsed_on_actions):
        """Events should append even with just two sources."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        war = resolved["on_war_started"]
        
        # Vanilla: war.0001, war.0002
        # Mod B: mod_b_war.0001, mod_b_war.0002
        assert len(war.events) == 4


class TestContainerMergeSingleSlot:
    """Test that single-slot blocks use last-wins."""
    
    def test_trigger_conflict_detected(self, parsed_on_actions):
        """Trigger conflicts should be detected."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        birthday = resolved["on_birthday"]
        assert birthday.has_trigger_conflict
        assert len(birthday.trigger_sources) == 2  # vanilla + mod_a
    
    def test_trigger_last_wins(self, parsed_on_actions):
        """Last trigger definition should win."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        birthday = resolved["on_birthday"]
        # Mod A is last to define trigger (Mod B doesn't have one)
        assert birthday.trigger_winner == "02_mod_a_on_actions.txt"
    
    def test_effect_conflict_detected(self, parsed_on_actions):
        """Effect conflicts should be detected."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        birthday = resolved["on_birthday"]
        assert birthday.has_effect_conflict
        assert len(birthday.effect_sources) == 3  # all three files
    
    def test_effect_last_wins(self, parsed_on_actions):
        """Last effect definition should win."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        birthday = resolved["on_birthday"]
        assert birthday.effect_winner == "03_mod_b_on_actions.txt"
    
    def test_no_conflict_when_single_source(self, parsed_on_actions):
        """No conflict when only one source defines effect."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        war = resolved["on_war_started"]
        # Only Mod B defines effect for war_started
        assert not war.has_effect_conflict
        assert war.effect_winner == "03_mod_b_on_actions.txt"


class TestContainerMergeSourceTracking:
    """Test source provenance tracking."""
    
    def test_all_sources_tracked(self, parsed_on_actions):
        """All contributing sources should be tracked."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        birthday = resolved["on_birthday"]
        assert len(birthday.sources) == 3
        assert "01_vanilla_on_actions.txt" in birthday.sources
        assert "02_mod_a_on_actions.txt" in birthday.sources
        assert "03_mod_b_on_actions.txt" in birthday.sources
    
    def test_single_source_on_action(self, parsed_on_actions):
        """Single-source on_actions should have one source."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        # on_mod_a_special only in mod A
        mod_a = resolved["on_mod_a_special"]
        assert len(mod_a.sources) == 1
        assert mod_a.sources[0] == "02_mod_a_on_actions.txt"
    
    def test_two_source_on_action(self, parsed_on_actions):
        """Two-source on_actions should track both."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        death = resolved["on_death"]
        assert len(death.sources) == 2


class TestContainerMergeTotalCounts:
    """Test aggregate counts are correct."""
    
    def test_total_on_actions(self, parsed_on_actions):
        """Should have correct total unique on_actions."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        # on_birthday, on_death, on_war_started, on_mod_a_special, on_mod_b_unique
        assert len(resolved) == 5
    
    def test_multi_source_count(self, parsed_on_actions):
        """Count on_actions with multiple sources."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        multi_source = [m for m in resolved.values() if len(m.sources) > 1]
        assert len(multi_source) == 3  # birthday, death, war_started
    
    def test_conflict_count(self, parsed_on_actions):
        """Count on_actions with effect/trigger conflicts."""
        resolved = resolve_container_merge(parsed_on_actions)
        
        with_effect_conflict = [m for m in resolved.values() if m.has_effect_conflict]
        assert len(with_effect_conflict) == 1  # only birthday
        
        with_trigger_conflict = [m for m in resolved.values() if m.has_trigger_conflict]
        assert len(with_trigger_conflict) == 1  # only birthday
