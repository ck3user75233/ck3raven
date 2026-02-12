"""
QBuilder Discovery — Canonical Phase 1

Crash-safe file enumeration with fingerprint binding.

Key behaviors:
- discovery_queue references cvid ONLY (paths derived via joins)
- Every file gets upserted with fingerprint (mtime, size, hash)
- Every file gets build_queue row with fingerprint binding
- Commits frequently for crash safety
- Resume via last_path_processed

No parallel constructs:
- No root_type/root_path/root_name in queue
- No files_discovered/files_queued counters
- Logging derives paths via canonical joins
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional
import sqlite3

from qbuilder.schema import get_root_path_for_cvid

# Commit progress every N files
COMMIT_BATCH_SIZE = 500

# Lease duration in seconds
DISCOVERY_LEASE_SECONDS = 300  # 5 minutes


@dataclass
class FileRecord:
    """Discovered file with fingerprint."""
    relpath: str
    mtime: float      # Unix timestamp (seconds)
    size: int         # Bytes
    hash: str         # SHA256 hex


def get_routing_table() -> dict:
    """Load routing table from JSON file."""
    routing_path = Path(__file__).parent / "routing_table.json"
    if routing_path.exists():
        with open(routing_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    # Minimal fallback
    return {
        "extension_to_type": {".txt": "script", ".yml": "localization"},
        "type_to_envelope": {"script": "E_SCRIPT", "localization": "E_LOC", "unknown": "E_SKIP"},
        "skip_extensions": [".dds", ".png", ".jpg", ".wav", ".mp3", ".mesh", ".anim"]
    }


def get_envelope_for_file(relpath: str, routing_table: dict) -> str:
    """Route file to envelope based on path rules first, then extension."""
    from pathlib import Path as P
    relpath_normalized = relpath.replace('\\', '/').lower()
    
    # Check path rules first (lookups, skip folders)
    for rule in routing_table.get('path_rules', []):
        if rule['match'].lower() in relpath_normalized:
            return rule['envelope']
    
    # Then check skip_extensions
    ext = P(relpath).suffix.lower()
    if ext in routing_table.get('skip_extensions', []):
        return 'E_SKIP'
    
    # Finally, extension-based routing
    ext_to_type = routing_table.get('extension_to_type', {})
    type_to_env = routing_table.get('type_to_envelope', {})
    
    file_type = ext_to_type.get(ext, 'unknown')
    return type_to_env.get(file_type, 'E_SKIP')


def get_file_type(relpath: str, routing_table: dict) -> str:
    """Get file type from extension."""
    ext = Path(relpath).suffix.lower()
    return routing_table.get('extension_to_type', {}).get(ext, 'unknown')


def compute_file_fingerprint(filepath: Path) -> Optional[FileRecord]:
    """
    Compute complete fingerprint for a file.
    
    Returns FileRecord with mtime, size, and hash.
    Returns None if file cannot be read.
    """
    try:
        stat = filepath.stat()
        
        # Compute hash
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        
        relpath = ""  # Will be set by caller
        return FileRecord(
            relpath=relpath,
            mtime=stat.st_mtime,
            size=stat.st_size,
            hash=h.hexdigest()
        )
    except (OSError, IOError):
        return None


def enumerate_files(root_path: Path, resume_after: Optional[str] = None) -> Iterator[FileRecord]:
    """
    Enumerate all files under root_path with fingerprints.
    
    Yields FileRecord for each file, sorted by relpath for deterministic resume.
    """
    # Collect and sort for deterministic order
    all_files = []
    for dirpath, _, filenames in os.walk(root_path):
        for filename in filenames:
            filepath = Path(dirpath) / filename
            relpath = str(filepath.relative_to(root_path)).replace('\\', '/')
            all_files.append((relpath, filepath))
    
    all_files.sort(key=lambda x: x[0])
    
    # Resume logic
    past_resume = resume_after is None
    
    for relpath, filepath in all_files:
        if not past_resume:
            if relpath == resume_after:
                past_resume = True
            continue
        
        record = compute_file_fingerprint(filepath)
        if record:
            record.relpath = relpath
            yield record


def enqueue_playset_roots(conn: sqlite3.Connection, playset_path: Path) -> int:
    """
    Read playset JSON and enqueue discovery tasks for all content sources.
    
    Returns count of tasks enqueued.
    """
    with open(playset_path, 'r', encoding='utf-8-sig') as f:
        playset = json.load(f)
    
    now = time.time()
    count = 0
    
    # Enqueue vanilla (check both formats: vanilla_path string or vanilla object)
    vanilla = playset.get('vanilla') or {}
    vanilla_path = playset.get('vanilla_path') or vanilla.get('path')
    if vanilla_path and Path(vanilla_path).exists():
        cvid = _ensure_cvid(conn, name='Vanilla CK3', source_path=vanilla_path, workshop_id=None)
        _enqueue_discovery(conn, cvid, now)
        count += 1
    
    # Enqueue mods
    for mod in playset.get('mods', []):
        mod_path = mod.get('path') or mod.get('source_path')
        if not mod_path or not Path(mod_path).exists():
            continue
        
        cvid = _ensure_cvid(
            conn, 
            name=mod.get('name', 'Unknown'),
            source_path=mod_path,
            workshop_id=mod.get('steam_id') or mod.get('workshop_id')
        )
        _enqueue_discovery(conn, cvid, now)
        count += 1
    
    conn.commit()
    return count


def _ensure_cvid(conn: sqlite3.Connection, name: str, source_path: str, 
                 workshop_id: str | None) -> int:
    """
    Get or create content_version for any content source.
    
    Lookup priority:
    1. By workshop_id if provided
    2. By source_path otherwise
    
    Creates mod_package + content_version if not found.
    """
    # Try to find existing by workshop_id or source_path
    if workshop_id:
        row = conn.execute(
            "SELECT mod_package_id FROM mod_packages WHERE workshop_id = ?",
            (workshop_id,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT mod_package_id FROM mod_packages WHERE source_path = ?",
            (source_path,)
        ).fetchone()
    
    if row:
        mp_id = row[0]
    else:
        # Create mod_package
        cursor = conn.execute("""
            INSERT INTO mod_packages (name, source_path, workshop_id)
            VALUES (?, ?, ?)
        """, (name, source_path, workshop_id))
        conn.commit()
        mp_id = cursor.lastrowid
        assert mp_id is not None  # INSERT always sets lastrowid
    
    # Get or create content_version
    row = conn.execute(
        "SELECT content_version_id FROM content_versions WHERE mod_package_id = ?",
        (mp_id,)
    ).fetchone()
    if row:
        return row[0]
    
    content_root_hash = hashlib.sha256(source_path.encode()).hexdigest()[:32]
    cursor = conn.execute("""
        INSERT INTO content_versions (kind, mod_package_id, content_root_hash)
        VALUES ('mod', ?, ?)
    """, (mp_id, content_root_hash))
    conn.commit()
    cvid = cursor.lastrowid
    assert cvid is not None  # INSERT always sets lastrowid
    return cvid


def _enqueue_discovery(conn: sqlite3.Connection, cvid: int, now: float) -> None:
    """Enqueue a discovery task for cvid (idempotent)."""
    conn.execute("""
        INSERT INTO discovery_queue (content_version_id, status, created_at)
        VALUES (?, 'pending', ?)
        ON CONFLICT (content_version_id) DO NOTHING
    """, (cvid, now))


class IncrementalDiscovery:
    """
    Crash-safe incremental file discovery.
    
    Processes one discovery_queue task at a time:
    1. Claim task with lease (cvid only)
    2. Resolve root path via canonical join
    3. Enumerate files with fingerprints
    4. Upsert files and build_queue rows
    5. Commit frequently
    6. Mark complete
    """
    
    def __init__(self, conn: sqlite3.Connection, worker_id: Optional[str] = None):
        self.conn = conn
        self.worker_id = worker_id or f"worker-{os.getpid()}"
        self.routing_table = get_routing_table()
    
    def claim_task(self) -> Optional[dict]:
        """Claim next available discovery task."""
        now = time.time()
        lease_until = now + DISCOVERY_LEASE_SECONDS
        
        cursor = self.conn.execute("""
            UPDATE discovery_queue
            SET status = 'processing',
                lease_expires_at = ?,
                lease_holder = ?,
                started_at = COALESCE(started_at, ?)
            WHERE discovery_id = (
                SELECT discovery_id FROM discovery_queue
                WHERE status = 'pending'
                   OR (status = 'processing' AND lease_expires_at < ?)
                ORDER BY discovery_id
                LIMIT 1
            )
            RETURNING discovery_id, content_version_id, last_path_processed
        """, (lease_until, self.worker_id, now, now))
        
        row = cursor.fetchone()
        self.conn.commit()
        
        if row:
            return {
                'discovery_id': row[0],
                'cvid': row[1],
                'last_path_processed': row[2]
            }
        return None
    
    def process_task(self, task: dict) -> dict:
        """
        Process discovery task: enumerate files and enqueue build work.
        
        Returns summary with file count.
        """
        discovery_id = task['discovery_id']
        cvid = task['cvid']
        resume_after = task.get('last_path_processed')
        
        # Resolve root path via canonical join
        root_path = self._resolve_root_path(cvid)
        if not root_path:
            self._mark_error(discovery_id, f"Cannot resolve root path for cvid={cvid}")
            return {'error': f"Cannot resolve root path for cvid={cvid}"}
        
        root_path = Path(root_path)
        if not root_path.exists():
            self._mark_error(discovery_id, f"Root path does not exist: {root_path}")
            return {'error': f"Root path does not exist: {root_path}"}
        
        # Get display name for logging
        display_name = self._get_display_name(cvid)
        print(f"Processing: {display_name} ({root_path})")
        
        file_count = 0
        batch = []
        
        for record in enumerate_files(root_path, resume_after):
            batch.append(record)
            file_count += 1
            
            if len(batch) >= COMMIT_BATCH_SIZE:
                self._commit_batch(cvid, batch, record.relpath, discovery_id)
                batch = []
                self._renew_lease(discovery_id)
        
        # Final batch
        if batch:
            self._commit_batch(cvid, batch, batch[-1].relpath, discovery_id)
        
        # Mark complete
        now = time.time()
        self.conn.execute("""
            UPDATE discovery_queue
            SET status = 'completed', completed_at = ?
            WHERE discovery_id = ?
        """, (now, discovery_id))
        self.conn.commit()
        
        print(f"  Discovered: {file_count} files")
        return {'cvid': cvid, 'file_count': file_count}
    
    def _resolve_root_path(self, cvid: int) -> Optional[str]:
        """Resolve cvid to root path via canonical joins."""
        row = self.conn.execute("""
            SELECT cv.kind, mp.source_path
            FROM content_versions cv
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE cv.content_version_id = ?
        """, (cvid,)).fetchone()
        
        if not row:
            return None
        
        kind, source_path = row
        
        if kind == 'vanilla':
            # Get vanilla path from active playset or config
            # For now, check if there's a recent playset file
            return self._get_vanilla_path()
        
        return source_path
    
    def _get_vanilla_path(self) -> Optional[str]:
        """Get vanilla game path from playset or environment."""
        # Try to find active playset
        manifest_path = Path.home() / ".ck3raven" / "playsets" / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path, 'r', encoding='utf-8-sig') as f:
                manifest = json.load(f)
            active = manifest.get('active_playset')
            if active:
                playset_path = manifest_path.parent / active
                if playset_path.exists():
                    with open(playset_path, 'r', encoding='utf-8-sig') as f:
                        playset = json.load(f)
                    return playset.get('vanilla_path')
        return None
    
    def _get_display_name(self, cvid: int) -> str:
        """Get human-readable name for cvid via joins."""
        row = self.conn.execute("""
            SELECT cv.kind, mp.name
            FROM content_versions cv
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE cv.content_version_id = ?
        """, (cvid,)).fetchone()
        
        if row:
            kind, name = row
            if kind == 'vanilla':
                return 'Vanilla CK3'
            return name or f'Mod #{cvid}'
        return f'Unknown #{cvid}'
    
    def _commit_batch(self, cvid: int, batch: list[FileRecord], 
                      last_path: str, discovery_id: int) -> None:
        """
        Commit a batch of files atomically.
        
        For each file:
        1. Upsert into files with fingerprint
        2. Route to envelope
        3. Upsert into build_queue with fingerprint binding
        """
        now = time.time()
        
        for record in batch:
            # Upsert file with fingerprint
            file_type = get_file_type(record.relpath, self.routing_table)
            cursor = self.conn.execute("""
                INSERT INTO files (content_version_id, relpath, content_hash, 
                                   file_type, file_mtime, file_size, file_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (content_version_id, relpath) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    file_type = excluded.file_type,
                    file_mtime = excluded.file_mtime,
                    file_size = excluded.file_size,
                    file_hash = excluded.file_hash
                RETURNING file_id
            """, (cvid, record.relpath, record.hash, file_type,
                  record.mtime, record.size, record.hash))
            
            file_id = cursor.fetchone()[0]
            
            # Route to envelope
            envelope = get_envelope_for_file(record.relpath, self.routing_table)
            
            # Skip queueing files with no work to do
            if envelope == 'E_SKIP':
                continue
            
            # Upsert build_queue with fingerprint binding (priority=0 for batch discovery)
            self.conn.execute("""
                INSERT INTO build_queue 
                    (file_id, envelope, priority, work_file_mtime, work_file_size, 
                     work_file_hash, status, created_at)
                VALUES (?, ?, 0, ?, ?, ?, 'pending', ?)
                ON CONFLICT (file_id, envelope, work_file_mtime, work_file_size, 
                             COALESCE(work_file_hash, '')) 
                DO NOTHING
            """, (file_id, envelope, record.mtime, record.size, record.hash, now))
        
        # Update progress
        self.conn.execute("""
            UPDATE discovery_queue
            SET last_path_processed = ?
            WHERE discovery_id = ?
        """, (last_path, discovery_id))
        
        self.conn.commit()
    
    def _renew_lease(self, discovery_id: int) -> None:
        """Renew lease to prevent timeout."""
        lease_until = time.time() + DISCOVERY_LEASE_SECONDS
        self.conn.execute("""
            UPDATE discovery_queue SET lease_expires_at = ?
            WHERE discovery_id = ?
        """, (lease_until, discovery_id))
        self.conn.commit()
    
    def _mark_error(self, discovery_id: int, message: str) -> None:
        """Mark discovery task as error."""
        self.conn.execute("""
            UPDATE discovery_queue
            SET status = 'error', error_message = ?
            WHERE discovery_id = ?
        """, (message, discovery_id))
        self.conn.commit()


def run_discovery(conn: sqlite3.Connection, max_tasks: Optional[int] = None) -> dict:
    """
    Run discovery worker until no more tasks.
    
    Returns summary of work done.
    """
    discovery = IncrementalDiscovery(conn)
    
    tasks_processed = 0
    total_files = 0
    
    while True:
        if max_tasks and tasks_processed >= max_tasks:
            break
        
        task = discovery.claim_task()
        if not task:
            break
        
        result = discovery.process_task(task)
        tasks_processed += 1
        
        if 'file_count' in result:
            total_files += result['file_count']
    
    return {
        'tasks_processed': tasks_processed,
        'files_discovered': total_files,
    }
