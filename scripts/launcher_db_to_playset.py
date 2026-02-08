#!/usr/bin/env python3
"""
CK3 Launcher Database to CK3Raven Playset Converter

Reads directly from the CK3 launcher's SQLite database (launcher-v2.sqlite)
to create playsets with ALL mods including local mods at their correct positions.

This is the preferred import method because launcher JSON exports exclude local mods.

Usage:
    python launcher_db_to_playset.py "Mini Super Compatch 0702"
    python launcher_db_to_playset.py --list
    python launcher_db_to_playset.py --active
"""
import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional


# Default paths
LAUNCHER_DB = Path.home() / "Documents/Paradox Interactive/Crusader Kings III/launcher-v2.sqlite"
LOCAL_MODS_FOLDER = Path.home() / "Documents/Paradox Interactive/Crusader Kings III/mod"
PLAYSETS_DIR = Path(__file__).parent.parent / "playsets"
STEAM_WORKSHOP = Path("C:/Program Files (x86)/Steam/steamapps/workshop/content/1158310")
VANILLA_PATH = "C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game"


def get_connection(db_path: Path = LAUNCHER_DB) -> sqlite3.Connection:
    """Open read-only connection to launcher database."""
    if not db_path.exists():
        raise FileNotFoundError(f"Launcher database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def list_playsets(conn: sqlite3.Connection) -> list[dict]:
    """List all playsets in the launcher database."""
    rows = conn.execute("""
        SELECT id, name, isActive,
            (SELECT COUNT(*) FROM playsets_mods WHERE playsetId = playsets.id) as mod_count
        FROM playsets
        ORDER BY name
    """).fetchall()
    return [dict(row) for row in rows]


def get_playset_by_name(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    """Find playset by exact or partial name match."""
    # Try exact match first
    row = conn.execute(
        "SELECT id, name, isActive FROM playsets WHERE name = ?", (name,)
    ).fetchone()
    if row:
        return dict(row)
    
    # Try case-insensitive partial match
    row = conn.execute(
        "SELECT id, name, isActive FROM playsets WHERE name LIKE ?", (f"%{name}%",)
    ).fetchone()
    if row:
        return dict(row)
    
    return None


def get_active_playset(conn: sqlite3.Connection) -> Optional[dict]:
    """Get the currently active playset."""
    row = conn.execute(
        "SELECT id, name, isActive FROM playsets WHERE isActive = 1"
    ).fetchone()
    return dict(row) if row else None


def get_playset_mods(conn: sqlite3.Connection, playset_id: str) -> list[dict]:
    """Get all mods in a playset with their positions and paths."""
    rows = conn.execute("""
        SELECT 
            pm.position,
            pm.enabled,
            m.displayName,
            m.steamId,
            m.dirPath,
            m.source
        FROM playsets_mods pm
        JOIN mods m ON pm.modId = m.id
        WHERE pm.playsetId = ?
        ORDER BY pm.position
    """, (playset_id,)).fetchall()
    return [dict(row) for row in rows]


def is_local_mod(mod: dict) -> bool:
    """Determine if a mod is local (not from Steam Workshop)."""
    source = (mod.get('source') or '').lower()
    dir_path = mod.get('dirPath') or ''
    
    # Check source field
    if 'local' in source:
        return True
    
    # Check if path is outside workshop
    if dir_path and 'workshop' not in dir_path.lower():
        return True
    
    # No steam ID usually means local
    if not mod.get('steamId'):
        return True
    
    return False


def is_compatch_mod(name: str) -> bool:
    """Heuristically detect compatibility patch mods by name."""
    name_lower = name.lower()
    indicators = ['compatch', 'compatibility', 'patch', 'fix', 'hotfix']
    return any(ind in name_lower for ind in indicators)


def convert_to_playset(
    playset_info: dict,
    mods: list[dict],
    description: Optional[str] = None
) -> dict[str, Any]:
    """Convert launcher data to ck3raven playset format."""
    today = date.today().isoformat()
    
    playset_name = playset_info['name']
    
    # Build mods array
    mods_array = []
    local_count = 0
    steam_count = 0
    
    for mod in mods:
        display_name = mod['displayName']
        steam_id = mod.get('steamId')
        dir_path = mod.get('dirPath') or ''
        local = is_local_mod(mod)
        
        entry = {
            "name": display_name,
            "path": dir_path if dir_path else (
                str(LOCAL_MODS_FOLDER / display_name) if local 
                else str(STEAM_WORKSHOP / steam_id) if steam_id 
                else f"UNKNOWN/{display_name}"
            ),
            "load_order": mod['position'],
            "enabled": bool(mod['enabled']),
            "is_compatch": is_compatch_mod(display_name),
            "notes": "local mod" if local else ""
        }
        
        # Add steam_id only for workshop mods
        if steam_id and not local:
            entry["steam_id"] = steam_id
        
        mods_array.append(entry)
        
        if local:
            local_count += 1
        else:
            steam_count += 1
    
    # Build playset structure matching schema
    playset = {
        "$schema": "./playset.schema.json",
        "playset_name": playset_name,
        "description": description or f"Imported from CK3 Launcher DB on {today} ({steam_count} Steam, {local_count} local mods)",
        "created": today,
        "last_modified": today,
        
        "vanilla": {
            "version": "1.18",
            "path": VANILLA_PATH,
            "enabled": True
        },
        
        "mods": mods_array,
        
        "local_mods_folder": str(LOCAL_MODS_FOLDER),
        
        "agent_briefing": {
            "context": f"Playset '{playset_name}' with {len(mods_array)} mods",
            "error_analysis_notes": [
                "Focus on runtime errors during gameplay",
                "Loading errors from compatch targets may be expected"
            ],
            "conflict_resolution_notes": [
                "Mods marked is_compatch=true are expected to override others"
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
    
    return playset


def main():
    parser = argparse.ArgumentParser(
        description="Import playsets from CK3 launcher database (includes local mods)"
    )
    parser.add_argument(
        "playset_name",
        nargs="?",
        help="Name of playset to import (partial match supported)"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available playsets"
    )
    parser.add_argument(
        "--active", "-a",
        action="store_true",
        help="Import the currently active playset"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Output file path (default: playsets/<name>_playset.json)"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=LAUNCHER_DB,
        help=f"Launcher database path (default: {LAUNCHER_DB})"
    )
    
    args = parser.parse_args()
    
    # Open database
    try:
        conn = get_connection(args.db)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # List mode
    if args.list:
        playsets = list_playsets(conn)
        print(f"{'Name':<45} {'Mods':>5}  Active")
        print("-" * 60)
        for ps in playsets:
            active = "[*]" if ps['isActive'] else "   "
            print(f"{ps['name'][:44]:<45} {ps['mod_count']:>5}  {active}")
        return
    
    # Determine which playset to import
    if args.active:
        playset_info = get_active_playset(conn)
        if not playset_info:
            print("Error: No active playset found", file=sys.stderr)
            sys.exit(1)
    elif args.playset_name:
        playset_info = get_playset_by_name(conn, args.playset_name)
        if not playset_info:
            print(f"Error: Playset '{args.playset_name}' not found", file=sys.stderr)
            print("Use --list to see available playsets", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)
    
    # Get mods
    mods = get_playset_mods(conn, playset_info['id'])
    
    # Convert to playset format
    playset = convert_to_playset(playset_info, mods)
    
    # Determine output path
    if args.output:
        output_path = args.output
    else:
        safe_name = playset_info['name'].replace(' ', '_').replace('/', '_')
        output_path = PLAYSETS_DIR / f"{safe_name}_playset.json"
    
    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(playset, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    
    # Summary
    local_mods = [m for m in mods if is_local_mod(m)]
    steam_mods = [m for m in mods if not is_local_mod(m)]
    enabled_mods = [m for m in mods if m['enabled']]
    
    print(f"✓ Imported '{playset_info['name']}'")
    print(f"  Total mods: {len(mods)} ({len(enabled_mods)} enabled)")
    print(f"  Steam Workshop: {len(steam_mods)}")
    print(f"  Local mods: {len(local_mods)}")
    if local_mods:
        print(f"  Local mod positions: {[m['position'] for m in local_mods]}")
    print(f"  Output: {output_path}")


if __name__ == "__main__":
    main()
