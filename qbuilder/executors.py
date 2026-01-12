"""
QBuilder Step Executors - Functions that execute each processing step.

Each executor function takes (conn, work_item) and performs one step.
Executors are registered with the Worker.

Schema v4 column names:
- symbols: file_id, ast_id, content_version_id, column_number
- refs: file_id, ast_id, content_version_id, column_number
- localization_entries: file_id, content_version_id
"""

from __future__ import annotations
import sqlite3
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qbuilder.worker import WorkItem


def get_file_content(conn: sqlite3.Connection, content_hash: str) -> str | None:
    """Get file content from file_contents table."""
    row = conn.execute(
        "SELECT content_text FROM file_contents WHERE content_hash = ?",
        (content_hash,)
    ).fetchone()
    return row["content_text"] if row else None


def get_file_absolute_path(conn: sqlite3.Connection, file_id: int) -> Path | None:
    """Get absolute path for a file by looking up content_version root."""
    row = conn.execute("""
        SELECT cv.root_path, f.relpath
        FROM files f
        JOIN content_versions cv ON f.content_version_id = cv.content_version_id
        WHERE f.file_id = ?
    """, (file_id,)).fetchone()
    
    if row and row["root_path"]:
        return Path(row["root_path"]) / row["relpath"]
    return None


def get_ast_for_file(conn: sqlite3.Connection, content_hash: str) -> tuple[dict | None, int | None]:
    """Get parsed AST dict and ast_id for a file by content_hash."""
    row = conn.execute(
        "SELECT ast_id, ast_blob FROM asts WHERE content_hash = ?",
        (content_hash,)
    ).fetchone()
    
    if row is None or row["ast_blob"] is None:
        return None, None
    
    return json.loads(row["ast_blob"]), row["ast_id"]


def get_content_version_id(conn: sqlite3.Connection, file_id: int) -> int | None:
    """Get content_version_id for a file."""
    row = conn.execute(
        "SELECT content_version_id FROM files WHERE file_id = ?",
        (file_id,)
    ).fetchone()
    return row["content_version_id"] if row else None


# =============================================================================
# Step Executors
# =============================================================================

def execute_ingest(conn: sqlite3.Connection, item: WorkItem) -> None:
    """
    INGEST step: Ensure file content is in file_contents table.
    
    For fresh builds, content should already be there from discovery.
    This step verifies it exists and content_hash matches.
    """
    row = conn.execute(
        "SELECT content_hash FROM file_contents WHERE content_hash = ?",
        (item.content_hash,)
    ).fetchone()
    
    if row is None:
        # Content not found - need to read from disk
        abs_path = get_file_absolute_path(conn, item.file_id)
        if abs_path is None or not abs_path.exists():
            raise FileNotFoundError(f"Cannot find file for ingest: {item.relpath}")
        
        content = abs_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        
        # Verify hash matches
        if content_hash != item.content_hash:
            raise ValueError(f"Content hash mismatch for {item.relpath}")
        
        # Insert content
        try:
            text = content.decode('utf-8-sig')
            is_binary = 0
        except UnicodeDecodeError:
            text = None
            is_binary = 1
        
        conn.execute("""
            INSERT OR IGNORE INTO file_contents 
                (content_hash, content_blob, content_text, size, is_binary)
            VALUES (?, ?, ?, ?, ?)
        """, (content_hash, content, text, len(content), is_binary))


def execute_parse(conn: sqlite3.Connection, item: WorkItem) -> None:
    """
    PARSE step: Parse file content into AST.
    
    Stores AST in asts table keyed by content_hash.
    Skips if AST already exists for this content_hash.
    """
    from ck3raven.parser import parse_source
    
    # Check if AST already exists
    row = conn.execute(
        "SELECT ast_id FROM asts WHERE content_hash = ?",
        (item.content_hash,)
    ).fetchone()
    
    if row is not None:
        return  # Already parsed
    
    # Get content
    content = get_file_content(conn, item.content_hash)
    if content is None:
        raise ValueError(f"No content for {item.relpath}")
    
    # Parse
    try:
        ast = parse_source(content, filename=item.relpath)
        ast_blob = ast.to_json().encode('utf-8')
        parse_error = None
    except Exception as e:
        ast_blob = None
        parse_error = str(e)
    
    # Store AST
    conn.execute("""
        INSERT OR REPLACE INTO asts 
            (content_hash, ast_blob, parse_error, parser_version)
        VALUES (?, ?, ?, ?)
    """, (item.content_hash, ast_blob, parse_error, "1.0"))


def execute_symbols(conn: sqlite3.Connection, item: WorkItem) -> None:
    """
    SYMBOLS step: Extract symbol definitions from AST.
    
    Uses new schema v4 column names: file_id, ast_id, content_version_id, column_number
    """
    from ck3raven.db.symbols import extract_symbols_from_ast
    
    # Check if symbols already extracted for this file
    row = conn.execute(
        "SELECT 1 FROM symbols WHERE file_id = ? LIMIT 1",
        (item.file_id,)
    ).fetchone()
    
    if row is not None:
        return  # Already extracted
    
    # Get AST and ast_id
    ast_dict, ast_id = get_ast_for_file(conn, item.content_hash)
    if ast_dict is None:
        return  # No AST available (parse error)
    
    # Get content_version_id
    content_version_id = get_content_version_id(conn, item.file_id)
    if content_version_id is None:
        return  # No content_version
    
    # Extract symbols
    symbols = list(extract_symbols_from_ast(ast_dict, item.relpath, item.content_hash))
    
    if symbols:
        # Store symbols with new column names
        for sym in symbols:
            conn.execute("""
                INSERT OR IGNORE INTO symbols 
                    (file_id, content_version_id, ast_id, line_number, column_number,
                     symbol_type, name, scope, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.file_id,
                content_version_id,
                ast_id,
                sym.line,
                sym.column,  # NEW: column_number
                sym.kind,
                sym.name,
                sym.scope,
                json.dumps({"signature": sym.signature, "doc": sym.doc}) if sym.signature or sym.doc else None
            ))


def execute_refs(conn: sqlite3.Connection, item: WorkItem) -> None:
    """
    REFS step: Extract symbol references from AST.
    
    Uses new schema v4 column names: file_id, ast_id, content_version_id, column_number
    """
    from ck3raven.db.symbols import extract_refs_from_ast
    
    # Check if refs already extracted for this file
    row = conn.execute(
        "SELECT 1 FROM refs WHERE file_id = ? LIMIT 1",
        (item.file_id,)
    ).fetchone()
    
    if row is not None:
        return  # Already extracted
    
    # Get AST and ast_id
    ast_dict, ast_id = get_ast_for_file(conn, item.content_hash)
    if ast_dict is None:
        return  # No AST available
    
    # Get content_version_id
    content_version_id = get_content_version_id(conn, item.file_id)
    if content_version_id is None:
        return  # No content_version
    
    # Extract refs
    refs = list(extract_refs_from_ast(ast_dict, item.relpath, item.content_hash))
    
    if refs:
        # Store refs with new column names
        for ref in refs:
            conn.execute("""
                INSERT OR IGNORE INTO refs 
                    (file_id, content_version_id, ast_id, line_number, column_number,
                     ref_type, name, context, resolution_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unknown')
            """, (
                item.file_id,
                content_version_id,
                ast_id,
                ref.line,
                ref.column,  # NEW: column_number
                ref.kind,
                ref.name,
                ref.context
            ))


def execute_localization(conn: sqlite3.Connection, item: WorkItem) -> None:
    """
    LOCALIZATION step: Parse YML localization file.
    
    Extracts localization keys and stores them in localization_entries table.
    Uses new schema v4: file_id, content_version_id (not content_hash)
    """
    import re
    
    # Check if already parsed
    row = conn.execute(
        "SELECT 1 FROM localization_entries WHERE file_id = ? LIMIT 1",
        (item.file_id,)
    ).fetchone()
    
    if row is not None:
        return  # Already parsed
    
    # Get content
    content = get_file_content(conn, item.content_hash)
    if content is None:
        return
    
    # Get content_version_id
    content_version_id = get_content_version_id(conn, item.file_id)
    if content_version_id is None:
        return
    
    # Detect language from path (e.g., localization/english/...)
    relpath_lower = item.relpath.replace('\\', '/').lower()
    language = 'english'  # default
    for lang in ['english', 'german', 'french', 'spanish', 'russian', 'korean', 'simp_chinese', 'braz_por']:
        if f'/{lang}/' in relpath_lower or f'\\{lang}\\' in relpath_lower:
            language = lang
            break
    
    # Simple YAML localization parser
    # Format: key:0 "value" or key:1 "value"
    entries = []
    line_num = 0
    for line in content.split('\n'):
        line_num += 1
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith('#'):
            continue
        
        # Match localization entries: key:N "value"
        match = re.match(r'^([a-zA-Z0-9_\.]+):(\d+)\s+"(.*)"\s*$', line_stripped)
        if match:
            key = match.group(1)
            version = int(match.group(2))
            value = match.group(3)
            entries.append((
                item.file_id,
                content_version_id,
                line_num,
                language,
                key,
                version,
                value,
                value  # plain_text (could strip formatting codes later)
            ))
    
    if entries:
        conn.executemany("""
            INSERT OR IGNORE INTO localization_entries 
                (file_id, content_version_id, line_number, language, loc_key, version, raw_value, plain_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, entries)


def execute_lookup_traits(conn: sqlite3.Connection, item: WorkItem) -> None:
    """LOOKUP_TRAITS step: Build trait lookup entries from symbols."""
    # Get trait symbols defined in this file (using new column name: file_id)
    rows = conn.execute("""
        SELECT symbol_id, name, line_number
        FROM symbols 
        WHERE file_id = ? AND symbol_type = 'trait'
    """, (item.file_id,)).fetchall()
    
    for row in rows:
        conn.execute("""
            INSERT OR IGNORE INTO trait_lookups 
                (symbol_id, trait_name, file_id)
            VALUES (?, ?, ?)
        """, (row["symbol_id"], row["name"], item.file_id))


def execute_lookup_events(conn: sqlite3.Connection, item: WorkItem) -> None:
    """LOOKUP_EVENTS step: Build event lookup entries from symbols."""
    # Get event symbols defined in this file
    rows = conn.execute("""
        SELECT symbol_id, name, line_number
        FROM symbols 
        WHERE file_id = ? AND symbol_type = 'event'
    """, (item.file_id,)).fetchall()
    
    for row in rows:
        conn.execute("""
            INSERT OR IGNORE INTO event_lookups 
                (symbol_id, event_id, file_id)
            VALUES (?, ?, ?)
        """, (row["symbol_id"], row["name"], item.file_id))


def execute_lookup_decisions(conn: sqlite3.Connection, item: WorkItem) -> None:
    """LOOKUP_DECISIONS step: Build decision lookup entries from symbols."""
    # Get decision symbols defined in this file
    rows = conn.execute("""
        SELECT symbol_id, name, line_number
        FROM symbols 
        WHERE file_id = ? AND symbol_type = 'decision'
    """, (item.file_id,)).fetchall()
    
    for row in rows:
        conn.execute("""
            INSERT OR IGNORE INTO decision_lookups 
                (symbol_id, decision_id, file_id)
            VALUES (?, ?, ?)
        """, (row["symbol_id"], row["name"], item.file_id))


def execute_lookup_dynasties(conn: sqlite3.Connection, item: WorkItem) -> None:
    """LOOKUP_DYNASTIES step: Build dynasty lookup entries."""
    # TODO: Implement dynasty lookups
    pass


def execute_lookup_characters(conn: sqlite3.Connection, item: WorkItem) -> None:
    """LOOKUP_CHARACTERS step: Build character lookup entries."""
    # TODO: Implement character lookups
    pass


def execute_lookup_titles(conn: sqlite3.Connection, item: WorkItem) -> None:
    """LOOKUP_TITLES step: Build title lookup entries."""
    # Get title symbols defined in this file
    rows = conn.execute("""
        SELECT symbol_id, name, line_number
        FROM symbols 
        WHERE file_id = ? AND symbol_type = 'title'
    """, (item.file_id,)).fetchall()
    
    for row in rows:
        conn.execute("""
            INSERT OR IGNORE INTO title_lookups 
                (symbol_id, title_id, file_id)
            VALUES (?, ?, ?)
        """, (row["symbol_id"], row["name"], item.file_id))


def execute_lookup_provinces(conn: sqlite3.Connection, item: WorkItem) -> None:
    """LOOKUP_PROVINCES step: Build province lookup entries."""
    # TODO: Implement province lookups
    pass


def execute_lookup_holy_sites(conn: sqlite3.Connection, item: WorkItem) -> None:
    """LOOKUP_HOLY_SITES step: Build holy site lookup entries."""
    # TODO: Implement holy site lookups
    pass


# =============================================================================
# Executor Registry
# =============================================================================

EXECUTORS = {
    "INGEST": execute_ingest,
    "PARSE": execute_parse,
    "SYMBOLS": execute_symbols,
    "REFS": execute_refs,
    "LOCALIZATION": execute_localization,
    "LOOKUP_TRAITS": execute_lookup_traits,
    "LOOKUP_EVENTS": execute_lookup_events,
    "LOOKUP_DECISIONS": execute_lookup_decisions,
    "LOOKUP_DYNASTIES": execute_lookup_dynasties,
    "LOOKUP_CHARACTERS": execute_lookup_characters,
    "LOOKUP_TITLES": execute_lookup_titles,
    "LOOKUP_PROVINCES": execute_lookup_provinces,
    "LOOKUP_HOLY_SITES": execute_lookup_holy_sites,
}


def register_all_executors(worker) -> None:
    """Register all step executors with a worker."""
    for step, executor in EXECUTORS.items():
        worker.register_executor(step, executor)
