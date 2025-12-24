# CK3 Compass: Quantitative Analysis

> **Comparison:** More Bookmarks+ vs Vanilla CK3  
> **Date:** December 24, 2025  
> **MB+ Version:** 1.3 (Steam ID: 2216670956)  
> **CK3 Version:** 1.18.2

---

## Executive Summary

More Bookmarks+ represents a **major restructuring** of CK3's map:
- **~3x more empires** (66 → 190)
- **~2.5x more kingdoms** (193 → 505)
- **~2x more duchies** (1,211 → 2,606)
- **~1.5x more counties** (3,074 → 4,557)
- **~2x more holy sites** (323 → 682)

Province IDs 1-14139 are **shared** between systems, enabling direct mapping for most provinces.

---

## Map Infrastructure

### Provinces (definition.csv)

| Metric | Vanilla | MB+ | Difference |
|--------|---------|-----|------------|
| Total provinces | 14,152 | 14,198 | +46 (+0.3%) |
| Province IDs 1-14139 | ✓ | ✓ | Shared |
| Province IDs 14140+ | — | 59 new | China expansion |

**Key finding:** Province IDs are largely compatible. New provinces added primarily in China region.

### File Sizes

| File | Vanilla | MB+ |
|------|---------|-----|
| definition.csv | 14,154 lines | 14,200 lines |
| 00_landed_titles.txt | 1.29 MB | 1.88 MB (+46%) |
| 00_holy_sites.txt | 67 KB | 154 KB (+130%) |
| geographical_region.txt | 140 KB | 160 KB (+14%) |

---

## Title Hierarchy

### Counts by Tier

| Title Tier | Vanilla | MB+ | Difference |
|------------|---------|-----|------------|
| Empires (e_) | 66 | 190 | +124 (+188%) |
| Kingdoms (k_) | 193 | 505 | +312 (+162%) |
| Duchies (d_) | 1,211 | 2,606 | +1,395 (+115%) |
| Counties (c_) | 3,074 | 4,557 | +1,483 (+48%) |
| Baronies (b_) | 8,847 | 11,886 | +3,039 (+34%) |
| **Total** | **13,391** | **19,744** | **+6,353 (+47%)** |

### Implications

- Nearly **triple** the empires means dramatically different high-level political structure
- De jure kingdom/duchy assignments likely differ substantially
- Many vanilla titles exist with same ID but different de jure positions

---

## Religious Infrastructure

### Holy Sites

| Metric | Vanilla | MB+ | Difference |
|--------|---------|-----|------------|
| Holy site definitions | 323 | 682 | +359 (+111%) |
| File size | 67 KB | 154 KB | +130% |

### Example Mapping Discovery

```
Holy site: santiago
  Vanilla: county = c_santiago
  MB+:     county = c_tui
```

Same logical holy site, different physical county. This is the **semantic mapping** pattern.

---

## History Files

| Category | Vanilla | MB+ | Difference |
|----------|---------|-----|------------|
| Province history files | 178 | 183 | +5 |
| Title history files | 183 | 257 | +74 (+40%) |

---

## Scripted Content

### Title References in Vanilla Decisions

| Reference Type | Count |
|----------------|-------|
| `title:e_*` | 311 |
| `title:k_*` | 275 |
| `title:d_*` | 300 |
| `title:c_*` | 130 |
| `title:b_*` | 136 |
| **Total** | **1,152** |

### MB+ Override Pattern

MB+ creates `z_MB_REPLACE_*` files that completely restate regional decisions:

```
z_MB_REPLACE_major_decisions_british_isles.txt
z_MB_REPLACE_major_decisions_central_asia.txt
z_MB_REPLACE_major_decisions_east_europe.txt
z_MB_REPLACE_major_decisions_iberia_north_africa.txt
z_MB_REPLACE_major_decisions_middle_east.txt
z_MB_REPLACE_major_decisions_middle_europe.txt
z_MB_REPLACE_major_decisions_south_asia.txt
z_MB_REPLACE_major_decisions_south_europe.txt
```

This is the pattern we need to automate.

---

## Geographical Regions

| Metric | Vanilla | MB+ |
|--------|---------|-----|
| Main region file | 140 KB | 160 KB |
| Additional region files | 1 | 8 |

MB+ adds compatibility regions for:
- RICE submod
- Celtic Expansion (CE)
- Other integrations

---

## Culture and Other Content

| Content Type | Vanilla Files | MB+ Files |
|--------------|---------------|-----------|
| Culture | 141 | 73 |
| Decisions | 34 | 15 |
| Scripted triggers | 135 | 15 |
| Scripted effects | 165 | 19 |
| Buildings | 19 (56K lines) | 8 (7K lines) |

MB+ has **fewer** files in many categories because it uses selective overrides rather than full replacements.

---

## File Types Affected by Map Mods

### Primary (Direct References)

| Type | Location | Impact |
|------|----------|--------|
| Landed titles | `common/landed_titles/` | Complete restructure |
| Holy sites | `common/religion/holy_sites/` | County remapping |
| Province history | `history/provinces/` | Province-specific setup |
| Title history | `history/titles/` | Title existence changes |
| Geographical regions | `map_data/geographical_regions/` | Region redefinition |
| Definition.csv | `map_data/` | Core map data |

### Secondary (Scripted References)

| Type | Location | Impact |
|------|----------|--------|
| Decisions | `common/decisions/` | Logic tied to titles |
| Events | `events/` | Narrative references |
| Scripted triggers | `common/scripted_triggers/` | Reusable logic |
| Scripted effects | `common/scripted_effects/` | Action code |
| On actions | `common/on_action/` | Timing hooks |
| Story cycles | `common/story_cycles/` | Narrative boundaries |

### Tertiary (Implicit Dependencies)

| Type | Location | Impact |
|------|----------|--------|
| Buildings | `common/buildings/` | Location-specific buffs |
| Culture | `common/culture/` | Heritage regions |
| Coat of arms | `common/coat_of_arms/` | Visual identity |
| Localization | `localization/` | Display strings |

---

## Mapping Complexity Estimate

### Straightforward (Automatable)

- **Exact matches:** ~2,500 titles (same ID in both systems)
- **Province IDs 1-14139:** Direct mapping

### Requires Algorithm

- **Renamed titles:** ~500 estimated (different ID, same location)
- **New MB+ titles:** ~3,800 (no vanilla source)

### Requires Human Review

- **Split/merged titles:** Unknown count
- **Semantic mappings:** Holy sites, special locations
- **Ambiguous cases:** Multiple candidates

---

## Conclusion

The mapping problem is **well-structured and automatable**:

1. Province IDs are largely shared → direct mapping
2. Many titles have exact matches → automatable
3. Holy sites follow semantic pattern → discoverable
4. MB+ override files show the transformation pattern

With ck3raven's existing parser and symbol extraction, we can build comprehensive mapping tables that enable automated mod conversion for simple cases and AI-assisted conversion for complex cases.
