"""
AST Cache with Deduplication

Stores parsed AST keyed by (content_hash, parser_version_id).
Enables cache reuse across playsets and versions.
"""

import sqlite3
import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path

from ck3raven.db.schema import get_connection
from ck3raven.db.models import ASTRecord
from ck3raven.db.parser_version import get_current_parser_version
from ck3raven.parser import parse_file
from ck3raven.parser.parser import RootNode, BlockNode, AssignmentNode, ValueNode, ListNode

logger = logging.getLogger(__name__)


def serialize_ast(ast: RootNode) -> bytes:
    """Serialize AST to JSON bytes."""
    
    def node_to_dict(node) -> Dict[str, Any]:
        """Convert AST node to serializable dict."""
        if isinstance(node, RootNode):
            return {
                '_type': 'root',
                'filename': node.filename,
                'children': [node_to_dict(c) for c in node.children]
            }
        elif isinstance(node, BlockNode):
            return {
                '_type': 'block',
                'name': node.name,
                'operator': node.operator,
                'line': node.line,
                'column': node.column,
                'children': [node_to_dict(c) for c in node.children]
            }
        elif isinstance(node, AssignmentNode):
            return {
                '_type': 'assignment',
                'key': node.key,
                'operator': node.operator,
                'line': node.line,
                'column': node.column,
                'value': node_to_dict(node.value)
            }
        elif isinstance(node, ValueNode):
            return {
                '_type': 'value',
                'value': node.value,
                'value_type': node.value_type,
                'line': node.line,
                'column': node.column,
            }
        elif isinstance(node, ListNode):
            return {
                '_type': 'list',
                'line': node.line,
                'column': node.column,
                'items': [node_to_dict(i) for i in node.items]
            }
        else:
            return {'_type': 'unknown', 'repr': repr(node)}
    
    data = node_to_dict(ast)
    return json.dumps(data, separators=(',', ':')).encode('utf-8')


def deserialize_ast(data: bytes) -> Dict[str, Any]:
    """Deserialize AST from JSON bytes."""
    return json.loads(data.decode('utf-8'))


def count_ast_nodes(ast_dict: Dict[str, Any]) -> int:
    """Count nodes in a serialized AST."""
    count = 1
    for key in ('children', 'items', 'value'):
        if key in ast_dict:
            val = ast_dict[key]
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        count += count_ast_nodes(item)
            elif isinstance(val, dict):
                count += count_ast_nodes(val)
    return count


def get_cached_ast(
    conn: sqlite3.Connection,
    content_hash: str,
    parser_version_id: Optional[int] = None
) -> Optional[ASTRecord]:
    """
    Get cached AST for a content hash.
    
    Args:
        conn: Database connection
        content_hash: SHA256 of file content
        parser_version_id: Parser version (uses current if None)
    
    Returns:
        ASTRecord if cached, None otherwise
    """
    if parser_version_id is None:
        parser_version = get_current_parser_version(conn)
        parser_version_id = parser_version.parser_version_id
    
    row = conn.execute("""
        SELECT * FROM asts 
        WHERE content_hash = ? AND parser_version_id = ?
    """, (content_hash, parser_version_id)).fetchone()
    
    if row:
        return ASTRecord.from_row(row)
    return None


def store_ast(
    conn: sqlite3.Connection,
    content_hash: str,
    ast: RootNode,
    parser_version_id: Optional[int] = None,
    diagnostics: Optional[List[Dict[str, Any]]] = None
) -> ASTRecord:
    """
    Store AST in cache.
    
    Args:
        conn: Database connection
        content_hash: SHA256 of file content
        ast: Parsed AST
        parser_version_id: Parser version (uses current if None)
        diagnostics: Any parse warnings/notes
    
    Returns:
        ASTRecord
    """
    if parser_version_id is None:
        parser_version = get_current_parser_version(conn)
        parser_version_id = parser_version.parser_version_id
    
    # Serialize AST
    ast_blob = serialize_ast(ast)
    ast_dict = deserialize_ast(ast_blob)
    node_count = count_ast_nodes(ast_dict)
    
    diagnostics = diagnostics or []
    diagnostics_json = json.dumps(diagnostics)
    
    cursor = conn.execute("""
        INSERT OR REPLACE INTO asts 
        (content_hash, parser_version_id, ast_blob, ast_format, parse_ok, node_count, diagnostics_json)
        VALUES (?, ?, ?, 'json', 1, ?, ?)
    """, (content_hash, parser_version_id, ast_blob, node_count, diagnostics_json))
    
    conn.commit()
    
    row = conn.execute(
        "SELECT * FROM asts WHERE ast_id = ?",
        (cursor.lastrowid,)
    ).fetchone()
    
    return ASTRecord.from_row(row)


def store_parse_failure(
    conn: sqlite3.Connection,
    content_hash: str,
    error_message: str,
    parser_version_id: Optional[int] = None
) -> ASTRecord:
    """
    Store a parse failure in cache.
    
    This prevents re-attempting to parse known-bad files.
    """
    if parser_version_id is None:
        parser_version = get_current_parser_version(conn)
        parser_version_id = parser_version.parser_version_id
    
    diagnostics = [{'type': 'error', 'message': error_message}]
    diagnostics_json = json.dumps(diagnostics)
    
    # Store empty AST blob for failed parses
    empty_ast = json.dumps({'_type': 'error', 'message': error_message}).encode('utf-8')
    
    cursor = conn.execute("""
        INSERT OR REPLACE INTO asts 
        (content_hash, parser_version_id, ast_blob, ast_format, parse_ok, node_count, diagnostics_json)
        VALUES (?, ?, ?, 'json', 0, 0, ?)
    """, (content_hash, parser_version_id, empty_ast, diagnostics_json))
    
    conn.commit()
    
    row = conn.execute(
        "SELECT * FROM asts WHERE ast_id = ?",
        (cursor.lastrowid,)
    ).fetchone()
    
    return ASTRecord.from_row(row)


def parse_and_cache(
    conn: sqlite3.Connection,
    content_hash: str,
    content_text: str,
    filename: str = "<unknown>",
    force: bool = False
) -> Tuple[Optional[RootNode], ASTRecord]:
    """
    Parse content and cache the result.
    
    Args:
        conn: Database connection
        content_hash: SHA256 of content
        content_text: Text content to parse
        filename: Original filename (for error messages)
        force: Re-parse even if cached
    
    Returns:
        (AST if successful, ASTRecord)
    """
    from ck3raven.parser.parser import parse_source
    
    parser_version = get_current_parser_version(conn)
    
    # Check cache first
    if not force:
        cached = get_cached_ast(conn, content_hash, parser_version.parser_version_id)
        if cached:
            if cached.parse_ok:
                # Deserialize and reconstruct (or just return the record)
                return None, cached  # Caller can deserialize if needed
            else:
                return None, cached  # Known failure
    
    # Parse
    try:
        ast = parse_source(content_text, filename)
        record = store_ast(conn, content_hash, ast, parser_version.parser_version_id)
        return ast, record
        
    except Exception as e:
        record = store_parse_failure(conn, content_hash, str(e), parser_version.parser_version_id)
        return None, record


def parse_file_cached(
    conn: sqlite3.Connection,
    file_path: Path,
    content_hash: Optional[str] = None,
    force: bool = False
) -> Tuple[Optional[RootNode], ASTRecord]:
    """
    Parse a file with caching.
    
    Args:
        conn: Database connection
        file_path: Path to file
        content_hash: Pre-computed hash (computed if None)
        force: Re-parse even if cached
    
    Returns:
        (AST if successful, ASTRecord)
    """
    from ck3raven.db.content import compute_content_hash, detect_encoding
    
    # Read file
    data = file_path.read_bytes()
    
    if content_hash is None:
        content_hash = compute_content_hash(data)
    
    # Decode text
    encoding, is_binary = detect_encoding(data)
    if is_binary:
        # Can't parse binary files
        record = store_parse_failure(conn, content_hash, "Binary file")
        return None, record
    
    try:
        content_text = data.decode(encoding.replace('-sig', ''))
    except UnicodeDecodeError as e:
        record = store_parse_failure(conn, content_hash, f"Encoding error: {e}")
        return None, record
    
    return parse_and_cache(conn, content_hash, content_text, str(file_path), force)


def get_ast_stats(conn: sqlite3.Connection) -> Dict[str, int]:
    """Get statistics about the AST cache."""
    stats = {}
    
    row = conn.execute("SELECT COUNT(*) as cnt FROM asts").fetchone()
    stats['total'] = row['cnt']
    
    row = conn.execute("SELECT COUNT(*) as cnt FROM asts WHERE parse_ok = 1").fetchone()
    stats['successful'] = row['cnt']
    
    row = conn.execute("SELECT COUNT(*) as cnt FROM asts WHERE parse_ok = 0").fetchone()
    stats['failed'] = row['cnt']
    
    row = conn.execute("SELECT SUM(node_count) as total FROM asts WHERE parse_ok = 1").fetchone()
    stats['total_nodes'] = row['total'] or 0
    
    row = conn.execute("""
        SELECT COUNT(DISTINCT content_hash) as unique_files FROM asts
    """).fetchone()
    stats['unique_files'] = row['unique_files']
    
    return stats


def clear_ast_cache_for_parser(
    conn: sqlite3.Connection,
    parser_version_id: int
) -> int:
    """
    Clear AST cache for a specific parser version.
    
    Returns:
        Number of records deleted
    """
    cursor = conn.execute(
        "DELETE FROM asts WHERE parser_version_id = ?",
        (parser_version_id,)
    )
    conn.commit()
    return cursor.rowcount
