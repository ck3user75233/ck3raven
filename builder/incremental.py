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
    
    result = refresh_single_file(conn, mod_name="MSC", rel_path="common/traits/zzz_msc_traits.txt")
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
