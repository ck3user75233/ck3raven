"""
Database Schema for ck3raven

SQLite schema with content-addressed storage, versioning, and full traceability.
All content is deduplicated by SHA256 hash.
"""

import sqlite3
from pathlib import Path
from typing import Optional
import threading

# Schema version - bump when schema changes
DATABASE_VERSION = 1

# Thread-local storage for connections
_local = threading.local()

# Default database path
DEFAULT_DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"


SCHEMA_SQL = """
-- ============================================================================
-- VERSIONING & IDENTITIES
-- ============================================================================

-- Vanilla game versions (immutable once stored)
CREATE TABLE IF NOT EXISTS vanilla_versions (
    vanilla_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ck3_version TEXT NOT NULL,              -- e.g., "1.13.2"
    dlc_set_json TEXT NOT NULL DEFAULT '[]', -- JSON array of DLC IDs enabled
    build_hash TEXT,                         -- Optional build identifier
    ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
    notes TEXT,
    UNIQUE(ck3_version, dlc_set_json)
);

-- Mod package identities (e.g., Steam Workshop ID)
CREATE TABLE IF NOT EXISTS mod_packages (
    mod_package_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workshop_id TEXT,                        -- Steam Workshop ID (can be NULL for local mods)
    name TEXT NOT NULL,
    source_path TEXT,                        -- Original filesystem path
    source_url TEXT,                         -- Workshop URL or other source
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(workshop_id)
);

-- Content versions - specific version of vanilla or a mod
-- Keyed by content_root_hash (hash of all file hashes + paths)
CREATE TABLE IF NOT EXISTS content_versions (
    content_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('vanilla', 'mod')),
    vanilla_version_id INTEGER,              -- FK if kind='vanilla'
    mod_package_id INTEGER,                  -- FK if kind='mod'
    content_root_hash TEXT NOT NULL UNIQUE,  -- SHA256 of sorted (relpath, file_hash) pairs
    file_count INTEGER NOT NULL DEFAULT 0,
    total_size INTEGER NOT NULL DEFAULT 0,
    ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
    -- Lifecycle tracking
    downloaded_at TEXT,                      -- When mod was downloaded from workshop (for mods)
    source_mtime TEXT,                       -- Latest mtime of source directory
    symbols_extracted_at TEXT,               -- When symbols were extracted
    contributions_extracted_at TEXT,         -- When contributions were extracted
    is_stale INTEGER NOT NULL DEFAULT 1,     -- 1 = needs re-check, 0 = current
    FOREIGN KEY (vanilla_version_id) REFERENCES vanilla_versions(vanilla_version_id),
    FOREIGN KEY (mod_package_id) REFERENCES mod_packages(mod_package_id)
);

-- ============================================================================
-- FILES & CONTENT (Content-Addressed Storage)
-- ============================================================================

-- File contents - deduplicated by SHA256 hash
-- Same content appearing in multiple mods/versions stored once
CREATE TABLE IF NOT EXISTS file_contents (
    content_hash TEXT PRIMARY KEY,           -- SHA256 of raw bytes
    content_blob BLOB NOT NULL,              -- Raw file content
    content_text TEXT,                       -- Text content (if text file)
    size INTEGER NOT NULL,
    encoding_guess TEXT,                     -- 'utf-8', 'latin-1', etc.
    is_binary INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- File records - maps files to content versions
-- Links a specific file path in a version to its content
CREATE TABLE IF NOT EXISTS files (
    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_version_id INTEGER NOT NULL,
    relpath TEXT NOT NULL,                   -- Relative path within mod/vanilla (normalized)
    content_hash TEXT NOT NULL,              -- FK to file_contents
    file_type TEXT,                          -- 'script', 'localization', 'gfx', 'gui', 'other'
    mtime TEXT,                              -- Last modified time from filesystem
    deleted INTEGER NOT NULL DEFAULT 0,      -- Soft delete flag
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id),
    FOREIGN KEY (content_hash) REFERENCES file_contents(content_hash),
    UNIQUE(content_version_id, relpath)
);

CREATE INDEX IF NOT EXISTS idx_files_content_hash ON files(content_hash);
CREATE INDEX IF NOT EXISTS idx_files_relpath ON files(relpath);
CREATE INDEX IF NOT EXISTS idx_files_type ON files(file_type);

-- ============================================================================
-- PARSER VERSIONING
-- ============================================================================

-- Parser versions - track parser changes for cache invalidation
CREATE TABLE IF NOT EXISTS parsers (
    parser_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_string TEXT NOT NULL UNIQUE,     -- e.g., "1.0.0"
    git_commit TEXT,                         -- Git commit hash
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================================
-- AST CACHE
-- ============================================================================

-- AST records - keyed by (content_hash, parser_version_id)
-- Same file parsed by same parser version = same AST
-- Note: content_hash is NOT a FK - AST can exist without storing content blob
CREATE TABLE IF NOT EXISTS asts (
    ast_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT NOT NULL,              -- SHA256 of source content (not FK)
    parser_version_id INTEGER NOT NULL,      -- FK to parsers
    ast_blob BLOB NOT NULL,                  -- Serialized AST (JSON or msgpack)
    ast_format TEXT NOT NULL DEFAULT 'json', -- 'json', 'msgpack'
    parse_ok INTEGER NOT NULL DEFAULT 1,     -- 1 = success, 0 = failed
    node_count INTEGER,                      -- Number of AST nodes
    diagnostics_json TEXT,                   -- Parse errors/warnings as JSON
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (parser_version_id) REFERENCES parsers(parser_version_id),
    UNIQUE(content_hash, parser_version_id)
);

CREATE INDEX IF NOT EXISTS idx_asts_content_hash ON asts(content_hash);
CREATE INDEX IF NOT EXISTS idx_asts_parse_ok ON asts(parse_ok);

-- ============================================================================
-- REFERENCE GRAPH (Symbols & References)
-- ============================================================================

-- Symbols - things that define names/IDs/keys
CREATE TABLE IF NOT EXISTS symbols (
    symbol_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_type TEXT NOT NULL,               -- 'tradition', 'event', 'decision', 'scripted_effect', etc.
    name TEXT NOT NULL,                      -- The symbol name/ID
    scope TEXT,                              -- Scope/domain (e.g., namespace for events)
    defining_ast_id INTEGER,                 -- FK to asts
    defining_file_id INTEGER NOT NULL,       -- FK to files
    content_version_id INTEGER NOT NULL,     -- FK to content_versions
    ast_node_path TEXT,                      -- JSON path to AST node (for exact location)
    line_number INTEGER,
    metadata_json TEXT,                      -- Additional symbol metadata
    FOREIGN KEY (defining_ast_id) REFERENCES asts(ast_id),
    FOREIGN KEY (defining_file_id) REFERENCES files(file_id),
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
);

CREATE INDEX IF NOT EXISTS idx_symbols_type ON symbols(symbol_type);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_type_name ON symbols(symbol_type, name);
CREATE INDEX IF NOT EXISTS idx_symbols_content_version ON symbols(content_version_id);

-- References - places that use symbols
CREATE TABLE IF NOT EXISTS refs (
    ref_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_type TEXT NOT NULL,                  -- Type of reference (e.g., 'tradition_ref', 'event_ref')
    name TEXT NOT NULL,                      -- Referenced name
    using_ast_id INTEGER,                    -- FK to asts
    using_file_id INTEGER NOT NULL,          -- FK to files
    content_version_id INTEGER NOT NULL,     -- FK to content_versions
    ast_node_path TEXT,                      -- JSON path to AST node
    line_number INTEGER,
    context TEXT,                            -- Context (e.g., which effect/trigger)
    resolution_status TEXT NOT NULL DEFAULT 'unknown', -- 'resolved', 'unresolved', 'dynamic', 'unknown'
    resolved_symbol_id INTEGER,              -- FK to symbols if resolved
    candidates_json TEXT,                    -- Best-guess candidates if unresolved
    FOREIGN KEY (using_ast_id) REFERENCES asts(ast_id),
    FOREIGN KEY (using_file_id) REFERENCES files(file_id),
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id),
    FOREIGN KEY (resolved_symbol_id) REFERENCES symbols(symbol_id)
);

CREATE INDEX IF NOT EXISTS idx_refs_type ON refs(ref_type);
CREATE INDEX IF NOT EXISTS idx_refs_name ON refs(name);
CREATE INDEX IF NOT EXISTS idx_refs_type_name ON refs(ref_type, name);
CREATE INDEX IF NOT EXISTS idx_refs_content_version ON refs(content_version_id);
CREATE INDEX IF NOT EXISTS idx_refs_resolution ON refs(resolution_status);

-- ============================================================================
-- PLAYSETS & BUILDS
-- ============================================================================

-- Playsets - user-defined mod collections with load order
CREATE TABLE IF NOT EXISTS playsets (
    playset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    vanilla_version_id INTEGER NOT NULL,     -- FK to vanilla_versions
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 0,    -- Max 5 active at once (enforced in code)
    -- Contribution lifecycle tracking
    contributions_hash TEXT,                 -- Hash of current contribution state
    contributions_stale INTEGER NOT NULL DEFAULT 1,  -- 1 = needs rescan, 0 = up to date
    contributions_scanned_at TEXT,           -- When last scanned
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vanilla_version_id) REFERENCES vanilla_versions(vanilla_version_id)
);

-- Playset mod membership with load order
CREATE TABLE IF NOT EXISTS playset_mods (
    playset_id INTEGER NOT NULL,
    content_version_id INTEGER NOT NULL,     -- FK to content_versions (mod version)
    load_order_index INTEGER NOT NULL,       -- Lower = loaded first, higher = wins in OVERRIDE
    enabled INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (playset_id, content_version_id),
    FOREIGN KEY (playset_id) REFERENCES playsets(playset_id),
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
);

CREATE INDEX IF NOT EXISTS idx_playset_mods_order ON playset_mods(playset_id, load_order_index);

-- Optional: Build cache for resolved states
CREATE TABLE IF NOT EXISTS builds (
    build_id INTEGER PRIMARY KEY AUTOINCREMENT,
    playset_id INTEGER NOT NULL,
    ruleset_version TEXT NOT NULL,           -- Version of merge rules used
    load_order_hash TEXT NOT NULL,           -- Hash of load order for cache key
    resolved_at TEXT NOT NULL DEFAULT (datetime('now')),
    build_metadata_json TEXT,
    FOREIGN KEY (playset_id) REFERENCES playsets(playset_id),
    UNIQUE(playset_id, ruleset_version, load_order_hash)
);

-- ============================================================================
-- SNAPSHOTS (Cryo)
-- ============================================================================

-- Snapshots - frozen immutable state captures
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    vanilla_version_id INTEGER NOT NULL,
    playset_id INTEGER,                      -- Optional: snapshot of a playset
    parser_version_id INTEGER,
    ruleset_version TEXT,
    include_ast INTEGER NOT NULL DEFAULT 1,
    include_refs INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vanilla_version_id) REFERENCES vanilla_versions(vanilla_version_id),
    FOREIGN KEY (playset_id) REFERENCES playsets(playset_id),
    FOREIGN KEY (parser_version_id) REFERENCES parsers(parser_version_id)
);

-- Snapshot members - which content versions are included
CREATE TABLE IF NOT EXISTS snapshot_members (
    snapshot_id INTEGER NOT NULL,
    content_version_id INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, content_version_id),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id),
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
);

-- ============================================================================
-- EXEMPLAR MODS (for linter-by-example)
-- ============================================================================

CREATE TABLE IF NOT EXISTS exemplar_mods (
    exemplar_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_package_id INTEGER NOT NULL,
    pinned_content_version_id INTEGER,       -- Specific version to use as exemplar
    reason_tags_json TEXT,                   -- JSON array: ["best_practice", "merge_behavior", etc.]
    topics_json TEXT,                        -- JSON array of topics this exemplar covers
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (mod_package_id) REFERENCES mod_packages(mod_package_id),
    FOREIGN KEY (pinned_content_version_id) REFERENCES content_versions(content_version_id)
);

-- ============================================================================
-- FULL-TEXT SEARCH
-- ============================================================================

-- FTS for file content
CREATE VIRTUAL TABLE IF NOT EXISTS file_content_fts USING fts5(
    content_text,
    content=file_contents,
    content_rowid=rowid
);

-- FTS for symbols
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    name,
    symbol_type,
    content=symbols,
    content_rowid=symbol_id
);

-- FTS for references
CREATE VIRTUAL TABLE IF NOT EXISTS refs_fts USING fts5(
    name,
    ref_type,
    content=refs,
    content_rowid=ref_id
);

-- ============================================================================
-- METADATA
-- ============================================================================

-- Database metadata
CREATE TABLE IF NOT EXISTS db_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================================
-- CONTRIBUTION & CONFLICT ANALYSIS
-- ============================================================================

-- Contribution Units - what each source (vanilla/mod) provides for a unit_key
-- Extracted ONCE per content_version, NOT per playset
-- This is the canonical "what does this mod define" data
CREATE TABLE IF NOT EXISTS contribution_units (
    contrib_id TEXT PRIMARY KEY,              -- SHA256[:16] of (cv_id, file_id, node_path)
    content_version_id INTEGER NOT NULL,      -- FK to content_versions
    file_id INTEGER NOT NULL,                 -- FK to files
    domain TEXT NOT NULL,                     -- on_action, decision, trait, etc.
    unit_key TEXT NOT NULL,                   -- on_action:on_yearly_pulse
    node_path TEXT,                           -- JSON path to AST node
    relpath TEXT NOT NULL,                    -- File path for display
    line_number INTEGER,
    merge_behavior TEXT NOT NULL,             -- replace, append, merge_by_id, unknown
    symbols_json TEXT,                        -- JSON: symbols defined by this unit
    refs_json TEXT,                           -- JSON: refs used by this unit
    node_hash TEXT,                           -- Hash of AST node for diff detection
    summary TEXT,                             -- Human-readable summary
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id),
    FOREIGN KEY (file_id) REFERENCES files(file_id)
);

CREATE INDEX IF NOT EXISTS idx_contrib_cv ON contribution_units(content_version_id);
CREATE INDEX IF NOT EXISTS idx_contrib_domain ON contribution_units(domain);
CREATE INDEX IF NOT EXISTS idx_contrib_unit_key ON contribution_units(unit_key);
CREATE INDEX IF NOT EXISTS idx_contrib_file ON contribution_units(file_id);

-- Conflict Units - grouped conflicts for a specific playset
-- Created by grouping contribution_units from playset's content_versions by unit_key
CREATE TABLE IF NOT EXISTS conflict_units (
    conflict_unit_id TEXT PRIMARY KEY,        -- SHA256[:16] of (playset_id, unit_key)
    playset_id INTEGER NOT NULL,              -- FK to playsets
    unit_key TEXT NOT NULL,                   -- on_action:on_yearly_pulse
    domain TEXT NOT NULL,                     -- on_action
    candidate_count INTEGER NOT NULL,
    merge_capability TEXT NOT NULL,           -- winner_only, guided_merge, ai_merge
    risk TEXT NOT NULL,                       -- low, med, high
    risk_score INTEGER NOT NULL,              -- 0-100
    uncertainty TEXT NOT NULL,                -- none, low, med, high
    reasons_json TEXT,                        -- JSON array of risk reasons
    resolution_status TEXT NOT NULL DEFAULT 'unresolved',  -- unresolved, resolved, deferred
    resolution_id TEXT,                       -- FK to resolution if resolved
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (playset_id) REFERENCES playsets(playset_id)
);

CREATE INDEX IF NOT EXISTS idx_conflict_playset ON conflict_units(playset_id);
CREATE INDEX IF NOT EXISTS idx_conflict_unit_key ON conflict_units(unit_key);
CREATE INDEX IF NOT EXISTS idx_conflict_domain ON conflict_units(domain);
CREATE INDEX IF NOT EXISTS idx_conflict_risk ON conflict_units(risk);
CREATE INDEX IF NOT EXISTS idx_conflict_status ON conflict_units(resolution_status);

-- Conflict Candidates - link conflict units to contribution units
-- Each candidate is a contribution from a specific source in the playset
CREATE TABLE IF NOT EXISTS conflict_candidates (
    conflict_unit_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,               -- Unique within conflict
    contrib_id TEXT NOT NULL,                 -- FK to contribution_units
    source_kind TEXT NOT NULL,                -- vanilla or mod
    source_name TEXT NOT NULL,                -- Mod name
    load_order_index INTEGER NOT NULL,
    is_winner INTEGER NOT NULL DEFAULT 0,     -- 1 if this would win by load order
    PRIMARY KEY (conflict_unit_id, candidate_id),
    FOREIGN KEY (conflict_unit_id) REFERENCES conflict_units(conflict_unit_id),
    FOREIGN KEY (contrib_id) REFERENCES contribution_units(contrib_id)
);

-- Resolution Choices - user decisions on how to handle conflicts
CREATE TABLE IF NOT EXISTS resolution_choices (
    resolution_id TEXT PRIMARY KEY,
    conflict_unit_id TEXT NOT NULL,
    decision_type TEXT NOT NULL,              -- winner, custom_merge, defer
    winner_candidate_id TEXT,                 -- For winner type
    merge_policy_json TEXT,                   -- For custom_merge type
    notes TEXT,
    applied_at TEXT,
    applied_by TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (conflict_unit_id) REFERENCES conflict_units(conflict_unit_id)
);

CREATE INDEX IF NOT EXISTS idx_resolution_conflict ON resolution_choices(conflict_unit_id);

-- ============================================================================
-- CHANGE LOG & UPDATE TRACKING
-- ============================================================================

-- Change Log - tracks all file changes when mods/vanilla are updated
CREATE TABLE IF NOT EXISTS change_log (
    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_version_id INTEGER NOT NULL,      -- Which mod/vanilla was updated
    previous_version_id INTEGER,              -- Previous content_version (if upgrade)
    change_type TEXT NOT NULL,                -- 'initial', 'update', 'revert'
    changed_at TEXT NOT NULL DEFAULT (datetime('now')),
    summary TEXT,                             -- Human-readable summary
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id),
    FOREIGN KEY (previous_version_id) REFERENCES content_versions(content_version_id)
);

CREATE INDEX IF NOT EXISTS idx_changelog_cv ON change_log(content_version_id);
CREATE INDEX IF NOT EXISTS idx_changelog_time ON change_log(changed_at);

-- File Changes - detailed per-file changes within a change_log entry
CREATE TABLE IF NOT EXISTS file_changes (
    file_change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id INTEGER NOT NULL,               -- FK to change_log
    file_id INTEGER NOT NULL,                 -- FK to files
    relpath TEXT NOT NULL,                    -- Path for display
    change_type TEXT NOT NULL,                -- 'added', 'modified', 'deleted'
    old_content_hash TEXT,                    -- Previous content hash
    new_content_hash TEXT,                    -- New content hash
    blocks_changed_json TEXT,                 -- JSON: [{name, type, change}] summary
    FOREIGN KEY (change_id) REFERENCES change_log(change_id),
    FOREIGN KEY (file_id) REFERENCES files(file_id)
);

CREATE INDEX IF NOT EXISTS idx_filechange_changeid ON file_changes(change_id);
CREATE INDEX IF NOT EXISTS idx_filechange_relpath ON file_changes(relpath);

-- ============================================================================
-- LOCALIZATION (Paradox .yml format)
-- ============================================================================

-- Localization entries - parsed key/value pairs from .yml files
-- Separate from ASTs because localization uses a different format
CREATE TABLE IF NOT EXISTS localization_entries (
    loc_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT NOT NULL,               -- FK to file_contents
    language TEXT NOT NULL,                   -- 'english', 'german', 'french', etc.
    loc_key TEXT NOT NULL,                    -- Key name, e.g. 'trait_brave'
    version INTEGER NOT NULL DEFAULT 0,       -- Version number from key:0 or key:2
    raw_value TEXT NOT NULL,                  -- Full value with codes
    plain_text TEXT,                          -- Stripped of [scope], $var$, #format#
    line_number INTEGER,                      -- Line in source file
    parser_version_id INTEGER,                -- FK to parsers for cache invalidation
    UNIQUE(content_hash, loc_key, parser_version_id),
    FOREIGN KEY (parser_version_id) REFERENCES parsers(parser_version_id)
);

CREATE INDEX IF NOT EXISTS idx_loc_key ON localization_entries(loc_key);
CREATE INDEX IF NOT EXISTS idx_loc_language ON localization_entries(language);
CREATE INDEX IF NOT EXISTS idx_loc_hash ON localization_entries(content_hash);

-- Localization references - [scope.Function] and $variable$ refs within loc values
CREATE TABLE IF NOT EXISTS localization_refs (
    loc_ref_id INTEGER PRIMARY KEY AUTOINCREMENT,
    loc_id INTEGER NOT NULL,                  -- FK to localization_entries
    ref_type TEXT NOT NULL,                   -- 'scripted', 'variable', 'icon'
    ref_value TEXT NOT NULL,                  -- 'ROOT.Char.GetHerHis', 'bonus_line', etc.
    FOREIGN KEY (loc_id) REFERENCES localization_entries(loc_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_locref_locid ON localization_refs(loc_id);
CREATE INDEX IF NOT EXISTS idx_locref_value ON localization_refs(ref_value);
"""

# FTS triggers for keeping indexes in sync
FTS_TRIGGERS_SQL = """
-- Triggers to keep FTS indexes synchronized

-- file_content_fts triggers
CREATE TRIGGER IF NOT EXISTS file_contents_ai AFTER INSERT ON file_contents BEGIN
    INSERT INTO file_content_fts(rowid, content_text) VALUES (NEW.rowid, NEW.content_text);
END;

CREATE TRIGGER IF NOT EXISTS file_contents_ad AFTER DELETE ON file_contents BEGIN
    INSERT INTO file_content_fts(file_content_fts, rowid, content_text) VALUES('delete', OLD.rowid, OLD.content_text);
END;

CREATE TRIGGER IF NOT EXISTS file_contents_au AFTER UPDATE ON file_contents BEGIN
    INSERT INTO file_content_fts(file_content_fts, rowid, content_text) VALUES('delete', OLD.rowid, OLD.content_text);
    INSERT INTO file_content_fts(rowid, content_text) VALUES (NEW.rowid, NEW.content_text);
END;

-- symbols_fts triggers
CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
    INSERT INTO symbols_fts(rowid, name, symbol_type) VALUES (NEW.symbol_id, NEW.name, NEW.symbol_type);
END;

CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, name, symbol_type) VALUES('delete', OLD.symbol_id, OLD.name, OLD.symbol_type);
END;

CREATE TRIGGER IF NOT EXISTS symbols_au AFTER UPDATE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, name, symbol_type) VALUES('delete', OLD.symbol_id, OLD.name, OLD.symbol_type);
    INSERT INTO symbols_fts(rowid, name, symbol_type) VALUES (NEW.symbol_id, NEW.name, NEW.symbol_type);
END;

-- refs_fts triggers
CREATE TRIGGER IF NOT EXISTS refs_ai AFTER INSERT ON refs BEGIN
    INSERT INTO refs_fts(rowid, name, ref_type) VALUES (NEW.ref_id, NEW.name, NEW.ref_type);
END;

CREATE TRIGGER IF NOT EXISTS refs_ad AFTER DELETE ON refs BEGIN
    INSERT INTO refs_fts(refs_fts, rowid, name, ref_type) VALUES('delete', OLD.ref_id, OLD.name, OLD.ref_type);
END;

CREATE TRIGGER IF NOT EXISTS refs_au AFTER UPDATE ON refs BEGIN
    INSERT INTO refs_fts(refs_fts, rowid, name, ref_type) VALUES('delete', OLD.ref_id, OLD.name, OLD.ref_type);
    INSERT INTO refs_fts(rowid, name, ref_type) VALUES (NEW.ref_id, NEW.name, NEW.ref_type);
END;
"""


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Get a thread-local database connection.
    
    Uses a connection pool pattern - one connection per thread.
    """
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    
    # Ensure directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Thread-local connection
    key = str(db_path)
    if not hasattr(_local, 'connections'):
        _local.connections = {}
    
    if key not in _local.connections:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        _local.connections[key] = conn
    
    return _local.connections[key]


def init_database(db_path: Optional[Path] = None, force: bool = False) -> sqlite3.Connection:
    """
    Initialize the database schema.
    
    Args:
        db_path: Path to database file (uses default if None)
        force: If True, recreate tables even if they exist
    
    Returns:
        Database connection
    """
    conn = get_connection(db_path)
    
    if force:
        # Drop all tables (careful!)
        conn.executescript("""
            DROP TABLE IF EXISTS snapshot_members;
            DROP TABLE IF EXISTS snapshots;
            DROP TABLE IF EXISTS builds;
            DROP TABLE IF EXISTS playset_mods;
            DROP TABLE IF EXISTS playsets;
            DROP TABLE IF EXISTS refs;
            DROP TABLE IF EXISTS symbols;
            DROP TABLE IF EXISTS asts;
            DROP TABLE IF EXISTS parsers;
            DROP TABLE IF EXISTS files;
            DROP TABLE IF EXISTS file_contents;
            DROP TABLE IF EXISTS content_versions;
            DROP TABLE IF EXISTS mod_packages;
            DROP TABLE IF EXISTS vanilla_versions;
            DROP TABLE IF EXISTS exemplar_mods;
            DROP TABLE IF EXISTS db_metadata;
            DROP TABLE IF EXISTS file_content_fts;
            DROP TABLE IF EXISTS symbols_fts;
            DROP TABLE IF EXISTS refs_fts;
        """)
    
    # Create schema
    conn.executescript(SCHEMA_SQL)
    conn.executescript(FTS_TRIGGERS_SQL)
    
    # Set metadata
    conn.execute("""
        INSERT OR REPLACE INTO db_metadata (key, value, updated_at)
        VALUES ('schema_version', ?, datetime('now'))
    """, (str(DATABASE_VERSION),))
    
    conn.commit()
    
    return conn


def get_schema_version(conn: sqlite3.Connection) -> Optional[int]:
    """Get the current schema version from the database."""
    try:
        row = conn.execute(
            "SELECT value FROM db_metadata WHERE key = 'schema_version'"
        ).fetchone()
        return int(row['value']) if row else None
    except sqlite3.OperationalError:
        return None


def close_all_connections():
    """Close all thread-local connections."""
    if hasattr(_local, 'connections'):
        for conn in _local.connections.values():
            conn.close()
        _local.connections = {}
