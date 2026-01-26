"""
Golden Join Helpers — Centralized Symbol Query Patterns

The symbols table uses ast_id only (NOT file_id or content_version_id).
To filter symbols by content version, use the Golden Join pattern:

    symbols s
    JOIN asts a ON s.ast_id = a.ast_id
    JOIN files f ON a.content_hash = f.content_hash
    JOIN content_versions cv ON f.content_version_id = cv.content_version_id

This module provides centralized helpers to prevent schema mismatches.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


# =============================================================================
# SQL FRAGMENTS
# =============================================================================

# The canonical join chain from symbols to content_versions
GOLDEN_JOIN = """
    JOIN asts a ON s.ast_id = a.ast_id
    JOIN files f ON a.content_hash = f.content_hash
    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
"""

# For refs table (also uses ast_id, same pattern)
GOLDEN_JOIN_REFS = """
    JOIN asts a ON r.ast_id = a.ast_id
    JOIN files f ON a.content_hash = f.content_hash
    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
"""


def cvid_filter_clause(cvids: list[int] | set[int] | None, table_alias: str = "cv") -> tuple[str, list[int]]:
    """
    Build a WHERE clause fragment for content version filtering.
    
    Args:
        cvids: Content version IDs to filter to, or None for no filter
        table_alias: Alias for content_versions table (default "cv")
    
    Returns:
        (sql_fragment, params) tuple
        - sql_fragment: "AND cv.content_version_id IN (?, ?, ?)" or ""
        - params: List of cvid values or empty list
    
    Example:
        clause, params = cvid_filter_clause([1, 2, 3])
        sql = f"SELECT * FROM symbols s {GOLDEN_JOIN} WHERE 1=1 {clause}"
        cursor.execute(sql, params)
    """
    if not cvids:
        return "", []
    
    cvid_list = list(cvids)
    placeholders = ", ".join("?" * len(cvid_list))
    return f"AND {table_alias}.content_version_id IN ({placeholders})", cvid_list


def build_symbol_query(
    select_cols: str = "s.*",
    where_clause: str = "1=1",
    cvids: list[int] | set[int] | None = None,
    order_by: str | None = None,
    limit: int | None = None,
) -> tuple[str, list]:
    """
    Build a complete symbol query using Golden Join.
    
    Args:
        select_cols: Column selection (default "s.*")
        where_clause: Additional WHERE conditions (default "1=1")
        cvids: Content version IDs to filter to
        order_by: ORDER BY clause (without ORDER BY keyword)
        limit: LIMIT value
    
    Returns:
        (sql, params) tuple ready for execute()
    
    Example:
        sql, params = build_symbol_query(
            select_cols="s.name, s.symbol_type",
            where_clause="s.symbol_type = ?",
            cvids=[1, 2, 3],
            limit=100,
        )
        # params will include the cvids
        all_params = ["trait"] + params  # Add your where params first
        cursor.execute(sql, all_params)
    """
    cvid_clause, cvid_params = cvid_filter_clause(cvids)
    
    sql_parts = [
        f"SELECT {select_cols}",
        "FROM symbols s",
        GOLDEN_JOIN,
        f"WHERE {where_clause}",
        cvid_clause,
    ]
    
    if order_by:
        sql_parts.append(f"ORDER BY {order_by}")
    
    if limit:
        sql_parts.append(f"LIMIT {limit}")
    
    return "\n".join(sql_parts), cvid_params


def build_refs_query(
    select_cols: str = "r.*",
    where_clause: str = "1=1",
    cvids: list[int] | set[int] | None = None,
    order_by: str | None = None,
    limit: int | None = None,
) -> tuple[str, list]:
    """
    Build a complete refs query using Golden Join.
    
    Same pattern as build_symbol_query but for refs table.
    """
    cvid_clause, cvid_params = cvid_filter_clause(cvids)
    
    sql_parts = [
        f"SELECT {select_cols}",
        "FROM refs r",
        GOLDEN_JOIN_REFS,
        f"WHERE {where_clause}",
        cvid_clause,
    ]
    
    if order_by:
        sql_parts.append(f"ORDER BY {order_by}")
    
    if limit:
        sql_parts.append(f"LIMIT {limit}")
    
    return "\n".join(sql_parts), cvid_params


def get_symbols_by_name(
    conn: "sqlite3.Connection",
    name: str,
    symbol_type: str | None = None,
    cvids: list[int] | set[int] | None = None,
    limit: int = 100,
) -> list[dict]:
    """
    Look up symbols by name with optional type and cvid filtering.
    
    This is the canonical way to check if a symbol exists.
    
    Args:
        conn: Database connection
        name: Symbol name to look up
        symbol_type: Optional type filter (trait, event, etc.)
        cvids: Optional content version filter
        limit: Max results
    
    Returns:
        List of symbol dicts with keys: symbol_id, name, symbol_type, 
        line_number, file_id, relpath, content_version_id
    """
    where_parts = ["s.name = ?"]
    params: list = [name]
    
    if symbol_type:
        where_parts.append("s.symbol_type = ?")
        params.append(symbol_type)
    
    sql, cvid_params = build_symbol_query(
        select_cols="s.symbol_id, s.name, s.symbol_type, s.line_number, f.file_id, f.relpath, cv.content_version_id",
        where_clause=" AND ".join(where_parts),
        cvids=cvids,
        limit=limit,
    )
    
    params.extend(cvid_params)
    
    rows = conn.execute(sql, params).fetchall()
    cols = ["symbol_id", "name", "symbol_type", "line_number", "file_id", "relpath", "content_version_id"]
    return [dict(zip(cols, row)) for row in rows]


def symbol_exists(
    conn: "sqlite3.Connection",
    name: str,
    symbol_type: str | None = None,
    cvids: list[int] | set[int] | None = None,
) -> bool:
    """
    Check if a symbol exists in the database.
    
    Args:
        conn: Database connection
        name: Symbol name
        symbol_type: Optional type filter
        cvids: Optional content version filter
    
    Returns:
        True if symbol exists, False otherwise
    """
    results = get_symbols_by_name(conn, name, symbol_type, cvids, limit=1)
    return len(results) > 0
