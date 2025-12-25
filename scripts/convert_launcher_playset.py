#!/usr/bin/env python3
"""
Convert CK3 Launcher playset JSON to active_mod_paths.json format.

Usage:
    python convert_launcher_playset.py "MSC Religion Expanded Dec20.json" [--add-local]
"""

import json
import sys
from pathlib import Path

# Paths
AI_WORKSPACE = Path(r"C:\Users\Nathan\Documents\AI Workspace")
STEAM_BASE = Path(r"C:\Program Files (x86)\Steam\steamapps\workshop\content\1158310")
LOCAL_MOD_BASE = Path(r"C:\Users\Nathan\Documents\Paradox Interactive\Crusader Kings III\mod")
OUTPUT_FILE = AI_WORKSPACE / "active_mod_paths.json"

# Local mods to add at the end (in order)
LOCAL_MODS = [
    ("Lowborn Rise Expanded", "Lowborn Rise Expanded"),
    ("More Raid and Prisoners", "More Raid and Prisoners"),
    ("Mini Super Compatch", "Mini Super Compatch"),
    ("MSC Religion Expanded", "MSCRE"),
    ("VanillaPatch", "VanillaPatch"),
]


def main():
    if len(sys.argv) < 2:
        print("Usage: python convert_launcher_playset.py <playset_file.json>")
        return 1
    
    launcher_file = AI_WORKSPACE / sys.argv[1]
    if not launcher_file.exists():
        print(f"Error: File not found: {launcher_file}")
        return 1
    
    print(f"Reading: {launcher_file.name}")
    launcher_data = json.loads(launcher_file.read_text())
    playset_name = launcher_data.get("name", "Unknown Playset")
    
    # Build paths array from enabled mods
    paths = []
    for mod in launcher_data.get("mods", []):
        if not mod.get("enabled", True):
            continue  # Skip disabled mods
        
        steam_id = mod.get("steamId", "")
        if steam_id:
            path = str(STEAM_BASE / steam_id)
        else:
            path = ""
        
        paths.append({
            "load_order": mod.get("position", 999),
            "path": path,
            "enabled": True,
            "name": mod.get("displayName", "Unknown"),
            "steam_id": steam_id
        })
    
    # Sort by load order
    paths.sort(key=lambda x: x["load_order"])
    
    print(f"Found {len(paths)} enabled Steam mods")
    
    # Add local mods at the end
    max_order = max(p["load_order"] for p in paths) + 1 if paths else 0
    
    add_local = "--add-local" in sys.argv or True  # Always add for now
    if add_local:
        for i, (name, folder) in enumerate(LOCAL_MODS):
            mod_path = LOCAL_MOD_BASE / folder
            paths.append({
                "load_order": max_order + i,
                "path": str(mod_path),
                "enabled": True,
                "name": name,
                "steam_id": ""
            })
        print(f"Added {len(LOCAL_MODS)} local mods at end")
    
    # Create output
    output = {
        "not_found": 0,
        "playset_name": playset_name,
        "paths": paths
    }
    
    # Write to file
    OUTPUT_FILE.write_text(json.dumps(output, indent=2))
    
    print(f"\nCreated: {OUTPUT_FILE}")
    print(f"Total mods: {len(paths)}")
    print(f"Playset name: {playset_name}")
    print("\nLast 5 mods in load order:")
    for p in paths[-5:]:
        print(f"  [{p['load_order']:3}] {p['name']}")
    
    print("\nNext steps:")
    print("  1. Update scripts/create_playset.py with the new playset name")
    print("  2. Run: python scripts/create_playset.py")
    print("  3. Run: python builder/daemon.py start (if needed)")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
