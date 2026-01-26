"""
Conflict Operations Implementation

Shared implementation module for conflict detection.
Used by both MCP server (server.py) and VS Code extension bridge.

This module provides conflict detection functions that take explicit parameters,
avoiding reliance on global state or playset_mods table (BANNED).

Architecture:
- Takes database connection and CVID list as parameters
- CVIDs are obtained from playset_ops.get_playset_mods()
- Both MCP and bridge call with their own connection/CVID context
"""
from __future__ import annotations

import sqlite3
from typing import Optional


def get_file_conflicts(
    conn: sqlite3.Connection,
    cvids: Optional[set[int]] = None,
    path_pattern: str = "%",
    limit: int = 100,
) -> dict:
    """Get file-level conflicts (same relpath from multiple mods).
    
    Conflicts occur when multiple mods define the same file path.
    The mod loaded last wins (last in the cvids list or by load order).
    
    Args:
        conn: Database connection
        cvids: Set of content_version_ids to filter to
        path_pattern: SQL LIKE pattern for file paths
        limit: Maximum conflicts to return
    
    Returns:
        Dict with conflicts list
    """
    try:
        # Build CVID filter
        cvid_filter = ""
        params = []
        if cvids:
            placeholders = ",".join("?" * len(cvids))
            cvid_filter = f"AND cv.content_version_id IN ({placeholders})"
            params = list(sorted(cvids))
        
        # Find files that exist in multiple content versions
        sql = f"""
            SELECT f.relpath, 
                   GROUP_CONCAT(
                       COALESCE(mp.name, 'vanilla') || ':' || cv.content_version_id, 
                       '|'
                   ) as sources,
                   COUNT(*) as source_count
            FROM files f
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE f.relpath LIKE ? {cvid_filter}
            GROUP BY f.relpath
            HAVING COUNT(*) > 1
            ORDER BY f.relpath
            LIMIT ?
        """
        params = [path_pattern] + params + [limit]
        
        conflicts = conn.execute(sql, params).fetchall()
        
        result_conflicts = []
        for c in conflicts:
            sources = c[1].split('|')
            # Parse mod:cvid pairs
            parsed = []
            for s in sources:
                parts = s.rsplit(':', 1)
                if len(parts) == 2:
                    mod_name = parts[0]
                    cvid = int(parts[1])
                    parsed.append({
                        "mod": mod_name,
                        "contentVersionId": cvid
                    })
            
            # Sort by cvid (higher = later = winner for typical load order)
            parsed.sort(key=lambda x: -x["contentVersionId"])
            
            if len(parsed) >= 2:
                result_conflicts.append({
                    "relpath": c[0],
                    "winner": parsed[0],
                    "losers": parsed[1:]
                })
        
        return {"conflicts": result_conflicts}
        
    except Exception as e:
        return {"error": str(e), "conflicts": []}


def get_symbol_conflicts(
    conn: sqlite3.Connection,
    cvids: Optional[set[int]] = None,
    symbol_type: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """Get symbol-level conflicts (same symbol defined by multiple mods).
    
    Uses Golden Join pattern: symbols → asts → files → content_versions
    
    Args:
        conn: Database connection
        cvids: Set of content_version_ids to filter to
        symbol_type: Filter by symbol type (trait, event, etc.)
        limit: Maximum conflicts to return
    
    Returns:
        Dict with conflicts list
    """
    try:
        # Build filters
        cvid_filter = ""
        type_filter = ""
        params = []
        
        if cvids:
            placeholders = ",".join("?" * len(cvids))
            cvid_filter = f"AND cv.content_version_id IN ({placeholders})"
            params = list(sorted(cvids))
        
        if symbol_type:
            type_filter = "AND s.symbol_type = ?"
        
        # GOLDEN JOIN: symbols → asts → files → content_versions
        sql = f"""
            SELECT s.name, s.symbol_type,
                   GROUP_CONCAT(
                       COALESCE(mp.name, 'vanilla') || ':' || cv.content_version_id,
                       '|'
                   ) as sources,
                   COUNT(*) as source_count
            FROM symbols s
            JOIN asts a ON s.ast_id = a.ast_id
            JOIN files f ON a.content_hash = f.content_hash
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE 1=1 {cvid_filter} {type_filter}
            GROUP BY s.name, s.symbol_type
            HAVING COUNT(DISTINCT cv.content_version_id) > 1
            ORDER BY s.name
            LIMIT ?
        """
        
        final_params = params
        if symbol_type:
            final_params = params + [symbol_type]
        final_params = final_params + [limit]
        
        conflicts = conn.execute(sql, final_params).fetchall()
        
        result_conflicts = []
        for c in conflicts:
            sources = c[2].split('|') if c[2] else []
            # Parse mod:cvid pairs
            parsed = []
            seen = set()
            for s in sources:
                parts = s.rsplit(':', 1)
                if len(parts) == 2:
                    mod_name = parts[0]
                    cvid = int(parts[1])
                    key = (mod_name, cvid)
                    if key not in seen:
                        seen.add(key)
                        parsed.append({
                            "mod": mod_name,
                            "contentVersionId": cvid
                        })
            
            # Sort by cvid
            parsed.sort(key=lambda x: -x["contentVersionId"])
            
            if len(parsed) >= 2:
                result_conflicts.append({
                    "name": c[0],
                    "symbolType": c[1],
                    "winner": parsed[0],
                    "losers": parsed[1:]
                })
        
        return {"conflicts": result_conflicts}
        
    except Exception as e:
        return {"error": str(e), "conflicts": []}


def get_conflict_summary(
    conn: sqlite3.Connection,
    cvids: Optional[set[int]] = None,
) -> dict:
    """Get summary of conflicts in the playset.
    
    Args:
        conn: Database connection
        cvids: Set of content_version_ids to filter to
    
    Returns:
        Dict with conflict counts by type
    """
    try:
        file_result = get_file_conflicts(conn, cvids, "%", 1000)
        symbol_result = get_symbol_conflicts(conn, cvids, None, 1000)
        
        file_conflicts = file_result.get("conflicts", [])
        symbol_conflicts = symbol_result.get("conflicts", [])
        
        # Count symbol conflicts by type
        by_type = {}
        for c in symbol_conflicts:
            t = c.get("symbolType", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        
        # Count file conflicts by folder
        by_folder = {}
        for c in file_conflicts:
            relpath = c.get("relpath", "")
            if "/" in relpath:
                folder = relpath.split("/")[0]
            else:
                folder = "(root)"
            by_folder[folder] = by_folder.get(folder, 0) + 1
        
        return {
            "total_file_conflicts": len(file_conflicts),
            "total_symbol_conflicts": len(symbol_conflicts),
            "by_symbol_type": by_type,
            "by_folder": by_folder,
        }
        
    except Exception as e:
        return {"error": str(e)}
