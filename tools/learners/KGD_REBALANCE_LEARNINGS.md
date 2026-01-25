# KGD Rebalance Learnings - Session 2026-01-26

## Overview

Analysis of KGD: The Great Rebalance (Workshop ID: 3422759424) to understand rebalancing patterns for creating compatibility patches.

---

## 1. MAA (Men-at-Arms) Patterns

**Source:** `kgd_maa_patterns_v3.json` (62KB, 109 MAA types analyzed)

### Global Variables Changed

| Variable | Vanilla | KGD | Change |
|----------|---------|-----|--------|
| `maa_buy_cost` | 150 | 150 | Unchanged |
| `maa_low_maintenance_cost` | 1.0 | 1.0 | Unchanged |
| `maa_high_maintenance_cost` | 5.0 | 5.0 | Unchanged |
| `cultural_maa_extra_ai_score` | 80 | 60 | -25% |
| `provisions_cost_infantry_cheap` | 3 | 4 | +33% |
| `provisions_cost_infantry_moderate` | 7 | 10 | +43% |
| `provisions_cost_infantry_expensive` | 12 | 18 | +50% |
| `provisions_cost_cavalry_cheap` | 7 | 12 | +71% |
| `provisions_cost_cavalry_moderate` | 15 | 26 | +73% |
| `provisions_cost_cavalry_expensive` | 21 | 34 | +62% |

### Key MAA Patterns

1. **Provision costs significantly increased** - Makes armies more expensive to maintain
2. **Cultural MAA AI preference reduced** - AI less likely to spam cultural units
3. **Terrain bonuses adjusted** per unit type
4. **Counter relationships modified**

---

## 2. Building Values Patterns

**Source:** `kgd_building_values.json` (extracted from `BKT_building_values.txt`)

### Summary Statistics

| Category | Variables Changed | Avg Multiplier |
|----------|------------------|----------------|
| Tax | 18 | 0.60x (reduced 40%) |
| Levy | 10 | 0.44x (reduced 56%) |
| MAA Maintenance | 2 | 0.50x (halved) |
| Development | 8 | 0.50x (halved) |
| Garrison | 6 | 0.51x (halved) |
| Cost | 2 | 1.42x (increased 42%) |

### Specific Value Changes

| Variable | Vanilla | KGD | Multiplier |
|----------|---------|-----|------------|
| `poor_tax_base` | 0.25 | 0.125 | 0.5x |
| `normal_tax_base` | 0.35 | 0.2 | 0.57x |
| `good_tax_base` | 0.5 | 0.25 | 0.5x |
| `excellent_tax_base` | 0.7 | 0.35 | 0.5x |
| `poor_levy_scale_addition_per_tier` | 25 | 10 | 0.4x |
| `normal_levy_scale_addition_per_tier` | 75 | 35 | 0.47x |
| `low_development_growth_base` | 0.01 | 0 | 0x (removed) |
| `normal_development_growth_base` | 0.02 | 0 | 0x (removed) |
| `good_development_growth_base` | 0.04 | 0 | 0x (removed) |

### Design Philosophy

KGD's building rebalance follows a "slow snowball" philosophy:
- Buildings give ~50% less income
- Buildings give ~50% fewer levies per tier
- Development growth from buildings completely removed
- Building costs increased ~40%

This makes early advantages compound more slowly.

---

## 3. Building Override Strategy

### Counts

| Metric | Count |
|--------|-------|
| Vanilla buildings total | 945 |
| KGD buildings total | 557 |
| Buildings KGD overrides | 557 |
| Buildings vanilla-only (untouched) | 388 |
| New buildings KGD adds | 0 |

### File Strategy

KGD uses `01_*.txt` filenames to load AFTER vanilla's `00_*.txt` files. Since CK3 uses OVERRIDE at the **symbol level** (not file level), this means:
- Buildings defined in BOTH get KGD's version (557)
- Buildings only in vanilla remain vanilla (388)

### Files KGD Does NOT Override

| Vanilla File | Untouched Buildings | Reason |
|--------------|---------------------|--------|
| `00_special_mines.txt` | 215 | Location-specific mines - use scripted values for numbers |
| `00_standard_economy_buildings.txt` | 112 | Subset left vanilla (see below) |
| `temple_citadel_buildings.txt` | 28 | DLC content (Roads to Power) |
| `00_admin_buildings.txt` | 8 | DLC content (Roads to Power) |
| `00_city_buildings.txt` | 8 | Guild halls |
| `00_temple_buildings.txt` | 8 | Some temple buildings |
| `99_background_graphics_buildings.txt` | 6 | Cosmetic only |
| `ccp3_special_buildings.txt` | 2 | Community pack |
| `00_nomad_buildings.txt` | 1 | 1 nomad building |

### Economy Buildings KGD Skips (112 total)

| Building Chain | Count | Likely Reason |
|----------------|-------|---------------|
| `caravanserai_*` | 8 | Uses scripted values → indirectly rebalanced |
| `common_tradeport_*` | 8 | Uses scripted values |
| `elephant_pens_*` | 8 | Regional/cultural specific |
| `farm_estates_*` | 8 | Uses scripted values |
| `hill_farms_*` | 8 | Uses scripted values |
| `logging_camps_*` | 8 | Uses scripted values |
| `paddy_fields_*` | 8 | Regional (East Asia) |
| `peat_quarries_*` | 8 | Uses scripted values |
| `plantations_*` | 8 | Regional |
| `qanats_*` | 8 | Cultural (Persian) |
| `quarries_*` | 8 | Uses scripted values |
| `spice_plantation_*` | 8 | Regional (India) |
| `waterworks_*` | 4 | Regional |

### Why Some Buildings Are Skipped

**Two categories:**

1. **Rely on scripted values for numbers** - These buildings use tokens like `normal_building_tax_tier_1` which resolve to values in `00_building_values.txt`. KGD overrides those values in `BKT_building_values.txt`, so the buildings are **indirectly rebalanced** without needing to override their definitions.

2. **Regional/cultural specific** - Elephant pens, paddy fields, spice plantations, etc. are niche buildings that may be intentionally left vanilla.

---

## 4. Implications for Patching

### Mod Content That Gets Auto-Rebalanced

If a mod adds buildings/MAA that use vanilla's scripted values:
- `normal_building_tax_tier_1`
- `excellent_building_levy_tier_2`
- `@maa_buy_cost`
- etc.

→ **Automatically rebalanced** by KGD's value overrides. No patch needed.

### Mod Content That Needs Patching

If a mod hardcodes numeric values:
```pdx
province_modifier = {
    monthly_income = 0.5  # Hardcoded, won't be affected by KGD
}
```

→ **Needs patching** to match KGD's reduced numbers (multiply by ~0.5x for tax).

### DLC Content

- Roads to Power (Admin, Temple Citadel buildings) → KGD doesn't touch
- Other DLCs → May or may not be patched, check per-DLC

---

## 5. Pattern Summary for Applicator Tool

### Tax/Income Modifiers
- Multiply by **0.5-0.6x**

### Levy Modifiers
- Multiply base by **~1.0x** (unchanged)
- Multiply scaling by **0.4-0.5x**

### Development Growth
- Set to **0** (remove entirely)

### Garrison
- Multiply by **~0.5x**

### MAA Provision Costs
- Infantry: multiply by **1.3-1.5x**
- Cavalry: multiply by **1.6-1.8x**

### Building Costs
- Multiply by **~1.4x**

---

## 6. Files Generated

| File | Contents |
|------|----------|
| `kgd_maa_patterns_v3.json` | 109 MAA comparisons with terrain/counter changes |
| `kgd_building_values.json` | 64 changed variables with multipliers |
| `kgd_rebalance_learner.py` | MAA learner script |
| `kgd_building_values_learner.py` | Building values learner script |

---

## 7. Next Steps

1. **Unified Learner** - Extract patterns automatically from AST structure without hardcoding fields
2. **Pattern Applicator** - Tool to apply learned multipliers to new mod content
3. **Patch Generator** - Generate zzz_ override files for mods that need patching
