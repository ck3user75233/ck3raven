"""
Incremental File Refresh for ck3raven

Updates a single file in the database after edits.
This is the fast path for live mod editing - full rebuild not needed.

Operations (all < 500ms for typical files):
1. Update file_contents with new content hash
2. Update files table with new hash  
3. Parse and store AST (if script file)
4. Re-extract symbols and refs (if AST succeeded)

Usage:
    from builder.incremental import refresh_single_file
    
    result = refresh_single_file(conn, mod_name="MyMod", rel_path="common/traits/zzz_mymod_traits.txt")
    # Returns: {"success": True, "ingested": True, "parsed": True, "symbols": 42, "refs": 18}
"""

import sqlite3
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)


def refresh_single_file(
    conn: sqlite3.Connection,
    mod_name: str,
    rel_path: str,
    content: Optional[str] = None,
    full_path: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Refresh a single file in the database after edit.
    
    This is the incremental update path - much faster than full rebuild.
    Call this after writing/editing a file in a live mod.
    
    Args:
        conn: Database connection
        mod_name: Name of the mod (used to find file in database)
        rel_path: Relative path within mod (e.g., "common/traits/my_traits.txt")
        content: File content (if None, reads from disk using full_path)
        full_path: Absolute path to file (required if content is None)
    
    Returns:
        {
            "success": bool,
            "ingested": bool,      # Content was stored/updated
            "parsed": bool,        # AST was generated (if script file)
            "symbols": int,        # Number of symbols extracted
            "refs": int,           # Number of references extracted
            "content_hash": str,   # New content hash
            "time_ms": float,      # Total time in milliseconds
            "error": str           # Error message if failed
        }
    """
    start_time = time.perf_counter()
    
    result = {
        "success": False,
        "ingested": False,
        "parsed": False,
        "symbols": 0,
        "refs": 0,
        "content_hash": None,
        "time_ms": 0,
        "error": None
    }
    
    try:
        # Get content
        if content is None:
            if full_path is None:
                result["error"] = "Either content or full_path must be provided"
                return result
            
            if not full_path.exists():
                result["error"] = f"File not found: {full_path}"
                return result
            
            content = full_path.read_text(encoding="utf-8-sig")
        
        # Convert to bytes for hashing/storage
        content_bytes = content.encode("utf-8")
        
        # Step 1: Store content (deduped by hash)
        from ck3raven.db.content import compute_content_hash, store_file_content
        
        content_hash = compute_content_hash(content_bytes)
        store_file_content(conn, content_bytes, content_hash)
        result["content_hash"] = content_hash
        result["ingested"] = True
        
        # Step 2: Find or create file record
        file_id = _get_or_create_file_id(conn, mod_name, rel_path, content_hash)
        
        if file_id is None:
            result["error"] = f"Could not find/create file record for {mod_name}/{rel_path}"
            return result
        
        # Step 3: Route the file to determine processing
        from ck3raven.db.file_routes import get_file_route, FileRoute
        
        route, reason = get_file_route(rel_path)
        logger.debug(f"File route for {rel_path}: {route.value} ({reason})")
        
        if route == FileRoute.SKIP:
            # No further processing needed
            result["success"] = True
            result["time_ms"] = (time.perf_counter() - start_time) * 1000
            return result
        
        if route == FileRoute.LOCALIZATION:
            # Localization files use different parser
            loc_result = _refresh_localization(conn, file_id, content_hash, content, rel_path)
            result.update(loc_result)
            result["success"] = True
            result["time_ms"] = (time.perf_counter() - start_time) * 1000
            return result
        
        # Route == SCRIPT or LOOKUPS - parse with script parser
        # Step 4: Parse and store AST
        ast_id = _parse_and_store_ast(conn, content_hash, content, rel_path)
        
        if ast_id is None:
            # Parse failed - still consider success (file is stored)
            result["success"] = True
            result["parsed"] = False
            result["time_ms"] = (time.perf_counter() - start_time) * 1000
            return result
        
        result["parsed"] = True
        
        # Step 5: Extract symbols and refs
        sym_count, ref_count = _extract_symbols_and_refs(
            conn, file_id, content_hash, ast_id, rel_path
        )
        
        result["symbols"] = sym_count
        result["refs"] = ref_count
        result["success"] = True
        
    except Exception as e:
        logger.exception(f"Error refreshing {mod_name}/{rel_path}")
        result["error"] = str(e)
    
    result["time_ms"] = (time.perf_counter() - start_time) * 1000
    return result


def mark_file_deleted(
    conn: sqlite3.Connection,
    mod_name: str,
    rel_path: str
) -> Dict[str, Any]:
    """
    Mark a file as deleted in the database.
    
    Doesn't remove content (other files may share it).
    Sets deleted=1 on files table and removes symbols/refs.
    
    Args:
        conn: Database connection
        mod_name: Name of the mod
        rel_path: Relative path within mod
    
    Returns:
        {"success": bool, "file_id": int, "error": str}
    """
    result = {"success": False, "file_id": None, "error": None}
    
    try:
        # Find the file
        file_id = _find_file_id(conn, mod_name, rel_path)
        
        if file_id is None:
            result["error"] = f"File not found: {mod_name}/{rel_path}"
            return result
        
        result["file_id"] = file_id
        
        # Mark as deleted
        conn.execute("UPDATE files SET deleted = 1 WHERE file_id = ?", (file_id,))
        
        # Remove symbols and refs for this file
        conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
        conn.execute("DELETE FROM refs WHERE file_id = ?", (file_id,))
        
        conn.commit()
        result["success"] = True
        
    except Exception as e:
        logger.exception(f"Error marking {mod_name}/{rel_path} as deleted")
        result["error"] = str(e)
    
    return result


def _get_or_create_file_id(
    conn: sqlite3.Connection,
    mod_name: str,
    rel_path: str,
    content_hash: str
) -> Optional[int]:
    """Get existing file_id or create new file record."""
    
    # First try to find existing file
    file_id = _find_file_id(conn, mod_name, rel_path)
    
    if file_id is not None:
        # Update content hash
        conn.execute("""
            UPDATE files 
            SET content_hash = ?, deleted = 0
            WHERE file_id = ?
        """, (content_hash, file_id))
        conn.commit()
        return file_id
    
    # Need to create new file record
    # First find the content_version_id for this mod
    row = conn.execute("""
        SELECT cv.content_version_id
        FROM content_versions cv
        JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
        WHERE mp.name = ?
        ORDER BY cv.ingested_at DESC
        LIMIT 1
    """, (mod_name,)).fetchone()
    
    if row is None:
        logger.warning(f"Mod not found in database: {mod_name}")
        return None
    
    content_version_id = row[0]
    
    # Insert new file record
    cursor = conn.execute("""
        INSERT INTO files (content_version_id, relpath, content_hash, deleted)
        VALUES (?, ?, ?, 0)
    """, (content_version_id, rel_path, content_hash))
    
    conn.commit()
    return cursor.lastrowid


def _find_file_id(
    conn: sqlite3.Connection,
    mod_name: str,
    rel_path: str
) -> Optional[int]:
    """Find file_id by mod name and relative path."""
    
    # Join through content_versions and mod_packages to find by mod name
    row = conn.execute("""
        SELECT f.file_id
        FROM files f
        JOIN content_versions cv ON f.content_version_id = cv.content_version_id
        JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
        WHERE mp.name = ? AND f.relpath = ?
        ORDER BY cv.ingested_at DESC
        LIMIT 1
    """, (mod_name, rel_path)).fetchone()
    
    return row[0] if row else None


def _parse_and_store_ast(
    conn: sqlite3.Connection,
    content_hash: str,
    content: str,
    rel_path: str
) -> Optional[int]:
    """Parse content and store AST. Returns ast_id or None if failed."""
    
    from ck3raven.parser import parse_source
    from ck3raven.db.ast_cache import store_ast, store_parse_failure, get_current_parser_version
    
    parser_version = get_current_parser_version(conn)
    
    try:
        ast = parse_source(content)
        record = store_ast(conn, content_hash, ast, parser_version.parser_version_id)
        return record.ast_id
        
    except Exception as e:
        logger.warning(f"Parse failed for {rel_path}: {e}")
        store_parse_failure(conn, content_hash, str(e), parser_version.parser_version_id)
        return None


def _extract_symbols_and_refs(
    conn: sqlite3.Connection,
    file_id: int,
    content_hash: str,
    ast_id: int,
    rel_path: str
) -> Tuple[int, int]:
    """Extract symbols and refs from stored AST. Returns (symbol_count, ref_count)."""
    
    from ck3raven.db.ast_cache import deserialize_ast
    from ck3raven.db.symbols import extract_symbols_from_ast, extract_refs_from_ast
    
    # Get AST blob
    row = conn.execute(
        "SELECT ast_blob FROM asts WHERE ast_id = ?",
        (ast_id,)
    ).fetchone()
    
    if row is None:
        logger.warning(f"AST not found for ast_id={ast_id}")
        return 0, 0
    
    ast_dict = deserialize_ast(row[0])
    
    # Delete old symbols and refs for this file
    conn.execute("DELETE FROM symbols WHERE defining_file_id = ?", (file_id,))
    conn.execute("DELETE FROM refs WHERE using_file_id = ?", (file_id,))
    
    # Extract symbols
    symbols = list(extract_symbols_from_ast(ast_dict, rel_path, content_hash))
    sym_count = 0
    
    for sym in symbols:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO symbols
            (symbol_type, name, scope, defining_ast_id, defining_file_id,
             content_version_id, line_number, metadata_json)
            VALUES (?, ?, ?, ?, ?,
                    (SELECT content_version_id FROM files WHERE file_id = ?),
                    ?, ?)
        """, (
            sym.kind, sym.name, sym.scope, ast_id, file_id,
            file_id, sym.line, None
        ))
        if cursor.rowcount > 0:
            sym_count += 1
    
    # Extract refs
    refs = list(extract_refs_from_ast(ast_dict, rel_path, content_hash))
    ref_count = 0
    
    for ref in refs:
        cursor = conn.execute("""
            INSERT INTO refs
            (ref_type, name, using_ast_id, using_file_id, 
             content_version_id, line_number, context)
            VALUES (?, ?, ?, ?,
                    (SELECT content_version_id FROM files WHERE file_id = ?),
                    ?, ?)
        """, (
            ref.kind, ref.name, ast_id, file_id,
            file_id, ref.line, ref.context
        ))
        if cursor.rowcount > 0:
            ref_count += 1
    
    conn.commit()
    return sym_count, ref_count


def _refresh_localization(
    conn: sqlite3.Connection,
    file_id: int,
    content_hash: str,
    content: str,
    rel_path: str
) -> Dict[str, Any]:
    """Refresh a localization file. Returns dict with loc_entries count."""
    
    from ck3raven.parser.localization import parse_localization
    from ck3raven.db.ast_cache import get_current_parser_version
    
    parser_version = get_current_parser_version(conn)
    result = {"parsed": False, "loc_entries": 0}
    
    try:
        # Delete existing loc entries for this content hash
        conn.execute("""
            DELETE FROM localization_entries 
            WHERE content_hash = ? AND parser_version_id = ?
        """, (content_hash, parser_version.parser_version_id))
        
        # Parse localization
        loc_file = parse_localization(content, rel_path)
        
        if loc_file.entries:
            # Insert new entries
            rows = [
                (content_hash, parser_version.parser_version_id,
                 entry.key, entry.value, entry.version or 0,
                 loc_file.language)
                for entry in loc_file.entries
            ]
            
            conn.executemany("""
                INSERT INTO localization_entries 
                (content_hash, parser_version_id, key, value, version, language)
                VALUES (?, ?, ?, ?, ?, ?)
            """, rows)
            
            result["loc_entries"] = len(rows)
        
        conn.commit()
        result["parsed"] = True
        
    except Exception as e:
        logger.warning(f"Localization parse failed for {rel_path}: {e}")
    
    return result


# Batch refresh for multiple files
def refresh_files_batch(
    conn: sqlite3.Connection,
    files: list[Tuple[str, str, Optional[str]]]
) -> Dict[str, Any]:
    """
    Refresh multiple files in one call.
    
    Args:
        conn: Database connection
        files: List of (mod_name, rel_path, content) tuples
               If content is None, file is marked as deleted
    
    Returns:
        {
            "success": True,
            "total": int,
            "refreshed": int,
            "deleted": int,
            "errors": int,
            "results": [...]
        }
    """
    results = []
    refreshed = 0
    deleted = 0
    errors = 0
    
    for mod_name, rel_path, content in files:
        if content is None:
            # Delete
            r = mark_file_deleted(conn, mod_name, rel_path)
            if r["success"]:
                deleted += 1
            else:
                errors += 1
        else:
            # Refresh
            r = refresh_single_file(conn, mod_name, rel_path, content=content)
            if r["success"]:
                refreshed += 1
            else:
                errors += 1
        
        results.append({
            "mod_name": mod_name,
            "rel_path": rel_path,
            **r
        })
    
    return {
        "success": errors == 0,
        "total": len(files),
        "refreshed": refreshed,
        "deleted": deleted,
        "errors": errors,
        "results": results
    }


# =============================================================================
# Playset Build Status Check
# =============================================================================

def check_playset_build_status(
    conn: sqlite3.Connection,
    playset_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Check the build status of mods in a playset.
    
    This is called when switching to a new playset to determine which mods
    need to be built before the playset can be used effectively.
    
    Build phases per mod:
    1. ingested_at - Files indexed into database
    2. symbols_extracted_at - Symbols (traits, events, etc.) extracted from ASTs
    3. contributions_extracted_at - Contribution units extracted for conflict detection
    
    Args:
        conn: Database connection
        playset_data: Playset definition with:
            - vanilla_version_id: int
            - mods: list of {content_version_id, name, path, ...}
    
    Returns:
        {
            "playset_valid": bool,      # True if at least one mod exists on disk
            "total_mods": int,
            "ready_mods": int,          # Fully processed (symbols extracted)
            "pending_mods": int,        # Need processing
            "missing_mods": int,        # Not on disk
            "mods": [
                {
                    "name": str,
                    "content_version_id": int,
                    "status": "ready" | "pending_symbols" | "pending_ingest" | "not_indexed" | "missing",
                    "ingested_at": str | None,
                    "symbols_extracted_at": str | None,
                    "exists_on_disk": bool,
                    "path": str | None
                }
            ],
            "needs_build": bool,        # True if any mods need processing
            "missing_mod_names": list,  # Names of mods not on disk
        }
    """
    result = {
        "playset_valid": False,
        "total_mods": 0,
        "ready_mods": 0,
        "pending_mods": 0,
        "missing_mods": 0,
        "mods": [],
        "needs_build": False,
        "missing_mod_names": [],
    }
    
    # Check vanilla first
    vanilla_version_id = playset_data.get("vanilla_version_id")
    if vanilla_version_id:
        row = conn.execute("""
            SELECT cv.content_version_id, cv.ingested_at, cv.symbols_extracted_at,
                   vv.ck3_version
            FROM content_versions cv
            JOIN vanilla_versions vv ON cv.vanilla_version_id = vv.vanilla_version_id
            WHERE cv.vanilla_version_id = ? AND cv.kind = 'vanilla'
        """, (vanilla_version_id,)).fetchone()
        
        if row:
            # Vanilla is assumed to exist if it's in the database
            # The path is external knowledge (from workspace config)
            if row["symbols_extracted_at"]:
                status = "ready"
                result["ready_mods"] += 1
            elif row["ingested_at"]:
                status = "pending_symbols"
                result["pending_mods"] += 1
                result["needs_build"] = True
            else:
                status = "pending_ingest"
                result["pending_mods"] += 1
                result["needs_build"] = True
            
            result["mods"].append({
                "name": f"Vanilla {row['ck3_version']}",
                "content_version_id": row["content_version_id"],
                "status": status,
                "ingested_at": row["ingested_at"],
                "symbols_extracted_at": row["symbols_extracted_at"],
                "exists_on_disk": True,  # Assumed - vanilla must exist to be indexed
                "path": None,  # Path is external to DB
                "is_vanilla": True,
            })
            result["total_mods"] += 1
            result["playset_valid"] = True  # Vanilla exists = playset is valid
    
    # Check each mod
    mods = playset_data.get("mods", [])
    for mod in mods:
        content_version_id = mod.get("content_version_id")
        mod_name = mod.get("name", "Unknown")
        mod_path = mod.get("path")
        
        if content_version_id:
            row = conn.execute("""
                SELECT ingested_at, symbols_extracted_at
                FROM content_versions
                WHERE content_version_id = ?
            """, (content_version_id,)).fetchone()
        else:
            row = None
        
        # Check if mod exists on disk
        exists_on_disk = mod_path and Path(mod_path).exists() if mod_path else False
        
        if not exists_on_disk:
            status = "missing"
            result["missing_mods"] += 1
            result["missing_mod_names"].append(mod_name)
        elif row is None:
            status = "not_indexed"
            result["pending_mods"] += 1
            result["needs_build"] = True
        elif row["symbols_extracted_at"]:
            status = "ready"
            result["ready_mods"] += 1
        elif row["ingested_at"]:
            status = "pending_symbols"
            result["pending_mods"] += 1
            result["needs_build"] = True
        else:
            status = "pending_ingest"
            result["pending_mods"] += 1
            result["needs_build"] = True
        
        result["mods"].append({
            "name": mod_name,
            "content_version_id": content_version_id,
            "status": status,
            "ingested_at": row["ingested_at"] if row else None,
            "symbols_extracted_at": row["symbols_extracted_at"] if row else None,
            "exists_on_disk": exists_on_disk,
            "path": mod_path,
            "is_vanilla": False,
        })
        result["total_mods"] += 1
        
        if exists_on_disk:
            result["playset_valid"] = True
    
    return result


# =============================================================================
# Incremental Rebuild Detection
# =============================================================================

def get_mods_needing_rebuild(
    conn: sqlite3.Connection,
    playset_mods: list[Dict[str, Any]],
    check_file_changes: bool = False
) -> Dict[str, Any]:
    """
    Determine which mods need processing for an incremental rebuild.
    
    This is the key function for incremental builds - it checks each mod in
    the playset and determines if it needs any processing.
    
    A mod needs processing if:
    1. Not in database at all (new mod)
    2. Ingested but symbols not extracted (interrupted build)
    3. Files changed on disk since last ingest (if check_file_changes=True)
    
    Args:
        conn: Database connection
        playset_mods: List of mods from playset, each with:
            - name: str
            - path: str
            - workshop_id: str or None
            - load_order: int
        check_file_changes: If True, also check for changed files (slower)
    
    Returns:
        {
            "needs_rebuild": bool,
            "total_mods": int,
            "mods_needing_ingest": list,    # New mods not in DB
            "mods_needing_symbols": list,   # Ingested but no symbols
            "mods_with_changes": list,      # Files changed on disk
            "mods_ready": list,             # Fully processed
            "mods_missing": list,           # Path doesn't exist
            "summary": str,
        }
    """
    result = {
        "needs_rebuild": False,
        "total_mods": len(playset_mods),
        "mods_needing_ingest": [],
        "mods_needing_symbols": [],
        "mods_with_changes": [],
        "mods_ready": [],
        "mods_missing": [],
        "summary": "",
    }
    
    for mod in playset_mods:
        mod_name = mod.get("name", "Unknown")
        mod_path = mod.get("path")
        workshop_id = mod.get("workshop_id")
        
        # Check if mod exists on disk
        if not mod_path or not Path(mod_path).exists():
            result["mods_missing"].append({"name": mod_name, "path": mod_path})
            continue
        
        # Look up mod in database by path or workshop_id
        cv_row = None
        if workshop_id:
            cv_row = conn.execute("""
                SELECT cv.content_version_id, cv.ingested_at, cv.symbols_extracted_at,
                       mp.name, mp.mod_package_id
                FROM content_versions cv
                JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE mp.workshop_id = ?
                ORDER BY cv.ingested_at DESC
                LIMIT 1
            """, (workshop_id,)).fetchone()
        
        if cv_row is None:
            # Try by path
            cv_row = conn.execute("""
                SELECT cv.content_version_id, cv.ingested_at, cv.symbols_extracted_at,
                       mp.name, mp.mod_package_id
                FROM content_versions cv
                JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE mp.source_path = ?
                ORDER BY cv.ingested_at DESC
                LIMIT 1
            """, (str(mod_path),)).fetchone()
        
        if cv_row is None:
            # Mod not in database - needs full ingest
            result["mods_needing_ingest"].append({
                "name": mod_name,
                "path": mod_path,
                "workshop_id": workshop_id,
                "reason": "new_mod"
            })
            result["needs_rebuild"] = True
            continue
        
        # Mod is in database - check processing state
        ingested_at = cv_row["ingested_at"]
        symbols_at = cv_row["symbols_extracted_at"]
        cv_id = cv_row["content_version_id"]
        
        if symbols_at is None:
            # Symbols not extracted - interrupted build
            result["mods_needing_symbols"].append({
                "name": mod_name,
                "path": mod_path,
                "content_version_id": cv_id,
                "reason": "pending_symbols"
            })
            result["needs_rebuild"] = True
            continue
        
        # Check for file changes if requested
        if check_file_changes:
            changes = _detect_mod_file_changes(conn, cv_id, Path(mod_path))
            if changes["has_changes"]:
                result["mods_with_changes"].append({
                    "name": mod_name,
                    "path": mod_path,
                    "content_version_id": cv_id,
                    "changes": changes,
                    "reason": "files_changed"
                })
                result["needs_rebuild"] = True
                continue
        
        # Mod is fully processed
        result["mods_ready"].append({
            "name": mod_name,
            "path": mod_path,
            "content_version_id": cv_id
        })
    
    # Generate summary
    parts = []
    if result["mods_needing_ingest"]:
        parts.append(f"{len(result['mods_needing_ingest'])} new")
    if result["mods_needing_symbols"]:
        parts.append(f"{len(result['mods_needing_symbols'])} need symbols")
    if result["mods_with_changes"]:
        parts.append(f"{len(result['mods_with_changes'])} changed")
    if result["mods_missing"]:
        parts.append(f"{len(result['mods_missing'])} missing")
    
    if parts:
        result["summary"] = f"Need rebuild: {', '.join(parts)}"
    else:
        result["summary"] = f"All {len(result['mods_ready'])} mods ready"
    
    return result


def _detect_mod_file_changes(
    conn: sqlite3.Connection,
    content_version_id: int,
    mod_path: Path
) -> Dict[str, Any]:
    """
    Detect file changes in a mod by comparing disk to database.
    
    Compares file hashes between database and disk to detect:
    - New files (on disk, not in database)
    - Deleted files (in database, not on disk)
    - Modified files (hash mismatch)
    
    Args:
        conn: Database connection
        content_version_id: The content_version_id for this mod
        mod_path: Path to mod on disk
    
    Returns:
        {
            "has_changes": bool,
            "new_files": list,
            "deleted_files": list,
            "modified_files": list,
        }
    """
    from ck3raven.db.content import compute_content_hash
    
    result = {
        "has_changes": False,
        "new_files": [],
        "deleted_files": [],
        "modified_files": [],
    }
    
    # Get all files for this content_version from database
    db_files = {}
    rows = conn.execute("""
        SELECT file_id, relpath, content_hash
        FROM files
        WHERE content_version_id = ? AND deleted = 0
    """, (content_version_id,)).fetchall()
    
    for row in rows:
        db_files[row["relpath"]] = {
            "file_id": row["file_id"],
            "content_hash": row["content_hash"]
        }
    
    # Scan disk files
    disk_files = set()
    script_extensions = {'.txt', '.yml', '.mod', '.info'}
    
    for file_path in mod_path.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in script_extensions:
            continue
        
        rel_path = str(file_path.relative_to(mod_path)).replace("\\", "/")
        disk_files.add(rel_path)
        
        if rel_path not in db_files:
            # New file
            result["new_files"].append(rel_path)
            result["has_changes"] = True
        else:
            # Check if content changed (sample first 100 files only for speed)
            if len(result["modified_files"]) < 100:
                try:
                    content = file_path.read_bytes()
                    disk_hash = compute_content_hash(content)
                    if disk_hash != db_files[rel_path]["content_hash"]:
                        result["modified_files"].append(rel_path)
                        result["has_changes"] = True
                except Exception:
                    pass  # Skip unreadable files
    
    # Check for deleted files
    for rel_path in db_files:
        if rel_path not in disk_files:
            result["deleted_files"].append(rel_path)
            result["has_changes"] = True
    
    return result


def get_files_needing_processing(
    conn: sqlite3.Connection,
    content_version_id: int
) -> Dict[str, Any]:
    """
    Get files that need processing for a specific mod.
    
    Checks which files have:
    - No AST (needs parsing)
    - No symbols extracted (needs symbol extraction)
    - No refs extracted (needs ref extraction)
    
    Args:
        conn: Database connection
        content_version_id: Mod's content_version_id
    
    Returns:
        {
            "needs_parsing": list of file_ids,
            "needs_symbols": list of file_ids,
            "needs_refs": list of file_ids,
            "total_files": int,
        }
    """
    result = {
        "needs_parsing": [],
        "needs_symbols": [],
        "needs_refs": [],
        "total_files": 0,
    }
    
    # Get parser version
    parser_row = conn.execute(
        "SELECT parser_version_id FROM parsers ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    parser_version_id = parser_row[0] if parser_row else 1
    
    # Files needing AST
    rows = conn.execute("""
        SELECT f.file_id, f.relpath
        FROM files f
        LEFT JOIN asts a ON f.content_hash = a.content_hash 
            AND a.parser_version_id = ?
        WHERE f.content_version_id = ?
        AND f.deleted = 0
        AND f.relpath LIKE '%.txt'
        AND a.ast_id IS NULL
    """, (parser_version_id, content_version_id)).fetchall()
    
    result["needs_parsing"] = [r["file_id"] for r in rows]
    
    # Files needing symbol extraction (have AST but no symbols)
    rows = conn.execute("""
        SELECT DISTINCT f.file_id
        FROM files f
        JOIN asts a ON f.content_hash = a.content_hash
        LEFT JOIN symbols s ON s.defining_file_id = f.file_id
        WHERE f.content_version_id = ?
        AND f.deleted = 0
        AND a.parser_version_id = ?
        AND s.symbol_id IS NULL
    """, (content_version_id, parser_version_id)).fetchall()
    
    result["needs_symbols"] = [r["file_id"] for r in rows]
    
    # Files needing ref extraction
    rows = conn.execute("""
        SELECT DISTINCT f.file_id
        FROM files f
        JOIN asts a ON f.content_hash = a.content_hash
        LEFT JOIN refs r ON r.using_file_id = f.file_id
        WHERE f.content_version_id = ?
        AND f.deleted = 0
        AND a.parser_version_id = ?
        AND r.ref_id IS NULL
    """, (content_version_id, parser_version_id)).fetchall()
    
    result["needs_refs"] = [r["file_id"] for r in rows]
    
    # Total files
    total_row = conn.execute("""
        SELECT COUNT(*) FROM files 
        WHERE content_version_id = ? AND deleted = 0
    """, (content_version_id,)).fetchone()
    result["total_files"] = total_row[0] if total_row else 0
    
    return result
