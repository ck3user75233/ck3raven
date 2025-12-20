# Map Mod Conversion Agent - Design Concept

> **Status:** Roadmap / Future Development  
> **Created:** December 20, 2025  
> **Priority:** Phase 5 (after core conflict resolution is stable)

---

## Problem Statement

Historically, mods that make widespread changes to the map (like More Bookmarks+, TFE, AGOT) have been some of the most popular and impactful, but also the hardest to mix with gameplay mods due to:

- **Landed titles** being entwined with decisions, on_actions, events
- **Place names** tied to special buildings, holy sites, triggers
- **Geographic regions** referenced in scripted triggers/effects

Many gameplay mods doing heavy lifting (religion expansions, cultural overhauls, building mods) are extremely difficult to compatch for map mods.

---

## Analysis: More Bookmarks+ Scale

### The Numbers
| Content Type | Vanilla | MB+ | Delta |
|--------------|---------|-----|-------|
| `00_landed_titles.txt` | 60,406 lines | 87,815 lines | +45% |
| `00_holy_sites.txt` | 2,830 lines | 7,058 lines | +149% |
| Holy sites files | 1 file | 2 files (incl. RICE integration) | - |
| Additional title files | 1 | 11 (Japan, Korea, China, SEA, etc.) | +10 files |
| New baronies | - | ~300 | Restructured duchies/kingdoms |

MB+ is explicitly a **total conversion** for the map.

---

## The Compatching Challenge

### 1. Landed Title References Are Everywhere
```pdx
common/decisions/       → title_target = title:k_england
common/on_action/       → scope:landed_title = title:d_normandy  
events/                 → any_held_title = { this = title:c_paris }
common/great_projects/  → barony = b_tower_of_london
common/scripted_effects/→ create_title_and_vassal_change = { title = title:e_britannia }
```

When MB+ renames `c_paris` to `c_ile_de_france` or restructures which baronies are under which county, **every reference breaks**.

### 2. Holy Sites Are Tied to Specific Baronies
```pdx
holy_site_rome = {
    county = c_roma
    barony = b_roma  # <-- If this barony is renamed or moved, religion mods break
}
```

### 3. Geographic Region Triggers
```pdx
trigger = {
    capital_province = { geographical_region = world_europe_west_britannia }
}
```
MB+ may restructure which provinces are in which regions.

### 4. The Ripple Effect
A religion mod like Pagan Religions Revived that adds 50 new faiths with custom holy sites now needs:
- All 50 faiths' holy sites remapped to MB+ baronies
- All decisions checking `title:c_x` remapped
- All events with region triggers checked

---

## Proposed Solution: Map Conversion Agent

### Core Concept

Map mod compatibility is a **translation problem** - mapping one namespace (vanilla titles) to another (map mod titles). Once you have the Rosetta Stone (the mapping index), translation becomes mechanical.

### Phase 1: Build the Mapping Index

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Map Conversion Index                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  TITLE MAPPING TABLE                                                         │
│  ┌──────────────────┬────────────────────┬──────────────┐                   │
│  │ Vanilla Title    │ Map Mod Title      │ Confidence   │                   │
│  ├──────────────────┼────────────────────┼──────────────┤                   │
│  │ c_paris          │ c_ile_de_france    │ HIGH (name)  │                   │
│  │ c_jerusalem      │ c_jerusalem        │ EXACT        │                   │
│  │ b_tower_of_london│ b_london_tower     │ MEDIUM       │                   │
│  │ c_viken          │ ???                │ NEEDS_REVIEW │                   │
│  └──────────────────┴────────────────────┴──────────────┘                   │
│                                                                              │
│  REGION MAPPING TABLE                                                        │
│  ┌──────────────────────────────┬─────────────────────────┐                 │
│  │ Vanilla Region              │ Map Mod Equivalent(s)    │                 │
│  ├──────────────────────────────┼─────────────────────────┤                 │
│  │ world_europe_west_britannia │ world_britannia          │                 │
│  │ custom_norse_homeland       │ custom_norse_homeland    │ (unchanged)    │
│  └──────────────────────────────┴─────────────────────────┘                 │
│                                                                              │
│  HOLY SITE MAPPING TABLE                                                     │
│  ┌──────────────────┬────────────────────┬────────────────────┐             │
│  │ Holy Site ID     │ Vanilla Barony     │ Map Mod Barony     │             │
│  ├──────────────────┼────────────────────┼────────────────────┤             │
│  │ holy_site_rome   │ b_roma             │ b_roma             │ (same)      │
│  │ holy_site_mecca  │ b_mecca            │ b_mecca_city       │             │
│  └──────────────────┴────────────────────┴────────────────────┘             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Phase 2: MCP Tools for Map Conversion Agent

| Tool | Purpose |
|------|---------|
| `ck3_build_title_mapping` | Compare vanilla vs map mod `landed_titles`, build mapping table |
| `ck3_build_region_mapping` | Compare `geographical_region` definitions |
| `ck3_build_holy_site_mapping` | Map vanilla holy sites to their new locations |
| `ck3_find_unmapped_refs` | Find all references to vanilla titles that don't exist in map mod |
| `ck3_suggest_mapping` | Fuzzy match + heuristics to suggest mappings for ambiguous cases |
| `ck3_apply_conversion` | Apply the mapping to a mod's files |

### Phase 3: Mapping Confidence Levels

```python
class MappingConfidence(Enum):
    EXACT = "exact"           # Same ID in both
    HIGH = "high"             # Strong name/location match
    MEDIUM = "medium"         # Fuzzy match, likely correct
    LOW = "low"               # Possible match, needs review
    UNMAPPED = "unmapped"     # No match found
    REMOVED = "removed"       # Title exists in vanilla but intentionally not in map mod
    NEW = "new"               # Title only exists in map mod
```

### Phase 4: Heuristics for Auto-Mapping

1. **Exact ID Match** → `EXACT` (many titles unchanged)
2. **Parent Title Match** → If `c_x` is under `d_y` in both, high confidence
3. **Geographic Proximity** → If provinces are near each other, likely related
4. **Name Similarity** → Levenshtein distance on localized names
5. **Barony Count Match** → If county has same number of baronies, likely same county
6. **Cultural/Religious Context** → Holy sites for same faith should map to same region

### Phase 5: Agent Workflow

```
1. ANALYZE PHASE
   ├─ Load vanilla landed_titles into structured index
   ├─ Load map mod landed_titles into structured index
   ├─ Run auto-mapping with confidence scoring
   ├─ Generate "ambiguous mappings" report for human review
   └─ Human confirms/corrects ambiguous mappings

2. CONVERT PHASE
   ├─ For each gameplay mod (e.g., Pagan Religions):
   │   ├─ Find all title/region/holy_site references
   │   ├─ Apply mapping table
   │   ├─ Flag any UNMAPPED references for manual review
   │   └─ Generate converted version
   └─ Output: Ready-to-use compatch files

3. VALIDATE PHASE
   ├─ Parse all generated files
   ├─ Check all references resolve in map mod context
   └─ Report any broken references
```

---

## Why This Is Feasible

1. **Structured Data**: Landed titles are hierarchical (`e_` → `k_` → `d_` → `c_` → `b_`). We can parse and compare them systematically.

2. **Finite Problem**: There are ~5,000 titles in vanilla, ~6,000 in MB+. A mapping table is a one-time creation that then applies to all mods.

3. **High Automation Potential**: Estimated 70-80% of mappings would be `EXACT` or `HIGH` confidence, requiring no human input.

4. **Incremental**: Once the base mapping exists, updating for a new MB+ version only requires diffing.

5. **Reusable**: The same infrastructure works for ANY map mod (TFE, AGOT, etc.) - just regenerate the mapping index.

---

## Implementation Requirements

### Database Extensions

New tables for mapping storage:
```sql
CREATE TABLE title_mappings (
    mapping_id INTEGER PRIMARY KEY,
    source_mod_id INTEGER,      -- e.g., vanilla
    target_mod_id INTEGER,      -- e.g., MB+
    source_title TEXT,
    target_title TEXT,
    confidence TEXT,            -- EXACT, HIGH, MEDIUM, LOW, UNMAPPED
    mapping_reason TEXT,        -- Why this mapping was chosen
    verified_by_human INTEGER DEFAULT 0,
    created_at TIMESTAMP
);

CREATE TABLE region_mappings (...);
CREATE TABLE holy_site_mappings (...);
```

### Title Parser Enhancement

Parse `landed_titles` into a proper hierarchy data structure with:
- Province IDs
- Capital info
- Parent/child relationships
- Cultural names from localization

### Fuzzy Matcher

Sophisticated matching considering:
- Name similarity (Levenshtein)
- Parent title match
- Children titles match
- Province adjacency
- Localized name similarity

### Conversion Engine

Apply mappings across an entire mod:
- Find all title/region references
- Substitute according to mapping table
- Report unmapped references

### UI for Ambiguous Cases

Quick interface to resolve: "Did `c_old` become `c_new_a` or `c_new_b`?"

---

## Potential Use Cases

1. **MB+ Compatch for Religion Mods**: Convert Pagan Religions, Hellenism Reloaded, etc.
2. **MB+ Compatch for Building Mods**: Remap special building locations
3. **MB+ Compatch for Decision Mods**: Fix title-based decisions
4. **Future Map Mods**: TFE, AGOT, or any other total conversion

---

## Success Metrics

- **Automation Rate**: Target 80%+ of mappings auto-resolved
- **Time Savings**: Hours → Minutes for per-mod conversion
- **Error Rate**: <5% broken references after conversion
- **Maintainability**: New MB+ version → <1 hour to update mappings

---

## Related Work

- Current conflict resolution system (Phase 3-4)
- Symbol extraction and reference tracking
- Localization handling

This builds on the existing ck3raven infrastructure for parsing and symbol management.
