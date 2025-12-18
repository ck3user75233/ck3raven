#!/usr/bin/env python3
"""
Build ck3raven Database

Indexes vanilla CK3 and active playset mods into the SQLite database.
Run this to initialize or update the database for CK3 Lens.

Usage:
    python build_database.py                    # Index vanilla + active playset
    python build_database.py --vanilla-only     # Just vanilla
    python build_database.py --mod-only         # Just mods
    python build_database.py --force            # Re-index even if unchanged
"""

import sys
import json
import logging
import argparse
from pathlib import Path

# Add src to path for ck3raven imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.db.schema import init_database, get_connection, DEFAULT_DB_PATH
from ck3raven.db.ingest import ingest_vanilla, ingest_mod

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# Paths
VANILLA_PATH = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\game")
ACTIVE_MOD_PATHS_FILE = Path(r"C:\Users\Nathan\Documents\AI Workspace\active_mod_paths.json")


def get_ck3_version() -> str:
    """Try to detect CK3 version from launcher-settings.json or fallback."""
    try:
        # launcher-settings.json is in the launcher subfolder, not parent
        launcher_settings = VANILLA_PATH.parent / "launcher" / "launcher-settings.json"
        if launcher_settings.exists():
            data = json.loads(launcher_settings.read_text())
            return data.get("version", "1.18.x")
    except:
        pass
    return "1.18.x"  # Fallback - update when new versions release


def load_active_mods() -> list:
    """Load active mod paths from JSON file."""
    if not ACTIVE_MOD_PATHS_FILE.exists():
        logger.warning(f"No active_mod_paths.json found at {ACTIVE_MOD_PATHS_FILE}")
        return []
    
    data = json.loads(ACTIVE_MOD_PATHS_FILE.read_text())
    return data.get("paths", [])


def main():
    parser = argparse.ArgumentParser(description="Build ck3raven database")
    parser.add_argument("--vanilla-only", action="store_true", help="Only index vanilla")
    parser.add_argument("--mod-only", action="store_true", help="Only index mods")
    parser.add_argument("--force", action="store_true", help="Re-index even if unchanged")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Database path")
    args = parser.parse_args()
    
    # Initialize database
    logger.info(f"Database: {args.db}")
    init_database(args.db)
    conn = get_connection(args.db)
    
    try:
        # Index vanilla
        if not args.mod_only:
            if VANILLA_PATH.exists():
                ck3_version = get_ck3_version()
                logger.info(f"Indexing vanilla CK3 {ck3_version}...")
                
                vanilla_ver, result = ingest_vanilla(
                    conn=conn,
                    game_path=VANILLA_PATH,
                    ck3_version=ck3_version,
                    force=args.force,
                )
                
                if result.stats.content_reused:
                    logger.info(f"  Vanilla already indexed (version {vanilla_ver.vanilla_version_id})")
                else:
                    logger.info(f"  Indexed {result.stats.files_new} files, {result.stats.bytes_stored:,} bytes")
            else:
                logger.error(f"Vanilla path not found: {VANILLA_PATH}")
        
        # Index mods
        if not args.vanilla_only:
            mods = load_active_mods()
            logger.info(f"Found {len(mods)} active mods")
            
            for i, mod_info in enumerate(mods):
                mod_path = Path(mod_info["path"])
                mod_name = mod_info.get("name", mod_path.name)
                workshop_id = mod_info.get("steam_id")
                
                if not mod_path.exists():
                    logger.warning(f"  [{i+1}/{len(mods)}] SKIP {mod_name} - path not found")
                    continue
                
                logger.info(f"  [{i+1}/{len(mods)}] {mod_name}...")
                
                try:
                    mod_pkg, result = ingest_mod(
                        conn=conn,
                        mod_path=mod_path,
                        name=mod_name,
                        workshop_id=workshop_id,
                        force=args.force,
                    )
                    
                    if result.stats.content_reused:
                        logger.info(f"      Already indexed")
                    else:
                        logger.info(f"      {result.stats.files_new} files, {result.stats.bytes_stored:,} bytes")
                        
                except Exception as e:
                    logger.error(f"      Error: {e}")
        
        # Summary
        row = conn.execute("SELECT COUNT(*) FROM content_versions").fetchone()
        versions_count = row[0]
        
        row = conn.execute("SELECT COUNT(*) FROM files WHERE deleted = 0").fetchone()
        files_count = row[0]
        
        row = conn.execute("SELECT SUM(size) FROM file_contents").fetchone()
        total_bytes = row[0] or 0
        
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"Database Summary:")
        logger.info(f"  Content versions: {versions_count}")
        logger.info(f"  Files indexed: {files_count:,}")
        logger.info(f"  Total content: {total_bytes:,} bytes ({total_bytes / (1024*1024):.1f} MB)")
        logger.info("=" * 60)
        
    finally:
        conn.close()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
