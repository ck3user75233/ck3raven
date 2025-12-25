# CK3Raven Playsets

This folder contains playset configuration files for CK3 modding work.

## What is a Playset?

A playset defines:
- Which mods are included (in load order)
- Which mods the agent can write to (live_mods)
- Agent briefing notes for error analysis and conflict resolution
- Sub-agent configuration for automated review

## Files

| File | Description |
|------|-------------|
| `playset.schema.json` | JSON Schema for playset files |
| `example_playset.json` | Template playset to copy and customize |
| `sub_agent_templates.json` | Templates for sub-agent briefings |

## Creating a Playset

### Option 1: Convert from CK3 Launcher

```bash
python scripts/launcher_to_playset.py "My Playset Export.json"
```

This creates a playset from a CK3 launcher export.

### Option 2: Create Manually

1. Copy `example_playset.json` to a new file
2. Edit the mods list (in load order)
3. Add live_mods for mods the agent can write to
4. Fill in agent_briefing notes

## Switching Playsets

Use the MCP tools:

```
ck3_list_playsets()      # See available playsets
ck3_switch_playset("MSC") # Switch to a playset by name
ck3_get_active_playset()  # Check current playset
ck3_get_agent_briefing()  # Get briefing notes for sub-agents
```

## Agent Briefing

The `agent_briefing` section tells AI agents important context:

```json
"agent_briefing": {
  "context": "Developing MSC compatibility patch",
  
  "error_analysis_notes": [
    "Errors from Morven's compatch target mods are expected",
    "Focus on steady-play errors, not loading errors"
  ],
  
  "conflict_resolution_notes": [
    "Morven's compatch handles the 8 mods before it",
    "Don't duplicate conflict resolution Morven already does"
  ],
  
  "mod_relationships": [
    {
      "mod": "Morven's Compatch",
      "relationship": "handles_conflicts_for",
      "targets": ["Mod A", "Mod B"],
      "notes": "Expected to override these"
    }
  ],
  
  "priorities": [
    "1. Crashes",
    "2. Gameplay bugs",
    "3. Visual issues"
  ]
}
```

## Sub-Agent Configuration

The `sub_agent_config` section controls when sub-agents are spawned:

```json
"sub_agent_config": {
  "error_analysis": {
    "enabled": true,
    "auto_spawn_threshold": 50,
    "output_format": "markdown",
    "include_recommendations": true
  },
  "conflict_review": {
    "enabled": false,
    "min_risk_score": 70,
    "require_approval": true
  }
}
```

## Sub-Agent Templates

The file `sub_agent_templates.json` contains pre-defined briefings for common tasks:

| Template | Purpose |
|----------|---------|
| `error_analysis` | Briefing for error log analysis sub-agents |
| `conflict_resolution` | Briefing for conflict resolution sub-agents |
| `mod_development` | Briefing for mod creation sub-agents |

Use `ck3_get_agent_briefing(template="error_analysis")` to get the full briefing.

## Active Playset Selection

The MCP server automatically loads the first `.json` file in the `playsets/` folder.
To switch playsets:

1. Use `ck3_list_playsets()` to see available playsets
2. Use `ck3_switch_playset("MyPlayset")` to activate

## Schema Validation

Playsets are validated against `playset.schema.json`. Required fields:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique playset identifier |
| `mods` | array | Ordered list of mod definitions |
| `live_mods` | array | Names of mods the agent can write to |

Optional fields: `description`, `created_at`, `agent_briefing`, `sub_agent_config`

## Migration from Database

If you have playsets in the old database format, run:

```bash
python scripts/launcher_to_playset.py --migrate-db
```

This exports existing database playsets to JSON files.
