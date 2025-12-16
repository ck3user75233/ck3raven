"""
CK3 Content Types Registry

Comprehensive mapping of all CK3 content types with their folder paths and merge policies.
This is the authoritative source for understanding how CK3 handles file merging.

Based on extensive testing with the CK3 engine.
"""

from dataclasses import dataclass
from typing import Optional, Dict
from .policies import MergePolicy


@dataclass
class ContentType:
    """Describes a content type and how to process it."""
    
    name: str                   # Display name ("Traditions", "Events", etc.)
    relative_path: str          # Path relative to mod root ("common/culture/traditions")
    key_prefix: Optional[str] = None  # Prefix filter for valid keys (None = all)
    merge_policy: MergePolicy = MergePolicy.OVERRIDE  # How to handle conflicts
    file_pattern: str = "*.txt" # Glob pattern for files
    
    @property
    def folder(self) -> str:
        """Return the relative folder path."""
        return self.relative_path


# =========================================================================
# COMPREHENSIVE CK3 CONTENT TYPES
# Organized by folder structure
# =========================================================================

CONTENT_TYPES: Dict[str, ContentType] = {
    # =========================================
    # COMMON FOLDER - Override policy (last wins)
    # =========================================
    
    # Accolades
    "accolade_icons": ContentType("Accolade Icons", "common/accolade_icons"),
    "accolade_names": ContentType("Accolade Names", "common/accolade_names"),
    "accolade_types": ContentType("Accolade Types", "common/accolade_types"),
    
    # Achievements
    "achievements": ContentType("Achievements", "common/achievements"),
    
    # Activities
    "activities": ContentType("Activities", "common/activities"),
    "activity_locales": ContentType("Activity Locales", "common/activity_locales"),
    "activity_types": ContentType("Activity Types", "common/activity_types"),
    
    # AI
    "ai_goaltypes": ContentType("AI Goal Types", "common/ai_goaltypes"),
    "ai_war_stances": ContentType("AI War Stances", "common/ai_war_stances"),
    
    # Artifacts
    "artifacts": ContentType("Artifacts", "common/artifacts"),
    "artifact_blueprints": ContentType("Artifact Blueprints", "common/artifact_blueprints"),
    "artifact_feature_groups": ContentType("Artifact Feature Groups", "common/artifact_feature_groups"),
    "artifact_features": ContentType("Artifact Features", "common/artifact_features"),
    "artifact_slots": ContentType("Artifact Slots", "common/artifact_slots"),
    "artifact_types": ContentType("Artifact Types", "common/artifact_types"),
    "artifact_visuals": ContentType("Artifact Visuals", "common/artifact_visuals"),
    
    # Bookmarks
    "bookmarks": ContentType("Bookmarks", "common/bookmarks"),
    "bookmark_portraits": ContentType("Bookmark Portraits", "common/bookmark_portraits"),
    
    # Buildings
    "buildings": ContentType("Buildings", "common/buildings"),
    
    # Casus Belli
    "casus_belli_groups": ContentType("CB Groups", "common/casus_belli_groups"),
    "casus_belli_types": ContentType("CB Types", "common/casus_belli_types"),
    
    # Characters
    "character_backgrounds": ContentType("Character Backgrounds", "common/character_backgrounds"),
    "character_interactions": ContentType("Character Interactions", "common/character_interactions"),
    "character_interaction_categories": ContentType("Interaction Categories", "common/character_interaction_categories"),
    "character_memory_types": ContentType("Memory Types", "common/character_memory_types"),
    
    # Coat of Arms
    "coat_of_arms": ContentType("Coat of Arms", "common/coat_of_arms/coat_of_arms"),
    "coa_templates": ContentType("CoA Templates", "common/coat_of_arms/template_lists"),
    "coa_dynamic_definitions": ContentType("CoA Dynamic Defs", "common/coat_of_arms/dynamic_definitions"),
    
    # Combat
    "combat_effects": ContentType("Combat Effects", "common/combat_effects"),
    "combat_phase_events": ContentType("Combat Phase Events", "common/combat_phase_events"),
    
    # Confederation
    "confederation_types": ContentType("Confederation Types", "common/confederation_types"),
    
    # Council
    "council_positions": ContentType("Council Positions", "common/council_positions"),
    "council_tasks": ContentType("Council Tasks", "common/council_tasks"),
    
    # Court
    "courtier_guest_management": ContentType("Courtier Management", "common/courtier_guest_management"),
    "court_amenities": ContentType("Court Amenities", "common/court_amenities"),
    "court_positions": ContentType("Court Positions", "common/court_positions"),
    "court_types": ContentType("Court Types", "common/court_types"),
    
    # Culture
    "cultures": ContentType("Cultures", "common/culture/cultures"),
    "culture_pillars": ContentType("Culture Pillars", "common/culture/pillars"),
    "culture_eras": ContentType("Culture Eras", "common/culture/eras"),
    "traditions": ContentType("Traditions", "common/culture/traditions", key_prefix="tradition_"),
    "innovations": ContentType("Innovations", "common/culture/innovations"),
    "name_lists": ContentType("Name Lists", "common/culture/name_lists"),
    "creation_names": ContentType("Creation Names", "common/culture/creation_names"),
    
    # Customization
    "customizable_localization": ContentType("Custom Localization", "common/customizable_localization"),
    
    # Death
    "deathreasons": ContentType("Death Reasons", "common/deathreasons"),
    
    # Decisions
    "decisions": ContentType("Decisions", "common/decisions"),
    "decision_group_types": ContentType("Decision Groups", "common/decision_group_types"),
    
    # Defines (special - key-value pairs, PER_KEY_OVERRIDE)
    "defines": ContentType(
        "Defines", 
        "common/defines",
        merge_policy=MergePolicy.PER_KEY_OVERRIDE
    ),
    
    # Diarchies
    "diarchies": ContentType("Diarchies", "common/diarchies"),
    
    # DNA
    "dna_data": ContentType("DNA Data", "common/dna_data"),
    
    # Domiciles
    "domiciles": ContentType("Domiciles", "common/domiciles"),
    "domicile_building_types": ContentType("Domicile Buildings", "common/domicile_building_types"),
    
    # Dynasties
    "dynasties": ContentType("Dynasties", "common/dynasties"),
    "dynasty_houses": ContentType("Dynasty Houses", "common/dynasty_houses"),
    "dynasty_house_mottos": ContentType("House Mottos", "common/dynasty_house_mottos"),
    "dynasty_house_motto_inserts": ContentType("Motto Inserts", "common/dynasty_house_motto_inserts"),
    "dynasty_legacies": ContentType("Dynasty Legacies", "common/dynasty_legacies"),
    "dynasty_perks": ContentType("Dynasty Perks", "common/dynasty_perks"),
    
    # Effects/Triggers Localization
    "effect_localization": ContentType("Effect Localization", "common/effect_localization"),
    "trigger_localization": ContentType("Trigger Localization", "common/trigger_localization"),
    
    # Epidemics
    "epidemics": ContentType("Epidemics", "common/epidemics"),
    
    # Ethnicities
    "ethnicities": ContentType("Ethnicities", "common/ethnicities"),
    
    # Event Visual
    "event_2d_effects": ContentType("Event 2D Effects", "common/event_2d_effects"),
    "event_backgrounds": ContentType("Event Backgrounds", "common/event_backgrounds"),
    "event_themes": ContentType("Event Themes", "common/event_themes"),
    "event_transitions": ContentType("Event Transitions", "common/event_transitions"),
    
    # Factions
    "factions": ContentType("Factions", "common/factions"),
    
    # Flavor
    "flavorization": ContentType("Flavorization", "common/flavorization"),
    
    # Focus/Lifestyle
    "focuses": ContentType("Focuses", "common/focuses"),
    "lifestyles": ContentType("Lifestyles", "common/lifestyles"),
    "lifestyle_perks": ContentType("Lifestyle Perks", "common/lifestyle_perks"),
    
    # Game Concepts
    "game_concepts": ContentType("Game Concepts", "common/game_concepts"),
    "game_rules": ContentType("Game Rules", "common/game_rules"),
    
    # Genes/Portrait
    "genes": ContentType("Genes", "common/genes"),
    
    # Governments
    "governments": ContentType("Governments", "common/governments"),
    
    # Great Projects
    "great_projects": ContentType("Great Projects", "common/great_projects"),
    
    # Guest System
    "guest_system": ContentType("Guest System", "common/guest_system"),
    
    # Holdings
    "holdings": ContentType("Holdings", "common/holdings"),
    
    # Hooks
    "hook_types": ContentType("Hook Types", "common/hook_types"),
    
    # House Features
    "house_aspirations": ContentType("House Aspirations", "common/house_aspirations"),
    "house_relation_types": ContentType("House Relations", "common/house_relation_types"),
    "house_unities": ContentType("House Unities", "common/house_unities"),
    
    # Important Actions
    "important_actions": ContentType("Important Actions", "common/important_actions"),
    
    # Inspirations
    "inspirations": ContentType("Inspirations", "common/inspirations"),
    
    # Landed Titles
    "landed_titles": ContentType("Landed Titles", "common/landed_titles"),
    
    # Laws
    "laws": ContentType("Laws", "common/laws"),
    
    # Lease Contracts
    "lease_contracts": ContentType("Lease Contracts", "common/lease_contracts"),
    
    # Legends
    "legends": ContentType("Legends", "common/legends"),
    "legend_chronicles": ContentType("Legend Chronicles", "common/legend_chronicles"),
    "legend_seeds": ContentType("Legend Seeds", "common/legend_seeds"),
    "legend_types": ContentType("Legend Types", "common/legend_types"),
    
    # Legitimacy
    "legitimacy": ContentType("Legitimacy", "common/legitimacy"),
    
    # Men-at-Arms
    "men_at_arms": ContentType("Men-at-Arms Types", "common/men_at_arms_types"),
    
    # Messages
    "messages": ContentType("Messages", "common/messages"),
    "message_filter_types": ContentType("Message Filters", "common/message_filter_types"),
    "message_group_types": ContentType("Message Groups", "common/message_group_types"),
    
    # Modifiers
    "modifiers": ContentType("Modifiers", "common/modifiers"),
    "modifier_icons": ContentType("Modifier Icons", "common/modifier_icons"),
    "opinion_modifiers": ContentType("Opinion Modifiers", "common/opinion_modifiers"),
    "static_modifiers": ContentType("Static Modifiers", "common/static_modifiers"),
    
    # Named Colors
    "named_colors": ContentType("Named Colors", "common/named_colors"),
    
    # Nicknames
    "nicknames": ContentType("Nicknames", "common/nicknames"),
    
    # On Actions (CONTAINER MERGE - special handling)
    "on_actions": ContentType(
        "On Actions", 
        "common/on_action",
        merge_policy=MergePolicy.CONTAINER_MERGE
    ),
    
    # Playable Difficulty
    "playable_difficulty_infos": ContentType("Difficulty Info", "common/playable_difficulty_infos"),
    
    # Pool Characters
    "pool_character_selectors": ContentType("Pool Selectors", "common/pool_character_selectors"),
    
    # Portrait
    "portrait_modifiers": ContentType("Portrait Modifiers", "common/portrait_modifiers"),
    "portrait_types": ContentType("Portrait Types", "common/portrait_types"),
    
    # Province/Terrain
    "province_terrain": ContentType("Province Terrain", "common/province_terrain"),
    "terrain_types": ContentType("Terrain Types", "common/terrain_types"),
    
    # Raids
    "raids": ContentType("Raids", "common/raids"),
    
    # Religion
    "religions": ContentType("Religions", "common/religion/religions"),
    "religion_families": ContentType("Religion Families", "common/religion/religion_families"),
    "doctrines": ContentType("Doctrines", "common/religion/doctrines"),
    "holy_sites": ContentType("Holy Sites", "common/religion/holy_sites"),
    "fervor_modifiers": ContentType("Fervor Modifiers", "common/religion/fervor_modifiers"),
    
    # Ruler Objectives
    "ruler_objective_advice_types": ContentType("Ruler Advice", "common/ruler_objective_advice_types"),
    
    # Schemes
    "schemes": ContentType("Schemes", "common/schemes"),
    
    # Scripted Content
    "scripted_animations": ContentType("Scripted Animations", "common/scripted_animations"),
    "scripted_character_templates": ContentType("Character Templates", "common/scripted_character_templates"),
    "scripted_costs": ContentType("Scripted Costs", "common/scripted_costs"),
    "scripted_effects": ContentType("Scripted Effects", "common/scripted_effects"),
    "scripted_guis": ContentType("Scripted GUIs", "common/scripted_guis"),
    "scripted_lists": ContentType("Scripted Lists", "common/scripted_lists"),
    "scripted_modifiers": ContentType("Scripted Modifiers", "common/scripted_modifiers"),
    "scripted_relations": ContentType("Scripted Relations", "common/scripted_relations"),
    "scripted_rules": ContentType("Scripted Rules", "common/scripted_rules"),
    "scripted_triggers": ContentType("Scripted Triggers", "common/scripted_triggers"),
    "script_values": ContentType("Script Values", "common/script_values"),
    
    # Secrets
    "secret_types": ContentType("Secret Types", "common/secret_types"),
    
    # Situations
    "situations": ContentType("Situations", "common/situation"),
    
    # Story Cycles
    "story_cycles": ContentType("Story Cycles", "common/story_cycles"),
    
    # Struggles
    "struggles": ContentType("Struggles", "common/struggle"),
    
    # Subjects
    "subject_contracts": ContentType("Subject Contracts", "common/subject_contracts"),
    
    # Succession
    "succession_appointment": ContentType("Succession Appointment", "common/succession_appointment"),
    "succession_election": ContentType("Succession Election", "common/succession_election"),
    
    # Suggestions
    "suggestions": ContentType("Suggestions", "common/suggestions"),
    
    # Task Contracts
    "task_contracts": ContentType("Task Contracts", "common/task_contracts"),
    
    # Tax Slots
    "tax_slots": ContentType("Tax Slots", "common/tax_slots"),
    
    # Traits
    "traits": ContentType("Traits", "common/traits"),
    
    # Travel
    "travel": ContentType("Travel", "common/travel"),
    "travel_options": ContentType("Travel Options", "common/travel_options"),
    
    # Tutorials
    "tutorial_lessons": ContentType("Tutorial Lessons", "common/tutorial_lessons"),
    "tutorial_lesson_chains": ContentType("Tutorial Chains", "common/tutorial_lesson_chains"),
    
    # Vassal Stances
    "vassal_stances": ContentType("Vassal Stances", "common/vassal_stances"),
    "vassal_contracts": ContentType("Vassal Contracts", "common/vassal_contracts"),
    
    # =========================================
    # EVENTS FOLDER - Override policy
    # =========================================
    "events": ContentType("Events", "events"),
    
    # =========================================
    # GFX FOLDER - Override policy
    # =========================================
    "gfx": ContentType("Graphics", "gfx"),
    "portraits": ContentType("Portraits", "gfx/portraits"),
    
    # =========================================
    # HISTORY FOLDER - Override policy
    # =========================================
    "history_characters": ContentType("History Characters", "history/characters"),
    "history_provinces": ContentType("History Provinces", "history/provinces"),
    "history_titles": ContentType("History Titles", "history/titles"),
    "history_wars": ContentType("History Wars", "history/wars"),
    
    # =========================================
    # GUI FOLDER - FIOS policy (first wins!)
    # =========================================
    "gui": ContentType(
        "GUI",
        "gui",
        merge_policy=MergePolicy.FIOS,
        file_pattern="*.gui"
    ),
    
    # =========================================
    # LOCALIZATION - Per-key override
    # =========================================
    "localization": ContentType(
        "Localization", 
        "localization/english", 
        merge_policy=MergePolicy.PER_KEY_OVERRIDE,
        file_pattern="*.yml"
    ),
    "localization_french": ContentType(
        "Localization French", 
        "localization/french", 
        merge_policy=MergePolicy.PER_KEY_OVERRIDE,
        file_pattern="*.yml"
    ),
    "localization_german": ContentType(
        "Localization German", 
        "localization/german", 
        merge_policy=MergePolicy.PER_KEY_OVERRIDE,
        file_pattern="*.yml"
    ),
    "localization_spanish": ContentType(
        "Localization Spanish", 
        "localization/spanish", 
        merge_policy=MergePolicy.PER_KEY_OVERRIDE,
        file_pattern="*.yml"
    ),
    "localization_korean": ContentType(
        "Localization Korean", 
        "localization/korean", 
        merge_policy=MergePolicy.PER_KEY_OVERRIDE,
        file_pattern="*.yml"
    ),
    "localization_russian": ContentType(
        "Localization Russian", 
        "localization/russian", 
        merge_policy=MergePolicy.PER_KEY_OVERRIDE,
        file_pattern="*.yml"
    ),
    "localization_simp_chinese": ContentType(
        "Localization Chinese Simplified", 
        "localization/simp_chinese", 
        merge_policy=MergePolicy.PER_KEY_OVERRIDE,
        file_pattern="*.yml"
    ),
    
    # =========================================
    # MAP FOLDER - Override policy
    # =========================================
    "map_data": ContentType("Map Data", "map_data"),
    
    # =========================================
    # MUSIC FOLDER
    # =========================================
    "music": ContentType("Music", "music"),
}


def get_content_type(type_id: str) -> Optional[ContentType]:
    """Get a content type by its ID."""
    return CONTENT_TYPES.get(type_id)


def get_content_type_for_path(relative_path: str) -> Optional[ContentType]:
    """
    Find the content type that matches a relative file path.
    
    Args:
        relative_path: e.g., "common/culture/traditions/00_regional_traditions.txt"
    
    Returns:
        The matching ContentType or None
    """
    # Normalize path
    path = relative_path.replace("\\", "/").strip("/")
    
    # Find best match (longest matching path prefix)
    best_match = None
    best_length = 0
    
    for type_id, content_type in CONTENT_TYPES.items():
        folder = content_type.relative_path.replace("\\", "/").strip("/")
        if path.startswith(folder + "/") or path == folder:
            if len(folder) > best_length:
                best_match = content_type
                best_length = len(folder)
    
    return best_match


def get_policy_for_path(relative_path: str) -> MergePolicy:
    """
    Determine the merge policy for a file based on its path.
    
    Args:
        relative_path: e.g., "common/on_action/yearly.txt"
    
    Returns:
        The appropriate MergePolicy (defaults to OVERRIDE)
    """
    content_type = get_content_type_for_path(relative_path)
    if content_type:
        return content_type.merge_policy
    return MergePolicy.OVERRIDE


# Mapping from folder to merge policy for quick lookups
FOLDER_POLICIES: Dict[str, MergePolicy] = {
    ct.relative_path: ct.merge_policy 
    for ct in CONTENT_TYPES.values()
}
