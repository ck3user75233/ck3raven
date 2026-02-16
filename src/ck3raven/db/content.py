"""
Content-Addressed Storage Operations

Handles file content deduplication, hashing, and storage.
All content is stored once and referenced by SHA256 hash.
"""

import hashlib
import sqlite3
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Iterator
from dataclasses import dataclass
import os

from ck3raven.db.schema import get_connection
from ck3raven.db.models import FileContent, FileRecord, ContentVersion


def compute_content_hash(data: bytes) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(data).hexdigest()


def compute_root_hash(file_hashes: List[Tuple[str, str]]) -> str:
    """
    Compute a root hash from sorted (relpath, content_hash) pairs.
    
    This gives a stable version identity for a mod/vanilla version
    even if timestamps change.
    """
    # Sort by relpath for deterministic ordering
    sorted_pairs = sorted(file_hashes, key=lambda x: x[0].lower())
    
    # Hash the concatenated pairs
    hasher = hashlib.sha256()
    for relpath, content_hash in sorted_pairs:
        hasher.update(relpath.encode('utf-8'))
        hasher.update(content_hash.encode('utf-8'))
    
    return hasher.hexdigest()


def normalize_relpath(path: str) -> str:
    """
    Normalize a relative path to CK3-style.
    
    - Use forward slashes
    - Lowercase for consistency
    - Strip leading/trailing slashes
    """
    normalized = path.replace('\\', '/').strip('/')
    # CK3 paths are case-insensitive on Windows, normalize to lowercase
    return normalized.lower()


def detect_encoding(data: bytes) -> Tuple[str, bool]:
    """
    Detect file encoding and whether it's binary.
    
    Returns:
        (encoding, is_binary) tuple
    """
    # Check for BOM
    if data.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig', False
    if data.startswith(b'\xff\xfe'):
        return 'utf-16-le', False
    if data.startswith(b'\xfe\xff'):
        return 'utf-16-be', False
    
    # Check for binary content (null bytes in first 8KB)
    sample = data[:8192]
    if b'\x00' in sample:
        return 'binary', True
    
    # Try UTF-8
    try:
        data.decode('utf-8')
        return 'utf-8', False
    except UnicodeDecodeError:
        pass
    
    # Fall back to latin-1 (always succeeds for byte data)
    return 'latin-1', False


def classify_file_type(relpath: str) -> str:
    """
    Classify file type based on file routing rules.
    
    Returns: 'script', 'localization', 'lookups', 'skip'
    
    This is the canonical classification - used at ingest time to tag files
    so that later phases know which processing pipeline applies.
    """
    from ck3raven.db.file_routes import get_file_route, FileRoute
    
    route, _reason = get_file_route(relpath)
    
    # Map FileRoute enum to stored file_type string
    if route == FileRoute.SCRIPT:
        return 'script'
    elif route == FileRoute.LOCALIZATION:
        return 'localization'
    elif route == FileRoute.LOOKUPS:
        return 'lookups'
    else:
        return 'skip'


@dataclass
class FileManifestEntry:
    """Entry in a file manifest for change detection."""
    relpath: str
    size: int
    mtime: float
    content_hash: Optional[str] = None  # Computed lazily


def scan_directory(root_path: Path, include_patterns: Optional[List[str]] = None) -> Iterator[FileManifestEntry]:
    """
    Scan a directory and yield manifest entries for all files.
    
    Args:
        root_path: Root directory to scan
        include_patterns: Optional list of glob patterns to include
    
    Yields:
        FileManifestEntry for each file
    """
    if not root_path.exists():
        return
    
    for file_path in root_path.rglob('*'):
        if not file_path.is_file():
            continue
        
        # Skip certain files/directories
        relpath = str(file_path.relative_to(root_path))
        relpath_lower = relpath.lower()
        
        # Skip hidden files, thumbnails, etc.
        if any(part.startswith('.') for part in Path(relpath).parts):
            continue
        if 'thumbnail' in relpath_lower:
            continue

        # Only ingest CK3 script files (.txt, .yml) - skip binary assets
        # This prevents 50GB+ of .dds, .mesh, .anim files from bloating the database
        file_type = classify_file_type(relpath)
        if file_type not in ('script', 'localization'):
            continue

        try:
            stat = file_path.stat()
            yield FileManifestEntry(
                relpath=normalize_relpath(relpath),
                size=stat.st_size,
                mtime=stat.st_mtime,
            )
        except OSError:
            continue


def store_file_content(
    conn: sqlite3.Connection,
    data: bytes,
    content_hash: Optional[str] = None
) -> str:
    """
    Store file content with deduplication.
    
    Args:
        conn: Database connection
        data: Raw file bytes
        content_hash: Pre-computed hash (computed if None)
    
    Returns:
        Content hash (SHA256)
    """
    if content_hash is None:
        content_hash = compute_content_hash(data)
    
    # Check if already stored
    existing = conn.execute(
        "SELECT content_hash FROM file_contents WHERE content_hash = ?",
        (content_hash,)
    ).fetchone()
    
    if existing:
        return content_hash
    
    # Detect encoding
    encoding, is_binary = detect_encoding(data)
    
    # Store text preview if not binary
    content_text = None
    if not is_binary:
        try:
            # Use the full encoding name (including -sig suffix) to properly strip BOM
            content_text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    
    conn.execute("""
        INSERT INTO file_contents (content_hash, content_blob, content_text, size, encoding_guess, is_binary)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (content_hash, data, content_text, len(data), encoding, int(is_binary)))
    
    return content_hash


def get_file_content(conn: sqlite3.Connection, content_hash: str) -> Optional[FileContent]:
    """Retrieve file content by hash."""
    row = conn.execute(
        "SELECT * FROM file_contents WHERE content_hash = ?",
        (content_hash,)
    ).fetchone()
    
    if row:
        return FileContent.from_row(row)
    return None


def store_file_record(
    conn: sqlite3.Connection,
    content_version_id: int,
    relpath: str,
    content_hash: str,
    mtime: Optional[str] = None
) -> int:
    """
    Store a file record linking a path to content.
    
    Returns:
        file_id of the stored record
    """
    file_type = classify_file_type(relpath)
    normalized_path = normalize_relpath(relpath)
    
    cursor = conn.execute("""
        INSERT OR REPLACE INTO files (content_version_id, relpath, content_hash, file_type, mtime, deleted)
        VALUES (?, ?, ?, ?, ?, 0)
    """, (content_version_id, normalized_path, content_hash, file_type, mtime))
    
    return cursor.lastrowid


def get_file_record(
    conn: sqlite3.Connection,
    content_version_id: int,
    relpath: str
) -> Optional[FileRecord]:
    """Get a file record by version and path."""
    normalized_path = normalize_relpath(relpath)
    
    row = conn.execute("""
        SELECT * FROM files 
        WHERE content_version_id = ? AND relpath = ? AND deleted = 0
    """, (content_version_id, normalized_path)).fetchone()
    
    if row:
        return FileRecord.from_row(row)
    return None


def list_files_in_version(
    conn: sqlite3.Connection,
    content_version_id: int,
    file_type: Optional[str] = None
) -> List[FileRecord]:
    """List all files in a content version."""
    if file_type:
        rows = conn.execute("""
            SELECT * FROM files 
            WHERE content_version_id = ? AND file_type = ? AND deleted = 0
            ORDER BY relpath
        """, (content_version_id, file_type)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM files 
            WHERE content_version_id = ? AND deleted = 0
            ORDER BY relpath
        """, (content_version_id,)).fetchall()
    
    return [FileRecord.from_row(row) for row in rows]


def get_stored_manifest(
    conn: sqlite3.Connection,
    content_version_id: int
) -> Dict[str, str]:
    """
    Get the stored manifest for a content version.
    
    Returns:
        Dict mapping relpath -> content_hash
    """
    rows = conn.execute("""
        SELECT relpath, content_hash FROM files
        WHERE content_version_id = ? AND deleted = 0
    """, (content_version_id,)).fetchall()
    
    return {row['relpath']: row['content_hash'] for row in rows}


def find_content_version_by_hash(
    conn: sqlite3.Connection,
    content_root_hash: str
) -> Optional[ContentVersion]:
    """Find a content version by its root hash."""
    row = conn.execute(
        "SELECT * FROM content_versions WHERE content_root_hash = ?",
        (content_root_hash,)
    ).fetchone()
    
    if row:
        return ContentVersion.from_row(row)
    return None

def create_content_version(
    conn: sqlite3.Connection,
    content_root_hash: str,
    name: Optional[str] = None,
    source_path: Optional[str] = None,
    workshop_id: Optional[str] = None,
    file_count: int = 0,
    total_size: int = 0
) -> int:
    """
    Create a new content version.
    
    Returns:
        content_version_id
    """
    cursor = conn.execute("""
        INSERT INTO content_versions (name, source_path, workshop_id, content_root_hash, file_count, total_size)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name, source_path, workshop_id, content_root_hash, file_count, total_size))
    
    return cursor.lastrowid
