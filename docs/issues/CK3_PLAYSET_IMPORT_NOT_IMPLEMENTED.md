# ck3_playset Import Command Not Implemented

**Date:** January 5, 2026  
**Status:** Open  
**Component:** `tools/ck3lens_mcp/server.py` - `ck3_playset` tool  

## Issue

The `ck3_playset(command="import")` MCP tool command exists in the function signature but returns:

```python
{
  "success": false,
  "error": "Command 'import' not yet implemented for file-based playsets",
  "hint": "Use 'get', 'list', 'switch', or 'mods' commands"
}
```

## Current Workaround

The `scripts/launcher_to_playset.py` script successfully converts CK3 launcher JSON exports to ck3raven playset format:

```bash
python scripts/launcher_to_playset.py "C:\path\to\launcher_export.json"
```

This creates a properly formatted playset in `playsets/` folder.

## Proposed Fix

Integrate `launcher_to_playset.py` functionality into the MCP tooling:

1. **Option A:** Pull the conversion logic from `launcher_to_playset.py` directly into the `ck3_playset` tool's import command handler

2. **Option B:** Have the import command call the script internally

### Implementation Notes

The `launcher_to_playset.py` script:
- Converts launcher JSON format (`displayName`, `steamId`, `position`) to ck3raven format (`name`, `steam_id`, `load_order`)
- Auto-detects compatch mods by name patterns
- Generates proper agent_briefing and sub_agent_config scaffolding
- Resolves Steam Workshop paths from steam_id
- Outputs to `playsets/` folder with `_playset.json` suffix

### Expected API

```python
ck3_playset(
    command="import",
    launcher_playset_name="MSC Religion Expanded Jan 5",
    # OR
    launcher_json_path="C:/path/to/launcher_export.json"
)
```

Should return:
```python
{
    "success": true,
    "playset_file": "MSC Religion Expanded Jan 5_playset.json",
    "mod_count": 107,
    "message": "Imported playset. Edit agent_briefing and add local_mods as needed."
}
```

## Priority

Medium - workaround exists but requires manual script execution.
