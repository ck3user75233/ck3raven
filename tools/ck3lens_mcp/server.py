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
- Writes only allowed to whitelisted live mods
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Optional, Literal

from mcp.server.fastmcp import FastMCP

# Add ck3raven to path
CK3RAVEN_ROOT = Path(__file__).parent.parent.parent / "src"
if CK3RAVEN_ROOT.exists():
    sys.path.insert(0, str(CK3RAVEN_ROOT))

from ck3lens.workspace import Session, DEFAULT_LIVE_MODS
from ck3lens.db_queries import DBQueries
from ck3lens import live_mods, git_ops
from ck3lens.validate import parse_content, validate_patchdraft
from ck3lens.contracts import PatchDraft
from ck3lens.trace import ToolTrace

mcp = FastMCP("ck3lens")

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


def _get_trace() -> ToolTrace:
    global _trace
    if _trace is None:
        from ck3lens.workspace import DEFAULT_CK3_MOD_DIR
        session = _get_session()
        mod_root = DEFAULT_CK3_MOD_DIR
        if session.live_mods:
            mod_root = session.live_mods[0].path.parent
        _trace = ToolTrace(mod_root / "ck3lens_trace.jsonl")
    return _trace


# ============================================================================
# Session Management
# ============================================================================

@mcp.tool()
def ck3_init_session(
    db_path: Optional[str] = None,
    live_mods: Optional[list[str]] = None
) -> dict:
    """
    Initialize the CK3 Lens session.
    
    Args:
        db_path: Path to ck3raven SQLite database (optional, uses default)
        live_mods: Override list of whitelisted live mod folder names (optional)
    
    Returns:
        Session info including mod_root and live_mods list
    """
    from ck3lens.workspace import load_config, DEFAULT_DB_PATH, DEFAULT_CK3_MOD_DIR, LiveMod
    
    global _session, _db, _trace, _playset_id
    
    # Reset playset
    _playset_id = None
    
    # Use load_config to get default session with live mods
    _session = load_config()
    
    # Override DB path if provided
    if db_path:
        _session.db_path = Path(db_path)
    
    # Override live mods if specific names provided
    if live_mods:
        _session.live_mods = [
            LiveMod(mod_id=name, name=name, path=DEFAULT_CK3_MOD_DIR / name)
            for name in live_mods
            if (DEFAULT_CK3_MOD_DIR / name).exists()
        ]
    
    _db = DBQueries(db_path=_session.db_path)
    
    # Get mod root from first live mod or default
    mod_root = DEFAULT_CK3_MOD_DIR
    if _session.live_mods:
        mod_root = _session.live_mods[0].path.parent
    _trace = ToolTrace(mod_root / "ck3lens_trace.jsonl")
    
    _trace.log("ck3.init_session", {"db_path": db_path, "live_mods": live_mods}, {
        "mod_root": str(mod_root),
        "live_mods_count": len(_session.live_mods)
    })
    
    # Auto-detect playset
    playset_id = _get_playset_id()
    playset_info = _db.conn.execute(
        "SELECT name, is_active FROM playsets WHERE playset_id = ?",
        (playset_id,)
    ).fetchone()
    
    return {
        "mod_root": str(mod_root),
        "live_mods": [m.name for m in _session.live_mods],
        "db_path": str(_db.db_path) if _db.db_path else None,
        "playset_id": playset_id,
        "playset_name": playset_info[0] if playset_info else None
    }


# ============================================================================
# Symbol Search Tools (from ck3raven DB)
# ============================================================================

@mcp.tool()
def ck3_search_symbols(
    query: str,
    symbol_type: Optional[str] = None,
    mod_filter: Optional[list[str]] = None,
    adjacency: Literal["auto", "strict", "fuzzy"] = "auto",
    limit: int = 50
) -> dict:
    """
    Search symbols in the ck3raven database with adjacency pattern expansion.
    
    IMPORTANT: This uses adjacency search which automatically expands queries:
    - "combat_skill" also matches "combat_*_skill", "*_combat_skill", etc.
    - Use adjacency="strict" to disable expansion (exact matches only)
    - Use adjacency="fuzzy" for maximum flexibility
    
    Args:
        query: Search query (symbol name, partial name, or pattern)
        symbol_type: Filter by type (trait, decision, event, etc.)
        mod_filter: Only search in these mods (list of mod_id strings)
        adjacency: Pattern expansion mode ("auto", "strict", "fuzzy")
        limit: Maximum results to return
    
    Returns:
        List of matching symbols with location info
    """
    db = _get_db()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    results = db.search_symbols(
        playset_id=playset_id,
        query=query,
        symbol_type=symbol_type,
        adjacency=adjacency,
        limit=limit
    )
    
    trace.log("ck3.search_symbols", {
        "query": query,
        "symbol_type": symbol_type,
        "adjacency": adjacency,
        "limit": limit
    }, {"results_count": len(results)})
    
    return {"results": results, "query": query, "adjacency_mode": adjacency}


@mcp.tool()
def ck3_confirm_not_exists(
    name: str,
    symbol_type: Optional[str] = None
) -> dict:
    """
    Confirm a symbol does NOT exist before claiming it's missing.
    
    This performs an exhaustive fuzzy search to prevent false negatives.
    ALWAYS call this before writing code that assumes something doesn't exist.
    
    Args:
        name: Symbol name to search for
        symbol_type: Optional type filter (trait, decision, etc.)
    
    Returns:
        - can_claim_not_exists: True if exhaustive search found nothing
        - similar_matches: Any similar symbols found (might be what you meant)
    """
    db = _get_db()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    result = db.confirm_not_exists(playset_id, name, symbol_type)
    
    trace.log("ck3.confirm_not_exists", {
        "name": name,
        "symbol_type": symbol_type
    }, {
        "can_claim": result["can_claim_not_exists"],
        "similar_count": len(result["similar_matches"])
    })
    
    return result


@mcp.tool()
def ck3_get_file(
    file_path: str,
    include_ast: bool = False,
    max_bytes: int = 200000
) -> dict:
    """
    Get file content from the ck3raven database.
    
    Args:
        file_path: Relative path to the file (e.g., "common/traits/00_traits.txt")
        include_ast: If True, also return parsed AST representation
        max_bytes: Maximum content bytes to return
    
    Returns:
        File content (raw and/or AST)
    """
    db = _get_db()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    result = db.get_file(playset_id, relpath=file_path, include_ast=include_ast)
    
    trace.log("ck3.get_file", {
        "file_path": file_path,
        "include_ast": include_ast
    }, {
        "found": result is not None,
        "content_length": len(result.get("content", "")) if result else 0
    })
    
    return result or {"error": f"File not found: {file_path}"}


@mcp.tool()
def ck3_get_conflicts(
    path_pattern: Optional[str] = None,
    symbol_name: Optional[str] = None,
    symbol_type: Optional[str] = None
) -> dict:
    """
    Get load-order conflicts from the SQLResolver.
    
    Args:
        path_pattern: Filter by file path pattern (glob-style)
        symbol_name: Filter by specific symbol name
        symbol_type: Filter by symbol type
    
    Returns:
        List of conflicts with winner/loser mods and resolution type
    """
    db = _get_db()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    conflicts = db.get_conflicts(
        playset_id=playset_id,
        folder=path_pattern,
        symbol_type=symbol_type
    )
    
    trace.log("ck3.get_conflicts", {
        "path_pattern": path_pattern,
        "symbol_name": symbol_name,
        "symbol_type": symbol_type
    }, {"conflicts_count": len(conflicts)})
    
    return {"conflicts": conflicts}


# ============================================================================
# Live Mod Operations (sandboxed writes)
# ============================================================================

@mcp.tool()
def ck3_list_live_mods() -> dict:
    """
    List whitelisted live mods that can be modified.
    
    Returns:
        List of mod names and paths that are available for writing
    """
    session = _get_session()
    trace = _get_trace()
    
    mods = live_mods.list_live_mods(session)
    
    trace.log("ck3.list_live_mods", {}, {"mods_count": len(mods)})
    
    return {"live_mods": mods}


@mcp.tool()
def ck3_read_live_file(
    mod_name: str,
    rel_path: str,
    max_bytes: int = 200000
) -> dict:
    """
    Read a file from a whitelisted live mod.
    
    Args:
        mod_name: Name of the live mod (folder name)
        rel_path: Relative path within the mod
        max_bytes: Maximum bytes to read
    
    Returns:
        File content
    """
    session = _get_session()
    trace = _get_trace()
    
    result = live_mods.read_live_file(session, mod_name, rel_path, max_bytes)
    
    trace.log("ck3.read_live_file", {
        "mod_name": mod_name,
        "rel_path": rel_path
    }, {"success": result.get("success", False)})
    
    return result


@mcp.tool()
def ck3_write_file(
    mod_name: str,
    rel_path: str,
    content: str,
    validate_syntax: bool = True
) -> dict:
    """
    Write a file to a whitelisted live mod.
    
    Args:
        mod_name: Name of the live mod (must be whitelisted)
        rel_path: Relative path within the mod
        content: File content to write
        validate_syntax: If True, validate CK3 script syntax before writing
    
    Returns:
        Success status and validation results
    """
    session = _get_session()
    trace = _get_trace()
    
    # Optional syntax validation
    if validate_syntax and rel_path.endswith(".txt"):
        parse_result = parse_content(content, rel_path)
        if not parse_result["success"]:
            trace.log("ck3.write_file", {
                "mod_name": mod_name,
                "rel_path": rel_path
            }, {"success": False, "reason": "syntax_error"})
            return {
                "success": False,
                "error": "Syntax validation failed",
                "parse_errors": parse_result["errors"]
            }
    
    result = live_mods.write_file(session, mod_name, rel_path, content)
    
    trace.log("ck3.write_file", {
        "mod_name": mod_name,
        "rel_path": rel_path,
        "content_length": len(content)
    }, {"success": result.get("success", False)})
    
    return result


@mcp.tool()
def ck3_edit_file(
    mod_name: str,
    rel_path: str,
    old_content: str,
    new_content: str,
    validate_syntax: bool = True
) -> dict:
    """
    Edit a file in a whitelisted live mod (search-replace style).
    
    Args:
        mod_name: Name of the live mod
        rel_path: Relative path within the mod
        old_content: Exact content to find and replace
        new_content: Content to replace with
        validate_syntax: If True, validate resulting syntax
    
    Returns:
        Success status
    """
    session = _get_session()
    trace = _get_trace()
    
    result = live_mods.edit_file(session, mod_name, rel_path, old_content, new_content)
    
    # Validate resulting file if requested
    if result.get("success") and validate_syntax and rel_path.endswith(".txt"):
        read_result = live_mods.read_live_file(session, mod_name, rel_path)
        if read_result.get("success"):
            parse_result = parse_content(read_result["content"], rel_path)
            result["syntax_valid"] = parse_result["success"]
            if not parse_result["success"]:
                result["syntax_warnings"] = parse_result["errors"]
    
    trace.log("ck3.edit_file", {
        "mod_name": mod_name,
        "rel_path": rel_path
    }, {"success": result.get("success", False)})
    
    return result


@mcp.tool()
def ck3_delete_file(
    mod_name: str,
    rel_path: str
) -> dict:
    """
    Delete a file from a whitelisted live mod.
    
    Args:
        mod_name: Name of the live mod
        rel_path: Relative path within the mod
    
    Returns:
        Success status
    """
    session = _get_session()
    trace = _get_trace()
    
    result = live_mods.delete_file(session, mod_name, rel_path)
    
    trace.log("ck3.delete_file", {
        "mod_name": mod_name,
        "rel_path": rel_path
    }, {"success": result.get("success", False)})
    
    return result


@mcp.tool()
def ck3_list_live_files(
    mod_name: str,
    path_prefix: Optional[str] = None,
    pattern: Optional[str] = None
) -> dict:
    """
    List files in a whitelisted live mod.
    
    Args:
        mod_name: Name of the live mod
        path_prefix: Filter by path prefix (e.g., "common/traits")
        pattern: Glob pattern filter (e.g., "*.txt")
    
    Returns:
        List of file paths
    """
    session = _get_session()
    trace = _get_trace()
    
    result = live_mods.list_live_files(session, mod_name, path_prefix, pattern)
    
    trace.log("ck3.list_live_files", {
        "mod_name": mod_name,
        "path_prefix": path_prefix,
        "pattern": pattern
    }, {"files_count": len(result.get("files", []))})
    
    return result


# ============================================================================
# Validation Tools
# ============================================================================

@mcp.tool()
def ck3_parse_content(
    content: str,
    filename: str = "inline.txt"
) -> dict:
    """
    Parse CK3 script content and return AST or errors.
    
    Args:
        content: CK3 script content to parse
        filename: Optional filename for error messages
    
    Returns:
        Parse result with AST (if successful) or errors
    """
    trace = _get_trace()
    
    result = parse_content(content, filename)
    
    trace.log("ck3.parse_content", {
        "filename": filename,
        "content_length": len(content)
    }, {"success": result["success"]})
    
    return result


@mcp.tool()
def ck3_validate_patchdraft(patchdraft: dict) -> dict:
    """
    Validate a PatchDraft contract.
    
    Checks path policy, parses content, and validates references.
    
    Args:
        patchdraft: PatchDraft as dict (patches list with path/content/format)
    
    Returns:
        ValidationReport with errors and warnings
    """
    trace = _get_trace()
    
    draft = PatchDraft.model_validate(patchdraft)
    report = validate_patchdraft(draft)
    
    trace.log("ck3.validate_patchdraft", {
        "patch_count": len(draft.patches)
    }, {"ok": report.ok, "errors": len(report.errors)})
    
    return report.model_dump()


# ============================================================================
# Git Operations
# ============================================================================

@mcp.tool()
def ck3_git_status(mod_name: str) -> dict:
    """
    Get git status for a live mod.
    
    Args:
        mod_name: Name of the live mod
    
    Returns:
        Git status (staged, unstaged, untracked files)
    """
    session = _get_session()
    trace = _get_trace()
    
    result = git_ops.git_status(session, mod_name)
    
    trace.log("ck3.git_status", {"mod_name": mod_name}, {"success": result.get("success", False)})
    
    return result


@mcp.tool()
def ck3_git_diff(
    mod_name: str,
    file_path: Optional[str] = None,
    staged: bool = False
) -> dict:
    """
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
    
    trace.log("ck3.git_diff", {"mod_name": mod_name, "file_path": file_path}, {"success": result.get("success", False)})
    
    return result


@mcp.tool()
def ck3_git_add(
    mod_name: str,
    paths: Optional[list[str]] = None
) -> dict:
    """
    Stage files for commit in a live mod.
    
    Args:
        mod_name: Name of the live mod
        paths: List of paths to stage (default: all changes)
    
    Returns:
        Success status
    """
    session = _get_session()
    trace = _get_trace()
    
    result = git_ops.git_add(session, mod_name, paths)
    
    trace.log("ck3.git_add", {"mod_name": mod_name, "paths": paths}, {"success": result.get("success", False)})
    
    return result


@mcp.tool()
def ck3_git_commit(
    mod_name: str,
    message: str
) -> dict:
    """
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
    
    trace.log("ck3.git_commit", {"mod_name": mod_name, "message": message[:50]}, {"success": result.get("success", False)})
    
    return result


@mcp.tool()
def ck3_git_push(mod_name: str) -> dict:
    """
    Push commits to remote for a live mod.
    
    Args:
        mod_name: Name of the live mod
    
    Returns:
        Push result
    """
    session = _get_session()
    trace = _get_trace()
    
    result = git_ops.git_push(session, mod_name)
    
    trace.log("ck3.git_push", {"mod_name": mod_name}, {"success": result.get("success", False)})
    
    return result


@mcp.tool()
def ck3_git_pull(mod_name: str) -> dict:
    """
    Pull latest changes from remote for a live mod.
    
    Args:
        mod_name: Name of the live mod
    
    Returns:
        Pull result
    """
    session = _get_session()
    trace = _get_trace()
    
    result = git_ops.git_pull(session, mod_name)
    
    trace.log("ck3.git_pull", {"mod_name": mod_name}, {"success": result.get("success", False)})
    
    return result


@mcp.tool()
def ck3_git_log(
    mod_name: str,
    limit: int = 10,
    file_path: Optional[str] = None
) -> dict:
    """
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
    
    trace.log("ck3.git_log", {"mod_name": mod_name, "limit": limit}, {"success": result.get("success", False)})
    
    return result


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    mcp.run()
