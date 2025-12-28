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
    # Store (relpath, content_hash, mtime) for later storage
    file_hashes: List[Tuple[str, str, str]] = []
    total_size = 0
    
    for i, entry in enumerate(file_entries):
        stats.files_scanned += 1
        
        try:
            file_path = root_path / entry.relpath
            data = file_path.read_bytes()
            content_hash = compute_content_hash(data)
            file_size = len(data)
            
            # Store mtime as string for database
            mtime_str = str(entry.mtime) if entry.mtime else None
            file_hashes.append((entry.relpath, content_hash, mtime_str))
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
    
    # Phase 3: Compute root hash (only using relpath and hash, not mtime)
    hash_pairs = [(r, h) for r, h, _ in file_hashes]
    content_root_hash = compute_root_hash(hash_pairs)
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
    
    for batch_start in range(0, len(file_hashes), batch_size):
        batch_end = min(batch_start + batch_size, len(file_hashes))
        batch = file_hashes[batch_start:batch_end]
        
        for relpath, content_hash, mtime in batch:
            try:
                file_path = root_path / relpath
                data = file_path.read_bytes()
                
                # Store content (deduped by hash)
                store_file_content(conn, data, content_hash)
                
                # Store file record with mtime
                store_file_record(
                    conn=conn,
                    content_version_id=content_version_id,
                    relpath=relpath,
                    content_hash=content_hash,
                    mtime=mtime,
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
    
    Uses incremental update if mod already exists - only reads changed files.
    
    Args:
        conn: Database connection
        mod_path: Path to mod directory
        name: Mod name
        workshop_id: Steam Workshop ID (if applicable)
        force: Re-ingest all files even if exists
    
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
    
    # Check if mod already has a content_version (for incremental update)
    if not force:
        existing_cv = conn.execute("""
            SELECT content_version_id 
            FROM content_versions 
            WHERE mod_package_id = ? 
            ORDER BY ingested_at DESC LIMIT 1
        """, (mod_package.mod_package_id,)).fetchone()
        
        if existing_cv:
            content_version_id = existing_cv[0]
            
            # Use incremental update - only reads changed files
            stats = incremental_update(conn, content_version_id, mod_path)
            
            # Get the updated root hash
            new_hash = conn.execute(
                "SELECT content_root_hash FROM content_versions WHERE content_version_id = ?",
                (content_version_id,)
            ).fetchone()[0]
            
            if stats.files_changed == 0 and stats.files_new == 0 and stats.files_removed == 0:
                logger.info(f"Mod '{name}' unchanged")
                stats.content_reused = True
            else:
                logger.info(f"Mod '{name}' updated: +{stats.files_new} ~{stats.files_changed} -{stats.files_removed}")
            
            return mod_package, IngestResult(
                content_version_id=content_version_id,
                content_root_hash=new_hash,
                stats=stats,
                errors=[],
            )
    
    logger.info(f"Ingesting mod '{name}' (full)...")
    
    # Full ingest - new mod or force rebuild
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
    
    Uses mtime for fast change detection - only reads files that may have changed.
    For replaced/removed files, deletes ALL associated data:
      - symbols (keyed by file_id)
      - refs (keyed by file_id)  
      - asts (keyed by content_hash, only if orphaned)
      - file_contents (keyed by content_hash, only if orphaned)
    
    Sets is_stale=1 and symbols_extracted_at=NULL so the daemon's normal
    file routing regenerates ASTs and symbols for the new content.
    
    Args:
        conn: Database connection
        content_version_id: Version to update
        root_path: Path to content directory
    
    Returns:
        IngestStats with change counts
    """
    stats = IngestStats()
    
    # Get stored manifest with mtime and hash
    stored_files = {}
    for row in conn.execute("""
        SELECT file_id, relpath, content_hash, mtime FROM files
        WHERE content_version_id = ? AND deleted = 0
    """, (content_version_id,)).fetchall():
        stored_files[row['relpath']] = {
            'file_id': row['file_id'],
            'content_hash': row['content_hash'],
            'mtime': row['mtime']
        }
    
    # Scan current directory - just paths and mtime, no content yet
    current_files = {}
    for entry in scan_directory(root_path):
        stats.files_scanned += 1
        current_files[entry.relpath] = {
            'mtime': entry.mtime,
            'size': entry.size
        }
    
    # Determine changes
    stored_paths = set(stored_files.keys())
    current_paths = set(current_files.keys())
    
    added_paths = current_paths - stored_paths
    removed_paths = stored_paths - current_paths
    common_paths = stored_paths & current_paths
    
    # For common files, check if mtime changed (quick) then hash (definitive)
    changed_paths = set()
    unchanged_paths = set()
    
    for relpath in common_paths:
        stored = stored_files[relpath]
        current = current_files[relpath]
        
        # Quick mtime check - if same, assume unchanged
        stored_mtime = float(stored['mtime']) if stored['mtime'] else 0
        if abs(current['mtime'] - stored_mtime) < 0.001:  # mtime unchanged
            unchanged_paths.add(relpath)
            continue
        
        # mtime changed - compute hash to confirm
        try:
            file_path = root_path / relpath
            data = file_path.read_bytes()
            new_hash = compute_content_hash(data)
            
            if new_hash == stored['content_hash']:
                # Hash same despite mtime change (touched but not modified)
                unchanged_paths.add(relpath)
            else:
                changed_paths.add(relpath)
        except Exception as e:
            logger.warning(f"Error reading {relpath}: {e}")
    
    stats.files_new = len(added_paths)
    stats.files_removed = len(removed_paths)
    stats.files_changed = len(changed_paths)
    stats.files_unchanged = len(unchanged_paths)
    
    # Clean up data for files being replaced or removed
    # This ensures the daemon's file routing regenerates everything fresh
    files_to_cleanup = changed_paths | removed_paths
    if files_to_cleanup:
        file_ids_to_cleanup = [stored_files[p]['file_id'] for p in files_to_cleanup if p in stored_files]
        content_hashes_to_cleanup = [stored_files[p]['content_hash'] for p in files_to_cleanup if p in stored_files]
        
        if file_ids_to_cleanup:
            placeholders = ','.join('?' * len(file_ids_to_cleanup))
            # Delete symbols (keyed by file_id - includes mod/version context)
            conn.execute(f"DELETE FROM symbols WHERE defining_file_id IN ({placeholders})", file_ids_to_cleanup)
            # Delete refs (keyed by file_id)
            conn.execute(f"DELETE FROM refs WHERE file_id IN ({placeholders})", file_ids_to_cleanup)
        
        if content_hashes_to_cleanup:
            hash_placeholders = ','.join('?' * len(content_hashes_to_cleanup))
            # Delete ASTs (keyed by content_hash - content-addressable)
            # Only delete if no other files reference this content_hash
            conn.execute(f"""
                DELETE FROM asts WHERE content_hash IN ({hash_placeholders})
                AND content_hash NOT IN (
                    SELECT DISTINCT content_hash FROM files 
                    WHERE content_hash IN ({hash_placeholders}) 
                    AND file_id NOT IN ({placeholders})
                    AND deleted = 0
                )
            """, content_hashes_to_cleanup + content_hashes_to_cleanup + file_ids_to_cleanup)
            
            # Delete raw file content (keyed by content_hash)
            # Only delete if no other files reference this content_hash
            conn.execute(f"""
                DELETE FROM file_contents WHERE content_hash IN ({hash_placeholders})
                AND content_hash NOT IN (
                    SELECT DISTINCT content_hash FROM files 
                    WHERE content_hash IN ({hash_placeholders}) 
                    AND file_id NOT IN ({placeholders})
                    AND deleted = 0
                )
            """, content_hashes_to_cleanup + content_hashes_to_cleanup + file_ids_to_cleanup)
    
    # Process additions and changes - only read these files
    for relpath in added_paths | changed_paths:
        try:
            file_path = root_path / relpath
            stat = file_path.stat()
            data = file_path.read_bytes()
            content_hash = compute_content_hash(data)
            
            store_file_content(conn, data, content_hash)
            store_file_record(conn, content_version_id, relpath, content_hash, mtime=str(stat.st_mtime))
            stats.bytes_stored += len(data)
        except Exception as e:
            logger.warning(f"Error storing {relpath}: {e}")
    
    # Mark removed files as deleted
    for relpath in removed_paths:
        conn.execute("""
            UPDATE files SET deleted = 1
            WHERE content_version_id = ? AND relpath = ?
        """, (content_version_id, relpath))
    
    # Update root hash
    current_hashes = []
    for relpath in current_paths:
        if relpath in added_paths or relpath in changed_paths:
            # Get hash from just-stored record
            h = conn.execute(
                "SELECT content_hash FROM files WHERE content_version_id = ? AND relpath = ?",
                (content_version_id, relpath)
            ).fetchone()[0]
        else:
            h = stored_files[relpath]['content_hash']
        current_hashes.append((relpath, h))
    
    new_root_hash = compute_root_hash(current_hashes)
    
    conn.execute("""
        UPDATE content_versions 
        SET content_root_hash = ?, file_count = ?, 
            symbols_extracted_at = NULL
        WHERE content_version_id = ?
    """, (new_root_hash, len(current_paths), content_version_id))
    
    conn.commit()
    
    logger.info(f"Incremental update: +{stats.files_new} -{stats.files_removed} ~{stats.files_changed} (read {stats.files_new + stats.files_changed} files)")
    
    return stats
