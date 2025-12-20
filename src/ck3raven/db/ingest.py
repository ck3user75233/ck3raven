"""
Ingestion Pipeline for ck3raven

Handles incremental ingestion of vanilla and mod content.
Only re-processes files that have changed.
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Set
from dataclasses import dataclass
from datetime import datetime

from ck3raven.db.schema import get_connection
from ck3raven.db.models import VanillaVersion, ModPackage, ContentVersion
from ck3raven.db.content import (
    compute_content_hash,
    compute_root_hash,
    normalize_relpath,
    scan_directory,
    store_file_content,
    store_file_record,
    find_content_version_by_hash,
    create_content_version,
    get_stored_manifest,
    FileManifestEntry,
)

logger = logging.getLogger(__name__)


@dataclass
class IngestStats:
    """Statistics from an ingestion run."""
    files_scanned: int = 0
    files_new: int = 0
    files_changed: int = 0
    files_unchanged: int = 0
    files_removed: int = 0
    bytes_stored: int = 0
    content_reused: bool = False  # True if entire version was already stored


@dataclass 
class IngestResult:
    """Result of an ingestion operation."""
    content_version_id: int
    content_root_hash: str
    stats: IngestStats
    errors: List[Tuple[str, str]]  # (relpath, error_message)


def get_or_create_vanilla_version(
    conn: sqlite3.Connection,
    ck3_version: str,
    dlc_set: List[str] = None
) -> VanillaVersion:
    """
    Get or create a vanilla version record.
    
    Args:
        conn: Database connection
        ck3_version: CK3 version string (e.g., "1.13.2")
        dlc_set: List of enabled DLC IDs
    
    Returns:
        VanillaVersion record
    """
    import json
    
    dlc_set = dlc_set or []
    dlc_set_json = json.dumps(sorted(dlc_set))
    
    # Check if exists
    row = conn.execute("""
        SELECT * FROM vanilla_versions 
        WHERE ck3_version = ? AND dlc_set_json = ?
    """, (ck3_version, dlc_set_json)).fetchone()
    
    if row:
        return VanillaVersion.from_row(row)
    
    # Create new
    cursor = conn.execute("""
        INSERT INTO vanilla_versions (ck3_version, dlc_set_json)
        VALUES (?, ?)
    """, (ck3_version, dlc_set_json))
    
    conn.commit()
    
    row = conn.execute(
        "SELECT * FROM vanilla_versions WHERE vanilla_version_id = ?",
        (cursor.lastrowid,)
    ).fetchone()
    
    return VanillaVersion.from_row(row)


def get_or_create_mod_package(
    conn: sqlite3.Connection,
    name: str,
    workshop_id: Optional[str] = None,
    source_path: Optional[str] = None
) -> ModPackage:
    """
    Get or create a mod package record.
    
    Args:
        conn: Database connection
        name: Mod name
        workshop_id: Steam Workshop ID (if applicable)
        source_path: Local filesystem path
    
    Returns:
        ModPackage record
    """
    # Check by workshop_id first if provided
    if workshop_id:
        row = conn.execute(
            "SELECT * FROM mod_packages WHERE workshop_id = ?",
            (workshop_id,)
        ).fetchone()
        if row:
            return ModPackage.from_row(row)
    
    # Check by name + source_path
    row = conn.execute(
        "SELECT * FROM mod_packages WHERE name = ? AND source_path = ?",
        (name, source_path)
    ).fetchone()
    if row:
        return ModPackage.from_row(row)
    
    # Create new
    cursor = conn.execute("""
        INSERT INTO mod_packages (name, workshop_id, source_path)
        VALUES (?, ?, ?)
    """, (name, workshop_id, source_path))
    
    conn.commit()
    
    row = conn.execute(
        "SELECT * FROM mod_packages WHERE mod_package_id = ?",
        (cursor.lastrowid,)
    ).fetchone()
    
    return ModPackage.from_row(row)


def ingest_directory(
    conn: sqlite3.Connection,
    root_path: Path,
    kind: str,
    vanilla_version_id: Optional[int] = None,
    mod_package_id: Optional[int] = None,
    force: bool = False,
    progress_callback: Optional[callable] = None,
    batch_size: int = 500
) -> IngestResult:
    """
    Ingest a directory (vanilla or mod) into the database.
    
    This is the core ingestion function. It:
    1. Scans the directory for files (streaming, not all in memory)
    2. Computes content hashes in batches
    3. Computes root hash to identify the version
    4. If version already exists and not force, returns existing
    5. Otherwise, stores new/changed content and creates records
    
    Args:
        conn: Database connection
        root_path: Path to the content root
        kind: 'vanilla' or 'mod'
        vanilla_version_id: FK for vanilla versions
        mod_package_id: FK for mod packages
        force: If True, re-ingest even if version exists
        progress_callback: Optional callback(files_done, total_files) for progress
        batch_size: Number of files to process per batch
    
    Returns:
        IngestResult with content_version_id and stats
    """
    stats = IngestStats()
    errors = []
    
    logger.info(f"Scanning {root_path}...")
    
    # Phase 1: Scan directory and collect file paths (lightweight - just paths)
    # This is O(n) memory for paths only, not file contents
    file_entries = list(scan_directory(root_path))
    total_files = len(file_entries)
    logger.info(f"Found {total_files} files to process")
    
    if not file_entries:
        raise ValueError(f"No files found in {root_path}")
    
    # Phase 2: Compute hashes in streaming fashion for root hash
    # We need all hashes for the root hash, but we don't need to keep content
    file_hashes: List[Tuple[str, str]] = []
    total_size = 0
    
    for i, entry in enumerate(file_entries):
        stats.files_scanned += 1
        
        try:
            file_path = root_path / entry.relpath
            data = file_path.read_bytes()
            content_hash = compute_content_hash(data)
            file_size = len(data)
            
            file_hashes.append((entry.relpath, content_hash))
            total_size += file_size
            
            # Don't keep data in memory - we'll re-read it if needed
            del data
            
        except Exception as e:
            errors.append((entry.relpath, str(e)))
            logger.warning(f"Error reading {entry.relpath}: {e}")
        
        # Progress callback
        if progress_callback and (i + 1) % 1000 == 0:
            progress_callback(i + 1, total_files)
    
    logger.info(f"Computed hashes for {len(file_hashes)} files")
    
    # Phase 3: Compute root hash
    content_root_hash = compute_root_hash(file_hashes)
    logger.info(f"Root hash: {content_root_hash[:12]}... ({len(file_hashes)} files)")
    
    # Phase 4: Check if version already exists
    existing = find_content_version_by_hash(conn, content_root_hash)
    
    if existing and not force:
        logger.info(f"Content version already exists: {existing.content_version_id}")
        stats.content_reused = True
        stats.files_unchanged = stats.files_scanned
        return IngestResult(
            content_version_id=existing.content_version_id,
            content_root_hash=content_root_hash,
            stats=stats,
            errors=errors,
        )
    
    # If force and existing, delete old version first
    if existing and force:
        logger.info(f"Force mode: deleting existing content version {existing.content_version_id}")
        conn.execute("DELETE FROM files WHERE content_version_id = ?", (existing.content_version_id,))
        conn.execute("DELETE FROM content_versions WHERE content_version_id = ?", (existing.content_version_id,))
        conn.commit()
    
    # Phase 5: Create content version
    content_version_id = create_content_version(
        conn=conn,
        kind=kind,
        content_root_hash=content_root_hash,
        vanilla_version_id=vanilla_version_id,
        mod_package_id=mod_package_id,
        file_count=len(file_hashes),
        total_size=total_size,
    )
    
    logger.info(f"Created content version {content_version_id}")
    
    # Phase 6: Store file contents in batches (re-read files, but batch commits)
    # This keeps memory bounded to batch_size files at a time
    hash_to_relpath = {h: r for r, h in file_hashes}
    
    for batch_start in range(0, len(file_hashes), batch_size):
        batch_end = min(batch_start + batch_size, len(file_hashes))
        batch = file_hashes[batch_start:batch_end]
        
        for relpath, content_hash in batch:
            try:
                file_path = root_path / relpath
                data = file_path.read_bytes()
                
                # Store content (deduped by hash)
                store_file_content(conn, data, content_hash)
                
                # Store file record
                store_file_record(
                    conn=conn,
                    content_version_id=content_version_id,
                    relpath=relpath,
                    content_hash=content_hash,
                )
                
                stats.files_new += 1
                stats.bytes_stored += len(data)
                
                del data  # Free memory immediately
                
            except Exception as e:
                errors.append((relpath, str(e)))
                logger.warning(f"Error storing {relpath}: {e}")
        
        # Commit after each batch
        conn.commit()
        
        # Progress callback
        if progress_callback:
            progress_callback(batch_end, total_files)
        
        if batch_end % 5000 == 0:
            logger.info(f"Stored {batch_end}/{len(file_hashes)} files...")
    
    logger.info(f"Ingested {stats.files_new} files, {stats.bytes_stored:,} bytes")
    
    return IngestResult(
        content_version_id=content_version_id,
        content_root_hash=content_root_hash,
        stats=stats,
        errors=errors,
    )


def ingest_vanilla(
    conn: sqlite3.Connection,
    game_path: Path,
    ck3_version: str,
    dlc_set: List[str] = None,
    force: bool = False,
    progress_callback: Optional[callable] = None
) -> Tuple[VanillaVersion, IngestResult]:
    """
    Ingest vanilla CK3 game files.
    
    Args:
        conn: Database connection
        game_path: Path to CK3 game directory
        ck3_version: CK3 version string
        dlc_set: List of enabled DLC IDs
        force: Re-ingest even if exists
        progress_callback: Optional callback(files_done, total_files)
    
    Returns:
        (VanillaVersion, IngestResult)
    """
    # Get or create vanilla version record
    vanilla_version = get_or_create_vanilla_version(conn, ck3_version, dlc_set)
    
    logger.info(f"Ingesting vanilla {ck3_version}...")
    
    # Ingest the game directory
    result = ingest_directory(
        conn=conn,
        root_path=game_path,
        kind='vanilla',
        vanilla_version_id=vanilla_version.vanilla_version_id,
        force=force,
        progress_callback=progress_callback,
    )
    
    return vanilla_version, result


def ingest_mod(
    conn: sqlite3.Connection,
    mod_path: Path,
    name: str,
    workshop_id: Optional[str] = None,
    force: bool = False
) -> Tuple[ModPackage, IngestResult]:
    """
    Ingest a mod's files.
    
    Args:
        conn: Database connection
        mod_path: Path to mod directory
        name: Mod name
        workshop_id: Steam Workshop ID (if applicable)
        force: Re-ingest even if exists
    
    Returns:
        (ModPackage, IngestResult)
    """
    # Get or create mod package record
    mod_package = get_or_create_mod_package(
        conn=conn,
        name=name,
        workshop_id=workshop_id,
        source_path=str(mod_path),
    )
    
    logger.info(f"Ingesting mod '{name}'...")
    
    # Ingest the mod directory
    result = ingest_directory(
        conn=conn,
        root_path=mod_path,
        kind='mod',
        mod_package_id=mod_package.mod_package_id,
        force=force,
    )
    
    return mod_package, result


def compare_manifests(
    stored: Dict[str, str],
    current: Dict[str, str]
) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    """
    Compare stored manifest to current directory state.
    
    Args:
        stored: Dict of relpath -> content_hash from database
        current: Dict of relpath -> content_hash from filesystem
    
    Returns:
        (added, removed, changed, unchanged) sets of relpaths
    """
    stored_paths = set(stored.keys())
    current_paths = set(current.keys())
    
    added = current_paths - stored_paths
    removed = stored_paths - current_paths
    
    common = stored_paths & current_paths
    changed = {p for p in common if stored[p] != current[p]}
    unchanged = common - changed
    
    return added, removed, changed, unchanged


def incremental_update(
    conn: sqlite3.Connection,
    content_version_id: int,
    root_path: Path
) -> IngestStats:
    """
    Incrementally update a content version with filesystem changes.
    
    This is for updating an existing version when files change,
    rather than creating a new version.
    
    Note: This changes the content_root_hash, so the version identity changes.
    Consider whether you want this or a new version.
    
    Args:
        conn: Database connection
        content_version_id: Version to update
        root_path: Path to content directory
    
    Returns:
        IngestStats with change counts
    """
    stats = IngestStats()
    
    # Get stored manifest
    stored_manifest = get_stored_manifest(conn, content_version_id)
    
    # Scan current directory
    current_manifest: Dict[str, str] = {}
    for entry in scan_directory(root_path):
        stats.files_scanned += 1
        try:
            file_path = root_path / entry.relpath
            data = file_path.read_bytes()
            content_hash = compute_content_hash(data)
            current_manifest[entry.relpath] = content_hash
        except Exception as e:
            logger.warning(f"Error reading {entry.relpath}: {e}")
    
    # Compare
    added, removed, changed, unchanged = compare_manifests(stored_manifest, current_manifest)
    
    stats.files_new = len(added)
    stats.files_removed = len(removed)
    stats.files_changed = len(changed)
    stats.files_unchanged = len(unchanged)
    
    # Process additions and changes
    for relpath in added | changed:
        file_path = root_path / relpath
        data = file_path.read_bytes()
        content_hash = compute_content_hash(data)
        
        store_file_content(conn, data, content_hash)
        store_file_record(conn, content_version_id, relpath, content_hash)
        stats.bytes_stored += len(data)
    
    # Mark removed files as deleted
    for relpath in removed:
        conn.execute("""
            UPDATE files SET deleted = 1
            WHERE content_version_id = ? AND relpath = ?
        """, (content_version_id, relpath))
    
    # Update root hash
    current_hashes = [(p, h) for p, h in current_manifest.items()]
    new_root_hash = compute_root_hash(current_hashes)
    
    conn.execute("""
        UPDATE content_versions 
        SET content_root_hash = ?, file_count = ?, total_size = (
            SELECT SUM(size) FROM file_contents fc
            JOIN files f ON fc.content_hash = f.content_hash
            WHERE f.content_version_id = ? AND f.deleted = 0
        )
        WHERE content_version_id = ?
    """, (new_root_hash, len(current_manifest), content_version_id, content_version_id))
    
    conn.commit()
    
    logger.info(f"Incremental update: +{stats.files_new} -{stats.files_removed} ~{stats.files_changed}")
    
    return stats
