"""
Search Infrastructure

Context-aware search across content, symbols, and references.
Uses SQLite FTS5 for full-text search with ranking.
"""

import sqlite3
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum

from ck3raven.db.models import Symbol, Reference, FileRecord


class SearchScope(Enum):
    """Search scope options."""
    ALL = "all"
    SYMBOLS = "symbols"
    REFS = "refs"
    CONTENT = "content"


@dataclass
class SearchResult:
    """A search result with context."""
    kind: str  # 'symbol', 'ref', 'content'
    name: str
    file_path: str
    line: Optional[int]
    snippet: str
    relevance: float
    metadata: Dict[str, Any]


def escape_fts_query(query: str) -> str:
    """Escape special characters for FTS5 queries."""
    # FTS5 special chars: " * ^ - OR AND NOT ( )
    # Escape quotes and wrap terms
    query = query.replace('"', '""')
    
    # Split into terms and wrap each
    terms = query.split()
    if len(terms) == 1:
        return f'"{terms[0]}"' if terms else ''
    
    # Multiple terms: OR them together
    escaped = ' OR '.join(f'"{t}"' for t in terms if t)
    return escaped


def search_symbols(
    conn: sqlite3.Connection,
    query: str,
    symbol_type: Optional[str] = None,
    content_version_id: Optional[int] = None,
    limit: int = 50
) -> List[SearchResult]:
    """
    Search for symbols using FTS.
    
    Args:
        conn: Database connection
        query: Search query
        symbol_type: Filter by symbol type (e.g., 'event', 'trait')
        content_version_id: Filter by content version
        limit: Maximum results
    
    Returns:
        List of SearchResult
    """
    fts_query = escape_fts_query(query)
    if not fts_query:
        return []
    
    sql = """
        SELECT s.*, f.relpath, rank
        FROM symbols_fts fts
        JOIN symbols s ON s.symbol_id = fts.rowid
        LEFT JOIN files f ON s.defining_file_id = f.file_id
        WHERE symbols_fts MATCH ?
    """
    params: List[Any] = [fts_query]
    
    if symbol_type:
        sql += " AND s.symbol_type = ?"
        params.append(symbol_type)
    
    if content_version_id:
        sql += " AND s.content_version_id = ?"
        params.append(content_version_id)
    
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    
    results = []
    for row in conn.execute(sql, params):
        results.append(SearchResult(
            kind='symbol',
            name=row['name'],
            file_path=row['relpath'] or '',
            line=row['line_number'],
            snippet=f"{row['symbol_type']}: {row['name']}",
            relevance=-row['rank'],  # FTS5 rank is negative, lower is better
            metadata={
                'symbol_id': row['symbol_id'],
                'symbol_type': row['symbol_type'],
                'scope': row['scope'],
            }
        ))
    
    return results


def search_refs(
    conn: sqlite3.Connection,
    query: str,
    ref_type: Optional[str] = None,
    content_version_id: Optional[int] = None,
    limit: int = 50
) -> List[SearchResult]:
    """
    Search for references using FTS.
    
    Args:
        conn: Database connection
        query: Search query
        ref_type: Filter by reference type
        content_version_id: Filter by content version
        limit: Maximum results
    
    Returns:
        List of SearchResult
    """
    fts_query = escape_fts_query(query)
    if not fts_query:
        return []
    
    sql = """
        SELECT r.*, f.relpath, rank
        FROM refs_fts fts
        JOIN refs r ON r.ref_id = fts.rowid
        LEFT JOIN files f ON r.using_file_id = f.file_id
        WHERE refs_fts MATCH ?
    """
    params: List[Any] = [fts_query]
    
    if ref_type:
        sql += " AND r.ref_type = ?"
        params.append(ref_type)
    
    if content_version_id:
        sql += " AND r.content_version_id = ?"
        params.append(content_version_id)
    
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    
    results = []
    for row in conn.execute(sql, params):
        results.append(SearchResult(
            kind='ref',
            name=row['name'],
            file_path=row['relpath'] or '',
            line=row['line_number'],
            snippet=f"{row['ref_type']} -> {row['name']} ({row['context']})",
            relevance=-row['rank'],
            metadata={
                'ref_id': row['ref_id'],
                'ref_type': row['ref_type'],
                'context': row['context'],
                'resolution_status': row['resolution_status'],
            }
        ))
    
    return results


def search_content(
    conn: sqlite3.Connection,
    query: str,
    file_type: Optional[str] = None,
    content_version_id: Optional[int] = None,
    limit: int = 50
) -> List[SearchResult]:
    """
    Search file content using FTS.
    
    Args:
        conn: Database connection
        query: Search query
        file_type: Filter by file type ('script', 'localization', etc.)
        content_version_id: Filter by content version
        limit: Maximum results
    
    Returns:
        List of SearchResult
    """
    fts_query = escape_fts_query(query)
    if not fts_query:
        return []
    
    # Join through files to get relpath
    sql = """
        SELECT fc.content_hash, fc.content_text, f.relpath, f.file_type, 
               f.content_version_id, rank
        FROM file_content_fts fts
        JOIN file_contents fc ON fc.rowid = fts.rowid
        JOIN files f ON f.content_hash = fc.content_hash
        WHERE file_content_fts MATCH ?
    """
    params: List[Any] = [fts_query]
    
    if file_type:
        sql += " AND f.file_type = ?"
        params.append(file_type)
    
    if content_version_id:
        sql += " AND f.content_version_id = ?"
        params.append(content_version_id)
    
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    
    results = []
    seen_files = set()  # Dedupe by file path
    
    for row in conn.execute(sql, params):
        if row['relpath'] in seen_files:
            continue
        seen_files.add(row['relpath'])
        
        # Extract snippet around match
        content = row['content_text'] or ''
        snippet = extract_snippet(content, query, max_length=150)
        
        results.append(SearchResult(
            kind='content',
            name=row['relpath'],
            file_path=row['relpath'] or '',
            line=None,  # FTS doesn't give line numbers
            snippet=snippet,
            relevance=-row['rank'],
            metadata={
                'content_hash': row['content_hash'],
                'file_type': row['file_type'],
            }
        ))
    
    return results


def extract_snippet(content: str, query: str, max_length: int = 150) -> str:
    """Extract a snippet around the first occurrence of query terms."""
    content = content.replace('\r', '')
    
    # Find first occurrence of any query term
    terms = query.lower().split()
    content_lower = content.lower()
    
    first_pos = len(content)
    for term in terms:
        pos = content_lower.find(term)
        if pos >= 0 and pos < first_pos:
            first_pos = pos
    
    if first_pos == len(content):
        # No match found, return beginning
        first_pos = 0
    
    # Extract window around match
    start = max(0, first_pos - max_length // 3)
    end = min(len(content), first_pos + max_length * 2 // 3)
    
    snippet = content[start:end]
    
    # Clean up
    if start > 0:
        snippet = '...' + snippet.lstrip()
    if end < len(content):
        snippet = snippet.rstrip() + '...'
    
    # Replace newlines with spaces for single-line display
    snippet = ' '.join(snippet.split())
    
    return snippet


def search_all(
    conn: sqlite3.Connection,
    query: str,
    scope: SearchScope = SearchScope.ALL,
    content_version_id: Optional[int] = None,
    limit: int = 50
) -> List[SearchResult]:
    """
    Search across all scopes.
    
    Args:
        conn: Database connection
        query: Search query
        scope: Which areas to search
        content_version_id: Filter by content version
        limit: Maximum results per scope
    
    Returns:
        Combined list of SearchResult, sorted by relevance
    """
    results = []
    
    if scope in (SearchScope.ALL, SearchScope.SYMBOLS):
        results.extend(search_symbols(conn, query, content_version_id=content_version_id, limit=limit))
    
    if scope in (SearchScope.ALL, SearchScope.REFS):
        results.extend(search_refs(conn, query, content_version_id=content_version_id, limit=limit))
    
    if scope in (SearchScope.ALL, SearchScope.CONTENT):
        results.extend(search_content(conn, query, content_version_id=content_version_id, limit=limit))
    
    # Sort by relevance (higher is better)
    results.sort(key=lambda r: r.relevance, reverse=True)
    
    return results[:limit]


def find_definition(
    conn: sqlite3.Connection,
    name: str,
    symbol_type: Optional[str] = None
) -> List[SearchResult]:
    """
    Find the definition(s) of a symbol by exact name.
    
    Args:
        conn: Database connection
        name: Exact symbol name
        symbol_type: Optional type filter
    
    Returns:
        List of SearchResult for matching definitions
    """
    sql = """
        SELECT s.*, f.relpath
        FROM symbols s
        LEFT JOIN files f ON s.defining_file_id = f.file_id
        WHERE s.name = ?
    """
    params: List[Any] = [name]
    
    if symbol_type:
        sql += " AND s.symbol_type = ?"
        params.append(symbol_type)
    
    results = []
    for row in conn.execute(sql, params):
        results.append(SearchResult(
            kind='symbol',
            name=row['name'],
            file_path=row['relpath'] or '',
            line=row['line_number'],
            snippet=f"{row['symbol_type']}: {row['name']}",
            relevance=1.0,
            metadata={
                'symbol_id': row['symbol_id'],
                'symbol_type': row['symbol_type'],
                'scope': row['scope'],
            }
        ))
    
    return results


def find_references(
    conn: sqlite3.Connection,
    name: str,
    ref_type: Optional[str] = None
) -> List[SearchResult]:
    """
    Find all references to a symbol by exact name.
    
    Args:
        conn: Database connection
        name: Exact symbol name being referenced
        ref_type: Optional type filter
    
    Returns:
        List of SearchResult for matching references
    """
    sql = """
        SELECT r.*, f.relpath
        FROM refs r
        LEFT JOIN files f ON r.using_file_id = f.file_id
        WHERE r.name = ?
    """
    params: List[Any] = [name]
    
    if ref_type:
        sql += " AND r.ref_type = ?"
        params.append(ref_type)
    
    results = []
    for row in conn.execute(sql, params):
        results.append(SearchResult(
            kind='ref',
            name=row['name'],
            file_path=row['relpath'] or '',
            line=row['line_number'],
            snippet=f"{row['ref_type']} -> {row['name']} in {row['context']}",
            relevance=1.0,
            metadata={
                'ref_id': row['ref_id'],
                'ref_type': row['ref_type'],
                'context': row['context'],
            }
        ))
    
    return results


def get_search_stats(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Get statistics about searchable content."""
    stats = {}
    
    # Symbols
    row = conn.execute("SELECT COUNT(*) as cnt FROM symbols").fetchone()
    stats['total_symbols'] = row['cnt']
    
    # Refs
    row = conn.execute("SELECT COUNT(*) as cnt FROM refs").fetchone()
    stats['total_refs'] = row['cnt']
    
    # Files with content
    row = conn.execute("SELECT COUNT(*) as cnt FROM file_contents").fetchone()
    stats['indexed_files'] = row['cnt']
    
    return stats
