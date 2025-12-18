"""
Migration: Add contribution lifecycle columns to playsets table.

This migration adds:
- contributions_stale: Flag indicating if contributions need rescan
- contributions_hash: Hash of load order for cache validation
- contributions_scanned_at: When contributions were last scanned

Run this once to upgrade an existing database.
"""

import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.db.schema import get_connection


def migrate():
    """Add staleness tracking columns to playsets table."""
    conn = get_connection()
    
    # Check if columns already exist
    columns = [r[1] for r in conn.execute("PRAGMA table_info(playsets)").fetchall()]
    
    migrations_needed = []
    
    if 'contributions_stale' not in columns:
        migrations_needed.append(
            "ALTER TABLE playsets ADD COLUMN contributions_stale INTEGER NOT NULL DEFAULT 1"
        )
    
    if 'contributions_hash' not in columns:
        migrations_needed.append(
            "ALTER TABLE playsets ADD COLUMN contributions_hash TEXT"
        )
    
    if 'contributions_scanned_at' not in columns:
        migrations_needed.append(
            "ALTER TABLE playsets ADD COLUMN contributions_scanned_at TEXT"
        )
    
    if not migrations_needed:
        print("✅ No migrations needed - columns already exist")
        return
    
    print(f"Running {len(migrations_needed)} migrations...")
    
    for sql in migrations_needed:
        print(f"  - {sql[:60]}...")
        conn.execute(sql)
    
    conn.commit()
    print("✅ Migrations complete")
    
    # Verify
    columns = [r[1] for r in conn.execute("PRAGMA table_info(playsets)").fetchall()]
    print(f"Playsets columns: {columns}")


if __name__ == "__main__":
    migrate()
