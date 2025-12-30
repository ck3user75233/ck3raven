"""
CK3 Lens MCP Server

An MCP server providing CK3 modding tools:
- Symbol search (from ck3raven SQLite DB)
- Conflict detection
- Live mod file operations (sandboxed)
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

from mcp.server.fastmcp import FastMCP

# Add ck3raven to path
CK3RAVEN_ROOT = Path(__file__).parent.parent.parent / "src"
if CK3RAVEN_ROOT.exists():
    sys.path.insert(0, str(CK3RAVEN_ROOT))

from ck3lens.workspace import Session, LocalMod
from ck3lens.db_queries import DBQueries
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
_playset_id: Optional[int] = None


def _get_session() -> Session:
    global _session
    if _session is None:
        from ck3lens.workspace import load_config
        _session = load_config()
    return _session


def _get_db() -> DBQueries:
    global _db
    if _db is None:
        session = _get_session()
        _db = DBQueries(db_path=session.db_path)
    return _db


def _get_playset_id() -> int:
    """Get active playset ID, auto-detecting if needed."""
    global _playset_id
    if _playset_id is None:
        db = _get_db()
        # Get the first active playset from the database
        playsets = db.conn.execute(
            "SELECT playset_id FROM playsets WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if playsets:
            _playset_id = playsets[0]
        else:
            # Fallback: get any playset
            playsets = db.conn.execute(
                "SELECT playset_id FROM playsets ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            _playset_id = playsets[0] if playsets else 1
    return _playset_id


# Cached file-based lens
_cached_file_lens = None
_cached_file_lens_source = None


def _get_lens(no_lens: bool = False):
    """
    Get the active playset lens for filtering queries.
    
    The lens is like putting on glasses - you only see content from the active playset.
    
    The ONLY source for playset data is file-based JSON configuration.
    Database-based playsets are DEPRECATED and NOT used.
    
    Args:
        no_lens: If True, return None to search ALL content (take glasses off)
    
    Returns:
        PlaysetLens object or None if no_lens=True or no playset configured
    """
    global _cached_file_lens, _cached_file_lens_source
    
    if no_lens:
        return None
    
    db = _get_db()
    
    # File-based playset is the ONLY source (database is DEPRECATED)
    scope = _get_session_scope()
    
    if scope.get("source") in ("json", "legacy_file"):
        # Check if we have a cached lens for this source
        source_key = scope.get("file_path")
        if _cached_file_lens is not None and _cached_file_lens_source == source_key:
            return _cached_file_lens
        
        # Build lens from file-based scope
        mod_steam_ids = list(scope.get("active_mod_ids", set()))
        mod_paths = list(scope.get("active_roots", set()))
        playset_name = scope.get("playset_name", "File Playset")
        
        lens = db.build_lens_from_scope(
            playset_name=playset_name,
            mod_steam_ids=mod_steam_ids,
            mod_paths=mod_paths
        )
        
        if lens:
            _cached_file_lens = lens
            _cached_file_lens_source = source_key
            return lens
    
    # No playset configured - return None (searches ALL content)
    # NOTE: Database-based playsets are DEPRECATED and NOT used
    return None


# Cached playset scope for path validation
_cached_playset_scope = None


def _get_playset_scope():
    """
    Get the PlaysetScope for filesystem path validation.
    
    This restricts filesystem operations (reads, greps) to paths within
    the active playset (vanilla + active mods).
    
    Returns:
        PlaysetScope or None if no playset configured
    """
    global _cached_playset_scope
    
    if _cached_playset_scope is not None:
        return _cached_playset_scope
    
    from ck3lens.playset_scope import PlaysetScope, build_scope_from_session
    
    scope = _get_session_scope()
    session = _get_session()
    
    if scope.get("source") == "none":
        return None
    
    _cached_playset_scope = build_scope_from_session(scope, session.local_mods_folder)
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
    
    # Get dependencies
    db = _get_db()
    lens = _get_lens(no_lens=False)
    scope = _get_playset_scope()
    
    # Build adapter via router
    try:
        adapter = get_world(db=db, lens=lens, scope=scope)
        _cached_world_adapter = adapter
        _cached_world_mode = mode
        return adapter
    except Exception as e:
        # If any error occurs (mode not initialized, DB issues, etc.),
        # return None to allow tools to work in degraded mode.
        # This is intentional - we want graceful degradation.
        import logging
        logging.getLogger('ck3lens.world').debug(f'WorldAdapter unavailable: {e}')
        return None


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

# Legacy fallback
LEGACY_PLAYSET_FILE = Path.home() / "Documents" / "AI Workspace" / "active_mod_paths.json"


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
            data = json.loads(f.read_text(encoding="utf-8"))
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
    
    Returns dict with session scope data or None if file missing.
    """
    if not playset_file.exists():
        return None
    
    try:
        data = json.loads(playset_file.read_text(encoding='utf-8'))
        
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
        
        # Derive editable mods by checking which mods[] are under local_mods_folder
        editable_mods_list = []
        if local_mods_folder and local_mods_folder.exists():
            for mod in data.get("mods", []):
                if not mod.get("enabled", True):
                    continue
                mod_path = mod.get("path", "")
                if mod_path:
                    try:
                        mod_path_expanded = Path(mod_path).expanduser().resolve()
                        # Check if mod is under local_mods_folder
                        if str(mod_path_expanded).lower().startswith(str(local_mods_folder.resolve()).lower()):
                            editable_mods_list.append({
                                "mod_id": mod.get("name"),  # Use name as ID
                                "name": mod.get("name"),
                                "path": str(mod_path_expanded),
                            })
                    except Exception:
                        pass
        
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
            "editable_mods": editable_mods_list,  # DERIVED from mods[] + local_mods_folder path
            "agent_briefing": agent_briefing,
            "sub_agent_config": data.get("sub_agent_config", {}),
            "mod_list": data.get("mods", []),  # Full mod list for reference
        }
    except Exception as e:
        print(f"Warning: Failed to load playset from {playset_file}: {e}")
        return None


def _load_legacy_playset(playset_file: Path) -> Optional[dict]:
    """
    Load playset from legacy active_mod_paths.json format.
    
    This is the FALLBACK for backward compatibility.
    """
    if not playset_file.exists():
        return None
    
    try:
        data = json.loads(playset_file.read_text(encoding='utf-8'))
        
        active_mod_ids = set()
        active_roots = set()
        
        for mod in data.get("paths", []):
            if mod.get("enabled", True):
                steam_id = mod.get("steam_id")
                if steam_id:
                    active_mod_ids.add(str(steam_id))
                path = mod.get("path")
                if path:
                    active_roots.add(path)
        
        return {
            "playset_id": None,
            "playset_name": data.get("playset_name", "Legacy Playset"),
            "active_mod_ids": active_mod_ids,
            "active_roots": active_roots,
            "vanilla_version_id": None,
            "vanilla_root": str(Path("C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game")),
            "source": "legacy_file",
            "file_path": str(playset_file),
        }
    except Exception as e:
        print(f"Warning: Failed to load legacy playset from {playset_file}: {e}")
        return None


def _get_session_scope(force_refresh: bool = False) -> dict:
    """
    Get all session scope data from a single source of truth.
    
    Priority:
    1. Manifest file (playsets/playset_manifest.json) -> points to active playset
    2. Legacy active_mod_paths.json - backward compat
    3. Empty scope (no playset)
    
    NOTE: Database is NO LONGER used for playset storage.
    
    Returns dict with:
        playset_id: None (JSON-based, no DB ID)
        playset_name: Human-readable name
        active_mod_ids: Set of workshop IDs for mods in playset
        active_roots: Set of filesystem root paths for mods
        vanilla_version_id: None (unused)
        vanilla_root: Path to vanilla game files
        source: "json" or "legacy_file" or "none"
        agent_briefing: Dict with agent instructions (if available)
    """
    global _session_scope
    
    if _session_scope is not None and not force_refresh:
        return _session_scope
    
    # Try manifest file first - this points to the active playset
    if PLAYSET_MANIFEST_FILE.exists():
        try:
            manifest = json.loads(PLAYSET_MANIFEST_FILE.read_text(encoding='utf-8'))
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
    
    # Fall back to legacy file
    legacy_scope = _load_legacy_playset(LEGACY_PLAYSET_FILE)
    if legacy_scope:
        _session_scope = legacy_scope
        return _session_scope
    
    # No playset available
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


@mcp.tool()
def ck3_init_session(
    db_path: Optional[str] = None,
    local_mods: Optional[list[str]] = None
) -> dict:
    """
    DEPRECATED: Use ck3_get_mode_instructions() instead.
    
    This tool is kept for backwards compatibility but redirects to
    ck3_get_mode_instructions with mode auto-detection.
    
    The recommended initialization flow is:
        ck3_get_mode_instructions(mode="ck3lens")  # or "ck3raven-dev"
    
    This single call handles:
    - Database connection
    - Mode setting
    - WIP workspace initialization
    - Returns instructions + policy boundaries
    """
    return {
        "deprecated": True,
        "message": "ck3_init_session is deprecated. Use ck3_get_mode_instructions() instead.",
        "guidance": (
            "Call ck3_get_mode_instructions(mode='ck3lens') or "
            "ck3_get_mode_instructions(mode='ck3raven-dev') to initialize properly.\n\n"
            "This single call handles: database connection, mode setting, "
            "WIP workspace initialization, and returns mode instructions."
        ),
        "example": "ck3_get_mode_instructions(mode='ck3lens')",
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
    - "Local mods" are derived at runtime, not stored

    Returns session info dict.
    """
    from ck3lens.workspace import load_config

    global _session, _db, _trace, _playset_id, _session_scope

    # Reset playset and scope cache
    _playset_id = None
    _session_scope = None

    # Use load_config to get session from active playset
    _session = load_config()

    # Override DB path if provided
    if db_path:
        _session.db_path = Path(db_path)

    _db = DBQueries(db_path=_session.db_path)

    # Initialize trace with proper path based on mode
    _trace = ToolTrace(_get_trace_path())

    # Auto-detect playset
    playset_id = _get_playset_id()
    playset_info = _db.conn.execute(
        "SELECT name, is_active FROM playsets WHERE playset_id = ?",
        (playset_id,)
    ).fetchone()

    # Check database health
    db_status = _check_db_health(_db.conn)

    # Return minimal session info - WorldAdapter handles visibility,
    # enforcement.py handles write permission. No "local_mods" listing needed.
    result = {
        "db_path": str(_db.db_path) if _db.db_path else None,
        "playset_id": playset_id,
        "playset_name": playset_info[0] if playset_info else None,
        "db_status": db_status,
    }

    # Add warning if database needs attention
    if not db_status.get("is_complete"):
        result["warning"] = f"Database incomplete: {db_status.get('rebuild_reason', 'unknown')}. Run: python builder/daemon.py start"

    return result


def _check_db_health(conn) -> dict:
    """Check database build status and completeness."""
    try:
        # Check builder_runs table (written by daemon)
        run_row = conn.execute("""
            SELECT build_id, state, completed_at, files_ingested, 
                   symbols_extracted, refs_extracted, error_message
            FROM builder_runs 
            ORDER BY started_at DESC 
            LIMIT 1
        """).fetchone()
        
        if run_row:
            last_state = run_row[1]  # state column
            is_complete = last_state == 'complete'
            last_updated = run_row[2]  # completed_at
        else:
            last_state = None
            is_complete = False
            last_updated = None
        
        # Get counts
        files = conn.execute("SELECT COUNT(*) FROM files WHERE deleted = 0").fetchone()[0]
        symbols = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        refs = conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
        
        # Determine if rebuild needed
        needs_rebuild = False
        rebuild_reason = None
        
        if not run_row:
            needs_rebuild = True
            rebuild_reason = "No build runs found - database may not be fully initialized"
        elif last_state == 'failed':
            needs_rebuild = True
            error = run_row[6]  # error_message
            rebuild_reason = f"Last build failed: {error[:100] if error else 'Unknown error'}"
        elif last_state == 'running':
            needs_rebuild = True
            rebuild_reason = "Build still in progress or was interrupted"
        elif symbols == 0:
            needs_rebuild = True
            rebuild_reason = "No symbols extracted"
        elif refs == 0:
            needs_rebuild = True
            rebuild_reason = "No references extracted"
        
        return {
            "is_complete": is_complete and not needs_rebuild,
            "phase": last_state if last_state else "unknown",
            "last_updated": last_updated,
            "files_indexed": files,
            "symbols_extracted": symbols,
            "refs_extracted": refs,
            "needs_rebuild": needs_rebuild,
            "rebuild_reason": rebuild_reason,
        }
    except Exception as e:
        return {
            "is_complete": False,
            "error": str(e),
            "needs_rebuild": True,
            "rebuild_reason": f"Error checking database: {e}"
        }


@mcp.tool()
def ck3_get_db_status() -> dict:
    """
    Check database build status and completeness.
    
    Returns information about:
    - Current build phase (complete, in progress, or failed)
    - File, symbol, and reference counts
    - Whether a rebuild is needed and why
    
    If the database is incomplete, provides the command to run
    for a full rebuild.
    
    Returns:
        {
            "is_complete": bool,
            "phase": "complete" | "symbol_extraction" | etc,
            "files_indexed": int,
            "symbols_extracted": int,
            "refs_extracted": int,
            "needs_rebuild": bool,
            "rebuild_reason": str or null,
            "rebuild_command": str
        }
    """
    db = _get_db()
    trace = _get_trace()
    
    status = _check_db_health(db.conn)
    status["rebuild_command"] = "python builder/daemon.py start"
    
    if status.get("needs_rebuild"):
        status["message"] = f"âš ï¸ Database needs rebuild: {status.get('rebuild_reason')}"
    else:
        status["message"] = f"âœ… Database ready: {status.get('symbols_extracted', 0):,} symbols, {status.get('refs_extracted', 0):,} refs"
    
    trace.log("ck3lens.get_db_status", {}, status)
    
    return status


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
        if _db is not None:
            # Close the connection
            try:
                _db.conn.close()
            except Exception:
                pass
            _db = None
        
        # Also clear cached state that depends on DB
        _playset_id = None
        _session_scope = None
        
        # Clear thread-local connections from schema module
        try:
            from ck3raven.db.schema import close_all_connections
            close_all_connections()
        except Exception:
            pass
        
        trace.log("ck3lens.close_db", {}, {"success": True})
        
        return {
            "success": True,
            "message": "Database connection closed. File lock released."
        }
    except Exception as e:
        trace.log("ck3lens.close_db", {}, {"success": False, "error": str(e)})
        return {
            "success": False,
            "message": f"Failed to close connection: {e}"
        }


@mcp.tool()
def ck3_get_playset_build_status(playset_name: str | None = None) -> dict:
    """
    Check build status of mods in a playset.
    
    Works in both modes:
    - ck3lens mode: Check active playset or specified playset
    - ck3raven-dev mode: Check any playset for testing
    
    This determines which mods are fully processed and ready for use,
    and which need to be built before the playset can be used effectively.
    
    Build phases per mod:
    - ingested: Files indexed into database
    - symbols_extracted: Symbols (traits, events, etc.) extracted from ASTs
    - ready: Fully processed and ready for searching/conflict detection
    
    Args:
        playset_name: Name of playset to check (default: active playset)
    
    Returns:
        {
            "playset_name": str,
            "playset_valid": bool,      # True if at least one mod exists on disk
            "total_mods": int,
            "ready_mods": int,          # Fully processed
            "pending_mods": int,        # Need processing
            "missing_mods": int,        # Not on disk
            "needs_build": bool,        # True if any mods need processing
            "missing_mod_names": list,  # Names of mods not on disk
            "mods": [
                {
                    "name": str,
                    "status": "ready" | "pending_symbols" | "pending_ingest" | "not_indexed" | "missing",
                    "exists_on_disk": bool,
                }
            ],
            "build_command": str,       # Command to run if build needed
            "guidance": str,            # Human-readable guidance
        }
    """
    from builder.incremental import check_playset_build_status
    from pathlib import Path
    
    db = _get_db()
    trace = _get_trace()
    
    # Get playset data
    if playset_name:
        # Find specified playset
        playset_folder = Path.home() / ".ck3raven" / "playsets"
        playset_data = None
        
        for f in playset_folder.glob("*.json"):
            if f.name.endswith(".schema.json") or f.name == "playset_manifest.json":
                continue
            data = _load_playset_from_json(f)
            if data and (data.get("playset_name") == playset_name or f.stem == playset_name):
                playset_data = data
                break
        
        if not playset_data:
            return {"error": f"Playset not found: {playset_name}"}
    else:
        # Use active playset
        scope = _get_session_scope()
        if scope.get("source") == "none":
            return {"error": "No active playset configured"}
        playset_data = scope.get("playset_data", {})
        playset_name = playset_data.get("playset_name", "Unknown")
    
    # Check build status
    result = check_playset_build_status(db.conn, playset_data)
    result["playset_name"] = playset_name
    
    # Add guidance
    if not result["playset_valid"]:
        result["guidance"] = "⛔ Invalid playset: All mods are missing from disk. Cannot activate."
        result["build_command"] = None
    elif result["needs_build"]:
        pending = result["pending_mods"]
        result["guidance"] = f"⚠️ {pending} mod(s) need processing before full functionality."
        result["build_command"] = "python builder/daemon.py start --symbols-only"
    else:
        result["guidance"] = "✅ All mods are fully processed and ready."
        result["build_command"] = None
    
    if result["missing_mods"] > 0:
        names = ", ".join(result["missing_mod_names"][:5])
        if result["missing_mods"] > 5:
            names += f" and {result['missing_mods'] - 5} more"
        result["guidance"] += f"\n⚠️ Missing mods (not on disk): {names}"
    
    trace.log("ck3lens.get_playset_build_status", {"playset_name": playset_name}, {
        "valid": result["playset_valid"],
        "ready": result["ready_mods"],
        "pending": result["pending_mods"],
        "missing": result["missing_mods"],
    })
    
    return result


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
    from ck3lens.work_contracts import get_active_contract
    
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
            repo_domains=contract.canonical_domains if contract else [],
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
            elif table in ("files", "asts", "symbols", "refs"):
                if table == "files":
                    return "WHERE content_version_id > 1", []
                else:
                    return f"WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id > 1)", []
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
            # Files cascade - need to delete symbols, refs, asts first
            count_sql = f"SELECT COUNT(*) FROM files {where}"
            
            if confirm:
                # Get content_version_ids for the files being deleted
                cv_where = where.replace("WHERE content_version_id", "WHERE content_version_id")
                if scope == "mods_only":
                    # Delete symbols/refs by content_version_id > 1
                    cur.execute("DELETE FROM symbols WHERE content_version_id > 1")
                    symbols_deleted = cur.rowcount
                    cur.execute("DELETE FROM refs WHERE content_version_id > 1")
                    refs_deleted = cur.rowcount
                else:
                    # Get file_ids first, then find their content_version_ids
                    cur.execute(f"SELECT DISTINCT content_version_id FROM files {where}", params)
                    cv_ids = [r[0] for r in cur.fetchall()]
                    if cv_ids:
                        placeholders = ",".join("?" * len(cv_ids))
                        cur.execute(f"DELETE FROM symbols WHERE content_version_id IN ({placeholders})", cv_ids)
                        symbols_deleted = cur.rowcount
                        cur.execute(f"DELETE FROM refs WHERE content_version_id IN ({placeholders})", cv_ids)
                        refs_deleted = cur.rowcount
                    else:
                        symbols_deleted = refs_deleted = 0
                
                # Delete ASTs by content_hash (ASTs are content-addressed)
                cur.execute(f"DELETE FROM asts WHERE content_hash IN (SELECT content_hash FROM files {where})", params)
                asts_deleted = cur.rowcount
                cur.execute(f"DELETE FROM files {where}", params)
                files_deleted = cur.rowcount
                db.conn.commit()
                
                result["success"] = True
                result["rows_deleted"] = files_deleted
                result["cascade"] = {
                    "symbols_deleted": symbols_deleted,
                    "refs_deleted": refs_deleted,
                    "asts_deleted": asts_deleted,
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
                    # Cascade delete
                    cur.execute(f"DELETE FROM symbols WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id IN ({placeholders}))", cv_ids)
                    symbols_deleted = cur.rowcount
                    cur.execute(f"DELETE FROM refs WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id IN ({placeholders}))", cv_ids)
                    refs_deleted = cur.rowcount
                    cur.execute(f"DELETE FROM asts WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id IN ({placeholders}))", cv_ids)
                    asts_deleted = cur.rowcount
                    cur.execute(f"DELETE FROM files WHERE content_version_id IN ({placeholders})", cv_ids)
                    files_deleted = cur.rowcount
                    cur.execute(f"DELETE FROM playset_mods WHERE content_version_id IN ({placeholders})", cv_ids)
                    playset_mods_deleted = cur.rowcount
                    cur.execute(f"DELETE FROM content_versions {where}", params)
                    cv_deleted = cur.rowcount
                    # Also clean mod_packages for deleted mods
                    cur.execute("DELETE FROM mod_packages WHERE mod_package_id NOT IN (SELECT DISTINCT mod_package_id FROM content_versions WHERE mod_package_id IS NOT NULL)")
                    mod_packages_deleted = cur.rowcount
                    db.conn.commit()
                    
                    result["success"] = True
                    result["rows_deleted"] = cv_deleted
                    result["cascade"] = {
                        "files_deleted": files_deleted,
                        "symbols_deleted": symbols_deleted,
                        "refs_deleted": refs_deleted,
                        "asts_deleted": asts_deleted,
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
    
    âš ï¸ CRITICAL: If this returns healthy=False, the agent MUST stop work
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
        result["message"] = "âœ… Policy enforcement is ACTIVE"
    else:
        result["message"] = f"ðŸš¨ POLICY ENFORCEMENT IS DOWN: {health['error']}"
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
        command=summary     → Error log summary (counts by priority/category/mod)
        command=list        → Filtered error list (priority, category, mod_filter)
        command=search      → Search errors (query required)
        command=cascades    → Cascading error patterns (fix root causes first)
    
    source=game:
        command=summary     → Game log summary with category breakdown
        command=list        → Game log errors (category filter optional)
        command=search      → Search game log (query required)
        command=categories  → Category breakdown with descriptions
    
    source=debug:
        command=summary     → System info, DLCs, mod list
    
    source=crash:
        command=summary     → Recent crash reports list
        command=detail      → Full crash report (crash_id required)
    
    Any source:
        command=read        → Raw log content (lines, from_end, query for search)
    
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


@mcp.tool()
def ck3_conflicts(
    command: Literal["scan", "summary", "list", "detail", "resolve", "content", "high_risk", "report"] = "summary",
    # For scan
    folder_filter: str | None = None,
    # For list
    risk_filter: str | None = None,
    domain_filter: str | None = None,
    status_filter: str | None = None,
    # For detail/resolve
    conflict_id: str | None = None,
    # For content
    unit_key: str | None = None,
    # For resolve
    decision_type: Literal["winner", "defer"] | None = None,
    winner_candidate_id: str | None = None,
    notes: str | None = None,
    # For content
    source_filter: str | None = None,
    # For report/high_risk
    domains_include: list[str] | None = None,
    domains_exclude: list[str] | None = None,
    paths_filter: str | None = None,
    min_candidates: int = 2,
    min_risk_score: int = 60,
    output_format: Literal["summary", "json", "full"] = "summary",
    # Pagination
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    Unified conflict management tool for the active playset.
    
    Commands:
    
    command=scan        → Scan for unit-level conflicts (folder_filter optional)
    command=summary     → Conflict summary by risk/domain/status
    command=list        → List conflicts with filters
    command=detail      → Get conflict details (conflict_id required)
    command=resolve     → Record resolution (conflict_id, decision_type required)
    command=content     → Get all contributions for unit_key (unit_key required)
    command=high_risk   → Get highest-risk conflicts for review
    command=report      → Generate full conflicts report
    
    Args:
        command: Action to perform
        folder_filter: Limit scan to folder (e.g., "common/on_action")
        risk_filter: Filter by risk level (low, med, high)
        domain_filter: Filter by domain (on_action, decision, trait, etc.)
        status_filter: Filter by status (unresolved, resolved, deferred)
        conflict_id: Conflict unit ID for detail/resolve
        unit_key: Unit key for content command (e.g., "on_action:on_yearly_pulse")
        decision_type: Resolution type (winner or defer)
        winner_candidate_id: Winning candidate for winner decision
        notes: Resolution notes
        source_filter: Filter contributions by source
        domains_include: Include only these domains in report
        domains_exclude: Exclude these domains from report
        paths_filter: SQL LIKE pattern for paths
        min_candidates: Min sources for conflict (default 2)
        min_risk_score: Min risk for high_risk (default 60)
        output_format: Report format (summary, json, full)
        limit: Max results
        offset: Pagination offset
    
    Returns:
        Dict with results based on command
    """
    from ck3lens.unified_tools import ck3_conflicts_impl
    
    db = _get_db()
    playset_id = _get_playset_id()
    trace = _get_trace()
    
    result = ck3_conflicts_impl(
        command=command,
        folder_filter=folder_filter,
        risk_filter=risk_filter,
        domain_filter=domain_filter,
        status_filter=status_filter,
        conflict_id=conflict_id,
        unit_key=unit_key,
        decision_type=decision_type,
        winner_candidate_id=winner_candidate_id,
        notes=notes,
        source_filter=source_filter,
        domains_include=domains_include,
        domains_exclude=domains_exclude,
        paths_filter=paths_filter,
        min_candidates=min_candidates,
        min_risk_score=min_risk_score,
        output_format=output_format,
        limit=limit,
        offset=offset,
        db=db,
        playset_id=playset_id,
        trace=trace,
    )
    
    trace.log("ck3lens.conflicts", {
        "command": command,
        "domain_filter": domain_filter,
    }, {"success": "error" not in result})
    
    return result


# ============================================================================
# Unified File Operations
# ============================================================================

@mcp.tool()
def ck3_file(
    command: Literal["get", "read", "write", "edit", "delete", "rename", "refresh", "list"],
    # Path identification
    path: str | None = None,
    mod_name: str | None = None,
    rel_path: str | None = None,
    # For get (from DB)
    include_ast: bool = False,
    no_lens: bool = False,
    # For read/write
    content: str | None = None,
    start_line: int = 1,
    end_line: int | None = None,
    max_bytes: int = 200000,
    justification: str | None = None,
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
) -> dict:
    """
    Unified file operations tool.
    
    Commands:
    
    command=get      → Get file content from database (path required)
    command=read     → Read file from filesystem (path or mod_name+rel_path)
    command=write    → Write file (path for raw write, or mod_name+rel_path for mod)
    command=edit     → Search-replace in live mod file (mod_name, rel_path, old_content, new_content)
    command=delete   → Delete file from live mod (mod_name, rel_path required)
    command=rename   → Rename/move file in live mod (mod_name, rel_path, new_path required)
    command=refresh  → Re-sync file to database (mod_name, rel_path required)
    command=list     → List files in live mod (mod_name required, path_prefix/pattern optional)
    
    For write command with raw path:
    - ck3lens mode: DENIED (must use mod_name+rel_path)
    - ck3raven-dev mode: Allowed with active contract or token
    
    Args:
        command: Operation to perform
        path: File path (for get/read from filesystem)
        mod_name: Live mod name (for write/edit/delete/rename/refresh/list)
        rel_path: Relative path within mod
        include_ast: Include parsed AST (for get)
        no_lens: Search all content, not just active playset (for get)
        content: File content (for write)
        start_line: Start line for read (1-indexed)
        end_line: End line for read (inclusive)
        max_bytes: Max bytes to return
        justification: Audit justification for filesystem reads
        old_content: Content to find (for edit)
        new_content: Replacement content (for edit)
        new_path: New path (for rename)
        validate_syntax: Validate CK3 syntax before write/edit
        path_prefix: Filter by path prefix (for list)
        pattern: Glob pattern (for list)
    
    Returns:
        Dict with results based on command
    """
    from ck3lens.unified_tools import ck3_file_impl
    
    session = _get_session()
    db = _get_db()
    trace = _get_trace()
    lens = _get_lens(no_lens=no_lens)
    world = _get_world()  # WorldAdapter for unified path resolution
    
    return ck3_file_impl(
        command=command,
        path=path,
        mod_name=mod_name,
        rel_path=rel_path,
        include_ast=include_ast,
        no_lens=no_lens,
        content=content,
        start_line=start_line,
        end_line=end_line,
        max_bytes=max_bytes,
        justification=justification,
        old_content=old_content,
        new_content=new_content,
        new_path=new_path,
        validate_syntax=validate_syntax,
        token_id=token_id,
        path_prefix=path_prefix,
        pattern=pattern,
        session=session,
        db=db,
        trace=trace,
        lens=lens,
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
    justification: str | None = None,
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
    
    command=list        → List directory contents from filesystem (path required)
    command=contents    → Get folder contents from database (path required)
    command=top_level   → Get top-level folders in active playset
    command=mod_folders → Get folders in specific mod (content_version_id required)
    
    Args:
        command: Operation to perform
        path: Folder path (for list/contents)
        justification: Audit justification for filesystem access
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
    
    db = _get_db()
    playset_id = _get_playset_id()
    trace = _get_trace()
    world = _get_world()  # WorldAdapter for visibility enforcement
    
    return ck3_folder_impl(
        command=command,
        path=path,
        justification=justification,
        content_version_id=content_version_id,
        folder_pattern=folder_pattern,
        text_search=text_search,
        symbol_search=symbol_search,
        mod_filter=mod_filter,
        file_type_filter=file_type_filter,
        db=db,
        playset_id=playset_id,
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
    
    command=get        → Get active playset info
    command=list       → List all playsets
    command=switch     → Switch to different playset (playset_name required)
    command=mods       → Get mods in active playset
    command=add_mod    → Add mod to playset (mod_name required)
    command=remove_mod → Remove mod from playset (mod_name required)
    command=reorder    → Change mod load order (mod_name, new_position required)
    command=create     → Create new playset (name required)
    command=import     → Import playset from CK3 launcher
    
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
    global _session_scope, _cached_file_lens, _cached_file_lens_source
    
    trace = _get_trace()
    
    # FILE-BASED IMPLEMENTATION (database is DEPRECATED)
    
    if command == "list":
        # List all available playsets
        playsets = []
        manifest_active = None
        
        # Read manifest to see which is active
        if PLAYSET_MANIFEST_FILE.exists():
            try:
                manifest = json.loads(PLAYSET_MANIFEST_FILE.read_text(encoding='utf-8'))
                manifest_active = manifest.get("active", "")
            except Exception:
                pass
        
        for f in PLAYSETS_DIR.glob("*.json"):
            if f.name.endswith(".schema.json") or f.name == "playset_manifest.json" or f.name == "sub_agent_templates.json":
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
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
                    playset_data = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    pass
                break
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
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
        
        # Clear cached scope/lens to force reload
        _session_scope = None
        _cached_file_lens = None
        _cached_file_lens_source = None
        
        # Reload and return new scope
        new_scope = _get_session_scope(force_refresh=True)
        
        # Check build status for all mods in this playset
        build_status = None
        mods_needing_build = []
        mods_missing_from_disk = []
        db_available = False
        try:
            from builder.incremental import check_playset_build_status
            db = _get_db()
            if db and playset_data:
                db_available = True
                build_status = check_playset_build_status(db.conn, playset_data)
                
                # Collect mods needing build (on disk but not fully indexed)
                for mod in build_status.get("mods", []):
                    if mod["status"] in ("not_indexed", "pending_ingest", "pending_symbols"):
                        mods_needing_build.append({
                            "name": mod["name"],
                            "status": mod["status"],
                            "path": mod.get("path")
                        })
                    elif mod["status"] == "missing":
                        mods_missing_from_disk.append(mod["name"])
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
                f"❌ {len(mods_missing_from_disk)} mod(s) are in playset but not on disk. "
                f"These mods will be skipped: {mods_missing_from_disk}"
            )
        
        # Automatically start builder if mods need processing
        builder_started = False
        if mods_needing_build or not db_available:
            try:
                import subprocess
                import sys
                
                # Find the daemon script and venv python
                repo_root = Path(__file__).parent.parent.parent
                daemon_script = repo_root / "builder" / "daemon.py"
                venv_python = repo_root / ".venv" / "Scripts" / "python.exe"
                
                if not venv_python.exists():
                    venv_python = repo_root / ".venv" / "bin" / "python"  # Linux/Mac
                
                if daemon_script.exists() and venv_python.exists():
                    # Start the builder daemon with the playset file
                    cmd = [
                        str(venv_python),
                        str(daemon_script),
                        "start",
                        "--playset-file", str(target_file)
                    ]
                    
                    # Run detached (daemon mode)
                    if sys.platform == "win32":
                        DETACHED_PROCESS = 0x00000008
                        CREATE_NEW_PROCESS_GROUP = 0x00000200
                        CREATE_NO_WINDOW = 0x08000000
                        subprocess.Popen(
                            cmd,
                            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
                            close_fds=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    else:
                        subprocess.Popen(
                            cmd,
                            start_new_session=True,
                            close_fds=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    
                    builder_started = True
                    if mods_needing_build:
                        result["builder_started"] = True
                        result["builder_message"] = (
                            f"🔨 Builder started for {len(mods_needing_build)} mod(s) needing processing. "
                            f"Check status with: python builder/daemon.py status"
                        )
                    else:
                        result["builder_started"] = True
                        result["builder_message"] = (
                            "🔨 Database not available or empty. Builder started to index all playset mods. "
                            "Check status with: python builder/daemon.py status"
                        )
            except Exception as e:
                result["builder_error"] = f"Failed to start builder: {e}"
                result["build_command"] = f"python builder/daemon.py start --playset-file \"{target_file}\""
        
        # Add build status information
        if build_status and not build_status.get("error"):
            result["build_status"] = {
                "playset_valid": build_status.get("playset_valid", False),
                "ready_mods": build_status.get("ready_mods", 0),
                "pending_mods": build_status.get("pending_mods", 0),
                "missing_mods": build_status.get("missing_mods", 0),
            }
        
        if not mods_needing_build and not mods_missing_from_disk and db_available and build_status and not build_status.get("error"):
            result["build_status_message"] = "✅ All mods are ready. No build needed."
        
        return result
    
    elif command == "get":
        # Get current active playset info
        scope = _get_session_scope()
        manifest_active = None
        if PLAYSET_MANIFEST_FILE.exists():
            try:
                manifest = json.loads(PLAYSET_MANIFEST_FILE.read_text(encoding='utf-8'))
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
        # Add a local mod to the active playset's local_mods array
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
            manifest = json.loads(PLAYSET_MANIFEST_FILE.read_text(encoding="utf-8"))
            active_file = manifest.get("active")
            if not active_file:
                return {"success": False, "error": "No active playset in manifest"}
            
            playset_path = PLAYSETS_DIR / active_file
            if not playset_path.exists():
                return {"success": False, "error": f"Active playset file not found: {active_file}"}
            
            playset_data = json.loads(playset_path.read_text(encoding="utf-8"))
        except Exception as e:
            return {"success": False, "error": f"Failed to read playset: {e}"}
        
        # Check if mod_name is a path or a name
        mod_path = None
        if Path(mod_name).exists():
            # It's a path
            mod_path = str(Path(mod_name).resolve())
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
                                        mod_path = str(folder.resolve())
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
        
        # Check if mod needs building
        build_needed = False
        try:
            from builder.incremental import check_playset_build_status
            db = _get_db()
            if db:
                build_status = check_playset_build_status(db.conn, playset_data)
                for mod in build_status.get("mods", []):
                    if mod.get("path") == mod_path and mod["status"] != "ready":
                        build_needed = True
                        break
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
                f"⚠️ Mod '{mod_name}' needs to be indexed. "
                f"Run: python builder/daemon.py start --playset-file \"{playset_path}\""
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
    Unified git operations for live mods.
    
    ⚠️ KNOWN ISSUE: This tool may hang due to GitLens extension conflicts.
    WORKAROUND: Use ck3_exec with git commands instead:
        ck3_exec("git status", working_dir=mod_path)
        ck3_exec("git add .", working_dir=mod_path)
        ck3_exec("git commit -m 'message'", working_dir=mod_path)
    
    Mode-aware behavior:
    - ck3raven-dev mode: Operates on ck3raven repo (mod_name ignored)
    - ck3lens mode: Operates on live mods (mod_name required)
    
    Commands:
    
    command=status → Get git status
    command=diff   → Get git diff (file_path optional)
    command=add    → Stage files (files or all_files required)
    command=commit → Commit staged changes (message required)
    command=push   → Push to remote
    command=pull   → Pull from remote
    command=log    → Get commit log (limit optional)
    
    Args:
        command: Git operation to perform
        mod_name: Live mod name (required in ck3lens mode, ignored in ck3raven-dev mode)
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
    
    target=syntax     → Validate CK3 script syntax (content required)
    target=python     → Check Python syntax (content or file_path required)
    target=references → Validate symbol references exist (symbol_name required)
    target=bundle     → Validate artifact bundle (artifact_bundle required)
    target=policy     → Validate against policy rules (mode required)
    
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
    
    command=status         → Check if VS Code IPC server is available
    command=ping           → Test connection to VS Code
    command=diagnostics    → Get diagnostics for a file (path required)
    command=all_diagnostics → Get diagnostics for all open files
    command=errors_summary → Get workspace error summary
    command=validate_file  → Trigger validation for a file (path required)
    command=open_files     → List currently open files in VS Code
    command=active_file    → Get active file info with diagnostics
    
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
    command: Literal["query", "diagnose_launcher", "repair_registry", "delete_cache", "backup_launcher"] = "query",
    # For query - get status of repair targets
    target: Literal["all", "launcher", "cache", "dlc_load"] | None = None,
    # For repair_registry / delete_cache
    dry_run: bool = True,
    # For backup
    backup_name: str | None = None,
) -> dict:
    """
    Repair CK3 launcher registry and cache issues.
    
    ⚠️ MODE: ck3lens only. Not available in ck3raven-dev mode.
    
    SCOPE: Launcher domain operations only.
    - ~/.ck3raven/ directory management
    - CK3 launcher registry analysis (read-only by default)
    - Cache cleanup
    
    Commands:
    
    command=query             → Get status of repair targets (launcher registry, cache, etc.)
    command=diagnose_launcher → Analyze launcher database for issues
    command=repair_registry   → Fix launcher registry entries (requires dry_run=False)
    command=delete_cache      → Clear ck3raven cache files (requires dry_run=False)
    command=backup_launcher   → Create backup of launcher database before repair
    
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
# Work Contract Management (CLW)
# ============================================================================

@mcp.tool()
def ck3_contract(
    command: Literal["open", "close", "cancel", "status", "list", "flush"] = "status",
    # For open
    intent: str | None = None,
    canonical_domains: list[str] | None = None,
    allowed_paths: list[str] | None = None,
    capabilities: list[str] | None = None,
    expires_hours: float = 8.0,
    notes: str | None = None,
    # For close/cancel
    contract_id: str | None = None,
    closure_commit: str | None = None,
    cancel_reason: str | None = None,
    # For list
    status_filter: str | None = None,
    include_archived: bool = False,
) -> dict:
    """
    Manage work contracts (WCP) for CLI wrapping.
    
    Work contracts define scope and constraints for agent tasks.
    Required for any write or destructive operations.
    
    Commands:
    
    command=open      → Open new contract (intent, canonical_domains required)
    command=close     → Close contract after work complete (contract_id or uses active)
    command=cancel    → Cancel contract without completing (contract_id or uses active)
    command=status    → Get current active contract status
    command=list      → List contracts (status_filter, include_archived optional)
    command=flush     → Archive old contracts from previous days
    
    Args:
        command: Action to perform
        intent: Description of work to be done (for open)
        canonical_domains: Domains this work touches. Product domains: parser, routing,
            builder, extraction, query, cli. Repo domains: docs, tools, tests, policy,
            config, wip, ci, scripts, src
        allowed_paths: Glob patterns for allowed file paths
        capabilities: Requested capabilities (defaults to standard tier)
        expires_hours: Hours until expiry (default 8)
        notes: Optional notes
        contract_id: Contract ID for close/cancel (uses active if not specified)
        closure_commit: Git commit SHA for close
        cancel_reason: Reason for cancellation
        status_filter: Filter list by status
        include_archived: Include archived in list
    
    Returns:
        Contract info or operation result
    """
    from ck3lens.work_contracts import (
        open_contract, close_contract, cancel_contract,
        get_active_contract, list_contracts, flush_old_contracts,
        CANONICAL_DOMAINS, CAPABILITIES,
    )
    from ck3lens.agent_mode import get_agent_mode
    
    trace = _get_trace()
    agent_mode = get_agent_mode()
    
    # Null mode check - agent must initialize mode first
    if agent_mode is None and command == "open":
        return {
            "error": "Agent mode not initialized",
            "guidance": "Ask the user which mode to use, then call ck3_get_mode_instructions() with their choice.",
            "modes": {
                "ck3lens": "CK3 modding - search database, edit live mods, resolve conflicts",
                "ck3raven-dev": "Infrastructure development - modify ck3raven source code",
            },
            "example_prompt": "Which mode should I operate in? 'ck3lens' for CK3 modding or 'ck3raven-dev' for infrastructure work?",
        }
    
    if command == "open":
        if not intent:
            return {"error": "intent required for open command"}
        if not canonical_domains:
            return {"error": "canonical_domains required for open command"}
        
        # Validate domains
        invalid = set(canonical_domains) - CANONICAL_DOMAINS
        if invalid:
            return {
                "error": f"Invalid canonical domains: {invalid}",
                "valid_domains": list(CANONICAL_DOMAINS),
            }
        
        try:
            contract = open_contract(
                intent=intent,
                canonical_domains=canonical_domains,
                allowed_paths=allowed_paths,
                capabilities=capabilities,
                expires_hours=expires_hours,
                agent_mode=agent_mode,
                notes=notes,
            )
            
            trace.log("ck3lens.contract.open", {
                "intent": intent,
                "canonical_domains": canonical_domains,
            }, {"contract_id": contract.contract_id})
            
            return {
                "success": True,
                "contract_id": contract.contract_id,
                "expires_at": contract.expires_at,
                "capabilities": contract.capabilities,
                "allowed_paths": contract.allowed_paths,
            }
        except Exception as e:
            return {"error": str(e)}
    
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
            
            return {
                "success": True,
                "contract_id": contract.contract_id,
                "closed_at": contract.closed_at,
                "closure_commit": contract.closure_commit,
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
            return {
                "has_active_contract": True,
                "contract_id": active.contract_id,
                "intent": active.intent,
                "canonical_domains": active.canonical_domains,
                "capabilities": active.capabilities,
                "allowed_paths": active.allowed_paths,
                "expires_at": active.expires_at,
                "created_at": active.created_at,
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
        
        return {
            "count": len(contracts),
            "contracts": [
                {
                    "contract_id": c.contract_id,
                    "intent": c.intent,
                    "status": c.status,
                    "canonical_domains": c.canonical_domains,
                    "created_at": c.created_at,
                    "closed_at": c.closed_at,
                }
                for c in contracts
            ],
        }
    
    elif command == "flush":
        archived = flush_old_contracts()
        
        trace.log("ck3lens.contract.flush", {}, {"archived": archived})
        
        return {
            "success": True,
            "archived": archived,
            "message": f"Archived {archived} contracts from previous days",
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
) -> dict:
    """
    Execute a shell command with CLW policy enforcement.
    
    Mode-aware behavior:
    - ck3lens mode: Limited to CK3/mod-related commands within playset scope
    - ck3raven-dev mode: Broader access for infrastructure work (USE THIS instead of run_in_terminal)
    
    This is the ONLY safe way for agents to run shell commands.
    All commands are evaluated against the policy engine:
    
    - Safe commands (cat, git status, etc.) → Allowed automatically
    - Risky commands (rm *.py, git push) → Require approval token
    - Blocked commands (rm -rf /) → Always denied
    
    If a command requires a token, use ck3_token to request one first,
    then pass the token_id here.
    
    Args:
        command: Shell command to execute
        working_dir: Working directory (defaults to ck3raven root)
        target_paths: Files/dirs being affected (helps scope validation)
        token_id: Approval token ID (required for risky commands)
        dry_run: If True, only check policy without executing
    
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
    from ck3lens.work_contracts import get_active_contract
    from ck3lens.world_adapter import normalize_path_input
    import subprocess
    
    trace = _get_trace()
    
    # ==========================================================================
    # CANONICAL PATH NORMALIZATION for working_dir and target_paths
    # Use normalize_path_input() for all path resolution.
    # ==========================================================================
    
    world = _get_world()
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
                    "policy": {"decision": "NOT_FOUND", "reason": f"Working directory not visible in {world.mode} mode"},
                    "error": resolution.error_message or f"Reference not found: {working_dir}",
                    "hint": "This path is outside the visibility scope for the current agent mode",
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
                        "policy": {"decision": "NOT_FOUND", "reason": f"Target path not visible in {world.mode} mode"},
                        "error": resolution.error_message or f"Reference not found: {target}",
                        "hint": "This path is outside the visibility scope for the current agent mode",
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
        from ck3lens.policy.tokens import validate_token
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
        
        # Validate token
        token_valid, token_msg = validate_token(
            token_id,
            "SCRIPT_EXECUTE",
            script_hash=wip_script_info.get("script_hash"),
        )
        
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
    # Pattern: classify → map to OperationType → enforce_and_log → execute
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
                timeout=300,  # 5 minute timeout
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
                timeout=300,  # 5 minute timeout
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
            "output": "Command timed out after 5 minutes",
            "exit_code": -1,
            "policy": policy_info,
            "error": "timeout",
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
    
    command=request   → Request a new approval token
    command=list      → List active tokens
    command=validate  → Check if a token is valid for an operation
    command=revoke    → Revoke a token
    
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
    from ck3lens.work_contracts import get_active_contract
    
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
    source_filter: Optional[str] = None,
    mod_filter: Optional[list[str]] = None,
    game_folder: Optional[str] = None,
    symbol_type: Optional[str] = None,
    adjacency: Literal["auto", "strict", "fuzzy"] = "auto",
    limit: int = 25,
    definitions_only: bool = False,
    verbose: bool = False,
    no_lens: bool = False
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
        source_filter: Filter by source ("vanilla" or mod name)
        mod_filter: List of mod names to search (e.g., ["vanilla", "MSC"])
        game_folder: Limit to CK3 folder (e.g., "events", "common/traits", "common/on_action")
        symbol_type: Filter symbols by type (trait, event, decision, etc.)
        adjacency: Pattern expansion ("auto", "strict", "fuzzy")
        limit: Max results per category (default 25)
        definitions_only: If True, skip references (faster but less useful)
        verbose: More detail (all matches per file, snippets)
        no_lens: If True, search ALL content (not just active playset)
    
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
        ck3_search("brave", mod_filter=["MSC"])  # Only in MSC mod
        ck3_search("has_trait", limit=100, verbose=True)  # More results
    """
    db = _get_db()
    trace = _get_trace()
    lens = _get_lens(no_lens=no_lens)
    
    # Build file_pattern from game_folder if provided
    effective_file_pattern = file_pattern
    if game_folder:
        # Normalize folder path
        folder = game_folder.replace("\\", "/").strip("/")
        effective_file_pattern = f"{folder}/%"
    
    # Build source filter from mod_filter if provided
    effective_source = source_filter
    # Note: mod_filter is handled in the query layer
    
    # By default, include references (usages) - this is what compatch needs
    include_references = not definitions_only
    
    result = db.unified_search(
        lens=lens,
        query=query,
        file_pattern=effective_file_pattern,
        source_filter=effective_source,
        symbol_type=symbol_type,
        adjacency=adjacency,
        limit=limit,
        matches_per_file=5 if not verbose else 50,
        include_references=include_references,
        verbose=verbose
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
        if not mod_filter and not source_filter:
            guidance_parts.append("To narrow: use mod_filter=['ModName'] or source_filter='vanilla'.")
        
        guidance = " ".join(guidance_parts)
    
    result["truncated"] = truncated
    if guidance:
        result["guidance"] = guidance
    
    trace.log("ck3lens.search", {
        "query": query,
        "file_pattern": effective_file_pattern,
        "game_folder": game_folder,
        "mod_filter": mod_filter,
        "symbol_type": symbol_type,
        "limit": limit,
        "definitions_only": definitions_only,
        "no_lens": no_lens
    }, {
        "symbols_count": result["symbols"]["count"],
        "references_count": total_refs,
        "content_count": content_count,
        "truncated": truncated
    })
    
    return result


# ============================================================================
# Symbol Tools (from ck3raven DB)
# ============================================================================

@mcp.tool()
def ck3_confirm_not_exists(
    name: str,
    symbol_type: Optional[str] = None,
    no_lens: bool = False
) -> dict:
    """
    Confirm a symbol does NOT exist before claiming it's missing.
    
    This performs an exhaustive fuzzy search to prevent false negatives.
    ALWAYS call this before writing code that assumes something doesn't exist.
    
    Args:
        name: Symbol name to search for
        symbol_type: Optional type filter (trait, decision, etc.)
        no_lens: If True, search ALL content (not just active playset)
    
    Returns:
        - can_claim_not_exists: True if exhaustive search found nothing
        - similar_matches: Any similar symbols found (might be what you meant)
    """
    db = _get_db()
    trace = _get_trace()
    lens = _get_lens(no_lens=no_lens)
    
    result = db.confirm_not_exists(lens, name, symbol_type)
    
    trace.log("ck3lens.confirm_not_exists", {
        "name": name,
        "symbol_type": symbol_type
    }, {
        "can_claim": result["can_claim_not_exists"],
        "adjacencies_count": len(result.get("adjacencies", []))
    })
    
    return result


# @mcp.tool()  # DEPRECATED - use ck3_file(command="get")
def ck3_get_file(
    file_path: str,
    include_ast: bool = False,
    max_bytes: int = 200000,
    no_lens: bool = False
) -> dict:
    """
    DEPRECATED: Use ck3_file(command="get", path=...) instead.
    
    Get file content from the ck3raven database.
    
    Args:
        file_path: Relative path to the file (e.g., "common/traits/00_traits.txt")
        include_ast: If True, also return parsed AST representation
        max_bytes: Maximum content bytes to return
        no_lens: If True, search ALL content (not just active playset)
    
    Returns:
        File content (raw and/or AST)
    """
    db = _get_db()
    trace = _get_trace()
    lens = _get_lens(no_lens=no_lens)
    
    result = db.get_file(lens, relpath=file_path, include_ast=include_ast)
    
    trace.log("ck3lens.get_file", {
        "file_path": file_path,
        "include_ast": include_ast
    }, {
        "found": result is not None,
        "content_length": len(result.get("content", "")) if result else 0
    })
    
    if result:
        result["lens"] = lens.playset_name if lens else "ALL CONTENT (no lens)"
    
    return result or {"error": f"File not found: {file_path}"}


@mcp.tool()
def ck3_qr_conflicts(
    path_pattern: Optional[str] = None,
    symbol_name: Optional[str] = None,
    symbol_type: Optional[str] = None
) -> dict:
    """
    Quick-resolve conflicts using load order (SQLResolver).
    
    Shows what "wins" for each conflicting symbol based on CK3's
    merge rules and mod load order.
    
    Args:
        path_pattern: Filter by file path pattern (glob-style)
        symbol_name: Filter by specific symbol name
        symbol_type: Filter by symbol type
    
    Returns:
        List of conflicts with winner/loser mods and resolution type
    """
    db = _get_db()
    trace = _get_trace()
    lens = _get_lens()
    
    if not lens:
        return {"error": "No active playset. Use ck3_set_active_playset first."}
    
    conflicts = db.get_conflicts(
        lens=lens,
        folder=path_pattern,
        symbol_type=symbol_type
    )
    
    trace.log("ck3lens.qr_conflicts", {
        "path_pattern": path_pattern,
        "symbol_name": symbol_name,
        "symbol_type": symbol_type
    }, {"conflicts_count": len(conflicts)})
    
    return {"conflicts": conflicts}


@mcp.tool()
def ck3_get_symbol_conflicts(
    symbol_type: Optional[str] = None,
    game_folder: Optional[str] = None,
    limit: int = 100,
    include_compatch: bool = False
) -> dict:
    """
    Fast ID-level conflict detection using the symbols table.
    
    This is INSTANT compared to the slow contribution_units analysis.
    Finds symbols (traits, events, decisions, etc.) defined by multiple mods.
    
    By default, filters out conflicts involving compatibility patches (compatch mods)
    since they are DESIGNED to conflict - that's their purpose.
    
    Args:
        symbol_type: Filter by type (trait, event, decision, on_action, etc.)
        game_folder: Filter by CK3 folder (e.g., "common/traits", "events")
        limit: Maximum conflicts to return (default 100)
        include_compatch: If True, include conflicts from compatch mods
                          (default False - compatch conflicts are expected)
    
    Returns:
        {
            "conflict_count": int,
            "conflicts": [
                {
                    "name": str,
                    "symbol_type": str,
                    "source_count": int,  # How many mods define this
                    "sources": [{"mod": str, "file": str, "line": int}],
                    "is_compatch_conflict": bool
                }
            ],
            "compatch_conflicts_hidden": int  # Conflicts filtered out
        }
    
    Examples:
        ck3_get_symbol_conflicts()  # All non-compatch conflicts
        ck3_get_symbol_conflicts(symbol_type="trait")  # Only trait conflicts
        ck3_get_symbol_conflicts(game_folder="common/on_action")  # Only on_action conflicts
        ck3_get_symbol_conflicts(include_compatch=True)  # Include compatch conflicts
    """
    db = _get_db()
    trace = _get_trace()
    lens = _get_lens()
    
    if not lens:
        return {"error": "No active playset. Use ck3_set_active_playset first."}
    
    result = db.get_symbol_conflicts(
        lens=lens,
        symbol_type=symbol_type,
        game_folder=game_folder,
        limit=limit,
        include_compatch=include_compatch
    )
    
    trace.log("ck3lens.get_symbol_conflicts", {
        "symbol_type": symbol_type,
        "game_folder": game_folder,
        "include_compatch": include_compatch
    }, {
        "conflict_count": result["conflict_count"],
        "compatch_hidden": result["compatch_conflicts_hidden"]
    })
    
    return result


# ============================================================================
# ARCHIVED: Legacy Local Mod Operations
# ============================================================================
# The following tools have been DELETED (December 30, 2025):
# - ck3_list_local_mods() → Use ck3_file(command="list", mod_name=...)
# - ck3_read_live_file() → Use ck3_file(command="read", mod_name=..., rel_path=...)
# - ck3_write_file() → Use ck3_file(command="write", mod_name=..., rel_path=..., content=...)
# - ck3_edit_file() → Use ck3_file(command="edit", mod_name=..., rel_path=..., old_content=..., new_content=...)
# - ck3_delete_file() → Use ck3_file(command="delete", mod_name=..., rel_path=...)
# - ck3_rename_file() → Use ck3_file(command="rename", mod_name=..., rel_path=..., new_path=...)
# - ck3_refresh_file() → Use ck3_file(command="refresh", mod_name=..., rel_path=...)
#
# These used the BANNED "local_mods" module which has been deleted.
# All file operations now flow through ck3_file unified tool with enforcement.
# ============================================================================


@mcp.tool()
def ck3_create_override_patch(
    source_path: str,
    target_mod: str,
    mode: Literal["override_patch", "full_replace"],
    initial_content: str | None = None,
) -> dict:
    """
    Create an override patch file in a live mod.
    
    ⚠️ MODE: ck3lens only. Cannot write to mod files in ck3raven-dev mode.
    
    Use this when you need to patch a file from vanilla or a non-editable mod.
    Automatically creates the correct directory structure and follows naming conventions.
    
    Modes:
    - override_patch: Creates zzz_msc_[original_name].txt (for adding/modifying specific units)
    - full_replace: Creates [original_name].txt (full replacement, last-wins)
    
    Args:
        source_path: The relative path being overridden (e.g., "common/traits/00_traits.txt")
        target_mod: Name of the live mod to create the patch in (e.g., "MSC")
        mode: "override_patch" for partial override, "full_replace" for full replacement
        initial_content: Optional initial content for the file. If None, creates with comment header.
    
    Returns:
        {
            "success": bool,
            "created_path": str,  # Relative path in target mod
            "full_path": str,     # Absolute filesystem path
            "mode": str,
            "source_path": str
        }
    
    Example:
        ck3_create_override_patch(
            source_path="common/traits/00_traits.txt",
            target_mod="MSC",
            mode="override_patch"
        )
        # Creates: MSC/common/traits/zzz_msc_00_traits.txt
    """
    from pathlib import Path as P
    from datetime import datetime
    
    session = _get_session()
    trace = _get_trace()
    
    # Parse source path
    source = P(source_path)
    if source.is_absolute() or ".." in source.parts:
        return {"success": False, "error": "source_path must be relative without .."}
    
    # Determine output filename
    if mode == "override_patch":
        # zzz_msc_[original_name].txt
        new_name = f"zzz_msc_{source.name}"
    elif mode == "full_replace":
        # Same name (will override due to load order)
        new_name = source.name
    else:
        return {"success": False, "error": f"Invalid mode: {mode}. Use 'override_patch' or 'full_replace'"}
    
    # Build target path (same directory structure)
    target_rel_path = str(source.parent / new_name)
    
    # Generate default content if not provided
    if initial_content is None:
        initial_content = f"""# Override patch for: {source_path}
# Created: {datetime.now().strftime("%Y-%m-%d %H:%M")}
# Mode: {mode}
# 
# Add your overrides below. For 'override_patch' mode, only include
# the specific units you want to override/add.

"""
    
    # Write the file
    result = local_mods.write_file(session, target_mod, target_rel_path, initial_content)
    
    if result.get("success"):
        # Get the full path for navigation
        local_mod = session.get_local_mod(target_mod)
        full_path = str(local_mod.path / target_rel_path) if local_mod else None
        
        trace.log("ck3lens.create_override_patch", {
            "source_path": source_path,
            "target_mod": target_mod,
            "mode": mode
        }, {"success": True, "created_path": target_rel_path})
        
        return {
            "success": True,
            "created_path": target_rel_path,
            "full_path": full_path,
            "mode": mode,
            "source_path": source_path,
            "message": f"Created override patch: {target_rel_path}"
        }
    else:
        trace.log("ck3lens.create_override_patch", {
            "source_path": source_path,
            "target_mod": target_mod,
            "mode": mode
        }, {"success": False, "error": result.get("error")})
        
        return result


# @mcp.tool()  # DEPRECATED - use ck3_file(command="list")
def ck3_list_live_files(
    mod_name: str,
    path_prefix: Optional[str] = None,
    pattern: Optional[str] = None
) -> dict:
    """
    DEPRECATED: Use ck3_file(command="list", mod_name=...) instead.
    
    List files in a mod.
    
    Args:
        mod_name: Name of the live mod
        path_prefix: Filter by path prefix (e.g., "common/traits")
        pattern: Glob pattern filter (e.g., "*.txt")
    
    Returns:
        List of file paths
    """
    session = _get_session()
    trace = _get_trace()
    
    result = local_mods.list_local_files(session, mod_name, path_prefix, pattern)
    
    trace.log("ck3lens.list_live_files", {
        "mod_name": mod_name,
        "path_prefix": path_prefix,
        "pattern": pattern
    }, {"files_count": len(result.get("files", []))})
    
    return result


# ============================================================================
# Filesystem Wrapper Tools (Traceable)
# ============================================================================
# These tools wrap VS Code's built-in filesystem operations to make them
# traceable by the policy validator. Agents should use these instead of
# read_file, list_dir, grep_search directly when working in ck3lens mode.

# @mcp.tool()  # DEPRECATED - use ck3_file(command="read")
def ck3_read_raw_file(
    path: str,
    justification: str,
    start_line: int = 1,
    end_line: Optional[int] = None
) -> dict:
    """
    DEPRECATED: Use ck3_file(command="read", path=..., justification=...) instead.
    
    Read a file from the filesystem with tracing and justification.
    
    USE THIS instead of VS Code's read_file when you need to read files
    outside the ck3raven database. Every read is logged for policy validation.
    
    Args:
        path: Absolute path to the file to read
        justification: Why this file needs to be read (for audit trail)
        start_line: Line to start reading from (1-indexed)
        end_line: Line to stop reading at (inclusive, None = EOF)
    
    Returns:
        {"success": bool, "content": str, "lines_read": int, "total_lines": int}
    """
    trace = _get_trace()
    file_path = Path(path)
    
    # Log the attempt
    trace.log("ck3lens.read_raw_file", {
        "path": str(file_path),
        "justification": justification,
        "start_line": start_line,
        "end_line": end_line,
    }, {})
    
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {path}"}
    
    if not file_path.is_file():
        return {"success": False, "error": f"Not a file: {path}"}
    
    try:
        # Read all lines
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
        
        total_lines = len(all_lines)
        
        # Apply line range
        start_idx = max(0, start_line - 1)
        end_idx = end_line if end_line else total_lines
        end_idx = min(end_idx, total_lines)
        
        selected_lines = all_lines[start_idx:end_idx]
        content = ''.join(selected_lines)
        
        result = {
            "success": True,
            "content": content,
            "lines_read": len(selected_lines),
            "total_lines": total_lines,
            "path": str(file_path),
        }
        
        trace.log("ck3lens.read_raw_file.result", {
            "path": str(file_path),
        }, {"lines_read": len(selected_lines), "total_lines": total_lines})
        
        return result
        
    except Exception as e:
        return {"success": False, "error": str(e)}


# @mcp.tool()  # DEPRECATED - use ck3_folder(command="list")
def ck3_list_raw_dir(
    path: str,
    justification: str,
    pattern: Optional[str] = None,
    recursive: bool = False
) -> dict:
    """
    DEPRECATED: Use ck3_folder(command="list", path=..., justification=...) instead.
    
    List directory contents from the filesystem with tracing.
    
    USE THIS instead of VS Code's list_dir when you need to browse files
    outside the ck3raven database. Every listing is logged for policy validation.
    
    Args:
        path: Absolute path to the directory
        justification: Why this directory needs to be listed (for audit trail)
        pattern: Optional glob pattern to filter files (e.g., "*.txt")
        recursive: If True, list recursively
    
    Returns:
        {"success": bool, "entries": [{"name": str, "is_dir": bool, "path": str}]}
    """
    trace = _get_trace()
    dir_path = Path(path)
    
    # Log the attempt
    trace.log("ck3lens.list_raw_dir", {
        "path": str(dir_path),
        "justification": justification,
        "pattern": pattern,
        "recursive": recursive,
    }, {})
    
    if not dir_path.exists():
        return {"success": False, "error": f"Directory not found: {path}"}
    
    if not dir_path.is_dir():
        return {"success": False, "error": f"Not a directory: {path}"}
    
    try:
        entries = []
        
        if recursive:
            # Recursive listing with optional pattern
            if pattern:
                for p in dir_path.rglob(pattern):
                    entries.append({
                        "name": p.name,
                        "is_dir": p.is_dir(),
                        "path": str(p),
                        "relpath": str(p.relative_to(dir_path)),
                    })
            else:
                for p in dir_path.rglob("*"):
                    entries.append({
                        "name": p.name,
                        "is_dir": p.is_dir(),
                        "path": str(p),
                        "relpath": str(p.relative_to(dir_path)),
                    })
        else:
            # Non-recursive listing
            for p in dir_path.iterdir():
                if pattern:
                    import fnmatch
                    if not fnmatch.fnmatch(p.name, pattern):
                        continue
                entries.append({
                    "name": p.name,
                    "is_dir": p.is_dir(),
                    "path": str(p),
                })
        
        result = {
            "success": True,
            "entries": entries,
            "count": len(entries),
            "path": str(dir_path),
        }
        
        trace.log("ck3lens.list_raw_dir.result", {
            "path": str(dir_path),
        }, {"count": len(entries)})
        
        return result
        
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def ck3_grep_raw(
    path: str,
    query: str,
    justification: str,
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
        justification: Why this search is needed (for audit trail)
        is_regex: If True, treat query as regex
        include_pattern: Glob pattern to filter files (e.g., "*.txt")
    
    Returns:
        {"success": bool, "matches": [{"file": str, "line": int, "content": str}]}
    """
    import re
    from ck3lens.agent_mode import get_agent_mode
    
    trace = _get_trace()
    search_path = Path(path)
    
    # WorldAdapter visibility enforcement (preferred path)
    world = _get_world()
    if world is not None:
        resolution = world.resolve(str(search_path))
        if not resolution.found:
            return {
                "success": False,
                "error": resolution.error_message or f"Path not visible in {world.mode} mode: {path}",
                "mode": world.mode,
                "hint": "This path is outside the visibility scope for the current agent mode",
            }
        # Use resolved absolute path
        search_path = resolution.absolute_path
    else:
        # Fallback: Legacy lens enforcement for ck3lens mode
        mode = get_agent_mode()
        if mode == "ck3lens":
            playset_scope = _get_playset_scope()
            if playset_scope and not playset_scope.is_path_in_scope(search_path):
                location_type, _ = playset_scope.get_path_location(search_path)
                return {
                    "success": False,
                    "error": f"Path outside active playset scope: {path}",
                    "location_type": location_type,
                    "hint": "ck3lens mode restricts filesystem access to paths within the active playset (vanilla + active mods)",
                }
    
    # Log the attempt
    trace.log("ck3lens.grep_raw", {
        "path": str(search_path),
        "query": query,
        "justification": justification,
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
    justification: str,
    base_path: Optional[str] = None
) -> dict:
    """
    Search for files by glob pattern with tracing.
    
    USE THIS instead of VS Code's file_search when you need to find files
    outside the ck3raven database. Every search is logged for policy validation.
    
    In ck3lens mode: Only paths within the active playset (vanilla + mods) are searchable.
    In ck3raven-dev mode: Broader access for infrastructure testing.
    
    Args:
        pattern: Glob pattern to match (e.g., "**/*.txt", "common/traits/*.txt")
        justification: Why this search is needed (for audit trail)
        base_path: Base directory to search in (defaults to vanilla game path)
    
    Returns:
        {"success": bool, "files": [str], "count": int}
    """
    from ck3lens.agent_mode import get_agent_mode
    
    trace = _get_trace()
    scope = _get_session_scope()
    
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
    
    # Lens enforcement for ck3lens mode
    if mode == "ck3lens":
        playset_scope = _get_playset_scope()
        if playset_scope and not playset_scope.is_path_in_scope(search_base):
            location_type, _ = playset_scope.get_path_location(search_base)
            return {
                "success": False,
                "error": f"Base path outside active playset scope: {base_path}",
                "location_type": location_type,
                "hint": "ck3lens mode restricts filesystem access to paths within the active playset (vanilla + active mods)",
            }
    
    # Log the attempt
    trace.log("ck3lens.file_search", {
        "pattern": pattern,
        "base_path": str(search_base),
        "justification": justification,
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


@mcp.tool()
def ck3_get_scope_info() -> dict:
    """
    Get current session scope information.
    
    Returns the active lens (playset) used for all scoped operations.
    The lens is like wearing glasses - it filters what you see in the database.
    
    Returns:
        {
            "lens_active": bool,
            "playset_id": int or None,
            "playset_name": str,
            "mod_count": int,
            "mods": [{name, workshop_id}]
        }
    """
    lens = _get_lens(no_lens=False)
    scope = _get_session_scope()
    
    if not lens:
        return {
            "lens_active": False,
            "playset_id": None,
            "playset_name": scope.get("playset_name"),
            "source": scope.get("source", "none"),
            "mod_count": len(scope.get("active_mod_ids", set())),
            "mods": [],
            "hint": "No active playset lens. Check playset_manifest.json or use ck3_playset(command='switch')."
        }
    
    # Get mod info from scope (file-based)
    mod_list = scope.get("mod_list", [])
    enabled_mods = [m for m in mod_list if m.get("enabled", True)]
    
    # Format mod info for output
    mods_info = []
    for i, m in enumerate(enabled_mods[:25]):  # Limit to first 25
        mods_info.append({
            "name": m.get("name", "Unknown"),
            "steam_id": m.get("steam_id"),
            "load_order": m.get("load_order", i),
            "is_compatch": m.get("is_compatch", False),
        })
    
    return {
        "lens_active": True,
        "playset_id": lens.playset_id,
        "playset_name": lens.playset_name,
        "source": scope.get("source", "json"),
        "vanilla_cv_id": lens.vanilla_cv_id,
        "mod_cv_count": len(lens.mod_cv_ids),
        "mod_count": len(enabled_mods),
        "mods": mods_info,
        "truncated": len(enabled_mods) > 25,
    }


# ============================================================================
# Validation Tools
# DEPRECATED: Use ck3_validate(target=...) instead
# ============================================================================

# @mcp.tool()  # DEPRECATED - use ck3_validate(target="syntax")
def ck3_validate_syntax(
    content: str,
    filename: str = "inline.txt"
) -> dict:
    """
    DEPRECATED: Use ck3_validate(target="syntax", content=...) instead.
    
    Validate CK3 script syntax.
    
    Use this tool to check if CK3 script content is syntactically valid
    BEFORE writing it to a file. This is the primary syntax validation tool
    for agents working on CK3 mod content.
    
    Args:
        content: CK3 script content to validate
        filename: Optional filename for error messages
    
    Returns:
        {
            "valid": bool,           # True if no syntax errors
            "error_count": int,      # Number of errors found
            "errors": [              # List of syntax errors
                {
                    "line": 5,
                    "column": 10,
                    "message": "Expected value after operator",
                    "severity": "error"
                },
                ...
            ]
        }
    
    Example usage:
        result = ck3_validate_syntax(my_script)
        if result["valid"]:
            # Safe to write
            ck3_write_file(mod_name, path, my_script)
        else:
            # Fix errors first
            for err in result["errors"]:
                print(f"Line {err['line']}: {err['message']}")
    """
    trace = _get_trace()
    
    result = parse_content(content, filename, recover=True)
    
    # Simplify errors for agent consumption
    simple_errors = []
    for err in result.get("errors", []):
        simple_errors.append({
            "line": err.get("line", 0),
            "column": err.get("column", 0),
            "message": err.get("message", "Unknown error"),
            "severity": err.get("severity", "error"),
        })
    
    response = {
        "valid": result["success"],
        "error_count": len(simple_errors),
        "errors": simple_errors,
    }
    
    trace.log("ck3lens.validate_syntax", {
        "filename": filename,
        "content_length": len(content)
    }, response)
    
    return response


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


# @mcp.tool()  # DEPRECATED - use ck3_validate(target="bundle")
def ck3_validate_artifact_bundle(artifact_bundle: dict) -> dict:
    """
    DEPRECATED: Use ck3_validate(target="bundle", artifact_bundle=...) instead.
    
    Validate an ArtifactBundle contract.
    
    Checks path policy, parses content, and validates references.
    
    Args:
        artifact_bundle: ArtifactBundle as dict (artifacts list with path/content/format)
    
    Returns:
        ValidationReport with errors and warnings
    """
    trace = _get_trace()
    
    bundle = ArtifactBundle.model_validate(artifact_bundle)
    report = validate_artifact_bundle(bundle)
    
    trace.log("ck3lens.validate_artifact_bundle", {
        "artifact_count": len(bundle.artifacts)
    }, {"ok": report.ok, "errors": len(report.errors)})
    
    return report.model_dump()


# @mcp.tool()  # DEPRECATED - use ck3_validate(target="policy")
def ck3_validate_policy(
    mode: Literal["ck3lens", "ck3raven-dev"],
    artifact_bundle: dict | None = None,
    session_start_ts: float | None = None,
) -> dict:
    """
    DEPRECATED: Use ck3_validate(target="policy", mode=...) instead.
    
    Validate agent behavior against the policy specification.
    
    This is the delivery gate for agent outputs. It checks:
    - Global rules (trace required, no silent assumptions)
    - Mode-specific rules (ck3lens or ck3raven-dev)
    - ArtifactBundle validation (if provided)
    
    Call this before claiming a task is complete to verify policy compliance.
    
    Args:
        mode: Agent mode - "ck3lens" for modding, "ck3raven-dev" for infrastructure
        artifact_bundle: Optional ArtifactBundle dict being delivered
        session_start_ts: Optional timestamp to limit trace scope
    
    Returns:
        PolicyOutcome with deliverable status, violations, and summary
    """
    import time
    
    trace = _get_trace()
    
    # Check policy health first - fail fast if broken
    health = _check_policy_health()
    if not health["healthy"]:
        error_result = {
            "status": "error",
            "deliverable": False,
            "policy_healthy": False,
            "error": f"Policy module broken: {health['error']}",
            "message": "âš ï¸ POLICY ENFORCEMENT IS DOWN. Agent must stop work until fixed.",
            "violations": [{
                "severity": "error",
                "rule_id": "POLICY_IMPORT_FAILED",
                "message": f"Cannot import policy module: {health['error']}",
            }],
            "rules_checked": [],
        }
        trace.log("ck3lens.validate_policy", {
            "mode": mode,
            "policy_error": health["error"],
        }, {"deliverable": False, "error": "policy_broken"})
        return error_result
    
    # Import policy module (no reload - validation must be pure and deterministic)
    from ck3lens import policy
    
    # Get trace events
    if session_start_ts:
        trace_events = trace.get_session_trace(session_start_ts)
    else:
        # Get last 100 events
        trace_events = trace.read_recent(max_events=100)
    
    # Get playset context
    playset_id = _get_playset_id()
    
    # Run validation
    result = policy.validate_for_mode(
        mode=mode,
        trace=trace_events,
        artifact_bundle_dict=artifact_bundle,
        playset_id=playset_id,
    )
    
    # Add health status to result
    result["policy_healthy"] = True
    
    trace.log("ck3lens.validate_policy", {
        "mode": mode,
        "has_artifact_bundle": artifact_bundle is not None,
        "trace_events": len(trace_events),
    }, {
        "deliverable": result.get("deliverable", False),
        "error_count": result.get("summary", {}).get("violations_error_count", 0),
    })
    
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


# @mcp.tool()  # DEPRECATED - use ck3_validate(target="python")
def ck3_validate_python(
    file_path: str | None = None,
    code_snippet: str | None = None,
) -> dict:
    """
    DEPRECATED: Use ck3_validate(target="python", file_path=..., content=...) instead.
    
    Validate Python code for syntax and import errors.
    
    Use this before deploying any Python code changes to ensure they are valid.
    This is MANDATORY for ck3raven-dev mode work.
    
    Provide either:
    - file_path: Path to a Python file to validate
    - code_snippet: Python code string to validate
    
    Args:
        file_path: Absolute path to Python file to check
        code_snippet: Python code string to validate (if no file_path)
    
    Returns:
        {
            "valid": bool,
            "errors": [...],
            "warnings": [...]
        }
    """
    import ast
    import subprocess
    import tempfile
    
    trace = _get_trace()
    errors: list[dict] = []
    warnings: list[dict] = []
    
    code_to_check = None
    source_desc = "snippet"
    
    if file_path:
        from pathlib import Path
        p = Path(file_path)
        if not p.exists():
            return {"valid": False, "errors": [{"message": f"File not found: {file_path}"}], "warnings": []}
        code_to_check = p.read_text(encoding="utf-8")
        source_desc = str(p)
    elif code_snippet:
        code_to_check = code_snippet
    else:
        return {"valid": False, "errors": [{"message": "Provide either file_path or code_snippet"}], "warnings": []}
    
    # Step 1: Python AST syntax check
    try:
        ast.parse(code_to_check)
    except SyntaxError as e:
        errors.append({
            "type": "syntax",
            "line": e.lineno,
            "column": e.offset,
            "message": str(e.msg),
            "source": source_desc
        })
        # Syntax error is fatal - return immediately
        trace.log("ck3lens.validate_python", {"source": source_desc}, {"valid": False, "error_count": 1})
        return {"valid": False, "errors": errors, "warnings": []}
    
    # Step 2: Try to compile (catches more issues)
    try:
        compile(code_to_check, source_desc, 'exec')
    except Exception as e:
        errors.append({
            "type": "compile",
            "message": str(e),
            "source": source_desc
        })
    
    # Step 3: For file paths, try running Python -m py_compile
    if file_path and not errors:
        try:
            result = subprocess.run(
                ["python", "-m", "py_compile", file_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                errors.append({
                    "type": "py_compile",
                    "message": result.stderr.strip(),
                    "source": source_desc
                })
        except subprocess.TimeoutExpired:
            warnings.append({"type": "timeout", "message": "py_compile check timed out"})
        except Exception as e:
            warnings.append({"type": "subprocess", "message": f"Could not run py_compile: {e}"})
    
    # Step 4: Basic import checking for common issues
    import_lines = [line for line in code_to_check.split('\n') if line.strip().startswith(('import ', 'from '))]
    for line in import_lines[:10]:  # Check first 10 imports
        # Just note them - actual import validation would require execution context
        pass
    
    valid = len(errors) == 0
    trace.log("ck3lens.validate_python", {
        "source": source_desc,
        "code_length": len(code_to_check)
    }, {"valid": valid, "errors": len(errors), "warnings": len(warnings)})
    
    return {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "imports_found": len(import_lines),
        "note": "For full type checking, use get_errors tool on saved files."
    }


# ============================================================================
# Semantic Analysis Tools (Autocomplete, Hover, Reference Validation)
# ============================================================================

# @mcp.tool()  # DEPRECATED - use ck3_validate(target="references")
def ck3_validate_references(
    content: str,
    filename: str = "inline.txt"
) -> dict:
    """
    DEPRECATED: Use ck3_validate(target="references", content=...) instead.
    
    Validate all references in CK3 script content.
    
    Checks that all symbol references (traits, events, decisions, etc.)
    exist in the symbol database. Returns diagnostics for undefined references
    with suggestions for similar symbols.
    
    Args:
        content: CK3 script content to validate
        filename: For context in error messages
    
    Returns:
        {
            "success": bool (true if no errors),
            "errors": [...],
            "warnings": [...]
        }
    """
    from ck3lens.semantic import validate_content
    
    session = _get_session()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    result = validate_content(
        content=content,
        db_path=session.db_path,
        playset_id=playset_id,
        filename=filename
    )
    
    trace.log("ck3lens.validate_references", {
        "filename": filename,
        "content_length": len(content)
    }, {
        "success": result["success"],
        "errors": len(result["errors"]),
        "warnings": len(result["warnings"])
    })
    
    return result


@mcp.tool()
def ck3_get_completions(
    content: str,
    line: int,
    column: int,
    filename: str = "inline.txt"
) -> dict:
    """
    Get autocomplete suggestions at cursor position.
    
    Provides intelligent completions based on context:
    - After 'has_trait = ' suggests traits
    - After 'trigger_event = ' suggests events
    - Block names suggest scope changers and keywords
    
    Args:
        content: Full file content
        line: 1-based line number
        column: 0-based column position
        filename: For context
    
    Returns:
        {
            "completions": [
                {
                    "label": "brave",
                    "kind": "symbol",
                    "detail": "trait (vanilla)",
                    "documentation": "Defined in: common/traits/00_traits.txt",
                    "insertText": "brave"
                },
                ...
            ]
        }
    """
    from ck3lens.semantic import get_completions
    
    session = _get_session()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    completions = get_completions(
        content=content,
        line=line,
        column=column,
        db_path=session.db_path,
        playset_id=playset_id
    )
    
    trace.log("ck3lens.get_completions", {
        "line": line,
        "column": column
    }, {
        "completions_count": len(completions)
    })
    
    return {"completions": completions}


@mcp.tool()
def ck3_get_hover(
    content: str,
    line: int,
    column: int,
    filename: str = "inline.txt"
) -> dict:
    """
    Get hover documentation for symbol at cursor position.
    
    Returns markdown-formatted documentation including:
    - Symbol name and type
    - Source mod (vanilla or mod name)
    - Definition file and line number
    
    Args:
        content: Full file content
        line: 1-based line number
        column: 0-based column position
        filename: For context
    
    Returns:
        {
            "content": "**brave**\n\nType: `trait`\n\nSource: `vanilla`\n\nFile: `common/traits/00_traits.txt`",
            "range": {"line": 5, "column": 10, "end_line": 5, "end_column": 15}
        }
        or null if no symbol at position
    """
    from ck3lens.semantic import get_hover
    
    session = _get_session()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    result = get_hover(
        content=content,
        line=line,
        column=column,
        db_path=session.db_path,
        playset_id=playset_id
    )
    
    trace.log("ck3lens.get_hover", {
        "line": line,
        "column": column
    }, {
        "found": result is not None
    })
    
    return result or {"content": None}


@mcp.tool()
def ck3_get_definition(
    content: str,
    line: int,
    column: int,
    filename: str = "inline.txt"
) -> dict:
    """
    Get definition location for symbol at cursor position.
    
    Returns file path and line number where the symbol is defined.
    
    Args:
        content: Full file content
        line: 1-based line number
        column: 0-based column position
        filename: For context
    
    Returns:
        {
            "file": "common/traits/00_traits.txt",
            "line": 42,
            "mod": "vanilla"
        }
        or null if not found
    """
    from ck3lens.semantic import SemanticAnalyzer
    
    session = _get_session()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    analyzer = SemanticAnalyzer(session.db_path, playset_id)
    try:
        location = analyzer.get_definition(content, line, column, filename)
        
        trace.log("ck3lens.get_definition", {
            "line": line,
            "column": column
        }, {
            "found": location is not None
        })
        
        if location:
            return {
                "file": location.file_path,
                "line": location.line,
                "mod": location.mod
            }
        return {"file": None}
    finally:
        analyzer.close()


# ============================================================================
# Git Operations
# DEPRECATED: Use ck3_git(command=..., mod_name=...) instead
# ============================================================================

# @mcp.tool()  # DEPRECATED - use ck3_git(command="status")
def ck3_git_status(mod_name: str) -> dict:
    """
    DEPRECATED: Use ck3_git(command="status", mod_name=...) instead.
    
    Get git status for a live mod.
    
    Args:
        mod_name: Name of the live mod
    
    Returns:
        Git status (staged, unstaged, untracked files)
    """
    session = _get_session()
    trace = _get_trace()
    
    result = git_ops.git_status(session, mod_name)
    
    trace.log("ck3lens.git_status", {"mod_name": mod_name}, {"success": result.get("success", False)})
    
    return result


# @mcp.tool()  # DEPRECATED - use ck3_git(command="diff")
def ck3_git_diff(
    mod_name: str,
    file_path: Optional[str] = None,
    staged: bool = False
) -> dict:
    """
    DEPRECATED: Use ck3_git(command="diff", mod_name=..., file_path=...) instead.
    
    Get git diff for a live mod.
    
    Args:
        mod_name: Name of the live mod
        file_path: Optional specific file to diff
        staged: If True, show staged changes
    
    Returns:
        Diff output
    """
    session = _get_session()
    trace = _get_trace()
    
    result = git_ops.git_diff(session, mod_name, file_path, staged)
    
    trace.log("ck3lens.git_diff", {"mod_name": mod_name, "file_path": file_path}, {"success": result.get("success", False)})
    
    return result


# @mcp.tool()  # DEPRECATED - use ck3_git(command="add")
def ck3_git_add(
    mod_name: str,
    paths: Optional[list[str]] = None,
    all_files: bool = False
) -> dict:
    """
    DEPRECATED: Use ck3_git(command="add", mod_name=..., files=..., all_files=...) instead.
    
    Stage files for commit in a live mod.
    
    Args:
        mod_name: Name of the live mod
        paths: List of paths to stage (default: all if all_files=True)
        all_files: If True, stage all changes (git add -A)
    Returns:
        Success status
    """
    session = _get_session()
    trace = _get_trace()
    
    
    result = git_ops.git_add(session, mod_name, paths, all_files)
    
    trace.log("ck3lens.git_add", {"mod_name": mod_name, "paths": paths, "all_files": all_files}, {"success": result.get("success", False)})


# @mcp.tool()  # DEPRECATED - use ck3_git(command="commit")
def ck3_git_commit(
    mod_name: str,
    message: str
) -> dict:
    """
    DEPRECATED: Use ck3_git(command="commit", mod_name=..., message=...) instead.
    
    Commit staged changes in a live mod.
    
    Args:
        mod_name: Name of the live mod
        message: Commit message
    
    Returns:
        Commit info (hash, etc.)
    """
    session = _get_session()
    trace = _get_trace()
    
    result = git_ops.git_commit(session, mod_name, message)
    
    trace.log("ck3lens.git_commit", {"mod_name": mod_name, "message": message[:50]}, {"success": result.get("success", False)})
    
    return result


# @mcp.tool()  # DEPRECATED - use ck3_git(command="push")
def ck3_git_push(mod_name: str) -> dict:
    """
    DEPRECATED: Use ck3_git(command="push", mod_name=...) instead.
    
    Push commits to remote for a live mod.
    
    Args:
        mod_name: Name of the live mod
    
    Returns:
        Push result
    """
    session = _get_session()
    trace = _get_trace()
    
    result = git_ops.git_push(session, mod_name)
    
    trace.log("ck3lens.git_push", {"mod_name": mod_name}, {"success": result.get("success", False)})
    
    return result


# @mcp.tool()  # DEPRECATED - use ck3_git(command="pull")
def ck3_git_pull(mod_name: str) -> dict:
    """
    DEPRECATED: Use ck3_git(command="pull", mod_name=...) instead.
    
    Pull latest changes from remote for a live mod.
    
    Args:
        mod_name: Name of the live mod
    
    Returns:
        Pull result
    """
    session = _get_session()
    trace = _get_trace()
    
    result = git_ops.git_pull(session, mod_name)
    
    trace.log("ck3lens.git_pull", {"mod_name": mod_name}, {"success": result.get("success", False)})
    
    return result


# @mcp.tool()  # DEPRECATED - use ck3_git(command="log")
def ck3_git_log(
    mod_name: str,
    limit: int = 10,
    file_path: Optional[str] = None
) -> dict:
    """
    DEPRECATED: Use ck3_git(command="log", mod_name=..., limit=...) instead.
    
    Get git log for a live mod.
    
    Args:
        mod_name: Name of the live mod
        limit: Max commits to return
        file_path: Optional path to filter commits
    
    Returns:
        List of commits
    """
    session = _get_session()
    trace = _get_trace()
    
    result = git_ops.git_log(session, mod_name, limit, file_path)
    
    trace.log("ck3lens.git_log", {"mod_name": mod_name, "limit": limit}, {"success": result.get("success", False)})
    
    return result


# ============================================================================
# Playset Management Tools (JSON-based)
# DEPRECATED: Use ck3_playset(command=...) instead
# ============================================================================

# @mcp.tool()  # DEPRECATED - use ck3_playset(command="get")
def ck3_get_active_playset() -> dict:
    """
    DEPRECATED: Use ck3_playset(command="get") instead.
    
    Get information about the currently active playset.
    
    Playsets are now stored as JSON files in the playsets/ folder.
    This returns the active playset's configuration including:
    - Mod list with load order
    - Agent briefing notes
    - Live mods (writable)
    
    Returns:
        Playset details including name, mods, and agent_briefing
    """
    trace = _get_trace()
    
    scope = _get_session_scope(force_refresh=True)
    
    if scope.get("source") == "none":
        return {
            "error": "No active playset found",
            "hint": "Create a playset JSON in playsets/ folder or set active_playset.json"
        }
    
    result = {
        "playset_name": scope.get("playset_name"),
        "source": scope.get("source"),
        "file_path": scope.get("file_path"),
        "mod_count": len(scope.get("active_mod_ids", set())),
        "active_mod_ids": list(scope.get("active_mod_ids", set())),
        "active_roots": list(scope.get("active_roots", set())),
        "vanilla_root": scope.get("vanilla_root"),
        "local_mods_folder": scope.get("local_mods_folder"),
        "editable_mods": scope.get("editable_mods", []),
        "agent_briefing": scope.get("agent_briefing", {}),
        "sub_agent_config": scope.get("sub_agent_config", {}),
    }
    
    # Include mod list if available
    if scope.get("mod_list"):
        result["mods"] = scope["mod_list"]
    
    trace.log("ck3lens.get_active_playset", {}, {
        "mod_count": result["mod_count"],
        "source": result["source"]
    })
    
    return result


# @mcp.tool()  # DEPRECATED - use ck3_playset(command="list")
def ck3_list_playsets() -> dict:
    """
    DEPRECATED: Use ck3_playset(command="list") instead.
    
    List all available playsets from the playsets/ folder.
    
    Playsets are JSON files that define:
    - Which mods are in the playset
    - Agent briefing notes for error analysis
    - Live mods the agent can edit
    
    Returns:
        List of available playsets
    """
    trace = _get_trace()
    
    playsets = _list_available_playsets()
    
    # Mark which one is active
    active_scope = _get_session_scope()
    active_file = active_scope.get("file_path")
    
    for p in playsets:
        p["is_active"] = p["file_path"] == active_file
    
    result = {
        "playsets": playsets,
        "count": len(playsets),
        "playsets_dir": str(PLAYSETS_DIR),
    }
    
    trace.log("ck3lens.list_playsets", {}, {"count": len(playsets)})
    
    return result


# @mcp.tool()  # DEPRECATED - use ck3_playset(command="switch")
def ck3_switch_playset(playset_name: str) -> dict:
    """
    DEPRECATED: Use ck3_playset(command="switch", playset_name=...) instead.
    
    Switch the active playset by name or file path.
    
    This changes which playset is used for all lens-scoped operations.
    The switch takes effect immediately for new searches.
    
    Args:
        playset_name: Name of the playset (matches playset_name or filename)
    
    Returns:
        Success status with new active playset info
    """
    global _session_scope
    trace = _get_trace()
    
    # Find matching playset
    target_file = None
    
    if PLAYSETS_DIR.exists():
        for f in PLAYSETS_DIR.glob("*.json"):
            if f.name.endswith(".schema.json"):
                continue
            
            # Check if filename matches
            if playset_name.lower() in f.stem.lower():
                target_file = f
                break
            
            # Check if playset_name inside file matches
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if playset_name.lower() in data.get("playset_name", "").lower():
                    target_file = f
                    break
            except Exception:
                pass
    
    if not target_file:
        return {
            "success": False,
            "error": f"Playset not found: {playset_name}",
            "available": [p["name"] for p in _list_available_playsets()]
        }
    
    # Write active_playset.json pointer
    try:
        ACTIVE_PLAYSET_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACTIVE_PLAYSET_FILE.write_text(json.dumps({
            "active_playset": str(target_file),
            "switched_at": datetime.now().isoformat()
        }, indent=2), encoding="utf-8")
    except Exception as e:
        return {"success": False, "error": f"Failed to write pointer: {e}"}
    
    # Invalidate cache to force reload
    _session_scope = None
    
    # Load new scope
    new_scope = _get_session_scope(force_refresh=True)
    
    trace.log("ck3lens.switch_playset", {
        "playset_name": playset_name,
        "target_file": str(target_file)
    }, {"success": True})
    
    return {
        "success": True,
        "message": f"Switched to playset: {new_scope.get('playset_name')}",
        "playset_name": new_scope.get("playset_name"),
        "file_path": str(target_file),
        "mod_count": len(new_scope.get("active_mod_ids", set()))
    }


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


# @mcp.tool()  # DEPRECATED - use ck3_playset(command="add_mod")
def ck3_add_mod_to_playset(
    mod_identifier: str,
    position: Optional[int] = None,
    before_mod: Optional[str] = None,
    after_mod: Optional[str] = None
) -> dict:
    """
    DEPRECATED: Use ck3_playset(command="add_mod", mod_name=...) instead.
    
    Add a mod to the active playset, with full ingestion and symbol extraction.
    
    This is a comprehensive operation that:
    1. Finds the mod (by workshop ID, name, or path)
    2. Ingests files if not already indexed
    3. Extracts symbols for search
    4. Adds to playset at specified position
    
    Args:
        mod_identifier: Workshop ID, mod name, or filesystem path
        position: Explicit load order position (0-indexed)
        before_mod: Insert before this mod (by name or workshop ID)
        after_mod: Insert after this mod (by name or workshop ID)
    
    Returns:
        Success status with mod details
    """
    db = _get_db()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    # Import ck3raven modules for ingestion
    from ck3raven.db.ingest import ingest_mod, get_or_create_mod_package
    from ck3raven.parser import parse_source
    from ck3raven.db.symbols import extract_symbols_from_ast
    
    # Step 1: Find the mod
    mod_path = None
    workshop_id = None
    mod_name = None
    
    # Check if it's a workshop ID
    if mod_identifier.isdigit():
        workshop_id = mod_identifier
        # Check if already in database
        existing = db.conn.execute(
            "SELECT mod_package_id, name, source_path FROM mod_packages WHERE workshop_id = ?",
            (workshop_id,)
        ).fetchone()
        if existing:
            mod_name = existing[1]
            mod_path = Path(existing[2]) if existing[2] else None
        else:
            # Look for it in workshop folder
            workshop_path = Path("C:/Program Files (x86)/Steam/steamapps/workshop/content/1158310") / workshop_id
            if workshop_path.exists():
                mod_path = workshop_path
                mod_name = f"Workshop Mod {workshop_id}"
    
    # Check if it's a path
    elif "/" in mod_identifier or "\\" in mod_identifier:
        mod_path = Path(mod_identifier)
        if mod_path.exists():
            mod_name = mod_path.name
            # Try to extract workshop ID from path
            if "1158310" in str(mod_path):
                parts = str(mod_path).split("1158310")
                if len(parts) > 1:
                    potential_id = parts[1].strip("/\\").split("/")[0].split("\\")[0]
                    if potential_id.isdigit():
                        workshop_id = potential_id
    
    # Otherwise search by name
    else:
        search_result = db.conn.execute("""
            SELECT mod_package_id, name, workshop_id, source_path
            FROM mod_packages WHERE LOWER(name) LIKE LOWER(?)
            ORDER BY mod_package_id LIMIT 1
        """, (f"%{mod_identifier}%",)).fetchone()
        if search_result:
            mod_name = search_result[1]
            workshop_id = search_result[2]
            mod_path = Path(search_result[3]) if search_result[3] else None
    
    if not mod_path or not mod_path.exists():
        return {"error": f"Could not find mod: {mod_identifier}"}
    
    # Step 2: Ingest if needed
    mod_pkg, ingest_result = ingest_mod(
        conn=db.conn,
        mod_path=mod_path,
        name=mod_name,
        workshop_id=workshop_id,
        force=False
    )
    
    # Get content_version_id
    cv_row = db.conn.execute("""
        SELECT content_version_id, file_count FROM content_versions
        WHERE mod_package_id = ? ORDER BY ingested_at DESC LIMIT 1
    """, (mod_pkg.mod_package_id,)).fetchone()
    
    if not cv_row:
        return {"error": "Failed to ingest mod files"}
    
    content_version_id = cv_row[0]
    file_count = cv_row[1]
    
    # Step 3: Extract symbols if not already done
    existing_symbols = db.conn.execute(
        "SELECT COUNT(*) FROM symbols WHERE content_version_id = ?",
        (content_version_id,)
    ).fetchone()[0]
    
    symbols_extracted = 0
    if existing_symbols == 0:
        # Extract symbols
        rows = db.conn.execute("""
            SELECT f.file_id, f.relpath, f.content_hash FROM files f
            WHERE f.content_version_id = ? AND f.relpath LIKE '%.txt'
        """, (content_version_id,)).fetchall()
        
        batch = []
        for row in rows:
            content_row = db.conn.execute(
                "SELECT COALESCE(content_text, content_blob) as content FROM file_contents WHERE content_hash = ?",
                (row[2],)
            ).fetchone()
            if not content_row:
                continue
            
            content = content_row[0]
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='replace')
            if content.startswith('\ufeff'):
                content = content[1:]
            
            try:
                ast = parse_source(content, filename=row[1])
                for sym in extract_symbols_from_ast(ast.to_dict(), row[1], row[2]):
                    batch.append((sym.kind, sym.name, sym.scope, None, row[0], 
                                 content_version_id, None, sym.line, None))
            except:
                pass
        
        if batch:
            db.conn.executemany("""
                INSERT INTO symbols (symbol_type, name, scope, defining_ast_id, defining_file_id,
                                    content_version_id, ast_node_path, line_number, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
        symbols_extracted = len(batch)
    else:
        symbols_extracted = existing_symbols
    
    # Step 4: Determine load order position
    if before_mod:
        # Find the mod to insert before
        ref_row = db.conn.execute("""
            SELECT pm.load_order_index FROM playset_mods pm
            JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
            JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE pm.playset_id = ? AND (mp.name LIKE ? OR mp.workshop_id = ?)
        """, (playset_id, f"%{before_mod}%", before_mod)).fetchone()
        if ref_row:
            position = ref_row[0]
    elif after_mod:
        # Find the mod to insert after
        ref_row = db.conn.execute("""
            SELECT pm.load_order_index FROM playset_mods pm
            JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
            JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE pm.playset_id = ? AND (mp.name LIKE ? OR mp.workshop_id = ?)
        """, (playset_id, f"%{after_mod}%", after_mod)).fetchone()
        if ref_row:
            position = ref_row[0] + 1
    
    if position is None:
        # Add at end
        max_order = db.conn.execute(
            "SELECT MAX(load_order_index) FROM playset_mods WHERE playset_id = ?",
            (playset_id,)
        ).fetchone()[0]
        position = (max_order or -1) + 1
    
    # Shift existing mods if inserting in the middle
    db.conn.execute("""
        UPDATE playset_mods SET load_order_index = load_order_index + 1
        WHERE playset_id = ? AND load_order_index >= ?
    """, (playset_id, position))
    
    # Insert the new mod
    db.conn.execute("""
        INSERT OR REPLACE INTO playset_mods (playset_id, content_version_id, load_order_index, enabled)
        VALUES (?, ?, ?, 1)
    """, (playset_id, content_version_id, position))
    
    db.conn.commit()
    
    trace.log("ck3lens.add_mod_to_playset", {
        "mod_identifier": mod_identifier, "position": position
    }, {
        "mod_name": mod_name, "files": file_count, "symbols": symbols_extracted
    })
    
    return {
        "success": True,
        "mod_name": mod_name,
        "workshop_id": workshop_id,
        "content_version_id": content_version_id,
        "load_order_position": position,
        "files_indexed": file_count,
        "symbols_extracted": symbols_extracted,
        "was_already_indexed": ingest_result.stats.content_reused if ingest_result else False
    }


# @mcp.tool()  # DEPRECATED - use ck3_playset(command="remove_mod")
def ck3_remove_mod_from_playset(
    mod_identifier: str
) -> dict:
    """
    DEPRECATED: Use ck3_playset(command="remove_mod", mod_name=...) instead.
    
    Remove a mod from the active playset.
    
    Note: This only removes from the playset, not from the database.
    The mod's files and symbols remain indexed for potential re-use.
    
    Args:
        mod_identifier: Workshop ID or mod name
    
    Returns:
        Success status
    """
    db = _get_db()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    # Find the content_version_id for this mod
    if mod_identifier.isdigit():
        row = db.conn.execute("""
            SELECT pm.content_version_id, mp.name, pm.load_order_index
            FROM playset_mods pm
            JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
            JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE pm.playset_id = ? AND mp.workshop_id = ?
        """, (playset_id, mod_identifier)).fetchone()
    else:
        row = db.conn.execute("""
            SELECT pm.content_version_id, mp.name, pm.load_order_index
            FROM playset_mods pm
            JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
            JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE pm.playset_id = ? AND LOWER(mp.name) LIKE LOWER(?)
        """, (playset_id, f"%{mod_identifier}%")).fetchone()
    
    if not row:
        return {"error": f"Mod not found in playset: {mod_identifier}"}
    
    content_version_id = row[0]
    mod_name = row[1]
    removed_position = row[2]
    
    # Remove from playset
    db.conn.execute("""
        DELETE FROM playset_mods WHERE playset_id = ? AND content_version_id = ?
    """, (playset_id, content_version_id))
    
    # Shift remaining mods down
    db.conn.execute("""
        UPDATE playset_mods SET load_order_index = load_order_index - 1
        WHERE playset_id = ? AND load_order_index > ?
    """, (playset_id, removed_position))
    
    db.conn.commit()
    
    trace.log("ck3lens.remove_mod_from_playset", {"mod_identifier": mod_identifier},
              {"mod_name": mod_name, "position": removed_position})
    
    return {
        "success": True,
        "mod_name": mod_name,
        "removed_from_position": removed_position
    }


# @mcp.tool()  # DEPRECATED - use ck3_playset(command="create")
def ck3_create_playset_from_indexed(
    playset_name: str | None = None,
    playset_file: str | None = None,
    set_active: bool = True
) -> dict:
    """
    DEPRECATED: Use ck3_playset(command="create", name=...) instead.
    
    Create a playset from already-indexed content in the database.
    
    This links existing content_versions to a new playset. Use this after
    running the daemon build, which ingests mods but doesn't create playsets.
    
    If playset_file is provided, it reads the active_mod_paths.json format:
    {
        "playset_name": "...",
        "paths": [
            {"name": "ModName", "steam_id": "123", "load_order": 0, "enabled": true},
            ...
        ]
    }
    
    If no file is provided, creates a playset with ALL indexed mods in
    the order they were ingested (vanilla first).
    
    Args:
        playset_name: Name for the playset (default: from file or "Default Playset")
        playset_file: Path to active_mod_paths.json (optional)
        set_active: Whether to make this the active playset (default: True)
    
    Returns:
        Playset creation result with linked mods count
    """
    import json
    db = _get_db()
    trace = _get_trace()
    
    # Load playset file if provided
    mod_entries = []
    final_name = playset_name
    
    if playset_file:
        path = Path(playset_file)
        if not path.exists():
            return {"error": f"File not found: {playset_file}"}
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not final_name and "playset_name" in data:
            final_name = data["playset_name"]
        
        if "paths" in data:
            mod_entries = data["paths"]
    
    if not final_name:
        final_name = "Default Playset"
    
    # Get vanilla content_version_id and vanilla_version_id
    vanilla_cv = db.conn.execute("""
        SELECT content_version_id, vanilla_version_id 
        FROM content_versions WHERE kind = 'vanilla' 
        ORDER BY ingested_at DESC LIMIT 1
    """).fetchone()
    
    if not vanilla_cv:
        return {"error": "No vanilla content indexed. Run daemon build first."}
    
    vanilla_cv_id = vanilla_cv[0]
    vanilla_version_id = vanilla_cv[1]
    
    # Create the playset with vanilla_version_id
    db.conn.execute("""
        INSERT INTO playsets (name, vanilla_version_id, is_active, created_at, updated_at)
        VALUES (?, ?, ?, datetime('now'), datetime('now'))
    """, (final_name, vanilla_version_id, 1 if set_active else 0))
    db.conn.commit()
    
    playset_id = db.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # Deactivate other playsets if setting this one active
    if set_active:
        db.conn.execute("""
            UPDATE playsets SET is_active = 0 WHERE playset_id != ?
        """, (playset_id,))
    
    # Add vanilla as load_order -1 (before all mods)
    db.conn.execute("""
        INSERT INTO playset_mods (playset_id, content_version_id, load_order_index, enabled)
        VALUES (?, ?, -1, 1)
    """, (playset_id, vanilla_cv_id))
    
    linked_count = 1  # Vanilla
    skipped = []
    
    if mod_entries:
        # Link mods from the playset file
        for entry in mod_entries:
            if not entry.get("enabled", True):
                continue
            
            mod_name = entry.get("name", "")
            steam_id = entry.get("steam_id", "")
            mod_path = entry.get("path", "")
            load_order = entry.get("load_order", 0)
            
            cv_row = None
            
            # Try steam_id first (most reliable for workshop mods)
            if steam_id:
                cv_row = db.conn.execute("""
                    SELECT cv.content_version_id, mp.name
                    FROM content_versions cv
                    JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                    WHERE mp.workshop_id = ?
                    ORDER BY cv.ingested_at DESC LIMIT 1
                """, (steam_id,)).fetchone()
            
            # If not found by steam_id, try by source_path (for local mods)
            if not cv_row and mod_path:
                cv_row = db.conn.execute("""
                    SELECT cv.content_version_id, mp.name
                    FROM content_versions cv
                    JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                    WHERE mp.source_path = ?
                    ORDER BY cv.ingested_at DESC LIMIT 1
                """, (mod_path,)).fetchone()
            
            # Last resort: try by exact name
            if not cv_row:
                cv_row = db.conn.execute("""
                    SELECT cv.content_version_id, mp.name
                    FROM content_versions cv
                    JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                    WHERE mp.name = ?
                    ORDER BY cv.ingested_at DESC LIMIT 1
                """, (mod_name,)).fetchone()
            
            if not cv_row:
                skipped.append({"name": mod_name, "steam_id": steam_id, "reason": "not_in_database"})
                continue
            
            # Add to playset - use load_order directly from JSON
            db.conn.execute("""
                INSERT INTO playset_mods (playset_id, content_version_id, load_order_index, enabled)
                VALUES (?, ?, ?, 1)
            """, (playset_id, cv_row[0], load_order))
            
            linked_count += 1
    else:
        # No file provided - link ALL indexed mods
        all_mods = db.conn.execute("""
            SELECT cv.content_version_id, mp.name
            FROM content_versions cv
            JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE cv.kind = 'mod'
            ORDER BY cv.ingested_at ASC
        """).fetchall()
        
        for idx, row in enumerate(all_mods, start=1):
            db.conn.execute("""
                INSERT INTO playset_mods (playset_id, content_version_id, load_order_index, enabled)
                VALUES (?, ?, ?, 1)
            """, (playset_id, row[0], idx))
            linked_count += 1
    
    db.conn.commit()
    
    # Update global playset_id
    if set_active:
        global _playset_id
        _playset_id = playset_id
    
    trace.log("ck3lens.create_playset_from_indexed", {
        "source": playset_file or "all_indexed",
        "playset_name": final_name
    }, {
        "playset_id": playset_id,
        "linked": linked_count,
        "skipped": len(skipped)
    })
    
    return {
        "success": True,
        "playset_id": playset_id,
        "playset_name": final_name,
        "vanilla_version_id": vanilla_version_id,
        "mods_linked": linked_count,
        "mods_skipped": skipped if skipped else None,
        "is_active": set_active
    }


# @mcp.tool()  # DEPRECATED - use ck3_playset(command="import")
def ck3_import_playset_from_launcher(
    launcher_json_path: str | None = None,
    launcher_json_content: str | None = None,
    playset_name: str | None = None,
    local_mod_paths: list[str] | None = None,
    set_active: bool = True
) -> dict:
    """
    DEPRECATED: Use ck3_playset(command="import", ...) instead.
    
    Import a playset from CK3 Launcher JSON export.
    
    The launcher JSON can be exported from Paradox Launcher:
    Settings > Export Playset (creates .json file)
    
    Args:
        launcher_json_path: Path to the launcher JSON file
        launcher_json_content: Raw JSON content (alternative to path)
        playset_name: Override name (default: from JSON or "Imported Playset")
        local_mod_paths: Additional local mod paths to add at end of load order
        set_active: Whether to make this the active playset (default: True)
    
    Returns:
        Playset creation result with linked mods count
    """
    import json
    db = _get_db()
    trace = _get_trace()
    
    # Load JSON
    if launcher_json_path:
        path = Path(launcher_json_path)
        if not path.exists():
            return {"error": f"File not found: {launcher_json_path}"}
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    elif launcher_json_content:
        data = json.loads(launcher_json_content)
    else:
        return {"error": "Must provide launcher_json_path or launcher_json_content"}
    
    # Extract playset name
    final_name = playset_name
    if not final_name:
        if "name" in data:
            final_name = data["name"]
        elif "playset" in data and "name" in data["playset"]:
            final_name = data["playset"]["name"]
        else:
            final_name = "Imported Playset"
    
    # Extract mods from JSON
    mod_entries = []
    if "mods" in data:
        mod_entries = data["mods"]
    elif "playset" in data and "mods" in data["playset"]:
        mod_entries = data["playset"]["mods"]
    
    # Create the playset
    db.conn.execute("""
        INSERT INTO playsets (name, created_at) VALUES (?, datetime('now'))
    """, (final_name,))
    db.conn.commit()
    
    playset_id = db.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # Process mods
    linked_count = 0
    skipped = []
    load_order = 1  # Start at 1 (0 is typically vanilla)
    
    for mod in mod_entries:
        # Get steam_id from mod entry
        steam_id = None
        if "steamId" in mod:
            steam_id = str(mod["steamId"])
        elif "steam_id" in mod:
            steam_id = str(mod["steam_id"])
        elif "id" in mod:
            steam_id = str(mod["id"])
        
        if not steam_id:
            skipped.append({"reason": "no_steam_id", "mod": mod})
            continue
        
        # Find in database by workshop_id
        cv_row = db.conn.execute("""
            SELECT cv.content_version_id, mp.name
            FROM content_versions cv
            JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE mp.workshop_id = ?
            ORDER BY cv.ingested_at DESC LIMIT 1
        """, (steam_id,)).fetchone()
        
        if not cv_row:
            mod_name = mod.get("displayName") or mod.get("name") or steam_id
            skipped.append({"steam_id": steam_id, "name": mod_name, "reason": "not_in_database"})
            continue
        
        # Add to playset
        db.conn.execute("""
            INSERT INTO playset_mods (playset_id, content_version_id, load_order_index, enabled)
            VALUES (?, ?, ?, 1)
        """, (playset_id, cv_row[0], load_order))
        
        linked_count += 1
        load_order += 1
    
    # Add local mods at end
    local_linked = 0
    if local_mod_paths:
        for local_path in local_mod_paths:
            path = Path(local_path)
            if not path.exists():
                skipped.append({"path": local_path, "reason": "path_not_found"})
                continue
            
            # Find by source_path
            cv_row = db.conn.execute("""
                SELECT cv.content_version_id, mp.name
                FROM content_versions cv
                JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE mp.source_path LIKE ?
                ORDER BY cv.ingested_at DESC LIMIT 1
            """, (f"%{path.name}",)).fetchone()
            
            if cv_row:
                db.conn.execute("""
                    INSERT INTO playset_mods (playset_id, content_version_id, load_order_index, enabled)
                    VALUES (?, ?, ?, 1)
                """, (playset_id, cv_row[0], load_order))
                local_linked += 1
                load_order += 1
            else:
                skipped.append({"path": local_path, "reason": "not_in_database"})
    
    db.conn.commit()
    
    # Set as active if requested
    if set_active:
        global _session
        if _session:
            _session.playset_id = playset_id
    
    trace.log("ck3lens.import_playset_from_launcher", {
        "source": launcher_json_path or "inline_json",
        "playset_name": final_name
    }, {
        "playset_id": playset_id,
        "linked": linked_count,
        "local_linked": local_linked,
        "skipped": len(skipped)
    })
    
    return {
        "success": True,
        "playset_id": playset_id,
        "playset_name": final_name,
        "mods_linked": linked_count,
        "local_mods_linked": local_linked,
        "mods_skipped": skipped if skipped else None,
        "is_active": set_active,
        "next_steps": "Use ck3_add_mod_to_playset to add missing mods after ingesting them"
    }


# @mcp.tool()  # DEPRECATED - use ck3_playset(command="reorder")
def ck3_reorder_mod_in_playset(
    mod_identifier: str,
    new_position: int | None = None,
    before_mod: str | None = None,
    after_mod: str | None = None
) -> dict:
    """
    DEPRECATED: Use ck3_playset(command="reorder", mod_name=..., new_position=...) instead.
    
    Move a mod to a new position in the active playset's load order.
    
    Args:
        mod_identifier: Workshop ID or mod name to move
        new_position: Target position (0-indexed). 0=first loaded, higher=later
        before_mod: Move before this mod (by name or workshop ID)
        after_mod: Move after this mod (by name or workshop ID)
    
    Returns:
        Success status with old and new positions
    """
    db = _get_db()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    # Find the mod to move
    if mod_identifier.isdigit():
        row = db.conn.execute("""
            SELECT pm.content_version_id, mp.name, pm.load_order_index
            FROM playset_mods pm
            JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
            JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE pm.playset_id = ? AND mp.workshop_id = ?
        """, (playset_id, mod_identifier)).fetchone()
    else:
        row = db.conn.execute("""
            SELECT pm.content_version_id, mp.name, pm.load_order_index
            FROM playset_mods pm
            JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
            JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE pm.playset_id = ? AND LOWER(mp.name) LIKE LOWER(?)
        """, (playset_id, f"%{mod_identifier}%")).fetchone()
    
    if not row:
        return {"error": f"Mod not found in playset: {mod_identifier}"}
    
    content_version_id = row[0]
    mod_name = row[1]
    old_position = row[2]
    
    # Determine target position
    target_position = new_position
    
    if before_mod:
        ref_row = db.conn.execute("""
            SELECT pm.load_order_index FROM playset_mods pm
            JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
            JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE pm.playset_id = ? AND (mp.name LIKE ? OR mp.workshop_id = ?)
        """, (playset_id, f"%{before_mod}%", before_mod)).fetchone()
        if ref_row:
            target_position = ref_row[0]
    elif after_mod:
        ref_row = db.conn.execute("""
            SELECT pm.load_order_index FROM playset_mods pm
            JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
            JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE pm.playset_id = ? AND (mp.name LIKE ? OR mp.workshop_id = ?)
        """, (playset_id, f"%{after_mod}%", after_mod)).fetchone()
        if ref_row:
            target_position = ref_row[0] + 1
    
    if target_position is None:
        return {"error": "Must specify new_position, before_mod, or after_mod"}
    
    if target_position == old_position:
        return {"success": True, "mod_name": mod_name, "position": old_position, "message": "No change needed"}
    
    # Remove from old position
    db.conn.execute("""
        DELETE FROM playset_mods WHERE playset_id = ? AND content_version_id = ?
    """, (playset_id, content_version_id))
    
    # Shift mods to close the gap
    db.conn.execute("""
        UPDATE playset_mods SET load_order_index = load_order_index - 1
        WHERE playset_id = ? AND load_order_index > ?
    """, (playset_id, old_position))
    
    # Adjust target if moving down
    if target_position > old_position:
        target_position -= 1
    
    # Shift mods to make room at target
    db.conn.execute("""
        UPDATE playset_mods SET load_order_index = load_order_index + 1
        WHERE playset_id = ? AND load_order_index >= ?
    """, (playset_id, target_position))
    
    # Insert at target position
    db.conn.execute("""
        INSERT INTO playset_mods (playset_id, content_version_id, load_order_index, enabled)
        VALUES (?, ?, ?, 1)
    """, (playset_id, content_version_id, target_position))
    
    db.conn.commit()
    
    trace.log("ck3lens.reorder_mod", {
        "mod_identifier": mod_identifier
    }, {
        "mod_name": mod_name,
        "old_position": old_position,
        "new_position": target_position
    })
    
    return {
        "success": True,
        "mod_name": mod_name,
        "old_position": old_position,
        "new_position": target_position
    }


# ============================================================================
# Conflict Analysis Tools (Unit-Level)
# DEPRECATED: Use ck3_conflicts(command=...) instead
# ============================================================================

# @mcp.tool()  # DEPRECATED - use ck3_conflicts(command="scan")
def ck3_scan_unit_conflicts(
    folder_filter: str | None = None,
) -> dict:
    """
    Scan the active playset for unit-level conflicts.
    
    This is a comprehensive scan that:
    1. Extracts all ContributionUnits from parsed ASTs
    2. Groups them into ConflictUnits by unit_key
    3. Computes risk scores and merge capabilities
    
    A "unit" is a separately-resolvable block (decision, trait, on_action, etc.)
    
    Args:
        folder_filter: Optional folder path filter (e.g., "common/on_action")
    
    Returns:
        Scan results with conflict summary
    """
    db = _get_db()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    try:
        from ck3raven.resolver.conflict_analyzer import scan_playset_conflicts
        
        result = scan_playset_conflicts(
            db.conn,
            playset_id,
            folder_filter=folder_filter,
        )
        
        trace.log("ck3lens.scan_unit_conflicts", 
                  {"folder_filter": folder_filter},
                  {"conflicts_found": result["conflicts_found"]})
        
        return result
        
    except Exception as e:
        return {"error": str(e)}


# @mcp.tool()  # DEPRECATED - use ck3_conflicts(command="summary")
def ck3_get_conflict_summary() -> dict:
    """
    DEPRECATED: Use ck3_conflicts(command="summary") instead.
    
    Get a summary of all unit-level conflicts in the active playset.
    
    Returns:
        Summary with counts by risk level, domain, and resolution status
    """
    db = _get_db()
    playset_id = _get_playset_id()
    
    try:
        from ck3raven.resolver.conflict_analyzer import get_conflict_summary
        
        return get_conflict_summary(db.conn, playset_id)
        
    except Exception as e:
        return {"error": str(e)}


# @mcp.tool()  # DEPRECATED - use ck3_conflicts(command="list")
def ck3_list_conflict_units(
    risk_filter: str | None = None,
    domain_filter: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    List conflict units with optional filters.
    
    Args:
        risk_filter: Filter by risk level (low, med, high)
        domain_filter: Filter by domain (on_action, decision, trait, etc.)
        status_filter: Filter by resolution status (unresolved, resolved, deferred)
        limit: Maximum results to return
        offset: Offset for pagination
    
    Returns:
        List of conflict units with candidates
    """
    db = _get_db()
    playset_id = _get_playset_id()
    
    try:
        from ck3raven.resolver.conflict_analyzer import get_conflict_units
        
        conflicts = get_conflict_units(
            db.conn,
            playset_id,
            risk_filter=risk_filter,
            domain_filter=domain_filter,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
        )
        
        return {
            "playset_id": playset_id,
            "count": len(conflicts),
            "conflicts": conflicts,
        }
        
    except Exception as e:
        return {"error": str(e)}


# @mcp.tool()  # DEPRECATED - use ck3_conflicts(command="detail", conflict_id=...)
def ck3_get_conflict_detail(conflict_unit_id: str) -> dict:
    """
    Get detailed information about a specific conflict unit.
    
    Includes full candidate information with file content previews.
    
    Args:
        conflict_unit_id: The conflict unit ID
    
    Returns:
        Detailed conflict information
    """
    db = _get_db()
    
    try:
        from ck3raven.resolver.conflict_analyzer import get_conflict_unit_detail
        
        detail = get_conflict_unit_detail(db.conn, conflict_unit_id)
        
        if not detail:
            return {"error": f"Conflict unit not found: {conflict_unit_id}"}
        
        return detail
        
    except Exception as e:
        return {"error": str(e)}


# @mcp.tool()  # DEPRECATED - use ck3_conflicts(command="resolve", ...)
def ck3_resolve_conflict(
    conflict_unit_id: str,
    decision_type: Literal["winner", "defer"],
    winner_candidate_id: str | None = None,
    notes: str | None = None,
) -> dict:
    """
    Record a resolution decision for a conflict unit.
    
    Args:
        conflict_unit_id: The conflict unit ID
        decision_type: Type of resolution (winner = pick a winner, defer = handle later)
        winner_candidate_id: Required if decision_type is "winner" - the candidate to use
        notes: Optional notes explaining the decision
    
    Returns:
        Resolution result
    """
    import hashlib
    import json
    from datetime import datetime
    
    db = _get_db()
    trace = _get_trace()
    
    # Validate conflict exists
    conflict = db.conn.execute("""
        SELECT unit_key, domain FROM conflict_units WHERE conflict_unit_id = ?
    """, (conflict_unit_id,)).fetchone()
    
    if not conflict:
        return {"error": f"Conflict unit not found: {conflict_unit_id}"}
    
    if decision_type == "winner" and not winner_candidate_id:
        return {"error": "winner_candidate_id is required when decision_type is 'winner'"}
    
    # Validate winner candidate exists
    if winner_candidate_id:
        candidate = db.conn.execute("""
            SELECT source_name FROM conflict_candidates 
            WHERE conflict_unit_id = ? AND candidate_id = ?
        """, (conflict_unit_id, winner_candidate_id)).fetchone()
        
        if not candidate:
            return {"error": f"Candidate not found: {winner_candidate_id}"}
    
    # Create resolution
    resolution_id = hashlib.sha256(f"{conflict_unit_id}:{datetime.now().isoformat()}".encode()).hexdigest()[:16]
    
    db.conn.execute("""
        INSERT INTO resolution_choices 
        (resolution_id, conflict_unit_id, decision_type, winner_candidate_id, notes, applied_at, applied_by)
        VALUES (?, ?, ?, ?, ?, datetime('now'), 'user')
    """, (resolution_id, conflict_unit_id, decision_type, winner_candidate_id, notes))
    
    # Update conflict status
    db.conn.execute("""
        UPDATE conflict_units 
        SET resolution_status = ?, resolution_id = ?
        WHERE conflict_unit_id = ?
    """, ('deferred' if decision_type == 'defer' else 'resolved', resolution_id, conflict_unit_id))
    
    db.conn.commit()
    
    trace.log("ck3lens.resolve_conflict", 
              {"conflict_unit_id": conflict_unit_id, "decision_type": decision_type},
              {"resolution_id": resolution_id})
    
    return {
        "success": True,
        "resolution_id": resolution_id,
        "unit_key": conflict[0],
        "domain": conflict[1],
        "decision_type": decision_type,
        "winner_candidate_id": winner_candidate_id,
    }


# @mcp.tool()  # DEPRECATED - use ck3_conflicts(command="content", unit_key=...)
def ck3_get_unit_content(
    unit_key: str,
    source_filter: str | None = None,
) -> dict:
    """
    Get the content for all candidates of a unit_key.
    
    Useful for comparing what different mods define for the same unit.
    
    Args:
        unit_key: The unit key (e.g., "on_action:on_yearly_pulse")
        source_filter: Optional filter by source name
    
    Returns:
        All contributions for this unit_key with their content
    """
    db = _get_db()
    playset_id = _get_playset_id()
    
    # Contributions are now per-content_version, so we need to join through
    # playset_mods and vanilla to get only contributions in this playset
    query = """
        WITH playset_contribs AS (
            -- Vanilla contributions
            SELECT 
                cu.contrib_id, cu.content_version_id, cu.file_id,
                cu.domain, cu.unit_key, cu.relpath, cu.line_number,
                cu.merge_behavior, cu.summary, cu.node_hash,
                -1 as load_order_index, 'vanilla' as source_kind, 'vanilla' as source_name
            FROM contribution_units cu
            JOIN content_versions cv ON cu.content_version_id = cv.content_version_id
            JOIN vanilla_versions vv ON cv.vanilla_version_id = vv.vanilla_version_id
            JOIN playsets p ON p.vanilla_version_id = vv.vanilla_version_id
            WHERE p.playset_id = ? AND cv.kind = 'vanilla'
            
            UNION ALL
            
            -- Mod contributions
            SELECT 
                cu.contrib_id, cu.content_version_id, cu.file_id,
                cu.domain, cu.unit_key, cu.relpath, cu.line_number,
                cu.merge_behavior, cu.summary, cu.node_hash,
                pm.load_order_index, 'mod' as source_kind,
                COALESCE(mp.name, 'Unknown Mod') as source_name
            FROM contribution_units cu
            JOIN playset_mods pm ON cu.content_version_id = pm.content_version_id
            JOIN content_versions cv ON cu.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE pm.playset_id = ? AND pm.enabled = 1
        )
        SELECT 
            pc.contrib_id, pc.content_version_id, pc.file_id,
            pc.domain, pc.relpath, pc.line_number, pc.merge_behavior, pc.summary,
            pc.load_order_index, pc.source_kind, pc.source_name,
            fc.content_text
        FROM playset_contribs pc
        LEFT JOIN files f ON pc.file_id = f.file_id
        LEFT JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE pc.unit_key = ?
    """
    params = [playset_id, playset_id, unit_key]
    
    if source_filter:
        query += " AND (pc.source_kind = ? OR LOWER(pc.source_name) LIKE LOWER(?))"
        params.extend([source_filter, f"%{source_filter}%"])
    
    query += " ORDER BY load_order_index"
    
    contributions = []
    for row in db.conn.execute(query, params).fetchall():
        contributions.append({
            "contrib_id": row[0],
            "content_version_id": row[1],
            "file_id": row[2],
            "domain": row[3],
            "relpath": row[4],
            "line_number": row[5],
            "merge_behavior": row[6],
            "summary": row[7],
            "load_order_index": row[8],
            "source_kind": row[9],
            "source_name": row[10],
            "content": row[11][:5000] if row[11] else None,  # Limit content preview
        })
    
    return {
        "unit_key": unit_key,
        "count": len(contributions),
        "contributions": contributions,
    }


# ============================================================================
# Conflicts Report Tools
# DEPRECATED: Use ck3_conflicts(command=...) instead
# ============================================================================

# @mcp.tool()  # DEPRECATED - use ck3_conflicts(command="report", ...)
def ck3_generate_conflicts_report(
    domains_include: Optional[list[str]] = None,
    domains_exclude: Optional[list[str]] = None,
    paths_filter: Optional[str] = None,
    min_candidates: int = 2,
    min_risk_score: int = 0,
    output_format: Literal["summary", "json", "full"] = "summary"
) -> dict:
    """
    Generate a complete conflicts report for the active playset.
    
    This analyzes all file-level and ID-level conflicts and produces
    a deterministic, machine-readable report.
    
    Args:
        domains_include: Only analyze these domains (None = all)
        domains_exclude: Exclude these domains from analysis
        paths_filter: SQL LIKE pattern for paths (e.g., "common/on_action%")
        min_candidates: Minimum sources to count as conflict (default 2)
        min_risk_score: Only include conflicts with risk >= this score
        output_format: "summary" (CLI text), "json" (full JSON), "full" (both)
    
    Returns:
        Conflicts report in requested format
    """
    from ck3raven.resolver.report import ConflictsReportGenerator, report_summary_cli
    
    db = _get_db()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    generator = ConflictsReportGenerator(db.conn)
    report = generator.generate(
        playset_id=playset_id,
        domains_include=domains_include,
        domains_exclude=domains_exclude,
        paths_filter=paths_filter,
        min_candidates=min_candidates,
        min_risk_score=min_risk_score,
    )
    
    trace.log("ck3lens.generate_conflicts_report", {
        "domains_include": domains_include,
        "paths_filter": paths_filter,
    }, {
        "file_conflicts": report.summary.file_conflicts if report.summary else 0,
        "id_conflicts": report.summary.id_conflicts if report.summary else 0,
    })
    
    result = {}
    
    if output_format in ("summary", "full"):
        result["summary_text"] = report_summary_cli(report)
    
    if output_format in ("json", "full"):
        result["report"] = report.to_dict()
    
    # Always include key stats
    if report.summary:
        result["stats"] = {
            "file_conflicts": report.summary.file_conflicts,
            "id_conflicts": report.summary.id_conflicts,
            "high_risk": report.summary.high_risk_id_conflicts,
            "uncertain": report.summary.uncertain_conflicts,
        }
    
    return result


# @mcp.tool()  # DEPRECATED - use ck3_conflicts(command="high_risk", ...)
def ck3_get_high_risk_conflicts(
    domain: Optional[str] = None,
    min_risk_score: int = 60,
    limit: int = 20
) -> dict:
    """
    Get the highest-risk conflicts for prioritized review.
    
    Args:
        domain: Filter by domain (on_action, events, etc.)
        min_risk_score: Minimum risk score (default 60 = high risk)
        limit: Maximum conflicts to return
    
    Returns:
        List of high-risk conflicts sorted by risk score
    """
    from ck3raven.resolver.report import ConflictsReportGenerator
    
    db = _get_db()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    generator = ConflictsReportGenerator(db.conn)
    report = generator.generate(
        playset_id=playset_id,
        domains_include=[domain] if domain else None,
        min_candidates=2,
        min_risk_score=0,  # We'll filter ourselves
    )
    
    # Combine and sort by risk
    all_conflicts = []
    
    for fc in report.file_level:
        if fc.risk and fc.risk.score >= min_risk_score:
            all_conflicts.append({
                "type": "file",
                "key": fc.vpath,
                "domain": fc.domain,
                "risk_score": fc.risk.score,
                "risk_bucket": fc.risk.bucket,
                "reasons": fc.risk.reasons,
                "candidate_count": len(fc.candidates),
                "winner": fc.winner_by_load_order.source_name if fc.winner_by_load_order else None,
            })
    
    for ic in report.id_level:
        if ic.risk and ic.risk.score >= min_risk_score:
            all_conflicts.append({
                "type": "id",
                "key": ic.unit_key,
                "domain": ic.domain,
                "container": ic.container_vpath,
                "risk_score": ic.risk.score,
                "risk_bucket": ic.risk.bucket,
                "reasons": ic.risk.reasons,
                "candidate_count": len(ic.candidates),
                "winner": ic.engine_effective_winner.candidate_id if ic.engine_effective_winner else None,
                "merge_semantics": ic.merge_semantics.expected if ic.merge_semantics else None,
            })
    
    # Sort by risk score descending
    all_conflicts.sort(key=lambda x: x["risk_score"], reverse=True)
    
    trace.log("ck3lens.get_high_risk_conflicts", {
        "domain": domain,
        "min_risk_score": min_risk_score,
    }, {"count": len(all_conflicts)})
    
    return {
        "count": len(all_conflicts),
        "conflicts": all_conflicts[:limit],
    }


# ============================================================================
# Log Parsing Tools
# DEPRECATED: Use ck3_logs(source=..., command=...) instead
# ============================================================================

# @mcp.tool()  # DEPRECATED - use ck3_logs(source="error", command="summary")
def ck3_get_error_summary() -> dict:
    """
    DEPRECATED: Use ck3_logs(source="error", command="summary") instead.
    
    Get summary of errors from the current CK3 error.log.
    
    Parses the error log and returns:
    - Total error count
    - Errors grouped by priority (1=critical to 5=low)
    - Errors grouped by category (script, encoding, missing reference, etc.)
    - Errors grouped by mod
    - Number of cascading error patterns detected
    
    Use this as the first step when diagnosing game issues.
    
    Returns:
        Summary statistics from error.log
    """
    from ck3raven.analyzers.error_parser import CK3ErrorParser
    
    parser = CK3ErrorParser()
    
    try:
        parser.parse_log()
        parser.detect_cascading_errors()
    except FileNotFoundError:
        return {
            "error": "error.log not found",
            "hint": "Make sure CK3 has been run at least once",
        }
    
    return parser.get_summary()


# @mcp.tool()  # DEPRECATED - use ck3_logs(source="error", command="list")
def ck3_get_errors(
    priority: int | None = None,
    category: str | None = None,
    mod_filter: str | None = None,
    exclude_cascade_children: bool = True,
    limit: int = 50,
) -> dict:
    """
    Get filtered list of errors from the CK3 error.log.
    
    Args:
        priority: Max priority to include (1=critical, 2=high, 3=medium, 4=low, 5=very low)
        category: Filter by category (script_system_error, missing_reference, encoding_error, etc.)
        mod_filter: Filter by mod name (partial match)
        exclude_cascade_children: If True, exclude errors caused by cascade patterns
        limit: Maximum errors to return
    
    Returns:
        List of errors with details and fix hints
    """
    from ck3raven.analyzers.error_parser import CK3ErrorParser
    
    parser = CK3ErrorParser()
    
    try:
        parser.parse_log()
        parser.detect_cascading_errors()
    except FileNotFoundError:
        return {"error": "error.log not found"}
    
    errors = parser.get_errors(
        category=category,
        priority=priority,
        mod_filter=mod_filter,
        exclude_cascade_children=exclude_cascade_children,
        limit=limit,
    )
    
    # Convert to dicts with fix hints
    from ck3raven.analyzers.error_parser import ERROR_CATEGORIES
    
    results = []
    for error in errors:
        cat = next((c for c in ERROR_CATEGORIES if c.name == error.category), None)
        results.append({
            **error.to_dict(),
            "fix_hint": cat.fix_hint if cat else None,
        })
    
    return {
        "count": len(results),
        "total_in_log": parser.stats['total_errors'],
        "errors": results,
    }


# @mcp.tool()  # DEPRECATED - use ck3_logs(source="error", command="search", query=...)
def ck3_search_errors(
    query: str,
    limit: int = 30,
) -> dict:
    """
    Search errors in the CK3 error.log by message or file path.
    
    Args:
        query: Search query (case-insensitive, matches message or file path)
        limit: Maximum results
    
    Returns:
        Matching errors
    """
    from ck3raven.analyzers.error_parser import CK3ErrorParser
    
    parser = CK3ErrorParser()
    
    try:
        parser.parse_log()
    except FileNotFoundError:
        return {"error": "error.log not found"}
    
    errors = parser.search_errors(query, limit=limit)
    
    return {
        "query": query,
        "count": len(errors),
        "errors": [e.to_dict() for e in errors],
    }


# @mcp.tool()  # DEPRECATED - use ck3_logs(source="error", command="cascades")
def ck3_get_cascade_patterns() -> dict:
    """
    Get detected cascading error patterns from the error.log.
    
    Cascading errors are patterns where one root error causes many subsequent errors.
    Fixing the root error can eliminate many downstream errors.
    
    Pattern types:
    - script_parse_cascade: Script syntax error causing many "not defined" errors
    - mod_load_cascade: Encoding error causing mod-wide issues
    - repeated_error_spam: Same error repeated many times
    
    Returns:
        List of cascade patterns with root errors and child counts
    """
    from ck3raven.analyzers.error_parser import CK3ErrorParser
    
    parser = CK3ErrorParser()
    
    try:
        parser.parse_log()
        parser.detect_cascading_errors()
    except FileNotFoundError:
        return {"error": "error.log not found"}
    
    cascades = [c.to_dict() for c in parser.cascade_patterns]
    
    return {
        "cascade_count": len(cascades),
        "total_errors": parser.stats['total_errors'],
        "cascades": cascades,
        "recommendation": "Fix root errors first - they can eliminate many child errors",
    }


# @mcp.tool()  # DEPRECATED - use ck3_logs(source="crash", command="summary")
def ck3_get_crash_reports(
    limit: int = 5,
) -> dict:
    """
    Get recent crash reports from CK3.
    
    Parses crash folders in the CK3 crashes directory, which contain:
    - exception.txt (stack trace)
    - meta.yml (crash metadata)
    - logs/ (copies of logs at crash time)
    
    Args:
        limit: Maximum number of crashes to return (default 5)
    
    Returns:
        List of crash reports with details
    """
    from ck3raven.analyzers.crash_parser import get_recent_crashes
    
    crashes = get_recent_crashes(limit=limit)
    
    if not crashes:
        return {
            "count": 0,
            "message": "No crash reports found",
        }
    
    return {
        "count": len(crashes),
        "crashes": [c.to_dict() for c in crashes],
    }


# @mcp.tool()  # DEPRECATED - use ck3_logs(source="crash", command="detail", crash_id=...)
def ck3_get_crash_detail(
    crash_id: str,
) -> dict:
    """
    Get detailed information about a specific crash.
    
    Args:
        crash_id: Crash folder name (e.g., "ck3_20251217_060926")
    
    Returns:
        Full crash report with logs and stack trace
    """
    from pathlib import Path
    from ck3raven.analyzers.crash_parser import parse_crash_folder
    
    crashes_dir = (
        Path.home() / "Documents" / "Paradox Interactive" / 
        "Crusader Kings III" / "crashes"
    )
    
    crash_path = crashes_dir / crash_id
    
    if not crash_path.exists():
        return {
            "error": f"Crash folder not found: {crash_id}",
            "hint": "Use ck3_get_crash_reports to see available crashes",
        }
    
    report = parse_crash_folder(crash_path)
    
    if not report:
        return {"error": "Failed to parse crash folder"}
    
    return report.to_dict()


# @mcp.tool()  # DEPRECATED - use ck3_logs(source=..., command="read", ...)
def ck3_read_log(
    log_type: str = "error",
    lines: int = 100,
    from_end: bool = True,
    search: str | None = None,
) -> dict:
    """
    Read content from a CK3 log file.
    
    Args:
        log_type: Type of log to read: "error", "game", "debug", "setup", "gui_warnings"
        lines: Number of lines to return (default 100)
        from_end: If True, return last N lines; otherwise first N lines
        search: Optional search filter (only return lines containing this text)
    
    Returns:
        Log content
    """
    from pathlib import Path
    
    logs_dir = (
        Path.home() / "Documents" / "Paradox Interactive" / 
        "Crusader Kings III" / "logs"
    )
    
    log_files = {
        "error": "error.log",
        "game": "game.log",
        "debug": "debug.log",
        "setup": "setup.log",
        "gui_warnings": "gui_warnings.log",
        "database_conflicts": "database_conflicts.log",
    }
    
    if log_type not in log_files:
        return {
            "error": f"Unknown log type: {log_type}",
            "available": list(log_files.keys()),
        }
    
    log_path = logs_dir / log_files[log_type]
    
    if not log_path.exists():
        return {
            "error": f"Log file not found: {log_files[log_type]}",
            "hint": "Make sure CK3 has been run",
        }
    
    try:
        content_lines = log_path.read_text(encoding='utf-8', errors='replace').splitlines()
        
        # Apply search filter if provided
        if search:
            search_lower = search.lower()
            content_lines = [l for l in content_lines if search_lower in l.lower()]
        
        # Select lines
        if from_end:
            selected = content_lines[-lines:] if len(content_lines) > lines else content_lines
        else:
            selected = content_lines[:lines]
        
        return {
            "log_type": log_type,
            "total_lines": len(content_lines),
            "returned_lines": len(selected),
            "from_end": from_end,
            "search": search,
            "content": "\n".join(selected),
        }
    except Exception as e:
        return {"error": str(e)}


# @mcp.tool()  # DEPRECATED - use ck3_logs(source="game", command="list")
def ck3_get_game_log_errors(
    category: str | None = None,
    limit: int = 100,
) -> dict:
    """
    Parse and get errors from game.log with categorization.
    
    game.log contains runtime errors during game startup and play,
    including casus belli errors, decision errors, culture/religion
    issues, building gfx errors, etc.
    
    Args:
        category: Filter by category (e.g., "culture_error", "building_error")
        limit: Maximum results
    
    Returns:
        Parsed and categorized errors from game.log
    """
    from ck3raven.analyzers.log_parser import CK3LogParser, LogType
    
    parser = CK3LogParser()
    
    try:
        count = parser.parse_game_log()
    except FileNotFoundError:
        return {"error": "game.log not found"}
    
    entries = parser.entries[LogType.GAME]
    
    if category:
        entries = [e for e in entries if e.category == category]
    
    return {
        "total_parsed": count,
        "filtered_count": len(entries[:limit]),
        "summary": parser.get_game_log_summary(),
        "errors": [e.to_dict() for e in entries[:limit]],
    }


# @mcp.tool()  # DEPRECATED - use ck3_logs(source="debug", command="summary")
def ck3_get_debug_info() -> dict:
    """
    Extract system and mod information from debug.log.
    
    Returns:
        - System info (GPU, architecture, worker threads)
        - DLCs enabled
        - Mods enabled/disabled
    """
    from ck3raven.analyzers.log_parser import CK3LogParser
    
    parser = CK3LogParser()
    
    try:
        parser.parse_debug_log(extract_system_info=True)
    except FileNotFoundError:
        return {"error": "debug.log not found"}
    
    return parser.get_debug_info_summary()


# @mcp.tool()  # DEPRECATED - use ck3_logs(source="game", command="search", query=...)
def ck3_search_game_log(
    query: str,
    limit: int = 50,
) -> dict:
    """
    Search game.log errors by message or file path.
    
    Args:
        query: Search query (case-insensitive)
        limit: Maximum results
    
    Returns:
        Matching errors from game.log
    """
    from ck3raven.analyzers.log_parser import CK3LogParser, LogType
    
    parser = CK3LogParser()
    
    try:
        parser.parse_game_log()
    except FileNotFoundError:
        return {"error": "game.log not found"}
    
    entries = parser.search_entries(query, log_type=LogType.GAME, limit=limit)
    
    return {
        "query": query,
        "count": len(entries),
        "errors": [e.to_dict() for e in entries],
    }


# @mcp.tool()  # DEPRECATED - use ck3_logs(source="game", command="categories")
def ck3_get_game_log_categories() -> dict:
    """
    Get all error categories found in game.log with counts.
    
    Useful for understanding what types of errors exist and
    deciding which to focus on fixing.
    
    Returns:
        Category breakdown with counts and descriptions
    """
    from ck3raven.analyzers.log_parser import CK3LogParser, LogType, GAME_LOG_CATEGORIES
    
    parser = CK3LogParser()
    
    try:
        parser.parse_game_log()
    except FileNotFoundError:
        return {"error": "game.log not found"}
    
    stats = parser.stats.get(LogType.GAME, {})
    by_category = dict(stats.get('by_category', {}).most_common())
    
    # Add descriptions
    category_info = {name: desc for name, _, _, desc in GAME_LOG_CATEGORIES}
    
    categories = []
    for cat, count in by_category.items():
        categories.append({
            "category": cat,
            "count": count,
            "description": category_info.get(cat, "Other/uncategorized errors"),
        })
    
    return {
        "total_errors": stats.get('total', 0),
        "categories": categories,
    }


# ============================================================================
# Explorer Tools (for UI navigation)
# DEPRECATED: Use ck3_playset, ck3_folder instead
# ============================================================================

# @mcp.tool()  # DEPRECATED - use ck3_playset(command="mods")
def ck3_get_playset_mods() -> dict:
    """
    DEPRECATED: Use ck3_playset(command="mods") instead.
    
    Get all mods in the active playset with load order.
    
    Returns list of mods with:
    - name: Display name
    - contentVersionId: For querying files
    - loadOrder: Position (0=vanilla, 1=first mod, etc.)
    - kind: 'vanilla' or 'mod'
    - fileCount: Number of files
    - sourcePath: Original source path (if known)
    """
    db = _get_db()
    playset_id = _get_playset_id()
    
    rows = db.conn.execute("""
        SELECT 
            pm.load_order_index,
            pm.content_version_id,
            cv.kind,
            cv.file_count,
            vv.ck3_version,
            mp.name as mod_name,
            mp.source_path
        FROM playset_mods pm
        JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
        LEFT JOIN vanilla_versions vv ON cv.vanilla_version_id = vv.vanilla_version_id
        LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
        WHERE pm.playset_id = ? AND pm.enabled = 1
        ORDER BY pm.load_order_index
    """, (playset_id,)).fetchall()
    
    mods = []
    for row in rows:
        name = row['mod_name'] if row['mod_name'] else f"Vanilla CK3 {row['ck3_version'] or ''}"
        mods.append({
            "name": name,
            "contentVersionId": row['content_version_id'],
            "loadOrder": row['load_order_index'],
            "kind": row['kind'],
            "fileCount": row['file_count'],
            "sourcePath": row['source_path']
        })
    
    return {"mods": mods, "playset_id": playset_id}


# @mcp.tool()  # DEPRECATED - use ck3_folder(command="top_level")
def ck3_get_top_level_folders() -> dict:
    """
    DEPRECATED: Use ck3_folder(command="top_level") instead.
    
    Get top-level folders across all mods in the active playset.
    
    Returns unique folder names with file counts.
    """
    db = _get_db()
    playset_id = _get_playset_id()
    
    rows = db.conn.execute("""
        SELECT 
            SUBSTR(f.relpath, 1, INSTR(f.relpath || '/', '/') - 1) as folder,
            COUNT(*) as file_count
        FROM files f
        JOIN playset_mods pm ON f.content_version_id = pm.content_version_id
        WHERE pm.playset_id = ? AND pm.enabled = 1 AND f.deleted = 0
        GROUP BY folder
        ORDER BY folder
    """, (playset_id,)).fetchall()
    
    folders = [{"name": row['folder'], "fileCount": row['file_count']} for row in rows if row['folder']]
    return {"folders": folders}


# @mcp.tool()  # DEPRECATED - use ck3_folder(command="mod_folders")
def ck3_get_mod_folders(content_version_id: int) -> dict:
    """
    DEPRECATED: Use ck3_folder(command="mod_folders", content_version_id=...) instead.
    
    Get top-level folders within a specific mod.
    
    Args:
        content_version_id: The content version to query
    
    Returns folders with file counts.
    """
    db = _get_db()
    
    rows = db.conn.execute("""
        SELECT 
            SUBSTR(f.relpath, 1, INSTR(f.relpath || '/', '/') - 1) as folder,
            COUNT(*) as file_count
        FROM files f
        WHERE f.content_version_id = ? AND f.deleted = 0
        GROUP BY folder
        ORDER BY folder
    """, (content_version_id,)).fetchall()
    
    folders = [{"name": row['folder'], "fileCount": row['file_count']} for row in rows if row['folder']]
    return {"folders": folders}


# @mcp.tool()  # DEPRECATED - use ck3_folder(command="contents")
def ck3_get_folder_contents(
    path: str,
    content_version_id: Optional[int] = None,
    folder_pattern: Optional[str] = None,
    text_search: Optional[str] = None,
    symbol_search: Optional[str] = None,
    mod_filter: Optional[list[str]] = None,
    file_type_filter: Optional[list[str]] = None
) -> dict:
    """
    DEPRECATED: Use ck3_folder(command="contents", path=...) instead.
    
    Get contents of a folder - subfolders and files.
    
    Args:
        path: Folder path (e.g., "common/traits")
        content_version_id: Limit to specific mod (optional)
        folder_pattern: Filter by folder pattern
        text_search: Filter by content text (FTS)
        symbol_search: Filter by symbol name
        mod_filter: Only show files from these mods
        file_type_filter: Only show these file types
    
    Returns subfolders and files in the path.
    """
    db = _get_db()
    playset_id = _get_playset_id()
    
    # Normalize path
    path = path.strip('/').replace('\\', '/')
    path_prefix = f"{path}/" if path else ""
    
    # Build query for subfolders
    if content_version_id:
        # Single mod query
        subfolder_sql = """
            SELECT DISTINCT
                SUBSTR(f.relpath, ?, INSTR(SUBSTR(f.relpath, ?), '/')) as subfolder
            FROM files f
            WHERE f.content_version_id = ? 
              AND f.relpath LIKE ?
              AND f.deleted = 0
              AND SUBSTR(f.relpath, ?, INSTR(SUBSTR(f.relpath, ?), '/')) != ''
        """
        prefix_len = len(path_prefix) + 1
        subfolder_rows = db.conn.execute(subfolder_sql, (
            prefix_len, prefix_len, content_version_id, f"{path_prefix}%", prefix_len, prefix_len
        )).fetchall()
    else:
        # All mods in playset
        subfolder_sql = """
            SELECT DISTINCT
                SUBSTR(f.relpath, ?, INSTR(SUBSTR(f.relpath, ?), '/')) as subfolder
            FROM files f
            JOIN playset_mods pm ON f.content_version_id = pm.content_version_id
            WHERE pm.playset_id = ? 
              AND pm.enabled = 1
              AND f.relpath LIKE ?
              AND f.deleted = 0
              AND SUBSTR(f.relpath, ?, INSTR(SUBSTR(f.relpath, ?), '/')) != ''
        """
        prefix_len = len(path_prefix) + 1
        subfolder_rows = db.conn.execute(subfolder_sql, (
            prefix_len, prefix_len, playset_id, f"{path_prefix}%", prefix_len, prefix_len
        )).fetchall()
    
    # Count files in each subfolder
    subfolders = []
    seen_folders = set()
    for row in subfolder_rows:
        if row['subfolder'] and row['subfolder'] not in seen_folders:
            seen_folders.add(row['subfolder'])
            subfolders.append({"name": row['subfolder']})
    
    # Build query for files in this exact folder (not subfolders)
    if content_version_id:
        file_sql = """
            SELECT 
                f.file_id,
                f.relpath,
                f.content_hash,
                f.file_type,
                cv.kind,
                mp.name as mod_name,
                mp.source_path
            FROM files f
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE f.content_version_id = ?
              AND f.relpath LIKE ?
              AND f.relpath NOT LIKE ?
              AND f.deleted = 0
            ORDER BY f.relpath
        """
        file_rows = db.conn.execute(file_sql, (
            content_version_id, f"{path_prefix}%", f"{path_prefix}%/%"
        )).fetchall()
    else:
        file_sql = """
            SELECT 
                f.file_id,
                f.relpath,
                f.content_hash,
                f.file_type,
                cv.kind,
                mp.name as mod_name,
                mp.source_path,
                pm.load_order_index
            FROM files f
            JOIN playset_mods pm ON f.content_version_id = pm.content_version_id
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE pm.playset_id = ?
              AND pm.enabled = 1
              AND f.relpath LIKE ?
              AND f.relpath NOT LIKE ?
              AND f.deleted = 0
            ORDER BY pm.load_order_index, f.relpath
        """
        file_rows = db.conn.execute(file_sql, (
            playset_id, f"{path_prefix}%", f"{path_prefix}%/%"
        )).fetchall()
    
    # Build file list with absolute paths
    files = []
    for row in file_rows:
        mod_name = row['mod_name'] if row['mod_name'] else f"Vanilla"
        
        # Determine absolute path
        abs_path = None
        if row['source_path']:
            abs_path = str(Path(row['source_path']) / row['relpath'])
        
        files.append({
            "relpath": row['relpath'],
            "modName": mod_name,
            "contentHash": row['content_hash'],
            "fileType": row['file_type'] or 'text',
            "absPath": abs_path
        })
    
    return {
        "folders": subfolders,
        "files": files,
        "path": path
    }


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
            - "ck3lens": CK3 modding with database search and live mod editing
            - "ck3raven-dev": Full development mode for infrastructure
    
    Returns:
        Mode instructions, policy boundaries, session context, and database status
    """
    from pathlib import Path
    from ck3lens.policy import (
        ScopeDomain, IntentType, CK3LensTokenType, AgentMode,
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
                "mod_root": session_info.get("mod_root"),
                "local_mods_folder": session_info.get("local_mods_folder"),
                "editable_mods": session_info.get("editable_mods", []),
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
        ScopeDomain, IntentType, CK3LensTokenType,
        Ck3RavenDevScopeDomain, Ck3RavenDevIntentType, Ck3RavenDevWipIntent,
        Ck3RavenDevTokenType, CK3RAVEN_DEV_TOKEN_TIER_A, CK3RAVEN_DEV_TOKEN_TIER_B,
    )
    
    if mode == "ck3lens":
        return {
            "mode": "ck3lens",
            "description": "CK3 modding: Database search + live mod file editing",
            "scope_domains": {
                "read_allowed": [
                    ScopeDomain.ACTIVE_PLAYSET_DB.value,
                    ScopeDomain.ACTIVE_LOCAL_MODS.value,
                    ScopeDomain.ACTIVE_WORKSHOP_MODS.value,
                    ScopeDomain.VANILLA_GAME.value,
                    ScopeDomain.CK3_UTILITY_FILES.value,
                    ScopeDomain.CK3RAVEN_SOURCE.value,  # Read OK for error context
                    ScopeDomain.WIP_WORKSPACE.value,
                ],
                "write_allowed": [
                    ScopeDomain.ACTIVE_LOCAL_MODS.value,
                    ScopeDomain.WIP_WORKSPACE.value,
                ],
                "delete_requires_token": [
                    ScopeDomain.ACTIVE_LOCAL_MODS.value,
                ],
                "hidden_require_token": [
                    ScopeDomain.INACTIVE_WORKSHOP_MODS.value,
                    ScopeDomain.INACTIVE_LOCAL_MODS.value,
                ],
                "always_denied": [
                    "write to WORKSHOP_MODS",
                    "write to VANILLA_GAME",
                    "write to CK3RAVEN_SOURCE",
                    "delete from WORKSHOP_MODS",
                ],
            },
            "intent_types": [it.value for it in IntentType],
            "available_tokens": [tt.value for tt in CK3LensTokenType],
            "hard_rules": [
                "Intent type required for all operations",
                "Write only to active local mods (MSC, MSCRE, LRE, MRP)",
                "Python files only allowed in WIP workspace",
                "Delete requires explicit token with user prompt evidence",
                "Inactive mod access requires user prompt + token",
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
            "intent_types": [it.value for it in Ck3RavenDevIntentType],
            "wip_intents": [wi.value for wi in Ck3RavenDevWipIntent],
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
            "• Search symbols, files, content via database\n"
            "• Write/edit files in active local mods (MSC, MSCRE, LRE, MRP)\n"
            "• Draft Python scripts in WIP workspace (~/.ck3raven/wip/)\n"
            "• Use ck3_repair for launcher/cache issues\n\n"
            "You CANNOT write to workshop mods, vanilla, or ck3raven source."
        )
    elif mode == "ck3raven-dev":
        return (
            "CK3 Raven Dev mode active. You can:\n"
            "• Read all source code and mods (for parser/ingestion testing)\n"
            "• Write/edit ck3raven infrastructure code\n"
            "• Execute commands via ck3_exec (NOT run_in_terminal)\n"
            "• Write analysis scripts to <repo>/.wip/\n\n"
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
    result = {
        "database": {
            "path": str(session.db_path),
            "exists": session.db_path.exists(),
        },
        "playset_name": session.playset_name,
        "tool_sets": None,
        "mcp_config": None,
        "available_modes": [
            {
                "name": "ck3lens",
                "description": "CK3 modding - database search, conflict detection, live mod editing",
                "use_case": "Fixing mod errors, compatibility patching, mod development",
            },
            {
                "name": "ck3raven-dev",
                "description": "Full development mode - all tools for infrastructure work",
                "use_case": "Python development, MCP server changes, database schema",
            },
        ],
    }

    # Try to read toolSets.json
    ai_workspace = Path(__file__).parent.parent.parent.parent
    tool_sets_path = ai_workspace / ".vscode" / "toolSets.json"

    if tool_sets_path.exists():
        try:
            result["tool_sets"] = json.loads(tool_sets_path.read_text(encoding="utf-8"))
            result["tool_sets_path"] = str(tool_sets_path)
        except Exception as e:
            result["tool_sets_error"] = str(e)
    
    # Try to read mcp.json
    mcp_paths = [
        ai_workspace / ".vscode" / "mcp.json",
        ai_workspace / "ck3raven" / ".vscode" / "mcp.json",
    ]
    
    for mcp_path in mcp_paths:
        if mcp_path.exists():
            try:
                # Read as text and strip comments for JSONC
                content = mcp_path.read_text(encoding="utf-8")
                # Simple JSONC handling: remove // comments
                lines = [l for l in content.splitlines() if not l.strip().startswith("//")]
                clean_json = "\n".join(lines)
                result["mcp_config"] = json.loads(clean_json)
                result["mcp_config_path"] = str(mcp_path)
                break
            except Exception as e:
                result["mcp_config_error"] = str(e)
    
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
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    mcp.run()

