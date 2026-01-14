"""
Fix daemon.py to use canonical playset loading from playset_manifest.json.

Changes:
1. Remove --playset-file argument (parallel concept)
2. Add load_mods_from_active_playset() that reads from manifest
3. Update run_rebuild to use canonical loading
4. Update CLI to use --playset-name instead
"""
import pathlib
import re

daemon_path = pathlib.Path('builder/daemon.py')
content = daemon_path.read_text(encoding='utf-8')

# 1. Add PLAYSETS_DIR constant near the top (after DAEMON_DIR)
old_constants = '''DAEMON_DIR = Path.home() / ".ck3raven" / "daemon"'''
new_constants = '''DAEMON_DIR = Path.home() / ".ck3raven" / "daemon"
PLAYSETS_DIR = Path(__file__).parent.parent / "playsets"
PLAYSET_MANIFEST = PLAYSETS_DIR / "playset_manifest.json"'''

content = content.replace(old_constants, new_constants)

# 2. Replace discover_playset_mods with load_mods_from_active_playset
old_discover = '''def discover_playset_mods(playset_file: Path, logger: DaemonLogger) -> List[Dict]:
    """
    Load mod list from an active_mod_paths.json file (exported from launcher).
    
    Returns list of dicts in same format as discover_all_mods(): {name, path, workshop_id}
    Respects load_order from the file.
    """
    import json
    
    if not playset_file.exists():
        logger.error(f"Playset file not found: {playset_file}")
        return []
    
    try:
        data = json.loads(playset_file.read_text(encoding='utf-8'))
    except Exception as e:
        logger.error(f"Failed to parse playset file: {e}")
        return []
    
    playset_name = data.get('playset_name', 'Unknown')
    # CANONICAL: Use 'mods' key only. Legacy 'paths' format is BANNED.
    mod_entries = data.get('mods', [])
    if not mod_entries:
        raise ValueError(
            f"Playset {playset_file} missing required 'mods' key - "
            f"legacy 'paths' format is not supported"
        )
    mods = []
    for entry in mod_entries:
        if not entry.get('enabled', True):
            continue  # Skip disabled mods
        
        mod_path = Path(entry.get('path', ''))
        if not mod_path.exists():
            logger.warning(f"Mod path not found: {mod_path}")
            continue
        
        mods.append({
            "name": entry.get('name', mod_path.name),
            "path": mod_path,
            "workshop_id": entry.get('steam_id') or None,  # Empty string -> None
            "load_order": entry.get('load_order', 999)
        })
    
    # Sort by load order
    mods.sort(key=lambda m: m.get('load_order', 999))
    
    workshop_count = sum(1 for m in mods if m['workshop_id'])
    local_count = len(mods) - workshop_count
    logger.info(f"Loaded playset '{playset_name}' with {len(mods)} mods ({workshop_count} workshop, {local_count} local)")
    
    return mods'''

new_discover = '''def load_mods_from_active_playset(logger: DaemonLogger) -> List[Dict]:
    """
    Load mod list from the ACTIVE playset (canonical source).
    
    Reads from playsets/playset_manifest.json to get active playset name,
    then loads mods[] from playsets/{active}.json.
    
    Returns list of dicts: {name, path, workshop_id, load_order}
    """
    import json
    
    # Step 1: Read manifest to get active playset
    if not PLAYSET_MANIFEST.exists():
        logger.error(f"Playset manifest not found: {PLAYSET_MANIFEST}")
        logger.info("Run 'ck3_playset switch' to set an active playset")
        return []
    
    try:
        manifest = json.loads(PLAYSET_MANIFEST.read_text(encoding='utf-8'))
    except Exception as e:
        logger.error(f"Failed to parse manifest: {e}")
        return []
    
    active_filename = manifest.get('active')
    if not active_filename:
        logger.error("No active playset set in manifest")
        logger.info("Run 'ck3_playset switch' to set an active playset")
        return []
    
    # Step 2: Load the active playset file
    playset_path = PLAYSETS_DIR / active_filename
    if not playset_path.exists():
        logger.error(f"Active playset file not found: {playset_path}")
        return []
    
    try:
        data = json.loads(playset_path.read_text(encoding='utf-8'))
    except Exception as e:
        logger.error(f"Failed to parse playset: {e}")
        return []
    
    playset_name = data.get('playset_name', 'Unknown')
    
    # CANONICAL: Use 'mods' key only. Legacy 'paths' format is BANNED.
    mod_entries = data.get('mods', [])
    if not mod_entries:
        logger.warning(f"Playset '{playset_name}' has no mods")
        return []
    
    mods = []
    for entry in mod_entries:
        if not entry.get('enabled', True):
            continue  # Skip disabled mods
        
        mod_path = Path(entry.get('path', ''))
        if not mod_path.exists():
            logger.warning(f"Mod path not found: {mod_path}")
            continue
        
        mods.append({
            "name": entry.get('name', mod_path.name),
            "path": mod_path,
            "workshop_id": entry.get('steam_id') or None,
            "load_order": entry.get('load_order', 999)
        })
    
    # Sort by load order
    mods.sort(key=lambda m: m.get('load_order', 999))
    
    workshop_count = sum(1 for m in mods if m['workshop_id'])
    local_count = len(mods) - workshop_count
    logger.info(f"Active playset: '{playset_name}' with {len(mods)} mods ({workshop_count} workshop, {local_count} local)")
    
    return mods'''

content = content.replace(old_discover, new_discover)

# 3. Update ingest_all_mods to not need playset_file parameter
old_ingest_call = '''def ingest_all_mods(conn, logger: DaemonLogger, status: StatusWriter, playset_file: Path = None):
    """Ingest mods with progress tracking.
    
    If playset_file is provided, only ingest mods from that playset.
    Otherwise, discover and ingest all mods.
    """
    from ck3raven.db.ingest import ingest_mod
    
    if playset_file:
        mods = discover_playset_mods(playset_file, logger)
    else:
        mods = discover_all_mods(logger)'''

new_ingest_call = '''def ingest_all_mods(conn, logger: DaemonLogger, status: StatusWriter, use_active_playset: bool = True):
    """Ingest mods with progress tracking.
    
    If use_active_playset is True (default), ingest mods from active playset.
    Otherwise, discover and ingest ALL mods from workshop + local.
    """
    from ck3raven.db.ingest import ingest_mod
    
    if use_active_playset:
        mods = load_mods_from_active_playset(logger)
    else:
        mods = discover_all_mods(logger)'''

content = content.replace(old_ingest_call, new_ingest_call)

# 4. Update run_rebuild signature to remove playset_file
old_run_sig = '''def run_rebuild(db_path: Path, force: bool, logger: DaemonLogger, status: StatusWriter, symbols_only: bool = False, vanilla_path: str = None, skip_mods: bool = False, playset_file: Path = None):'''
new_run_sig = '''def run_rebuild(db_path: Path, force: bool, logger: DaemonLogger, status: StatusWriter, symbols_only: bool = False, vanilla_path: str = None, skip_mods: bool = False, use_active_playset: bool = True):'''

content = content.replace(old_run_sig, new_run_sig)

# 5. Update the mod ingest call inside run_rebuild
old_ingest_phase = '''            if not skip_mods:
                build_tracker.start_step("mod_ingest")
                if playset_file:
                    status.update(
                        phase="mod_ingest",
                        phase_number=2,
                        message="Ingesting playset mod files..."
                    )
                else:
                    status.update(
                        phase="mod_ingest",
                        phase_number=2,
                        message="Ingesting all mod files..."
                    )
                write_heartbeat()
                build_tracker.update_lock_heartbeat()

                mod_files = ingest_all_mods(conn, logger, status, playset_file=playset_file)'''

new_ingest_phase = '''            if not skip_mods:
                build_tracker.start_step("mod_ingest")
                if use_active_playset:
                    status.update(
                        phase="mod_ingest",
                        phase_number=2,
                        message="Ingesting active playset mods..."
                    )
                else:
                    status.update(
                        phase="mod_ingest",
                        phase_number=2,
                        message="Ingesting all discovered mods..."
                    )
                write_heartbeat()
                build_tracker.update_lock_heartbeat()

                mod_files = ingest_all_mods(conn, logger, status, use_active_playset=use_active_playset)'''

content = content.replace(old_ingest_phase, new_ingest_phase)

# 6. Update start_detached to remove playset_file
old_start_detached = '''def start_detached(db_path: Path, force: bool, symbols_only: bool = False, playset_file: Path = None):'''
new_start_detached = '''def start_detached(db_path: Path, force: bool, symbols_only: bool = False, ingest_all: bool = False):'''

content = content.replace(old_start_detached, new_start_detached)

# 7. Update start_detached body
old_start_body = '''    if playset_file:
        args.extend(["--playset-file", str(playset_file)])'''
new_start_body = '''    if ingest_all:
        args.append("--ingest-all")'''

content = content.replace(old_start_body, new_start_body)

# 8. Update argparse - remove --playset-file, add --ingest-all
old_argparse = '''    parser.add_argument("--playset-file", type=Path,
                        help="Path to active_mod_paths.json to build only active playset mods")'''
new_argparse = '''    parser.add_argument("--ingest-all", action="store_true",
                        help="Ingest ALL mods (workshop + local) instead of just active playset")'''

content = content.replace(old_argparse, new_argparse)

# 9. Update the main() start command handling
old_main_start = '''        start_detached(args.db, args.force, args.symbols_only, playset_file=args.playset_file)'''
new_main_start = '''        start_detached(args.db, args.force, args.symbols_only, ingest_all=args.ingest_all)'''

content = content.replace(old_main_start, new_main_start)

# 10. Update test mode call
old_test_call = '''            run_rebuild(
                args.db, args.force, logger, status, args.symbols_only,
                vanilla_path=args.vanilla_path,
                skip_mods=args.skip_mods,
                playset_file=args.playset_file
            )'''
new_test_call = '''            run_rebuild(
                args.db, args.force, logger, status, args.symbols_only,
                vanilla_path=args.vanilla_path,
                skip_mods=args.skip_mods,
                use_active_playset=not args.ingest_all
            )'''

content = content.replace(old_test_call, new_test_call)

# 11. Update _run_daemon call
old_daemon_call = '''            run_rebuild(args.db, args.force, logger, status, args.symbols_only, playset_file=args.playset_file)'''
new_daemon_call = '''            run_rebuild(args.db, args.force, logger, status, args.symbols_only, use_active_playset=not args.ingest_all)'''

content = content.replace(old_daemon_call, new_daemon_call)

# 12. Update test mode print
old_test_print = '''            print(f"  Playset file: {args.playset_file or 'all mods'}")'''
new_test_print = '''            print(f"  Ingest all mods: {args.ingest_all}")'''

content = content.replace(old_test_print, new_test_print)

daemon_path.write_text(content, encoding='utf-8')
print("Fixed daemon.py to use canonical playset loading")
print("- Removed --playset-file argument")
print("- Added load_mods_from_active_playset() function")
print("- Now reads from playsets/playset_manifest.json")
