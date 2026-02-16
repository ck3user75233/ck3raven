"""
Cryo Snapshots

Export and import frozen state captures for offline analysis,
sharing, and reproducibility.
"""

import sqlite3
import json
import gzip
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Iterator
from dataclasses import dataclass, asdict
from datetime import datetime

from ck3raven.db.models import Snapshot


@dataclass
class CryoManifest:
    """Manifest for a cryo export."""
    version: str = "1.0"
    name: str = ""
    description: str = ""
    created_at: str = ""
    vanilla_version: str = ""
    playset_name: Optional[str] = None
    parser_version: Optional[str] = None
    include_ast: bool = True
    include_refs: bool = True
    content_version_ids: List[int] = None
    file_count: int = 0
    total_size: int = 0
    checksum: str = ""
    
    def __post_init__(self):
        if self.content_version_ids is None:
            self.content_version_ids = []


def create_snapshot(
    conn: sqlite3.Connection,
    name: str,
    vanilla_version_id: int,
    playset_id: Optional[int] = None,
    parser_version_id: Optional[int] = None,
    description: Optional[str] = None,
    include_ast: bool = True,
    include_refs: bool = True,
    ruleset_version: Optional[str] = None
) -> Snapshot:
    """
    Create a new snapshot record.
    
    Args:
        conn: Database connection
        name: Snapshot name
        vanilla_version_id: Vanilla version to include
        playset_id: Optional playset to snapshot
        parser_version_id: Parser version used
        description: Description
        include_ast: Whether to include AST data
        include_refs: Whether to include symbol/ref data
        ruleset_version: Version of merge rules
    
    Returns:
        Created Snapshot
    """
    cursor = conn.execute("""
        INSERT INTO snapshots 
        (name, description, vanilla_version_id, playset_id, parser_version_id,
         ruleset_version, include_ast, include_refs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, description, vanilla_version_id, playset_id, parser_version_id,
          ruleset_version, int(include_ast), int(include_refs)))
    
    conn.commit()
    
    return get_snapshot(conn, cursor.lastrowid)


def get_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> Optional[Snapshot]:
    """Get a snapshot by ID."""
    row = conn.execute(
        "SELECT * FROM snapshots WHERE snapshot_id = ?",
        (snapshot_id,)
    ).fetchone()
    
    return Snapshot.from_row(row) if row else None


def list_snapshots(conn: sqlite3.Connection) -> List[Snapshot]:
    """List all snapshots."""
    rows = conn.execute(
        "SELECT * FROM snapshots ORDER BY created_at DESC"
    ).fetchall()
    
    return [Snapshot.from_row(r) for r in rows]


def add_content_to_snapshot(
    conn: sqlite3.Connection,
    snapshot_id: int,
    content_version_id: int
) -> None:
    """Add a content version to a snapshot."""
    conn.execute("""
        INSERT OR IGNORE INTO snapshot_members (snapshot_id, content_version_id)
        VALUES (?, ?)
    """, (snapshot_id, content_version_id))
    conn.commit()


def get_snapshot_contents(
    conn: sqlite3.Connection,
    snapshot_id: int
) -> List[int]:
    """Get all content version IDs in a snapshot."""
    rows = conn.execute("""
        SELECT content_version_id FROM snapshot_members
        WHERE snapshot_id = ?
    """, (snapshot_id,)).fetchall()
    
    return [r['content_version_id'] for r in rows]


def delete_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> bool:
    """
    Delete a snapshot and its memberships.
    
    Returns:
        True if deleted, False if not found
    """
    conn.execute(
        "DELETE FROM snapshot_members WHERE snapshot_id = ?",
        (snapshot_id,)
    )
    cursor = conn.execute(
        "DELETE FROM snapshots WHERE snapshot_id = ?",
        (snapshot_id,)
    )
    conn.commit()
    return cursor.rowcount > 0


def export_snapshot_to_file(
    conn: sqlite3.Connection,
    snapshot_id: int,
    output_path: Path,
    compress: bool = True
) -> CryoManifest:
    """
    Export a snapshot to a file.
    
    The export format is a gzipped JSON file containing:
    - Manifest with metadata
    - All file contents for included versions
    - AST data (if include_ast)
    - Symbol/ref data (if include_refs)
    
    Args:
        conn: Database connection
        snapshot_id: Snapshot to export
        output_path: Where to write the file
        compress: Whether to gzip the output
    
    Returns:
        CryoManifest with export details
    """
    snapshot = get_snapshot(conn, snapshot_id)
    if not snapshot:
        raise ValueError(f"Snapshot {snapshot_id} not found")
    
    content_version_ids = get_snapshot_contents(conn, snapshot_id)
    
    # Get vanilla version info (vanilla_versions table no longer exists)
    vanilla_version = 'unknown'
    
    # Get playset name if applicable
    playset_name = None
    if snapshot.playset_id:
        ps_row = conn.execute(
            "SELECT name FROM playsets WHERE playset_id = ?",
            (snapshot.playset_id,)
        ).fetchone()
        playset_name = ps_row['name'] if ps_row else None
    
    # Get parser version
    parser_version = None
    if snapshot.parser_version_id:
        pv_row = conn.execute(
            "SELECT version_string FROM parsers WHERE parser_version_id = ?",
            (snapshot.parser_version_id,)
        ).fetchone()
        parser_version = pv_row['version_string'] if pv_row else None
    
    # Collect data
    export_data = {
        'manifest': None,  # Will be filled at the end
        'vanilla_version': {},
        'files': [],
        'file_contents': {},  # content_hash -> content
        'asts': [],
        'symbols': [],
        'refs': [],
    }
    
    file_count = 0
    total_size = 0
    
    # Collect files and content
    for cvid in content_version_ids:
        rows = conn.execute("""
            SELECT f.*, fc.content_text, fc.size
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE f.content_version_id = ?
        """, (cvid,)).fetchall()
        
        for row in rows:
            file_count += 1
            total_size += row['size'] or 0
            
            export_data['files'].append({
                'content_version_id': row['content_version_id'],
                'relpath': row['relpath'],
                'content_hash': row['content_hash'],
                'file_type': row['file_type'],
            })
            
            # Store content if not already stored
            if row['content_hash'] not in export_data['file_contents']:
                export_data['file_contents'][row['content_hash']] = row['content_text']
    
    # Collect AST if requested
    if snapshot.include_ast:
        for cvid in content_version_ids:
            rows = conn.execute("""
                SELECT a.* FROM asts a
                JOIN files f ON f.content_hash = a.content_hash
                WHERE f.content_version_id = ?
            """, (cvid,)).fetchall()
            
            for row in rows:
                export_data['asts'].append({
                    'content_hash': row['content_hash'],
                    'parser_version_id': row['parser_version_id'],
                    'ast_blob': row['ast_blob'].decode('utf-8') if row['ast_blob'] else None,
                    'parse_ok': row['parse_ok'],
                    'node_count': row['node_count'],
                })
    
    # Collect symbols/refs if requested
    if snapshot.include_refs:
        for cvid in content_version_ids:
            sym_rows = conn.execute(
                "SELECT * FROM symbols WHERE content_version_id = ?",
                (cvid,)
            ).fetchall()
            
            for row in sym_rows:
                export_data['symbols'].append({
                    'symbol_type': row['symbol_type'],
                    'name': row['name'],
                    'scope': row['scope'],
                    'line_number': row['line_number'],
                    'content_version_id': row['content_version_id'],
                })
            
            ref_rows = conn.execute(
                "SELECT * FROM refs WHERE content_version_id = ?",
                (cvid,)
            ).fetchall()
            
            for row in ref_rows:
                export_data['refs'].append({
                    'ref_type': row['ref_type'],
                    'name': row['name'],
                    'line_number': row['line_number'],
                    'context': row['context'],
                    'content_version_id': row['content_version_id'],
                })
    
    # Create manifest
    manifest = CryoManifest(
        version="1.0",
        name=snapshot.name,
        description=snapshot.description or '',
        created_at=datetime.now().isoformat(),
        vanilla_version=vanilla_version,
        playset_name=playset_name,
        parser_version=parser_version,
        include_ast=snapshot.include_ast,
        include_refs=snapshot.include_refs,
        content_version_ids=content_version_ids,
        file_count=file_count,
        total_size=total_size,
    )
    
    export_data['manifest'] = asdict(manifest)
    
    # Compute checksum of data
    data_json = json.dumps(export_data, sort_keys=True, separators=(',', ':'))
    manifest.checksum = hashlib.sha256(data_json.encode()).hexdigest()
    export_data['manifest']['checksum'] = manifest.checksum
    
    # Write to file
    data_bytes = json.dumps(export_data, separators=(',', ':')).encode('utf-8')
    
    if compress:
        with gzip.open(output_path, 'wb') as f:
            f.write(data_bytes)
    else:
        output_path.write_bytes(data_bytes)
    
    return manifest


def import_snapshot_from_file(
    conn: sqlite3.Connection,
    input_path: Path,
    new_name: Optional[str] = None
) -> Snapshot:
    """
    Import a snapshot from a file.
    
    Args:
        conn: Database connection
        input_path: Path to cryo file
        new_name: Override name for the snapshot
    
    Returns:
        Imported Snapshot
    """
    # Read and decompress
    try:
        with gzip.open(input_path, 'rb') as f:
            data_bytes = f.read()
    except gzip.BadGzipFile:
        # Not compressed
        data_bytes = input_path.read_bytes()
    
    export_data = json.loads(data_bytes.decode('utf-8'))
    manifest = CryoManifest(**export_data['manifest'])
    
    # vanilla_versions table no longer exists — use placeholder
    vanilla_version_id = None
    
    # Create snapshot
    snapshot = create_snapshot(
        conn,
        name=new_name or manifest.name,
        vanilla_version_id=vanilla_version_id,
        description=f"Imported from {input_path.name}",
        include_ast=manifest.include_ast,
        include_refs=manifest.include_refs,
    )
    
    # Import file contents
    file_contents = export_data.get('file_contents', {})
    for content_hash, content_text in file_contents.items():
        conn.execute("""
            INSERT OR IGNORE INTO file_contents (content_hash, content_blob, content_text, size, is_binary)
            VALUES (?, ?, ?, ?, 0)
        """, (content_hash, (content_text or '').encode('utf-8'), content_text, len(content_text or '')))
    
    # We would need to create content_versions for files, but that's complex
    # For now, just store the data and mark the snapshot as imported
    
    conn.commit()
    
    return snapshot


def get_snapshot_stats(conn: sqlite3.Connection, snapshot_id: int) -> Dict[str, Any]:
    """Get statistics about a snapshot."""
    snapshot = get_snapshot(conn, snapshot_id)
    if not snapshot:
        return {}
    
    content_version_ids = get_snapshot_contents(conn, snapshot_id)
    
    stats = {
        'name': snapshot.name,
        'content_versions': len(content_version_ids),
        'files': 0,
        'total_size': 0,
        'asts': 0,
        'symbols': 0,
        'refs': 0,
    }
    
    for cvid in content_version_ids:
        row = conn.execute("""
            SELECT COUNT(*) as cnt, SUM(fc.size) as total
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE f.content_version_id = ?
        """, (cvid,)).fetchone()
        
        stats['files'] += row['cnt'] or 0
        stats['total_size'] += row['total'] or 0
        
        if snapshot.include_refs:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM symbols WHERE content_version_id = ?",
                (cvid,)
            ).fetchone()
            stats['symbols'] += row['cnt'] or 0
            
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM refs WHERE content_version_id = ?",
                (cvid,)
            ).fetchone()
            stats['refs'] += row['cnt'] or 0
    
    return stats
