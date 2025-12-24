# CK3 Compass

> **Status:** Planned Future Feature  
> **Target:** Post-MSC stabilization  
> **Last Updated:** December 24, 2025

## Overview

**ck3compass** is a planned capability within ck3raven that enables automated and AI-assisted compatching of mods across different CK3 map systems (vanilla, More Bookmarks+, Ibn Battuta's Legacy, etc.).

## Problem Statement

Total conversion and map expansion mods fundamentally restructure CK3's geography. Any mod that references vanilla titles, provinces, holy sites, or geographical regions **breaks** when loaded with these map mods.

Current compatching is:
- **Time-consuming** - Hours per mod, per map target
- **Error-prone** - Easy to miss references or map incorrectly
- **Unsustainable** - Must redo for each map mod update

## Solution

Build **conversion reference tables** within ck3raven that enable:
1. Automated conversion of simple mods
2. AI-assisted conversion with human review for ambiguous cases
3. Validation of existing compatches for completeness

## Documentation

| Document | Description |
|----------|-------------|
| [DESIGN_BRIEF.md](DESIGN_BRIEF.md) | Full design specification |
| [QUANTITATIVE_ANALYSIS.md](QUANTITATIVE_ANALYSIS.md) | MB+ vs Vanilla comparison data |

## Key Insight

This leverages **existing ck3raven infrastructure**:
- Parser → Extract title/province references
- Symbol extraction → Inventory all defined titles
- Conflict analysis → Identify overrides
- Lookup tables → Store mappings

No new parsing or database architecture needed - just new tables and MCP tools.

## Prerequisites

Before implementing ck3compass:
1. ✅ Core ck3raven database stable
2. ✅ Symbol extraction working
3. ✅ Conflict analysis tools working
4. ⬜ Title/holy site lookup tables complete
5. ⬜ Multi-playset switching tested

## Next Steps (When Ready)

1. Create isolated MB+ playset (vanilla + MB+ only)
2. Add `map_systems` and `compass_*_mappings` tables
3. Implement extraction and matching algorithms
4. Build proof-of-concept with MB+ mappings
