"""
QBuilder Schema — Canonical Phase 1

Two-queue model with fingerprint binding. No parallel constructs.

Key identities:
- content_version_id (cvid): Root scope identity (vanilla, mod package, etc.)
- file_id: Stable file identity, unique per (cvid, relpath)
- fingerprint: (mtime, size, hash) - exact bytes this work item targets

Rules:
- discovery_queue references cvid ONLY (no duplicate root_type/path/name)
- build_queue references file_id ONLY (no duplicate relpath/cvid)
- fingerprint fields bind work to exact file bytes
- derived artifacts must store matching fingerprint
"""

import sqlite3
from typing import Optional


QBUILDER_SCHEMA_SQL = """
-- ============================================================================
-- DISCOVERY QUEUE (Root Enumeration)
-- ============================================================================
-- Each row = "enumerate files under this content_version's root"
-- Identity is cvid ONLY. Paths/names derived via joins.

CREATE TABLE IF NOT EXISTS discovery_queue (
    discovery_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_version_id INTEGER NOT NULL,    -- FK to content_versions (sole root identity)
    
    -- Status and lease
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'processing', 'completed', 'error')),
    lease_expires_at REAL,
    lease_holder TEXT,
    
    -- Progress (optional, for mid-tree resume)
    last_path_processed TEXT,
    
    -- Metadata
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    
    UNIQUE(content_version_id)
);

CREATE INDEX IF NOT EXISTS idx_discovery_claim 
    ON discovery_queue(status, lease_expires_at, discovery_id);


-- ============================================================================
-- FILES TABLE (Canonical Identity + Fingerprint)
-- ============================================================================
-- file_id is stable identity for (cvid, relpath).
-- Fingerprint columns track current observed bytes.

-- Note: We ALTER existing files table to add fingerprint columns
-- rather than recreate, to preserve existing file_ids.

-- These will be run as separate statements if columns don't exist:
-- ALTER TABLE files ADD COLUMN file_mtime REAL;
-- ALTER TABLE files ADD COLUMN file_size INTEGER;
-- ALTER TABLE files ADD COLUMN file_hash TEXT;


-- ============================================================================
-- BUILD QUEUE (File Envelope Execution)
-- ============================================================================
-- Each row = "execute envelope E for file F with fingerprint P"
-- References file_id ONLY. Paths/cvid derived via joins.
-- Fingerprint fields bind this work item to exact bytes.

CREATE TABLE IF NOT EXISTS build_queue (
    build_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,               -- FK to files (sole file identity)
    envelope TEXT NOT NULL,                 -- Routing table envelope code
    priority INTEGER NOT NULL DEFAULT 0,    -- 0=normal, 1=flash (higher = process first)
    
    -- Fingerprint binding (copied from files at enqueue time)
    work_file_mtime REAL NOT NULL,
    work_file_size INTEGER NOT NULL,
    work_file_hash TEXT,
    
    -- Status and lease
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'processing', 'completed', 'error')),
    lease_expires_at REAL,
    lease_holder TEXT,
    
    -- Metadata
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    reclaim_count INTEGER NOT NULL DEFAULT 0,  -- Times reclaimed due to expired lease (crash recovery)
    error_message TEXT,
    error_step TEXT                         -- Which step failed (for debugging only)
);

-- Uniqueness: one work item per (file, envelope, fingerprint)
-- If file bytes change, enqueue NEW row with new fingerprint
-- Use index with expression for NULL-safe hash comparison
CREATE UNIQUE INDEX IF NOT EXISTS idx_build_unique_work
    ON build_queue(file_id, envelope, work_file_mtime, work_file_size, COALESCE(work_file_hash, ''));

-- Claim order: priority DESC (flash first), then build_id ASC (FIFO within priority)
CREATE INDEX IF NOT EXISTS idx_build_claim 
    ON build_queue(status, priority DESC, build_id);
CREATE INDEX IF NOT EXISTS idx_build_file 
    ON build_queue(file_id);
"""


def init_qbuilder_schema(conn: sqlite3.Connection) -> None:
    """Initialize QBuilder schema tables and add fingerprint columns to files."""
    # Create queue tables
    conn.executescript(QBUILDER_SCHEMA_SQL)
    
    # Add fingerprint columns to files table if they don't exist
    _add_column_if_missing(conn, 'files', 'file_mtime', 'REAL')
    _add_column_if_missing(conn, 'files', 'file_size', 'INTEGER')
    _add_column_if_missing(conn, 'files', 'file_hash', 'TEXT')
    
    # Add priority column to build_queue if not exists (migration for existing DBs)
    _add_column_if_missing(conn, 'build_queue', 'priority', 'INTEGER DEFAULT 0')
    
    # Add reclaim_count for tracking lease expirations (crash recovery)
    _add_column_if_missing(conn, 'build_queue', 'reclaim_count', 'INTEGER DEFAULT 0')
    
    # Add AST validity signature fields (file_id + input fingerprint)
    # An AST is valid only if its signature matches current file fingerprint
    _add_column_if_missing(conn, 'asts', 'file_id', 'INTEGER')
    _add_column_if_missing(conn, 'asts', 'src_file_mtime', 'REAL')
    _add_column_if_missing(conn, 'asts', 'src_file_size', 'INTEGER')
    _add_column_if_missing(conn, 'asts', 'src_file_hash', 'TEXT')
    
    # Create unique index on asts(file_id, src_file_hash) for validity lookup
    try:
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_asts_file_signature
            ON asts(file_id, COALESCE(src_file_hash, ''))
        """)
    except sqlite3.OperationalError:
        pass  # Index may already exist with different name
    
    conn.commit()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, dtype: str) -> None:
    """Add column to table if it doesn't exist."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = {row[1] for row in cursor.fetchall()}
    
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {dtype}")


def reset_qbuilder_tables(conn: sqlite3.Connection) -> None:
    """Drop and recreate QBuilder queue tables for fresh build."""
    drop_sql = """
        DROP INDEX IF EXISTS idx_build_unique_work;
        DROP INDEX IF EXISTS idx_build_claim;
        DROP INDEX IF EXISTS idx_build_file;
        DROP INDEX IF EXISTS idx_discovery_claim;
        DROP TABLE IF EXISTS build_queue;
        DROP TABLE IF EXISTS discovery_queue;
    """
    conn.executescript(drop_sql)
    init_qbuilder_schema(conn)


def get_queue_counts(conn: sqlite3.Connection) -> dict:
    """Get current queue status counts."""
    discovery = {}
    build = {}
    
    # Check if tables exist
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    
    if 'discovery_queue' in tables:
        for row in conn.execute("""
            SELECT status, COUNT(*) as count FROM discovery_queue GROUP BY status
        """):
            discovery[row[0]] = row[1]
    
    if 'build_queue' in tables:
        for row in conn.execute("""
            SELECT status, COUNT(*) as count FROM build_queue GROUP BY status
        """):
            build[row[0]] = row[1]
    
    return {
        'discovery': discovery,
        'build': build,
        'discovery_total': sum(discovery.values()),
        'build_total': sum(build.values()),
    }


def get_root_path_for_cvid(conn: sqlite3.Connection, cvid: int) -> Optional[str]:
    """
    Resolve content_version_id to filesystem root path.
    
    This is THE canonical way to get a root path from cvid.
    Joins through content_versions → mod_packages (or vanilla).
    """
    # Check if vanilla
    row = conn.execute("""
        SELECT cv.kind, mp.source_path, vv.ck3_version
        FROM content_versions cv
        LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
        LEFT JOIN vanilla_versions vv ON cv.vanilla_version_id = vv.vanilla_version_id
        WHERE cv.content_version_id = ?
    """, (cvid,)).fetchone()
    
    if not row:
        return None
    
    kind = row[0]
    
    if kind == 'vanilla':
        # For vanilla, we need to get the path from config or environment
        # This is a known limitation - vanilla path should be in content_versions
        # or derived from vanilla_versions + config
        return None  # TODO: implement vanilla path resolution
    else:
        return row[1]  # mod_packages.source_path
