"""
File Operations Implementation

Shared implementation module for file operations.
Used by both MCP server (server.py) and VS Code extension bridge.

This module provides database file query functions that take explicit parameters,
avoiding reliance on global state or playset_mods table (BANNED).

Architecture:
- Takes database connection and CVID list as parameters
- CVIDs are obtained from playset_ops.get_playset_mods()
- Both MCP and bridge call with their own connection/CVID context
"""
from __future__ import annotations

import sqlite3
from typing import Optional


def list_files(
    conn: sqlite3.Connection,
    folder: str,
    cvids: Optional[set[int]] = None,
) -> dict:
    """List files in a folder within the playset.
    
    Args:
        conn: Database connection
        folder: Folder path to list (without trailing slash)
        cvids: Set of content_version_ids to filter to
    
    Returns:
        Dict with files and folders lists
    """
    folder = folder.rstrip("/")
    
    try:
        # Build CVID filter
        cvid_filter = ""
        params_base = []
        if cvids:
            placeholders = ",".join("?" * len(cvids))
            cvid_filter = f"cv.content_version_id IN ({placeholders})"
            params_base = list(sorted(cvids))
        else:
            cvid_filter = "1=1"  # No filter
        
        # Get files directly in this folder
        files_sql = f"""
            SELECT f.file_id, f.relpath, mp.name as mod_name
            FROM files f
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE {cvid_filter}
            AND f.relpath LIKE ? || '/%'
            AND f.relpath NOT LIKE ? || '/%/%'
            ORDER BY f.relpath
        """
        files_params = params_base + [folder, folder]
        files = conn.execute(files_sql, files_params).fetchall()
        
        # Get subfolders
        subfolders_sql = f"""
            SELECT DISTINCT 
                SUBSTR(f.relpath, LENGTH(?) + 2, 
                       INSTR(SUBSTR(f.relpath, LENGTH(?) + 2), '/') - 1
                ) as subfolder,
                COUNT(*) as file_count
            FROM files f
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            WHERE {cvid_filter}
            AND f.relpath LIKE ? || '/%/%'
            GROUP BY subfolder
            HAVING subfolder != '' AND subfolder IS NOT NULL
            ORDER BY subfolder
        """
        subfolders_params = [folder, folder] + params_base + [folder]
        subfolders = conn.execute(subfolders_sql, subfolders_params).fetchall()
        
        return {
            "files": [
                {"fileId": f[0], "relpath": f[1], "mod": f[2] or "vanilla"}
                for f in files
            ],
            "folders": [
                {"name": sf[0], "fileCount": sf[1]}
                for sf in subfolders
            ]
        }
        
    except Exception as e:
        return {"error": str(e), "files": [], "folders": []}


def get_file(
    conn: sqlite3.Connection,
    file_id: Optional[int] = None,
    relpath: Optional[str] = None,
    cvids: Optional[set[int]] = None,
    include_content: bool = True,
    include_ast: bool = False,
) -> dict:
    """Get file details and optionally content/AST.
    
    Args:
        conn: Database connection
        file_id: File ID to retrieve
        relpath: Relative path to file (alternative to file_id)
        cvids: Set of content_version_ids to filter to
        include_content: Whether to include file content
        include_ast: Whether to include parsed AST
    
    Returns:
        Dict with file info, content, and optionally AST
    """
    if not file_id and not relpath:
        return {"error": "file_id or relpath required"}
    
    try:
        # Build CVID filter
        cvid_filter = ""
        params = []
        if cvids:
            placeholders = ",".join("?" * len(cvids))
            cvid_filter = f"AND cv.content_version_id IN ({placeholders})"
            params = list(sorted(cvids))
        
        if file_id:
            sql = f"""
                SELECT f.file_id, f.relpath, f.content_version_id,
                       mp.name as mod_name, cv.source_path
                FROM files f
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE f.file_id = ? {cvid_filter}
            """
            params = [file_id] + params
        else:
            sql = f"""
                SELECT f.file_id, f.relpath, f.content_version_id,
                       mp.name as mod_name, cv.source_path
                FROM files f
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE f.relpath = ? {cvid_filter}
            """
            params = [relpath] + params
        
        row = conn.execute(sql, params).fetchone()
        
        if not row:
            return {"error": "File not found or not in active playset"}
        
        result = {
            "fileId": row[0],
            "relpath": row[1],
            "contentVersionId": row[2],
            "mod": row[3] or "vanilla",
            "sourcePath": row[4],
        }
        
        # Get content if requested
        if include_content:
            from pathlib import Path
            source_path = row[4]
            if source_path:
                full_path = Path(source_path) / row[1]
                if full_path.exists():
                    try:
                        result["content"] = full_path.read_text(encoding="utf-8-sig")
                    except Exception as e:
                        result["content_error"] = str(e)
        
        # Get AST if requested
        if include_ast:
            ast_row = conn.execute("""
                SELECT ast_json FROM file_asts WHERE file_id = ?
            """, (row[0],)).fetchone()
            if ast_row and ast_row[0]:
                import json
                try:
                    result["ast"] = json.loads(ast_row[0])
                except Exception:
                    result["ast"] = None
        
        return result
        
    except Exception as e:
        return {"error": str(e)}


def get_top_level_folders(
    conn: sqlite3.Connection,
    cvids: Optional[set[int]] = None,
) -> dict:
    """Get top-level folders across all mods in the playset.
    
    Args:
        conn: Database connection
        cvids: Set of content_version_ids to filter to
    
    Returns:
        Dict with folders list
    """
    try:
        # Build CVID filter
        cvid_filter = ""
        params = []
        if cvids:
            placeholders = ",".join("?" * len(cvids))
            cvid_filter = f"WHERE cv.content_version_id IN ({placeholders})"
            params = list(sorted(cvids))
        
        sql = f"""
            SELECT 
                CASE 
                    WHEN INSTR(f.relpath, '/') > 0 THEN SUBSTR(f.relpath, 1, INSTR(f.relpath, '/') - 1)
                    ELSE f.relpath
                END as folder,
                COUNT(*) as file_count
            FROM files f
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            {cvid_filter}
            GROUP BY folder
            ORDER BY folder
        """
        
        folders = conn.execute(sql, params).fetchall()
        
        return {
            "folders": [
                {"name": f[0], "fileCount": f[1]}
                for f in folders
            ]
        }
        
    except Exception as e:
        return {"error": str(e), "folders": []}
