"""
CK3 Lens MCP Server

An MCP server providing CK3 modding tools:
- Symbol search (from ck3raven SQLite DB)
- Conflict detection
- Mod file operations (writes sandboxed to local_mods_folder)
- Git operations
- Validation

Architecture:
- ALL reads come from ck3raven's SQLite database (symbols, files, AST)
- Writes only allowed to mods under local_mods_folder
"""
from __future__ import annotations
import sys
import os
import json
import importlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Literal

from ck3lens.policy.capability_matrix import Operation, validate_operations

# =============================================================================
# STARTUP TRIPWIRE - Verify running from correct Python environment
# =============================================================================
def _verify_python_environment() -> None:
    """
    Verify the MCP server is running from the repo .venv on Windows.
    
    If running from Windows Store Python stub, exit immediately with diagnostic info.
    This prevents "ghost" processes that waste debugging time.
    """
    if sys.platform != "win32":
        return  # Only enforce on Windows where the stub exists
    
    exe = Path(sys.executable).resolve()
    repo_root = Path(__file__).parent.parent.parent
    expected_venv = (repo_root / ".venv" / "Scripts" / "python.exe").resolve()
    
    # Check if running from WindowsApps (the stub location)
    is_windows_store = "WindowsApps" in str(exe) or "Microsoft\\WindowsApps" in str(exe)
    is_correct_venv = exe == expected_venv or str(exe).lower() == str(expected_venv).lower()
    
    if is_windows_store or not is_correct_venv:
        # Print diagnostic info and exit
        import site
        print("=" * 70, file=sys.stderr)
        print("FATAL: MCP Server started with wrong Python interpreter!", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print(f"  sys.executable:    {sys.executable}", file=sys.stderr)
        print(f"  Expected venv:     {expected_venv}", file=sys.stderr)
        print(f"  sys.prefix:        {sys.prefix}", file=sys.stderr)
        print(f"  VIRTUAL_ENV:       {os.environ.get('VIRTUAL_ENV', '<not set>')}", file=sys.stderr)
        try:
            print(f"  site-packages:     {site.getsitepackages()}", file=sys.stderr)
        except Exception:
            print(f"  site-packages:     <unavailable>", file=sys.stderr)
        print("", file=sys.stderr)
        print("This is likely caused by a bare 'python' fallback in the launcher.", file=sys.stderr)
        print("Fix: Ensure VS Code extension uses absolute path to .venv Python.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        sys.exit(1)

# Run tripwire at module load time
_verify_python_environment()

from mcp.server.fastmcp import FastMCP

# Add ck3raven to path
CK3RAVEN_ROOT = Path(__file__).parent.parent.parent / "src"
if CK3RAVEN_ROOT.exists():
    sys.path.insert(0, str(CK3RAVEN_ROOT))

from ck3lens.workspace import Session, LocalMod
from ck3lens.db_queries import DBQueries
from ck3lens.db_api import db as db_api  # Database API Layer - THE interface for DB access
from ck3lens import git_ops
from ck3lens.validate import parse_content, validate_artifact_bundle
from ck3lens.contracts import ArtifactBundle
from ck3lens.trace import ToolTrace

# =============================================================================
# Policy Health Check - Validate imports at module load time
# =============================================================================
_policy_status = {"healthy": False, "error": None, "validated_at": None}

def _check_policy_health() -> dict:
    """
    Validate that policy module is properly importable.
    
    Returns dict with status info.
    """
    import time
    from ck3lens import policy
    
    try:
        # Reload at health check time only (startup) to verify imports work.
        # The actual validate_policy calls must NOT reload - they must be pure.
        importlib.reload(policy)
        
        # Verify required functions exist
        required = ['validate_for_mode', 'validate_policy', 'load_policy']
        missing = [f for f in required if not hasattr(policy, f)]
        
        if missing:
            _policy_status["healthy"] = False
            _policy_status["error"] = f"Missing exports: {missing}"
        else:
            _policy_status["healthy"] = True
            _policy_status["error"] = None
            
        _policy_status["validated_at"] = time.time()
        
    except Exception as e:
        _policy_status["healthy"] = False
        _policy_status["error"] = str(e)
        _policy_status["validated_at"] = time.time()
    
    return _policy_status

# Run health check at startup
_check_policy_health()

# =============================================================================

# Instance ID support for multi-window isolation
_instance_id = os.environ.get("CK3LENS_INSTANCE_ID", "default")
_server_name = f"ck3lens-{_instance_id}" if _instance_id != "default" else "ck3lens"
mcp = FastMCP(_server_name)

# Session state
_session: Optional[Session] = None
_db: Optional[DBQueries] = None
_trace: Optional[ToolTrace] = None
_session_cv_ids_resolved: bool = False

# World adapter cache (for session persistence)
_cached_world_adapter = None
_cached_world_mode: Optional[str] = None


def _get_session() -> Session:
    global _session, _session_cv_ids_resolved, _db
    if _session is None:
        from ck3lens.workspace import load_config
        _session = load_config()
    
    # Ensure CVIDs are resolved if we have a DB connection
    # This handles cases where _get_session() is called after _get_db()
    # but CVIDs weren't resolved yet (e.g., after server restart)
    if not _session_cv_ids_resolved and _db is not None:
        stats = _session.resolve_cvids(_db)
        _session_cv_ids_resolved = True
        if stats.get("mods_missing"):
            import logging
            logging.getLogger(__name__).warning(
                f"Mods not indexed: {stats['mods_missing']}"
            )
    
    return _session


def _get_db() -> DBQueries:
    """
    Get database connection via db_api layer.
    
    NOTE: This function now delegates to db_api. If db_api.is_available()
    returns False, this will raise RuntimeError. Tools should check
    db_api.is_available() before calling operations that require DB.
    
    ARCHITECTURAL NOTE (January 2026):
    The db_api module is THE interface for database access. This function
    remains for backward compatibility but should not be used for new code.
    Use db_api methods directly (db_api.unified_search(), etc.)
    """
    global _db, _session_cv_ids_resolved
    
    # Check if database access is disabled
    if not db_api.is_available():
        raise RuntimeError("Database is disabled for maintenance. Use ck3_db(command='enable') to reconnect.")
    
    if _db is None:
        session = _get_session()
        if session.db_path is None:
            raise RuntimeError("No database path configured. Check playset configuration.")
        
        # Configure db_api with path (if not already configured)
        db_api.configure(session.db_path, session)
        
        # Get connection via db_api
        _db = db_api._get_db()
        
        # Resolve cvids on first DB connection
        if not _session_cv_ids_resolved:
            stats = session.resolve_cvids(_db)
            _session_cv_ids_resolved = True
            # Log resolution stats for debugging
            if stats.get("mods_missing"):
                import logging
                logging.getLogger(__name__).warning(
                    f"Mods not indexed: {stats['mods_missing']}"
                )
    return _db


# BANNED: _get_lens, _get_cvids, _derive_search_cvids, db_visibility (December 2025 purge)
# Derive CVIDs inline from session.mods[] - THE canonical way


# ============================================================================
# DELETED December 2025: _cached_playset_scope and _get_playset_scope()
# 
# These were illegal enforcement oracles outside enforcement.py.
# Use WorldAdapter.resolve() for visibility, enforcement.py for decisions.
# ============================================================================


def _get_world():
    """
    Get the WorldAdapter for the current agent mode.
    
    The WorldAdapter provides unified path resolution and visibility control:
    - In ck3lens mode: paths are resolved within the active playset
    - In ck3raven-dev mode: paths are resolved with ck3raven source priority
    
    All MCP tools should use this to resolve paths before policy checks.
    
    Returns:
        WorldAdapter appropriate for the current mode
        
    Raises:
        RuntimeError: If mode is not initialized
    """
    global _cached_world_adapter, _cached_world_mode
    
    from ck3lens.world_router import get_world
    from ck3lens.agent_mode import get_agent_mode
    
    mode = get_agent_mode()
    
    # Check cache
    if _cached_world_adapter is not None and _cached_world_mode == mode:
        return _cached_world_adapter
    
    # Get session for mod paths - DB is NOT needed for path resolution
    # DB is only needed for DB operations (search, get_file from DB, etc.)
    session = _get_session()
    
    # Build adapter via router - mods[] is THE source, no lens
    # Pass db=None - WorldAdapter doesn't need DB for path resolution
    # NOTE: Do NOT catch exceptions here. If mode is not initialized,
    # the error should propagate with a clear message about calling
    # ck3_get_mode_instructions() first.
    adapter = get_world(
        db=None,  # DB not needed for path resolution - get it when needed
        local_mods_folder=session.local_mods_folder,
        mods=session.mods
    )
    _cached_world_adapter = adapter
    _cached_world_mode = mode
    return adapter


def _reset_world_cache():
    """Reset the cached world adapter (for mode changes)."""
    global _cached_world_adapter, _cached_world_mode
    _cached_world_adapter = None
    _cached_world_mode = None


# Cached session scope data
_session_scope: Optional[dict] = None

# Playset folder - JSON files here define available playsets
# Located at ck3raven/playsets/ (repository root, not tools/)
PLAYSETS_DIR = Path(__file__).parent.parent.parent / "playsets"

# Manifest file - points to which playset is currently active
# Lives in the playsets folder alongside the playset files
PLAYSET_MANIFEST_FILE = PLAYSETS_DIR / "playset_manifest.json"




def _list_available_playsets() -> list[dict]:
    """
    List all available playsets from the playsets folder.
    
    Returns list of {name, file_path, description, mod_count}
    """
    if not PLAYSETS_DIR.exists():
        return []
    
    playsets = []
    for f in PLAYSETS_DIR.glob("*.json"):
        if f.name.endswith(".schema.json"):
            continue  # Skip schema files
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
            playsets.append({
                "name": data.get("playset_name", f.stem),
                "file_path": str(f),
                "description": data.get("description", ""),
                "mod_count": len(data.get("mods", [])),
            })
        except Exception:
            pass
    return playsets


def _load_playset_from_json(playset_file: Path) -> Optional[dict]:
    """
    Load playset data from a ck3raven playset JSON file.
    
    This is the NEW primary source for playset data.
    Reads the full playset format with agent_briefing support.
    
    IMPORTANT: Auto-migrates paths if they reference a different user profile.
    This handles the case where playset files are synced via git between machines.
    
    Returns dict with session scope data or None if file missing.
    """
    if not playset_file.exists():
        return None
    
    try:
        data = json.loads(playset_file.read_text(encoding='utf-8-sig'))
        
        # Auto-migrate paths if they reference a different user profile
        try:
            from .ck3lens.path_migration import migrate_playset_paths
            migrated_data, was_modified, migration_msg = migrate_playset_paths(data)
            if was_modified:
                print(f"[PATH MIGRATION] {migration_msg}")
                data = migrated_data
                # Optionally save the migrated playset
                # (disabled for now - just migrate in memory)
        except ImportError:
            pass  # path_migration module not available
        
        active_mod_ids = set()
        active_roots = set()
        
        # Read mods array (new format)
        for mod in data.get("mods", []):
            if not mod.get("enabled", True):
                continue
            steam_id = mod.get("steam_id")
            if steam_id:
                active_mod_ids.add(str(steam_id))
            path = mod.get("path")
            if path:
                # Expand ~ in paths
                active_roots.add(str(Path(path).expanduser()))
        
        # Get vanilla info
        vanilla_config = data.get("vanilla", {})
        vanilla_root = vanilla_config.get("path", "C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game")
        
        # Get local_mods_folder path (editability is DERIVED from path containment)
        local_mods_folder_raw = data.get("local_mods_folder", "")
        local_mods_folder = Path(local_mods_folder_raw).expanduser() if local_mods_folder_raw else None
        
        # NOTE: No editable_mods list - enforcement.py determines writability at execution time
        # based on path containment under local_mods_folder. No pre-computed permission lists.
        
        # Get agent briefing
        agent_briefing = data.get("agent_briefing", {})
        
        return {
            "playset_id": None,  # No DB ID for JSON-based
            "playset_name": data.get("playset_name", "JSON Playset"),
            "active_mod_ids": active_mod_ids,
            "active_roots": active_roots,
            "vanilla_version_id": None,
            "vanilla_root": str(Path(vanilla_root).expanduser()),
            "source": "json",
            "file_path": str(playset_file),
            "local_mods_folder": str(local_mods_folder) if local_mods_folder else None,
            "agent_briefing": agent_briefing,
            "sub_agent_config": data.get("sub_agent_config", {}),
            "mod_list": data.get("mods", []),  # Full mod list for reference
        }
    except Exception as e:
        print(f"Warning: Failed to load playset from {playset_file}: {e}")
        return None


# REMOVED: _load_legacy_playset - Legacy playset format BANNED (December 2025)
# All playsets must use the canonical mods[] format in playsets/*.json


def _get_session_scope(force_refresh: bool = False) -> dict:
    """
    Get all session scope data from a single source of truth.
    
    Source:
    1. Manifest file (playsets/playset_manifest.json) -> points to active playset
    2. Empty scope (no playset)
    
    NOTE: Database is NO LONGER used for playset storage.
    
    Returns dict with:
        playset_id: None (JSON-based, no DB ID)
        playset_name: Human-readable name
        active_mod_ids: Set of workshop IDs for mods in playset
        active_roots: Set of filesystem root paths for mods
        vanilla_version_id: None (unused)
        vanilla_root: Path to vanilla game files
        source: "json" or "none"
        agent_briefing: Dict with agent instructions (if available)
    """
    global _session_scope
    
    if _session_scope is not None and not force_refresh:
        return _session_scope
    
    # Try manifest file first - this points to the active playset
    if PLAYSET_MANIFEST_FILE.exists():
        try:
            manifest = json.loads(PLAYSET_MANIFEST_FILE.read_text(encoding='utf-8-sig'))
            active_filename = manifest.get("active", "")
            if active_filename:
                active_file = PLAYSETS_DIR / active_filename
                if active_file.exists():
                    scope = _load_playset_from_json(active_file)
                    if scope:
                        _session_scope = scope
                        return _session_scope
                else:
                    print(f"Warning: Manifest points to {active_filename} but file not found")
        except Exception as e:
            print(f"Warning: Failed to read playset manifest: {e}")
    
    # No playset available - legacy format support REMOVED
    _session_scope = {
        "playset_id": None,
        "playset_name": None,
        "active_mod_ids": set(),
        "active_roots": set(),
        "vanilla_version_id": None,
        "vanilla_root": None,
        "source": "none",
    }
    return _session_scope


def _get_trace_path() -> Path:
    """
    Get the trace log path based on agent mode.
    
    - ck3raven-dev mode: {repo}/.wip/traces/ck3lens_trace.jsonl
    - ck3lens mode: ~/.ck3raven/traces/ck3lens_trace.jsonl
    """
    from ck3lens.agent_mode import get_agent_mode
    
    mode = get_agent_mode()
    
    if mode == "ck3raven-dev":
        # Trace goes in repo's .wip folder
        ck3raven_root = Path(__file__).parent.parent
        trace_dir = ck3raven_root / ".wip" / "traces"
    else:
        # Trace goes in ~/.ck3raven/traces/
        trace_dir = Path.home() / ".ck3raven" / "traces"
    
    trace_dir.mkdir(parents=True, exist_ok=True)
    return trace_dir / "ck3lens_trace.jsonl"


def _get_trace() -> ToolTrace:
    global _trace
    if _trace is None:
        _trace = ToolTrace(_get_trace_path())
    return _trace


def _detect_wip_script(command: str, working_dir: str) -> dict | None:
    """
    Detect if a command is running a Python script in the .wip/ directory.
    
    Returns dict with script_path, script_hash, and (optional) wip_intent if detected,
    otherwise None.
    
    WIP scripts are detected when:
    - Command starts with 'python' and includes a .py file in .wip/
    - Or working_dir is .wip/ and command runs a .py file
    """
    import hashlib
    import re
    
    cmd_lower = command.lower()
    
    # Pattern 1: python .wip/script.py or python -c ... (not WIP)
    # Pattern 2: python script.py when working_dir is .wip/
    wip_patterns = [
        r"python[3]?\s+(?:[\w\-\.]+\s+)*[\"']?([^\s\"']*\.wip[/\\][^\s\"']+\.py)[\"']?",  # python .wip/script.py
        r"python[3]?\s+(?:[\w\-\.]+\s+)*[\"']?(\\.wip[/\\][^\s\"']+\.py)[\"']?",  # python \.wip\script.py
    ]
    
    script_path = None
    
    # Check explicit .wip/ in command
    for pattern in wip_patterns:
        match = re.search(pattern, command, re.IGNORECASE)
        if match:
            script_path = match.group(1)
            break
    
    # Check if working_dir is in .wip/ and command runs a .py file
    if script_path is None:
        working_dir_normalized = working_dir.replace("\\", "/").lower()
        if ".wip/" in working_dir_normalized or working_dir_normalized.endswith(".wip"):
            # Look for python script.py pattern
            py_match = re.search(r"python[3]?\s+(?:[\w\-\.]+\s+)*[\"']?([^\s\"']+\.py)[\"']?", command, re.IGNORECASE)
            if py_match:
                # Combine working_dir with script name
                script_name = py_match.group(1)
                script_path = f"{working_dir}/{script_name}".replace("\\", "/")
    
    if script_path is None:
        return None
    
    # Compute script hash if the file exists
    script_hash = None
    try:
        from pathlib import Path
        full_path = Path(script_path)
        if not full_path.is_absolute():
            full_path = Path(working_dir) / script_path
        if full_path.exists():
            content = full_path.read_text(encoding="utf-8")
            script_hash = hashlib.sha256(content.encode()).hexdigest()
    except Exception:
        # File may not exist yet or other issue - hash will be None
        script_hash = "UNKNOWN"
    
    return {
        "script_path": script_path,
        "script_hash": script_hash,
        "wip_intent": None,  # Caller must provide via token or contract
    }


# ============================================================================
# Session Management
# ============================================================================


@mcp.tool()
def ck3_get_instance_info() -> dict:
    """
    Get information about this MCP server instance.
    
    Use this to verify which server instance you're connected to.
    Each VS Code window should have a unique instance ID.
    
    Returns:
        Instance ID, server name, and process info
    """
    import os
    return {
        "instance_id": _instance_id,
        "server_name": _server_name,
        "pid": os.getpid(),
        "is_isolated": _instance_id != "default",
    }


@mcp.tool()
def ck3_ping() -> dict:
    """
    Simple health check - always returns success.
    
    Use this to verify MCP server connectivity is working.
    Unlike other tools, this has no dependencies and will
    always succeed if the server is reachable.
    
    Returns:
        {"status": "ok", "instance_id": str, "timestamp": str}
    """
    from datetime import datetime
    return {
        "status": "ok",
        "instance_id": _instance_id,
        "timestamp": datetime.now().isoformat(),
    }

def _init_session_internal(
    db_path: Optional[str] = None,
) -> dict:
    """
    Internal session initialization - called by ck3_get_mode_instructions.

    CANONICAL MODEL:
    - Session is loaded from active playset via load_config()
    - mods[] contains all mods from playset
    - local_mods_folder is the folder boundary for editable mods
    - "mods under local_mods_folder" are derived at runtime, not stored

    Returns session info dict.
    """
    from ck3lens.workspace import load_config

    global _session, _db, _trace, _playset_id, _session_scope, _session_cv_ids_resolved

    # Reset playset and scope cache
    _playset_id = None
    _session_scope = None
    _session_cv_ids_resolved = False  # Reset so CVIDs are resolved on reconnect

    # Use load_config to get session from active playset
    _session = load_config()

    # Override DB path if provided
    if db_path:
        _session.db_path = Path(db_path)

    if _session.db_path is None:
        raise RuntimeError("No database path configured. Check playset configuration.")
    
    # Use db_api.configure() so enable/disable cycle works correctly
    db_api.configure(_session.db_path, _session)
    _db = db_api._get_db()

    # Initialize trace with proper path based on mode
    _trace = ToolTrace(_get_trace_path())

    # CANONICAL: Get playset info from session - no database lookup needed
    # Vanilla is mods[0], playset name comes from session config
    playset_name = getattr(_session, "playset_name", "Active Playset")
    mod_count = len(_session.mods) if hasattr(_session, "mods") else 0

    # Check database health
    db_status = _check_db_health(_db.conn)

    # Return minimal session info - WorldAdapter handles visibility,
    result = {
        "db_path": str(_db.db_path) if _db.db_path else None,
        "playset_name": playset_name,
        "mod_count": mod_count,
        "db_status": db_status,
        "local_mods_folder": str(_session.local_mods_folder) if _session.local_mods_folder else None,
    }

    # Add warning if database needs attention
    if not db_status.get("is_complete"):
        result["warning"] = f"Database incomplete: {db_status.get('rebuild_reason', 'unknown')}. Run: python builder/daemon.py start"

    return result


def _check_db_health(conn) -> dict:
    """Check database build status and completeness.
    
    Works with qbuilder tables (build_queue, build_runs).
    Falls back gracefully if tables don't exist.
    """
    try:
        # Get counts first (these tables should always exist)
        files = conn.execute("SELECT COUNT(*) FROM files WHERE deleted = 0").fetchone()[0]
        symbols = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        refs = conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
        
        # Check which tables exist
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        
        # Check qbuilder queue status (preferred)
        queue_pending = 0
        queue_processing = 0
        queue_completed = 0
        queue_error = 0
        
        if 'build_queue' in tables:
            for row in conn.execute("""
                SELECT status, COUNT(*) as cnt FROM build_queue GROUP BY status
            """):
                if row[0] == 'pending':
                    queue_pending = row[1]
                elif row[0] == 'processing':
                    queue_processing = row[1]
                elif row[0] == 'completed':
                    queue_completed = row[1]
                elif row[0] == 'error':
                    queue_error = row[1]
        
        # Check build_runs table (qbuilder's run tracking)
        last_state = None
        last_updated = None
        
        if 'build_runs' in tables:
            run_row = conn.execute("""
                SELECT status, completed_at FROM build_runs 
                ORDER BY started_at DESC LIMIT 1
            """).fetchone()
            if run_row:
                last_state = run_row[0]
                last_updated = run_row[1]
        
        # Determine completion status
        # Complete if: no pending/processing items AND we have symbols/refs
        has_pending_work = queue_pending > 0 or queue_processing > 0
        
        if has_pending_work:
            is_complete = False
            phase = "building"
            needs_rebuild = False  # Work in progress, not a "rebuild" situation
            rebuild_reason = f"{queue_pending} pending, {queue_processing} processing"
        elif symbols == 0:
            is_complete = False
            phase = "no_symbols"
            needs_rebuild = True
            rebuild_reason = "No symbols extracted - run: python -m qbuilder.cli build"
        elif refs == 0:
            is_complete = False
            phase = "no_refs"
            needs_rebuild = True
            rebuild_reason = "No references extracted - run: python -m qbuilder.cli build"
        elif queue_error > 0:
            is_complete = False
            phase = "has_errors"
            needs_rebuild = False
            rebuild_reason = f"{queue_error} files had errors during build"
        else:
            is_complete = True
            phase = "complete"
            needs_rebuild = False
            rebuild_reason = None
        
        return {
            "is_complete": is_complete,
            "phase": phase,
            "last_updated": last_updated,
            "files_indexed": files,
            "symbols_extracted": symbols,
            "refs_extracted": refs,
            "needs_rebuild": needs_rebuild,
            "rebuild_reason": rebuild_reason,
            "queue": {
                "pending": queue_pending,
                "processing": queue_processing,
                "completed": queue_completed,
                "error": queue_error,
            },
        }
    except Exception as e:
        return {
            "is_complete": False,
            "error": str(e),
            "needs_rebuild": True,
            "rebuild_reason": f"Error checking database: {e}"
        }


# NOTE: ck3_get_db_status() DELETED - January 2026
# Functionality consolidated into ck3_qbuilder(command="status")
# This avoids redundant tools and eliminates qbuilder import dependency


@mcp.tool()
def ck3_close_db() -> dict:
    """
    Close database connection to release file lock.
    
    Use this before operations that require exclusive file access:
    - Deleting the database file
    - Moving/renaming the database
    - Running external tools that need exclusive access
    
    The connection will be automatically re-established on the next
    database operation.
    
    Returns:
        {"success": bool, "message": str}
    """
    global _db, _playset_id, _session_scope
    
    trace = _get_trace()
    
    try:
        # Use db_api to disable (which handles WAL mode, close, and blocks reconnect)
        result = db_api.disable()
        
        # Also clear module-level cache
        _db = None
        
        # Clear cached state that depends on DB
        _playset_id = None
        _session_scope = None
        
        # Clear thread-local connections from schema module
        try:
            from ck3raven.db.schema import close_all_connections
            close_all_connections()
        except Exception:
            pass
        
        # Force garbage collection to release any lingering file handles
        import gc
        gc.collect()
        
        trace.log("ck3lens.close_db", {}, {"success": True})
        
        return {
            "success": True,
            "message": "Database connection closed and DISABLED. Use ck3_db(command='enable') to reconnect. File lock released."
        }
    except Exception as e:
        trace.log("ck3lens.close_db", {}, {"success": False, "error": str(e)})
        return {
            "success": False,
            "message": f"Failed to close connection: {e}"
        }


@mcp.tool()
def ck3_db(
    command: Literal["status", "disable", "enable"] = "status",
) -> dict:
    """
    Manage database connection for maintenance operations.
    
    Commands:
    
    command=status   ? Check if database is enabled/connected
    command=disable  ? Close connection and block reconnection (for file operations)
    command=enable   ? Re-enable database access
    
    Use disable before deleting database files to ensure file locks are released.
    Use enable to restore normal operation.
    
    Args:
        command: Operation to perform
        
    Returns:
        Dict with operation result
        
    Examples:
        ck3_db(command="status")   # Check current state
        ck3_db(command="disable")  # Close and block for file deletion
        ck3_db(command="enable")   # Restore normal operation
    """
    global _db
    
    trace = _get_trace()
    
    if command == "status":
        result = db_api.status()
        trace.log("ck3lens.db.status", {}, result)
        return result
        
    elif command == "disable":
        # Use db_api to disable (handles WAL mode, close, blocks reconnect)
        result = db_api.disable()
        
        # Also clear module-level cache
        _db = None
        
        # Clear thread-local connections from schema module
        try:
            from ck3raven.db.schema import close_all_connections
            close_all_connections()
        except Exception:
            pass
        
        # Force garbage collection to release file handles
        import gc
        gc.collect()
        
        trace.log("ck3lens.db.disable", {}, result)
        return result
        
    elif command == "enable":
        result = db_api.enable()
        trace.log("ck3lens.db.enable", {}, result)
        return result
    
    else:
        return {"error": f"Unknown command: {command}"}


# NOTE: ck3_get_playset_build_status() DELETED - January 2026
# Functionality consolidated into ck3_qbuilder(command="status")
# This avoids redundant tools and eliminates qbuilder import dependency


@mcp.tool()
def ck3_db_delete(
    target: Literal["asts", "symbols", "refs", "files", "content_versions", "lookups", "playsets", "build_tracking"],
    scope: Literal["all", "mods_only", "by_ids", "by_content_version"],
    ids: Optional[list[int | str]] = None,
    content_version_ids: Optional[list[int]] = None,
    confirm: bool = False
) -> dict:
    """
    Flexible database cleanup tool for surgical deletion of indexed data.
    
    Mode-aware behavior:
    - ck3lens mode: Can delete playset/mod data for re-ingestion
    - ck3raven-dev mode: Full access for schema changes and debugging
    
    Use this to clear cached/derived data when:
    - Mods have been updated from Steam and need re-ingestion
    - Schema changes require re-extraction
    - Debugging requires fresh data
    
    Args:
        target: What type of data to delete:
            - "asts": Parsed AST cache (can be regenerated from files)
            - "symbols": Extracted symbol definitions
            - "refs": Extracted symbol references  
            - "files": File entries (deletes ASTs/symbols/refs too)
            - "content_versions": Mod/vanilla entries (cascades to files)
            - "lookups": All lookup tables (trait_lookups, event_lookups, etc.)
            - "playsets": Playset configuration
            - "build_tracking": builder_runs, builder_steps, build_lock
            
        scope: How to filter what gets deleted:
            - "all": Delete ALL entries of this target type
            - "mods_only": Delete mod data, preserve vanilla (content_version_id > 1)
            - "by_ids": Delete specific IDs (requires `ids` parameter)
            - "by_content_version": Delete by content_version_id (requires `content_version_ids`)
            
        ids: List of IDs to delete when scope="by_ids"
            - Integers: [1, 5, 10]
            - Ranges as strings: ["1-100", "500-600"]
            - Mixed: [1, 5, "10-20", 100]
            
        content_version_ids: List of content_version_ids when scope="by_content_version"
        
        confirm: Must be True to actually delete. If False, returns preview of what would be deleted.
        
    Returns:
        {
            "success": bool,
            "target": str,
            "scope": str,
            "rows_deleted": int,  # or "rows_would_delete" if confirm=False
            "details": {...}
        }
    
    Examples:
        # Preview deleting all mod ASTs
        ck3_db_delete(target="asts", scope="mods_only", confirm=False)
        
        # Actually delete all mod data
        ck3_db_delete(target="content_versions", scope="mods_only", confirm=True)
        
        # Delete specific content_versions by ID
        ck3_db_delete(target="content_versions", scope="by_ids", ids=[2, 3, 4], confirm=True)
        
        # Delete ASTs for content_versions 5-10
        ck3_db_delete(target="asts", scope="by_content_version", content_version_ids=[5,6,7,8,9,10], confirm=True)
    """
    from ck3lens.agent_mode import get_agent_mode
    from ck3lens.policy.enforcement import (
        OperationType, Decision, EnforcementRequest, enforce_and_log
    )
    from ck3lens.policy.contract_v1 import get_active_contract
    
    db = _get_db()
    trace = _get_trace()
    
    # ==========================================================================
    # CENTRALIZED ENFORCEMENT GATE (Phase 2)
    # DB delete operations go through enforce_and_log FIRST
    # ==========================================================================
    
    mode = get_agent_mode()
    
    if mode:
        contract = get_active_contract()
        
        # Build enforcement request
        request = EnforcementRequest(
            operation=OperationType.DB_DELETE,
            mode=mode,
            tool_name="ck3_db_delete",
            target_path=f"db:{target}",  # Use db: prefix for DB operations
            contract_id=contract.contract_id if contract else None,
        )
        
        # Enforce policy
        result = enforce_and_log(request, trace)
        
        # Handle enforcement decision
        if result.decision == Decision.DENY:
            return {
                "success": False,
                "target": target,
                "scope": scope,
                "error": result.reason,
                "policy_decision": "DENY",
            }
        
        if result.decision == Decision.REQUIRE_CONTRACT:
            return {
                "success": False,
                "target": target,
                "scope": scope,
                "error": result.reason,
                "policy_decision": "REQUIRE_CONTRACT",
                "guidance": "Use ck3_contract(command='open', ...) to open a work contract",
            }
        
        if result.decision == Decision.REQUIRE_TOKEN:
            return {
                "success": False,
                "target": target,
                "scope": scope,
                "error": result.reason,
                "policy_decision": "REQUIRE_TOKEN",
                "required_token_type": result.required_token_type,
                "hint": f"Use ck3_token to request a {result.required_token_type} token",
            }
        
        # Decision is ALLOW - continue to implementation
    
    # ==========================================================================
    # IMPLEMENTATION
    # ==========================================================================
    
    cur = db.conn.cursor()
    
    result = {
        "success": False,
        "target": target,
        "scope": scope,
        "confirm": confirm,
    }
    
    # Parse ID ranges into flat list
    def expand_ids(id_list: list) -> list[int]:
        expanded = []
        for item in id_list:
            if isinstance(item, int):
                expanded.append(item)
            elif isinstance(item, str) and "-" in item:
                start, end = item.split("-", 1)
                expanded.extend(range(int(start), int(end) + 1))
            else:
                expanded.append(int(item))
        return expanded
    
    # Build WHERE clause based on scope
    def get_where_clause(table: str, id_column: str) -> tuple[str, list]:
        if scope == "all":
            return "", []
        elif scope == "mods_only":
            if table == "content_versions":
                return "WHERE kind = 'mod'", []
            elif table in ("files", "asts"):
                if table == "files":
                    return "WHERE content_version_id > 1", []
                else:
                    # ASTs: filter by files with content_version_id > 1
                    return "WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id > 1)", []
            elif table in ("symbols", "refs"):
                # CONTENT-KEYED: symbols/refs join through asts.file_id
                return f"WHERE ast_id IN (SELECT ast_id FROM asts WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id > 1))", []
            else:
                return "", []  # For other tables, mods_only = all
        elif scope == "by_ids":
            if not ids:
                raise ValueError("scope='by_ids' requires 'ids' parameter")
            expanded = expand_ids(ids)
            placeholders = ",".join("?" * len(expanded))
            return f"WHERE {id_column} IN ({placeholders})", expanded
        elif scope == "by_content_version":
            if not content_version_ids:
                raise ValueError("scope='by_content_version' requires 'content_version_ids' parameter")
            placeholders = ",".join("?" * len(content_version_ids))
            if table == "content_versions":
                return f"WHERE content_version_id IN ({placeholders})", content_version_ids
            elif table == "files":
                return f"WHERE content_version_id IN ({placeholders})", content_version_ids
            elif table == "asts":
                return f"WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id IN ({placeholders}))", content_version_ids
            elif table in ("symbols", "refs"):
                # CONTENT-KEYED: symbols/refs join through asts.file_id
                return f"WHERE ast_id IN (SELECT ast_id FROM asts WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id IN ({placeholders})))", content_version_ids
            else:
                return f"WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id IN ({placeholders}))", content_version_ids
        else:
            raise ValueError(f"Unknown scope: {scope}")
    
    try:
        # Target-specific deletion logic
        if target == "asts":
            where, params = get_where_clause("asts", "ast_id")
            count_sql = f"SELECT COUNT(*) FROM asts {where}"
            delete_sql = f"DELETE FROM asts {where}"
            
        elif target == "symbols":
            where, params = get_where_clause("symbols", "symbol_id")
            count_sql = f"SELECT COUNT(*) FROM symbols {where}"
            delete_sql = f"DELETE FROM symbols {where}"
            
        elif target == "refs":
            where, params = get_where_clause("refs", "ref_id")
            count_sql = f"SELECT COUNT(*) FROM refs {where}"
            delete_sql = f"DELETE FROM refs {where}"
            
        elif target == "files":
            where, params = get_where_clause("files", "file_id")
            # Files have CASCADE DELETE to asts, which cascades to symbols/refs
            # We just need to delete files - SQLite cascade handles the rest
            count_sql = f"SELECT COUNT(*) FROM files {where}"
            
            if confirm:
                # Count what will be cascade-deleted before we delete
                cur.execute(f"SELECT COUNT(*) FROM asts WHERE file_id IN (SELECT file_id FROM files {where})", params)
                asts_count = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM symbols WHERE ast_id IN (SELECT ast_id FROM asts WHERE file_id IN (SELECT file_id FROM files {where}))", params)
                symbols_count = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM refs WHERE ast_id IN (SELECT ast_id FROM asts WHERE file_id IN (SELECT file_id FROM files {where}))", params)
                refs_count = cur.fetchone()[0]
                
                # Delete files - CASCADE handles asts, symbols, refs
                cur.execute(f"DELETE FROM files {where}", params)
                files_deleted = cur.rowcount
                db.conn.commit()
                
                result["success"] = True
                result["rows_deleted"] = files_deleted
                result["cascade"] = {
                    "symbols_deleted": symbols_count,  # Cascaded via asts
                    "refs_deleted": refs_count,        # Cascaded via asts
                    "asts_deleted": asts_count,        # Cascaded from files
                }
                trace.log("ck3lens.db_delete", {"target": target, "scope": scope}, result)
            return result
            
        elif target == "content_versions":
            where, params = get_where_clause("content_versions", "content_version_id")
            count_sql = f"SELECT COUNT(*) FROM content_versions {where}"
            
            if confirm:
                # Get IDs first for cascade
                cur.execute(f"SELECT content_version_id FROM content_versions {where}", params)
                cv_ids = [r[0] for r in cur.fetchall()]
                
                if cv_ids:
                    placeholders = ",".join("?" * len(cv_ids))
                    
                    # Count what will be cascade-deleted (symbols/refs cascade from asts)
                    cur.execute(f"SELECT COUNT(*) FROM asts WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id IN ({placeholders}))", cv_ids)
                    asts_count = cur.fetchone()[0]
                    cur.execute(f"SELECT COUNT(*) FROM symbols WHERE ast_id IN (SELECT ast_id FROM asts WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id IN ({placeholders})))", cv_ids)
                    symbols_count = cur.fetchone()[0]
                    cur.execute(f"SELECT COUNT(*) FROM refs WHERE ast_id IN (SELECT ast_id FROM asts WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id IN ({placeholders})))", cv_ids)
                    refs_count = cur.fetchone()[0]
                    cur.execute(f"SELECT COUNT(*) FROM files WHERE content_version_id IN ({placeholders})", cv_ids)
                    files_count = cur.fetchone()[0]
                    
                    # Delete playset_mods first (no cascade)
                    cur.execute(f"DELETE FROM playset_mods WHERE content_version_id IN ({placeholders})", cv_ids)
                    playset_mods_deleted = cur.rowcount
                    
                    # Delete files - CASCADE handles asts ? symbols/refs
                    cur.execute(f"DELETE FROM files WHERE content_version_id IN ({placeholders})", cv_ids)
                    files_deleted = cur.rowcount
                    
                    # Delete content_versions
                    cur.execute(f"DELETE FROM content_versions {where}", params)
                    cv_deleted = cur.rowcount
                    
                    # Clean orphaned mod_packages
                    cur.execute("DELETE FROM mod_packages WHERE mod_package_id NOT IN (SELECT DISTINCT mod_package_id FROM content_versions WHERE mod_package_id IS NOT NULL)")
                    mod_packages_deleted = cur.rowcount
                    db.conn.commit()
                    
                    result["success"] = True
                    result["rows_deleted"] = cv_deleted
                    result["cascade"] = {
                        "files_deleted": files_deleted,
                        "symbols_deleted": symbols_count,    # Cascaded via asts
                        "refs_deleted": refs_count,          # Cascaded via asts
                        "asts_deleted": asts_count,          # Cascaded from files
                        "playset_mods_deleted": playset_mods_deleted,
                        "mod_packages_deleted": mod_packages_deleted,
                    }
                else:
                    result["success"] = True
                    result["rows_deleted"] = 0
                    
                trace.log("ck3lens.db_delete", {"target": target, "scope": scope}, result)
                return result
                
        elif target == "lookups":
            # Delete all lookup tables
            lookup_tables = ["trait_lookups", "event_lookups", "decision_lookups", "culture_lookups", "religion_lookups"]
            if not confirm:
                counts = {}
                for table in lookup_tables:
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {table}")
                        counts[table] = cur.fetchone()[0]
                    except:
                        counts[table] = 0
                result["rows_would_delete"] = sum(counts.values())
                result["details"] = counts
                trace.log("ck3lens.db_delete", {"target": target, "scope": scope}, result)
                return result
            else:
                total = 0
                counts = {}
                for table in lookup_tables:
                    try:
                        cur.execute(f"DELETE FROM {table}")
                        counts[table] = cur.rowcount
                        total += cur.rowcount
                    except:
                        counts[table] = 0
                db.conn.commit()
                result["success"] = True
                result["rows_deleted"] = total
                result["details"] = counts
                trace.log("ck3lens.db_delete", {"target": target, "scope": scope}, result)
                return result
                
        elif target == "playsets":
            if not confirm:
                cur.execute("SELECT COUNT(*) FROM playsets")
                playsets = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM playset_mods")
                playset_mods = cur.fetchone()[0]
                result["rows_would_delete"] = playsets + playset_mods
                result["details"] = {"playsets": playsets, "playset_mods": playset_mods}
                trace.log("ck3lens.db_delete", {"target": target, "scope": scope}, result)
                return result
            else:
                cur.execute("DELETE FROM playset_mods")
                pm_deleted = cur.rowcount
                cur.execute("DELETE FROM playsets")
                p_deleted = cur.rowcount
                db.conn.commit()
                result["success"] = True
                result["rows_deleted"] = p_deleted + pm_deleted
                result["details"] = {"playsets": p_deleted, "playset_mods": pm_deleted}
                trace.log("ck3lens.db_delete", {"target": target, "scope": scope}, result)
                return result
                
        elif target == "build_tracking":
            if not confirm:
                cur.execute("SELECT COUNT(*) FROM builder_runs")
                runs = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM builder_steps")
                steps = cur.fetchone()[0]
                result["rows_would_delete"] = runs + steps
                result["details"] = {"builder_runs": runs, "builder_steps": steps}
                trace.log("ck3lens.db_delete", {"target": target, "scope": scope}, result)
                return result
            else:
                cur.execute("DELETE FROM build_lock")
                cur.execute("DELETE FROM builder_steps")
                steps = cur.rowcount
                cur.execute("DELETE FROM builder_runs")
                runs = cur.rowcount
                db.conn.commit()
                result["success"] = True
                result["rows_deleted"] = runs + steps
                result["details"] = {"builder_runs": runs, "builder_steps": steps}
                trace.log("ck3lens.db_delete", {"target": target, "scope": scope}, result)
                return result
        else:
            result["error"] = f"Unknown target: {target}"
            return result
        
        # Preview mode - count what would be deleted
        if not confirm:
            cur.execute(count_sql, params)
            count = cur.fetchone()[0]
            result["rows_would_delete"] = count
            result["preview"] = True
            trace.log("ck3lens.db_delete", {"target": target, "scope": scope, "preview": True}, result)
            return result
        
        # Actual delete
        cur.execute(delete_sql, params)
        result["success"] = True
        result["rows_deleted"] = cur.rowcount
        db.conn.commit()
        
    except Exception as e:
        result["error"] = str(e)
        
    trace.log("ck3lens.db_delete", {"target": target, "scope": scope}, result)
    return result


@mcp.tool()
def ck3_get_policy_status() -> dict:
    """
    Check if policy enforcement is working.
    
    ⚠️ CRITICAL: If this returns healthy=False, the agent MUST stop work
    and fix the policy system before continuing.
    
    Returns:
        {
            "healthy": bool,          # True if policy validation works
            "error": str or null,     # Error message if broken
            "validated_at": float,    # Timestamp of last check
            "message": str            # Human-readable status
        }
    """
    import time
    
    trace = _get_trace()
    
    # Run fresh health check
    health = _check_policy_health()
    
    result = {
        "healthy": health["healthy"],
        "error": health["error"],
        "validated_at": health["validated_at"],
    }
    
    if health["healthy"]:
        result["message"] = "✅ Policy enforcement is ACTIVE"
    else:
        result["message"] = f"🚨 POLICY ENFORCEMENT IS DOWN: {health['error']}"
        result["action_required"] = "Agent must stop work. Fix policy module or restart MCP server."
    
    trace.log("ck3lens.get_policy_status", {}, result)
    
    return result


# ============================================================================
# Unified Command Tools (Consolidated)
# ============================================================================

@mcp.tool()
def ck3_logs(
    source: Literal["error", "game", "debug", "crash"] = "error",
    command: Literal["summary", "list", "search", "detail", "categories", "cascades", "read"] = "summary",
    # Filters
    priority: int | None = None,
    category: str | None = None,
    mod_filter: str | None = None,
    exclude_cascade_children: bool = True,
    # Search
    query: str | None = None,
    # Detail (for crash)
    crash_id: str | None = None,
    # Read raw
    lines: int = 100,
    from_end: bool = True,
    # Pagination
    limit: int = 50,
) -> dict:
    """
    Unified logging tool for error.log, game.log, debug.log, and crash reports.
    
    Source + Command combinations:
    
    source=error:
        command=summary     ? Error log summary (counts by priority/category/mod)
        command=list        ? Filtered error list (priority, category, mod_filter)
        command=search      ? Search errors (query required)
        command=cascades    ? Cascading error patterns (fix root causes first)
    
    source=game:
        command=summary     ? Game log summary with category breakdown
        command=list        ? Game log errors (category filter optional)
        command=search      ? Search game log (query required)
        command=categories  ? Category breakdown with descriptions
    
    source=debug:
        command=summary     ? System info, DLCs, mod list
    
    source=crash:
        command=summary     ? Recent crash reports list
        command=detail      ? Full crash report (crash_id required)
    
    Any source:
        command=read        ? Raw log content (lines, from_end, query for search)
    
    Args:
        source: Log source to query
        command: Action to perform
        priority: Max priority 1-5 (error source only)
        category: Filter by category
        mod_filter: Filter by mod name (partial match)
        exclude_cascade_children: Skip errors caused by cascade patterns
        query: Search query for search/read commands
        crash_id: Crash folder name for detail command
        lines: Lines to return for read command
        from_end: Read from end (tail) vs start (head)
        limit: Max results for list commands
    
    Returns:
        Dict with results based on command
    """
    from ck3lens.unified_tools import ck3_logs_impl
    
    trace = _get_trace()
    
    result = ck3_logs_impl(
        source=source,
        command=command,
        priority=priority,
        category=category,
        mod_filter=mod_filter,
        exclude_cascade_children=exclude_cascade_children,
        query=query,
        crash_id=crash_id,
        lines=lines,
        from_end=from_end,
        limit=limit,
    )
    
    trace.log("ck3lens.logs", {
        "source": source,
        "command": command,
        "category": category,
    }, {"success": "error" not in result})
    
    return result


# ============================================================================
# ck3_conflicts - Unified Conflict Detection
# ============================================================================

ConflictCommand = Literal["symbols", "files", "summary"]

@mcp.tool()
def ck3_conflicts(
    command: ConflictCommand = "symbols",
    # Filters
    symbol_type: str | None = None,
    symbol_names: list[str] | None = None,
    game_folder: str | None = None,
    # Options
    include_compatch: bool = False,
    limit: int = 100,
) -> dict:
    """
    Unified conflict detection for the active playset.
    
    Commands:
    
    command=symbols  → Find symbols defined by multiple mods (default)
    command=files    → Find files that multiple mods override
    command=summary  → Get conflict statistics
    
    Args:
        command: Operation to perform
        symbol_type: Filter by symbol type (trait, event, decision, on_action, etc.)
        symbol_names: Filter to specific symbols (for detailed analysis)
        game_folder: Filter by CK3 folder (e.g., "common/traits", "events")
        include_compatch: Include conflicts from compatch mods (default False)
        limit: Max conflicts to return (default 100)
    
    Returns:
        command=symbols:
            {
                "conflict_count": int,
                "conflicts": [
                    {
                        "name": str,
                        "symbol_type": str,
                        "source_count": int,
                        "sources": [{"mod": str, "file": str, "line": int}],
                    }
                ],
                "compatch_conflicts_hidden": int
            }
        
        command=files:
            {
                "conflicts": [
                    {
                        "relpath": str,
                        "mods": [str],
                        "has_zzz_prefix": bool  # True if any mod uses zzz_ prefix
                    }
                ]
            }
        
        command=summary:
            {
                "total_symbol_conflicts": int,
                "total_file_conflicts": int,
                "by_type": {"trait": 5, "event": 3, ...},
                "by_folder": {"common/traits": 10, ...}
            }
    
    Examples:
        ck3_conflicts()  # All symbol conflicts
        ck3_conflicts(symbol_type="on_action")  # Only on_action conflicts
        ck3_conflicts(symbol_names=["brave", "craven"])  # Specific symbols
        ck3_conflicts(command="files", game_folder="common/on_action")  # File conflicts
        ck3_conflicts(command="summary")  # Overview statistics
    """
    db = _get_db()
    trace = _get_trace()
    session = _get_session()
    
    # Get CVIDs from session.mods[] - THE canonical source
    # No db_visibility() or visible_cvids - derive inline from mods[]
    cvids: frozenset[int] = frozenset(
        m.cvid for m in session.mods 
        if hasattr(m, 'cvid') and m.cvid is not None
    )
    
    if not cvids:
        return {"error": "No mods in session.mods[] - no active playset?"}
    
    if command == "symbols":
        # Use the internal method that was powering the deleted tools
        result = db._get_symbol_conflicts_internal(
            visible_cvids=cvids,
            symbol_type=symbol_type,
            game_folder=game_folder,
            limit=limit,
            include_compatch=include_compatch,
        )
        
        # Apply symbol_names filter if provided
        if symbol_names and result.get("conflicts"):
            names_lower = {n.lower() for n in symbol_names}
            result["conflicts"] = [
                c for c in result["conflicts"]
                if c["name"].lower() in names_lower
            ]
            result["conflict_count"] = len(result["conflicts"])
        
        trace.log("ck3lens.conflicts.symbols", {
            "symbol_type": symbol_type,
            "symbol_names": symbol_names,
            "game_folder": game_folder,
            "include_compatch": include_compatch,
        }, {
            "conflict_count": result.get("conflict_count", 0)
        })
        
        return result
    
    elif command == "files":
        # File-level conflict detection
        # Note: cvids already validated above - this code path only reached if cvids exist
        cv_filter = ",".join(str(cv) for cv in cvids)
        
        sql = f"""
            SELECT 
                f.relpath,
                GROUP_CONCAT(DISTINCT COALESCE(mp.name, 'vanilla')) as mods,
                COUNT(DISTINCT f.content_version_id) as mod_count
            FROM files f
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE f.content_version_id IN ({cv_filter})
        """
        params = []
        
        if game_folder:
            sql += " AND f.relpath LIKE ?"
            params.append(f"{game_folder}%")
        
        sql += """
            GROUP BY f.relpath
            HAVING mod_count > 1
            ORDER BY mod_count DESC
            LIMIT ?
        """
        params.append(limit)
        
        rows = db.conn.execute(sql, params).fetchall()
        
        conflicts = []
        for row in rows:
            relpath = row["relpath"]
            mods = row["mods"].split(",")
            has_zzz = any("zzz_" in relpath for _ in [1])  # Check prefix
            
            conflicts.append({
                "relpath": relpath,
                "mods": mods,
                "mod_count": row["mod_count"],
                "has_zzz_prefix": has_zzz,
            })
        
        trace.log("ck3lens.conflicts.files", {
            "game_folder": game_folder,
        }, {
            "conflict_count": len(conflicts)
        })
        
        return {"conflicts": conflicts, "count": len(conflicts)}
    
    elif command == "summary":
        # Summary statistics
        # Note: cvids already validated above - this code path only reached if cvids exist
        cv_filter = ",".join(str(cv) for cv in cvids)
        
        # Count symbol conflicts by type
        type_sql = f"""
            SELECT 
                s.symbol_type,
                COUNT(DISTINCT s.name) as conflict_count
            FROM (
                SELECT symbol_type, name
                FROM symbols
                WHERE content_version_id IN ({cv_filter})
                GROUP BY symbol_type, name
                HAVING COUNT(DISTINCT content_version_id) > 1
            ) s
            GROUP BY s.symbol_type
        """
        type_rows = db.conn.execute(type_sql).fetchall()
        by_type = {row["symbol_type"]: row["conflict_count"] for row in type_rows}
        
        # Count file conflicts by folder
        folder_sql = f"""
            SELECT 
                SUBSTR(f.relpath, 1, INSTR(f.relpath || '/', '/') - 1) || '/' ||
                SUBSTR(SUBSTR(f.relpath, INSTR(f.relpath, '/') + 1), 1, 
                       INSTR(SUBSTR(f.relpath, INSTR(f.relpath, '/') + 1) || '/', '/') - 1) as folder,
                COUNT(*) as conflict_count
            FROM (
                SELECT relpath
                FROM files
                WHERE content_version_id IN ({cv_filter})
                GROUP BY relpath
                HAVING COUNT(DISTINCT content_version_id) > 1
            ) f
            GROUP BY folder
            ORDER BY conflict_count DESC
            LIMIT 20
        """
        folder_rows = db.conn.execute(folder_sql).fetchall()
        by_folder = {row["folder"]: row["conflict_count"] for row in folder_rows}
        
        total_symbols = sum(by_type.values())
        total_files = sum(by_folder.values())
        
        trace.log("ck3lens.conflicts.summary", {}, {
            "total_symbols": total_symbols,
            "total_files": total_files,
        })
        
        return {
            "total_symbol_conflicts": total_symbols,
            "total_file_conflicts": total_files,
            "by_type": by_type,
            "by_folder": by_folder,
        }
    
    else:
        return {"error": f"Unknown command: {command}"}


# ============================================================================
# Unified File Operations
# ============================================================================

@mcp.tool()
def ck3_file(
    command: Literal["get", "read", "write", "edit", "delete", "rename", "refresh", "list", "create_patch"],
    # Path identification
    path: str | None = None,
    mod_name: str | None = None,  # Mod name from active playset
    rel_path: str | None = None,
    # For get (from DB)
    include_ast: bool = False,
    # For read/write
    content: str | None = None,
    start_line: int = 1,
    end_line: int | None = None,
    max_bytes: int = 200000,
    # For edit
    old_content: str | None = None,
    new_content: str | None = None,
    # For rename
    new_path: str | None = None,
    # For write/edit
    validate_syntax: bool = True,
    # For policy-gated raw writes
    token_id: str | None = None,
    # For list
    path_prefix: str | None = None,
    pattern: str | None = None,
    # For create_patch (ck3lens mode only)
    source_path: str | None = None,
    patch_mode: Literal["partial_patch", "full_replace"] | None = None,
) -> dict:
    """
    Unified file operations tool.
    
    Commands:
    
    command=get          → Get file content from database (path required)
    command=read         → Read file from filesystem (path or target+rel_path)
    command=write        → Write file (path for raw write, or target+rel_path)
    command=edit         → Search-replace edit (target, rel_path, old_content, new_content)
    command=delete       → Delete file (target, rel_path required)
    command=rename       → Rename/move file (target, rel_path, new_path required)
    command=refresh      → Re-sync file to database (target, rel_path required)
    command=list         → List files (target required, path_prefix/pattern optional)
    command=create_patch → Create override patch file (ck3lens mode only)
    
    For write command with raw path:
    - ck3lens mode: DENIED (must use target+rel_path)
    - ck3raven-dev mode: Allowed with active contract or token
    
    Args:
        command: Operation to perform
        path: File path (for get/read from filesystem)
        mod_name: Mod name from active playset. Writable only if mod path is under
            local_mods_folder. For WIP workspace or vanilla files, use path parameter
            with appropriate domain prefix.
        rel_path: Relative path within target
        include_ast: Include parsed AST (for get)
        content: File content (for write)
        start_line: Start line for read (1-indexed)
        end_line: End line for read (inclusive)
        max_bytes: Max bytes to return
        old_content: Content to find (for edit)
        new_content: Replacement content (for edit)
        new_path: New path (for rename)
        validate_syntax: Validate CK3 syntax before write/edit
        path_prefix: Filter by path prefix (for list)
        pattern: Glob pattern (for list)
        source_path: Path being overridden (for create_patch)
        patch_mode: "partial_patch" (zzz_ prefix) or "full_replace" (same name)
    
    Returns:
        Dict with results based on command
    """
    from ck3lens.unified_tools import ck3_file_impl
    
    session = _get_session()
    trace = _get_trace()
    world = _get_world()  # WorldAdapter for unified path resolution
    
    # Only acquire DB connection for commands that need it
    db = _get_db() if command == "get" else None
    
    return ck3_file_impl(
        command=command,
        path=path,
        mod_name=mod_name,
        rel_path=rel_path,
        include_ast=include_ast,
        content=content,
        start_line=start_line,
        end_line=end_line,
        max_bytes=max_bytes,
        old_content=old_content,
        new_content=new_content,
        new_path=new_path,
        validate_syntax=validate_syntax,
        token_id=token_id,
        path_prefix=path_prefix,
        pattern=pattern,
        source_path=source_path,
        patch_mode=patch_mode,
        session=session,
        db=db,
        trace=trace,
        world=world,
    )


# ============================================================================
# Unified Folder Operations
# ============================================================================

@mcp.tool()
def ck3_folder(
    command: Literal["list", "contents", "top_level", "mod_folders"] = "contents",
    # For list/contents
    path: str | None = None,
    # For mod_folders
    content_version_id: int | None = None,
    # For contents
    folder_pattern: str | None = None,
    text_search: str | None = None,
    symbol_search: str | None = None,
    mod_filter: list[str] | None = None,
    file_type_filter: list[str] | None = None,
) -> dict:
    """
    Unified folder operations tool.
    
    Mode-aware behavior:
    - ck3lens mode: command=list restricted to active playset paths
    - ck3raven-dev mode: command=list has broader access for infrastructure testing
    
    Commands:
    
    command=list        ? List directory contents from filesystem (path required)
    command=contents    ? Get folder contents from database (path required)
    command=top_level   ? Get top-level folders in active playset
    command=mod_folders ? Get folders in specific mod (content_version_id required)
    
    Args:
        command: Operation to perform
        path: Folder path (for list/contents)
        content_version_id: Mod content version ID (for mod_folders)
        folder_pattern: Filter by folder pattern
        text_search: Filter by content text (FTS)
        symbol_search: Filter by symbol name
        mod_filter: Only show files from these mods
        file_type_filter: Filter by file extensions
    
    Returns:
        Dict with folder contents or entries
    """
    from ck3lens.unified_tools import ck3_folder_impl
    
    session = _get_session()
    trace = _get_trace()
    world = _get_world()  # WorldAdapter for visibility enforcement
    
    # Only acquire DB connection for commands that need it
    db_required = command in ("contents", "top_level", "mod_folders")
    db = _get_db() if db_required else None
    
    # CANONICAL: Get cvids from session.mods[] instead of using playset_id
    cvids = [m.cvid for m in session.mods if m.cvid is not None] if db_required else None
    
    return ck3_folder_impl(
        command=command,
        path=path,
        content_version_id=content_version_id,
        folder_pattern=folder_pattern,
        text_search=text_search,
        symbol_search=symbol_search,
        mod_filter=mod_filter,
        file_type_filter=file_type_filter,
        db=db,
        cvids=cvids,
        trace=trace,
        world=world,
    )


# ============================================================================
# Unified Playset Operations
# ============================================================================

@mcp.tool()
def ck3_playset(
    command: Literal["get", "list", "switch", "mods", "add_mod", "remove_mod", "reorder", "create", "import"] = "get",
    # For switch/add_mod/remove_mod/reorder
    playset_name: str | None = None,
    mod_name: str | None = None,
    # For reorder
    new_position: int | None = None,
    # For create
    name: str | None = None,
    description: str | None = None,
    vanilla_version_id: int | None = None,
    mod_ids: list[int] | None = None,
    # For import
    launcher_playset_name: str | None = None,
    # For mods command
    limit: int | None = None,
) -> dict:
    """
    Unified playset operations tool.
    
    Works in both modes:
    - ck3lens mode: Full playset management for mod compatibility work
    - ck3raven-dev mode: Playset context available for parser/ingestion testing
    
    Commands:
    
    command=get        ? Get active playset info
    command=list       ? List all playsets
    command=switch     ? Switch to different playset (playset_name required)
    command=mods       ? Get mods in active playset
    command=add_mod    ? Add mod to playset (mod_name required)
    command=remove_mod ? Remove mod from playset (mod_name required)
    command=reorder    ? Change mod load order (mod_name, new_position required)
    command=create     ? Create new playset (name required)
    command=import     ? Import playset from CK3 launcher
    
    Args:
        command: Operation to perform
        playset_name: Playset name (for switch)
        mod_name: Mod name (for add_mod/remove_mod/reorder)
        new_position: New load order position (for reorder, 0-indexed)
        name: New playset name (for create)
        description: Playset description (for create)
        vanilla_version_id: Vanilla content version (for create)
        mod_ids: List of content_version_ids (for create)
        launcher_playset_name: Launcher playset to import (for import)
        limit: Max mods to return for 'mods' command (default: None = all mods)
    
    Returns:
        Dict with playset info or operation result
    """
    global _session_scope
    
    trace = _get_trace()
    
    # FILE-BASED IMPLEMENTATION (database is DEPRECATED)
    
    if command == "list":
        # List all available playsets
        playsets = []
        manifest_active = None
        
        # Read manifest to see which is active
        if PLAYSET_MANIFEST_FILE.exists():
            try:
                manifest = json.loads(PLAYSET_MANIFEST_FILE.read_text(encoding='utf-8-sig'))
                manifest_active = manifest.get("active", "")
            except Exception:
                pass
        
        for f in PLAYSETS_DIR.glob("*.json"):
            if f.name.endswith(".schema.json") or f.name == "playset_manifest.json" or f.name == "sub_agent_templates.json":
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8-sig"))
                enabled_mods = [m for m in data.get("mods", []) if m.get("enabled", True)]
                playsets.append({
                    "filename": f.name,
                    "name": data.get("playset_name", f.stem),
                    "description": data.get("description", ""),
                    "mod_count": len(enabled_mods),
                    "is_active": f.name == manifest_active,
                })
            except Exception as e:
                playsets.append({
                    "filename": f.name,
                    "name": f.stem,
                    "error": str(e),
                    "is_active": f.name == manifest_active,
                })
        
        return {
            "success": True,
            "playsets": playsets,
            "active": manifest_active,
            "manifest_path": str(PLAYSET_MANIFEST_FILE),
        }
    
    elif command == "switch":
        # Switch to a different playset by updating manifest
        # Automatically checks build status and starts builder if mods need processing
        if not playset_name:
            return {"success": False, "error": "playset_name required for switch"}
        
        # Find the playset file
        target_file = None
        playset_data = None
        for f in PLAYSETS_DIR.glob("*.json"):
            if f.name.endswith(".schema.json") or f.name == "playset_manifest.json":
                continue
            # Match by filename or playset_name in content
            if f.name == playset_name or f.stem == playset_name:
                target_file = f
                try:
                    playset_data = json.loads(f.read_text(encoding="utf-8-sig"))
                except Exception:
                    pass
                break
            try:
                data = json.loads(f.read_text(encoding="utf-8-sig"))
                if data.get("playset_name") == playset_name:
                    target_file = f
                    playset_data = data
                    break
            except Exception:
                pass
        
        if not target_file:
            return {"success": False, "error": f"Playset '{playset_name}' not found"}
        
        # Update manifest
        manifest = {
            "active": target_file.name,
            "last_switched": datetime.now().isoformat(),
            "notes": "Updated by ck3_playset switch command"
        }
        PLAYSET_MANIFEST_FILE.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        
        # Clear cached scope to force reload
        _session_scope = None
        
        # Reload and return new scope
        new_scope = _get_session_scope(force_refresh=True)
        
        # Check build status for all mods in this playset
        # NOTE: Inlined check logic (January 2026) - avoids qbuilder import hang
        build_status = None
        mods_needing_build = []
        mods_missing_from_disk = []
        db_available = False
        try:
            db = _get_db()
            if db and playset_data:
                db_available = True
                conn = db.conn
                mods = playset_data.get('mods', [])
                
                for mod in mods:
                    mod_name_check = mod.get('name', 'Unknown')
                    mod_path_check = mod.get('path') or mod.get('source_path')
                    exists_on_disk = mod_path_check and Path(mod_path_check).exists()
                    
                    if not exists_on_disk:
                        mods_missing_from_disk.append(mod_name_check)
                        continue
                    
                    # Check if mod has files in DB
                    try:
                        row = conn.execute("""
                            SELECT COUNT(*) as file_count,
                                   (SELECT COUNT(*) FROM build_queue bq 
                                    JOIN files f ON bq.file_id = f.file_id
                                    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                                    JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                                    WHERE mp.name = ? AND bq.status = 'pending') as pending_count
                            FROM files f
                            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                            JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                            WHERE mp.name = ?
                        """, (mod_name_check, mod_name_check)).fetchone()
                        
                        file_count = row[0] if row else 0
                        pending = row[1] if row else 0
                    except:
                        file_count = 0
                        pending = 0
                    
                    if file_count == 0:
                        mods_needing_build.append({
                            "name": mod_name_check,
                            "status": "not_indexed",
                            "path": mod_path_check
                        })
                    elif pending > 0:
                        mods_needing_build.append({
                            "name": mod_name_check,
                            "status": "pending_build",
                            "path": mod_path_check
                        })
                
                build_status = {
                    "needs_build": len(mods_needing_build) > 0,
                    "mods": mods_needing_build,
                }
        except Exception as e:
            # DB might not be available yet - need to build everything
            build_status = {"error": str(e), "needs_build": True}
        
        result = {
            "success": True,
            "message": f"Switched to playset: {target_file.name}",
            "active_playset": target_file.name,
            "playset_name": new_scope.get("playset_name"),
            "mod_count": len(new_scope.get("active_mod_ids", set())),
        }
        
        # Report missing-from-disk mods (these cannot be built)
        if mods_missing_from_disk:
            result["mods_missing_from_disk"] = mods_missing_from_disk
            result["missing_warning"] = (
                f"? {len(mods_missing_from_disk)} mod(s) are in playset but not on disk. "
                f"These mods will be skipped: {mods_missing_from_disk}"
            )
        
        # Automatically start qbuilder if mods need processing
        # NOTE: Updated January 2026 - builder/daemon.py replaced by qbuilder
        # RACE CONDITION FIX: Check writer lock before spawning
        builder_started = False
        if mods_needing_build or not db_available:
            try:
                import subprocess
                import sys
                import time
                
                # Find the qbuilder CLI and venv python
                repo_root = Path(__file__).parent.parent.parent
                qbuilder_module = repo_root / "qbuilder"
                venv_python = repo_root / ".venv" / "Scripts" / "python.exe"
                
                if not venv_python.exists():
                    venv_python = repo_root / ".venv" / "bin" / "python"  # Linux/Mac
                
                if qbuilder_module.exists() and venv_python.exists():
                    # CRITICAL: Check writer lock BEFORE spawning to prevent race condition
                    # This prevents multiple daemons from being spawned simultaneously
                    should_spawn = True
                    try:
                        sys.path.insert(0, str(repo_root))
                        from qbuilder.writer_lock import check_writer_lock
                        from ck3lens.daemon_client import daemon as daemon_client
                        
                        db_path = Path.home() / ".ck3raven" / "ck3raven.db"
                        lock_status = check_writer_lock(db_path)
                        
                        if lock_status.get("lock_exists") and lock_status.get("holder_alive"):
                            # Another daemon is starting or running - wait for IPC
                            should_spawn = False
                            for _ in range(20):  # Wait up to 10 seconds
                                time.sleep(0.5)
                                if daemon_client.is_available(force_check=True):
                                    builder_started = True
                                    result["builder_started"] = True
                                    result["builder_message"] = "QBuilder daemon already running"
                                    break
                    except ImportError:
                        pass  # Fall back to basic spawn
                    
                    if should_spawn:
                        # Start qbuilder daemon (single-writer architecture)
                        # The daemon runs discovery + build workers with IPC server
                        cmd = [
                            str(venv_python),
                            "-m", "qbuilder",
                            "daemon",
                        ]
                        
                        # Run detached (background mode)
                        if sys.platform == "win32":
                            DETACHED_PROCESS = 0x00000008
                            CREATE_NEW_PROCESS_GROUP = 0x00000200
                            CREATE_NO_WINDOW = 0x08000000
                            subprocess.Popen(
                                cmd,
                                cwd=str(repo_root),  # qbuilder needs repo context
                                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
                                close_fds=True,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                        else:
                            subprocess.Popen(
                                cmd,
                                cwd=str(repo_root),
                                start_new_session=True,
                                close_fds=True,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                        
                        builder_started = True
                        if mods_needing_build:
                            result["builder_started"] = True
                            result["builder_message"] = (
                                f"🔨 QBuilder started for {len(mods_needing_build)} mod(s) needing processing. "
                                f"Check status with: python -m qbuilder status"
                            )
                        else:
                            result["builder_started"] = True
                            result["builder_message"] = (
                                "🔨 Database not available or empty. QBuilder started to index all playset mods. "
                                "Check status with: python -m qbuilder status"
                            )
            except Exception as e:
                result["builder_error"] = f"Failed to start qbuilder: {e}"
                result["build_command"] = "python -m qbuilder build"
        
        # Add build status information
        if build_status and not build_status.get("error"):
            result["build_status"] = {
                "playset_valid": build_status.get("playset_valid", False),
                "ready_mods": build_status.get("ready_mods", 0),
                "pending_mods": build_status.get("pending_mods", 0),
                "missing_mods": build_status.get("missing_mods", 0),
            }
        
        if not mods_needing_build and not mods_missing_from_disk and db_available and build_status and not build_status.get("error"):
            result["build_status_message"] = "? All mods are ready. No build needed."
        
        return result
    
    elif command == "get":
        # Get current active playset info
        scope = _get_session_scope()
        manifest_active = None
        if PLAYSET_MANIFEST_FILE.exists():
            try:
                manifest = json.loads(PLAYSET_MANIFEST_FILE.read_text(encoding='utf-8-sig'))
                manifest_active = manifest.get("active")
            except Exception:
                pass
        
        return {
            "success": True,
            "active_file": manifest_active,
            "playset_name": scope.get("playset_name"),
            "source": scope.get("source"),
            "mod_count": len(scope.get("active_mod_ids", set())),
            "has_agent_briefing": bool(scope.get("agent_briefing")),
            "vanilla_root": scope.get("vanilla_root"),
        }
    
    elif command == "mods":
        # Get mods in active playset
        scope = _get_session_scope()
        mod_list = scope.get("mod_list", [])
        
        enabled = [m for m in mod_list if m.get("enabled", True)]
        disabled = [m for m in mod_list if not m.get("enabled", True)]
        
        return {
            "success": True,
            "playset_name": scope.get("playset_name"),
            "enabled_count": len(enabled),
            "disabled_count": len(disabled),
            "mods": enabled[:limit] if limit else enabled,
            "truncated": limit is not None and len(enabled) > limit,
        }
    
    elif command == "add_mod":
        # Add a mod to the active playset's local_mods array
        if not mod_name:
            return {"success": False, "error": "mod_name required for add_mod"}
        
        # Get the active playset file
        scope = _get_session_scope()
        if scope.get("source") == "none":
            return {"success": False, "error": "No active playset. Switch to one first."}
        
        # Find the active playset file
        if not PLAYSET_MANIFEST_FILE.exists():
            return {"success": False, "error": "No playset manifest found"}
        
        try:
            manifest = json.loads(PLAYSET_MANIFEST_FILE.read_text(encoding="utf-8-sig"))
            active_file = manifest.get("active")
            if not active_file:
                return {"success": False, "error": "No active playset in manifest"}
            
            playset_path = PLAYSETS_DIR / active_file
            if not playset_path.exists():
                return {"success": False, "error": f"Active playset file not found: {active_file}"}
            
            playset_data = json.loads(playset_path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            return {"success": False, "error": f"Failed to read playset: {e}"}
        
        # Check if mod_name is a path or a name
        mod_path = None
        if Path(mod_name).exists():
            # It's a path - normalize it via canonical utility
            mod_path = str(Path(mod_name).resolve())  # Needed for absolute path
            # Try to get the actual mod name from descriptor.mod
            descriptor = Path(mod_name) / "descriptor.mod"
            if descriptor.exists():
                try:
                    desc_content = descriptor.read_text(encoding="utf-8")
                    for line in desc_content.split("\n"):
                        if line.strip().startswith("name="):
                            # Extract quoted string
                            match = line.split("=", 1)[1].strip().strip('"')
                            if match:
                                mod_name = match
                                break
                except Exception:
                    pass
        else:
            # It's a name - try to find the mod path
            # Look in common mod locations
            mod_dirs = [
                Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod",
            ]
            for mod_dir in mod_dirs:
                if not mod_dir.exists():
                    continue
                # Check each folder for a matching descriptor
                for folder in mod_dir.iterdir():
                    if not folder.is_dir():
                        continue
                    descriptor = folder / "descriptor.mod"
                    if descriptor.exists():
                        try:
                            desc_content = descriptor.read_text(encoding="utf-8")
                            for line in desc_content.split("\n"):
                                if line.strip().startswith("name="):
                                    name_in_desc = line.split("=", 1)[1].strip().strip('"')
                                    if name_in_desc.lower() == mod_name.lower():
                                        mod_path = str(folder.resolve())  # Needed for absolute path
                                        mod_name = name_in_desc  # Use canonical name
                                        break
                        except Exception:
                            pass
                    if mod_path:
                        break
                if mod_path:
                    break
        
        if not mod_path:
            return {
                "success": False, 
                "error": f"Could not find mod '{mod_name}'. Provide full path or ensure mod is installed.",
                "hint": "Use full path to mod folder, e.g., 'C:\\...\\mod\\MyModFolder'"
            }
        
        # Check if already in mods[]
        mods_list = playset_data.get("mods", [])
        for existing in mods_list:
            if existing.get("name", "").lower() == mod_name.lower() or existing.get("path") == mod_path:
                return {
                    "success": False,
                    "error": f"Mod '{mod_name}' is already in mods[]",
                    "existing_entry": existing
                }
        
        # Calculate next load order
        max_load_order = max((m.get("load_order", 0) for m in mods_list), default=-1)
        
        # Add to mods[] (THE list, not a separate local_mods array)
        new_mod_entry = {
            "name": mod_name,
            "path": mod_path,
            "load_order": max_load_order + 1,
            "enabled": True,
            "is_compatch": False,
            "notes": f"Added by ck3_playset add_mod on {datetime.now().isoformat()}"
        }
        mods_list.append(new_mod_entry)
        playset_data["mods"] = mods_list
        
        # Write back
        try:
            playset_path.write_text(json.dumps(playset_data, indent=2), encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"Failed to write playset: {e}"}
        
        # Clear cached scope
        _session_scope = None
        
        # Check if mod needs building - pure SQL, no qbuilder import (January 2026)
        build_needed = False
        try:
            db = _get_db()
            if db:
                # Check if mod has files in DB
                row = db.conn.execute("""
                    SELECT COUNT(*) as file_count
                    FROM files f
                    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                    JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                    WHERE mp.name = ?
                """, (mod_name,)).fetchone()
                
                file_count = row[0] if row else 0
                build_needed = (file_count == 0)
        except Exception:
            build_needed = True  # Assume needs build if we can't check
        
        result = {
            "success": True,
            "message": f"Added '{mod_name}' to mods[]",
            "mod_entry": new_mod_entry,
            "mods_count": len(mods_list),
        }
        
        if build_needed:
            result["build_needed"] = True
            result["build_prompt"] = (
                f"?? Mod '{mod_name}' needs to be indexed. "
                f"Run: python -m qbuilder.cli build"
            )
        
        return result
    
    else:
        # Other commands not yet implemented for file-based
        return {
            "success": False,
            "error": f"Command '{command}' not yet implemented for file-based playsets",
            "hint": "Use 'get', 'list', 'switch', or 'mods' commands"
        }


# ============================================================================
# Unified Git Operations
# ============================================================================

@mcp.tool()
def ck3_git(
    command: Literal["status", "diff", "add", "commit", "push", "pull", "log"],
    mod_name: str | None = None,
    # For diff
    file_path: str | None = None,
    # For add
    files: list[str] | None = None,
    all_files: bool = False,
    # For commit
    message: str | None = None,
    # For log
    limit: int = 10,
) -> dict:
    """
    Unified git operations for mods.
    
    ?? KNOWN ISSUE: This tool may hang due to GitLens extension conflicts.
    WORKAROUND: Use ck3_exec with git commands instead:
        ck3_exec("git status", working_dir=mod_path)
        ck3_exec("git add .", working_dir=mod_path)
        ck3_exec("git commit -m 'message'", working_dir=mod_path)
    
    Mode-aware behavior:
    - ck3raven-dev mode: Operates on ck3raven repo (mod_name ignored)
    - ck3lens mode: Operates on mods (mod_name required)
    
    Commands:
    
    command=status ? Get git status
    command=diff   ? Get git diff (file_path optional)
    command=add    ? Stage files (files or all_files required)
    command=commit ? Commit staged changes (message required)
    command=push   ? Push to remote
    command=pull   ? Pull from remote
    command=log    ? Get commit log (limit optional)
    
    Args:
        command: Git operation to perform
        mod_name: mod name (required in ck3lens mode, ignored in ck3raven-dev mode)
        file_path: Specific file for diff
        files: List of files to stage
        all_files: Stage all changes
        message: Commit message
        limit: Max commits to return for log
    
    Returns:
        Dict with git operation results
    """
    from ck3lens.unified_tools import ck3_git_impl
    
    session = _get_session()
    trace = _get_trace()
    
    return ck3_git_impl(
        command=command,
        mod_name=mod_name,
        file_path=file_path,
        files=files,
        all_files=all_files,
        message=message,
        limit=limit,
        session=session,
        trace=trace,
    )


# ============================================================================
# Unified Validation Operations
# ============================================================================

@mcp.tool()
def ck3_validate(
    target: Literal["syntax", "python", "references", "bundle", "policy"],
    # For syntax/python
    content: str | None = None,
    file_path: str | None = None,
    # For references
    symbol_name: str | None = None,
    symbol_type: str | None = None,
    # For bundle
    artifact_bundle: dict | None = None,
    # For policy
    mode: str | None = None,
    trace_path: str | None = None,
) -> dict:
    """
    Unified validation tool.
    
    Targets:
    
    target=syntax     ? Validate CK3 script syntax (content required)
    target=python     ? Check Python syntax (content or file_path required)
    target=references ? Validate symbol references exist (symbol_name required)
    target=bundle     ? Validate artifact bundle (artifact_bundle required)
    target=policy     ? Validate against policy rules (mode required)
    
    Args:
        target: What to validate
        content: Code/script content to validate
        file_path: File path (for python, or context for syntax)
        symbol_name: Symbol to look up (for references)
        symbol_type: Filter by symbol type (for references)
        artifact_bundle: Bundle dict to validate
        mode: Agent mode for policy validation
        trace_path: Path to trace file for policy validation
    
    Returns:
        Dict with validation results
    """
    from ck3lens.unified_tools import ck3_validate_impl
    
    db = _get_db()
    trace = _get_trace()
    
    return ck3_validate_impl(
        target=target,
        content=content,
        file_path=file_path,
        symbol_name=symbol_name,
        symbol_type=symbol_type,
        artifact_bundle=artifact_bundle,
        mode=mode,
        trace_path=trace_path,
        db=db,
        trace=trace,
    )


# ============================================================================
# VS Code IPC Operations
# ============================================================================

@mcp.tool()
def ck3_vscode(
    command: Literal["ping", "diagnostics", "all_diagnostics", "errors_summary", 
                     "validate_file", "open_files", "active_file", "status"] = "status",
    # For diagnostics/validate_file
    path: str | None = None,
    # For all_diagnostics
    severity: str | None = None,
    source: str | None = None,
    limit: int = 50,
) -> dict:
    """
    Access VS Code IDE APIs via IPC connection.
    
    Connects to VS Code extension's diagnostics server to query IDE state,
    get Pylance/language server diagnostics, and more.
    
    Commands:
    
    command=status         ? Check if VS Code IPC server is available
    command=ping           ? Test connection to VS Code
    command=diagnostics    ? Get diagnostics for a file (path required)
    command=all_diagnostics ? Get diagnostics for all open files
    command=errors_summary ? Get workspace error summary
    command=validate_file  ? Trigger validation for a file (path required)
    command=open_files     ? List currently open files in VS Code
    command=active_file    ? Get active file info with diagnostics
    
    Args:
        command: Operation to perform
        path: Absolute file path (for diagnostics/validate_file)
        severity: Filter by severity ('error', 'warning', 'info', 'hint')
        source: Filter by source (e.g., 'Pylance', 'CK3 Lens')
        limit: Max files to return for all_diagnostics
    
    Returns:
        Dict with results based on command. Returns helpful error if VS Code not available.
    """
    from ck3lens.unified_tools import ck3_vscode_impl
    
    trace = _get_trace()
    
    return ck3_vscode_impl(
        command=command,
        path=path,
        severity=severity,
        source=source,
        limit=limit,
        trace=trace,
    )


# ============================================================================
# CK3 Repair Tool (Launcher Registry, Cache)
# ============================================================================

@mcp.tool()
def ck3_repair(
    command: Literal["query", "diagnose_launcher", "repair_registry", "delete_cache", "backup_launcher", "migrate_paths"] = "query",
    # For query - get status of repair targets
    target: Literal["all", "launcher", "cache", "dlc_load"] | None = None,
    # For repair_registry / delete_cache
    dry_run: bool = True,
    # For backup
    backup_name: str | None = None,
) -> dict:
    """
    Repair CK3 launcher registry and cache issues.
    
    ?? MODE: ck3lens only. Not available in ck3raven-dev mode.
    
    SCOPE: Launcher domain operations only.
    - ~/.ck3raven/ directory management
    - CK3 launcher registry analysis (read-only by default)
    - Cache cleanup
    
    Commands:
    
    command=query             ? Get status of repair targets (launcher registry, cache, etc.)
    command=diagnose_launcher ? Analyze launcher database for issues
    command=repair_registry   ? Fix launcher registry entries (requires dry_run=False)
    command=delete_cache      ? Clear ck3raven cache files (requires dry_run=False)
    command=backup_launcher   ? Create backup of launcher database before repair
    command=migrate_paths     ? Migrate playset paths to current user profile
    
    Args:
        command: Action to perform
        target: What to query ("all", "launcher", "cache", "dlc_load")
        dry_run: If True (default), only show what would be done
        backup_name: Optional name for backup file
    
    Returns:
        Dict with repair status/results
    
    WARNINGS:
    - repair_registry can modify the CK3 launcher database
    - Always run diagnose_launcher first to understand issues
    - backup_launcher before any repair operations
    - Cache deletion is reversible (ck3raven will rebuild)
    """
    import shutil
    from pathlib import Path
    from datetime import datetime
    
    trace = _get_trace()
    session = _get_session()
    
    ck3raven_dir = Path.home() / ".ck3raven"
    
    # Launcher database location (CK3 stores this in Paradox settings)
    launcher_db_candidates = [
        Path.home() / "AppData" / "Roaming" / "Paradox Interactive" / "launcher-v2_state" / "launcher-v2.sqlite",
        Path.home() / ".local" / "share" / "Paradox Interactive" / "launcher-v2_state" / "launcher-v2.sqlite",  # Linux
        Path.home() / "Library" / "Application Support" / "Paradox Interactive" / "launcher-v2_state" / "launcher-v2.sqlite",  # macOS
    ]
    
    launcher_db = None
    for candidate in launcher_db_candidates:
        if candidate.exists():
            launcher_db = candidate
            break
    
    if command == "query":
        # Return status of repair targets
        cache_files = list(ck3raven_dir.glob("*.cache")) if ck3raven_dir.exists() else []
        wip_files = list((ck3raven_dir / "wip").glob("**/*")) if (ck3raven_dir / "wip").exists() else []
        
        status = {
            "ck3raven_dir": str(ck3raven_dir),
            "ck3raven_exists": ck3raven_dir.exists(),
            "db_path": str(session.db_path) if session.db_path else None,
            "db_exists": session.db_path.exists() if session.db_path else False,
            "launcher_db": str(launcher_db) if launcher_db else None,
            "launcher_db_exists": launcher_db is not None,
            "cache_files": len(cache_files),
            "wip_files": len(wip_files),
            "repair_targets": {
                "cache": {
                    "files": len(cache_files),
                    "path": str(ck3raven_dir),
                    # NO permission oracles - enforcement decides at execution time
                },
                "wip": {
                    "files": len(wip_files),
                    "path": str(ck3raven_dir / "wip"),
                    # NO permission oracles - enforcement decides at execution time
                },
                "launcher": {
                    "path": str(launcher_db) if launcher_db else None,
                    "exists": launcher_db is not None,
                    "requires_backup": True,
                },
            },
        }
        
        if target == "launcher" or target == "all":
            if launcher_db:
                status["launcher_details"] = _diagnose_launcher_db(launcher_db)
        
        trace.log("ck3lens.repair", {"command": "query", "target": target}, {"success": True})
        return status
    
    elif command == "diagnose_launcher":
        # Analyze launcher database for issues
        if not launcher_db:
            return {"error": "CK3 launcher database not found", "checked_paths": [str(p) for p in launcher_db_candidates]}
        
        diagnosis = _diagnose_launcher_db(launcher_db)
        
        trace.log("ck3lens.repair", {"command": "diagnose_launcher"}, {"issues_found": diagnosis.get("issues_count", 0)})
        return diagnosis
    
    elif command == "backup_launcher":
        # Create backup of launcher database
        if not launcher_db:
            return {"error": "CK3 launcher database not found"}
        
        backups_dir = ck3raven_dir / "launcher_backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = backup_name or f"launcher-v2_{timestamp}"
        backup_path = backups_dir / f"{name}.sqlite"
        
        shutil.copy2(launcher_db, backup_path)
        
        trace.log("ck3lens.repair", {"command": "backup_launcher"}, {"backup_path": str(backup_path)})
        return {
            "success": True,
            "backup_path": str(backup_path),
            "original_path": str(launcher_db),
            "backup_size": backup_path.stat().st_size,
        }
    
    elif command == "repair_registry":
        # Repair launcher registry (requires token in strict mode)
        if not launcher_db:
            return {"error": "CK3 launcher database not found"}
        
        if dry_run:
            return {
                "dry_run": True,
                "message": "Would repair launcher registry. Set dry_run=False to proceed.",
                "recommendation": "Run backup_launcher first, then diagnose_launcher to see issues.",
            }
        
        # For now, return a placeholder - actual repair logic requires careful implementation
        return {
            "error": "Launcher repair not yet implemented",
            "reason": "Launcher database modifications require careful testing to avoid data loss",
            "workaround": "Use the CK3 launcher UI to reset settings, or delete ~/.ck3raven/ck3raven.db to force rebuild",
        }
    
    elif command == "delete_cache":
        # Delete ck3raven cache files
        cache_dir = ck3raven_dir
        wip_dir = ck3raven_dir / "wip"
        
        if dry_run:
            cache_files = list(cache_dir.glob("*.cache")) if cache_dir.exists() else []
            wip_files = list(wip_dir.rglob("*")) if wip_dir.exists() else []
            
            return {
                "dry_run": True,
                "would_delete": {
                    "cache_files": [str(f) for f in cache_files[:10]],  # First 10
                    "cache_count": len(cache_files),
                    "wip_files": [str(f) for f in wip_files[:10]],
                    "wip_count": len(wip_files),
                },
                "message": "Set dry_run=False to delete these files",
            }
        
        deleted = {"cache": 0, "wip": 0}
        
        # Delete cache files
        for cache_file in cache_dir.glob("*.cache"):
            try:
                cache_file.unlink()
                deleted["cache"] += 1
            except Exception as e:
                pass
        
        # Delete WIP directory contents (but keep directory)
        if wip_dir.exists():
            for item in wip_dir.rglob("*"):
                if item.is_file():
                    try:
                        item.unlink()
                        deleted["wip"] += 1
                    except Exception:
                        pass
        
        trace.log("ck3lens.repair", {"command": "delete_cache", "dry_run": False}, deleted)
        return {
            "success": True,
            "deleted": deleted,
            "message": "Cache cleared. ck3raven will rebuild as needed.",
        }
    
    if command == "migrate_paths":
        # Migrate playset paths to current user profile
        from .ck3lens.path_migration import detect_path_mismatch, migrate_playset_paths
        
        # Get active playset data
        if not session.playset_name:
            return {"error": "No active playset. Use ck3_playset to switch to a playset first."}
        
        # Find the playset file
        playsets_dir = Path(__file__).parent.parent.parent / "playsets"
        playset_file = None
        playset_data = None
        
        # Try to find playset file by name match
        for f in playsets_dir.glob("*.json"):
            try:
                with open(f, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                    if data.get("name") == session.playset_name:
                        playset_file = f
                        playset_data = data
                        break
            except:
                continue
        
        if not playset_data:
            return {
                "error": f"Could not find playset file for '{session.playset_name}'",
                "hint": "Playset may be stored in database only, not a JSON file",
            }
        
        # At this point playset_file is guaranteed to be set (found in loop above)
        assert playset_file is not None
        
        # Detect path mismatch
        local_mods_folder = playset_data.get("local_mods_folder", "")
        mismatch = detect_path_mismatch(local_mods_folder)
        
        if not mismatch:
            # Check individual mod paths too
            mods = playset_data.get("mods", [])
            for mod in mods:
                disk_path = mod.get("disk_path", "")
                if disk_path:
                    mismatch = detect_path_mismatch(disk_path)
                    if mismatch:
                        break
        
        if not mismatch:
            return {
                "success": True,
                "message": "No path migration needed - paths already match current user profile",
                "local_mods_folder": local_mods_folder,
            }
        
        old_user, new_user = mismatch
        
        # Perform migration
        migrated_data, was_modified, migration_msg = migrate_playset_paths(playset_data)
        
        if not was_modified:
            return {
                "success": True,
                "message": "No changes needed",
            }
        
        if dry_run:
            return {
                "dry_run": True,
                "migration": {
                    "old_user": old_user,
                    "new_user": new_user,
                    "message": migration_msg,
                },
                "playset_file": str(playset_file),
                "message": "Set dry_run=False to save changes to playset file",
            }
        
        # Save migrated playset
        try:
            with open(playset_file, 'w', encoding='utf-8') as fp:
                json.dump(migrated_data, fp, indent=2, ensure_ascii=False)
            
            # Reload the playset
            _load_playset_from_json(playset_file)
            
            trace.log("ck3lens.repair", {"command": "migrate_paths", "dry_run": False}, {
                "old_user": old_user,
                "new_user": new_user,
                "file": str(playset_file),
            })
            
            return {
                "success": True,
                "migration": {
                    "old_user": old_user,
                    "new_user": new_user,
                    "message": migration_msg,
                },
                "playset_file": str(playset_file),
                "message": "Paths migrated and playset reloaded",
            }
        except Exception as e:
            return {"error": f"Failed to save migrated playset: {e}"}
    
    return {"error": f"Unknown command: {command}"}


def _diagnose_launcher_db(launcher_db: Path) -> dict:
    """
    Analyze CK3 launcher database for issues.
    
    Returns diagnosis report with issues found.
    """
    import sqlite3
    
    try:
        conn = sqlite3.connect(launcher_db)
        conn.row_factory = sqlite3.Row
        
        result = {
            "path": str(launcher_db),
            "size_bytes": launcher_db.stat().st_size,
            "tables": [],
            "mods_registered": 0,
            "playsets": 0,
            "issues": [],
            "issues_count": 0,
        }
        
        # Get tables
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        result["tables"] = [t[0] for t in tables]
        
        # Count mods
        try:
            mods = conn.execute("SELECT COUNT(*) FROM mods").fetchone()
            result["mods_registered"] = mods[0] if mods else 0
        except:
            result["issues"].append("Cannot read mods table")
        
        # Count playsets
        try:
            playsets = conn.execute("SELECT COUNT(*) FROM playsets").fetchone()
            result["playsets"] = playsets[0] if playsets else 0
        except:
            result["issues"].append("Cannot read playsets table")
        
        # Check for orphaned mod references
        try:
            orphans = conn.execute("""
                SELECT pm.mod_id FROM playsets_mods pm 
                LEFT JOIN mods m ON pm.mod_id = m.id 
                WHERE m.id IS NULL
            """).fetchall()
            if orphans:
                result["issues"].append(f"Found {len(orphans)} orphaned mod references in playsets")
        except:
            pass
        
        # Check for mods with missing paths
        try:
            missing_paths = conn.execute("""
                SELECT display_name, steam_id FROM mods 
                WHERE path IS NULL OR path = ''
            """).fetchall()
            if missing_paths:
                result["issues"].append(f"Found {len(missing_paths)} mods with missing paths")
        except:
            pass
        
        result["issues_count"] = len(result["issues"])
        conn.close()
        
        return result
        
    except Exception as e:
        return {"error": f"Failed to analyze launcher database: {e}"}


# ============================================================================
# Work Contract Management V1 (CANONICAL CONTRACT SYSTEM)
# ============================================================================
# Schema: Contract V1 (geographic-only authorization)
# Capability Matrix: policy/capability_matrix.py (standalone truth table)
# Contract Storage: policy/contract_v1.py
# 
# BANNED: canonical_domains, semantic domains (active_local_mods, etc.)
# REQUIRED: root_category (one per contract)
# ============================================================================

@mcp.tool()
def ck3_contract(
    command: Literal["open", "close", "cancel", "status", "list", "flush", "archive_legacy"] = "status",
    # For open - REQUIRED
    intent: str | None = None,
    root_category: str | None = None,
    # For open - REQUIRED in ck3lens mode
    # For open - OPTIONAL
    operations: list[str] | None = None,
    targets: list[dict] | None = None,
    work_declaration: dict | None = None,
    expires_hours: float = 8.0,
    # For close/cancel
    contract_id: str | None = None,
    closure_commit: str | None = None,
    cancel_reason: str | None = None,
    # For list
    status_filter: str | None = None,
    include_archived: bool = False,
) -> dict:
    """
    Manage work contracts (Contract V1 schema).
    
    Contract V1 uses geographic-only authorization via the capability matrix.
    Each contract has exactly ONE root_category (geographic scope).
    
    Commands:
    
    command=open           ? Open new contract (intent, root_category required)
    command=close          ? Close contract after work complete
    command=cancel         ? Cancel contract without completing
    command=status         ? Get current active contract status
    command=list           ? List contracts
    command=flush          ? Archive old contracts from previous days
    command=archive_legacy ? Move pre-v1 contracts to legacy folder
    
    Args:
        command: Action to perform
        intent: Description of work to be done (for open)
        root_category: Geographic scope (ONE of: ROOT_REPO, ROOT_USER_DOCS, ROOT_WIP,
            ROOT_STEAM, ROOT_GAME, ROOT_UTILITIES, ROOT_LAUNCHER)
        operations: List of operations (READ, WRITE, DELETE, etc.)
        targets: List of target dicts with target_type, path, description
        work_declaration: Dict with work_summary, work_plan (3-15 items), out_of_scope
        expires_hours: Hours until expiry (default 8)
        contract_id: Contract ID for close/cancel (uses active if not specified)
        closure_commit: Git commit SHA for close
        cancel_reason: Reason for cancellation
        status_filter: Filter list by status
        include_archived: Include archived in list
    
    Returns:
        Contract info or operation result
    
    Examples:
        # ck3lens mode 
        ck3_contract(command="open", intent="Fix trait conflicts", 
                     root_category="ROOT_USER_DOCS",)
        
        # ck3raven-dev mode 
        ck3_contract(command="open", intent="Refactor parser", root_category="ROOT_REPO")
    """
    from ck3lens.policy.contract_v1 import (
        open_contract, close_contract, cancel_contract,
        get_active_contract, list_contracts, archive_legacy_contracts,
        ContractV1,
    )
    from ck3lens.policy.capability_matrix import (
        RootCategory, Operation, AgentMode, is_authorized, validate_operations,
    )
    from ck3lens.agent_mode import get_agent_mode
    
    trace = _get_trace()
    agent_mode = get_agent_mode()
    
    # Null mode check - agent must initialize mode first
    if agent_mode is None and command == "open":
        return {
            "error": "Agent mode not initialized",
            "guidance": "Call ck3_get_mode_instructions() first to initialize.",
            "modes": {
                "ck3lens": "CK3 modding - search database, edit mods, resolve conflicts",
                "ck3raven-dev": "Infrastructure development - modify ck3raven source code",
            },
        }
    
    if command == "open":
        # =====================================================================
        # CONTRACT V1: STRICT VALIDATION
        # =====================================================================
        if not intent:
            return {"error": "intent required for open command"}
        if not root_category:
            return {
                "error": "root_category required for open command",
                "valid_root_categories": [r.value for r in RootCategory],
            }
        
        # Validate root_category is a valid enum value
        try:
            root_cat = RootCategory(root_category)
        except ValueError:
            return {
                "error": f"Invalid root_category: {root_category}",
                "valid_root_categories": [r.value for r in RootCategory],
            }
        
        # Convert agent mode string to enum
        mode_enum = AgentMode.CK3LENS if agent_mode == "ck3lens" else AgentMode.CK3RAVEN_DEV
        
        # Validate operations against capability matrix
        ops_list = operations or ["READ", "WRITE"]
        try:
            op_enums = [Operation(op) for op in ops_list]
        except ValueError as e:
            return {
                "error": f"Invalid operation: {e}",
                "valid_operations": [o.value for o in Operation],
            }
        
        # Check authorization via capability matrix (SOLE SOURCE OF TRUTH)
        valid, denied = validate_operations(mode_enum, root_cat, ops_list)
        if not valid:
            return {
                "error": "Operations not authorized by capability matrix",
                "denied_operations": denied,
                "root_category": root_category,
                "mode": agent_mode,
            }
        
        try:
            import json
            from pathlib import Path
            from datetime import datetime
            import uuid
            
            # Call open_contract (no debug logging in hot path)
            contract = open_contract(
                mode=mode_enum,
                root_category=root_category,
                intent=intent,
                operations=ops_list,
                targets=targets or [],
                work_declaration=work_declaration or {},
                expires_hours=expires_hours,
            )
            
            # Trace log (minimal, no large payloads)
            trace.log("ck3lens.contract.open", {
                "intent": intent[:100] if intent else "",
                "root_category": root_category,
            }, {"contract_id": contract.contract_id})
            
            # =========================================================
            # MINIMAL RESPONSE - transport-safe, strictly serializable
            # =========================================================
            
            # Convert expires_at to ISO string if datetime
            # Note: ContractV1.expires_at is Optional[str], but handle datetime for robustness
            if contract.expires_at is None:
                expires_str = ""
            elif isinstance(contract.expires_at, str):
                expires_str = contract.expires_at
            else:
                # In case it's a datetime object (shouldn't happen with current schema)
                expires_str = contract.expires_at.isoformat()  # type: ignore[union-attr]
            
            # Convert enums to strings (RootCategory | str, Operation | str)
            if isinstance(contract.root_category, str):
                root_cat_str = contract.root_category
            else:
                root_cat_str = contract.root_category.value
            
            ops_list_str = [
                op if isinstance(op, str) else op.value
                for op in contract.operations
            ]
            
            # Build minimal response
            result = {
                "success": True,
                "contract_id": contract.contract_id,
                "expires_at": expires_str,
                "mode": agent_mode,
                "root_category": root_cat_str,
                "operations": ops_list_str,
            }
            
            # =========================================================
            # TRANSPORT SAFETY GUARDS
            # =========================================================
            
            # Guard 1: Verify JSON-serializable
            try:
                serialized = json.dumps(result)
            except (TypeError, ValueError) as ser_err:
                error_id = f"ser-{uuid.uuid4().hex[:8]}"
                # Log to file for debugging
                debug_log = Path.home() / ".ck3raven" / "contract_debug.log"
                with open(debug_log, "a") as f:
                    f.write(f"\n=== {datetime.now().isoformat()} ===\n")
                    f.write(f"SERIALIZATION_ERROR: {error_id}\n")
                    f.write(f"  Error: {ser_err}\n")
                    f.write(f"  Result keys: {list(result.keys())}\n")
                return {
                    "success": False,
                    "code": "CONTRACT_OPEN_SERIALIZATION_ERROR",
                    "message": f"Response not JSON-serializable. error_id={error_id}",
                    "error_id": error_id,
                }
            
            # Guard 2: Response size cap (32KB)
            MAX_RESPONSE_BYTES = 32 * 1024
            if len(serialized) > MAX_RESPONSE_BYTES:
                error_id = f"size-{uuid.uuid4().hex[:8]}"
                debug_log = Path.home() / ".ck3raven" / "contract_debug.log"
                with open(debug_log, "a") as f:
                    f.write(f"\n=== {datetime.now().isoformat()} ===\n")
                    f.write(f"RESPONSE_TOO_LARGE: {error_id}\n")
                    f.write(f"  Size: {len(serialized)} bytes\n")
                return {
                    "success": False,
                    "code": "CONTRACT_RESPONSE_TOO_LARGE",
                    "message": f"Response exceeds {MAX_RESPONSE_BYTES} bytes. error_id={error_id}",
                    "error_id": error_id,
                }
            
            return result
            
        except Exception as e:
            import traceback
            import uuid
            from pathlib import Path
            from datetime import datetime
            
            error_id = f"err-{uuid.uuid4().hex[:8]}"
            debug_log = Path.home() / ".ck3raven" / "contract_debug.log"
            with open(debug_log, "a") as f:
                f.write(f"\n=== {datetime.now().isoformat()} ===\n")
                f.write(f"CONTRACT_OPEN_ERROR: {error_id}\n")
                f.write(f"  Exception: {e}\n")
                f.write(traceback.format_exc())
            return {
                "success": False,
                "code": "CONTRACT_OPEN_ERROR",
                "message": f"Internal error. Logged as {error_id}",
                "error_id": error_id,
            }
    
    elif command == "close":
        target_id = contract_id
        if not target_id:
            active = get_active_contract()
            if not active:
                return {"error": "No active contract to close"}
            target_id = active.contract_id
        
        try:
            contract = close_contract(target_id, closure_commit)
            
            trace.log("ck3lens.contract.close", {
                "contract_id": target_id,
            }, {"closure_commit": closure_commit})
            
            # Serialize to transport-safe types
            return {
                "success": True,
                "contract_id": contract.contract_id,
                "closed_at": contract.closed_at if isinstance(contract.closed_at, str) else (contract.closed_at.isoformat() if contract.closed_at else None),
                "status": contract.status if isinstance(contract.status, str) else str(contract.status),
            }
        except Exception as e:
            return {"error": str(e)}
    
    elif command == "cancel":
        target_id = contract_id
        if not target_id:
            active = get_active_contract()
            if not active:
                return {"error": "No active contract to cancel"}
            target_id = active.contract_id
        
        try:
            contract = cancel_contract(target_id, cancel_reason or "")
            
            trace.log("ck3lens.contract.cancel", {
                "contract_id": target_id,
                "reason": cancel_reason,
            }, {})
            
            return {
                "success": True,
                "contract_id": contract.contract_id,
                "status": "cancelled",
            }
        except Exception as e:
            return {"error": str(e)}
    
    elif command == "status":
        active = get_active_contract()
        
        if active:
            # Serialize enums/datetime to transport-safe strings
            root_cat_str = active.root_category if isinstance(active.root_category, str) else active.root_category.value
            ops_list_str = [
                op if isinstance(op, str) else op.value
                for op in active.operations
            ]
            expires_str = active.expires_at if isinstance(active.expires_at, str) else (active.expires_at.isoformat() if active.expires_at else None)
            created_str = active.created_at if isinstance(active.created_at, str) else (active.created_at.isoformat() if active.created_at else None)
            
            return {
                "has_active_contract": True,
                "contract_id": active.contract_id,
                "intent": active.intent,
                "root_category": root_cat_str,
                "operations": ops_list_str,
                "expires_at": expires_str,
                "created_at": created_str,
                "schema_version": "v1",
            }
        else:
            return {
                "has_active_contract": False,
                "message": "No active contract. Use command=open to start work.",
            }
    
    elif command == "list":
        contracts = list_contracts(
            status=status_filter,
            include_archived=include_archived,
        )
        
        # Serialize each contract to transport-safe types
        def serialize_contract(c):
            root_cat_str = c.root_category if isinstance(c.root_category, str) else c.root_category.value
            status_str = c.status if isinstance(c.status, str) else str(c.status)
            created_str = c.created_at if isinstance(c.created_at, str) else (c.created_at.isoformat() if c.created_at else None)
            closed_str = c.closed_at if isinstance(c.closed_at, str) else (c.closed_at.isoformat() if c.closed_at else None)
            return {
                "contract_id": c.contract_id,
                "intent": c.intent,
                "status": status_str,
                "root_category": root_cat_str,
                "created_at": created_str,
                "closed_at": closed_str,
            }
        
        return {
            "count": len(contracts),
            "contracts": [serialize_contract(c) for c in contracts],
        }
    
    elif command == "flush":
        # Archive contracts from previous days
        import os
        from pathlib import Path
        from datetime import datetime
        
        contracts_dir = Path.home() / ".ck3raven" / "contracts"
        if not contracts_dir.exists():
            return {"success": True, "archived": 0}
        
        today = datetime.now().strftime("%Y-%m-%d")
        archive_dir = contracts_dir / "archive" / today
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        archived = 0
        for f in contracts_dir.glob("wcp-*.json"):
            # Only archive if not from today
            if today not in f.name:
                import shutil
                shutil.move(str(f), str(archive_dir / f.name))
                archived += 1
        
        trace.log("ck3lens.contract.flush", {}, {"archived": archived})
        
        return {
            "success": True,
            "archived": archived,
            "message": f"Archived {archived} contracts from previous days",
        }
    
    elif command == "archive_legacy":
        # Move all pre-v1 contracts to legacy folder
        archived = archive_legacy_contracts()
        
        trace.log("ck3lens.contract.archive_legacy", {}, {"archived": archived})
        
        return {
            "success": True,
            "archived": archived,
            "message": f"Archived {archived} legacy pre-v1 contracts",
        }
    
    return {"error": f"Unknown command: {command}"}


# ============================================================================
# Command Execution with Policy Enforcement (CLW)
# ============================================================================

@mcp.tool()
def ck3_exec(
    command: str,
    working_dir: str | None = None,
    target_paths: list[str] | None = None,
    token_id: str | None = None,
    dry_run: bool = False,
    timeout: int = 30,
) -> dict:
    """
    Execute a shell command with CLW policy enforcement.
    
    Mode-aware behavior:
    - ck3lens mode: Limited to CK3/mod-related commands within playset scope
    - ck3raven-dev mode: Broader access for infrastructure work (USE THIS instead of run_in_terminal)
    
    This is the ONLY safe way for agents to run shell commands.
    All commands are evaluated against the policy engine:
    
    - Safe commands (cat, git status, etc.) ? Allowed automatically
    - Risky commands (rm *.py, git push) ? Require approval token
    - Blocked commands (rm -rf /) ? Always denied
    
    If a command requires a token, use ck3_token to request one first,
    then pass the token_id here.
    
    Args:
        command: Shell command to execute
        working_dir: Working directory (defaults to ck3raven root)
        target_paths: Files/dirs being affected (helps scope validation)
        token_id: Approval token ID (required for risky commands)
        dry_run: If True, only check policy without executing
        timeout: Max seconds to wait for command (default 30, max 300)
    
    Returns:
        {
            "allowed": bool,
            "executed": bool,  # False if dry_run or denied
            "output": str,     # Command output (if executed)
            "exit_code": int,  # Exit code (if executed)
            "policy": {
                "decision": "ALLOW" | "DENY" | "REQUIRE_TOKEN",
                "reason": str,
                "required_token_type": str | None,
                "category": str,
            }
        }
    
    Examples:
        ck3_exec("git status")  # Safe - allowed
        ck3_exec("cat file.txt")  # Safe - allowed
        ck3_exec("rm test.py", token_id="tok-abc123")  # Risky - needs token
        ck3_exec("git push --force", dry_run=True)  # Check if would be allowed
    """
    # ==========================================================================
    # CANONICAL IMPORTS: All from enforcement.py (clw.py archived Dec 2025)
    # ==========================================================================
    from ck3lens.policy.enforcement import (
        enforce_and_log, EnforcementRequest, 
        OperationType, Decision,
        classify_command, CommandCategory,  # Shell command classification
    )
    from ck3lens.policy.audit import get_audit_logger
    from ck3lens.policy.contract_v1 import get_active_contract
    from ck3lens.world_adapter import normalize_path_input
    import subprocess
    
    trace = _get_trace()
    
    # ==========================================================================
    # CANONICAL PATH NORMALIZATION for working_dir and target_paths
    # Use normalize_path_input() for all path resolution.
    # NOTE: WorldAdapter is OPTIONAL - don't fail if DB unavailable
    # ==========================================================================
    
    try:
        world = _get_world()
    except Exception:
        # DB unavailable or not initialized - continue without path visibility checks
        # This allows ck3_exec to work even when DB is locked or missing
        world = None
    
    if world is not None:
        # Check working directory visibility
        if working_dir:
            resolution = normalize_path_input(world, path=working_dir)
            if not resolution.found:
                return {
                    "allowed": False,
                    "executed": False,
                    "output": None,
                    "exit_code": None,
                    "policy": {"decision": "PATH_NOT_FOUND", "reason": f"Working directory not found"},
                    "error": resolution.error_message or f"Path not found: {working_dir}",
                }
        
        # Check target paths visibility
        if target_paths:
            for target in target_paths:
                resolution = normalize_path_input(world, path=target)
                if not resolution.found:
                    return {
                        "allowed": False,
                        "executed": False,
                        "output": None,
                        "exit_code": None,
                        "policy": {"decision": "PATH_NOT_FOUND", "reason": f"Target path not found"},
                        "error": resolution.error_message or f"Path not found: {target}",
                    }
    
    # Get active contract
    active_contract = get_active_contract()
    contract_id = active_contract.contract_id if active_contract else None
    
    # Get agent mode for mode-aware policy
    from ck3lens.agent_mode import get_agent_mode
    mode = get_agent_mode()
    
    # ==========================================================================
    # WIP SCRIPT DETECTION AND SANDBOXED EXECUTION
    # - ck3lens mode: Sandboxed execution with Token B (user approval)
    # - ck3raven-dev mode: Enforcement gate (existing logic)
    # ==========================================================================
    wip_script_info = _detect_wip_script(command, working_dir or str(Path(__file__).parent.parent.parent))
    
    if wip_script_info and mode == "ck3lens":
        # =======================================================================
        # CK3LENS MODE: SANDBOXED WIP SCRIPT EXECUTION
        # Per Canonical Initialization #9: Scripts must be sandboxed
        # =======================================================================
        from ck3lens.policy.tokens import validate_script_token
        from ck3lens.tools.script_sandbox import run_script_sandboxed
        
        script_path = Path(wip_script_info["script_path"])
        
        # Token B (user approval) required for script execution in ck3lens
        if not token_id:
            return {
                "allowed": False,
                "executed": False,
                "output": None,
                "exit_code": None,
                "policy": {
                    "decision": "REQUIRE_TOKEN",
                    "reason": "WIP script execution in ck3lens mode requires SCRIPT_EXECUTE token (user approval)",
                    "required_token_type": "SCRIPT_EXECUTE",
                    "category": "WIP_SCRIPT_SANDBOXED",
                },
                "error": "Script execution requires user approval",
                "hint": "Use ck3_token(command='request', token_type='SCRIPT_EXECUTE', reason='...') to request approval",
            }
        
        # Validate token with script hash binding
        current_hash = wip_script_info.get("script_hash", "UNKNOWN")
        token_valid, token_msg = validate_script_token(token_id, current_hash)
        
        if not token_valid:
            return {
                "allowed": False,
                "executed": False,
                "output": None,
                "exit_code": None,
                "policy": {
                    "decision": "DENY",
                    "reason": f"Token invalid: {token_msg}",
                    "required_token_type": "SCRIPT_EXECUTE",
                    "category": "WIP_SCRIPT_SANDBOXED",
                },
                "error": f"Token validation failed: {token_msg}",
            }
        
        # Get sandbox paths
        from ck3lens.policy.wip_workspace import get_wip_workspace_path
        from ck3lens.policy.types import AgentMode

        wip_path = get_wip_workspace_path(AgentMode.CK3LENS)

        # Get session for WorldAdapter access
        session = _get_session()
        
        # Dry run returns early
        if dry_run:
            return {
                "allowed": True,
                "executed": False,
                "output": None,
                "exit_code": None,
                "policy": {
                    "decision": "ALLOW",
                    "reason": "Sandboxed script execution would be allowed",
                    "category": "WIP_SCRIPT_SANDBOXED",
                },
                "message": "Dry run - script would be executed in LensWorld sandbox",
                "sandbox_config": {
                    "wip_path": str(wip_path),
                },
            }

        # Execute in sandbox (delegates to WorldAdapter.is_visible + enforcement.gate_write)
        trace.log("ck3lens.exec.sandbox_start", {
            "script_path": str(script_path),
            "script_hash": wip_script_info.get("script_hash", "")[:16],
            "token_id": token_id,
        }, {})

        sandbox_result = run_script_sandboxed(
            script_path=script_path,
            session=session,
            wip_path=wip_path,
            contract_id=None,  # TODO: pass active contract if available
            token_id=token_id,
        )

        return {
            "allowed": True,
            "executed": True,
            "output": sandbox_result.get("output", ""),
            "exit_code": 0 if sandbox_result["success"] else 1,
            "policy": {
                "decision": "ALLOW",
                "reason": "Executed in LensWorld sandbox",
                "category": "WIP_SCRIPT_SANDBOXED",
            },
            "sandbox": {
                "success": sandbox_result["success"],
                "error": sandbox_result.get("error"),
                "audit": sandbox_result.get("audit", {}),
            },
        }
    
    elif wip_script_info and mode == "ck3raven-dev":
        # =======================================================================
        # CK3RAVEN-DEV MODE: Enforcement gate (existing logic)
        # =======================================================================
        from ck3lens.policy.enforcement import (
            enforce_and_log, EnforcementRequest, OperationType as EnfOp, Decision as EnfDecision
        )
        
        enforcement_request = EnforcementRequest(
            operation=EnfOp.WIP_SCRIPT_RUN,
            mode=mode or "unknown",
            tool_name="ck3_exec",
            command=command,
            script_path=wip_script_info["script_path"],
            script_hash=wip_script_info["script_hash"],
            wip_intent=wip_script_info.get("wip_intent"),  # May be None - will fail enforcement
            contract_id=contract_id,
            token_id=token_id,
        )
        
        enf_result = enforce_and_log(enforcement_request, trace, session_id="mcp_server")
        
        if enf_result.decision == EnfDecision.ALLOW:
            # Proceed to execution (below)
            pass
        elif enf_result.decision == EnfDecision.REQUIRE_TOKEN:
            return {
                "allowed": False,
                "executed": False,
                "output": None,
                "exit_code": None,
                "policy": {
                    "decision": "REQUIRE_TOKEN",
                    "reason": enf_result.reason,
                    "required_token_type": enf_result.required_token_type,
                    "category": "WIP_SCRIPT",
                },
                "error": f"Token required: {enf_result.required_token_type}",
                "hint": f"Use ck3_token to request a {enf_result.required_token_type} token",
            }
        elif enf_result.decision == EnfDecision.REQUIRE_CONTRACT:
            return {
                "allowed": False,
                "executed": False,
                "output": None,
                "exit_code": None,
                "policy": {
                    "decision": "REQUIRE_CONTRACT",
                    "reason": enf_result.reason,
                    "required_token_type": None,
                    "category": "WIP_SCRIPT",
                },
                "error": "Contract required for WIP script execution",
                "hint": "Use ck3_contract to open a work contract first",
            }
        else:
            # DENY or other
            return {
                "allowed": False,
                "executed": False,
                "output": None,
                "exit_code": None,
                "policy": {
                    "decision": enf_result.decision.name,
                    "reason": enf_result.reason,
                    "required_token_type": enf_result.required_token_type,
                    "category": "WIP_SCRIPT",
                },
                "error": enf_result.reason,
            }
    
    # ==========================================================================
    # CANONICAL ENFORCEMENT: Route through enforcement.py for non-WIP commands
    # 
    # Pattern: classify ? map to OperationType ? enforce_and_log ? execute
    # ==========================================================================
    
    # Step 1: Classify the command (structural classification, not policy)
    category = classify_command(command)
    
    # Step 2: Map CommandCategory to OperationType for enforcement.py
    def _category_to_operation(cat: CommandCategory) -> OperationType:
        """Map command category to enforcement OperationType."""
        if cat in (CommandCategory.READ_ONLY, CommandCategory.GIT_SAFE):
            return OperationType.SHELL_SAFE
        elif cat in (CommandCategory.WRITE_IN_SCOPE, CommandCategory.WRITE_OUT_OF_SCOPE, 
                     CommandCategory.GIT_MODIFY, CommandCategory.NETWORK, CommandCategory.SYSTEM):
            return OperationType.SHELL_WRITE
        elif cat in (CommandCategory.DESTRUCTIVE, CommandCategory.GIT_DANGEROUS, CommandCategory.BLOCKED):
            return OperationType.SHELL_DESTRUCTIVE
        else:
            return OperationType.SHELL_SAFE  # Default to safe for unknown
    
    op_type = _category_to_operation(category)
    
    # Step 3: Build EnforcementRequest for enforcement.py
    enforcement_request = EnforcementRequest(
        operation=op_type,
        mode=mode or "unknown",
        tool_name="ck3_exec",
        command=command,
        target_path=target_paths[0] if target_paths else None,  # Primary target for mode checks
        contract_id=contract_id,
        token_id=token_id,
    )
    
    # Step 4: Call enforcement.py - THE single policy gate
    result = enforce_and_log(enforcement_request, trace, session_id="mcp_server")
    
    policy_info = {
        "decision": result.decision.name,
        "reason": result.reason,
        "required_token_type": result.required_token_type,
        "category": category.name,
    }

    # Check decision - canonical enforcement result handling
    if result.decision == Decision.DENY:
        return {
            "allowed": False,
            "executed": False,
            "output": None,
            "exit_code": None,
            "policy": policy_info,
            "error": result.reason,
        }
    
    if result.decision == Decision.REQUIRE_CONTRACT:
        return {
            "allowed": False,
            "executed": False,
            "output": None,
            "exit_code": None,
            "policy": policy_info,
            "error": "Contract required for this operation",
            "hint": "Use ck3_contract(command='open', ...) to open a work contract first",
        }
    
    if result.decision == Decision.REQUIRE_TOKEN:
        return {
            "allowed": False,
            "executed": False,
            "output": None,
            "exit_code": None,
            "policy": policy_info,
            "error": f"Token required: {result.required_token_type}",
            "hint": f"Use ck3_token to request a {result.required_token_type} token",
        }
    
    # Allowed
    if dry_run:
        return {
            "allowed": True,
            "executed": False,
            "output": None,
            "exit_code": None,
            "policy": policy_info,
            "message": "Dry run - command would be allowed",
        }
    
    # Clamp timeout to max 300 seconds (moved outside try block for exception handler access)
    actual_timeout = min(max(timeout, 1), 300)
    
    # Actually execute
    try:
        import platform
        
        # Environment variables to prevent git from hanging
        exec_env = os.environ.copy()
        exec_env["GIT_TERMINAL_PROMPT"] = "0"  # Disable credential prompts
        exec_env["GIT_PAGER"] = "cat"  # Disable pager for git commands
        exec_env["PAGER"] = "cat"  # Disable pager generally
        exec_env["GCM_INTERACTIVE"] = "never"  # Disable Git Credential Manager GUI
        exec_env["GIT_ASKPASS"] = ""  # Disable askpass
        exec_env["SSH_ASKPASS"] = ""  # Disable SSH askpass
        exec_env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"  # SSH non-interactive
        
        # On Windows, use PowerShell to support & and other PS syntax
        if platform.system() == "Windows":
            ps_command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
            proc = subprocess.run(
                ps_command,
                shell=False,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=actual_timeout,
                env=exec_env,
                stdin=subprocess.DEVNULL,  # Prevent any stdin reads
            )
        else:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=actual_timeout,
                env=exec_env,
            )
        
        return {
            "allowed": True,
            "executed": True,
            "output": proc.stdout + proc.stderr,
            "exit_code": proc.returncode,
            "policy": policy_info,
        }
    except subprocess.TimeoutExpired:
        return {
            "allowed": True,
            "executed": True,
            "output": f"Command timed out after {actual_timeout} seconds",
            "exit_code": -1,
            "policy": policy_info,
            "error": "timeout",
            "hint": f"Command exceeded timeout of {actual_timeout}s. Use timeout= parameter to increase (max 300s).",
        }
    except Exception as e:
        return {
            "allowed": True,
            "executed": False,
            "output": None,
            "exit_code": None,
            "policy": policy_info,
            "error": str(e),
        }


@mcp.tool()
def ck3_token(
    command: Literal["request", "list", "validate", "revoke"] = "list",
    # For request
    token_type: str | None = None,
    reason: str | None = None,
    path_patterns: list[str] | None = None,
    command_patterns: list[str] | None = None,
    ttl_minutes: int | None = None,
    # For validate/revoke
    token_id: str | None = None,
    capability: str | None = None,
    path: str | None = None,
) -> dict:
    """
    Manage approval tokens for risky operations.
    
    Mode-aware token types:
    - ck3lens mode: Tokens for mod file deletion, inactive mod access, git push
    - ck3raven-dev mode: Additional tokens for git rewrite, DB schema changes, force push
    
    Tokens are HMAC-signed, time-limited approvals for specific operations.
    Required for commands that would otherwise be blocked.
    
    Commands:
    
    command=request   ? Request a new approval token
    command=list      ? List active tokens
    command=validate  ? Check if a token is valid for an operation
    command=revoke    ? Revoke a token
    
    Token Types (see TOKEN_TYPES):
    - FS_DELETE_CODE: Delete .py/.txt files (30 min TTL)
    - FS_WRITE_OUTSIDE_CONTRACT: Write outside contract scope (60 min)
    - CMD_RUN_DESTRUCTIVE: Drop tables, etc. (15 min)
    - CMD_RUN_ARBITRARY: Curl|bash patterns (10 min)
    - GIT_PUSH: Push to remote (60 min)
    - GIT_FORCE_PUSH: Force push (10 min)
    - GIT_REWRITE_HISTORY: Rebase, reset (15 min)
    - DB_SCHEMA_MIGRATE: Schema changes (30 min)
    - DB_DELETE_DATA: Delete DB rows (15 min)
    - BYPASS_CONTRACT: Skip contract check (5 min)
    - BYPASS_POLICY: Skip policy check (5 min)
    
    Args:
        command: Action to perform
        token_type: Type of token to request (for request)
        reason: Why this token is needed (for request)
        path_patterns: Allowed paths (for request)
        command_patterns: Allowed commands (for request)
        ttl_minutes: Override TTL (for request)
        token_id: Token to validate/revoke
        capability: Capability to check (for validate)
        path: Path to check against (for validate)
    
    Returns:
        Token info or operation result
    """
    from ck3lens.policy.tokens import (
        issue_token, validate_token, list_tokens, revoke_token,
        TOKEN_TYPES, ApprovalToken,
    )
    from ck3lens.policy.contract_v1 import get_active_contract
    
    trace = _get_trace()
    
    if command == "request":
        if not token_type:
            return {
                "error": "token_type required",
                "valid_types": list(TOKEN_TYPES.keys()),
            }
        if not reason:
            return {"error": "reason required for token request"}
        
        if token_type not in TOKEN_TYPES:
            return {
                "error": f"Unknown token type: {token_type}",
                "valid_types": list(TOKEN_TYPES.keys()),
            }
        
        # Get contract for context
        active_contract = get_active_contract()
        contract_id = active_contract.contract_id if active_contract else None
        
        try:
            token = issue_token(
                token_type=token_type,
                capability=token_type,  # Use type as capability
                reason=reason,
                path_patterns=path_patterns,
                command_patterns=command_patterns,
                contract_id=contract_id,
                issued_by="agent",
                ttl_minutes=ttl_minutes,
            )
            
            trace.log("ck3lens.token.issue", {
                "token_type": token_type,
                "reason": reason,
            }, {"token_id": token.token_id})
            
            return {
                "success": True,
                "token_id": token.token_id,
                "token_type": token.token_type,
                "expires_at": token.expires_at,
                "path_patterns": token.path_patterns,
                "command_patterns": token.command_patterns,
                "message": "Token issued. Use token_id with ck3_exec for approved commands.",
            }
        except Exception as e:
            return {"error": str(e)}
    
    elif command == "list":
        tokens = list_tokens()
        
        return {
            "count": len(tokens),
            "tokens": [
                {
                    "token_id": t.token_id,
                    "token_type": t.token_type,
                    "capability": t.capability,
                    "expires_at": t.expires_at,
                    "consumed": t.consumed,
                    "reason": t.reason,
                }
                for t in tokens
            ],
        }
    
    elif command == "validate":
        if not token_id:
            return {"error": "token_id required for validate"}
        if not capability:
            return {"error": "capability required for validate"}
        
        valid, msg = validate_token(
            token_id=token_id,
            required_capability=capability,
            path=path,
        )
        
        return {
            "valid": valid,
            "message": msg,
            "token_id": token_id,
            "capability": capability,
        }
    
    elif command == "revoke":
        if not token_id:
            return {"error": "token_id required for revoke"}
        
        success = revoke_token(token_id)
        
        if success:
            trace.log("ck3lens.token.revoke", {
                "token_id": token_id,
            }, {})
            
            return {
                "success": True,
                "token_id": token_id,
                "message": "Token revoked",
            }
        else:
            return {
                "success": False,
                "error": f"Token not found: {token_id}",
            }
    
    return {"error": f"Unknown command: {command}"}


# ============================================================================
# Unified Search Tool
# ============================================================================

@mcp.tool()
def ck3_search(
    query: str,
    file_pattern: Optional[str] = None,
    game_folder: Optional[str] = None,
    symbol_type: Optional[str] = None,
    adjacency: Literal["auto", "strict", "fuzzy"] = "auto",
    limit: int = 25,
    definitions_only: bool = False,
    verbose: bool = False,
) -> dict:
    """
    Unified search across symbols, file content, and file paths.
    
    This is THE search tool - it searches EVERYTHING:
    1. Symbol definitions (traits, events, decisions, etc.)
    2. Symbol USAGES (where symbols are referenced - DEFAULT behavior)
    3. File content (grep-style text matches with line numbers)
    4. File paths (if query looks like a path or file_pattern provided)
    
    Query syntax for content search:
    - Space-separated words: AND search (all must appear in file)
    - "quoted phrase": Exact phrase search
    - Single word: Simple text search
    
    By default, shows BOTH definitions AND usages - critical for compatch work
    where you need to understand how something is used, not just where it's defined.
    
    Args:
        query: Search term(s). Space-separated = AND, "quotes" = exact phrase
        file_pattern: SQL LIKE pattern for file paths (e.g., "%traits%")
        game_folder: Limit to CK3 folder (e.g., "events", "common/traits", "common/on_action")
        symbol_type: Filter symbols by type (trait, event, decision, etc.)
        adjacency: Pattern expansion ("auto", "strict", "fuzzy")
        limit: Max results per category (default 25)
        definitions_only: If True, skip references (faster but less useful)
        verbose: More detail (all matches per file, snippets)
    
    Returns:
        {
            "query": str,
            "symbols": {definitions, references_by_mod},
            "content": {line-by-line matches},
            "files": {matching paths},
            "truncated": bool,  # True if results were limited
            "guidance": str     # Suggestions if truncated
        }
    
    Examples:
        ck3_search("brave")  # Find all uses of 'brave'
        ck3_search("melkite localization")  # Files with BOTH terms
        ck3_search("brave", game_folder="events")  # Only in events/
        ck3_search("brave", game_folder="common/traits")  # Only trait files
        ck3_search("has_trait", limit=100, verbose=True)  # More results
    """
    db = _get_db()
    trace = _get_trace()
    session = _get_session()
    world = _get_world()
    
    # Build file_pattern from game_folder if provided
    effective_file_pattern = file_pattern
    if game_folder:
        # Normalize folder path
        # Use canonical path normalization via WorldAdapter
        folder = world.normalize(game_folder)
        effective_file_pattern = f"{folder}/%"
    
    # Build source filter from mod_filter if provided
    
    # By default, include references (usages) - this is what compatch needs
    include_references = not definitions_only
    
    # Derive CVIDs from session.mods[] for DB filtering (canonical approach)
    cvids: frozenset[int] = frozenset(
        m.cvid for m in session.mods 
        if hasattr(m, 'cvid') and m.cvid is not None
    )
    
    result = db._unified_search_internal(
        query=query,
        file_pattern=effective_file_pattern,
        symbol_type=symbol_type,
        adjacency=adjacency,
        limit=limit,
        matches_per_file=5 if not verbose else 50,
        include_references=include_references,
        verbose=verbose,
        visible_cvids=cvids if cvids else None
    )
    
    # Check if results were truncated and add guidance
    refs_by_mod = result["symbols"].get("references_by_mod", {})
    total_refs = sum(len(v) for v in refs_by_mod.values())
    content_count = result["content"]["count"]
    
    truncated = (total_refs >= limit or content_count >= limit)
    guidance = None
    
    if truncated:
        guidance_parts = []
        if total_refs >= limit:
            guidance_parts.append(f"References truncated at {limit}.")
        if content_count >= limit:
            guidance_parts.append(f"Content matches truncated at {limit} files.")
        
        guidance_parts.append("To see more: increase limit (e.g., limit=100).")
        
        if not game_folder:
            guidance_parts.append("To narrow: use game_folder (e.g., 'events', 'common/traits').")
        
        guidance = " ".join(guidance_parts)
    
    result["truncated"] = truncated
    if guidance:
        result["guidance"] = guidance
    
    trace.log("ck3lens.search", {
        "query": query,
        "file_pattern": effective_file_pattern,
        "game_folder": game_folder,
        "symbol_type": symbol_type,
        "limit": limit,
        "definitions_only": definitions_only,
    }, {
        "symbols_count": result["symbols"]["count"],
        "references_count": total_refs,
        "content_count": content_count,
        "truncated": truncated
    })
    
    return result


# ============================================================================
# Symbol Tools - ARCHIVED January 2, 2026
# ============================================================================
# The following tools have been DELETED:
# - ck3_confirm_not_exists() → Functionality moved to ck3_search with exhaustive mode
# - ck3_qr_conflicts() → Use ck3_conflicts(command="symbols") when implemented
# - ck3_get_symbol_conflicts() → Use ck3_conflicts(command="symbols") when implemented
#
# The unified ck3_conflicts tool will replace all conflict detection functionality.
# ============================================================================

# ============================================================================
# Filesystem Wrapper Tools (Traceable)
# ============================================================================
# These tools wrap VS Code's built-in filesystem operations to make them
# traceable by the policy validator. Agents should use these instead of
# read_file, list_dir, grep_search directly when working in ck3lens mode.


@mcp.tool()
def ck3_grep_raw(
    path: str,
    query: str,
    is_regex: bool = False,
    include_pattern: Optional[str] = None
) -> dict:
    """
    Search for text in files with tracing.
    
    USE THIS instead of VS Code's grep_search when you need to search files
    outside the ck3raven database. Every search is logged for policy validation.
    
    In ck3lens mode: Only paths within the active playset (vanilla + mods) are searchable.
    In ck3raven-dev mode: Broader access for infrastructure testing.
    
    Args:
        path: Absolute path to search in (file or directory)
        query: Text or regex pattern to search for
        is_regex: If True, treat query as regex
        include_pattern: Glob pattern to filter files (e.g., "*.txt")
    
    Returns:
        {"success": bool, "matches": [{"file": str, "line": int, "content": str}]}
    """
    import re
    from ck3lens.agent_mode import get_agent_mode
    
    trace = _get_trace()
    search_path = Path(path)
    
    # WorldAdapter visibility - THE canonical way
    world = _get_world()
    resolution = world.resolve(str(search_path))
    if not resolution.found:
        return {
            "success": False,
            "error": f"Path not found: {path}",
            "mode": world.mode,
        }
    # Use resolved absolute path (always set when resolution.found is True)
    if resolution.absolute_path is None:
        return {"success": False, "error": f"Resolution returned no path for: {path}"}
    search_path = resolution.absolute_path
    
    # Log the attempt
    trace.log("ck3lens.grep_raw", {
        "path": str(search_path),
        "query": query,
        "is_regex": is_regex,
        "include_pattern": include_pattern,
    }, {})
    
    if not search_path.exists():
        return {"success": False, "error": f"Path not found: {path}"}
    
    try:
        matches = []
        
        # Compile pattern
        if is_regex:
            pattern = re.compile(query, re.IGNORECASE)
        else:
            pattern = re.compile(re.escape(query), re.IGNORECASE)
        
        # Get files to search
        if search_path.is_file():
            files = [search_path]
        else:
            if include_pattern:
                files = list(search_path.rglob(include_pattern))
            else:
                files = list(search_path.rglob("*.txt"))
        
        # Search each file
        for file_path in files[:100]:  # Limit to 100 files
            if not file_path.is_file():
                continue
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    for line_num, line in enumerate(f, 1):
                        if pattern.search(line):
                            matches.append({
                                "file": str(file_path),
                                "line": line_num,
                                "content": line.rstrip()[:200],  # Truncate long lines
                            })
                            if len(matches) >= 50:  # Limit matches
                                break
            except Exception:
                continue
            
            if len(matches) >= 50:
                break
        
        result = {
            "success": True,
            "matches": matches,
            "count": len(matches),
            "truncated": len(matches) >= 50,
        }
        
        trace.log("ck3lens.grep_raw.result", {
            "path": str(search_path),
            "query": query,
        }, {"match_count": len(matches)})
        
        return result
        
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def ck3_file_search(
    pattern: str,
    base_path: Optional[str] = None
) -> dict:
    """
    Search for files by glob pattern with tracing.
    
    USE THIS instead of VS Code's file_search when you need to find files
    outside the ck3raven database. Every search is logged for policy validation.
    
    Path defaults:
    - ck3raven-dev mode: Defaults to ck3raven repo root (for infrastructure work)
    - ck3lens mode: Defaults to vanilla game path
    
    IMPORTANT: In ck3lens mode, while the default is vanilla, you can explicitly 
    set base_path to search other allowed paths including ck3raven source 
    (which is in read_allowed for research purposes). The WorldAdapter validates 
    all paths against mode visibility rules.
    
    Args:
        pattern: Glob pattern to match (e.g., "**/*.txt", "common/traits/*.txt")
        base_path: Base directory to search in. If not provided:
                   - ck3raven-dev: repo root
                   - ck3lens: vanilla game path
    
    Returns:
        {"success": bool, "files": [str], "count": int}
    """
    from ck3lens.agent_mode import get_agent_mode
    
    trace = _get_trace()
    scope = _get_session_scope()
    world = _get_world()
    
    # Get agent mode first for path defaults
    mode = get_agent_mode()
    
    # Default path depends on mode
    if base_path:
        search_base = Path(base_path)
    elif mode == "ck3raven-dev":
        # In ck3raven-dev mode, default to repo root for infrastructure work
        search_base = Path(__file__).parent.parent.parent
    elif scope.get("vanilla_root"):
        search_base = Path(scope["vanilla_root"])
    else:
        search_base = Path("C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game")
    
    # WorldAdapter visibility - THE canonical way
    resolution = world.resolve(str(search_base))
    if not resolution.found:
        return {
            "success": False,
            "error": f"Path not found: {base_path or search_base}",
            "mode": world.mode,
        }
    # Always set when resolution.found is True
    if resolution.absolute_path is None:
        return {"success": False, "error": f"Resolution returned no path for: {base_path}"}
    search_base = resolution.absolute_path
    
    # Log the attempt
    trace.log("ck3lens.file_search", {
        "pattern": pattern,
        "base_path": str(search_base),
    }, {})
    
    if not search_base.exists():
        return {"success": False, "error": f"Base path not found: {search_base}"}
    
    try:
        files = []
        for p in search_base.glob(pattern):
            if p.is_file():
                files.append(str(p))
                if len(files) >= 500:  # Limit results
                    break
        
        result = {
            "success": True,
            "files": files,
            "count": len(files),
            "truncated": len(files) >= 500,
            "base_path": str(search_base),
        }
        
        trace.log("ck3lens.file_search.result", {
            "pattern": pattern,
        }, {"count": len(files)})
        
        return result
        
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# DELETED January 3, 2026: ck3_get_scope_info
# 
# This tool was redundant with ck3_playset(command="mods").
# It used deprecated db_visibility() and visible_cvids concepts.
# 
# To get mods in active playset, use: ck3_playset(command="mods")
# To get playset info, use: ck3_playset(command="get")
# ============================================================================


@mcp.tool()
def ck3_parse_content(
    content: str,
    filename: str = "inline.txt"
) -> dict:
    """
    Parse CK3 script content and return AST or errors.
    
    Uses error-recovering parser that collects ALL errors instead of
    stopping at the first one. Returns partial AST even when errors occur.
    
    For simple syntax validation, prefer ck3_validate_syntax instead.
    Use this when you need the actual AST for analysis.
    
    Args:
        content: CK3 script content to parse
        filename: Optional filename for error messages
    
    Returns:
        {
            "success": bool (true if no errors),
            "ast": {...} (partial AST, may be valid despite errors),
            "errors": [
                {
                    "line": 5,
                    "column": 10,
                    "end_line": 5,
                    "end_column": 15,
                    "message": "Expected value after operator",
                    "code": "PARSE_ERROR",
                    "severity": "error"
                },
                ...
            ]
        }
    """
    trace = _get_trace()
    
    result = parse_content(content, filename, recover=True)
    
    trace.log("ck3lens.parse_content", {
        "filename": filename,
        "content_length": len(content)
    }, {"success": result["success"], "error_count": len(result["errors"])})
    
    return result


@mcp.tool()
def ck3_report_validation_issue(
    issue_type: Literal["parser_false_positive", "reference_false_positive", "parser_missed_error", "other"],
    code_snippet: str,
    expected_behavior: str,
    actual_behavior: str,
    notes: str | None = None,
) -> dict:
    """
    Report a validation false positive or missed error.
    
    Use this when the parser or reference validator produces incorrect results.
    These reports help improve ck3raven's validation accuracy.
    
    Issue types:
    - parser_false_positive: Parser rejected valid CK3 syntax
    - reference_false_positive: Reference checker flagged a valid symbol
    - parser_missed_error: Parser accepted invalid CK3 syntax
    - other: Other validation issues
    
    Args:
        issue_type: Category of validation issue
        code_snippet: The CK3 code that was incorrectly validated
        expected_behavior: What should have happened
        actual_behavior: What actually happened
        notes: Optional additional context
    
    Returns:
        Confirmation with issue ID for tracking
    """
    import json
    import hashlib
    from datetime import datetime
    
    trace = _get_trace()
    session = _get_session()
    
    # Create issue record
    issue_id = hashlib.sha256(
        f"{issue_type}:{code_snippet[:100]}:{datetime.now().isoformat()}".encode()
    ).hexdigest()[:12]
    
    issue = {
        "issue_id": issue_id,
        "issue_type": issue_type,
        "code_snippet": code_snippet,
        "expected_behavior": expected_behavior,
        "actual_behavior": actual_behavior,
        "notes": notes,
        "reported_at": datetime.now().isoformat(),
        "status": "open",
    }

    # Write to issues file in ck3raven project folder
    ck3raven_root = Path(__file__).parent.parent.parent
    issues_file = ck3raven_root / "ck3lens_validation_issues.jsonl"
    with issues_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(issue, ensure_ascii=False) + "\n")

    trace.log("ck3lens.report_validation_issue", {
        "issue_type": issue_type,
        "snippet_length": len(code_snippet)
    }, {"issue_id": issue_id})
    
    return {
        "success": True,
        "issue_id": issue_id,
        "message": f"Validation issue recorded. ID: {issue_id}. Will be reviewed in ck3raven-dev mode.",
        "issues_file": str(issues_file)
    }


# ============================================================================
# DELETED January 2, 2026: ck3_get_completions, ck3_get_hover, ck3_get_definition
# 
# These tools imported from ck3lens.semantic which does not exist.
# They also referenced _get_playset_id() which is undefined.
# 
# The functionality should be provided by the CK3 Lens Explorer VS Code
# extension, not via MCP tools. Re-add when ck3lens.semantic is implemented.
# ============================================================================


@mcp.tool()
def ck3_get_agent_briefing() -> dict:
    """
    Get the agent briefing notes for the active playset.
    
    Agent briefings contain user-written notes that help the AI understand:
    - Which errors to prioritize vs ignore
    - Which conflicts are expected (from compatch mods)
    - Mod relationships (which mods handle conflicts for others)
    - Overall priorities for the work
    
    Returns:
        Agent briefing configuration from the active playset
    """
    trace = _get_trace()
    
    scope = _get_session_scope()
    
    if scope.get("source") == "none":
        return {
            "error": "No active playset",
            "hint": "Switch to a playset with ck3_switch_playset first"
        }
    
    briefing = scope.get("agent_briefing", {})
    sub_agent = scope.get("sub_agent_config", {})
    
    result = {
        "playset_name": scope.get("playset_name"),
        "context": briefing.get("context", ""),
        "error_analysis_notes": briefing.get("error_analysis_notes", []),
        "conflict_resolution_notes": briefing.get("conflict_resolution_notes", []),
        "mod_relationships": briefing.get("mod_relationships", []),
        "priorities": briefing.get("priorities", []),
        "custom_instructions": briefing.get("custom_instructions", ""),
        "sub_agent_config": sub_agent,
    }
    
    # Count compatch mods
    mod_list = scope.get("mod_list", [])
    compatch_count = sum(1 for m in mod_list if m.get("is_compatch", False))
    result["compatch_mods_count"] = compatch_count
    result["compatch_mods"] = [m["name"] for m in mod_list if m.get("is_compatch", False)]
    
    trace.log("ck3lens.get_agent_briefing", {}, {
        "has_briefing": bool(briefing),
        "compatch_count": compatch_count
    })
    
    return result


@mcp.tool()
def ck3_search_mods(
    query: str,
    search_by: Literal["name", "workshop_id", "any"] = "any",
    fuzzy: bool = True,
    limit: int = 20
) -> dict:
    """
    Search for mods in the database by name, workshop ID, or both.
    
    Supports fuzzy matching for name searches (handles abbreviations).
    
    Args:
        query: Search term (mod name, abbreviation, or workshop ID)
        search_by: Search field - "name", "workshop_id", or "any"
        fuzzy: Enable fuzzy name matching (catches abbreviations like "EPE" for "Ethnicities and Portraits Expanded")
        limit: Maximum results
    
    Returns:
        List of matching mods with details
    """
    db = _get_db()
    trace = _get_trace()
    
    results = []
    
    if search_by in ("workshop_id", "any") and query.isdigit():
        # Exact workshop ID match
        rows = db.conn.execute("""
            SELECT mp.mod_package_id, mp.name, mp.workshop_id, mp.source_path,
                   cv.content_version_id, cv.file_count
            FROM mod_packages mp
            LEFT JOIN content_versions cv ON cv.mod_package_id = mp.mod_package_id
            WHERE mp.workshop_id = ?
            ORDER BY cv.ingested_at DESC
        """, (query,)).fetchall()
        for r in rows:
            results.append({
                "mod_package_id": r[0], "name": r[1], "workshop_id": r[2],
                "source_path": r[3], "content_version_id": r[4], "file_count": r[5],
                "match_type": "exact_id"
            })
    
    if search_by in ("name", "any"):
        # Name matching
        patterns = [
            (f"%{query}%", "contains"),
        ]
        
        if fuzzy:
            # Abbreviation matching: "EPE" -> "E%P%E%"
            if query.isupper() and len(query) <= 5:
                abbrev_pattern = "%".join(query) + "%"
                patterns.append((abbrev_pattern, "abbreviation"))
            
            # Token matching for underscore/space separated
            tokens = query.replace("_", " ").split()
            if len(tokens) > 1:
                token_pattern = "%".join(tokens)
                patterns.append((f"%{token_pattern}%", "tokens"))
        
        seen_ids = {r["mod_package_id"] for r in results}
        
        for pattern, match_type in patterns:
            rows = db.conn.execute("""
                SELECT mp.mod_package_id, mp.name, mp.workshop_id, mp.source_path,
                       cv.content_version_id, cv.file_count
                FROM mod_packages mp
                LEFT JOIN content_versions cv ON cv.mod_package_id = mp.mod_package_id
                WHERE LOWER(mp.name) LIKE LOWER(?)
                ORDER BY cv.ingested_at DESC
                LIMIT ?
            """, (pattern, limit)).fetchall()
            
            for r in rows:
                if r[0] not in seen_ids:
                    seen_ids.add(r[0])
                    results.append({
                        "mod_package_id": r[0], "name": r[1], "workshop_id": r[2],
                        "source_path": r[3], "content_version_id": r[4], "file_count": r[5],
                        "match_type": match_type
                    })
    
    trace.log("ck3lens.search_mods", {"query": query, "search_by": search_by, "fuzzy": fuzzy},
              {"result_count": len(results)})
    
    return {"results": results[:limit], "query": query}

# ============================================================================
# Mode & Configuration Tools
# ============================================================================

@mcp.tool()
def ck3_get_mode_instructions(
    mode: Literal["ck3lens", "ck3raven-dev"]
) -> dict:
    """
    Get the instruction content for a specific agent mode.
    
    CRITICAL: This is THE initialization function. Call this FIRST.
    
    This single call handles:
    1. Database connection initialization
    2. Mode setting (persisted to file)
    3. WIP workspace initialization (mode-specific location)
    4. Playset detection
    5. Returns mode instructions + policy boundaries + session info
    
    Args:
        mode: The mode to initialize:
            - "ck3lens": CK3 modding with database search and mod editing
            - "ck3raven-dev": Full development mode for infrastructure
    
    Returns:
        Mode instructions, policy boundaries, session context, and database status
    """
    from pathlib import Path
    from ck3lens.policy import (
        ScopeDomain, CK3LensTokenType, AgentMode,
        get_wip_workspace_path, initialize_workspace,
    )
    from ck3lens.agent_mode import set_agent_mode, VALID_MODES
    
    # Validate mode before proceeding
    if mode not in VALID_MODES:
        return {
            "error": f"Invalid mode: {mode}",
            "valid_modes": list(VALID_MODES),
        }
    
    # =========================================================================
    # STEP 1: Initialize database connection (what ck3_init_session used to do)
    # =========================================================================
    session_info = _init_session_internal()
    
    # =========================================================================
    # STEP 2: Set mode (persisted to file as single source of truth)
    # =========================================================================
    set_agent_mode(mode)
    
    # Reset cached world adapter - mode change invalidates the cache
    _reset_world_cache()
    
    # =========================================================================
    # STEP 3: Load mode-specific instructions
    # =========================================================================
    mode_files = {
        "ck3lens": "COPILOT_LENS_COMPATCH.md",
        "ck3raven-dev": "COPILOT_RAVEN_DEV.md",
    }
    
    ck3raven_root = Path(__file__).parent.parent.parent
    instructions_path = ck3raven_root / ".github" / mode_files[mode]
    
    if not instructions_path.exists():
        return {
            "error": f"Instructions file not found: {mode_files[mode]}",
            "expected_path": str(instructions_path),
            "session": session_info,  # Still return session info
        }
    
    try:
        content = instructions_path.read_text(encoding="utf-8")
        
        # =====================================================================
        # STEP 4: Initialize WIP workspace (mode-specific location)
        # =====================================================================
        wip_info = None
        agent_mode = AgentMode.CK3LENS if mode == "ck3lens" else AgentMode.CK3RAVEN_DEV
        
        try:
            wip_info = initialize_workspace(
                mode=agent_mode,
                repo_root=ck3raven_root if mode == "ck3raven-dev" else None,
                wipe=True  # Auto-wipe on session start
            )
        except Exception as e:
            wip_info = {"error": f"WIP init failed: {e}"}
        
        # Build policy context for the mode
        policy_context = _get_mode_policy_context(mode)
        
        # =====================================================================
        # STEP 5: Log initialization to trace
        # =====================================================================
        trace = _get_trace()
        wip_path = get_wip_workspace_path(
            agent_mode,
            ck3raven_root if mode == "ck3raven-dev" else None
        )
        trace.log("ck3lens.mode_initialized", {"mode": mode}, {
            "mode": mode,
            "source_file": str(instructions_path),
            "wip_workspace": str(wip_path),
            "playset_id": session_info.get("playset_id"),
            "playset_name": session_info.get("playset_name"),
        })
        
        # =====================================================================
        # Build complete response
        # =====================================================================
        result = {
            "mode": mode,
            "instructions": content,
            "source_file": str(instructions_path),
            "policy": policy_context,
            "wip_workspace": wip_info,
            "session_note": _get_mode_session_note(mode),
            # Session info (from what ck3_init_session used to return)
            "session": {
                "local_mods_folder": session_info.get("local_mods_folder"),
                "db_path": session_info.get("db_path"),
                "playset_id": session_info.get("playset_id"),
                "playset_name": session_info.get("playset_name"),
                "db_status": session_info.get("db_status", {}),
            },
        }
        
        # Add warning if database needs attention
        if session_info.get("warning"):
            result["db_warning"] = session_info["warning"]
        
        return result
        
    except Exception as e:
        return {
            "error": str(e),
            "session": session_info,  # Still return session info on error
        }


def _get_mode_policy_context(mode: str) -> dict:
    """
    Build policy context for a mode showing boundaries and capabilities.
    """
    from ck3lens.policy import (
        ScopeDomain, CK3LensTokenType,
        Ck3RavenDevScopeDomain,
        Ck3RavenDevTokenType, CK3RAVEN_DEV_TOKEN_TIER_A, CK3RAVEN_DEV_TOKEN_TIER_B,
    )
    
    if mode == "ck3lens":
        return {
            "mode": "ck3lens",
            "description": "CK3 modding: Database search + mod file editing",
            "scope_domains": {
                "read_allowed": [
                    ScopeDomain.PLAYSET_DB.value,  # Indexed playset content
                    "mods[]",  # All mods in active playset
                    ScopeDomain.VANILLA_GAME.value,
                    ScopeDomain.CK3_UTILITY_FILES.value,
                    ScopeDomain.CK3RAVEN_SOURCE.value,  # Read OK for error context
                    ScopeDomain.WIP_WORKSPACE.value,
                ],
                "write_allowed": [
                    "mods[] under local_mods_folder",  # Enforcement decides at execution time
                    ScopeDomain.WIP_WORKSPACE.value,
                ],
                "delete_requires_token": [
                    "mods[] under local_mods_folder",
                ],
                "always_denied": [
                    "write to mods[] NOT under local_mods_folder",
                    "write to VANILLA_GAME",
                    "write to CK3RAVEN_SOURCE",
                ],
            },
            "available_tokens": [tt.value for tt in CK3LensTokenType],
            "hard_rules": [
                "Python files only allowed in WIP workspace",
                "Delete requires explicit token with user prompt evidence",
            ],
        }
    elif mode == "ck3raven-dev":
        return {
            "mode": "ck3raven-dev",
            "description": "Development mode: CK3 Lens infrastructure development",
            "scope_domains": {
                "read_allowed": [
                    Ck3RavenDevScopeDomain.CK3RAVEN_SOURCE.value,
                    Ck3RavenDevScopeDomain.CK3LENS_MCP_SOURCE.value,
                    Ck3RavenDevScopeDomain.CK3LENS_EXPLORER_SOURCE.value,
                    Ck3RavenDevScopeDomain.MOD_FILESYSTEM.value,  # Read-only for parser testing
                    Ck3RavenDevScopeDomain.VANILLA_FILESYSTEM.value,  # Read-only for parser testing
                    Ck3RavenDevScopeDomain.CK3RAVEN_DATABASE.value,
                    Ck3RavenDevScopeDomain.WIP_WORKSPACE.value,
                    Ck3RavenDevScopeDomain.CK3_UTILITY_FILES.value,
                ],
                "write_allowed": [
                    Ck3RavenDevScopeDomain.CK3RAVEN_SOURCE.value,
                    Ck3RavenDevScopeDomain.CK3LENS_MCP_SOURCE.value,
                    Ck3RavenDevScopeDomain.CK3LENS_EXPLORER_SOURCE.value,
                    Ck3RavenDevScopeDomain.CK3RAVEN_DATABASE.value,  # With migration context
                    Ck3RavenDevScopeDomain.WIP_WORKSPACE.value,  # <repo>/.wip/ only
                ],
                "delete_requires_token": [
                    Ck3RavenDevScopeDomain.CK3RAVEN_SOURCE.value,
                    Ck3RavenDevScopeDomain.CK3LENS_MCP_SOURCE.value,
                    Ck3RavenDevScopeDomain.CK3LENS_EXPLORER_SOURCE.value,
                ],
                "always_denied": [
                    "write to MOD_FILESYSTEM (absolute prohibition)",
                    "write to VANILLA_FILESYSTEM (absolute prohibition)",
                    "launcher/registry repair (ck3lens mode only)",
                    "run_in_terminal (use ck3_exec instead)",
                ],
            },
            "available_tokens": {
                "tier_a_auto_grant": [tt.value for tt in CK3RAVEN_DEV_TOKEN_TIER_A],
                "tier_b_approval_required": [tt.value for tt in CK3RAVEN_DEV_TOKEN_TIER_B],
            },
            "hard_rules": [
                "ABSOLUTE PROHIBITION: Cannot write to ANY mod files (local, workshop, vanilla)",
                "PROHIBITION: Cannot use run_in_terminal (use ck3_exec)",
                "Git push/force push requires explicit token",
                "Git history rewrite (rebase, amend) requires explicit token",
                "DB destructive ops require migration context + rollback plan + token",
                "WIP scripts cannot substitute for proper code fixes",
                "Repeated script execution without core changes = AUTO_DENY",
            ],
            "wip_workspace": {
                "location": "<repo>/.wip/",
                "note": "Git-ignored, strictly constrained to analysis/staging only",
                "constraints": [
                    "ANALYSIS_ONLY: Read-only analysis, no writes",
                    "REFACTOR_ASSIST: Generate patches, requires core_change_plan",
                    "MIGRATION_HELPER: Generate migrations, requires core_change_plan",
                ],
            },
        }
    else:
        return {"error": f"Unknown mode: {mode}"}


def _get_mode_session_note(mode: str) -> str:
    """Get a brief session note for the mode."""
    if mode == "ck3lens":
        return (
            "CK3 Lens mode active. You can:\n"
            "- Search symbols, files, content via database\n"
            "- Draft Python scripts in WIP workspace (~/.ck3raven/wip/)\n"
            "- Use ck3_repair for launcher/cache issues\n\n"
            "You CANNOT write to workshop mods, vanilla, or ck3raven source."
        )
    elif mode == "ck3raven-dev":
        return (
            "CK3 Raven Dev mode active. You can:\n"
            "- Read all source code and mods (for parser/ingestion testing)\n"
            "- Write/edit ck3raven infrastructure code\n"
            "- Execute commands via ck3_exec (NOT run_in_terminal)\n"
            "- Write analysis scripts to <repo>/.wip/\n\n"
            "ABSOLUTE PROHIBITION: You CANNOT write to ANY mod files.\n"
            "Git push/rebase/amend requires explicit approval token."
        )
    return ""


@mcp.tool()
def ck3_get_detected_mode() -> dict:
    """
    Get the currently detected agent mode from trace log.
    
    Analyzes recent trace entries to determine which mode
    the agent is operating in based on:
    - Recent mode_initialized events
    - validate_policy calls with mode parameter
    
    Returns:
        {
            "detected_mode": str or null,
            "confidence": "high" | "medium" | "low",
            "last_activity": timestamp,
            "evidence": list of trace entries supporting detection
        }
    """
    trace = _get_trace()
    
    # Get recent events (last 100)
    events = trace.read_recent(max_events=100)
    
    detected_mode = None
    confidence = "low"
    evidence = []
    last_activity = None
    
    # Look for mode evidence in reverse chronological order
    for event in events:
        tool = event.get("tool", "")
        ts = event.get("ts", 0)
        
        # Direct mode initialization is the strongest signal
        if tool == "ck3lens.mode_initialized":
            mode = event.get("result", {}).get("mode") or event.get("args", {}).get("mode")
            if mode:
                detected_mode = mode
                confidence = "high"
                evidence.append({
                    "tool": tool,
                    "mode": mode,
                    "ts": ts
                })
                last_activity = ts
                break  # Most recent mode init wins
        
        # validate_policy calls also indicate mode
        if tool == "ck3lens.validate_policy":
            mode = event.get("args", {}).get("mode")
            if mode and not detected_mode:
                detected_mode = mode
                confidence = "high"
                evidence.append({
                    "tool": tool,
                    "mode": mode,
                    "ts": ts
                })
                last_activity = ts
                break
        
        # init_session indicates activity but not mode
        if tool == "ck3lens.init_session" and not last_activity:
            last_activity = ts
    
    # If no mode detected, check if there's any recent activity
    if not detected_mode and events:
        confidence = "none"
        last_activity = events[0].get("ts") if events else None
    
    return {
        "detected_mode": detected_mode,
        "confidence": confidence,
        "last_activity": last_activity,
        "evidence": evidence[:5]  # Limit evidence entries
    }


@mcp.tool()
def ck3_get_workspace_config() -> dict:
    """
    Get the workspace configuration including tool sets and MCP settings.
    
    Use this to understand:
    - Available modes/tool sets and what tools they enable
    - MCP server configuration
    - local_mods_folder (for editable mods)
    - Database path
    
    Returns:
        Complete workspace configuration
    """
    from pathlib import Path
    import json

    session = _get_session()

    # Minimal config - WorldAdapter handles visibility, enforcement handles writes
    db_path_str = str(session.db_path) if session.db_path else None
    db_exists = session.db_path.exists() if session.db_path else False
    
    result = {
        "database": {
            "path": db_path_str,
            "exists": db_exists,
        },
        "playset_name": session.playset_name,
        "local_mods_folder": str(session.local_mods_folder) if session.local_mods_folder else None,
        "available_modes": [
            {
                "name": "ck3lens",
                "description": "CK3 modding - database search, conflict detection, mod editing",
                "use_case": "Fixing mod errors, compatibility patching, mod development",
            },
            {
                "name": "ck3raven-dev",
                "description": "Full development mode - all tools for infrastructure work",
                "use_case": "Python development, MCP server changes, database schema",
            },
        ],
        # NOTE: mcp.json is BANNED - MCP server is provided dynamically by CK3 Lens Explorer extension
        # NOTE: toolSets.json reading removed - hard-coded paths are not portable
    }
    
    return result


# ============================================================================
# Unified Database Query Tool
# ============================================================================

# Schema definitions for --help output
_DB_QUERY_SCHEMA = {
    "provinces": {
        "table": "province_lookup",
        "columns": ["province_id", "name", "culture", "religion", "terrain", "holding_type"],
        "filters": {
            "province_id": "int - Exact province ID (e.g., 2333)",
            "name": "str - LIKE pattern for name (e.g., '%paris%')",
            "culture": "str - Exact culture match",
            "religion": "str - Exact religion match",
            "terrain": "str - Terrain type (plains, hills, etc.)",
        },
        "examples": [
            'table=provinces, filters={"province_id": 2333}',
            'table=provinces, filters={"culture": "french"}',
        ],
    },
    "characters": {
        "table": "character_lookup",
        "columns": ["character_id", "name", "dynasty_id", "dynasty_house", "culture", 
                    "religion", "birth_date", "death_date", "father_id", "mother_id"],
        "filters": {
            "character_id": "int - Exact character ID",
            "name": "str - LIKE pattern for name",
            "dynasty_id": "int - Dynasty ID",
            "culture": "str - Culture",
            "religion": "str - Religion",
            "birth_date_gte": "str - Birth >= date (e.g., '800.1.1')",
            "birth_date_lte": "str - Birth <= date",
        },
        "examples": [
            'table=characters, filters={"name": "%charlemagne%"}',
            'table=characters, filters={"dynasty_id": 699}',
        ],
    },
    "dynasties": {
        "table": "dynasty_lookup",
        "columns": ["dynasty_id", "name_key", "prefix", "culture", "motto"],
        "filters": {
            "dynasty_id": "int - Exact dynasty ID",
            "name_key": "str - LIKE pattern for name key",
            "culture": "str - Culture",
        },
        "examples": [
            'table=dynasties, filters={"name_key": "%karling%"}',
        ],
    },
    "titles": {
        "table": "title_lookup",
        "columns": ["title_key", "tier", "capital_county", "capital_province_id", 
                    "de_jure_liege", "color_r", "color_g", "color_b", "definite_form", "landless"],
        "filters": {
            "title_key": "str - Title key or LIKE pattern (e.g., 'k_france' or 'd_%')",
            "tier": "str - Tier: e, k, d, c, b, h",
            "de_jure_liege": "str - De jure parent title",
            "capital_county": "str - Capital county",
            "landless": "bool - Landless flag",
        },
        "examples": [
            'table=titles, filters={"tier": "k"}',
            'table=titles, filters={"de_jure_liege": "k_france"}',
        ],
    },
    "localization": {
        "table": "localization_entries",
        "columns": ["loc_key", "value", "file_id", "line_number", "language"],
        "filters": {
            "loc_key": "str - LIKE pattern for key",
            "value": "str - LIKE pattern for value text",
            "language": "str - Language (default: english)",
        },
        "examples": [
            'table=localization, filters={"loc_key": "%trait_brave%"}',
            'table=localization, filters={"value": "%Brave%", "language": "english"}',
        ],
    },
    "symbols": {
        "table": "symbols",
        "columns": ["symbol_id", "name", "symbol_type", "file_id", "line_number", "source_mod"],
        "filters": {
            "name": "str - LIKE pattern for symbol name",
            "symbol_type": "str - Type (trait, event, decision, etc.)",
            "source_mod": "str - Source mod name",
        },
        "examples": [
            'table=symbols, filters={"name": "brave", "symbol_type": "trait"}',
            'table=symbols, filters={"symbol_type": "event", "source_mod": "vanilla"}',
        ],
    },
    "files": {
        "table": "files",
        "columns": ["file_id", "rel_path", "source_name", "file_type", "size_bytes", "deleted"],
        "filters": {
            "rel_path": "str - LIKE pattern for path",
            "source_name": "str - Source mod name",
            "file_type": "str - File type",
            "deleted": "bool - Deleted flag (default: false)",
        },
        "examples": [
            'table=files, filters={"rel_path": "%traits%", "source_name": "vanilla"}',
        ],
    },
    "refs": {
        "table": "refs",
        "columns": ["ref_id", "name", "ref_type", "file_id", "line_number", "resolved_symbol_id"],
        "filters": {
            "name": "str - LIKE pattern for reference name",
            "ref_type": "str - Reference type",
        },
        "examples": [
            'table=refs, filters={"name": "brave"}',
        ],
    },
}


@mcp.tool()
def ck3_db_query(
    table: str | None = None,
    filters: dict | None = None,
    columns: list[str] | None = None,
    sql: str | None = None,
    sql_file: str | None = None,
    limit: int = 100,
    help: bool = False,
) -> dict:
    """
    Unified database query tool for CK3 raven database.
    
    Use help=True to see available tables and their schemas.
    
    SIMPLE QUERIES (recommended):
        table: Table name (provinces, characters, dynasties, titles, localization, symbols, files, refs)
        filters: Dict of column=value filters. Use % for LIKE patterns.
        columns: Optional list of columns to return (default: all)
        limit: Max rows (default 100)
    
    RAW SQL (advanced):
        sql: Raw SQL query string (SELECT only, for safety)
        sql_file: Path to .sql file with complex query
    
    Args:
        table: Table to query (use help=True to see options)
        filters: {"column": "value"} dict. % in value triggers LIKE match.
        columns: List of columns to select
        sql: Raw SELECT query
        sql_file: Path to .sql file
        limit: Max results
        help: Show schema documentation
        
    Examples:
        ck3_db_query(help=True)
        ck3_db_query(table="provinces", filters={"culture": "french"}, limit=10)
        ck3_db_query(table="titles", filters={"tier": "k"})
        ck3_db_query(table="symbols", filters={"name": "%brave%", "symbol_type": "trait"})
        ck3_db_query(sql="SELECT COUNT(*) as cnt FROM symbols GROUP BY symbol_type")
    """
    # Help mode
    if help:
        return {
            "usage": "ck3_db_query(table=..., filters={...}, limit=N) or ck3_db_query(sql=...)",
            "tables": {
                name: {
                    "columns": schema["columns"],
                    "filters": schema["filters"],
                    "examples": schema["examples"],
                }
                for name, schema in _DB_QUERY_SCHEMA.items()
            },
            "stats": _get_table_stats(),
        }
    
    db = _get_db()
    
    # Raw SQL mode
    if sql or sql_file:
        try:
            if sql_file:
                with open(sql_file, 'r', encoding='utf-8') as f:
                    sql = f.read()
            
            # At this point sql must be a string
            if sql is None:
                return {"error": "No SQL provided"}
            
            # Safety: only allow SELECT
            sql_upper = sql.strip().upper()
            if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
                return {"error": "Only SELECT queries allowed for safety"}
            
            # Add LIMIT if not present
            if "LIMIT" not in sql_upper:
                sql = f"{sql.rstrip().rstrip(';')} LIMIT {limit}"
            
            rows = db.conn.execute(sql).fetchall()
            # Get column names from cursor description
            cursor = db.conn.execute(sql)
            col_names = [d[0] for d in cursor.description] if cursor.description else []
            
            results = [dict(zip(col_names, row)) for row in rows]
            return {"count": len(results), "results": results}
        except Exception as e:
            return {"error": str(e)}
    
    # Table query mode
    if not table:
        return {"error": "Provide table= or sql=, or use help=True"}
    
    if table not in _DB_QUERY_SCHEMA:
        return {"error": f"Unknown table '{table}'. Use help=True to see options."}
    
    schema = _DB_QUERY_SCHEMA[table]
    db_table = schema["table"]
    
    # Build column list
    select_cols = columns if columns else schema["columns"]
    select_clause = ", ".join(select_cols)
    
    # Build WHERE clause
    conditions = []
    params = []
    
    if filters:
        for col, val in filters.items():
            # Handle special filter suffixes
            if col.endswith("_gte"):
                real_col = col[:-4]
                conditions.append(f"{real_col} >= ?")
                params.append(val)
            elif col.endswith("_lte"):
                real_col = col[:-4]
                conditions.append(f"{real_col} <= ?")
                params.append(val)
            elif isinstance(val, str) and '%' in val:
                conditions.append(f"{col} LIKE ?")
                params.append(val)
            elif isinstance(val, bool):
                conditions.append(f"{col} = ?")
                params.append(1 if val else 0)
            else:
                conditions.append(f"{col} = ?")
                params.append(val)
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    params.append(limit)
    
    try:
        query = f"SELECT {select_clause} FROM {db_table} WHERE {where_clause} LIMIT ?"
        rows = db.conn.execute(query, params).fetchall()
        
        results = [dict(zip(select_cols, row)) for row in rows]
        return {"count": len(results), "table": table, "results": results}
    except Exception as e:
        return {"error": str(e), "query": query if 'query' in dir() else None}


def _get_table_stats() -> dict:
    """Get row counts for all queryable tables."""
    db = _get_db()
    stats = {}
    for name, schema in _DB_QUERY_SCHEMA.items():
        try:
            count = db.conn.execute(f"SELECT COUNT(*) FROM {schema['table']}").fetchone()[0]
            stats[name] = count
        except:
            stats[name] = "error"
    return stats


# ============================================================================
# QBuilder - Build System Tools
# ============================================================================

@mcp.tool()
def ck3_qbuilder(
    command: Literal["status", "build", "discover", "reset"] = "status",
    max_tasks: Optional[int] = None,
    fresh: bool = False,
) -> dict:
    """
    Unified QBuilder tool for build system operations.

    ARCHITECTURE: MCP servers are READ-ONLY clients.
    All mutations go through the QBuilder daemon via IPC.
    See docs/SINGLE_WRITER_ARCHITECTURE.md for details.

    Commands:

    command=status   -> Get queue statistics and daemon status (via IPC)
    command=build    -> Launch background build daemon (subprocess)
    command=discover -> Request daemon to enqueue discovery tasks (via IPC)
    command=reset    -> Request queue reset (via IPC to daemon)

    Args:
        command: Operation to perform
        max_tasks: Execution throttle (caps work per invocation, not eligibility)
        fresh: For reset command - clear ALL data for fresh build

    Returns:
        Dict with command-specific results

    Background builds:
        The build command launches `python -m qbuilder.cli daemon` as a subprocess.
        The daemon holds the writer lock and processes all enqueued work.
        It also runs the IPC server for client requests.
    """
    import subprocess
    import sys
    
    from ck3lens.daemon_client import daemon, DaemonNotAvailableError
    
    trace = _get_trace()
    ck3raven_root = str(Path(__file__).parent.parent.parent)
    python_exe = sys.executable
    
    if command == "status":
        # Query daemon status via IPC
        try:
            if daemon.is_available():
                status = daemon.get_queue_status()
                status["daemon_available"] = True
                trace.log("ck3_qbuilder.status", {}, status)
                return status
            else:
                result = {
                    "daemon_available": False,
                    "message": "Daemon not running. Use ck3_qbuilder(command='build') to start.",
                    "hint": "The daemon is the single writer - it must be running for builds.",
                }
                trace.log("ck3_qbuilder.status", {}, result)
                return result
        except Exception as e:
            return {"error": f"Failed to get status: {e}", "daemon_available": False}
    
    elif command == "build":
        # Launch background daemon
        # The daemon is the ONLY process that writes to the database
        log_dir = Path.home() / ".ck3raven" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        from datetime import datetime
        import time
        log_file = log_dir / f"daemon_{datetime.now().strftime('%Y-%m-%d')}.log"
        
        # Check if daemon already running via IPC
        if daemon.is_available():
            health = daemon.health()
            result = {
                "success": True,
                "already_running": True,
                "daemon_pid": health.daemon_pid,
                "state": health.state,
                "queue_pending": health.queue_pending,
                "message": "Daemon already running",
            }
            trace.log("ck3_qbuilder.build", {}, result)
            return result
        
        # RACE CONDITION FIX: Check writer lock before spawning
        # The lock file exists immediately when daemon starts, before IPC is ready
        try:
            from qbuilder.writer_lock import check_writer_lock
            db_path = Path.home() / ".ck3raven" / "ck3raven.db"
            lock_status = check_writer_lock(db_path)
            
            if lock_status.get("lock_exists") and lock_status.get("holder_alive"):
                # Another daemon is starting - wait for IPC to become available
                for _ in range(20):  # Wait up to 10 seconds
                    time.sleep(0.5)
                    if daemon.is_available(force_check=True):
                        health = daemon.health()
                        result = {
                            "success": True,
                            "already_running": True,
                            "daemon_pid": health.daemon_pid,
                            "state": health.state,
                            "queue_pending": health.queue_pending,
                            "message": "Daemon already running (connected after lock wait)",
                        }
                        trace.log("ck3_qbuilder.build", {}, result)
                        return result
                
                # Lock holder exists but IPC not responding
                result = {
                    "success": False,
                    "error": f"Daemon lock held by PID {lock_status.get('holder_pid')} but IPC not responding",
                    "hint": "Kill the stale daemon process or wait for it to finish",
                }
                trace.log("ck3_qbuilder.build", {}, result)
                return result
        except ImportError:
            pass  # Fall back to basic spawn
        
        try:
            with open(log_file, "a", encoding="utf-8") as log_handle:
                log_handle.write(f"\n\n=== Daemon started at {datetime.now().isoformat()} ===\n")
                log_handle.flush()
                
                # Start daemon with IPC server
                proc = subprocess.Popen(
                    [python_exe, "-m", "qbuilder.cli", "daemon"],
                    cwd=ck3raven_root,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            
            # Wait briefly for daemon to start IPC server
            time.sleep(1.0)
            
            result = {
                "success": True,
                "pid": proc.pid,
                "message": f"Daemon started (PID {proc.pid})",
                "log_file": str(log_file),
                "note": "Daemon is the single DB writer. Use 'discover' to enqueue work.",
            }
        except Exception as e:
            result = {"success": False, "error": str(e)}
        
        trace.log("ck3_qbuilder.build", {}, result)
        return result
    
    elif command == "discover":
        # Request daemon to enqueue discovery tasks via IPC
        try:
            if not daemon.is_available():
                return {
                    "success": False,
                    "error": "Daemon not running",
                    "hint": "Start daemon first with ck3_qbuilder(command='build')",
                }
            
            result = daemon.enqueue_scan()
            result["note"] = "Discovery tasks enqueued. Daemon will process them."
            trace.log("ck3_qbuilder.discover", {}, result)
            return result
            
        except DaemonNotAvailableError as e:
            return {
                "success": False,
                "error": str(e),
                "hint": "Start daemon first with ck3_qbuilder(command='build')",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    elif command == "reset":
        # Reset is a write operation - must go through daemon
        # For now, this requires manual intervention since reset is destructive
        return {
            "success": False,
            "error": "Reset requires daemon restart with --fresh flag",
            "hint": "Stop daemon, then run: python -m qbuilder.cli daemon --fresh",
            "note": "This is intentionally gated to prevent accidental data loss.",
        }
    
    else:
        return {"error": f"Unknown command: {command}"}


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    mcp.run()


