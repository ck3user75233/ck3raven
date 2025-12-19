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
def ck3_rename_file(
    mod_name: str,
    old_rel_path: str,
    new_rel_path: str
) -> dict:
    """
    Rename or move a file within a whitelisted live mod.
    
    Args:
        mod_name: Name of the live mod
        old_rel_path: Current relative path within the mod
        new_rel_path: New relative path within the mod
    
    Returns:
        Success status
    """
    session = _get_session()
    trace = _get_trace()
    
    result = live_mods.rename_file(session, mod_name, old_rel_path, new_rel_path)
    
    trace.log("ck3.rename_file", {
        "mod_name": mod_name,
        "old_rel_path": old_rel_path,
        "new_rel_path": new_rel_path
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
# Playset Management Tools
# ============================================================================

@mcp.tool()
def ck3_get_active_playset() -> dict:
    """
    Get information about the currently active playset.
    
    Returns:
        Playset details including name, mod count, and mod list with load order
    """
    db = _get_db()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    # Get playset info
    playset = db.conn.execute("""
        SELECT playset_id, name, description, is_active, created_at, updated_at
        FROM playsets WHERE playset_id = ?
    """, (playset_id,)).fetchone()
    
    if not playset:
        return {"error": "No active playset found"}
    
    # Get mods in playset with load order
    mods = db.conn.execute("""
        SELECT pm.load_order_index, mp.name, mp.workshop_id, cv.file_count
        FROM playset_mods pm
        JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
        JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
        WHERE pm.playset_id = ? AND pm.enabled = 1
        ORDER BY pm.load_order_index
    """, (playset_id,)).fetchall()
    
    result = {
        "playset_id": playset[0],
        "name": playset[1],
        "description": playset[2],
        "is_active": bool(playset[3]),
        "mod_count": len(mods),
        "mods": [
            {"load_order": m[0], "name": m[1], "workshop_id": m[2], "file_count": m[3]}
            for m in mods
        ]
    }
    
    trace.log("ck3.get_active_playset", {}, {"mod_count": len(mods)})
    
    return result


@mcp.tool()
def ck3_list_playsets() -> dict:
    """
    List all available playsets in the database.
    
    Returns:
        List of playsets with basic info
    """
    db = _get_db()
    trace = _get_trace()
    
    playsets = db.conn.execute("""
        SELECT p.playset_id, p.name, p.description, p.is_active,
               COUNT(pm.content_version_id) as mod_count
        FROM playsets p
        LEFT JOIN playset_mods pm ON p.playset_id = pm.playset_id AND pm.enabled = 1
        GROUP BY p.playset_id
        ORDER BY p.is_active DESC, p.updated_at DESC
    """).fetchall()
    
    result = {
        "playsets": [
            {
                "playset_id": p[0],
                "name": p[1],
                "description": p[2],
                "is_active": bool(p[3]),
                "mod_count": p[4]
            }
            for p in playsets
        ]
    }
    
    trace.log("ck3.list_playsets", {}, {"count": len(playsets)})
    
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
    
    trace.log("ck3.search_mods", {"query": query, "search_by": search_by, "fuzzy": fuzzy},
              {"result_count": len(results)})
    
    return {"results": results[:limit], "query": query}


@mcp.tool()
def ck3_add_mod_to_playset(
    mod_identifier: str,
    position: Optional[int] = None,
    before_mod: Optional[str] = None,
    after_mod: Optional[str] = None
) -> dict:
    """
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
    
    trace.log("ck3.add_mod_to_playset", {
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


@mcp.tool()
def ck3_remove_mod_from_playset(
    mod_identifier: str
) -> dict:
    """
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
    
    trace.log("ck3.remove_mod_from_playset", {"mod_identifier": mod_identifier},
              {"mod_name": mod_name, "position": removed_position})
    
    return {
        "success": True,
        "mod_name": mod_name,
        "removed_from_position": removed_position
    }


# ============================================================================
# Conflict Analysis Tools (Unit-Level)
# ============================================================================

@mcp.tool()
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
        
        trace.log("ck3.scan_unit_conflicts", 
                  {"folder_filter": folder_filter},
                  {"conflicts_found": result["conflicts_found"]})
        
        return result
        
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def ck3_get_conflict_summary() -> dict:
    """
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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
    
    trace.log("ck3.resolve_conflict", 
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


@mcp.tool()
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
# General Search Tools
# ============================================================================

@mcp.tool()
def ck3_search_files(
    pattern: str,
    source_filter: Optional[str] = None,
    limit: int = 100
) -> dict:
    """
    Search for files by path pattern.
    
    Use this when you need to find files by name or path pattern,
    NOT for symbol/definition search (use ck3_search_symbols for that).
    
    Args:
        pattern: SQL LIKE pattern for file path (e.g., "%on_action%" or "common/traits/%")
        source_filter: Filter by source ("vanilla", mod name, or mod ID)
        limit: Maximum results to return
    
    Returns:
        List of matching files with source info
    """
    db = _get_db()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    files = db.search_files(playset_id, pattern, source_filter, limit)
    
    trace.log("ck3.search_files", {
        "pattern": pattern,
        "source_filter": source_filter,
    }, {"count": len(files)})
    
    return {"pattern": pattern, "count": len(files), "files": files}


@mcp.tool()
def ck3_search_content(
    query: str,
    file_pattern: Optional[str] = None,
    source_filter: Optional[str] = None,
    limit: int = 50
) -> dict:
    """
    Search file contents for text matches (grep-style).
    
    Use this when you need to search for specific text inside files,
    like finding where a specific effect or trigger is used.
    
    Args:
        query: Text to search for (case-insensitive substring match)
        file_pattern: SQL LIKE pattern to limit which files are searched
        source_filter: Filter by source ("vanilla", mod name, or mod ID)
        limit: Maximum results to return
    
    Returns:
        List of matching files with context snippets
    """
    db = _get_db()
    trace = _get_trace()
    playset_id = _get_playset_id()
    
    results = db.search_content(playset_id, query, file_pattern, source_filter, limit)
    
    trace.log("ck3.search_content", {
        "query": query,
        "file_pattern": file_pattern,
    }, {"count": len(results)})
    
    return {"query": query, "count": len(results), "results": results}


# ============================================================================
# Conflicts Report Tools
# ============================================================================

@mcp.tool()
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
    
    trace.log("ck3.generate_conflicts_report", {
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


@mcp.tool()
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
    
    trace.log("ck3.get_high_risk_conflicts", {
        "domain": domain,
        "min_risk_score": min_risk_score,
    }, {"count": len(all_conflicts)})
    
    return {
        "count": len(all_conflicts),
        "conflicts": all_conflicts[:limit],
    }


# ============================================================================
# Log Parsing Tools
# ============================================================================

@mcp.tool()
def ck3_get_error_summary() -> dict:
    """
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
    from ck3raven.logs.error_parser import CK3ErrorParser
    
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


@mcp.tool()
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
    from ck3raven.logs.error_parser import CK3ErrorParser
    
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
    from ck3raven.logs.error_parser import ERROR_CATEGORIES
    
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


@mcp.tool()
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
    from ck3raven.logs.error_parser import CK3ErrorParser
    
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


@mcp.tool()
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
    from ck3raven.logs.error_parser import CK3ErrorParser
    
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


@mcp.tool()
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
    from ck3raven.logs.crash_parser import get_recent_crashes
    
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


@mcp.tool()
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
    from ck3raven.logs.crash_parser import parse_crash_folder
    
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


@mcp.tool()
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


# ============================================================================
# Explorer Tools (for UI navigation)
# ============================================================================

@mcp.tool()
def ck3_get_playset_mods() -> dict:
    """
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


@mcp.tool()
def ck3_get_top_level_folders() -> dict:
    """
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


@mcp.tool()
def ck3_get_mod_folders(content_version_id: int) -> dict:
    """
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


@mcp.tool()
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
    mode: Literal["ck3lens", "ck3lens-live", "ck3raven-dev"]
) -> dict:
    """
    Get the instruction content for a specific agent mode.
    
    Use this to understand what a mode does or to switch modes.
    
    Args:
        mode: The mode to get instructions for:
            - "ck3lens": Database-only CK3 modding (restricted tools)
            - "ck3lens-live": Full CK3 modding with live file editing
            - "ck3raven-dev": Full development mode for infrastructure
    
    Returns:
        Mode instructions and configuration
    """
    from pathlib import Path
    
    # Map modes to instruction files
    mode_files = {
        "ck3lens": "COPILOT_LENS_COMPATCH.md",
        "ck3lens-live": "COPILOT_LENS_COMPATCH.md",  # Same file, different tool access
        "ck3raven-dev": "COPILOT_RAVEN_DEV.md",
    }
    
    if mode not in mode_files:
        return {
            "error": f"Unknown mode: {mode}",
            "available_modes": list(mode_files.keys()),
        }
    
    # Find the instructions file
    ck3raven_root = Path(__file__).parent.parent.parent
    instructions_path = ck3raven_root / ".github" / mode_files[mode]
    
    if not instructions_path.exists():
        return {
            "error": f"Instructions file not found: {mode_files[mode]}",
            "expected_path": str(instructions_path),
        }
    
    try:
        content = instructions_path.read_text(encoding="utf-8")
        
        # Add mode-specific notes
        mode_notes = {
            "ck3lens": "Restricted mode: Use only MCP tools, no filesystem access.",
            "ck3lens-live": "Full CK3 modding: All MCP tools including live file operations.",
            "ck3raven-dev": "Development mode: All tools available for infrastructure work.",
        }
        
        return {
            "mode": mode,
            "note": mode_notes.get(mode, ""),
            "instructions": content,
            "source_file": str(instructions_path),
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def ck3_get_workspace_config() -> dict:
    """
    Get the workspace configuration including tool sets and MCP settings.
    
    Use this to understand:
    - Available modes/tool sets and what tools they enable
    - MCP server configuration
    - Live mod whitelist
    - Database path
    
    Returns:
        Complete workspace configuration
    """
    from pathlib import Path
    import json
    
    session = _get_session()
    
    result = {
        "database": {
            "path": str(session.db_path),
            "exists": session.db_path.exists(),
        },
        "live_mods": [
            {"id": m.id, "name": m.name, "path": str(m.path)}
            for m in (session.live_mods or [])
        ],
        "tool_sets": None,
        "mcp_config": None,
        "available_modes": [
            {
                "name": "ck3lens",
                "description": "Database-only CK3 modding - searches, symbols, file content, conflict detection",
                "use_case": "Fixing mod errors, compatibility patching",
            },
            {
                "name": "ck3lens-live",
                "description": "Full CK3 modding including live file editing and git operations",
                "use_case": "Active mod development with file writes",
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
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    mcp.run()
