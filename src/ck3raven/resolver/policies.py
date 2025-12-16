"""
Merge/Override Policies for CK3 Content Types

Defines the 4 core merge policies used by CK3's engine.
"""

from enum import Enum, auto
from dataclasses import dataclass
from typing import Dict, List, Any, Optional


class MergePolicy(Enum):
    """The 4 core merge policies in CK3."""
    
    # Last definition wins completely (~95% of content)
    OVERRIDE = auto()
    
    # Container merges, sublists append, single-blocks conflict (on_actions)
    CONTAINER_MERGE = auto()
    
    # Each key is independent, last definition per key wins (localization, defines)
    PER_KEY_OVERRIDE = auto()
    
    # First definition wins (GUI types/templates only)
    FIOS = auto()


class SubBlockPolicy(Enum):
    """How sub-blocks within CONTAINER_MERGE containers are handled."""
    
    # All entries from all files are appended (events = {}, on_actions = {})
    APPEND_LIST = auto()
    
    # Only ONE slot allowed per container, last wins (effect = {}, trigger = {})
    SINGLE_SLOT_CONFLICT = auto()
    
    # Only ONE slot, last wins, no conflict warning
    SINGLE_SLOT_OVERRIDE = auto()


@dataclass
class ContentTypeConfig:
    """
    Configuration for how a content type handles merging.
    
    Note: Key identification is done via parsed AST (BlockNode.name),
    not via pattern matching. The folder path determines the policy.
    """
    
    # Folder path for matching (e.g., "common/culture/traditions")
    folder_path: str
    
    # File extension filter
    file_extension: str = ".txt"
    
    # Primary merge strategy
    policy: MergePolicy = MergePolicy.OVERRIDE
    
    # For CONTAINER_MERGE: rules for each sub-block type
    sub_rules: Optional[Dict[str, SubBlockPolicy]] = None
    
    # Human-readable description
    description: str = ""


# Default content type configurations
CONTENT_TYPE_CONFIGS: Dict[str, ContentTypeConfig] = {
    "tradition": ContentTypeConfig(
        folder_path="common/culture/traditions",
        description="Cultural traditions - last definition wins"
    ),
    
    "culture": ContentTypeConfig(
        folder_path="common/culture/cultures",
        description="Cultures - last definition wins"
    ),
    
    "on_action": ContentTypeConfig(
        folder_path="common/on_action",
        policy=MergePolicy.CONTAINER_MERGE,
        sub_rules={
            "events": SubBlockPolicy.APPEND_LIST,
            "on_actions": SubBlockPolicy.APPEND_LIST,
            "random_events": SubBlockPolicy.APPEND_LIST,
            "random_on_actions": SubBlockPolicy.APPEND_LIST,
            "first_valid": SubBlockPolicy.APPEND_LIST,
            "first_valid_on_action": SubBlockPolicy.APPEND_LIST,
            "effect": SubBlockPolicy.SINGLE_SLOT_CONFLICT,
            "trigger": SubBlockPolicy.SINGLE_SLOT_CONFLICT,
            "weight_multiplier": SubBlockPolicy.SINGLE_SLOT_OVERRIDE,
            "fallback": SubBlockPolicy.SINGLE_SLOT_OVERRIDE,
        },
        description="On-actions - container merges, events append, effect/trigger conflict"
    ),
    
    "event": ContentTypeConfig(
        folder_path="events",
        description="Events - last definition wins"
    ),
    
    "decision": ContentTypeConfig(
        folder_path="common/decisions",
        description="Decisions - last definition wins"
    ),
    
    "scripted_effect": ContentTypeConfig(
        folder_path="common/scripted_effects",
        description="Scripted effects - last definition wins"
    ),
    
    "scripted_trigger": ContentTypeConfig(
        folder_path="common/scripted_triggers",
        description="Scripted triggers - last definition wins"
    ),
    
    "trait": ContentTypeConfig(
        folder_path="common/traits",
        description="Traits - last definition wins"
    ),
    
    "localization": ContentTypeConfig(
        folder_path="localization",
        file_extension=".yml",
        policy=MergePolicy.PER_KEY_OVERRIDE,
        description="Localization - per-key override"
    ),
    
    "defines": ContentTypeConfig(
        folder_path="common/defines",
        policy=MergePolicy.PER_KEY_OVERRIDE,
        description="Defines - per-key override within categories"
    ),
    
    "gui_type": ContentTypeConfig(
        folder_path="gui",
        file_extension=".gui",
        policy=MergePolicy.FIOS,
        description="GUI types - first definition wins (use 00_ prefix)"
    ),
}


def get_content_config(content_type: str) -> Optional[ContentTypeConfig]:
    """Get the configuration for a content type."""
    return CONTENT_TYPE_CONFIGS.get(content_type)


def get_policy_for_folder(folder_path: str) -> MergePolicy:
    """
    Determine the merge policy based on folder path.
    
    Args:
        folder_path: Relative path like "common/culture/traditions"
    
    Returns:
        The appropriate MergePolicy for that folder
    """
    # Normalize path separators
    folder = folder_path.replace("\\", "/").strip("/")
    
    # Special cases
    if folder.startswith("common/on_action"):
        return MergePolicy.CONTAINER_MERGE
    if folder.startswith("common/defines"):
        return MergePolicy.PER_KEY_OVERRIDE
    if folder.startswith("localization"):
        return MergePolicy.PER_KEY_OVERRIDE
    if folder.startswith("gui"):
        return MergePolicy.FIOS
    
    # Default for common/ and most other folders
    return MergePolicy.OVERRIDE
