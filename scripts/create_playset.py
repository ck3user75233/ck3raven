#!/usr/bin/env python3
"""
Create Playset from active_mod_paths.json

This creates a playset linking vanilla + all active mods,
enabling the ck3lens MCP tools to search the active playset.
"""

import sys
import json
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.db.schema import get_connection, DEFAULT_DB_PATH
from ck3raven.db.playsets import (
    create_playset, 
    add_mod_to_playset, 
    get_playset_by_name,
    list_playsets
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

ACTIVE_MOD_PATHS_FILE = Path(r"C:\Users\Nathan\Documents\AI Workspace\active_mod_paths.json")
PLAYSET_NAME = "Active Playset"


def main():
    conn = get_connection(DEFAULT_DB_PATH)
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    
    # Check for existing playset
    existing = get_playset_by_name(conn, PLAYSET_NAME)
    if existing:
        logger.info(f"Playset '{PLAYSET_NAME}' already exists (ID: {existing.playset_id})")
        logger.info("Delete it first if you want to recreate.")
        
        # Show current playsets
        playsets = list_playsets(conn)
        logger.info(f"\nExisting playsets:")
        for p in playsets:
            active = "ACTIVE" if p.is_active else "inactive"
            logger.info(f"  [{p.playset_id}] {p.name} ({active})")
        return 0
    
    # Get vanilla version
    row = conn.execute("SELECT vanilla_version_id, ck3_version FROM vanilla_versions LIMIT 1").fetchone()
    if not row:
        logger.error("No vanilla version found in database. Run build_database.py first.")
        return 1
    
    vanilla_version_id = row['vanilla_version_id']
    ck3_version = row['ck3_version']
    logger.info(f"Using vanilla: CK3 {ck3_version} (ID: {vanilla_version_id})")
    
    # Load active mods
    if not ACTIVE_MOD_PATHS_FILE.exists():
        logger.error(f"Active mod paths file not found: {ACTIVE_MOD_PATHS_FILE}")
        return 1
    
    mod_data = json.loads(ACTIVE_MOD_PATHS_FILE.read_text())
    active_mods = [m for m in mod_data.get("paths", []) if m.get("enabled", True)]
    logger.info(f"Found {len(active_mods)} active mods in playset config")
    
    # Create playset
    playset = create_playset(
        conn=conn,
        name=PLAYSET_NAME,
        vanilla_version_id=vanilla_version_id,
        description=f"Active playset with {len(active_mods)} mods",
        is_active=True
    )
    logger.info(f"Created playset: {playset.name} (ID: {playset.playset_id})")
    
    # Add mods to playset
    added = 0
    skipped = 0
    
    for mod in sorted(active_mods, key=lambda m: m.get('load_order', 999)):
        steam_id = mod.get('steam_id')
        mod_name = mod.get('name', 'Unknown')
        load_order = mod.get('load_order', 999)
        
        # Find content_version for this mod
        if steam_id:
            row = conn.execute("""
                SELECT cv.content_version_id 
                FROM content_versions cv
                JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE mp.workshop_id = ?
            """, (steam_id,)).fetchone()
        else:
            # Try by name for local mods
            row = conn.execute("""
                SELECT cv.content_version_id 
                FROM content_versions cv
                JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE mp.name = ?
            """, (mod_name,)).fetchone()
        
        if row:
            add_mod_to_playset(
                conn=conn,
                playset_id=playset.playset_id,
                content_version_id=row['content_version_id'],
                load_order_index=load_order
            )
            added += 1
            logger.info(f"  [{load_order:3}] Added: {mod_name}")
        else:
            skipped += 1
            logger.warning(f"  [{load_order:3}] SKIP: {mod_name} (not in database)")
    
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Playset created: {playset.name}")
    logger.info(f"  Vanilla: CK3 {ck3_version}")
    logger.info(f"  Mods added: {added}")
    logger.info(f"  Mods skipped: {skipped}")
    logger.info("=" * 60)
    
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
