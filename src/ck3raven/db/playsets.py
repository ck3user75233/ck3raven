"""
Playsets Management

Create and manage mod playsets with load order.
Enforces maximum of 5 active playsets to save resources.
"""

import sqlite3
import json
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from ck3raven.db.models import Playset, PlaysetMod, ContentVersion


# Maximum number of active playsets
MAX_ACTIVE_PLAYSETS = 5


def create_playset(
    conn: sqlite3.Connection,
    name: str,
    vanilla_version_id: int,
    description: Optional[str] = None,
    is_active: bool = False
) -> Playset:
    """
    Create a new playset.
    
    Args:
        conn: Database connection
        name: Playset name
        vanilla_version_id: Which vanilla version to use
        description: Optional description
        is_active: Whether to mark as active
    
    Returns:
        Created Playset
    
    Raises:
        ValueError: If activating would exceed MAX_ACTIVE_PLAYSETS
    """
    if is_active:
        active_count = get_active_playset_count(conn)
        if active_count >= MAX_ACTIVE_PLAYSETS:
            raise ValueError(
                f"Cannot create active playset: already have {active_count} active "
                f"(max {MAX_ACTIVE_PLAYSETS}). Deactivate one first."
            )
    
    cursor = conn.execute("""
        INSERT INTO playsets (name, vanilla_version_id, description, is_active)
        VALUES (?, ?, ?, ?)
    """, (name, vanilla_version_id, description, int(is_active)))
    
    conn.commit()
    
    return get_playset(conn, cursor.lastrowid)


def get_playset(conn: sqlite3.Connection, playset_id: int) -> Optional[Playset]:
    """Get a playset by ID."""
    row = conn.execute(
        "SELECT * FROM playsets WHERE playset_id = ?",
        (playset_id,)
    ).fetchone()
    
    return Playset.from_row(row) if row else None


def get_playset_by_name(conn: sqlite3.Connection, name: str) -> Optional[Playset]:
    """Get a playset by name."""
    row = conn.execute(
        "SELECT * FROM playsets WHERE name = ?",
        (name,)
    ).fetchone()
    
    return Playset.from_row(row) if row else None


def list_playsets(
    conn: sqlite3.Connection,
    active_only: bool = False
) -> List[Playset]:
    """List all playsets."""
    sql = "SELECT * FROM playsets"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY updated_at DESC"
    
    rows = conn.execute(sql).fetchall()
    return [Playset.from_row(r) for r in rows]


def update_playset(
    conn: sqlite3.Connection,
    playset_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None
) -> Playset:
    """
    Update a playset.
    
    Args:
        conn: Database connection
        playset_id: ID of playset to update
        name: New name (if provided)
        description: New description (if provided)
        is_active: New active state (if provided)
    
    Returns:
        Updated Playset
    """
    updates = []
    params = []
    
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    
    if is_active is not None:
        if is_active:
            active_count = get_active_playset_count(conn)
            current = get_playset(conn, playset_id)
            if current and not current.is_active and active_count >= MAX_ACTIVE_PLAYSETS:
                raise ValueError(
                    f"Cannot activate: already have {active_count} active playsets "
                    f"(max {MAX_ACTIVE_PLAYSETS})"
                )
        updates.append("is_active = ?")
        params.append(int(is_active))
    
    if not updates:
        return get_playset(conn, playset_id)
    
    updates.append("updated_at = datetime('now')")
    params.append(playset_id)
    
    conn.execute(
        f"UPDATE playsets SET {', '.join(updates)} WHERE playset_id = ?",
        params
    )
    conn.commit()
    
    return get_playset(conn, playset_id)


def delete_playset(conn: sqlite3.Connection, playset_id: int) -> bool:
    """
    Delete a playset and its mod memberships.
    
    Returns:
        True if deleted, False if not found
    """
    # Delete memberships first
    conn.execute(
        "DELETE FROM playset_mods WHERE playset_id = ?",
        (playset_id,)
    )
    
    cursor = conn.execute(
        "DELETE FROM playsets WHERE playset_id = ?",
        (playset_id,)
    )
    
    conn.commit()
    return cursor.rowcount > 0


def get_active_playset_count(conn: sqlite3.Connection) -> int:
    """Get the number of active playsets."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM playsets WHERE is_active = 1"
    ).fetchone()
    return row['cnt']


def add_mod_to_playset(
    conn: sqlite3.Connection,
    playset_id: int,
    content_version_id: int,
    load_order_index: Optional[int] = None
) -> PlaysetMod:
    """
    Add a mod to a playset.
    
    Args:
        conn: Database connection
        playset_id: Target playset
        content_version_id: Mod content version to add
        load_order_index: Position in load order (appended to end if None)
    
    Returns:
        PlaysetMod record
    """
    if load_order_index is None:
        # Find next available index
        row = conn.execute("""
            SELECT COALESCE(MAX(load_order_index), -1) + 1 as next_idx
            FROM playset_mods WHERE playset_id = ?
        """, (playset_id,)).fetchone()
        load_order_index = row['next_idx']
    
    conn.execute("""
        INSERT OR REPLACE INTO playset_mods 
        (playset_id, content_version_id, load_order_index, enabled)
        VALUES (?, ?, ?, 1)
    """, (playset_id, content_version_id, load_order_index))
    
    conn.commit()
    
    return PlaysetMod(
        playset_id=playset_id,
        content_version_id=content_version_id,
        load_order_index=load_order_index,
        enabled=True
    )


def remove_mod_from_playset(
    conn: sqlite3.Connection,
    playset_id: int,
    content_version_id: int
) -> bool:
    """
    Remove a mod from a playset.
    
    Returns:
        True if removed, False if not found
    """
    cursor = conn.execute("""
        DELETE FROM playset_mods 
        WHERE playset_id = ? AND content_version_id = ?
    """, (playset_id, content_version_id))
    
    conn.commit()
    return cursor.rowcount > 0


def set_mod_enabled(
    conn: sqlite3.Connection,
    playset_id: int,
    content_version_id: int,
    enabled: bool
) -> bool:
    """
    Enable or disable a mod in a playset.
    
    Returns:
        True if updated, False if not found
    """
    cursor = conn.execute("""
        UPDATE playset_mods SET enabled = ?
        WHERE playset_id = ? AND content_version_id = ?
    """, (int(enabled), playset_id, content_version_id))
    
    conn.commit()
    return cursor.rowcount > 0


def reorder_mods(
    conn: sqlite3.Connection,
    playset_id: int,
    content_version_ids: List[int]
) -> None:
    """
    Reorder mods in a playset.
    
    Args:
        conn: Database connection
        playset_id: Target playset
        content_version_ids: List of content_version_ids in desired order
    """
    for idx, cvid in enumerate(content_version_ids):
        conn.execute("""
            UPDATE playset_mods SET load_order_index = ?
            WHERE playset_id = ? AND content_version_id = ?
        """, (idx, playset_id, cvid))
    
    conn.commit()


def get_playset_mods(
    conn: sqlite3.Connection,
    playset_id: int,
    enabled_only: bool = False
) -> List[Tuple[PlaysetMod, ContentVersion]]:
    """
    Get all mods in a playset with their content versions.
    
    Args:
        conn: Database connection
        playset_id: Target playset
        enabled_only: Only return enabled mods
    
    Returns:
        List of (PlaysetMod, ContentVersion) tuples in load order
    """
    sql = """
        SELECT pm.*, cv.*
        FROM playset_mods pm
        JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
        WHERE pm.playset_id = ?
    """
    if enabled_only:
        sql += " AND pm.enabled = 1"
    sql += " ORDER BY pm.load_order_index"
    
    results = []
    for row in conn.execute(sql, (playset_id,)):
        pm = PlaysetMod(
            playset_id=row['playset_id'],
            content_version_id=row['content_version_id'],
            load_order_index=row['load_order_index'],
            enabled=bool(row['enabled'])
        )
        cv = ContentVersion.from_row(row)
        results.append((pm, cv))
    
    return results


def get_playset_load_order(
    conn: sqlite3.Connection,
    playset_id: int,
    enabled_only: bool = True
) -> List[int]:
    """
    Get content version IDs in load order.
    
    Returns:
        List of content_version_ids in load order
    """
    sql = """
        SELECT content_version_id FROM playset_mods
        WHERE playset_id = ?
    """
    if enabled_only:
        sql += " AND enabled = 1"
    sql += " ORDER BY load_order_index"
    
    rows = conn.execute(sql, (playset_id,)).fetchall()
    return [r['content_version_id'] for r in rows]


def compute_load_order_hash(load_order: List[int]) -> str:
    """
    Compute a hash of the load order for cache keying.
    
    Args:
        load_order: List of content_version_ids
    
    Returns:
        Hash string
    """
    import hashlib
    data = ','.join(str(cvid) for cvid in load_order)
    return hashlib.sha256(data.encode()).hexdigest()


def clone_playset(
    conn: sqlite3.Connection,
    playset_id: int,
    new_name: str
) -> Playset:
    """
    Clone a playset with all its mods.
    
    Args:
        conn: Database connection
        playset_id: Source playset
        new_name: Name for the clone
    
    Returns:
        New Playset
    """
    source = get_playset(conn, playset_id)
    if not source:
        raise ValueError(f"Playset {playset_id} not found")
    
    # Create new playset
    new_playset = create_playset(
        conn,
        name=new_name,
        vanilla_version_id=source.vanilla_version_id,
        description=f"Clone of {source.name}",
        is_active=False
    )
    
    # Copy mods
    mods = get_playset_mods(conn, playset_id)
    for pm, cv in mods:
        add_mod_to_playset(conn, new_playset.playset_id, pm.content_version_id, pm.load_order_index)
        if not pm.enabled:
            set_mod_enabled(conn, new_playset.playset_id, pm.content_version_id, False)
    
    return new_playset
