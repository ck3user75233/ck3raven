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
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, Literal
from click import command
from ck3lens.log_rotation import rotate_logs
from ck3lens.logging import info, warn, bootstrap
import signal
import atexit
import threading
from ck3lens.policy.contract_v1 import Operation

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

# =============================================================================
# PYTHON PATH BOOTSTRAP
# =============================================================================
# ck3raven.core lives in ROOT_REPO/src/ck3raven/core/ - we need to add src/ to sys.path.
#
# ROOT_REPO comes from config. If not configured, FAIL LOUDLY.
# No fallbacks, no __file__ computation (breaks in venvs).
#
def _setup_ck3raven_import_path() -> None:
    """Set up sys.path to enable imports from ck3raven.core."""
    from ck3lens.config_loader import load_config
    config = load_config()
    root_repo = config.paths.root_repo
    
    if root_repo is None:
        print("=" * 70, file=sys.stderr)
        print("FATAL: root_repo not configured in workspace.toml", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("", file=sys.stderr)
        print("Run: python -m ck3lens.paths_doctor", file=sys.stderr)
        print("Or add to ~/.ck3raven/config/workspace.toml:", file=sys.stderr)
        print("", file=sys.stderr)
        print("  [paths]", file=sys.stderr)
        print('  root_repo = "C:/path/to/ck3raven"', file=sys.stderr)
        print("", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        sys.exit(1)
    
    if not root_repo.exists():
        print("=" * 70, file=sys.stderr)
        print(f"FATAL: root_repo does not exist: {root_repo}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("Fix root_repo in ~/.ck3raven/config/workspace.toml", file=sys.stderr)
        sys.exit(1)
    
    src_path = root_repo / "src"
    if not src_path.exists():
        print("=" * 70, file=sys.stderr)
        print(f"FATAL: src/ not found in root_repo: {src_path}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("Verify root_repo points to ck3raven repository root", file=sys.stderr)
        sys.exit(1)
    
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

_setup_ck3raven_import_path()

# Canonical Reply System (Phase C migration)
# NOTE: Must be after path setup since ck3raven.core is in ROOT_REPO/src/
from ck3raven.core.reply import Reply, TraceInfo, MetaInfo
from ck3raven.core.trace import generate_trace_id, get_or_create_session_id
from .safety import mcp_safe_tool, ReplyBuilder, get_current_trace_info, initialize_window_trace



from ck3lens.workspace import Session, LocalMod
from ck3lens.db_queries import DBQueries
from ck3lens.db_api import db as db_api  # Database API Layer - THE interface for DB access
from ck3lens import git_ops
from ck3lens.validate import parse_content, validate_artifact_bundle
from ck3lens.contracts import ArtifactBundle
from ck3lens.trace import ToolTrace
# Canonical path constants - use these instead of computing paths from __file__
from ck3lens.paths import ROOT_REPO, ROOT_CK3RAVEN_DATA, ROOT_GAME


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
            warn("mcp.init", f"Mods not indexed: {stats['mods_missing']}")
    
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
                warn("mcp.init", f"Mods not indexed: {stats['mods_missing']}")
    return _db


def _get_active_cvids() -> set[int]:
    """
    Get content_version_ids for the active playset.
    
    CANONICAL: Derives from session.mods[] - THE source of truth.
    
    Returns:
        Set of cvids for vanilla + all mods in the active playset.
        Empty set if no playset or CVIDs not resolved.
    """
    session = _get_session()
    return {m.cvid for m in session.mods if m.cvid is not None}


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
    
    One adapter, one construction path. Mode-sensitivity is handled inside
    WorldAdapter (e.g., mod visibility scoped by session.mods in ck3lens).
    
    All MCP tools should use this to resolve paths before policy checks.
    
    Returns:
        WorldAdapter appropriate for the current mode, or None if mode not initialized
    """
    global _cached_world_adapter, _cached_world_mode
    
    from ck3lens.agent_mode import get_agent_mode
    from ck3lens.world_adapter import WorldAdapter
    
    mode = get_agent_mode()
    
    if mode is None:
        return None
    
    # Check cache
    if _cached_world_adapter is not None and _cached_world_mode == mode:
        return _cached_world_adapter
    
    # Get session for mod paths (ck3lens gets playset mods, ck3raven-dev gets empty)
    session = _get_session()
    
    # Single construction path — no mode branching at call site
    adapter = WorldAdapter.create(
        mode=mode,
        db=None,
        mods=session.mods or [],
    )
    
    _cached_world_adapter = adapter
    _cached_world_mode = mode
    return adapter


def _reset_world_cache():
    """Reset cached world adapter v1 for mode changes.

    v2 is mode-agnostic (reads mode dynamically), so no invalidation needed.
    v1 bakes mode at construction, so must be rebuilt on mode change.
    """
    global _cached_world_adapter, _cached_world_mode
    _cached_world_adapter = None
    _cached_world_mode = None


# REMOVED: _session_scope global (January 2026)
# The dual session system caused playset state to always be null.
# Use _get_session() instead - it returns a proper Session object.

# Playset folder - JSON files here define available playsets
# CANONICAL LOCATION: ~/.ck3raven/playsets/

def _get_playsets_dir() -> Path:
    """Get the canonical playsets directory."""
    return ROOT_CK3RAVEN_DATA / "playsets"

# For backward compatibility during migration
PLAYSETS_DIR = ROOT_CK3RAVEN_DATA / "playsets"

# Manifest file - points to which playset is currently active
# Lives in the playsets folder alongside the playset files
PLAYSET_MANIFEST_FILE = ROOT_CK3RAVEN_DATA / "playsets" / "playset_manifest.json"



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


def _validate_playset_schema(data: dict, file_path: str) -> tuple[bool, list[str]]:
    """
    Validate playset JSON against required schema.
    
    FAIL CLOSED: If validation fails, returns (False, errors).
    The caller MUST NOT proceed with an invalid playset.
    
    Returns (is_valid, list of error messages).
    """
    errors = []
    
    # Required top-level fields
    if "playset_name" not in data:
        errors.append("Missing required field: playset_name")
    elif not isinstance(data["playset_name"], str):
        errors.append("playset_name must be a string")
    
    if "vanilla" not in data:
        errors.append("Missing required field: vanilla")
    elif not isinstance(data["vanilla"], dict):
        errors.append("vanilla must be an object")
    elif "path" not in data["vanilla"]:
        errors.append("Missing required field: vanilla.path")
    
    if "mods" not in data:
        errors.append("Missing required field: mods")
    elif not isinstance(data["mods"], list):
        errors.append("mods must be an array")
    else:
        # Validate each mod entry
        for i, mod in enumerate(data["mods"]):
            if not isinstance(mod, dict):
                errors.append(f"mods[{i}] must be an object")
                continue
            if "name" not in mod:
                errors.append(f"mods[{i}] missing required field: name")
            if "path" not in mod:
                errors.append(f"mods[{i}] missing required field: path")
            if "load_order" not in mod:
                errors.append(f"mods[{i}] missing required field: load_order")
    
    return (len(errors) == 0, errors)


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
        
        # FAIL CLOSED: Validate schema before proceeding
        is_valid, schema_errors = _validate_playset_schema(data, str(playset_file))
        if not is_valid:
            warn("mcp.init", f"Playset schema validation failed: {playset_file}",
                 errors=schema_errors)
            # Return error dict instead of None to signal validation failure
            return {
                "error": "PLAYSET_SCHEMA_INVALID",
                "message": f"Playset failed schema validation: {playset_file.name}",
                "validation_errors": schema_errors,
                "reply_code": "WA-VIS-I-003",
            }
        
        # Auto-migrate paths if they reference a different user profile
        try:
            from .ck3lens.path_migration import migrate_playset_paths
            migrated_data, was_modified, migration_msg = migrate_playset_paths(data)
            if was_modified:
                info("mcp.init", f"Path migration: {migration_msg}")
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
        vanilla_root = vanilla_config.get("path", str(ROOT_GAME) if ROOT_GAME else "")
        
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
            "vanilla_root": str(Path(vanilla_root).expanduser()),
            "source": "json",
            "file_path": str(playset_file),
            "local_mods_folder": str(local_mods_folder) if local_mods_folder else None,
            "agent_briefing": agent_briefing,
            "sub_agent_config": data.get("sub_agent_config", {}),
            "mod_list": data.get("mods", []),  # Full mod list for reference
        }
    except Exception as e:
        warn("mcp.init", f"Failed to load playset: {playset_file}", error=str(e))
        return None


# REMOVED: _load_legacy_playset - Legacy playset format BANNED (December 2025)
# All playsets must use the canonical mods[] format in playsets/*.json

# REMOVED: _get_session_scope() function (January 2026)
# This function was part of a dual session system that caused playset state to always be null.
# The bug: _get_session_scope() reimplemented session loading with a path mismatch bug.
# The fix: Use _get_session() which returns a proper Session object from load_config().
#
# If you need playset info, use:
#   session = _get_session()
#   session.playset_name  # Human-readable name
#   session.mods          # List of ModEntry objects
#   session.vanilla       # Vanilla entry (mods[0])
#   session.local_mods_folder  # Path to editable mods


def _get_trace_path() -> Path:
    """
    Get the trace log path based on agent mode.
    
    - ck3raven-dev mode: {repo}/.wip/traces/ck3lens_trace.jsonl
    - ck3lens mode: ~/.ck3raven/traces/ck3lens_trace.jsonl
    """
    # All traces go in ~/.ck3raven/traces/ (unified, no mode-specific location)
    trace_dir = ROOT_CK3RAVEN_DATA / "traces"
    
    trace_dir.mkdir(parents=True, exist_ok=True)
    return trace_dir / "ck3lens_trace.jsonl"


def _get_trace() -> ToolTrace:
    global _trace
    if _trace is None:
        _trace = ToolTrace(_get_trace_path())
    return _trace

# ============================================================================
# Session Management
# ============================================================================


@mcp.tool()
@mcp_safe_tool
def ck3_get_instance_info() -> Reply:
    """
    Get information about this MCP server instance.
    
    Use this to verify which server instance you're connected to.
    Each VS Code window should have a unique instance ID.
    
    Returns:
        Instance ID, server name, and process info
    """
    import os
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool="ck3_get_instance_info")
    # Instance info is infrastructure metadata - ungoverned -> MCP layer
    return rb.success(
        "MCP-SYS-S-001",
        data={
            "instance_id": _instance_id,
            "server_name": _server_name,
            "pid": os.getpid(),
            "is_isolated": _instance_id != "default",
        },
        message="Instance info retrieved.",
    )


@mcp.tool()
@mcp_safe_tool
def ck3_ping() -> Reply:
    """
    Simple health check - always returns success.
    
    Use this to verify MCP server connectivity is working.
    Unlike other tools, this has no dependencies and will
    always succeed if the server is reachable.
    
    Returns:
        Reply with status, instance_id, and timestamp in data
    """
    from datetime import datetime
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool="ck3_ping")
    # Ping is system health check - ungoverned -> MCP layer
    return rb.success(
        "MCP-SYS-S-001",
        data={
            "status": "ok",
            "instance_id": _instance_id,
            "timestamp": datetime.now().isoformat(),
        },
        message="Ping successful.",
    )


@mcp.tool()
@mcp_safe_tool
def debug_get_logs(
    lines: int = 50,
    level: Optional[Literal["DEBUG", "INFO", "WARN", "ERROR"]] = None,
    category: Optional[str] = None,
    trace_id: Optional[str] = None,
    source: Literal["all", "mcp", "ext", "daemon"] = "all",
) -> Reply:
    """
    Get recent logs from all ck3raven components, merged chronologically.
    
    This tool aggregates logs from:
    - MCP Server (Python): ~/.ck3raven/logs/ck3raven-mcp.log
    - VS Code Extension (Node): ~/.ck3raven/logs/ck3raven-ext.log
    - QBuilder Daemon: ~/.ck3raven/daemon/daemon.log
    
    Logs are returned in chronological order with source identification.
    Use this for debugging MCP lifecycle issues, tool failures, or 
    tracing operations across components via trace_id.
    
    This tool exists specifically so the user can copy-paste the agent's 
    output back to ChatGPT or other external review.
    
    Args:
        lines: Maximum total lines to return (default 50)
        level: Filter by minimum level (DEBUG, INFO, WARN, ERROR)
        category: Filter by category prefix (e.g., "mcp.", "ext.", "contract.")
        trace_id: Filter by trace ID (for debugging specific operations)
        source: Which log sources to include (all, mcp, ext, daemon)
    
    Returns:
        Merged, chronologically sorted log entries with source identification
    """
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool="debug_get_logs")
    
    log_files = {
        "mcp": Path.home() / ".ck3raven" / "logs" / "ck3raven-mcp.log",
        "ext": Path.home() / ".ck3raven" / "logs" / "ck3raven-ext.log",
        "daemon": Path.home() / ".ck3raven" / "daemon" / "daemon.log",
    }
    
    level_order = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
    entries = []
    files_read = []
    
    for src, log_path in log_files.items():
        if source != "all" and source != src:
            continue
        if not log_path.exists():
            continue
        
        files_read.append(str(log_path))
        
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line_text in f:
                    try:
                        entry = json.loads(line_text.strip())
                        entry["_source"] = src
                        
                        # Apply filters
                        if level:
                            entry_level = entry.get("level", "INFO")
                            if level_order.get(entry_level, 1) < level_order.get(level, 1):
                                continue
                        if category and not entry.get("cat", "").startswith(category):
                            continue
                        if trace_id and entry.get("trace_id") != trace_id:
                            continue
                        
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            # Log but continue - don't fail if one file is unreadable
            entries.append({
                "_source": src,
                "ts": datetime.now().isoformat() + "Z",
                "level": "WARN",
                "cat": "debug.get_logs",
                "msg": f"Could not read {log_path}: {e}",
            })
    
    # Sort by timestamp
    entries.sort(key=lambda e: e.get("ts", ""))
    
    # Return most recent entries
    result_entries = entries[-lines:] if len(entries) > lines else entries
    
    return rb.success(
        "WA-LOG-S-001",
        data={
            "entries": result_entries,
            "total_available": len(entries),
            "truncated": len(entries) > lines,
            "files_read": files_read,
            "filters_applied": {
                "level": level,
                "category": category,
                "trace_id": trace_id,
                "source": source,
            }
        },
        message=f"Retrieved {len(result_entries)} log entries from {len(files_read)} files.",
    )


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

    global _session, _db, _trace, _playset_id, _session_cv_ids_resolved

    # Reset playset cache
    _playset_id = None
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
    _internal_rb = ReplyBuilder(TraceInfo(trace_id="internal", session_id="internal"), tool='_init_session')
    db_health_reply = _check_db_health(_db.conn, rb=_internal_rb)
    db_status = db_health_reply.data

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


def _check_db_health(conn, *, rb: ReplyBuilder) -> Reply:
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
        
        return rb.success("MCP-SYS-S-001", data={
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
        })
    except Exception as e:
        return rb.error("MCP-SYS-E-001", data={
            "is_complete": False,
            "error": str(e),
            "needs_rebuild": True,
            "rebuild_reason": f"Error checking database: {e}"
        })


# NOTE: ck3_get_db_status() DELETED - January 2026
# Functionality consolidated into ck3_qbuilder(command="status")
# This avoids redundant tools and eliminates qbuilder import dependency


@mcp.tool()
@mcp_safe_tool
def ck3_close_db() -> Reply:
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
    global _db, _playset_id, _session
    
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool="ck3_close_db")
    
    try:
        # Use db_api to disable (which handles WAL mode, close, and blocks reconnect)
        result = db_api.disable()
        
        # Also clear module-level cache
        _db = None
        
        # Clear cached state that depends on DB
        _playset_id = None
        _session = None  # Clear session so it reloads on next access
        
        # Clear thread-local connections from schema module
        try:
            from ck3raven.db.schema import close_all_connections
            close_all_connections()
        except Exception:
            pass
        
        # Force garbage collection to release any lingering file handles
        import gc
        gc.collect()
        
        return rb.success(
            "WA-DB-S-001",
            data={"closed": True},
            message="Database connection closed and DISABLED. Use ck3_db(command='enable') to reconnect. File lock released.",
        )
    except Exception as e:
        return rb.error(
            "MCP-SYS-E-001",
            data={"error": str(e)},
            message=f"Failed to close connection: {e}",
        )


@mcp.tool()
@mcp_safe_tool
def ck3_db(
    command: Literal["status", "disable", "enable"] = "status",
) -> Reply:
    """
    Manage database connection for maintenance operations.
    
    Commands:
    
    command=status   → Check if database is enabled/connected
    command=disable  → Close connection and block reconnection (for file operations)
    command=enable   → Re-enable database access
    
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
    
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool="ck3_db")
    
    if command == "status":
        result = db_api.status()
        return rb.success("WA-DB-S-001", data=result, message="Database status retrieved.")
        
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
        
        return rb.success("WA-DB-S-001", data=result, message="Database disabled.")
        
    elif command == "enable":
        result = db_api.enable()
        return rb.success("WA-DB-S-001", data=result, message="Database enabled.")
    
    else:
        return rb.invalid("MCP-SYS-I-002", data={"command": command}, message=f"Unknown command: {command}")


# NOTE: ck3_get_playset_build_status() DELETED - January 2026
# Functionality consolidated into ck3_qbuilder(command="status")
# This avoids redundant tools and eliminates qbuilder import dependency


@mcp.tool()
@mcp_safe_tool
def ck3_db_delete(
    target: Literal["asts", "symbols", "refs", "files", "content_versions", "lookups", "playsets", "build_tracking"],
    scope: Literal["all", "mods_only", "by_ids", "by_content_version"],
    ids: Optional[list[int | str]] = None,
    content_version_ids: Optional[list[int]] = None,
    confirm: bool = False
) -> Reply:
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
            - "mods_only": Delete mod data, preserve game files (by name lookup)
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
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_db_delete')
    
    # Call internal implementation
    result = _ck3_db_delete_internal(target, scope, ids, content_version_ids, confirm)
    
    # Convert to Reply
    if result.get("error") or result.get("reply_type") == "D":
        # Enforcement denial — inner result has reply_type + code + denials
        if result.get("reply_type") == "D" and result.get("code"):
            return rb.denied(result["code"], data=result, message=result.get("error", "Policy denied"))
        
        err_msg = str(result.get("error", "")).lower()
        
        # System failure requires POSITIVE evidence
        if "failed to" in err_msg or "timeout" in err_msg or "connection" in err_msg or "exception" in err_msg:
            return rb.error('MCP-SYS-E-001', data=result, message=result.get("error", "System error"))
        
        # Default: Invalid (agent mistake / bad input)
        return rb.invalid('WA-DB-I-001', data=result, message=result.get("error", "Invalid input"))
    
    # DB delete is system-owned/ungoverned -> MCP layer owns success
    if result.get("success"):
        msg = f"Deleted {result.get('rows_deleted', 0)} rows from {target}."
        return rb.success('MCP-DB-S-001', data=result, message=msg)
    
    if result.get("preview") or result.get("rows_would_delete") is not None:
        msg = f"Would delete {result.get('rows_would_delete', 0)} rows from {target}. Use confirm=True to delete."
        return rb.success('MCP-DB-S-002', data=result, message=msg)  # Preview is success
    
    return rb.success('MCP-DB-S-001', data=result, message="Operation complete.")


def _ck3_db_delete_internal(
    target: str,
    scope: str,
    ids: Optional[list[int | str]],
    content_version_ids: Optional[list[int]],
    confirm: bool,
) -> dict:
    """Internal implementation of ck3_db_delete returning dict.
    
    NOTE: This is a maintenance operation that bypasses normal enforcement.
    Per CANONICAL_ARCHITECTURE.md INVARIANT 2, database paths are normally
    NEVER writable by tools (Single-Writer Architecture). However, this
    maintenance tool is explicitly designed for cache/data cleanup.
    
    The enforcement check has been intentionally removed because:
    1. INVARIANT 2 would always return DENY for db paths
    2. This is a legitimate maintenance operation
    3. The tool requires explicit confirm=True as a safety gate
    """
    from ck3lens.agent_mode import get_agent_mode
    from ck3lens.policy.contract_v1 import get_active_contract
    
    db = _get_db()
    trace = _get_trace()
    mode = get_agent_mode()
    
    # ==========================================================================
    # IMPLEMENTATION (no enforcement - maintenance operation)
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
            # Find game files cvid by name, then exclude it.
            # Game files are always named 'CK3 Game Files' in content_versions.
            game_row = cur.execute(
                "SELECT content_version_id FROM content_versions WHERE name = 'CK3 Game Files' LIMIT 1"
            ).fetchone()
            game_cvid = game_row[0] if game_row else None
            
            if game_cvid is None:
                # No game files entry found — mods_only = all
                return "", []
            
            if table == "content_versions":
                return "WHERE content_version_id != ?", [game_cvid]
            elif table in ("files", "asts"):
                if table == "files":
                    return "WHERE content_version_id != ?", [game_cvid]
                else:
                    return "WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id != ?)", [game_cvid]
            elif table in ("symbols", "refs"):
                return f"WHERE ast_id IN (SELECT ast_id FROM asts WHERE file_id IN (SELECT file_id FROM files WHERE content_version_id != ?))", [game_cvid]
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
                trace.log("mcp.tool", {"target": target, "scope": scope}, result)
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
                    
                    # Delete files - CASCADE handles asts → symbols/refs
                    cur.execute(f"DELETE FROM files WHERE content_version_id IN ({placeholders})", cv_ids)
                    files_deleted = cur.rowcount
                    
                    # Delete content_versions
                    cur.execute(f"DELETE FROM content_versions {where}", params)
                    cv_deleted = cur.rowcount
                    
                    db.conn.commit()
                    
                    result["success"] = True
                    result["rows_deleted"] = cv_deleted
                    result["cascade"] = {
                        "files_deleted": files_deleted,
                        "symbols_deleted": symbols_count,    # Cascaded via asts
                        "refs_deleted": refs_count,          # Cascaded via asts
                        "asts_deleted": asts_count,          # Cascaded from files
                    }
                else:
                    result["success"] = True
                    result["rows_deleted"] = 0
                    
                trace.log("mcp.tool", {"target": target, "scope": scope}, result)
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
                trace.log("mcp.tool", {"target": target, "scope": scope}, result)
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
                trace.log("mcp.tool", {"target": target, "scope": scope}, result)
                return result
                
        elif target == "build_tracking":
            if not confirm:
                cur.execute("SELECT COUNT(*) FROM builder_runs")
                runs = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM builder_steps")
                steps = cur.fetchone()[0]
                result["rows_would_delete"] = runs + steps
                result["details"] = {"builder_runs": runs, "builder_steps": steps}
                trace.log("mcp.tool", {"target": target, "scope": scope}, result)
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
                trace.log("mcp.tool", {"target": target, "scope": scope}, result)
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
            trace.log("mcp.tool", {"target": target, "scope": scope, "preview": True}, result)
            return result
        
        # Actual delete
        cur.execute(delete_sql, params)
        result["success"] = True
        result["rows_deleted"] = cur.rowcount
        db.conn.commit()
        
    except Exception as e:
        result["error"] = str(e)
        
    trace.log("mcp.tool", {"target": target, "scope": scope}, result)
    return result


# ============================================================================
# Unified Command Tools (Consolidated)
# ============================================================================

@mcp.tool()
@mcp_safe_tool
def ck3_logs(
    source: Literal["error", "game", "debug", "crash"] = "error",
    command: Literal["summary", "list", "search", "detail", "categories", "cascades", "read", "raw"] = "summary",
    # Filters
    priority: int | None = None,
    category: str | None = None,
    mod_filter: str | None = None,
    mod_filter_exact: bool = False,
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
    # FR-1: Custom log source path
    source_path: str | None = None,
    # FR-2: Export results to WIP
    export_to: str | None = None,
) -> Reply:
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
        command=read        → Raw log content (lines, from_end, query for search)
        command=raw         → Complete raw log file for backup/archival (no limits)
    
    Args:
        source: Log source to query
        command: Action to perform
        priority: Max priority 1-5 (error source only)
        category: Filter by category
        mod_filter: Filter by mod name (substring match by default)
        mod_filter_exact: If True, require exact match instead of substring
        exclude_cascade_children: Skip errors caused by cascade patterns
        query: Search query for search/read commands
        crash_id: Crash folder name for detail command
        lines: Lines to return for read command
        from_end: Read from end (tail) vs start (head)
        limit: Max results for list commands
        source_path: Custom path to log file (for analyzing backups). Accepts:
            - Absolute paths: "C:/path/to/error.log"
            - Home-relative: "~/.ck3raven/wip/log-backups/error.log"
        export_to: Export results to WIP as markdown. Accepts:
            - Absolute or home-relative paths
            - Use {timestamp} for auto-substitution
    
    Returns:
        Dict with results based on command (plus export_path if export_to was used)
    """
    from ck3lens.unified_tools import ck3_logs_impl
    
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_logs')
    
    reply = ck3_logs_impl(
        source=source,
        command=command,
        priority=priority,
        category=category,
        mod_filter=mod_filter,
        mod_filter_exact=mod_filter_exact,
        exclude_cascade_children=exclude_cascade_children,
        query=query,
        crash_id=crash_id,
        lines=lines,
        from_end=from_end,
        limit=limit,
        source_path=source_path,
        export_to=export_to,
        rb=rb,
    )
    # Forward Reply (already built with our rb)
    if reply.reply_type == "I":
        return rb.invalid(reply.code, data=reply.data, message=reply.message)
    if reply.reply_type != "S":
        return rb.error(reply.code, data=reply.data, message=reply.message)
    return rb.success(reply.code, data=reply.data, message=reply.message)


# ============================================================================
# ck3_conflicts - Unified Conflict Detection
# ============================================================================

ConflictCommand = Literal["symbols", "files", "summary"]

@mcp.tool()
@mcp_safe_tool
def ck3_conflicts(
    command: ConflictCommand = "symbols",
    # Filters
    symbol_type: str | None = None,
    symbol_names: list[str] | None = None,
    game_folder: str | None = None,
    # Options
    include_compatch: bool = False,
    limit: int = 100,
) -> Reply:
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
                        "policy": str,  # OVERRIDE, FIOS, CONTAINER_MERGE, PER_KEY_OVERRIDE
                        "last_loaded": str,  # mod loaded last for this identity (approx - true resolution needs AST)
                        "sources": [{"mod": str, "file": str, "line": int, "load_order": int, "is_last_loaded": bool}],
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
                        "last_loaded": str,  # mod with highest load_order (per-identity, not whole-file)
                        "sources": [{"mod": str, "load_order": int, "is_last_loaded": bool}],
                        "has_zzz_prefix": bool
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
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_conflicts')
    
    db = _get_db()
    session = _get_session()
    
    # Get CVIDs from session.mods[] - THE canonical source
    # No db_visibility() or visible_cvids - derive inline from mods[]
    cvids: frozenset[int] = frozenset(
        m.cvid for m in session.mods 
        if hasattr(m, 'cvid') and m.cvid is not None
    )
    
    # Build CVID → load_order mapping for last-loaded determination
    load_order_map: dict[int, int] = {
        m.cvid: m.load_order
        for m in session.mods
        if hasattr(m, 'cvid') and m.cvid is not None
    }
    
    if not cvids:
        return rb.error(
            'MCP-SYS-E-001',
            data={"error": "No mods in session.mods[]"},
            message="No mods in session.mods[] - no active playset?",
        )
    
    if command == "symbols":
        # Use the internal method that was powering the deleted tools
        result = db._get_symbol_conflicts_internal(
            visible_cvids=cvids,
            symbol_type=symbol_type,
            game_folder=game_folder,
            limit=limit,
            include_compatch=include_compatch,
            load_order_map=load_order_map,
        )
        
        # Apply symbol_names filter if provided
        if symbol_names and result.get("conflicts"):
            names_lower = {n.lower() for n in symbol_names}
            result["conflicts"] = [
                c for c in result["conflicts"]
                if c["name"].lower() in names_lower
            ]
            result["conflict_count"] = len(result["conflicts"])
        
        return rb.success(
            'WA-READ-S-001',
            data=result,
            message=f"Found {result.get('conflict_count', 0)} symbol conflicts.",
        )
    
    elif command == "files":
        # File-level conflict detection with last-loaded determination
        # File conflicts are ALWAYS LIOS (last wins) regardless of content policy
        cv_filter = ",".join(str(cv) for cv in cvids)
        
        sql = f"""
            SELECT 
                f.relpath,
                f.content_version_id,
                cv.name as mod_name
            FROM files f
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            WHERE f.content_version_id IN ({cv_filter})
        """
        params: list = []
        
        if game_folder:
            sql += " AND f.relpath LIKE ?"
            params.append(f"{game_folder}%")
        
        sql += " ORDER BY f.relpath"
        
        rows = db.conn.execute(sql, params).fetchall()
        
        # Group by relpath, attach load_order, determine last-loaded
        from collections import defaultdict
        by_relpath: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            cv_id = row["content_version_id"]
            by_relpath[row["relpath"]].append({
                "mod": row["mod_name"],
                "load_order": load_order_map.get(cv_id, -1),
            })
        
        conflicts = []
        for relpath, sources in by_relpath.items():
            if len(sources) < 2:
                continue
            # File-level is always LIOS (last loaded wins for overlapping identities)
            last_order = max(s["load_order"] for s in sources)
            for s in sources:
                s["is_last_loaded"] = (s["load_order"] == last_order)
            last_loaded_sources = [s for s in sources if s["is_last_loaded"]]
            
            fname = relpath.rsplit("/", 1)[-1] if "/" in relpath else relpath
            conflicts.append({
                "relpath": relpath,
                "mods": [s["mod"] for s in sources],
                "sources": sources,
                "mod_count": len(sources),
                "last_loaded": last_loaded_sources[0]["mod"] if last_loaded_sources else None,
                "has_zzz_prefix": fname.startswith("zzz_"),
            })
            if len(conflicts) >= limit:
                break
        
        return rb.success(
            'WA-READ-S-001',
            data={"conflicts": conflicts, "count": len(conflicts)},
            message=f"Found {len(conflicts)} file conflicts.",
        )
    
    elif command == "summary":
        # Summary statistics
        # Note: cvids already validated above - this code path only reached if cvids exist
        cv_filter = ",".join(str(cv) for cv in cvids)
        
        # Count symbol conflicts by type
        # GOLDEN JOIN: symbols → asts → files → content_versions
        # (symbols has ast_id, NOT content_version_id)
        type_sql = f"""
            SELECT 
                sub.symbol_type,
                COUNT(DISTINCT sub.name) as conflict_count
            FROM (
                SELECT s.symbol_type, s.name
                FROM symbols s
                JOIN asts a ON s.ast_id = a.ast_id
                JOIN files f ON a.content_hash = f.content_hash
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                WHERE cv.content_version_id IN ({cv_filter})
                GROUP BY s.symbol_type, s.name
                HAVING COUNT(DISTINCT cv.content_version_id) > 1
            ) sub
            GROUP BY sub.symbol_type
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
        
        return rb.success(
            'WA-READ-S-001',
            data={
                "total_symbol_conflicts": total_symbols,
                "total_file_conflicts": total_files,
                "by_type": by_type,
                "by_folder": by_folder,
            },
            message=f"Summary: {total_symbols} symbol conflicts, {total_files} file conflicts.",
        )
    
    else:
        return rb.invalid(
            'WA-SYS-I-001',
            data={"error": f"Unknown command: {command}", "valid_commands": ["symbols", "files", "summary"]},
            message=f"Unknown command: {command}",
        )


# ============================================================================
# Unified File Operations
# ============================================================================

@mcp.tool()
@mcp_safe_tool
def ck3_file(
    command: Literal["get", "read", "write", "edit", "delete", "rename", "refresh", "list", "create_patch"],
    # Path identification
    path: str | None = None,
    mod_name: str | None = None,  # Mod name, or "wip"/"vanilla" for those domains
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
) -> Reply:
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
        mod_name: Target identifier. Accepts:
            - Mod name from active playset (writes require mod under local_mods_folder)
            - "wip" → routes to WIP workspace (~/.ck3raven/wip/)
            - "vanilla" → routes to vanilla game files (read-only)
            Alternatively, use path parameter with canonical addresses (wip:/file.py)
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
    
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_file')
    
    session = _get_session()
    trace = _get_trace()
    world = _get_world()  # WorldAdapter for unified path resolution
    
    # Only acquire DB connection for commands that need it
    db = _get_db() if command == "get" else None
    
    result = ck3_file_impl(
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
        rb=rb,
    )
    
    # If impl returned a Reply directly, pass it through
    if isinstance(result, Reply):
        return result
    
    if result.get("error") or result.get("reply_type") == "D":
        err = str(result.get("error", "File operation failed"))
        err_lower = err.lower()
        policy_decision = result.get("policy_decision", "")
        visibility = result.get("visibility", "")
        
        # Pre-enforcement mode denial (mode not initialized)
        if policy_decision == "DENY":
            return rb.denied('EN-WRITE-D-001', data=result, message=err)
        
        # Invalid reference / not found
        if visibility == "NOT_FOUND" or "not found" in err_lower or "unknown" in err_lower:
            return rb.invalid('WA-RES-I-001', data=result, message=err)
        
        # System failure requires POSITIVE evidence
        if "failed to" in err_lower or "timeout" in err_lower or "connection" in err_lower or "exception" in err_lower:
            return rb.error('MCP-SYS-E-001', data=result, message=err)
        
        # Default: Invalid (agent mistake / bad input)
        return rb.invalid('WA-RES-I-001', data=result, message=err)
    
    # Determine if this was a read or write operation for correct code
    # Write operations pass through enforcement -> EN layer owns success
    if command in ("write", "edit", "delete", "rename"):
        return rb.success('EN-WRITE-S-001', data=result, message=f"File {command} complete.")
    else:
        return rb.success('WA-READ-S-001', data=result, message=f"File {command} complete.")


# ============================================================================
# Unified Folder Operations
# ============================================================================

@mcp.tool()
@mcp_safe_tool
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
) -> Reply:
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
    
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_folder')
    
    session = _get_session()
    trace = _get_trace()
    world = _get_world()  # WorldAdapter for visibility enforcement
    
    # Only acquire DB connection for commands that need it
    db_required = command in ("contents", "top_level", "mod_folders")
    db = _get_db() if db_required else None
    
    # CANONICAL: Get cvids from session.mods[] instead of using playset_id
    cvids = [m.cvid for m in session.mods if m.cvid is not None] if db_required else None
    
    result = ck3_folder_impl(
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
    
    if result.get("error"):
        err_msg = str(result.get("error", "")).lower()
        # System failure requires POSITIVE evidence
        if "failed to" in err_msg or "timeout" in err_msg or "connection" in err_msg or "exception" in err_msg:
            return rb.error('MCP-SYS-E-001', data=result, message=result.get("error", "Folder operation failed"))
        # Default: Invalid (agent mistake / bad input)
        return rb.invalid('WA-RES-I-001', data=result, message=result.get("error", "Folder operation failed"))
    
    return rb.success('WA-READ-S-001', data=result, message=f"Folder {command} complete.")


# ============================================================================
# Unified Playset Operations
# ============================================================================

@mcp.tool()
@mcp_safe_tool
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
    mod_ids: list[int] | None = None,
    # For import
    launcher_playset_name: str | None = None,
    # For mods command
    limit: int | None = None,
) -> Reply:
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
        mod_ids: List of content_version_ids (for create)
        launcher_playset_name: Launcher playset to import (for import)
        limit: Max mods to return for 'mods' command (default: None = all mods)
    
    Returns:
        Dict with playset info or operation result
    """
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_playset')
    
    result = _ck3_playset_internal(
        command, playset_name, mod_name, new_position,
        name, description, mod_ids, launcher_playset_name, limit
    )
    
    if result.get("invalid"):
        return rb.invalid('WA-VIS-I-001', data=result, message=result["invalid"])
    
    if result.get("error"):
        return rb.error('MCP-SYS-E-001', data=result, message=result["error"])
    
    if command == "switch":
        return rb.success('WA-VIS-S-001', data=result, message=f"Switched to playset: {result.get('playset_name')}")
    
    if command == "get":
        name_val = result.get("playset_name") or result.get("name")
        return rb.success('WA-VIS-S-001', data=result, message=f"Active playset: {name_val}")
    
    return rb.success('WA-VIS-S-001', data=result, message=f"Playset {command} complete.")


def _ck3_playset_internal(
    command: str,
    playset_name: str | None,
    mod_name: str | None,
    new_position: int | None,
    name: str | None,
    description: str | None,
    mod_ids: list[int] | None,
    launcher_playset_name: str | None,
    limit: int | None,
) -> dict:
    """Internal implementation returning dict."""
    global _session, _session_cv_ids_resolved
    
    from pathlib import Path
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
            return {"success": False, "invalid": "playset_name required for switch"}
        
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
            return {"success": False, "invalid": f"Playset '{playset_name}' not found"}
        
        # Update manifest
        manifest = {
            "active": target_file.name,
            "last_switched": datetime.now().isoformat(),
            "notes": "Updated by ck3_playset switch command"
        }
        PLAYSET_MANIFEST_FILE.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        
        # Clear cached session to force reload from new playset
        _session = None
        _session_cv_ids_resolved = False
        
        # Reload session from new playset
        session = _get_session()
        
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
                                    WHERE cv.name = ? AND bq.status = 'pending') as pending_count
                            FROM files f
                            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                            WHERE cv.name = ?
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
                
                # Calculate statistics for build_status
                total_mods = len(mods)
                missing_count = len(mods_missing_from_disk)
                pending_count = sum(1 for m in mods_needing_build if m.get("status") == "pending_build")
                not_indexed_count = sum(1 for m in mods_needing_build if m.get("status") == "not_indexed")
                ready_count = total_mods - missing_count - len(mods_needing_build)
                
                build_status = {
                    "needs_build": len(mods_needing_build) > 0,
                    "mods": mods_needing_build,
                    # Add the keys that the result construction expects:
                    "playset_valid": total_mods > 0 and missing_count < total_mods,
                    "ready_mods": max(0, ready_count),
                    "pending_mods": pending_count + not_indexed_count,
                    "missing_mods": missing_count,
                }
        except Exception as e:
            # DB might not be available yet - need to build everything
            build_status = {"error": str(e), "needs_build": True}
        
        result = {
            "success": True,
            "message": f"Switched to playset: {target_file.name}",
            "active_playset": target_file.name,
            "playset_name": session.playset_name,
            "mod_count": len(session.mods),
        }
        
        # Report missing-from-disk mods (these cannot be built)
        if mods_missing_from_disk:
            result["mods_missing_from_disk"] = mods_missing_from_disk
            result["missing_warning"] = (
                f"⚠ {len(mods_missing_from_disk)} mod(s) are in playset but not on disk. "
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
            result["build_status_message"] = "✓ All mods are ready. No build needed."
        
        return result
    
    elif command == "get":
        # Get current active playset info
        session = _get_session()
        manifest_active = None
        if PLAYSET_MANIFEST_FILE.exists():
            try:
                manifest = json.loads(PLAYSET_MANIFEST_FILE.read_text(encoding='utf-8-sig'))
                manifest_active = manifest.get("active")
            except Exception:
                pass
        
        # Get vanilla root from session.vanilla (mods[0])
        vanilla_root = None
        if session.vanilla and session.vanilla.path:
            vanilla_root = str(session.vanilla.path)
        
        return {
            "success": True,
            "active_file": manifest_active,
            "playset_name": session.playset_name,
            "source": "json" if session.playset_name else "none",
            "mod_count": len(session.mods),
            "has_agent_briefing": False,  # TODO: Implement agent briefing in Session
            "vanilla_root": vanilla_root,
            "local_mods_folder": str(session.local_mods_folder) if session.local_mods_folder else None,
        }
    
    elif command == "mods":
        # Get mods in active playset
        session = _get_session()
        
        # All mods in session.mods are "enabled" - they're part of the active playset
        # The concept of enabled/disabled doesn't apply here - disabled mods wouldn't be loaded
        mods_list = session.mods
        
        # Convert ModEntry to dict for JSON serialization
        def mod_to_dict(m):
            return {
                "name": m.name,
                "path": str(m.path) if m.path else None,
                "load_order": m.load_order,
                "workshop_id": m.workshop_id,
                "cvid": m.cvid,
                "is_indexed": m.is_indexed,
                "is_vanilla": m.is_vanilla,
            }
        
        mods_to_return = mods_list[:limit] if limit else mods_list
        
        return {
            "success": True,
            "playset_name": session.playset_name,
            "mod_count": len(mods_list),
            "mods": [mod_to_dict(m) for m in mods_to_return],
            "truncated": limit is not None and len(mods_list) > limit,
        }
    
    elif command == "add_mod":
        # Add a mod to the active playset's local_mods array
        if not mod_name:
            return {"success": False, "invalid": "mod_name required for add_mod"}
        
        # Get the active playset file
        session = _get_session()
        if not session.playset_name:
            return {"success": False, "invalid": "No active playset. Switch to one first."}
        
        # Find the active playset file
        if not PLAYSET_MANIFEST_FILE.exists():
            return {"success": False, "invalid": "No playset manifest found"}
        
        try:
            manifest = json.loads(PLAYSET_MANIFEST_FILE.read_text(encoding="utf-8-sig"))
            active_file = manifest.get("active")
            if not active_file:
                return {"success": False, "invalid": "No active playset in manifest"}
            
            playset_path = PLAYSETS_DIR / active_file
            if not playset_path.exists():
                return {"success": False, "invalid": f"Active playset file not found: {active_file}"}
            
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
            from ck3lens.paths import ROOT_USER_DOCS
            mod_dirs = [
                ROOT_USER_DOCS / "mod",
            ] if ROOT_USER_DOCS else []
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
                "invalid": f"Could not find mod '{mod_name}'. Provide full path or ensure mod is installed.",
                "hint": "Use full path to mod folder, e.g., 'C:\\...\\mod\\MyModFolder'"
            }
        
        # Check if already in mods[]
        mods_list = playset_data.get("mods", [])
        for existing in mods_list:
            if existing.get("name", "").lower() == mod_name.lower() or existing.get("path") == mod_path:
                return {
                    "success": False,
                    "invalid": f"Mod '{mod_name}' is already in mods[]",
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
        
        # Clear cached session to force reload
        _session = None
        _session_cv_ids_resolved = False
        
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
                    WHERE cv.name = ?
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
    
    elif command == "import":
        # Import playset from CK3 launcher database
        # Uses read-only connection - safe for concurrent launcher access
        from pathlib import Path
        from datetime import date
        from ck3lens.paths import ROOT_USER_DOCS, ROOT_STEAM, ROOT_GAME
        
        if not ROOT_USER_DOCS or not ROOT_STEAM or not ROOT_GAME:
            return {"success": False, "invalid": "Missing path configuration (ROOT_USER_DOCS, ROOT_STEAM, or ROOT_GAME). Run ck3_paths_doctor() to diagnose."}
        
        launcher_db = ROOT_USER_DOCS / "launcher-v2.sqlite"
        
        if not launcher_db.exists():
            return {"success": False, "invalid": f"Launcher database not found: {launcher_db}"}
        
        # Connect in read-only mode (safe for concurrent access)
        import sqlite3
        try:
            conn = sqlite3.connect(f"file:{launcher_db}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
        except Exception as e:
            return {"success": False, "error": f"Failed to connect to launcher DB: {e}"}
        
        try:
            # If no playset name specified, list available playsets
            if not launcher_playset_name:
                rows = conn.execute("""
                    SELECT id, name, isActive,
                        (SELECT COUNT(*) FROM playsets_mods WHERE playsetId = playsets.id) as mod_count
                    FROM playsets
                    ORDER BY name
                """).fetchall()
                
                available = []
                for row in rows:
                    available.append({
                        "name": row["name"],
                        "mod_count": row["mod_count"],
                        "is_active": bool(row["isActive"]),
                    })
                
                return {
                    "success": True,
                    "message": "Use launcher_playset_name parameter to import a specific playset",
                    "available_playsets": available,
                    "hint": "ck3_playset(command='import', launcher_playset_name='YourPlaysetName')"
                }
            
            # Find the requested playset
            # Try exact match first
            row = conn.execute(
                "SELECT id, name, isActive FROM playsets WHERE name = ?", 
                (launcher_playset_name,)
            ).fetchone()
            
            if not row:
                # Try case-insensitive partial match
                row = conn.execute(
                    "SELECT id, name, isActive FROM playsets WHERE name LIKE ?", 
                    (f"%{launcher_playset_name}%",)
                ).fetchone()
            
            if not row:
                return {"success": False, "invalid": f"Playset '{launcher_playset_name}' not found in launcher DB"}
            
            playset_id = row["id"]
            playset_name_actual = row["name"]
            
            # Get all mods in this playset
            mods_rows = conn.execute("""
                SELECT pm.position, pm.enabled, m.displayName, m.steamId, m.dirPath, m.source
                FROM playsets_mods pm
                JOIN mods m ON pm.modId = m.id
                WHERE pm.playsetId = ?
                ORDER BY pm.position
            """, (playset_id,)).fetchall()
            
            # Build mods array - only include ENABLED mods
            mods_list = []
            disabled_mods = []  # Track disabled mods for advisory
            steam_count = 0
            local_count = 0
            local_positions = []
            
            for mod_row in mods_rows:
                position = mod_row["position"]
                enabled = bool(mod_row["enabled"])
                display_name = mod_row["displayName"]
                steam_id = mod_row["steamId"]
                dir_path = mod_row["dirPath"]
                source = mod_row["source"]
                
                # Skip disabled mods - they should not be in the playset
                if not enabled:
                    disabled_mods.append(display_name)
                    continue
                
                # Determine path
                is_local = source in ("local", None) or (dir_path and "mod" in str(dir_path).lower() and "workshop" not in str(dir_path).lower())
                
                if steam_id and not is_local:
                    # Steam workshop mod
                    mod_path = str(ROOT_STEAM / steam_id)
                    steam_count += 1
                elif dir_path:
                    # Local mod - use dirPath
                    mod_path = str(Path(dir_path).resolve())
                    local_count += 1
                    local_positions.append(position)
                    is_local = True
                else:
                    # Fallback - try to construct path
                    mod_path = str(ROOT_USER_DOCS / "mod" / display_name.replace(" ", ""))
                    local_count += 1
                    local_positions.append(position)
                    is_local = True
                
                # Detect compatch
                name_lower = display_name.lower()
                is_compatch = any(kw in name_lower for kw in ["compatch", "compatibility", "patch"]) and "unofficial" not in name_lower
                
                mod_entry = {
                    "name": display_name,
                    "path": mod_path.replace("/", "\\"),
                    "load_order": position,
                    "is_compatch": is_compatch,
                    "notes": "local mod" if is_local else "",
                }
                
                if steam_id and not is_local:
                    mod_entry["steam_id"] = steam_id
                
                mods_list.append(mod_entry)
            
            # Build playset JSON
            today = date.today().isoformat()
            safe_name = playset_name_actual.replace(" ", "_").replace("/", "_")
            output_filename = f"{safe_name}_playset.json"
            output_path = PLAYSETS_DIR / output_filename
            
            playset_data = {
                "$schema": "./playset.schema.json",
                "playset_name": playset_name_actual,
                "description": f"Imported from CK3 Launcher DB on {today} ({steam_count} Steam, {local_count} local mods)",
                "created": today,
                "last_modified": today,
                "vanilla": {
                    "version": "1.18",
                    "path": str(ROOT_GAME),
                    "enabled": True
                },
                "mods": mods_list,
                "local_mods_folder": str(ROOT_USER_DOCS / "mod"),
                "agent_briefing": {
                    "context": f"Playset '{playset_name_actual}' with {len(mods_list)} mods",
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
            
            # Write the playset file
            output_path.write_text(json.dumps(playset_data, indent=2), encoding="utf-8")
            
            result = {
                "success": True,
                "message": f"Imported playset '{playset_name_actual}'",
                "playset_file": str(output_path),
                "total_mods": len(mods_list),
                "steam_mods": steam_count,
                "local_mods": local_count,
                "local_positions": local_positions,
                "hint": f"Switch with: ck3_playset(command='switch', playset_name='{playset_name_actual}')"
            }
            
            # Add advisory about disabled mods if any were skipped
            if disabled_mods:
                result["disabled_mods_omitted"] = len(disabled_mods)
                result["disabled_mod_names"] = disabled_mods
                result["advisory"] = f"{len(disabled_mods)} disabled mod(s) were not imported: {', '.join(disabled_mods[:5])}" + (f" (and {len(disabled_mods) - 5} more)" if len(disabled_mods) > 5 else "")
            
            return result
            
        finally:
            conn.close()
    
    else:
        # Other commands not yet implemented for file-based
        return {
            "success": False,
            "invalid": f"Command '{command}' not yet implemented for file-based playsets",
            "hint": "Use 'get', 'list', 'switch', or 'mods' commands"
        }


# ============================================================================
# Unified Git Operations
# ============================================================================

@mcp.tool()
@mcp_safe_tool
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
) -> Reply:
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
    
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_git')
    
    session = _get_session()
    trace = _get_trace()
    world = _get_world()  # For canonical path resolution
    
    result = ck3_git_impl(
        command=command,
        mod_name=mod_name,
        file_path=file_path,
        files=files,
        all_files=all_files,
        message=message,
        limit=limit,
        session=session,
        trace=trace,
        world=world,  # Pass world for enforce()
        rb=rb,
    )
    
    # Enforcement denial returns Reply directly — pass through
    if isinstance(result, Reply):
        return result
    
    if result.get("error"):
        err_msg = str(result.get("error", "")).lower()
        
        # System failure requires POSITIVE evidence
        if "failed to" in err_msg or "timeout" in err_msg or "connection" in err_msg or "exception" in err_msg:
            return rb.error('MCP-SYS-E-001', data=result, message=result.get("error", "Git command failed"))
        
        # Default: Invalid (agent mistake / bad input)
        return rb.invalid('WA-GIT-I-001', data=result, message=result.get("error", "Git command failed"))
    
    return rb.success('WA-GIT-S-001', data=result, message=f"Git {command} complete.")


# ============================================================================
# Unified Validation Operations
# ============================================================================

@mcp.tool()
@mcp_safe_tool
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
) -> Reply:
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
    
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_validate')
    
    db = _get_db()
    
    result = ck3_validate_impl(
        target=target,
        content=content,
        file_path=file_path,
        symbol_name=symbol_name,
        symbol_type=symbol_type,
        artifact_bundle=artifact_bundle,
        mode=mode,
        trace_path=trace_path,
        db=db,
        trace=None,  # Deprecated: using ReplyBuilder
    )
    
    if "error" in result:
        return rb.error(
            'MCP-SYS-E-001',
            data=result,
            message=result["error"],
        )
    
    return rb.success(
        'WA-VAL-S-001',
        data=result,
        message=f"Validation completed: target={target}",
    )


# ============================================================================
# VS Code IPC Operations
# ============================================================================

@mcp.tool()
@mcp_safe_tool
def ck3_vscode(
    command: Literal["ping", "diagnostics", "all_diagnostics", "errors_summary", 
                     "validate_file", "open_files", "active_file", "status"] = "status",
    # For diagnostics/validate_file
    path: str | None = None,
    # For all_diagnostics
    severity: str | None = None,
    source: str | None = None,
    limit: int = 50,
) -> Reply:
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
    
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_vscode')
    
    result = ck3_vscode_impl(
        command=command,
        path=path,
        severity=severity,
        source=source,
        limit=limit,
        trace=None,  # Deprecated: using ReplyBuilder
    )
    
    if "error" in result:
        return rb.error(
            'MCP-SYS-E-001',
            data=result,
            message=result["error"],
        )
    
    return rb.success(
        'WA-IO-S-001',
        data=result,
        message=f"VS Code operation completed: command={command}",
    )


# ============================================================================
# CK3 Repair Tool (Launcher Registry, Cache)
# ============================================================================

@mcp.tool()
@mcp_safe_tool
def ck3_repair(
    command: Literal["query", "diagnose_launcher", "repair_registry", "delete_cache", "backup_launcher", "migrate_paths"] = "query",
    # For query - get status of repair targets
    target: Literal["all", "launcher", "cache", "dlc_load"] | None = None,
    # For repair_registry / delete_cache
    dry_run: bool = True,
    # For backup
    backup_name: str | None = None,
) -> Reply:
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
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_repair')
    
    return _ck3_repair_internal(command, target, dry_run, backup_name, rb=rb, trace_info=trace_info)


def _ck3_repair_internal(
    command: str,
    target: str | None,
    dry_run: bool,
    backup_name: str | None,
    *,
    rb: ReplyBuilder,
    trace_info: TraceInfo,
) -> Reply:
    """Internal implementation returning Reply."""
    import shutil
    from pathlib import Path
    from datetime import datetime
    from ck3lens.paths import ROOT_CK3RAVEN_DATA
    
    trace = _get_trace()
    session = _get_session()
    
    ck3raven_dir = ROOT_CK3RAVEN_DATA
    
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
                },
                "wip": {
                    "files": len(wip_files),
                    "path": str(ck3raven_dir / "wip"),
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
                diag_reply = _diagnose_launcher_db(launcher_db, trace_info=trace_info)
                status["launcher_details"] = diag_reply.data
        
        trace.log("mcp.repair", {"command": "query", "target": target}, {"success": True})
        return rb.success('MCP-SYS-S-001', data=status, message="Repair query complete.")
    
    elif command == "diagnose_launcher":
        if not launcher_db:
            return rb.invalid('MCP-SYS-I-001', data={
                "checked_paths": [str(p) for p in launcher_db_candidates],
            }, message="CK3 launcher database not found")
        
        # Delegate to _diagnose_launcher_db which returns its own Reply
        return _diagnose_launcher_db(launcher_db, trace_info=trace_info)
    
    elif command == "backup_launcher":
        if not launcher_db:
            return rb.invalid('MCP-SYS-I-001', data={}, message="CK3 launcher database not found")
        
        backups_dir = ck3raven_dir / "launcher_backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = backup_name or f"launcher-v2_{timestamp}"
        backup_path = backups_dir / f"{name}.sqlite"
        
        shutil.copy2(launcher_db, backup_path)
        
        trace.log("mcp.repair", {"command": "backup_launcher"}, {"backup_path": str(backup_path)})
        return rb.success('MCP-SYS-S-001', data={
            "backup_path": str(backup_path),
            "original_path": str(launcher_db),
            "backup_size": backup_path.stat().st_size,
        }, message="Launcher database backed up.")
    
    elif command == "repair_registry":
        if not launcher_db:
            return rb.invalid('MCP-SYS-I-001', data={}, message="CK3 launcher database not found")
        
        if dry_run:
            return rb.success('MCP-SYS-S-002', data={
                "dry_run": True,
                "recommendation": "Run backup_launcher first, then diagnose_launcher to see issues.",
            }, message="Would repair launcher registry. Set dry_run=False to proceed.")
        
        return rb.error('MCP-SYS-E-001', data={
            "reason": "Launcher database modifications require careful testing to avoid data loss",
            "workaround": "Use the CK3 launcher UI to reset settings, or delete ~/.ck3raven/ck3raven.db to force rebuild",
        }, message="Launcher repair not yet implemented")
    
    elif command == "delete_cache":
        cache_dir = ck3raven_dir
        wip_dir = ck3raven_dir / "wip"
        
        if dry_run:
            cache_files = list(cache_dir.glob("*.cache")) if cache_dir.exists() else []
            wip_files = list(wip_dir.rglob("*")) if wip_dir.exists() else []
            
            return rb.success('MCP-SYS-S-002', data={
                "dry_run": True,
                "would_delete": {
                    "cache_files": [str(f) for f in cache_files[:10]],
                    "cache_count": len(cache_files),
                    "wip_files": [str(f) for f in wip_files[:10]],
                    "wip_count": len(wip_files),
                },
            }, message="Set dry_run=False to delete these files")
        
        deleted = {"cache": 0, "wip": 0}
        
        for cache_file in cache_dir.glob("*.cache"):
            try:
                cache_file.unlink()
                deleted["cache"] += 1
            except Exception:
                pass
        
        if wip_dir.exists():
            for item in wip_dir.rglob("*"):
                if item.is_file():
                    try:
                        item.unlink()
                        deleted["wip"] += 1
                    except Exception:
                        pass
        
        trace.log("mcp.repair", {"command": "delete_cache", "dry_run": False}, deleted)
        return rb.success('MCP-SYS-S-001', data={
            "deleted": deleted,
        }, message="Cache cleared. ck3raven will rebuild as needed.")
    
    elif command == "migrate_paths":
        from .ck3lens.path_migration import detect_path_mismatch, migrate_playset_paths
        
        if not session.playset_name:
            return rb.invalid('MCP-SYS-I-001', data={}, message="No active playset. Use ck3_playset to switch to one first.")
        
        playsets_dir = ROOT_CK3RAVEN_DATA / "playsets"
        playset_file = None
        playset_data = None
        
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
            return rb.invalid('MCP-SYS-I-001', data={
                "hint": "Playset may be stored in database only, not a JSON file",
            }, message=f"Could not find playset file for '{session.playset_name}'")
        
        assert playset_file is not None
        
        local_mods_folder_val = playset_data.get("local_mods_folder", "")
        mismatch = detect_path_mismatch(local_mods_folder_val)
        
        if not mismatch:
            mods_list = playset_data.get("mods", [])
            for mod in mods_list:
                disk_path = mod.get("disk_path", "")
                if disk_path:
                    mismatch = detect_path_mismatch(disk_path)
                    if mismatch:
                        break
        
        if not mismatch:
            return rb.success('MCP-SYS-S-001', data={
                "local_mods_folder": local_mods_folder_val,
            }, message="No path migration needed - paths already match current user profile")
        
        old_user, new_user = mismatch
        migrated_data, was_modified, migration_msg = migrate_playset_paths(playset_data)
        
        if not was_modified:
            return rb.success('MCP-SYS-S-001', data={}, message="No changes needed")
        
        if dry_run:
            return rb.success('MCP-SYS-S-002', data={
                "dry_run": True,
                "migration": {"old_user": old_user, "new_user": new_user, "message": migration_msg},
                "playset_file": str(playset_file),
            }, message="Set dry_run=False to save changes to playset file")
        
        try:
            with open(playset_file, 'w', encoding='utf-8') as fp:
                json.dump(migrated_data, fp, indent=2, ensure_ascii=False)
            
            _load_playset_from_json(playset_file)
            
            trace.log("mcp.repair", {"command": "migrate_paths", "dry_run": False}, {
                "old_user": old_user, "new_user": new_user, "file": str(playset_file),
            })
            
            return rb.success('MCP-SYS-S-001', data={
                "migration": {"old_user": old_user, "new_user": new_user, "message": migration_msg},
                "playset_file": str(playset_file),
            }, message="Paths migrated and playset reloaded")
        except Exception as e:
            return rb.error('MCP-SYS-E-001', data={}, message=f"Failed to save migrated playset: {e}")
    
    return rb.invalid('MCP-SYS-I-001', data={}, message=f"Unknown command: {command}")


def _diagnose_launcher_db(launcher_db: Path, *, trace_info: TraceInfo) -> Reply:
    """
    Analyze CK3 launcher database for issues.
    
    Returns Reply with diagnosis report.
    """
    import sqlite3
    rb = ReplyBuilder(trace_info, tool='_diagnose_launcher_db')
    
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
        
        return rb.success("MCP-SYS-S-001", data=result)
        
    except Exception as e:
        return rb.error("MCP-SYS-E-001", data={"error": f"Failed to analyze launcher database: {e}"})


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
@mcp_safe_tool
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
) -> Reply:
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
        root_category: Geographic scope (ONE of: ROOT_REPO, ROOT_USER_DOCS,
            ROOT_STEAM, ROOT_GAME, ROOT_CK3RAVEN_DATA, ROOT_VSCODE, ROOT_EXTERNAL)
        operations: List of operations (READ, WRITE, DELETE)
        targets: List of target dicts with target_type, path, description
        work_declaration: REQUIRED for mutating operations. JSON schema:
            {
                "work_summary": "Brief description of the work",
                "work_plan": ["Step 1", "Step 2", ...],  // 1-15 items
                "out_of_scope": ["What this does NOT include"],
                "edits": [  // REQUIRED for WRITE/DELETE operations
                    {
                        "file": "relative/path/to/file.py",
                        "edit_kind": "add" | "modify" | "delete" | "rename",
                        "location": "description of where in file",
                        "change_description": "what changes are being made"
                    }
                ]
            }
        expires_hours: Hours until expiry (default 8)
        contract_id: Contract ID for close/cancel (uses active if not specified)
        closure_commit: Git commit SHA for close
        cancel_reason: Reason for cancellation
        status_filter: Filter list by status
        include_archived: Include archived in list
    
    Returns:
        Contract info or operation result
    
    Examples:
        # ck3raven-dev mode with work_declaration
        ck3_contract(
            command="open",
            intent="Fix parser bug",
            root_category="ROOT_REPO",
            work_declaration={
                "work_summary": "Fix off-by-one error in lexer",
                "work_plan": ["Locate bug in lexer.py", "Add test case", "Fix bug"],
                "out_of_scope": ["Parser changes"],
                "edits": [{
                    "file": "src/ck3raven/parser/lexer.py",
                    "edit_kind": "modify",
                    "location": "tokenize() function",
                    "change_description": "Fix boundary check"
                }]
            }
        )
    """
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_contract')
    
    result = _ck3_contract_internal(
        command, intent, root_category, operations, targets, work_declaration,
        expires_hours, contract_id, closure_commit, cancel_reason, status_filter, include_archived
    )
    
    if result.get("error") or result.get("success") is False:
        error_msg = result.get("error") or result.get("message") or "Contract operation failed"
        # Authorization denial -> EN layer (CT cannot emit D)
        if "not authorized" in str(error_msg).lower():
            return rb.denied('EN-GATE-D-001', data=result, message=error_msg)
        return rb.error(
            result.get("code", "MCP-SYS-E-001"),
            data=result,
            message=error_msg,
        )
    
    if command == "status":
        if result.get("has_active_contract"):
            return rb.success('MCP-SYS-S-001', data=result, message=f"Active contract: {result.get('contract_id')}")
        # "No active contract" is informational, not governance denial
        return rb.invalid('CT-CLOSE-I-001', data=result, message="No active contract.")
    
    if command == "open":
        return rb.success('CT-OPEN-S-001', data=result, message=f"Contract opened: {result.get('contract_id')}")
    
    if command == "close":
        return rb.success('CT-CLOSE-S-001', data=result, message="Contract closed.")
    
    if command == "cancel":
        return rb.success('CT-CLOSE-S-002', data=result, message="Contract cancelled.")
    
    return rb.success('MCP-SYS-S-001', data=result, message=f"Contract {command} complete.")


def _ck3_contract_internal(
    command: str,
    intent: str | None,
    root_category: str | None,
    operations: list[str] | None,
    targets: list[dict] | None,
    work_declaration: dict | None,
    expires_hours: float,
    contract_id: str | None,
    closure_commit: str | None,
    cancel_reason: str | None,
    status_filter: str | None,
    include_archived: bool,
) -> dict:
    """Internal implementation returning dict."""
    from ck3lens.policy.contract_v1 import (
        open_contract, close_contract, cancel_contract,
        get_active_contract, list_contracts, archive_legacy_contracts,
        ContractV1, RootCategory, Operation, AgentMode,
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
        
        # Validate operations are valid enum values
        ops_list = operations or ["READ", "WRITE"]
        try:
            op_enums = [Operation(op) for op in ops_list]
        except ValueError as e:
            return {
                "error": f"Invalid operation: {e}",
                "valid_operations": [o.value for o in Operation],
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
            trace.log("contract.open", {
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
                    "code": "MCP-SYS-E-002",
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
                    "code": "MCP-SYS-E-003",
                    "message": f"Response exceeds {MAX_RESPONSE_BYTES} bytes. error_id={error_id}",
                    "error_id": error_id,
                }
            
            return result
        
        except ValueError as ve:
            # Contract validation errors - add contextual hints
            from ck3lens.hints import get_hint_engine
            
            error_msg = str(ve)
            hint_engine = get_hint_engine()
            hints = hint_engine.for_contract_error(error_msg, {
                "command": command,
                "intent": intent,
                "root_category": root_category,
                "operations": operations,
                "work_declaration": work_declaration,
            })
            
            return {
                "success": False,
                "code": "CT-VAL-E-001",
                "error": error_msg,
                **hints  # Include checklist, example, schema
            }
            
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
                "code": "MCP-SYS-E-001",
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
            
            trace.log("contract.close", {
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
            
            trace.log("contract.cancel", {
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
        
        trace.log("contract.flush", {}, {"archived": archived})
        
        return {
            "success": True,
            "archived": archived,
            "message": f"Archived {archived} contracts from previous days",
        }
    
    elif command == "archive_legacy":
        # Move all pre-v1 contracts to legacy folder
        archived = archive_legacy_contracts()
        
        trace.log("contract.archive", {}, {"archived": archived})
        
        return {
            "success": True,
            "archived": archived,
            "message": f"Archived {archived} legacy pre-v1 contracts",
        }
    
    return {"error": f"Unknown command: {command}"}


# ============================================================================
# Command Execution with Enforcement
# ============================================================================

@mcp.tool()
@mcp_safe_tool
def ck3_exec(
    command: str,
    working_dir: str | None = None,
    target_paths: list[str] | None = None,
    token_id: str | None = None,
    dry_run: bool = False,
    timeout: int = 30,
) -> Reply:
    """
    Execute a shell command with enforcement policy.
    
    Mode-aware behavior:
    - ck3lens mode: Limited to CK3/mod-related commands within playset scope
    - ck3raven-dev mode: Broader access for infrastructure work (USE THIS instead of run_in_terminal)
    
    This is the ONLY safe way for agents to run shell commands.
    All commands are evaluated against enforcement.py:
    
    - Safe commands (cat, git status, etc.) ? Allowed automatically
    - Mutating commands (rm *.py, git push) ? Require active contract
    - Blocked commands (rm -rf /) ? Always denied
    
    Args:
        command: Shell command to execute
        working_dir: Working directory (defaults to ck3raven root)
        target_paths: Files/dirs being affected (helps scope validation)
        token_id: Approval token ID (reserved for future use)
        dry_run: If True, only check policy without executing
        timeout: Max seconds to wait for command (default 30, max 300)
    
    Returns:
        {
            "allowed": bool,
            "executed": bool,  # False if dry_run or denied
            "output": str,     # Command output (if executed)
            "exit_code": int,  # Exit code (if executed)
            "policy": {
                "decision": "ALLOW" | "DENY",
                "reason": str,
                "category": str,
            }
        }
    
    Examples:
        ck3_exec("git status")  # Safe - allowed
        ck3_exec("cat file.txt")  # Safe - allowed
        ck3_exec("git push --force", dry_run=True)  # Check if would be allowed
    """
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_exec')
    
    # _ck3_exec_internal always returns Reply (normalized as of Feb 22, 2026)
    return _ck3_exec_internal(command, working_dir, target_paths, token_id, dry_run, timeout, rb=rb)


def _kill_process_tree_windows(pid: int) -> None:
    """
    Kill an entire process tree on Windows using taskkill /T /F.
    
    subprocess.run(timeout=N) only kills the direct child (powershell.exe)
    but orphans grandchild processes (python.exe, etc.). This uses
    'taskkill /T /F /PID' which recursively terminates the full tree.
    """
    import subprocess as _sp
    try:
        _sp.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        # Fallback: kill just the parent process
        try:
            os.kill(pid, 9)
        except Exception:
            pass


def _detect_script_path(command: str, cwd: Path | None) -> Path | None:
    """
    Detect if a shell command is executing a Python script file.

    Returns the absolute path to the script if detected, None otherwise.
    Handles:
        python script.py [args]
        python ./subdir/script.py
        python3 script.py

    Does NOT handle (whitelist territory):
        python -c "code"
        python -m module
        echo hello
        git status
    """
    import shlex
    parts = command.strip().split()
    if len(parts) < 2:
        return None

    exe = parts[0].lower()
    if exe not in ("python", "python3", "python.exe", "python3.exe"):
        return None

    # Skip flags: -c, -m are not file execution
    script_arg = parts[1]
    if script_arg.startswith("-"):
        return None

    # Resolve relative to cwd
    script = Path(script_arg)
    if not script.is_absolute() and cwd:
        script = cwd / script

    return script.resolve() if script.exists() else None



def _ck3_exec_internal(
    command: str,
    working_dir: str | None,
    target_paths: list[str] | None,
    token_id: str | None,
    dry_run: bool,
    timeout: int,
    rb=None,  # ReplyBuilder from tool handler — used by enforce()
) -> Reply:
    """Internal implementation. Always returns Reply."""
    from ck3lens.policy.enforcement_v2 import enforce
    from ck3lens.policy.contract_v1 import get_active_contract
    import subprocess

    # Get active contract
    active_contract = get_active_contract()
    has_contract = active_contract is not None

    # ==========================================================================
    # V2 ENFORCEMENT: Uses WorldAdapterV2 + enforcement_v2
    # ck3_exec is an EXECUTE operation on the resolved path.
    # ==========================================================================

    wa2 = _get_world_v2()

    # Resolve working directory or default to wip
    if working_dir:
        resolve_input = working_dir
    elif target_paths:
        resolve_input = target_paths[0]
    else:
        resolve_input = "root:ck3raven_data/wip"

    reply, ref = wa2.resolve(resolve_input, require_exists=True, rb=rb)
    if ref is None:
        return rb.invalid('WA-RES-I-001', data={
            "allowed": False,
            "executed": False,
            "output": None,
            "exit_code": None,
        }, message=f"Could not resolve path: {resolve_input}")

    # Working directory coordinates (used as fallback for enforcement)
    wd_root_key = reply.data.get("root_key", "")
    wd_subdirectory = reply.data.get("subdirectory")

    # ======================================================================
    # Data gathering (NOT a policy decision).
    # Detect script, hash content. Passed to enforce() as context kwargs.
    # The exec_gate condition handles the full decision tree:
    # whitelisted commands, script wip check, contract, and HMAC validation.
    # ======================================================================
    content_sha256 = None

    # Get host path for working directory
    host = wa2.host_path(ref)  # type: ignore[attr-defined]
    cwd = None
    if host is not None:
        cwd = host if host.is_dir() else host.parent

    # Detect if this is a script execution
    script_host_path = _detect_script_path(command, cwd)

    # ======================================================================
    # SCRIPT PATH WA2 RESOLUTION (§2)
    # If a script was detected, resolve its path through WA2 to get
    # the script's own root_key/subdirectory for enforcement.
    # This ensures enforcement evaluates the script's location,
    # not the working directory's location.
    # ======================================================================
    if script_host_path is not None:
        # Try to resolve the script's host-absolute path through WA2.
        # WA2.resolve() accepts canonical addresses, so we need to find
        # which root the script path falls under.
        script_root_key = wd_root_key
        script_subdirectory = wd_subdirectory
        for rk, root_path in wa2._roots.items():
            try:
                script_host_path.relative_to(root_path)
                # Script is under this root — resolve canonically
                rel = script_host_path.relative_to(root_path).as_posix()
                script_reply, script_ref = wa2.resolve(
                    f"root:{rk}/{rel}", require_exists=True, rb=rb
                )
                if script_ref is not None:
                    script_root_key = script_reply.data.get("root_key", rk)
                    script_subdirectory = script_reply.data.get("subdirectory")
                break
            except (ValueError, OSError):
                continue

        import hashlib as _hashlib
        try:
            current_content = script_host_path.read_bytes()
            content_sha256 = _hashlib.sha256(current_content).hexdigest()
        except OSError:
            pass  # content unreadable — condition will fail naturally
    else:
        script_root_key = wd_root_key
        script_subdirectory = wd_subdirectory

    # Use script coordinates for enforcement (script location matters, not cwd)
    enforce_root_key = script_root_key
    enforce_subdirectory = script_subdirectory

    # Shell execution is an EXECUTE operation — enforcement walks the matrix
    result = enforce(
        rb,
        mode=wa2.mode,
        tool="ck3_exec",
        command=command,
        root_key=enforce_root_key,
        subdirectory=enforce_subdirectory,
        # Context for exec_gate condition predicate
        exec_command=command,
        exec_subdirectory=enforce_subdirectory,
        has_contract=has_contract,
        script_host_path=str(script_host_path) if script_host_path else None,
        content_sha256=content_sha256,
    )

    # Enforcement denial — pass through
    if result.is_denied:
        return result

    # Enforcement passed — build policy info for response
    policy_info = {"decision": "ALLOW", "reason": f"Execute allowed ({result.code})"}
    
    # Allowed — dry run
    if dry_run:
        return rb.success('EN-EXEC-S-002', data={
            "allowed": True,
            "executed": False,
            "output": None,
            "exit_code": None,
            "policy": policy_info,
        }, message="Dry run - command would be allowed.")
    
    # Clamp timeout to max 300 seconds
    actual_timeout = min(max(timeout, 1), 300)
    
    # ======================================================================
    # Determine actual CWD for execution using WA v2 host_path
    # ======================================================================
    host = wa2.host_path(ref)
    if host is not None:
        exec_cwd = str(host) if host.is_dir() else str(host.parent)
    else:
        from ck3lens.paths import ROOT_REPO as _EXEC_ROOT_REPO
        exec_cwd = str(_EXEC_ROOT_REPO) if _EXEC_ROOT_REPO else None
    
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
        
        is_windows = platform.system() == "Windows"
        
        if is_windows:
            # =============================================================
            # FIX: Use Popen + manual timeout + process tree kill on Windows
            # subprocess.run(timeout=N) kills powershell.exe but orphans
            # child processes (python.exe, etc.) — taskkill /T /F kills the
            # entire process tree.
            # =============================================================
            ps_command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
            proc = subprocess.Popen(
                ps_command,
                shell=False,
                cwd=exec_cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                stdin=subprocess.DEVNULL,
                env=exec_env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            
            try:
                stdout, stderr = proc.communicate(timeout=actual_timeout)
            except subprocess.TimeoutExpired:
                # Kill entire process tree on Windows
                _kill_process_tree_windows(proc.pid)
                # Drain any remaining output after kill
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except Exception:
                    stdout, stderr = "", ""
                partial = f"{stdout}{stderr}".strip()
                partial_msg = f"\nPartial output:\n{partial}" if partial else ""
                return rb.error('MCP-SYS-E-001', data={
                    "allowed": True,
                    "executed": True,
                    "output": f"Command timed out after {actual_timeout} seconds (process tree killed).{partial_msg}",
                    "exit_code": -1,
                    "policy": policy_info,
                }, message=f"Command timed out after {actual_timeout}s. Use timeout= parameter to increase (max 300s).")
            
            return rb.success('EN-EXEC-S-001', data={
                "allowed": True,
                "executed": True,
                "output": stdout + stderr,
                "exit_code": proc.returncode,
                "policy": policy_info,
            }, message=f"Command executed. Exit code: {proc.returncode}.")
        else:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=exec_cwd,
                capture_output=True,
                text=True,
                timeout=actual_timeout,
                env=exec_env,
            )
            
            return rb.success('EN-EXEC-S-001', data={
                "allowed": True,
                "executed": True,
                "output": proc.stdout + proc.stderr,
                "exit_code": proc.returncode,
                "policy": policy_info,
            }, message=f"Command executed. Exit code: {proc.returncode}.")
    except subprocess.TimeoutExpired:
        # Non-Windows timeout (from subprocess.run on Unix)
        return rb.error('MCP-SYS-E-001', data={
            "allowed": True,
            "executed": True,
            "output": f"Command timed out after {actual_timeout} seconds",
            "exit_code": -1,
            "policy": policy_info,
        }, message=f"Command timed out after {actual_timeout}s. Use timeout= parameter to increase (max 300s).")
    except Exception as e:
        return rb.error('MCP-SYS-E-001', data={
            "allowed": True,
            "executed": False,
            "output": None,
            "exit_code": None,
            "policy": policy_info,
            "error": str(e),
        }, message=f"Execution failed: {e}")


@mcp.tool()
@mcp_safe_tool
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
) -> Reply:
    """
    DEPRECATED: Legacy token system replaced by HAT (Human Authorization Token).
    
    Only canonical tokens remain in tools/compliance/tokens.py:
    - NST (New Symbol Token): For creating new symbol identities
    - LXE (Lint Exception Token): For lint rule exceptions
    - HAT (Human Authorization Token): For protected file writes and mode init (see docs/PROTECTED_FILES_AND_HAT.md)
    
    This tool now returns a deprecation notice for all commands.
    """
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_token')
    
    return rb.invalid(
        'WA-CFG-I-001',
        data={
            "deprecated": True,
            "guidance": {
                "file_deletion": "File deletion requires active contract (same as write)",
                "git_push": "Git push allowed with active contract",
                "protected_files": "See docs/PROTECTED_FILES_AND_HAT.md for HAT system",
                "canonical_tokens": "NST, LXE, and HAT tokens are in tools/compliance/tokens.py",
            },
        },
        message="Token system deprecated. See HAT architecture for protected file authorization.",
    )



# ============================================================================
# Protected Files Management
# ============================================================================

@mcp.tool()
@mcp_safe_tool
def ck3_protect(
    command: Literal["list", "verify", "add", "remove"] = "list",
    path: str | None = None,
    entry_type: Literal["file", "folder"] | None = None,
    reason: str | None = None,
) -> Reply:
    '''
    Manage protected files manifest.

    Protected files require HAT (Human Authorization Token) approval to modify.
    The manifest at policy/protected_files.json tracks which files are protected.

    HAT approval is ephemeral: the extension writes a signed approval file,
    which is consumed (verified + deleted) here. No hat_id passes through chat.
    Click the shield icon in the CK3 Lens sidebar to approve pending requests.

    Commands:

    command=list   -> List all protected entries
    command=verify -> Check SHA256 hashes of all protected files
    command=add    -> Add file/folder to manifest (requires HAT approval)
    command=remove -> Remove entry from manifest (requires HAT approval)

    Args:
        command: Operation to perform
        path: Relative path for add/remove (e.g., ".github/copilot-instructions.md")
        entry_type: "file" or "folder" (for add, default "file")
        reason: Why this file is protected (for add)

    Returns:
        Protected files info or operation result

    Examples:
        ck3_protect(command="list")
        ck3_protect(command="verify")
        ck3_protect(command="add", path="docs/IMPORTANT.md", reason="Critical doc")
        ck3_protect(command="remove", path="docs/OLD.md")
    '''
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_protect')

    try:
        from tools.compliance.protected_files import (
            load_manifest, save_manifest, verify_all_hashes,
            compute_file_hash, is_protected, ProtectedEntry,
            _get_repo_root, MANIFEST_REL_PATH,
        )
    except ImportError as e:
        return rb.error('MCP-SYS-E-001', data={}, message=f"Failed to import protected_files module: {e}")

    if command == "list":
        entries = load_manifest()
        return rb.success(
            'MCP-SYS-S-001',
            data={
                "entries": [e.to_dict() for e in entries],
                "count": len(entries),
                "manifest_path": MANIFEST_REL_PATH,
                "hardcoded_protected": [MANIFEST_REL_PATH],
            },
            message=f"{len(entries)} protected entries.",
        )

    elif command == "verify":
        mismatches = verify_all_hashes()
        entries = load_manifest()
        return rb.success(
            'WA-VAL-S-001',
            data={
                "total_entries": len(entries),
                "mismatches": [
                    {
                        "path": p,
                        "expected": exp[:16] + "...",
                        "actual": (act[:16] + "...") if act != "FILE_NOT_FOUND" else act,
                    }
                    for p, exp, act in mismatches
                ],
                "all_match": len(mismatches) == 0,
            },
            message="All hashes match." if not mismatches else f"{len(mismatches)} hash mismatch(es) found.",
        )

    elif command == "add":
        if not path:
            return rb.invalid('MCP-SYS-I-001', data={}, message="path required for add command")
        if not reason:
            return rb.invalid('MCP-SYS-I-001', data={}, message="reason required for add command")

        # Consume ephemeral HAT approval (written by extension, verified + deleted here)
        try:
            from tools.compliance.tokens import consume_hat_approval, write_hat_request
        except ImportError as e:
            return rb.error('MCP-SYS-E-001', data={}, message=f"HAT module import failed: {e}")

        valid, msg = consume_hat_approval(required_paths=[path])
        if not valid:
            write_hat_request(
                intent=f"Add protected file: {path}",
                protected_paths=[path],
                root_category="ROOT_REPO",
            )
            return rb.invalid(
                'MCP-SYS-I-001',
                data={"requires_hat": True},
                message=f"HAT approval required: {msg}. Click the shield icon in CK3 Lens sidebar to approve.",
            )

        # Check if already protected
        if is_protected(path):
            return rb.invalid('MCP-SYS-I-001', data={}, message=f"Path already protected: {path}")

        # Compute hash for files
        resolved_type = entry_type or "file"
        sha256 = ""
        if resolved_type == "file":
            repo_root = _get_repo_root()
            file_path = repo_root / path
            if not file_path.exists():
                return rb.invalid('MCP-SYS-I-001', data={}, message=f"File not found: {path}")
            sha256 = compute_file_hash(file_path)

        from datetime import datetime
        entry = ProtectedEntry(
            path=path.replace("\\", "/"),
            entry_type=resolved_type,
            sha256=sha256,
            added_at=datetime.now().isoformat(),
            reason=reason,
        )

        entries = load_manifest()
        entries.append(entry)
        save_manifest(entries)

        return rb.success(
            'EN-WRITE-S-001',
            data={
                "added": entry.to_dict(),
                "total_entries": len(entries),
            },
            message=f"Protected: {path}",
        )

    elif command == "remove":
        if not path:
            return rb.invalid('MCP-SYS-I-001', data={}, message="path required for remove command")

        # Cannot remove the manifest itself (hardcoded)
        normalized = path.replace("\\", "/")
        if normalized == MANIFEST_REL_PATH:
            return rb.invalid(
                'MCP-SYS-I-001',
                data={},
                message=f"Cannot remove manifest self-protection: {MANIFEST_REL_PATH} is hardcoded.",
            )

        # Consume ephemeral HAT approval
        try:
            from tools.compliance.tokens import consume_hat_approval, write_hat_request
        except ImportError as e:
            return rb.error('MCP-SYS-E-001', data={}, message=f"HAT module import failed: {e}")

        valid, msg = consume_hat_approval(required_paths=[path])
        if not valid:
            write_hat_request(
                intent=f"Remove protected file: {path}",
                protected_paths=[path],
                root_category="ROOT_REPO",
            )
            return rb.invalid(
                'MCP-SYS-I-001',
                data={"requires_hat": True},
                message=f"HAT approval required: {msg}. Click the shield icon in CK3 Lens sidebar to approve.",
            )

        entries = load_manifest()
        before_count = len(entries)
        entries = [e for e in entries if e.path.replace("\\", "/") != normalized]
        after_count = len(entries)

        if before_count == after_count:
            return rb.invalid('MCP-SYS-I-001', data={}, message=f"Path not found in manifest: {path}")

        save_manifest(entries)

        return rb.success(
            'EN-WRITE-S-001',
            data={
                "removed": path,
                "total_entries": len(entries),
            },
            message=f"Removed protection: {path}",
        )

    else:
        return rb.invalid('MCP-SYS-I-002', data={}, message=f"Unknown command: {command}")


# ============================================================================
# Unified Search Tool
# ============================================================================

@mcp.tool()
@mcp_safe_tool
def ck3_search(
    query: str,
    file_pattern: Optional[str] = None,
    game_folder: Optional[str] = None,
    symbol_type: Optional[str] = None,
    adjacency: Literal["auto", "strict", "fuzzy"] = "auto",
    limit: int = 25,
    definitions_only: bool = False,
    verbose: bool = False,
) -> Reply:
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
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_search')
    
    db = _get_db()
    session = _get_session()
    world = _get_world()
    
    # Build file_pattern from game_folder if provided
    effective_file_pattern = file_pattern
    if game_folder:
        if world is None:
            return rb.denied("EN-MODE-D-001", {
                "detail": "Agent mode not initialized",
                "action": "Click 'Initialize Agent' in the CK3 Lens sidebar.",
            })
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
    
    # Add hints for empty results - help agent exhaust search options
    total_results = result['symbols']['count'] + total_refs + content_count + result['files']['count']
    if total_results == 0:
        from ck3lens.hints import get_hint_engine
        hint_engine = get_hint_engine()
        hints = hint_engine.for_empty_search(query, search_type="unified")
        result.update(hints)
    
    return rb.success(
        'WA-READ-S-001',
        data=result,
        message=f"Search completed: {result['symbols']['count']} symbols, {total_refs} refs, {content_count} content matches.",
    )


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
@mcp_safe_tool
def ck3_grep_raw(
    path: str,
    query: str,
    is_regex: bool = False,
    include_pattern: Optional[str] = None
) -> Reply:
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
    
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_grep_raw')
    
    trace = _get_trace()
    search_path = Path(path)
    
    # WorldAdapter visibility - THE canonical way
    world = _get_world()
    if world is None:
        return rb.denied("EN-MODE-D-001", {
            "detail": "Agent mode not initialized",
            "action": "Click 'Initialize Agent' in the CK3 Lens sidebar.",
        })
    resolution = world.resolve(str(search_path))
    if not resolution.found:
        return rb.invalid(
            'WA-RES-I-001',
            data={"path": path, "mode": world.mode},
            message=f"Path not found: {path}",
        )
    # Use resolved absolute path (always set when resolution.found is True)
    if resolution.absolute_path is None:
        return rb.invalid('WA-RES-I-001', data={"path": path}, message=f"Resolution returned no path for: {path}")
    search_path = resolution.absolute_path
    
    # Log the attempt
    trace.log("mcp.tool", {
        "path": str(search_path),
        "query": query,
        "is_regex": is_regex,
        "include_pattern": include_pattern,
    }, {})
    
    if not search_path.exists():
        return rb.invalid('WA-RES-I-001', data={"path": path}, message=f"Path not found: {path}")
    
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
        
        result_data = {
            "success": True,
            "matches": matches,
            "count": len(matches),
            "truncated": len(matches) >= 50,
        }
        
        trace.log("mcp.tool", {
            "path": str(search_path),
            "query": query,
        }, {"match_count": len(matches)})
        
        return rb.success('WA-READ-S-001', data=result_data, message=f"Found {len(matches)} matches.")
        
    except Exception as e:
        return rb.error('MCP-SYS-E-001', data={"error": str(e)}, message=str(e))


@mcp.tool()
@mcp_safe_tool
def ck3_file_search(
    pattern: str,
    base_path: Optional[str] = None
) -> Reply:
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
    
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_file_search')
    
    trace = _get_trace()
    session = _get_session()
    world = _get_world()
    if world is None:
        return rb.denied("EN-MODE-D-001", {
            "detail": "Agent mode not initialized",
            "action": "Click 'Initialize Agent' in the CK3 Lens sidebar.",
        })
    
    # Get agent mode first for path defaults
    mode = get_agent_mode()
    
    # Default path depends on mode
    if base_path:
        search_base = Path(base_path)
    elif mode == "ck3raven-dev":
        # In ck3raven-dev mode, default to repo root for infrastructure work
        search_base = Path(__file__).parent.parent.parent
    elif session.vanilla and session.vanilla.path:
        search_base = session.vanilla.path
    else:
        search_base = Path("C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game")
    
    # WorldAdapter visibility - THE canonical way
    resolution = world.resolve(str(search_base))
    if not resolution.found:
        return rb.invalid(
            'WA-RES-I-001',
            data={"path": str(base_path or search_base), "mode": world.mode},
            message=f"Path not found: {base_path or search_base}",
        )
    # Always set when resolution.found is True
    if resolution.absolute_path is None:
        return rb.invalid('WA-RES-I-001', data={"path": base_path}, message=f"Resolution returned no path for: {base_path}")
    search_base = resolution.absolute_path
    
    # Log the attempt
    trace.log("mcp.tool", {
        "pattern": pattern,
        "base_path": str(search_base),
    }, {})
    
    if not search_base.exists():
        return rb.invalid('WA-RES-I-001', data={"base_path": str(search_base)}, message=f"Base path not found: {search_base}")
    
    try:
        files = []
        for p in search_base.glob(pattern):
            if p.is_file():
                files.append(str(p))
                if len(files) >= 500:  # Limit results
                    break
        
        result_data = {
            "success": True,
            "files": files,
            "count": len(files),
            "truncated": len(files) >= 500,
            "base_path": str(search_base),
        }
        
        trace.log("mcp.tool", {
            "pattern": pattern,
        }, {"count": len(files)})
        
        return rb.success('WA-READ-S-001', data=result_data, message=f"Found {len(files)} files.")
        
    except Exception as e:
        return rb.error('MCP-SYS-E-001', data={"error": str(e)}, message=str(e))


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
@mcp_safe_tool
def ck3_parse_content(
    content: str,
    filename: str = "inline.txt",
) -> Reply:
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
        Reply with code WA-PARSE-S-001 on success (ast and node_count in data),
        or WA-PARSE-I-001 on syntax errors (errors list in data).
        Returns MCP-SYS-E-001 only on unexpected system failure.
    """
    trace = _get_trace()
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool="ck3_parse_content")
    
    # Wrap in try/except to distinguish user syntax errors from system failures
    try:
        result = parse_content(content, filename, recover=True)
    except Exception as e:
        # System failure - unexpected exception in parser
        import traceback
        return rb.error(
            "MCP-SYS-E-001",
            data={
                "error": f"Parser system failure: {e}",
                "error_type": type(e).__name__,
                "filename": filename,
                "traceback": traceback.format_exc(),
            },
            message=f"Parser system failure: {e}",
        )
    
    trace.log("mcp.tool", {
        "filename": filename,
        "content_length": len(content)
    }, {"success": result["success"], "error_count": len(result["errors"])})
    
    if result["success"]:
        # Count nodes in AST for the message
        node_count = 0
        if result["ast"]:
            # Simple node counting: count all dict items in AST
            def count_nodes(obj):
                if isinstance(obj, dict):
                    return 1 + sum(count_nodes(v) for v in obj.values())
                elif isinstance(obj, list):
                    return sum(count_nodes(item) for item in obj)
                return 0
            node_count = count_nodes(result["ast"])
        
        return rb.success(
            "WA-PARSE-S-001",
            data={
                "ast": result["ast"],
                "errors": result["errors"],  # Empty list on success
                "node_count": node_count,
                "filename": filename,
            },
        )
    else:
        # Parse failed due to user syntax errors - this is INVALID input, not system error
        first_error = result["errors"][0] if result["errors"] else {"line": 1, "message": "Unknown parse error"}
        
        return rb.invalid(
            "WA-PARSE-I-001",
            data={
                "ast": result["ast"],  # Partial AST may still be useful
                "errors": result["errors"],
                "line": first_error.get("line", 1),
                "error": first_error.get("message", "Unknown parse error"),
                "filename": filename,
            },
            message=f"Syntax error at line {first_error.get('line', 1)}: {first_error.get('message', 'Unknown parse error')}",
        )


@mcp.tool()
@mcp_safe_tool
def ck3_report_validation_issue(
    issue_type: Literal["parser_false_positive", "reference_false_positive", "parser_missed_error", "other"],
    code_snippet: str,
    expected_behavior: str,
    actual_behavior: str,
    notes: str | None = None,
) -> Reply:
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
    
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_report_validation_issue')
    
    trace = _get_trace()
    
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

    # Write to issues file in ck3raven project folder - requires ROOT_REPO from paths.py
    if ROOT_REPO is None:
        return rb.error(
            "GEN-E-001",
            data={},
            message="ROOT_REPO not configured - cannot write validation issues. Run in ck3raven-dev mode.",
        )
    issues_file = ROOT_REPO / "ck3lens_validation_issues.jsonl"
    with issues_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(issue, ensure_ascii=False) + "\n")

    trace.log("mcp.tool", {
        "issue_type": issue_type,
        "snippet_length": len(code_snippet)
    }, {"issue_id": issue_id})
    
    # This is an MCP-owned system operation - writes to ck3raven repo, not governed by EN
    return rb.success(
        'MCP-SYS-S-001',
        data={
            "issue_id": issue_id,
            "issues_file": str(issues_file),

        },
        message=f"Validation issue recorded. ID: {issue_id}. Will be reviewed in ck3raven-dev mode.",
    )


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
@mcp_safe_tool
def ck3_get_agent_briefing() -> Reply:
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
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_get_agent_briefing')
    
    session = _get_session()
    
    if not session.playset_name:
        return rb.invalid(
            'WA-VIS-I-001',
            data={"error": "No active playset", "hint": "Switch to a playset with ck3_playset(command='switch') first"},
            message="No active playset",
        )
    
    # TODO: Agent briefing should be added to Session class
    # For now, read directly from playset file if needed
    briefing = {}
    sub_agent = {}
    
    # Try to load briefing from playset file directly
    if PLAYSET_MANIFEST_FILE.exists():
        try:
            manifest = json.loads(PLAYSET_MANIFEST_FILE.read_text(encoding='utf-8-sig'))
            active_file = manifest.get("active", "")
            if active_file:
                playset_path = PLAYSETS_DIR / active_file
                if playset_path.exists():
                    playset_data = json.loads(playset_path.read_text(encoding='utf-8-sig'))
                    briefing = playset_data.get("agent_briefing", {})
                    sub_agent = playset_data.get("sub_agent_config", {})
        except Exception:
            pass
    
    result = {
        "playset_name": session.playset_name,
        "context": briefing.get("context", ""),
        "error_analysis_notes": briefing.get("error_analysis_notes", []),
        "conflict_resolution_notes": briefing.get("conflict_resolution_notes", []),
        "mod_relationships": briefing.get("mod_relationships", []),
        "priorities": briefing.get("priorities", []),
        "custom_instructions": briefing.get("custom_instructions", ""),
        "sub_agent_config": sub_agent,
    }
    
    return rb.success(
        'MCP-SYS-S-001',
        data=result,
        message=f"Agent briefing loaded for playset: {session.playset_name}",
    )


@mcp.tool()
@mcp_safe_tool
def ck3_search_mods(
    query: str,
    search_by: Literal["name", "workshop_id", "any"] = "any",
    fuzzy: bool = True,
    limit: int = 20
) -> Reply:
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
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_search_mods')
    
    db = _get_db()
    
    results = []
    
    if search_by in ("workshop_id", "any") and query.isdigit():
        # Exact workshop ID match
        rows = db.conn.execute("""
            SELECT cv.content_version_id, cv.name, cv.workshop_id, cv.source_path,
                   cv.file_count
            FROM content_versions cv
            WHERE cv.workshop_id = ?
            ORDER BY cv.ingested_at DESC
        """, (query,)).fetchall()
        for r in rows:
            results.append({
                "content_version_id": r[0], "name": r[1], "workshop_id": r[2],
                "source_path": r[3], "file_count": r[4],
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
        
        seen_ids = {r["content_version_id"] for r in results}
        
        for pattern, match_type in patterns:
            rows = db.conn.execute("""
                SELECT cv.content_version_id, cv.name, cv.workshop_id, cv.source_path,
                       cv.file_count
                FROM content_versions cv
                WHERE LOWER(cv.name) LIKE LOWER(?)
                ORDER BY cv.ingested_at DESC
                LIMIT ?
            """, (pattern, limit)).fetchall()
            
            for r in rows:
                if r[0] not in seen_ids:
                    seen_ids.add(r[0])
                    results.append({
                        "content_version_id": r[0], "name": r[1], "workshop_id": r[2],
                        "source_path": r[3], "file_count": r[4],
                        "match_type": match_type
                    })
    
    return rb.success(
        'WA-READ-S-001',
        data={"results": results[:limit], "query": query},
        message=f"Found {len(results[:limit])} mods matching '{query}'.",
    )

# ============================================================================
# Mode & Configuration Tools
# ============================================================================

@mcp.tool()
@mcp_safe_tool
def ck3_get_mode_instructions(
    mode: Literal["ck3lens", "ck3raven-dev"],
    mit_token: str | None = None,
    hat_token: str | None = None,
) -> Reply:
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
        mit_token: Deprecated — use hat_token instead.
        hat_token: Signed authorization token from extension (required).
    
    Returns:
        Mode instructions, policy boundaries, session context, and database status
    """
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_get_mode_instructions')
    
    # Accept hat_token, fall back to mit_token for backward compat
    token = hat_token or mit_token
    reply = _ck3_get_mode_instructions_internal(mode, token, rb=rb)
    # Forward Reply (already built with our rb)
    if reply.reply_type == "I":
        return rb.invalid(reply.code, data=reply.data, message=reply.message)
    if reply.reply_type != "S":
        return rb.error(reply.code, data=reply.data, message=reply.message)
    return rb.success(reply.code, data=reply.data, message=reply.message)


def _ck3_get_mode_instructions_internal(mode: str, hat_token: str | None = None, *, rb: ReplyBuilder) -> Reply:
    """Internal implementation returning Reply."""
    from pathlib import Path
    from ck3lens.policy import AgentMode, initialize_workspace
    from ck3lens.agent_mode import set_agent_mode, VALID_MODES
    from tools.compliance.sigil import sigil_verify, sigil_available
    
    # Validate mode before proceeding
    if mode not in VALID_MODES:
        return rb.invalid("MCP-SYS-I-001", data={
            "error": f"Invalid mode: {mode}",
            "valid_modes": list(VALID_MODES),
        })
    
    # =========================================================================
    # HUMAN-IN-THE-LOOP GATE: Inline HAT token from the prompt.
    # The extension signs "mode|timestamp|nonce" with Sigil when the user
    # clicks "Initialize Agent". Token format: "payload::signature".
    # Agents cannot forge this because they can't access CK3LENS_SIGIL_SECRET.
    # Fallback: CK3LENS_DEV_TOKEN for standalone testing without extension.
    # =========================================================================
    if hat_token and sigil_available():
        parts = hat_token.split("::", 1)
        if len(parts) != 2:
            return rb.invalid("MCP-SYS-I-001", data={
                "error": "Malformed HAT token",
                "requires_hat": True,
                "action": "Click 'Initialize Agent' in the CK3 Lens sidebar.",
            })
        payload, signature = parts
        # Verify signature
        if not sigil_verify(payload, signature):
            return rb.invalid("MCP-SYS-I-001", data={
                "error": "HAT token signature invalid — not signed by extension",
                "requires_hat": True,
                "action": "Click 'Initialize Agent' in the CK3 Lens sidebar.",
            })
        # Verify payload contains the requested mode
        token_fields = payload.split("|")
        if len(token_fields) != 3 or token_fields[0] != mode:
            return rb.invalid("MCP-SYS-I-001", data={
                "error": f"HAT token mode mismatch (token has '{token_fields[0] if token_fields else '?'}', requested '{mode}')",
                "requires_hat": True,
                "action": "Click 'Initialize Agent' again with the correct mode.",
            })
        # Verify timestamp (5-minute window)
        try:
            from datetime import datetime, timezone
            token_time = datetime.fromisoformat(token_fields[1])
            age = (datetime.now(timezone.utc) - token_time).total_seconds()
            if age > 300:
                return rb.invalid("MCP-SYS-I-001", data={
                    "error": f"HAT token expired ({age:.0f}s old, max 300s)",
                    "requires_hat": True,
                    "action": "Click 'Initialize Agent' again.",
                })
        except (ValueError, IndexError):
            return rb.invalid("MCP-SYS-I-001", data={
                "error": "HAT token has invalid timestamp",
                "requires_hat": True,
                "action": "Click 'Initialize Agent' again.",
            })
    elif not hat_token:
        # No token provided — check for dev fallback
        dev_token = os.environ.get("CK3LENS_DEV_TOKEN", "")
        if not dev_token:
            return rb.invalid("MCP-SYS-I-001", data={
                "error": "No HAT token provided. Mode initialization requires human authorization.",
                "requires_hat": True,
                "action": "Click 'Initialize Agent' in the CK3 Lens sidebar, then send the prompt.",
            })

    
    # =========================================================================
    # STEP 1: Initialize database connection (what ck3_init_session used to do)
    # =========================================================================
    session_info = _init_session_internal()
    
    # =========================================================================
    # STEP 2: Set mode (persisted to file as single source of truth)
    # =========================================================================


    set_agent_mode(mode)  # type: ignore[arg-type]
    
    # Reset cached world adapter - mode change invalidates the cache
    _reset_world_cache()
    
    # =========================================================================
    # STEP 3: Load mode-specific instructions (use ROOT_REPO from paths.py)
    # =========================================================================
    mode_files = {
        "ck3lens": "COPILOT_LENS_COMPATCH.md",
        "ck3raven-dev": "COPILOT_RAVEN_DEV.md",
    }
    
    if ROOT_REPO is None:
        return rb.error("MCP-SYS-E-001", data={
            "error": "ROOT_REPO not configured - mode instructions unavailable",
            "session": session_info,
        })
    
    instructions_path = ROOT_REPO / ".github" / mode_files[mode]
    
    if not instructions_path.exists():
        return rb.error("MCP-SYS-E-001", data={
            "error": f"Instructions file not found: {mode_files[mode]}",
            "expected_path": str(instructions_path),
            "session": session_info,
        })
    
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
                wipe=False  # DO NOT auto-wipe - preserve WIP contents across sessions
            )
        except Exception as e:
            wip_info = {"error": f"WIP init failed: {e}"}
        
        # Policy context: refer agent to canonical docs
        # (capability_matrix.py is the truth table, mode instructions have summaries)
        policy_context = {
            "mode": mode,
            "reference": "See docs/CANONICAL_ARCHITECTURE.md and tools/ck3lens_mcp/ck3lens/capability_matrix.py",
            "note": "Enforcement decides allow/deny at execution time based on the capability matrix.",
        }
        
        # =====================================================================
        # STEP 5: Log initialization to trace
        # =====================================================================
        trace = _get_trace()
        trace.log("session.mode", {"mode": mode}, {
            "mode": mode,
            "source_file": str(instructions_path),
            "wip_workspace": str(ROOT_CK3RAVEN_DATA / "wip"),
            "playset_id": session_info.get("playset_id"),
            "playset_name": session_info.get("playset_name"),
        })
        
        # =====================================================================
        # Build complete response
        # =====================================================================

        return rb.success("MCP-SYS-S-001", data={
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
            **({"db_warning": session_info["warning"]} if session_info.get("warning") else {}),
        })
        
    except Exception as e:
        return rb.error("MCP-SYS-E-001", data={
            "error": str(e),
            "session": session_info,
        })


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
@mcp_safe_tool
def ck3_get_detected_mode() -> Reply:
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
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_get_detected_mode')
    
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
        if tool == "session.mode":
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
    
    return rb.success(
        'MCP-SYS-S-001',
        data={
            "detected_mode": detected_mode,
            "confidence": confidence,
            "last_activity": last_activity,
            "evidence": evidence[:5]  # Limit evidence entries
        },
        message=f"Detected mode: {detected_mode or 'none'} (confidence: {confidence}).",
    )


@mcp.tool()
@mcp_safe_tool
def ck3_get_workspace_config() -> Reply:
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

    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_get_workspace_config')
    
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
    
    return rb.success(
        'MCP-SYS-S-001',
        data=result,
        message="Workspace configuration loaded.",
    )


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
        "columns": ["symbol_id", "ast_id", "line_number", "column_number", "name", "symbol_type", "scope"],
        "filters": {
            "name": "str - LIKE pattern for symbol name",
            "symbol_type": "str - Type (trait, event, decision, etc.)",
        },
        "examples": [
            'table=symbols, filters={"name": "brave", "symbol_type": "trait"}',
            'table=symbols, filters={"symbol_type": "event"}',
        ],
    },
    "files": {
        "table": "files",
        "columns": ["file_id", "content_version_id", "relpath", "content_hash", "file_type", "deleted", "file_size"],
        "filters": {
            "relpath": "str - LIKE pattern for path",
            "content_version_id": "int - Content version ID",
            "file_type": "str - File type",
            "deleted": "bool - Deleted flag (default: false)",
        },
        "examples": [
            'table=files, filters={"relpath": "%traits%"}',
            'table=files, filters={"file_type": "txt"}',
        ],
    },
    "refs": {
        "table": "refs",
        "columns": ["ref_id", "ast_id", "line_number", "column_number", "name", "ref_type", "resolution_status", "resolved_symbol_id"],
        "filters": {
            "name": "str - LIKE pattern for reference name",
            "ref_type": "str - Reference type",
            "resolution_status": "str - Resolution status (resolved, unresolved)",
        },
        "examples": [
            'table=refs, filters={"name": "brave"}',
            'table=refs, filters={"resolution_status": "unresolved"}',
        ],
    },
}


@mcp.tool()
@mcp_safe_tool
def ck3_db_query(
    table: str | None = None,
    filters: dict | None = None,
    columns: list[str] | None = None,
    sql: str | None = None,
    sql_file: str | None = None,
    limit: int = 100,
    help: bool = False,
    unfiltered: bool = False,
) -> Reply:
    """
    Unified database query tool for CK3 raven database.
    
    Use help=True to see available tables and their schemas.
    
    VISIBILITY FILTERING:
        In ck3lens mode, queries are automatically filtered to the active playset.
        Tables with content_version_id column only return rows from vanilla + active mods.
        Set unfiltered=True to bypass filtering (advanced use only).
    
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
        unfiltered: If True, bypass playset visibility filtering (ck3lens mode only)
        
    Examples:
        ck3_db_query(help=True)
        ck3_db_query(table="provinces", filters={"culture": "french"}, limit=10)
        ck3_db_query(table="titles", filters={"tier": "k"})
        ck3_db_query(table="symbols", filters={"name": "%brave%", "symbol_type": "trait"})
        ck3_db_query(sql="SELECT COUNT(*) as cnt FROM symbols GROUP BY symbol_type")
    """
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_db_query')
    
    # Help mode
    if help:
        return rb.success(
            'WA-DB-S-001',
            data={
                "usage": "ck3_db_query(table=..., filters={...}, limit=N) or ck3_db_query(sql=...)",
                "tables": {
                    name: {
                        "columns": schema["columns"],
                        "filters": schema["filters"],
                        "examples": schema["examples"],
                    }
                    for name, schema in _DB_QUERY_SCHEMA.items()
                },
                "stats": _get_table_stats(rb=rb).data,
            },
            message="Database schema and statistics.",
        )
    
    db = _get_db()
    
    # Raw SQL mode
    if sql or sql_file:
        # In ck3lens mode, raw SQL requires explicit opt-out of visibility filtering
        from ck3lens.agent_mode import get_agent_mode
        if get_agent_mode() == "ck3lens" and not unfiltered:
            return rb.invalid(
                'WA-DB-I-001',
                data={
                    "error": "Raw SQL not allowed without unfiltered=True in ck3lens mode",
                    "reason": "Raw SQL bypasses playset visibility filtering. Use structured table queries (which are auto-filtered) or set unfiltered=True to explicitly bypass filtering.",
                    "example": "ck3_db_query(table='files', filters={'relpath': '%traits%'}) — auto-filtered to playset",
                },
                message="Raw SQL requires unfiltered=True in ck3lens mode. Use table= for auto-filtered queries.",
            )
        
        try:
            if sql_file:
                with open(sql_file, 'r', encoding='utf-8') as f:
                    sql = f.read()
            
            # At this point sql must be a string
            if sql is None:
                return rb.invalid('WA-DB-I-001', data={"error": "No SQL provided"}, message="No SQL provided")
            
            # Safety: only allow SELECT
            sql_upper = sql.strip().upper()
            if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
                return rb.denied('EN-DB-D-001', data={"mode": "query"}, message="Only SELECT queries allowed for safety")
            
            # Add LIMIT if not present
            if "LIMIT" not in sql_upper:
                sql = f"{sql.rstrip().rstrip(';')} LIMIT {limit}"
            
            rows = db.conn.execute(sql).fetchall()
            # Get column names from cursor description
            cursor = db.conn.execute(sql)
            col_names = [d[0] for d in cursor.description] if cursor.description else []
            
            results = [dict(zip(col_names, row)) for row in rows]
            
            # Note: If we reach here, either:
            # - Mode is ck3raven-dev (no visibility filter needed)
            # - unfiltered=True was explicitly set (user opted out)
            
            return rb.success(
                'WA-DB-S-001',
                data={"count": len(results), "results": results, "unfiltered": True},
                message=f"Query returned {len(results)} rows (unfiltered).",
            )
        except sqlite3.OperationalError as e:
            # Predictable SQL errors (user mistakes): no such table, syntax error, unknown column
            error_msg = str(e).lower()
            if any(pattern in error_msg for pattern in [
                "no such table", "no such column", "syntax error", 
                "near", "unrecognized token", "incomplete input"
            ]):
                return rb.invalid(
                    'WA-DB-I-003',
                    data={"error": str(e), "sql": sql[:200] if sql else None},
                    message=f"Invalid SQL query: {e}",
                )
            # Other OperationalError = actual system failure
            return rb.error('WA-DB-E-001', data={"error": str(e)}, message=str(e))
        except Exception as e:
            # Unexpected exceptions = system failure
            return rb.error('MCP-SYS-E-001', data={"error": str(e)}, message=str(e))
    
    # Table query mode
    if not table:
        return rb.invalid('WA-DB-I-001', data={"error": "Provide table= or sql=, or use help=True"}, message="No table or SQL provided")
    
    if table not in _DB_QUERY_SCHEMA:
        return rb.invalid('WA-DB-I-002', data={"table": table, "available": list(_DB_QUERY_SCHEMA.keys())}, message=f"Unknown table '{table}'. Use help=True to see options.")
    
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
    
    # AUTO-FILTER: Add content_version_id filter for tables that have it
    # This ensures queries in ck3lens mode only see playset data
    from ck3lens.agent_mode import get_agent_mode
    visibility_applied = False
    if get_agent_mode() == "ck3lens" and not unfiltered:
        # Tables with content_version_id that need filtering
        tables_with_cvid = {"files"}  # files table has content_version_id
        if table in tables_with_cvid:
            active_cvids = _get_active_cvids()
            if active_cvids:
                cvid_list = ",".join(str(c) for c in active_cvids)
                where_clause = f"({where_clause}) AND content_version_id IN ({cvid_list})"
                visibility_applied = True
    
    params.append(limit)
    
    try:
        query = f"SELECT {select_clause} FROM {db_table} WHERE {where_clause} LIMIT ?"
        rows = db.conn.execute(query, params).fetchall()
        
        results = [dict(zip(select_cols, row)) for row in rows]
        data = {"count": len(results), "table": table, "results": results}
        if visibility_applied:
            data["visibility_filter"] = "active_playset"
        return rb.success(
            'WA-DB-S-001',
            data=data,
            message=f"Query returned {len(results)} rows from {table}.",
        )
    except Exception as e:
        return rb.error('MCP-SYS-E-001', data={"error": str(e), "query": query if 'query' in dir() else None}, message=str(e))


def _get_table_stats(*, rb: ReplyBuilder) -> Reply:
    """Get row counts for all queryable tables."""
    db = _get_db()
    stats = {}
    for name, schema in _DB_QUERY_SCHEMA.items():
        try:
            count = db.conn.execute(f"SELECT COUNT(*) FROM {schema['table']}").fetchone()[0]
            stats[name] = count
        except:
            stats[name] = "error"
    return rb.success("MCP-SYS-S-001", data=stats)


# ============================================================================
# Journal - REMOVED (February 2026)
# ============================================================================


# ============================================================================
# Paths Doctor - Diagnostic Tool
# ============================================================================

@mcp.tool()
@mcp_safe_tool
def ck3_paths_doctor(
    include_resolution_checks: bool = True,
    verbose: bool = False,
) -> Reply:
    """
    Run Paths Doctor to diagnose path configuration issues.
    
    A read-only diagnostic utility that validates:
    - Required paths (ROOT_GAME, ROOT_STEAM)
    - Optional paths (ROOT_USER_DOCS, ROOT_UTILITIES, etc.)
    - Computed paths (ROOT_REPO, ROOT_CK3RAVEN_DATA)
    - Data structure (wip/, playsets/, logs/, config/ under ROOT_CK3RAVEN_DATA)
    - Local mods folder configuration
    - Config file health
    - Resolution cross-checks (optional)
    
    Args:
        include_resolution_checks: Run WorldAdapter resolution cross-checks (default True)
        verbose: Include OK findings in output (default False)
    
    Returns:
        PathsDoctorReport with findings categorized by severity (ERROR, WARN, OK)
        
    Note:
        This tool ALWAYS returns Reply(S) even if findings include ERRORs.
        The report's 'ok' field indicates whether configuration is healthy.
        Use this to diagnose path issues before reporting bugs.
    """
    from ck3lens.paths_doctor import run_paths_doctor, PathsDoctorReport
    from dataclasses import asdict
    
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_paths_doctor')
    
    try:
        report = run_paths_doctor(include_resolution_checks=include_resolution_checks)
        
        # Convert to serializable dict
        report_dict = {
            "ok": report.ok,
            "findings": [asdict(f) for f in report.findings],
            "summary": report.summary,
            "config_path": report.config_path,
        }
        
        # Filter to non-OK findings unless verbose
        if not verbose:
            report_dict["findings"] = [
                f for f in report_dict["findings"]
                if f["severity"] != "OK"
            ]
            report_dict["verbose"] = False
        else:
            report_dict["verbose"] = True
        
        # Always Reply(S) - the report.ok field indicates health
        status = "HEALTHY" if report.ok else "UNHEALTHY"
        return rb.success(
            'MCP-SYS-S-001',
            data=report_dict,
            message=f"Paths Doctor: {status} ({report.summary['ERROR']} errors, {report.summary['WARN']} warnings, {report.summary['OK']} ok)",
        )
    except Exception as e:
        return rb.error(
            'MCP-SYS-E-001',
            data={"error": str(e)},
            message=f"Paths Doctor failed: {e}",
        )


# ============================================================================
# QBuilder - Build System Tools
# ============================================================================

@mcp.tool()
@mcp_safe_tool
def ck3_qbuilder(
    command: Literal["status", "build", "discover", "reset", "stop"] = "status",
    max_tasks: Optional[int] = None,
    fresh: bool = False,
) -> Reply:
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
    command=stop     -> Stop running daemon gracefully (via IPC)

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
    import time
    
    from ck3lens.daemon_client import daemon, DaemonNotAvailableError
    
    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool='ck3_qbuilder')
    
    # Use ROOT_REPO from paths.py instead of computing from __file__
    repo_root = str(ROOT_REPO)
    python_exe = sys.executable
    
    if command == "status":
        # Query daemon status via IPC
        try:
            if daemon.is_available():
                status = daemon.get_queue_status()
                status["daemon_available"] = True
                queue = status.get("queue", {})
                activity = status.get("recent_activity", {})
                activity_state = activity.get("state", "unknown") if activity else "unknown"
                return rb.success(
                    'MCP-SYS-S-001',
                    data=status,
                    message=f"Daemon running ({activity_state}). Pending: {queue.get('pending', 0)}, Leased: {queue.get('leased', 0)}.",
                )
            else:
                return rb.invalid(
                    'MCP-SYS-I-001',
                    data={
                        "daemon_available": False,
                        "message": "Daemon not running. Use ck3_qbuilder(command='build') to start.",
                        "hint": "The daemon is the single writer - it must be running for builds.",
                    },
                    message="Daemon not running.",
                )
        except Exception as e:

            return rb.error('MCP-SYS-E-001', data={"error": str(e), "daemon_available": False}, message=str(e))
    
    elif command == "build":
        # Launch background daemon
        # The daemon is the ONLY process that writes to the database
        log_dir = Path.home() / ".ck3raven" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        from datetime import datetime
        log_file = log_dir / f"daemon_{datetime.now().strftime('%Y-%m-%d')}.log"
        
        # Check if daemon already running via IPC
        if daemon.is_available():
            health = daemon.health()
            return rb.success(
                'MCP-SYS-S-001',
                data={
                    "success": True,
                    "already_running": True,
                    "daemon_pid": health.daemon_pid,
                    "state": health.state,
                    "queue_pending": health.queue_pending,
                },
                message="Daemon already running.",
            )
        
        # RACE CONDITION FIX: Check writer lock before spawning
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
                        return rb.success(
                            'MCP-SYS-S-001',
                            data={
                                "success": True,
                                "already_running": True,
                                "daemon_pid": health.daemon_pid,
                                "state": health.state,
                                "queue_pending": health.queue_pending,
                            },
                            message="Daemon already running (connected after lock wait).",
                        )
                
                # Lock holder exists but IPC not responding
                return rb.error(
                    'MCP-SYS-E-001',
                    data={
                        "success": False,
                        "error": f"Daemon lock held by PID {lock_status.get('holder_pid')} but IPC not responding",
                        "hint": "Kill the stale daemon process or wait for it to finish",
                    },
                    message="Daemon lock held but IPC not responding.",
                )
        except ImportError:
            pass  # Fall back to basic spawn
        
        try:
            with open(log_file, "a", encoding="utf-8") as log_handle:
                log_handle.write(f"\n\n=== Daemon started at {datetime.now().isoformat()} ===\n")
                log_handle.flush()
                
                # Start daemon with IPC server
                proc = subprocess.Popen(
                    [python_exe, "-m", "qbuilder.cli", "daemon"],
                    cwd=repo_root,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            
            # Wait briefly for daemon to start IPC server
            time.sleep(1.0)
            
            return rb.success(
                'MCP-SYS-S-001',
                data={

                    "success": True,
                    "pid": proc.pid,
                    "log_file": str(log_file),
                    "note": "Daemon is the single DB writer. Use 'discover' to enqueue work.",
                },
                message=f"Daemon started (PID {proc.pid}).",
            )
        except Exception as e:
            return rb.error('MCP-SYS-E-001', data={"success": False, "error": str(e)}, message=str(e))
    
    elif command == "discover":
        # Request daemon to enqueue discovery tasks via IPC
        try:
            if not daemon.is_available():
                return rb.error(
                    'MCP-SYS-E-001',
                    data={
                        "success": False,
                        "error": "Daemon not running",
                        "hint": "Start daemon first with ck3_qbuilder(command='build')",
                    },
                    message="Daemon not running.",
                )
            
            result = daemon.enqueue_scan()
            result["note"] = "Discovery tasks enqueued. Daemon will process them."
            return rb.success('MCP-SYS-S-001', data=result, message="Discovery tasks enqueued.")
            
        except DaemonNotAvailableError as e:
            return rb.error(
                'MCP-SYS-E-001',
                data={
                    "success": False,
                    "error": str(e),
                    "hint": "Start daemon first with ck3_qbuilder(command='build')",
                },
                message=str(e),
            )
        except Exception as e:
            return rb.error('MCP-SYS-E-001', data={"success": False, "error": str(e)}, message=str(e))
    
    elif command == "reset":
        # Reset is a write operation - must go through daemon
        return rb.denied(
            'EN-DB-D-001',
            data={
                "mode": "reset",
                "error": "Reset requires daemon restart with --fresh flag",
                "hint": "Stop daemon, then run: python -m qbuilder.cli daemon --fresh",
                "note": "This is intentionally gated to prevent accidental data loss.",
            },
            message="Reset requires daemon restart with --fresh flag.",
        )
    
    elif command == "stop":
        # Stop daemon gracefully via IPC
        try:
            if not daemon.is_available():
                return rb.success(
                    'MCP-SYS-S-001',
                    data={
                        "success": True,
                        "was_running": False,
                        "note": "Daemon was not running",
                    },
                    message="Daemon was not running.",
                )
            
            result = daemon.shutdown(graceful=True)
            return rb.success(
                'MCP-SYS-S-001',
                data={
                    "success": True,
                    "was_running": True,
                    "acknowledged": result.get("acknowledged", False),
                    "note": "Shutdown signal sent. Daemon will exit after completing current work.",
                },
                message="Daemon shutdown requested.",
            )
            
        except DaemonNotAvailableError:
            return rb.success(
                'MCP-SYS-S-001',
                data={
                    "success": True,
                    "was_running": False,
                    "note": "Daemon was not running",
                },
                message="Daemon was not running.",
            )
        except Exception as e:
            return rb.error('MCP-SYS-E-001', data={"success": False, "error": str(e)}, message=str(e))
    
    else:
        return rb.invalid('WA-SYS-I-001', data={"error": f"Unknown command: {command}", "valid_commands": ["status", "build", "discover", "reset", "stop"]}, message=f"Unknown command: {command}")


# ============================================================================
# World Adapter v2 — Canonical Addressing (Sprint 0)
# ============================================================================

_cached_world_adapter_v2 = None


def _get_world_v2():
    """
    Get or create the WorldAdapterV2 singleton.

    Mode-agnostic: WA v2 reads agent mode dynamically on every resolve() call.
    No mode baked in at construction. No cache invalidation needed for mode changes.
    """
    global _cached_world_adapter_v2

    if _cached_world_adapter_v2 is not None:
        return _cached_world_adapter_v2

    from ck3lens.world_adapter_v2 import WorldAdapterV2

    session = _get_session()
    _cached_world_adapter_v2 = WorldAdapterV2.create(
        session=session,
    )
    return _cached_world_adapter_v2


@mcp.tool()
@mcp_safe_tool
def ck3_dir(
    command: Literal["pwd", "cd", "list", "tree"],
    path: str | None = None,
    depth: int = 3,
) -> Reply:
    """
    Directory navigation using canonical addressing v2.

    This is the Sprint 0 pilot tool for the canonical addressing refactor.
    All paths are expressed as session-absolute addresses — no host paths
    are ever exposed to the agent.

    Commands:
        pwd  — Show current session home root
        cd   — Change session home root (e.g. 'root:repo', 'root:game')
        list — List directory contents (files and folders)
        tree — Show directory tree (folders only, depth-limited)

    Canonical address syntax:
        root:repo/src/server.py          (root-category addressing)
        root:ck3raven_data/wip/          (data folder)
        mod:SomeMod/common/traits        (mod addressing)

    If no path is given, commands operate on the current home root.
    Bare relative paths are resolved against the current home root.

    Args:
        command: One of pwd, cd, list, tree
        path: Canonical address or relative path (optional for pwd)
        depth: Tree depth limit (default 3, only used by tree command)
    """
    from ck3lens.impl.dir_ops import ck3_dir_impl
    from ck3lens.leak_detector import HostPathLeakError

    trace_info = get_current_trace_info()
    rb = ReplyBuilder(trace_info, tool="ck3_dir")

    wa2 = _get_world_v2()

    try:
        data = ck3_dir_impl(command=command, path=path, depth=depth, wa2=wa2, rb=rb)
    except HostPathLeakError as e:
        return rb.error(
            "WA-DIR-E-001",
            data={"error": str(e), "command": command},
            message=f"Internal error: host path leaked in output",
        )
    except ValueError as e:
        return rb.invalid(
            "WA-DIR-I-001",
            data={"error": str(e), "command": command, "path": path},
            message=str(e),
        )

    return rb.success(
        "WA-DIR-S-001",
        data=data,
        message=f"ck3_dir {command} complete",
    )


# ============================================================================
# Main Entry Point
# ============================================================================

import signal
import atexit

# Structured logging (canonical per docs/CANONICAL_LOGS.md)
from ck3lens.logging import info as log_info, error as log_error, bootstrap as log_bootstrap, set_instance_id
from ck3lens.log_rotation import rotate_logs

_pid = os.getpid()


def _log_exit():
    """Log exit for debugging - called via atexit."""
    global _instance_id, _pid
    # Dual output: structured log file + stderr for VS Code capture
    log_info("mcp.dispose", "MCP server exit (atexit)", instance_id=_instance_id, pid=_pid)
    print(f"MCP server exit: instanceId={_instance_id} pid={_pid}", file=sys.stderr)


def _setup_signal_handlers() -> None:
    """Setup signal handlers for clean shutdown."""
    def handle_signal(signum, frame):
        global _instance_id, _pid
        log_info("mcp.dispose", f"Signal {signum} received, shutting down", 
                 instance_id=_instance_id, pid=_pid, signal=signum)
        print(f"MCP server: signal {signum} received, shutting down instanceId={_instance_id} pid={_pid}", file=sys.stderr)
        sys.exit(0)
    
    # Handle common termination signals
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, 'SIGBREAK'):  # Windows
        signal.signal(signal.SIGBREAK, handle_signal)


if __name__ == "__main__":
    # Bootstrap structured logging
    log_bootstrap(_instance_id)
    
    # Set instance ID for structured logging
    set_instance_id(_instance_id)
    
    # Initialize per-window trace file for FR-3 journal capture
    trace_path = initialize_window_trace(_instance_id)
    
    # Rotate logs at startup (daily rotation)
    rotated = rotate_logs()
    
    # Log startup with structured logging
    log_info("mcp.init", "MCP server starting", 
             instance_id=_instance_id, pid=_pid, log_rotated=rotated,
             trace_file=str(trace_path))
    
    # Also log to stderr for VS Code capture
    print(
        f"MCP server start: instanceId={_instance_id} pid={_pid}",
        file=sys.stderr
    )
    
    # Register exit handler for logging
    atexit.register(_log_exit)
    
    # Setup signal handlers
    _setup_signal_handlers()
    
    try:
        # Run the MCP server (this blocks on stdio)
        # FastMCP uses stdin/stdout for MCP protocol.
        # When stdin closes (VS Code disconnect/reload), FastMCP should exit.
        # 
        # ZOMBIE BUG FIX: The key is that FastMCP's run() must exit when stdin
        # returns EOF. If it doesn't (e.g., gets stuck in asyncio loop), the
        # process becomes a zombie. The signal handlers + atexit logging help
        # us diagnose if this happens.
        #
        # All worker threads in this server should be daemon=True to ensure
        # they don't keep the process alive after main exits.
        mcp.run()
    except EOFError:
        # Explicit EOF handling - CRITICAL for zombie prevention
        log_info("mcp.dispose", "EOF on stdin, shutting down", 
                 reason="EOF on stdin", instance_id=_instance_id, pid=_pid)
        print(
            f"MCP server: stdin EOF detected, shutting down "
            f"instanceId={_instance_id} pid={_pid}",
            file=sys.stderr
        )
    except Exception as e:
        log_error("mcp.dispose", f"Error during run: {e}", 
                  error=str(e), instance_id=_instance_id, pid=_pid)
        print(
            f"MCP server: error during run - {e} "
            f"instanceId={_instance_id} pid={_pid}",
            file=sys.stderr
        )
    finally:
        # Ensure we exit
        log_info("mcp.dispose", "Main loop ended, exiting", 
                 instance_id=_instance_id, pid=_pid)
        print(
            f"MCP server: main loop ended, exiting "
            f"instanceId={_instance_id} pid={_pid}",
            file=sys.stderr
        )

