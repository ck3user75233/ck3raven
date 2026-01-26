"""
Search Operations Implementation

Shared implementation module for search operations.
Used by both MCP server (server.py) and VS Code extension bridge.

This module provides database search functions that take explicit parameters,
avoiding reliance on global state or playset_mods table (BANNED).

Architecture:
- Takes database connection and CVID list as parameters
- CVIDs are obtained from playset_ops.get_playset_mods()
- Both MCP and bridge call with their own connection/CVID context
"""
from __future__ import annotations

import sqlite3
from typing import Optional


def escape_fts_query(query: str) -> str:
    """Escape special characters for FTS5 queries.
    
    Args:
        query: Raw search query
    
    Returns:
        Escaped query safe for FTS5 MATCH
    """
    # Escape double quotes
    query = query.replace('"', '""')
    terms = query.split()
    if not terms:
        return ''
    if len(terms) == 1:
        # Single term: use prefix match for autocomplete
        return f'"{terms[0]}"*'
    # Multiple terms: OR them together
    escaped = ' OR '.join(f'"{t}"*' for t in terms)
    return escaped


def search_symbols(
    conn: sqlite3.Connection,
    query: str,
    cvids: Optional[set[int]] = None,
    symbol_type: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Search for symbols in the database.
    
    Uses FTS5 search on symbols_fts table, filtered to provided CVIDs.
    Uses Golden Join pattern: symbols → asts → files → content_versions
    
    Args:
        conn: Database connection
        query: Search query (will be escaped for FTS5)
        cvids: Set of content_version_ids to filter to (None = no filter)
        symbol_type: Filter by symbol type (trait, event, etc.)
        limit: Maximum results to return
    
    Returns:
        Dict with results list, adjacencies, and query patterns
    """
    if not query.strip():
        return {"results": [], "adjacencies": [], "query_patterns": [query]}
    
    try:
        fts_query = escape_fts_query(query)
        
        # Build SQL with CVID filtering using Golden Join
        # GOLDEN JOIN: symbols → asts → files → content_versions
        sql = """
            SELECT s.symbol_id, s.name, s.symbol_type, s.scope,
                   s.line_number, f.relpath, cv.content_version_id,
                   mp.name as mod_name, rank
            FROM symbols_fts fts
            JOIN symbols s ON s.symbol_id = fts.rowid
            JOIN asts a ON s.ast_id = a.ast_id
            LEFT JOIN files f ON a.content_hash = f.content_hash
            LEFT JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE symbols_fts MATCH ?
        """
        params_list = [fts_query]
        
        # Filter by CVIDs (from playset_ops, NOT playset_mods table)
        if cvids:
            placeholders = ",".join("?" * len(cvids))
            sql += f" AND cv.content_version_id IN ({placeholders})"
            params_list.extend(sorted(cvids))
        
        # Filter by symbol type if specified
        if symbol_type:
            sql += " AND s.symbol_type = ?"
            params_list.append(symbol_type)
        
        sql += " ORDER BY rank LIMIT ?"
        params_list.append(limit)
        
        rows = conn.execute(sql, params_list).fetchall()
        
        results = []
        for r in rows:
            results.append({
                "symbolId": r[0],
                "name": r[1],
                "symbolType": r[2],
                "scope": r[3],
                "line": r[4],
                "relpath": r[5],
                "contentVersionId": r[6],
                "mod": r[7] or "vanilla",
                "relevance": -r[8] if r[8] else 0
            })
        
        return {
            "results": results,
            "adjacencies": [],  # TODO: Implement fuzzy/adjacent matches
            "query_patterns": [query, fts_query]
        }
        
    except Exception as e:
        return {
            "results": [],
            "adjacencies": [],
            "query_patterns": [query],
            "error": str(e)
        }


def confirm_not_exists(
    conn: sqlite3.Connection,
    name: str,
    cvids: Optional[set[int]] = None,
    symbol_type: Optional[str] = None,
) -> dict:
    """Exhaustive search to confirm something doesn't exist.
    
    Performs a thorough search to prevent false negatives when
    claiming a symbol doesn't exist.
    Uses Golden Join pattern: symbols → asts → files → content_versions
    
    Args:
        conn: Database connection
        name: Symbol name to search for
        cvids: Set of content_version_ids to filter to
        symbol_type: Filter by symbol type
    
    Returns:
        Dict with can_claim_not_exists and similar_matches
    """
    if not name:
        return {"can_claim_not_exists": False, "similar_matches": []}
    
    try:
        # 1. Exact match search using Golden Join
        sql = """
            SELECT s.name, s.symbol_type, mp.name as mod_name
            FROM symbols s
            JOIN asts a ON s.ast_id = a.ast_id
            LEFT JOIN files f ON a.content_hash = f.content_hash
            LEFT JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE s.name = ?
        """
        params_list = [name]
        
        if cvids:
            placeholders = ",".join("?" * len(cvids))
            sql += f" AND cv.content_version_id IN ({placeholders})"
            params_list.extend(sorted(cvids))
        
        if symbol_type:
            sql += " AND s.symbol_type = ?"
            params_list.append(symbol_type)
        
        sql += " LIMIT 10"
        
        exact_matches = conn.execute(sql, params_list).fetchall()
        
        if exact_matches:
            return {
                "can_claim_not_exists": False,
                "found": True,
                "exact_matches": [
                    {"name": m[0], "type": m[1], "mod": m[2] or "vanilla"}
                    for m in exact_matches
                ],
                "similar_matches": []
            }
        
        # 2. Similar match search (fuzzy) using Golden Join
        fuzzy_sql = """
            SELECT DISTINCT s.name, s.symbol_type, mp.name as mod_name
            FROM symbols s
            JOIN asts a ON s.ast_id = a.ast_id
            LEFT JOIN files f ON a.content_hash = f.content_hash
            LEFT JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE s.name LIKE ?
        """
        fuzzy_params = [f"%{name}%"]
        
        if cvids:
            placeholders = ",".join("?" * len(cvids))
            fuzzy_sql += f" AND cv.content_version_id IN ({placeholders})"
            fuzzy_params.extend(sorted(cvids))
        
        if symbol_type:
            fuzzy_sql += " AND s.symbol_type = ?"
            fuzzy_params.append(symbol_type)
        
        fuzzy_sql += " LIMIT 20"
        
        similar = conn.execute(fuzzy_sql, fuzzy_params).fetchall()
        
        return {
            "can_claim_not_exists": True,
            "found": False,
            "exact_matches": [],
            "similar_matches": [
                {"name": m[0], "type": m[1], "mod": m[2] or "vanilla"}
                for m in similar
            ]
        }
        
    except Exception as e:
        return {
            "can_claim_not_exists": False,
            "error": str(e),
            "similar_matches": []
        }
