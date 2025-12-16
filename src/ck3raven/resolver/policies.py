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
    """Configuration for how a content type handles merging."""
    
    # Glob pattern for matching files
    file_glob: str
    
    # Regex pattern for identifying container keys (e.g., "^tradition_")
    key_pattern: str
    
    # Primary merge strategy
    policy: MergePolicy
    
    # For CONTAINER_MERGE: rules for each sub-block type
    sub_rules: Optional[Dict[str, SubBlockPolicy]] = None
    
    # Human-readable description
    description: str = ""


# Default content type configurations
CONTENT_TYPE_CONFIGS: Dict[str, ContentTypeConfig] = {
    "tradition": ContentTypeConfig(
        file_glob="common/culture/traditions/*.txt",
        key_pattern=r"^tradition_",
        policy=MergePolicy.OVERRIDE,
        description="Cultural traditions - last definition wins"
    ),
    
    "culture": ContentTypeConfig(
        file_glob="common/culture/cultures/*.txt",
        key_pattern=r"^[a-z_]+$",
        policy=MergePolicy.OVERRIDE,
        description="Cultures - last definition wins"
    ),
    
    "on_action": ContentTypeConfig(
        file_glob="common/on_action/*.txt",
        key_pattern=r"^on_",
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
        file_glob="events/*.txt",
        key_pattern=r"^[a-zA-Z0-9_.]+$",
        policy=MergePolicy.OVERRIDE,
        description="Events - last definition wins"
    ),
    
    "decision": ContentTypeConfig(
        file_glob="common/decisions/*.txt",
        key_pattern=r"^[a-z_]+$",
        policy=MergePolicy.OVERRIDE,
        description="Decisions - last definition wins"
    ),
    
    "scripted_effect": ContentTypeConfig(
        file_glob="common/scripted_effects/*.txt",
        key_pattern=r"^[a-z_]+$",
        policy=MergePolicy.OVERRIDE,
        description="Scripted effects - last definition wins"
    ),
    
    "scripted_trigger": ContentTypeConfig(
        file_glob="common/scripted_triggers/*.txt",
        key_pattern=r"^[a-z_]+$",
        policy=MergePolicy.OVERRIDE,
        description="Scripted triggers - last definition wins"
    ),
    
    "trait": ContentTypeConfig(
        file_glob="common/traits/*.txt",
        key_pattern=r"^[a-z_]+$",
        policy=MergePolicy.OVERRIDE,
        description="Traits - last definition wins"
    ),
    
    "localization": ContentTypeConfig(
        file_glob="localization/**/*.yml",
        key_pattern=r"^[a-zA-Z0-9_]+:",
        policy=MergePolicy.PER_KEY_OVERRIDE,
        description="Localization - per-key override"
    ),
    
    "defines": ContentTypeConfig(
        file_glob="common/defines/*.txt",
        key_pattern=r"^[A-Z][A-Za-z]+$",
        policy=MergePolicy.PER_KEY_OVERRIDE,
        description="Defines - per-key override within categories"
    ),
    
    "gui_type": ContentTypeConfig(
        file_glob="gui/**/*.gui",
        key_pattern=r"^type\s+",
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
