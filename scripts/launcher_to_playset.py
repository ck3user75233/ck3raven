#!/usr/bin/env python3
"""
Launcher JSON to CK3Raven Playset Converter

Converts a CK3 launcher.json playset export to the ck3raven playset format
with full agent_briefing support.

Usage:
    python launcher_to_playset.py <launcher_export.json> [output.json]

The output goes to playsets/ folder by default.
"""
import json
import sys
from pathlib import Path
from datetime import date
from typing import Any


PLAYSETS_DIR = Path(__file__).parent.parent / "playsets"
STEAM_WORKSHOP = Path("C:/Program Files (x86)/Steam/steamapps/workshop/content/1158310")
LOCAL_MODS = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"


def convert_launcher_to_playset(launcher_data: dict[str, Any]) -> dict[str, Any]:
    """
    Convert CK3 launcher.json format to ck3raven playset format.
    
    Args:
        launcher_data: Parsed launcher.json content
    
    Returns:
        ck3raven playset dict
    """
    today = date.today().isoformat()
    
    playset = {
        "$schema": "./playset.schema.json",
        "playset_name": launcher_data.get("name", "Imported Playset"),
        "description": f"Imported from CK3 Launcher on {today}",
        "created": today,
        "last_modified": today,
        
        "vanilla": {
            "version": launcher_data.get("gameVersion", "unknown"),
            "path": "C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game",
            "enabled": True
        },
        
        "mods": [],
        "live_mods": [],
        
        "agent_briefing": {
            "context": "",
            "error_analysis_notes": [
                "Fill in notes about which errors to prioritize or ignore"
            ],
            "conflict_resolution_notes": [
                "Fill in notes about expected conflicts (e.g., compatch mods)"
            ],
            "mod_relationships": [],
            "priorities": [
                "1. Crashes and game-breaking errors",
                "2. Gameplay-affecting bugs during steady play",
                "3. Minor visual/localization issues"
            ],
            "custom_instructions": ""
        },
        
        "sub_agent_config": {
            "error_analysis": {
                "enabled": True,
                "auto_spawn_threshold": 50,
                "output_format": "markdown",
                "include_recommendations": True
            },
            "conflict_review": {
                "enabled": False,
                "min_risk_score": 70,
                "require_approval": True
            }
        }
    }
    
    # Convert mods
    mods_list = launcher_data.get("mods", [])
    for i, mod in enumerate(mods_list):
        mod_entry = {
            "name": mod.get("displayName", mod.get("name", f"Mod {i}")),
            "load_order": i,
            "enabled": mod.get("enabled", True),
            "is_compatch": False,
            "notes": ""
        }
        
        # Extract steam ID
        steam_id = mod.get("steamId") or mod.get("pdxId") or mod.get("id")
        if steam_id:
            mod_entry["steam_id"] = str(steam_id)
            mod_entry["path"] = str(STEAM_WORKSHOP / str(steam_id))
        elif mod.get("path"):
            mod_entry["path"] = mod["path"]
        else:
            mod_entry["path"] = str(LOCAL_MODS / mod_entry["name"])
        
        # Detect compatch mods by name
        name_lower = mod_entry["name"].lower()
        if any(x in name_lower for x in ["compatch", "compatibility", "patch", "fix"]):
            mod_entry["is_compatch"] = True
        
        playset["mods"].append(mod_entry)
    
    return playset


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    input_path = Path(sys.argv[1])
    
    # Handle relative paths from AI Workspace
    if not input_path.is_absolute():
        ai_workspace = Path.home() / "Documents" / "AI Workspace"
        input_path = ai_workspace / input_path
    
    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
    else:
        output_path = PLAYSETS_DIR / f"{input_path.stem}_playset.json"
    
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)
    
    # Load launcher JSON
    try:
        launcher_data = json.loads(input_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}")
        sys.exit(1)
    
    # Convert
    playset = convert_launcher_to_playset(launcher_data)
    
    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(playset, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    
    print(f"✓ Converted {len(playset['mods'])} mods to playset format")
    print(f"  Output: {output_path}")
    print()
    print("Next steps:")
    print("  1. Edit the playset and fill in agent_briefing notes")
    print("  2. Add live_mods entries for mods the agent can edit")
    print("  3. Set is_compatch=true for compatibility patch mods")
    print("  4. Add mod_relationships for expected conflicts")


if __name__ == "__main__":
    main()
