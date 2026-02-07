"""
Parser Versioning System

Tracks parser versions to invalidate AST cache when parsing logic changes.
Stores current parser version and allows registering new versions.
"""

import sqlite3
import hashlib
import subprocess
import functools
from pathlib import Path
from typing import Optional
from datetime import datetime

from ck3raven.db.schema import get_connection
from ck3raven.db.models import ParserVersion

# Current parser version - bump this when parsing logic changes
# Format: MAJOR.MINOR.PATCH
# MAJOR: Breaking changes to AST structure
# MINOR: New features, compatible changes
# PATCH: Bug fixes
PARSER_VERSION = "1.0.0"

# Parser version description
PARSER_DESCRIPTION = "Initial parser with edge cases fixed"


@functools.cache
def get_git_commit() -> Optional[str]:
    """
    Get current git commit hash if in a git repo.
    
    Cached to avoid repeated subprocess calls per process.
    """
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]  # Short hash
    except Exception:
        pass
    return None


@functools.cache
def get_parser_source_hash() -> str:
    """
    Compute a hash of the parser source code.
    
    This provides automatic version detection when source changes.
    Cached per process since source doesn't change during runtime.
    """
    parser_dir = Path(__file__).parent.parent / 'parser'
    
    hasher = hashlib.sha256()
    
    for source_file in sorted(parser_dir.glob('*.py')):
        try:
            content = source_file.read_bytes()
            hasher.update(source_file.name.encode('utf-8'))
            hasher.update(content)
        except Exception:
            pass
    
    return hasher.hexdigest()[:12]


def get_or_create_parser_version(
    conn: sqlite3.Connection,
    version_string: Optional[str] = None,
    description: Optional[str] = None
) -> ParserVersion:
    """
    Get or create the current parser version record.
    
    Args:
        conn: Database connection
        version_string: Version string (uses PARSER_VERSION if None)
        description: Description (uses PARSER_DESCRIPTION if None)
    
    Returns:
        ParserVersion record
    """
    version_string = version_string or PARSER_VERSION
    description = description or PARSER_DESCRIPTION
    git_commit = get_git_commit()
    
    # Check if this version exists
    row = conn.execute(
        "SELECT * FROM parsers WHERE version_string = ?",
        (version_string,)
    ).fetchone()
    
    if row:
        return ParserVersion.from_row(row)
    
    # Create new version record
    cursor = conn.execute("""
        INSERT INTO parsers (version_string, git_commit, description)
        VALUES (?, ?, ?)
    """, (version_string, git_commit, description))
    
    conn.commit()
    
    row = conn.execute(
        "SELECT * FROM parsers WHERE parser_version_id = ?",
        (cursor.lastrowid,)
    ).fetchone()
    
    return ParserVersion.from_row(row)


def get_current_parser_version(conn: sqlite3.Connection) -> ParserVersion:
    """Get the current parser version, creating if needed."""
    return get_or_create_parser_version(conn)


def list_parser_versions(conn: sqlite3.Connection) -> list:
    """List all registered parser versions."""
    rows = conn.execute("""
        SELECT * FROM parsers ORDER BY created_at DESC
    """).fetchall()
    
    return [ParserVersion.from_row(row) for row in rows]


def is_parser_version_current(
    conn: sqlite3.Connection,
    parser_version_id: int
) -> bool:
    """Check if a parser version is the current version."""
    current = get_current_parser_version(conn)
    return current.parser_version_id == parser_version_id


def invalidate_ast_cache_for_old_parsers(conn: sqlite3.Connection) -> int:
    """
    Mark AST records from old parser versions for potential reparse.
    
    This doesn't delete them (they might be in snapshots) but
    returns count of records that need updating.
    
    Returns:
        Count of AST records from non-current parser versions
    """
    current = get_current_parser_version(conn)
    
    row = conn.execute("""
        SELECT COUNT(*) as cnt FROM asts 
        WHERE parser_version_id != ?
    """, (current.parser_version_id,)).fetchone()
    
    return row['cnt']


def register_new_parser_version(
    conn: sqlite3.Connection,
    version_string: str,
    description: str
) -> ParserVersion:
    """
    Register a new parser version explicitly.
    
    Use this when releasing a new parser version.
    """
    git_commit = get_git_commit()
    
    cursor = conn.execute("""
        INSERT INTO parsers (version_string, git_commit, description)
        VALUES (?, ?, ?)
    """, (version_string, git_commit, description))
    
    conn.commit()
    
    row = conn.execute(
        "SELECT * FROM parsers WHERE parser_version_id = ?",
        (cursor.lastrowid,)
    ).fetchone()
    
    return ParserVersion.from_row(row)


def get_parser_info() -> dict:
    """Get information about the current parser configuration."""
    return {
        'version': PARSER_VERSION,
        'description': PARSER_DESCRIPTION,
        'git_commit': get_git_commit(),
        'source_hash': get_parser_source_hash(),
    }
