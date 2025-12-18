"""
Migration: Add contribution lifecycle columns to content_versions and create change_log tables.

This migration adds to content_versions:
- downloaded_at: When this version was downloaded/ingested
- source_mtime: Last modification time of source files
- symbols_extracted_at: When symbols were last extracted
- contributions_extracted_at: When contributions were last extracted
- is_stale: Flag indicating if re-extraction is needed

It also creates:
- change_log: Track when content versions are updated
- file_changes: Per-file change details with block summaries

And if needed, recreates contribution_units WITHOUT playset_id
(the new design extracts per content_version, not per playset).

Run this once to upgrade an existing database.
"""

import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.db.schema import get_connection


def get_table_columns(conn: sqlite3.Connection, table: str) -> list:
    """Get column names for a table."""
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Check if a table exists."""
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,)
    ).fetchone() is not None


def migrate_content_versions(conn: sqlite3.Connection) -> int:
    """Add lifecycle columns to content_versions."""
    columns = get_table_columns(conn, "content_versions")
    migrations_count = 0
    
    new_columns = [
        ("downloaded_at", "TEXT"),
        ("source_mtime", "TEXT"),
        ("symbols_extracted_at", "TEXT"),
        ("contributions_extracted_at", "TEXT"),
        ("is_stale", "INTEGER NOT NULL DEFAULT 1"),
    ]
    
    for col_name, col_type in new_columns:
        if col_name not in columns:
            sql = f"ALTER TABLE content_versions ADD COLUMN {col_name} {col_type}"
            print(f"  - Adding {col_name} to content_versions")
            conn.execute(sql)
            migrations_count += 1
    
    return migrations_count


def migrate_contribution_units(conn: sqlite3.Connection) -> int:
    """Migrate contribution_units to remove playset_id if present."""
    if not table_exists(conn, "contribution_units"):
        print("  - contribution_units table doesn't exist yet (will be created later)")
        return 0
    
    columns = get_table_columns(conn, "contribution_units")
    
    if "playset_id" not in columns:
        print("  - contribution_units already uses new schema (no playset_id)")
        return 0
    
    # Need to recreate the table without playset_id
    print("  - Migrating contribution_units to remove playset_id...")
    
    # SQLite doesn't support DROP COLUMN (before 3.35), so we recreate
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contribution_units_new (
            contrib_id TEXT PRIMARY KEY,
            content_version_id INTEGER NOT NULL,
            file_id INTEGER NOT NULL,
            domain TEXT NOT NULL,
            unit_key TEXT NOT NULL,
            node_path TEXT,
            relpath TEXT NOT NULL,
            line_number INTEGER,
            merge_behavior TEXT NOT NULL,
            symbols_json TEXT,
            refs_json TEXT,
            node_hash TEXT,
            summary TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id),
            FOREIGN KEY (file_id) REFERENCES files(file_id)
        )
    """)
    
    # Copy data (contributions will need to be re-extracted anyway since they were per-playset)
    conn.execute("""
        INSERT OR IGNORE INTO contribution_units_new 
        (contrib_id, content_version_id, file_id, domain, unit_key, node_path,
         relpath, line_number, merge_behavior, symbols_json, refs_json, node_hash, summary)
        SELECT contrib_id, content_version_id, file_id, domain, unit_key, node_path,
               relpath, line_number, merge_behavior, symbols_json, refs_json, node_hash, summary
        FROM contribution_units
    """)
    
    # Drop old table and rename
    conn.execute("DROP TABLE contribution_units")
    conn.execute("ALTER TABLE contribution_units_new RENAME TO contribution_units")
    
    # Recreate indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contrib_unit_key ON contribution_units(unit_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contrib_domain ON contribution_units(domain)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contrib_cv ON contribution_units(content_version_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contrib_file ON contribution_units(file_id)")
    
    print("  - contribution_units migrated successfully")
    return 1


def create_change_log_tables(conn: sqlite3.Connection) -> int:
    """Create change_log and file_changes tables."""
    migrations_count = 0
    
    if not table_exists(conn, "change_log"):
        print("  - Creating change_log table")
        conn.execute("""
            CREATE TABLE change_log (
                change_id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_version_id INTEGER NOT NULL,
                previous_version_id INTEGER,
                change_type TEXT NOT NULL,
                summary TEXT,
                detected_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id),
                FOREIGN KEY (previous_version_id) REFERENCES content_versions(content_version_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_changelog_cv ON change_log(content_version_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_changelog_type ON change_log(change_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_changelog_time ON change_log(detected_at)")
        migrations_count += 1
    
    if not table_exists(conn, "file_changes"):
        print("  - Creating file_changes table")
        conn.execute("""
            CREATE TABLE file_changes (
                file_change_id INTEGER PRIMARY KEY AUTOINCREMENT,
                change_id INTEGER NOT NULL,
                file_id INTEGER,
                relpath TEXT NOT NULL,
                change_type TEXT NOT NULL,
                old_content_hash TEXT,
                new_content_hash TEXT,
                blocks_changed_json TEXT,
                FOREIGN KEY (change_id) REFERENCES change_log(change_id),
                FOREIGN KEY (file_id) REFERENCES files(file_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_filechanges_change ON file_changes(change_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_filechanges_file ON file_changes(file_id)")
        migrations_count += 1
    
    return migrations_count


def migrate():
    """Run all migrations."""
    conn = get_connection()
    
    print("=" * 60)
    print("Contribution Lifecycle Migration")
    print("=" * 60)
    
    total_migrations = 0
    
    print("\n1. Migrating content_versions table...")
    total_migrations += migrate_content_versions(conn)
    
    print("\n2. Migrating contribution_units table...")
    total_migrations += migrate_contribution_units(conn)
    
    print("\n3. Creating change_log tables...")
    total_migrations += create_change_log_tables(conn)
    
    if total_migrations > 0:
        conn.commit()
        print(f"\n✅ {total_migrations} migrations completed successfully")
    else:
        print("\n✅ No migrations needed - schema is up to date")
    
    # Verify content_versions
    cv_columns = get_table_columns(conn, "content_versions")
    print(f"\nContent versions columns: {cv_columns}")
    
    # Verify contribution_units
    if table_exists(conn, "contribution_units"):
        cu_columns = get_table_columns(conn, "contribution_units")
        print(f"Contribution units columns: {cu_columns}")
        
        if "playset_id" in cu_columns:
            print("⚠️  WARNING: playset_id still present in contribution_units!")
    
    # Verify change tables
    print(f"change_log exists: {table_exists(conn, 'change_log')}")
    print(f"file_changes exists: {table_exists(conn, 'file_changes')}")


if __name__ == "__main__":
    migrate()
