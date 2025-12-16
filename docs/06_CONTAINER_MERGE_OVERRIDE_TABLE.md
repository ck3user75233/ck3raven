# CK3 Containers: Complete Merge/Override Reference

> **Last Updated:** December 2025 - Verified against Paradox's `_on_actions.info` documentation

This document provides the **authoritative merge/override table** for all CK3 content types.
The game state emulator uses these rules to resolve conflicts between vanilla and mods.

---

## The 4 Core Merge Policies

Based on analysis of CK3's engine behavior, there are exactly **4 merge policies**:

### 1. OVERRIDE (Most Common)
**Last definition wins completely.**

- Multiple files define the same named block → last one in load order replaces all previous
- No merging of internal contents
- Simple, predictable behavior

**Used by:** Traditions, events, decisions, traits, scripted_effects, scripted_triggers, buildings, laws, governments, religions, cultures, and ~95% of content types.

### 2. CONTAINER_MERGE (Special)
**Container merges, but internal blocks have their own rules.**

- Same-named containers across files are combined
- Lists inside (like `events`, `on_actions`) **APPEND**
- Single-slot blocks (like `effect`, `trigger`) **CONFLICT** - only ONE allowed, last wins

**Used by:** `on_actions` (only confirmed case)

### 3. PER_KEY_OVERRIDE (Flat Files)
**Each key is independent. Last definition per key wins.**

- File structure is flat key=value pairs
- Multiple files can define different keys without conflict
- Same key defined multiple times → last wins for that key only

**Used by:** Localization, defines

### 4. LIST_APPEND (Rare)
**All entries are appended together.**

- No concept of "same key" override
- Every entry from every file is included
- Order is determined by load order

**Used by:** Certain sub-entries within CONTAINER_MERGE types (e.g., `events = {}` inside on_actions)

---

## File-Level Behavior: Same Filename vs Different Filename

> **Source:** Paradox Wiki modding documentation and empirical evidence from MSC compatch files.

This is a **critical architectural rule** that operates BEFORE the 4 merge policies above:

### The Golden Rule

**Same filename + same path = COMPLETE FILE REPLACEMENT**
**Different filename = KEY-LEVEL MERGE**

### Full File Override (Same Filename)

From the Paradox Wiki:
> "If a mod has the same file as the game, it replaces all the contents of the file.
> (By the same file we mean same path, same filename).
> Avoid doing this unless you intend to overwrite the whole file!"

When two sources (vanilla + mod, or mod + mod) have files with **identical path + filename**:
- The later file in load order COMPLETELY REPLACES the earlier file
- **ALL keys from the earlier file are discarded**
- Only the later file's content exists in the final game state

**Example:**
```
Vanilla: common/culture/traditions/00_regional_traditions.txt
  ├── tradition_SEA_1 = { ... }
  ├── tradition_SEA_2 = { ... }
  └── tradition_SEA_3 = { ... }

Mod (same filename): common/culture/traditions/00_regional_traditions.txt
  ├── tradition_SEA_4 = { ... }
  └── tradition_SEA_5 = { ... }

Result: ONLY tradition_SEA_4 and tradition_SEA_5 exist!
        tradition_SEA_1, SEA_2, SEA_3 are GONE.
```

This is called **FIOS (First In Only Served)** at the file level - only the first file's CONTENT is served when paths match (though in practice it's the LAST loaded file that wins, making "LIOS" more accurate terminology for file-level replacement).

### Key-Level Merge (Different Filename)

When files have **different filenames** (even in the same folder):
- ALL files are loaded
- Keys from ALL files are collected
- The **4 merge policies above** determine what happens to duplicate keys
- For OVERRIDE types: last definition per key wins (LIOS)
- For CONTAINER_MERGE types: containers merge, sublists append

**Example:**
```
Vanilla: common/culture/traditions/00_regional_traditions.txt
  ├── tradition_SEA_1 = { ... }
  ├── tradition_SEA_2 = { ... }
  └── tradition_SEA_3 = { ... }

Mod (different filename): common/culture/traditions/zzz_my_mod_traditions.txt
  ├── tradition_SEA_1 = { ... }  ← OVERRIDES vanilla's SEA_1
  └── tradition_SEA_4 = { ... }  ← NEW tradition added

Result: tradition_SEA_1 (mod version), SEA_2 (vanilla), 
        SEA_3 (vanilla), SEA_4 (mod) all exist!
```

### LIOS vs FIOS Load Order

For most content types (LIOS - Last In Only Served):
- Files are loaded in ASCIIbetical order
- Files starting with `z` load after files starting with `0`
- Mod files load after vanilla files
- Later mods in playset load after earlier mods
- **Last loaded definition wins**

For GUI types/templates (FIOS - First In Only Served):
- First loaded definition wins
- Use `00_` prefix to ensure your file loads first

From the Wiki:
> "This has been called Last in Only Served, or LIOS. Most overrides follow this order."
> "Types and templates can be overwritten, but they follow FIOS order: first loaded type or template takes priority."

### The `replace_path=` Directive

In `.mod` descriptor files, you can force **entire folder replacement**:

```
replace_path = "common/culture/traditions"
```

This tells the engine to IGNORE vanilla's entire folder and only use the mod's files. This is a drastic option used by total conversions.

### Localization `replace/` Subfolder

Localization has a special mechanism:
- Normal localization folder: `localization/<lang>/` - keys merge, duplicates cause errors
- Replace folder: `localization/<lang>/replace/` - keys intentionally override without errors

Both paths work:
- `localization/{language}/replace/`
- `localization/replace/{language}/`

### Summary Table: File-Level Resolution

| Scenario | Behavior |
|----------|----------|
| Same path + same filename | Complete file replacement (only last file exists) |
| Same path + different filename | All files loaded, key-level merge applies |
| `replace_path=` in .mod | Entire vanilla folder ignored |
| Localization `replace/` folder | Keys override without duplicate errors |
| GUI types/templates | FIOS - first loaded wins, use `00_` prefix |

### Implications for Emulator

The game state emulator must:

1. **First pass:** Group files by path + filename
   - Same path+name → only keep last file in load order
   
2. **Second pass:** Collect all remaining files per folder
   - Apply folder-specific merge policy (OVERRIDE, CONTAINER_MERGE, etc.)
   
3. **Third pass:** Handle special cases
   - `replace_path=` in active mods → skip vanilla folder entirely
   - Localization `replace/` → mark as intentional override

---

## Complete Content Type Reference

This table assigns a merge policy to **every CK3 content folder**.

### common/ Folder - Named Block Containers

All folders in `common/` use **OVERRIDE** policy unless noted otherwise.

| Folder | Policy | Key Pattern | Notes |
|--------|--------|-------------|-------|
| `accolade_icons/` | OVERRIDE | `<icon_id>` | |
| `accolade_names/` | OVERRIDE | `<name_id>` | |
| `accolade_types/` | OVERRIDE | `<type_id>` | |
| `achievements/` | OVERRIDE | `<achievement_id>` | |
| `activities/` | OVERRIDE | Various nested types | Subfolders have own types |
| `ai_goaltypes/` | OVERRIDE | `<goal_id>` | |
| `ai_war_stances/` | OVERRIDE | `<stance_id>` | |
| `artifacts/` | OVERRIDE | Various nested types | |
| `bookmarks/` | OVERRIDE | `<bookmark_id>` | |
| `buildings/` | OVERRIDE | `<building_id>` | |
| `casus_belli_groups/` | OVERRIDE | `<group_id>` | |
| `casus_belli_types/` | OVERRIDE | `<cb_id>` | |
| `character_backgrounds/` | OVERRIDE | `<background_id>` | |
| `character_interaction_categories/` | OVERRIDE | `<category_id>` | |
| `character_interactions/` | OVERRIDE | `<interaction_id>` | |
| `character_memory_types/` | OVERRIDE | `<memory_id>` | |
| `coat_of_arms/` | OVERRIDE | `<coa_id>` | |
| `combat_effects/` | OVERRIDE | `<effect_id>` | |
| `combat_phase_events/` | OVERRIDE | `<phase_id>` | |
| `confederation_types/` | OVERRIDE | `<type_id>` | |
| `council_positions/` | OVERRIDE | `<position_id>` | |
| `council_tasks/` | OVERRIDE | `<task_id>` | |
| `court_amenities/` | OVERRIDE | `<amenity_id>` | |
| `court_positions/` | OVERRIDE | `<position_id>` | |
| `court_types/` | OVERRIDE | `<type_id>` | |
| `culture/cultures/` | OVERRIDE | `<culture_id>` | |
| `culture/traditions/` | OVERRIDE | `tradition_*` | |
| `culture/innovations/` | OVERRIDE | `innovation_*` | |
| `culture/pillars/` | OVERRIDE | `<pillar_id>` | |
| `culture/eras/` | OVERRIDE | `culture_era_*` | |
| `customizable_localization/` | OVERRIDE | `<loc_id>` | |
| `deathreasons/` | OVERRIDE | `<reason_id>` | |
| `decision_group_types/` | OVERRIDE | `<group_id>` | |
| `decisions/` | OVERRIDE | `<decision_id>` | |
| `defines/` | **PER_KEY_OVERRIDE** | `Category.KEY` | Nested key=value |
| `diarchies/` | OVERRIDE | Various nested types | |
| `dna_data/` | OVERRIDE | `<dna_id>` | |
| `domiciles/` | OVERRIDE | Various nested types | |
| `dynasties/` | OVERRIDE | `<dynasty_id>` | |
| `dynasty_houses/` | OVERRIDE | `<house_id>` | |
| `dynasty_legacies/` | OVERRIDE | `<legacy_id>` | |
| `dynasty_perks/` | OVERRIDE | `<perk_id>` | |
| `effect_localization/` | OVERRIDE | `<effect_loc_id>` | |
| `epidemics/` | OVERRIDE | `<epidemic_id>` | |
| `ethnicities/` | OVERRIDE | `<ethnicity_id>` | |
| `event_2d_effects/` | OVERRIDE | `<effect_id>` | |
| `event_backgrounds/` | OVERRIDE | `<background_id>` | |
| `event_themes/` | OVERRIDE | `<theme_id>` | |
| `event_transitions/` | OVERRIDE | `<transition_id>` | |
| `factions/` | OVERRIDE | `<faction_id>` | |
| `flavorization/` | OVERRIDE | `<flavor_id>` | |
| `focuses/` | OVERRIDE | `<focus_id>` | |
| `game_concepts/` | OVERRIDE | `<concept_id>` | |
| `game_rules/` | OVERRIDE | `<rule_id>` | |
| `genes/` | OVERRIDE | `<gene_id>` | |
| `governments/` | OVERRIDE | `<gov_id>` | |
| `great_projects/` | OVERRIDE | `<project_id>` | |
| `holdings/` | OVERRIDE | `<holding_id>` | |
| `hook_types/` | OVERRIDE | `<hook_id>` | |
| `house_aspirations/` | OVERRIDE | `<aspiration_id>` | |
| `house_unities/` | OVERRIDE | `<unity_id>` | |
| `important_actions/` | OVERRIDE | `<action_id>` | |
| `inspirations/` | OVERRIDE | `<inspiration_id>` | |
| `landed_titles/` | OVERRIDE | `[ekdcb]_*` | Title keys |
| `laws/` | OVERRIDE | `<law_id>` | |
| `legends/` | OVERRIDE | Various nested types | |
| `legitimacy/` | OVERRIDE | `<legitimacy_id>` | |
| `lifestyle_perks/` | OVERRIDE | `<perk_id>` | |
| `lifestyles/` | OVERRIDE | `<lifestyle_id>` | |
| `men_at_arms_types/` | OVERRIDE | `<maa_id>` | |
| `messages/` | OVERRIDE | `<message_id>` | |
| `message_filter_types/` | OVERRIDE | `<filter_id>` | |
| `modifiers/` | OVERRIDE | `<modifier_id>` | Static modifiers |
| `nicknames/` | OVERRIDE | `nick_*` | |
| `on_action/` | **CONTAINER_MERGE** | `on_*` | Special - see detailed rules |
| `opinion_modifiers/` | OVERRIDE | `<opinion_id>` | |
| `pool_character_selectors/` | OVERRIDE | `<selector_id>` | |
| `province_terrain/` | OVERRIDE | `<terrain_id>` | |
| `raids/` | OVERRIDE | Various nested types | |
| `religion/religions/` | OVERRIDE | `<religion_id>` | |
| `religion/doctrines/` | OVERRIDE | `doctrine_*` | |
| `religion/holy_sites/` | OVERRIDE | `<site_id>` | |
| `schemes/` | OVERRIDE | Various nested types | |
| `script_values/` | OVERRIDE | `<value_id>` | |
| `scripted_animations/` | OVERRIDE | `<animation_id>` | |
| `scripted_character_templates/` | OVERRIDE | `<template_id>` | |
| `scripted_costs/` | OVERRIDE | `<cost_id>` | |
| `scripted_effects/` | OVERRIDE | `<effect_id>` | |
| `scripted_guis/` | OVERRIDE | `<gui_id>` | |
| `scripted_lists/` | OVERRIDE | `<list_id>` | |
| `scripted_modifiers/` | OVERRIDE | `<modifier_id>` | |
| `scripted_relations/` | OVERRIDE | `<relation_id>` | |
| `scripted_rules/` | OVERRIDE | `<rule_id>` | |
| `scripted_triggers/` | OVERRIDE | `<trigger_id>` | |
| `secret_types/` | OVERRIDE | `<secret_id>` | |
| `situation/` | OVERRIDE | Various nested types | |
| `story_cycles/` | OVERRIDE | `<story_id>` | |
| `struggle/` | OVERRIDE | Various nested types | |
| `subject_contracts/` | OVERRIDE | `<contract_id>` | |
| `succession_appointment/` | OVERRIDE | `<appointment_id>` | |
| `succession_election/` | OVERRIDE | `<election_id>` | |
| `suggestions/` | OVERRIDE | `<suggestion_id>` | |
| `task_contracts/` | OVERRIDE | `<contract_id>` | |
| `tax_slots/` | OVERRIDE | Various nested types | |
| `terrain_types/` | OVERRIDE | `<terrain_id>` | |
| `traits/` | OVERRIDE | `<trait_id>` | |
| `travel/` | OVERRIDE | Various nested types | |
| `trigger_localization/` | OVERRIDE | `<trigger_loc_id>` | |
| `tutorial_lessons/` | OVERRIDE | `<lesson_id>` | |
| `vassal_stances/` | OVERRIDE | `<stance_id>` | |

### events/ Folder

| Folder | Policy | Key Pattern | Notes |
|--------|--------|-------------|-------|
| `events/*.txt` | OVERRIDE | `namespace.id` | e.g., `my_mod.1001` |

### history/ Folder

| Folder | Policy | Key Pattern | Notes |
|--------|--------|-------------|-------|
| `history/characters/*.txt` | **PER_KEY_OVERRIDE** | Character ID | Date blocks merge |
| `history/provinces/*.txt` | **PER_KEY_OVERRIDE** | Province ID | Date blocks merge |
| `history/titles/*.txt` | **PER_KEY_OVERRIDE** | Title key | Date blocks merge |
| `history/cultures/*.txt` | **PER_KEY_OVERRIDE** | Culture ID | Date blocks merge |

**Note on History:** History files use a special variant where date blocks within the same character/province/title are merged. The last definition per date wins for conflicting keys within that date.

### localization/ Folder

| Folder | Policy | Key Pattern | Notes |
|--------|--------|-------------|-------|
| `localization/<lang>/*.yml` | **PER_KEY_OVERRIDE** | `key:0 "text"` | Per-key, per-language |

### gfx/ Folder

| Folder | Policy | Key Pattern | Notes |
|--------|--------|-------------|-------|
| Most gfx/ subfolders | OVERRIDE | Various | Asset definitions |

### gui/ Folder

| Folder | Policy | Key Pattern | Notes |
|--------|--------|-------------|-------|
| `gui/*.gui` | **FIOS (First In Only Served)** | Widget/type definitions | First loaded definition wins! Use `00_` prefix |

**Important:** GUI types and templates use **FIOS** (First In Only Served), the opposite of most content types!

From the Wiki:
> "Types and templates can be overwritten, but they follow FIOS order: first loaded type or template takes priority."
> "Your file name needs to come first asciibetically, for example, add 00_ to it"

Example to override a button type:
```txt
types SmallButton {
  type button_standard_small = button_standard {
    size = { 40 25 }
  }
}
```
File must be named `00_my_buttons.gui` (or similar) to load BEFORE vanilla's definitions.

---

## A. Cultures & Traditions

### 1. `common/culture/traditions/*.txt`

* Container: `tradition_xxx = { … }`
* Engine behavior:
  * **Tradition key (`tradition_xxx`)**: *override*. Last one in load order wins.
  * Inside the block: normal Paradox rules — if redefined in the same file, later key overrides earlier.

### 2. `common/culture/cultures/*.txt`

* Container: `culture_xxx = { … }`
* Engine behavior:
  * **Culture key (`culture_xxx`)**: *override*.
  * Multiple files can define the same culture → last file's block replaces the earlier one.

**Takeaway:**
For **traditions and cultures**, a resolver can safely treat each named culture/tradition as **whole-block override** at the cross-file level.

---

## B. Events

**`events/*.txt`**

* Container: event id, e.g. `my_mod.1001 = { … }`.
* Behavior:
  * **Event ID**: *override*. If more than one file defines `my_mod.1001`, the last one wins completely.
  * No merging of triggers/effects between event definitions across files.

Virtual merge is super useful here to compare "vanilla vs mod vs final".

---

## C. Decisions

**`decisions/*.txt`**

* Container: `my_decision = { … }`
* Behavior:
  * **Decision key**: *override*.
  * No automatic merging of sub-blocks like `ai_will_do`, `is_shown`, etc. across files.

---

## D. Scripted Effects & Scripted Triggers

**`common/scripted_effects/*.txt`**

* Container: `my_scripted_effect = { … }`
* Behavior:
  * **Effect name**: *override*. Last definition wins.

**`common/scripted_triggers/*.txt`**

* Container: `my_scripted_trigger = { … }`
* Behavior:
  * **Trigger name**: *override*.

Inside each block, normal per-key override rules apply only within that one definition.

---

## E. on_actions — The Complex One (CORRECTED)

**`common/on_action/*.txt`**

> **Source:** Paradox's official `game/common/on_action/_on_actions.info` documentation.

**Critical Rule from Paradox:**

> "You can declare data for on-actions in multiple files, however, **you cannot have multiple triggers or effect blocks for a given named on-action**. In particular, you cannot append an effect block directly to an on_action which already has an effect block, as this creates a conflict."

### Actual File Structure (NO wrapper!)

Unlike what the previous documentation implied, on_action files do NOT use a wrapper `on_action = { }`. The on_action names are defined at the file's top level:

```txt
# Correct structure - on_actions are top-level blocks:
on_character_death = {
    effect = { ... }
    events = { some_event.100 }
}

on_game_start = {
    on_actions = { my_custom_on_action }
    events = { startup.001 }
}
```

### Merge Behavior Per Block Type

| Block Type in on_action | Slots Per on_action | Cross-File Behavior |
|------------------------|---------------------|---------------------|
| `effect = { }` | **ONE** | CONFLICT - last loaded wins |
| `trigger = { }` | **ONE** | CONFLICT - last loaded wins |
| `weight_multiplier = { }` | **ONE** | Last loaded wins |
| `fallback = name` | **ONE** | Last loaded wins |
| `events = { }` | LIST | APPENDS from all files |
| `on_actions = { }` | LIST | APPENDS from all files |
| `random_events = { }` | LIST | APPENDS entries |
| `random_on_actions = { }` | LIST | APPENDS entries |
| `first_valid = { }` | LIST | APPENDS entries |
| `first_valid_on_action = { }` | LIST | APPENDS entries |

### Key Insight

The previous documentation was incorrect in saying:
- ❌ "If they're distinct (e.g. `effect = {}` vs `effect_2 = {}`), they can stack"

**The truth is:**
- ✅ There is only ONE `effect` slot per named on_action
- ✅ There is only ONE `trigger` slot per named on_action
- ✅ The syntax doesn't support `effect_2` - that's not valid
- ✅ If two mods both define `effect = {}` for `on_game_start`, it's a CONFLICT

### The Correct Modding Pattern

Paradox's recommended workaround:

```txt
# Mod file - chains off vanilla instead of overwriting:
some_vanilla_on_action = {
    on_actions = { some_modded_on_action }
}

some_modded_on_action = {
    effect = {
        some_fun_modding_effect = yes
    }
}
```

This makes the vanilla on-action call the modded on-action whenever it fires, preserving vanilla's `effect` block while adding mod functionality.

---

## F. Laws, Government Types, Tenets, Doctrines, Game Rules, Men-at-Arms Types

All of these follow the same basic pattern:

* `common/laws/*.txt`
* `common/governments/*.txt`
* `common/religion/tenets/*.txt`
* `common/religion/doctrines/*.txt`
* `common/game_rules/*.txt`
* `common/men_at_arms_types/*.txt`

Each defines named blocks:

```txt
crown_authority_0 = { … }
feudal_government = { … }
tenet_asceticism = { … }
```

Behavior:

* **Container key** (e.g. `feudal_government`, `tenet_asceticism`): *override*.
* No engine-level cross-file merging of fields within a named object.

---

## G. Localization

**`localization/**`**

* Container: individual localization key, e.g. `my_mod_decision:0 "Text"`.
* Behavior:
  * **Loc key**: *override per key*.
  * Multiple loc files can define the same key; last one in load order wins for that language.

This is effectively per-key override, but because localization is flat, it feels "lighter".

---

## H. `defines` and other oddballs

**`common/defines/*.txt`**

* Typically parsed as a set of categories and keys, e.g. `NCharacter = { MAX_AGE = 100 }`.
* Practically behaves like **per-key override**:
  * Same category + key: last one wins.
  * Different keys coexist.

Some other "list-style" constructs (e.g., modifiers lists, `events = {}`, etc.) are merged by appending entries, but that's semantically determined by the engine's "this is a list, not a single block" handling, not a universal rule.

---

## Summary Table (high-level) - CORRECTED

### File-Level Resolution (First Pass)

| File Matching | Result |
|---------------|--------|
| Same path + same filename across sources | **COMPLETE FILE REPLACEMENT** - only last file's content exists |
| Same path + different filename | All files loaded, proceed to key-level merge |
| `replace_path=` directive active | Entire vanilla folder skipped |
| GUI types/templates | **FIOS** - first loaded wins, use `00_` prefix |

### Key-Level Resolution (Second Pass)

| Type                              | Container merges? | Sub-entries merge?                       | Notes                                          |
| --------------------------------- | ----------------- | ---------------------------------------- | ---------------------------------------------- |
| Traditions                        | ❌ (override)      | Normal per-key *within same file*        | Last `tradition_xxx` wins across files         |
| Cultures                          | ❌ (override)      | Normal per-key within file               | Last `culture_xxx` wins                        |
| Events                            | ❌ (override)      | No cross-file merge                      | Last `event_id` wins                           |
| Decisions                         | ❌ (override)      | No cross-file merge                      | Last decision key wins                         |
| Scripted Effects                  | ❌ (override)      | No cross-file merge                      | Last effect name wins                          |
| Scripted Triggers                 | ❌ (override)      | No cross-file merge                      | Last trigger name wins                         |
| **on_action (named block)**       | ✅ (merge)         | See below                                | Same-named on_action merges across files       |
| → `events = { }` list             |                   | ✅ APPENDS                                | Multiple mods can add events                   |
| → `on_actions = { }` list         |                   | ✅ APPENDS                                | Multiple mods can chain on_actions             |
| → `random_events = { }` list      |                   | ✅ APPENDS                                | Weights/entries append                         |
| → `effect = { }` block            |                   | ❌ ONE slot, CONFLICT if multiple         | Only ONE per on_action, last wins              |
| → `trigger = { }` block           |                   | ❌ ONE slot, CONFLICT if multiple         | Only ONE per on_action, last wins              |
| Laws, governments, tenets…        | ❌ (override)      | Normal per-key within file               | Last named object wins                         |
| Localization keys                 | ✅ (per key)       | N/A (flat)                               | Last loc key definition per key wins           |
| Defines                           | ✅ (per key)       | N/A (flat)                               | Last category.key wins                         |

This is the granularity a serious tool needs to encode.

---

## Updating the Tradition-Resolver Design with This Complexity

The **tradition-only resolver** we sketched is still fine as v0 because:

* For **tradition blocks**, the cross-file behavior really *is*:
  * "Last `tradition_xxx` definition wins."

So the v0 algorithm:

* Collect all `tradition_*` definitions in playset order.
* For each key, keep list; final = last entry.
* Write "resolved traditions" file + conflict report.

…is still correct for traditions.

But when we extend the tool later, we must *not* treat everything like a tradition.

---

## Adding a "Merge Policy" Layer Per Type

Introduce a config describing how each object type behaves. Something like:

```json
{
  "tradition": {
    "file_glob": "common/culture/traditions/*.txt",
    "container_key_pattern": "^tradition_",
    "merge_strategy": "whole_block_override"
  },
  "event": {
    "file_glob": "events/*.txt",
    "container_key_pattern": "^[a-zA-Z0-9_.]+$",
    "merge_strategy": "whole_block_override"
  },
  "on_action": {
    "file_glob": "common/on_action/*.txt",
    "container_key_pattern": "^on_",
    "merge_strategy": "container_merge_with_subrules",
    "subrules": {
      "events": "append_list",
      "on_actions": "append_list",
      "random_events": "append_list",
      "random_on_actions": "append_list",
      "first_valid": "append_list",
      "first_valid_on_action": "append_list",
      "effect": "single_slot_conflict",
      "trigger": "single_slot_conflict",
      "weight_multiplier": "single_slot_override",
      "fallback": "single_slot_override"
    }
  }
}
```

**Note:** `single_slot_conflict` means there is exactly ONE slot for that key per on_action. If multiple mods define it, the resolver should:
1. Keep the last loaded one (as the engine does)
2. Flag this as a **conflict** in reports (since mod intent was likely to add, not replace)

For **v0**, we only implement `tradition` with `whole_block_override`.
But the architecture already expects that different types might:

* Merge containers
* Append sub-entries
* Override specific keys

So:

* **Traditions** use: `whole_block_override` (simple).
* **Events/decisions/scripted_effects** will also use `whole_block_override`.
* **on_actions** will use: `container_merge_with_subrules`.

---

## Parser Stays Generic, Resolver Becomes Type-Aware

The AST/parser doesn't need to know about semantics; it just needs to:

* Recognize top-level assignments.
* Hand back `BlockNode`s and nested structure.

The **resolver** then applies the correct strategy for each type:

* For *traditions/events/decisions*:
  * Group by key → last block wins.

* For *on_actions*:
  * Group by on_action name.
  * Combine all child entries into a synthetic container:
    * For `events = {}` lists → append from all definitions in order.
    * For singleton sub-blocks like `effect` → last one wins.

That's where the nuanced knowledge about "on_actions append, but effects overwrite" gets encoded.

---

## The Tradition-Resolver v0 with Future Expansion Hooks

Concretely, we'd refine the previous design as:

### v0 Implementation

* Only reads `common/culture/traditions/*.txt`.
* Applies `whole_block_override` on `tradition_*` keys.
* Outputs:
  * `00_resolved_traditions.txt`
  * `tradition_conflicts.json`

### Design Notes for v1+

* We add a "type registry" where each object type (tradition, event, on_action, etc.) has:
  * file pattern
  * key detection rule
  * merge policy

* When the tool is run in "extended mode", it:
  * Applies tradition logic to traditions.
  * Applies full-block override logic to events/decisions/scripted_*.
  * Applies container + subrules logic to on_actions.

### Virtual Merge for Human Inspection

* For conflict-heavy types (events, decisions, traditions), the tool can also build a *virtual merged view*:
  * Show "vanilla vs final vs synthetic-merged" for easy compatching.

* For on_actions, we might show:
  * One view with *actual engine result*.
  * One view with *all effects/entries grouped by source mod* to show who contributes what.
