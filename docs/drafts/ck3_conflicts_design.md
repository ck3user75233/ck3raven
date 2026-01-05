# ck3_conflicts Unified Tool Design

> **Status:** DESIGN
> **Author:** Agent (ck3raven-dev mode)
> **Date:** January 2, 2026

## Overview

Single unified MCP tool for conflict analysis, replacing multiple scattered tools.

## Commands

### command="scan" (or "detect")
Fast ID-level conflict detection.

**Input:**
- `symbol_type: Optional[str]` - Filter by type (trait, event, on_action)
- `game_folder: Optional[str]` - Filter by folder (common/traits, events)
- `include_compatch: bool = False` - Include compatch conflicts
- `limit: int = 100`

**Output:**
```json
{
    "conflict_count": 42,
    "conflicts": [
        {
            "symbol_name": "brave",
            "symbol_type": "trait",
            "source_count": 3,
            "sources": [
                {"mod": "vanilla", "file": "common/traits/00_traits.txt", "line": 100},
                {"mod": "Mod A", "file": "common/traits/00_traits.txt", "line": 50},
                {"mod": "Mod B", "file": "common/traits/zzz_brave.txt", "line": 1}
            ]
        }
    ],
    "compatch_hidden": 5
}
```

### command="files"
File-level conflict detection with prefix analysis.

**Input:**
- `folder: Optional[str]` - Filter by folder
- `limit: int = 100`

**Output:**
```json
{
    "file_conflicts": [
        {
            "target_path": "common/traits/00_traits.txt",
            "mods": [
                {"mod": "Mod A", "path": "common/traits/00_traits.txt", "type": "full_overwrite"},
                {"mod": "Mod B", "path": "common/traits/zzz_00_traits.txt", "type": "prefix_override"}
            ]
        }
    ],
    "prefix_conflicts": [
        {
            "original": "common/on_action/game_start.txt",
            "prefixed_files": [
                {"mod": "Mod A", "path": "common/on_action/zzz_game_start.txt"},
                {"mod": "Mod B", "path": "common/on_action/zzz_game_start.txt"}
            ],
            "note": "Both mods use zzz_ prefix targeting same file"
        }
    ]
}
```

### command="detail"
Get detailed info about a specific conflict by symbol name.

**Input:**
- `symbol_name: str` - REQUIRED - The symbol to analyze
- `symbol_type: Optional[str]` - Type filter if needed

**Output:**
```json
{
    "symbol_name": "brave",
    "symbol_type": "trait",
    "merge_policy": "OVERRIDE",
    "winner": {"mod": "Mod B", "file": "common/traits/zzz_brave.txt", "reason": "loads last"},
    "losers": [
        {"mod": "vanilla", "file": "common/traits/00_traits.txt"},
        {"mod": "Mod A", "file": "common/traits/00_traits.txt"}
    ],
    "content_diff": {
        "winner_lines": 15,
        "vanilla_lines": 10,
        "diff_summary": "+5 lines, major structural changes"
    }
}
```

### command="report"
Risk-scored conflict report.

**Input:**
- `min_risk: Optional[str]` - Filter: "critical", "major", "minor", "info"
- `content_type: Optional[str]` - Filter by content type
- `limit: int = 50`

**Risk Levels:**

| Level | Criteria |
|-------|----------|
| CRITICAL | Multiple mods adding to CONTAINER_MERGE containers (faiths, traditions, on_action effects) - only last wins, others LOST |
| MAJOR | Full overwrite with major diff (>50% changed) across 2+ mods |
| MINOR | Partial override where symbols are unique per mod |
| INFO | Expected conflicts (compatch) or intentional overrides |

**Output:**
```json
{
    "summary": {
        "critical": 3,
        "major": 12,
        "minor": 45,
        "info": 100
    },
    "conflicts": [
        {
            "symbol_name": "on_game_start",
            "symbol_type": "on_action",
            "risk_level": "CRITICAL",
            "risk_reason": "Multiple mods define effect={} - only last wins",
            "mods_affected": ["CAD", "TCT", "RE"],
            "recommendation": "Chain via on_actions={} list instead"
        }
    ]
}
```

## NOT in this tool

- **resolve**: Separate `ck3_resolver` tool for game state emulation (Phase 2)
- Complex merge simulation - that's the emulator's job

## Risk Assessment Logic

```python
def assess_risk(symbol_name, symbol_type, sources, merge_policy):
    if merge_policy == "CONTAINER_MERGE":
        # Check if multiple mods define single-slot blocks (effect, trigger)
        if has_multiple_effect_blocks(sources):
            return "CRITICAL", "Multiple mods define effect={} - only last wins"
        else:
            return "INFO", "List blocks merge safely"
    
    elif merge_policy == "OVERRIDE":
        if len(sources) >= 3:
            return "MAJOR", f"{len(sources)} mods redefine - complex conflict"
        elif diff_is_major(sources):
            return "MAJOR", "Significant structural changes"
        else:
            return "MINOR", "Minor override"
    
    elif merge_policy == "FIOS":
        if first_is_vanilla(sources):
            return "INFO", "Vanilla wins (FIOS)"
        else:
            return "MINOR", "Mod overrides vanilla FIOS file"
    
    return "INFO", "Expected behavior"
```

## Implementation Plan

1. Create unified `ck3_conflicts_impl` in unified_tools.py
2. Wire up in server.py as `ck3_conflicts`
3. Deprecate/remove old scattered tools
4. Update CONFLICT_ANALYSIS_ARCHITECTURE.md
