"""
Database Schema for ck3raven

SQLite schema with content-addressed storage, versioning, and full traceability.
All content is deduplicated by SHA256 hash.

SCHEMA REVISION: January 2026 - Content-Keyed Symbols & References (FLAG DAY)
- symbols and refs now bind to ast_id ONLY (content identity)
- REMOVED: file_id, content_version_id from symbols/refs tables
- File association derived via Golden Join: symbols → asts → files
- ON DELETE CASCADE for AST deletion cleanup
- See docs/SYMBOL_CONTENT_MIGRATION_PLAN.md for migration details

Previous revision:
- Renamed: defining_file_id → file_id, using_file_id → file_id
- Added: column_number for IDE precision
- Removed: deprecated daemon/logging/conflict tables
"""

import sqlite3
from pathlib import Path
from typing import Optional
import threading
import time

# Schema version - bump when schema changes
DATABASE_VERSION = 7  # Phase C: collapse mod_packages into content_versions

# Thread-local storage for connections
_local = threading.local()

# Default database path
DEFAULT_DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"


SCHEMA_SQL = """
-- ============================================================================
-- VERSIONING & IDENTITIES
-- ============================================================================

-- Content versions - specific version of vanilla or a mod
-- Keyed by content_root_hash (hash of all file hashes + paths)
-- Phase C: mod_packages columns collapsed directly into this table
CREATE TABLE IF NOT EXISTS content_versions (
    content_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',            -- Mod/vanilla display name (was mod_packages.name)
    source_path TEXT,                         -- Original filesystem path (was mod_packages.source_path)
    workshop_id TEXT,                         -- Steam Workshop ID, NULL for vanilla/local (was mod_packages.workshop_id)
    source_url TEXT,                          -- Workshop URL or other source
    notes TEXT,
    content_root_hash TEXT NOT NULL UNIQUE,   -- SHA256 of sorted (relpath, file_hash) pairs
    file_count INTEGER NOT NULL DEFAULT 0,
    total_size INTEGER NOT NULL DEFAULT 0,
    ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    -- Lifecycle tracking
    downloaded_at TEXT,                       -- When mod was downloaded from workshop (for mods)
    source_mtime TEXT,                        -- Latest mtime of source directory
    symbols_extracted_at TEXT,                -- When symbols were extracted
    contributions_extracted_at TEXT           -- When contributions were extracted
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
    symbols_processed_at TEXT,               -- When symbols were extracted (NULL = pending)
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (parser_version_id) REFERENCES parsers(parser_version_id),
    UNIQUE(content_hash, parser_version_id)
);

CREATE INDEX IF NOT EXISTS idx_asts_content_hash ON asts(content_hash);
CREATE INDEX IF NOT EXISTS idx_asts_parse_ok ON asts(parse_ok);
CREATE INDEX IF NOT EXISTS idx_asts_symbols_processed ON asts(symbols_processed_at);

-- ============================================================================
-- REFERENCE GRAPH (Symbols & References) - CONTENT-KEYED (January 2026)
-- ============================================================================
-- FLAG-DAY MIGRATION: Symbols and refs bind to AST (content), not files.
-- File association is ALWAYS derived via Golden Join: symbols → asts → files
-- See docs/SYMBOL_CONTENT_MIGRATION_PLAN.md for rationale.

-- Symbols - things that define names/IDs/keys
-- Bound to AST (content identity), NOT to files
CREATE TABLE IF NOT EXISTS symbols (
    symbol_id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Content binding (THE ONLY identity key)
    ast_id INTEGER NOT NULL,                 -- FK to asts (content identity)
    
    -- Position within AST
    line_number INTEGER,
    column_number INTEGER,
    
    -- Identity
    name TEXT NOT NULL,                      -- The symbol name/ID
    symbol_type TEXT NOT NULL,               -- 'trait', 'event', 'decision', etc.
    scope TEXT,                              -- Namespace (e.g., event namespace)
    
    -- Node identity for conflict detection (Phase 0, January 2026)
    -- These are character offsets (Python string indices) into content_text
    -- node_hash_norm = SHA-256 of normalized text from [start_offset:end_offset]
    node_hash_norm TEXT NOT NULL,            -- SHA-256 of normalized node text
    node_start_offset INTEGER NOT NULL,      -- Character offset (inclusive) into content_text
    node_end_offset INTEGER NOT NULL,        -- Character offset (exclusive) into content_text
    
    -- Metadata
    metadata_json TEXT,                      -- Extensible additional data
    
    FOREIGN KEY (ast_id) REFERENCES asts(ast_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_symbols_ast ON symbols(ast_id);
CREATE INDEX IF NOT EXISTS idx_symbols_lookup ON symbols(symbol_type, name);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_hash ON symbols(node_hash_norm);

-- References - places that use symbols
-- Bound to AST (content identity), NOT to files
CREATE TABLE IF NOT EXISTS refs (
    ref_id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Content binding (THE ONLY identity key)
    ast_id INTEGER NOT NULL,                 -- FK to asts (content identity)
    
    -- Position within AST
    line_number INTEGER,
    column_number INTEGER,
    
    -- Identity
    name TEXT NOT NULL,                      -- Referenced symbol name
    ref_type TEXT NOT NULL,                  -- Type of reference ('trait_ref', etc.)
    context TEXT,                            -- Context (which effect/trigger)
    
    -- Resolution
    resolution_status TEXT NOT NULL DEFAULT 'unresolved',
    resolved_symbol_id INTEGER,              -- FK to symbols if resolved
    candidates_json TEXT,                    -- Best-guess candidates if unresolved
    
    FOREIGN KEY (ast_id) REFERENCES asts(ast_id) ON DELETE CASCADE,
    FOREIGN KEY (resolved_symbol_id) REFERENCES symbols(symbol_id)
);

CREATE INDEX IF NOT EXISTS idx_refs_ast ON refs(ast_id);
CREATE INDEX IF NOT EXISTS idx_refs_lookup ON refs(ref_type, name);
CREATE INDEX IF NOT EXISTS idx_refs_name ON refs(name);

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
-- QBUILDER PIPELINE TRACKING
-- ============================================================================

-- Build runs - tracks each build session
-- REVISED January 2026: Simplified from old builder_runs
CREATE TABLE IF NOT EXISTS build_runs (
    run_id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',  -- running/completed/aborted
    trigger TEXT,                            -- 'cli', 'watch', 'manual'
    config_json TEXT,                        -- routing table version, limits, etc.
    
    -- Aggregate stats (updated on completion)
    envelopes_total INTEGER,
    envelopes_completed INTEGER,
    envelopes_failed INTEGER,
    duration_seconds REAL
);

-- Build lock - prevents concurrent builds
CREATE TABLE IF NOT EXISTS build_lock (
    lock_id INTEGER PRIMARY KEY CHECK (lock_id = 1),  -- Only one row allowed
    build_id TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    pid INTEGER
);

-- ============================================================================
-- QBUILDER QUEUE (January 2026)
-- ============================================================================
-- Envelope-based work queue. Each file gets one envelope defining all steps.
-- The routing table is the SOLE AUTHORITY for what work a file needs.

CREATE TABLE IF NOT EXISTS qbuilder_queue (
    queue_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    content_version_id INTEGER NOT NULL,
    relpath TEXT NOT NULL,
    content_hash TEXT,
    envelope TEXT NOT NULL,
    steps_json TEXT NOT NULL,                -- ["INGEST", "PARSE", ...]
    current_step INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',           -- pending, processing, done, error
    error_message TEXT,
    lease_holder TEXT,
    lease_expires_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES files(file_id),
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
);

CREATE INDEX IF NOT EXISTS idx_qqueue_status ON qbuilder_queue(status);
CREATE INDEX IF NOT EXISTS idx_qqueue_cvid ON qbuilder_queue(content_version_id);
CREATE INDEX IF NOT EXISTS idx_qqueue_envelope ON qbuilder_queue(envelope);

-- ============================================================================
-- LOCALIZATION (Paradox .yml format)
-- ============================================================================

-- Localization entries - parsed key/value pairs from .yml files
-- REVISED January 2026: Changed content_hash → file_id, added content_version_id
CREATE TABLE IF NOT EXISTS localization_entries (
    loc_id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Location
    file_id INTEGER NOT NULL,                -- FK to files (was: content_hash)
    content_version_id INTEGER NOT NULL,     -- FK to content_versions (for playset filtering)
    line_number INTEGER,
    
    -- Identity
    language TEXT NOT NULL,                  -- 'english', 'german', 'french', etc.
    loc_key TEXT NOT NULL,                   -- Key name, e.g. 'trait_brave'
    version INTEGER NOT NULL DEFAULT 0,      -- Version number from key:0 or key:2
    
    -- Content
    raw_value TEXT NOT NULL,                 -- Full value with codes
    plain_text TEXT,                         -- Stripped of [scope], $var$, #format#
    
    UNIQUE(file_id, loc_key, version),
    FOREIGN KEY (file_id) REFERENCES files(file_id),
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
);

CREATE INDEX IF NOT EXISTS idx_loc_key ON localization_entries(loc_key);
CREATE INDEX IF NOT EXISTS idx_loc_language ON localization_entries(language);
CREATE INDEX IF NOT EXISTS idx_loc_file ON localization_entries(file_id);
CREATE INDEX IF NOT EXISTS idx_loc_cvid ON localization_entries(content_version_id);

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

-- ============================================================================
-- LOOKUP TABLES - ID-keyed reference data
-- ============================================================================

-- Province lookup - from map_data/definition.csv + history/provinces/
CREATE TABLE IF NOT EXISTS province_lookup (
    province_id INTEGER PRIMARY KEY,          -- The numeric ID from definition.csv
    name TEXT NOT NULL,                       -- Province name from definition.csv col 4
    rgb_r INTEGER,                            -- RGB color from definition.csv
    rgb_g INTEGER,
    rgb_b INTEGER,
    culture TEXT,                             -- From history/provinces (at latest date)
    religion TEXT,
    holding_type TEXT,                        -- castle, city, temple, tribal, etc.
    terrain TEXT,
    content_version_id INTEGER,               -- Which mod/vanilla provides this
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
);

CREATE INDEX IF NOT EXISTS idx_province_name ON province_lookup(name);

-- Character lookup - from history/characters/
CREATE TABLE IF NOT EXISTS character_lookup (
    character_id INTEGER PRIMARY KEY,         -- The numeric character ID
    name TEXT NOT NULL,                       -- Character's name
    dynasty_id INTEGER,                       -- FK to dynasty_lookup
    dynasty_house TEXT,                       -- House name if applicable
    culture TEXT,
    religion TEXT,
    birth_date TEXT,                          -- e.g., "768.4.2"
    death_date TEXT,                          -- e.g., "814.1.28" or NULL if immortal/scripted
    father_id INTEGER,                        -- FK to another character
    mother_id INTEGER,
    traits_json TEXT,                         -- JSON array of trait names
    content_version_id INTEGER,
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
);

CREATE INDEX IF NOT EXISTS idx_character_name ON character_lookup(name);
CREATE INDEX IF NOT EXISTS idx_character_dynasty ON character_lookup(dynasty_id);

-- Dynasty lookup - from common/dynasties/
CREATE TABLE IF NOT EXISTS dynasty_lookup (
    dynasty_id INTEGER PRIMARY KEY,           -- The numeric dynasty ID
    name_key TEXT NOT NULL,                   -- Localization key, e.g., "dynn_Orsini"
    prefix TEXT,                              -- e.g., "dynnp_de"
    culture TEXT,
    motto TEXT,                               -- Motto localization key
    content_version_id INTEGER,
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
);

CREATE INDEX IF NOT EXISTS idx_dynasty_name ON dynasty_lookup(name_key);

-- Title lookup - from common/landed_titles/
CREATE TABLE IF NOT EXISTS title_lookup (
    title_key TEXT PRIMARY KEY,               -- e.g., "k_france", "c_paris"
    tier TEXT,                                -- 'e', 'k', 'd', 'c', 'b'
    capital_county TEXT,                      -- Reference to another title
    capital_province_id INTEGER,              -- Resolved province ID
    de_jure_liege TEXT,                       -- Parent title key
    color_r INTEGER,
    color_g INTEGER,
    color_b INTEGER,
    definite_form INTEGER DEFAULT 0,
    landless INTEGER DEFAULT 0,
    content_version_id INTEGER,
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id),
    FOREIGN KEY (capital_province_id) REFERENCES province_lookup(province_id)
);

CREATE INDEX IF NOT EXISTS idx_title_tier ON title_lookup(tier);
CREATE INDEX IF NOT EXISTS idx_title_liege ON title_lookup(de_jure_liege);

-- Title history lookup - from history/titles/
CREATE TABLE IF NOT EXISTS title_history_lookup (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title_key TEXT NOT NULL,                  -- e.g., "k_france"
    effective_date TEXT NOT NULL,             -- e.g., "867.1.1"
    holder_id INTEGER,                        -- character_id or 0
    liege_title TEXT,                         -- Parent title at this date
    government TEXT,                          -- Government type
    succession_laws_json TEXT,                -- JSON array of law keys
    content_version_id INTEGER,
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id),
    FOREIGN KEY (holder_id) REFERENCES character_lookup(character_id)
);

CREATE INDEX IF NOT EXISTS idx_title_history_key ON title_history_lookup(title_key);
CREATE INDEX IF NOT EXISTS idx_title_history_date ON title_history_lookup(title_key, effective_date);

-- Holy site lookup - from common/religion/holy_sites/
CREATE TABLE IF NOT EXISTS holy_site_lookup (
    holy_site_key TEXT PRIMARY KEY,           -- e.g., "jerusalem"
    county_key TEXT NOT NULL,                 -- e.g., "c_jerusalem"
    province_id INTEGER,                      -- Resolved province ID
    faith_key TEXT,                           -- Owning faith
    flag TEXT,                                -- Associated flag
    content_version_id INTEGER,
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
);

CREATE INDEX IF NOT EXISTS idx_holy_site_county ON holy_site_lookup(county_key);

-- ============================================================================
-- TRAIT/EVENT/DECISION LOOKUPS (linked to symbols)
-- ============================================================================

-- Trait lookup - additional trait metadata beyond symbols
CREATE TABLE IF NOT EXISTS trait_lookups (
    trait_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    category TEXT,                            -- education, personality, lifestyle, etc.
    trait_group TEXT,                         -- group = X value
    level INTEGER,                            -- level = X value (for tiered traits)
    is_genetic INTEGER DEFAULT 0,
    is_physical INTEGER DEFAULT 0,
    is_health INTEGER DEFAULT 0,
    is_fame INTEGER DEFAULT 0,
    opposites_json TEXT,                      -- JSON array of opposite trait names
    flags_json TEXT,                          -- JSON array of flag values
    modifiers_json TEXT,                      -- JSON of modifier key/values
    FOREIGN KEY (symbol_id) REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    UNIQUE(symbol_id)
);

CREATE INDEX IF NOT EXISTS idx_trait_name ON trait_lookups(name);
CREATE INDEX IF NOT EXISTS idx_trait_category ON trait_lookups(category);

-- Decision lookup - additional decision metadata
CREATE TABLE IF NOT EXISTS decision_lookups (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    is_shown_check TEXT,
    is_valid_check TEXT,
    major INTEGER DEFAULT 0,
    ai_check_interval INTEGER,
    FOREIGN KEY (symbol_id) REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    UNIQUE(symbol_id)
);

CREATE INDEX IF NOT EXISTS idx_decision_name ON decision_lookups(name);

-- Event lookup - additional event metadata
CREATE TABLE IF NOT EXISTS event_lookups (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL,
    event_name TEXT NOT NULL,
    namespace TEXT,
    event_type TEXT,                          -- character_event, letter_event, etc.
    is_hidden INTEGER DEFAULT 0,
    theme TEXT,
    FOREIGN KEY (symbol_id) REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    UNIQUE(symbol_id)
);

CREATE INDEX IF NOT EXISTS idx_event_name ON event_lookups(event_name);
CREATE INDEX IF NOT EXISTS idx_event_namespace ON event_lookups(namespace);

-- ============================================================================
-- BUILDER SESSION MANAGEMENT (for write protection)
-- ============================================================================

CREATE TABLE IF NOT EXISTS builder_sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    purpose TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    ended_at TEXT,
    rows_written INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_builder_sessions_active ON builder_sessions(is_active, expires_at);
CREATE INDEX IF NOT EXISTS idx_builder_sessions_token ON builder_sessions(token);

-- Helper view: Is there an active builder session?
CREATE VIEW IF NOT EXISTS v_builder_session_active AS
SELECT CASE 
    WHEN EXISTS (
        SELECT 1 FROM builder_sessions 
        WHERE is_active = 1 
        AND datetime(expires_at) > datetime('now')
    ) THEN 1 
    ELSE 0 
END AS has_active_session;
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

# Write protection triggers (optional - can be enabled for safety)
WRITE_PROTECTION_SQL = """
-- BEFORE INSERT/UPDATE/DELETE triggers on protected tables
-- These triggers ABORT if no active builder session exists.

-- SYMBOLS table protection
CREATE TRIGGER IF NOT EXISTS symbols_write_protect_insert
BEFORE INSERT ON symbols
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: symbols table requires active builder session.');
END;

CREATE TRIGGER IF NOT EXISTS symbols_write_protect_update
BEFORE UPDATE ON symbols
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: symbols table requires active builder session.');
END;

CREATE TRIGGER IF NOT EXISTS symbols_write_protect_delete
BEFORE DELETE ON symbols
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: symbols table requires active builder session.');
END;

-- REFS table protection
CREATE TRIGGER IF NOT EXISTS refs_write_protect_insert
BEFORE INSERT ON refs
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: refs table requires active builder session.');
END;

CREATE TRIGGER IF NOT EXISTS refs_write_protect_update
BEFORE UPDATE ON refs
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: refs table requires active builder session.');
END;

CREATE TRIGGER IF NOT EXISTS refs_write_protect_delete
BEFORE DELETE ON refs
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: refs table requires active builder session.');
END;

-- LOCALIZATION_ENTRIES protection
CREATE TRIGGER IF NOT EXISTS loc_entries_write_protect_insert
BEFORE INSERT ON localization_entries
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: localization_entries table requires active builder session.');
END;

CREATE TRIGGER IF NOT EXISTS loc_entries_write_protect_update
BEFORE UPDATE ON localization_entries
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: localization_entries table requires active builder session.');
END;

CREATE TRIGGER IF NOT EXISTS loc_entries_write_protect_delete
BEFORE DELETE ON localization_entries
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: localization_entries table requires active builder session.');
END;

-- TRAIT_LOOKUPS protection
CREATE TRIGGER IF NOT EXISTS trait_lookups_write_protect_insert
BEFORE INSERT ON trait_lookups
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: trait_lookups table requires active builder session.');
END;

CREATE TRIGGER IF NOT EXISTS trait_lookups_write_protect_update
BEFORE UPDATE ON trait_lookups
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: trait_lookups table requires active builder session.');
END;

CREATE TRIGGER IF NOT EXISTS trait_lookups_write_protect_delete
BEFORE DELETE ON trait_lookups
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: trait_lookups table requires active builder session.');
END;

-- DECISION_LOOKUPS protection
CREATE TRIGGER IF NOT EXISTS decision_lookups_write_protect_insert
BEFORE INSERT ON decision_lookups
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: decision_lookups table requires active builder session.');
END;

CREATE TRIGGER IF NOT EXISTS decision_lookups_write_protect_update
BEFORE UPDATE ON decision_lookups
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: decision_lookups table requires active builder session.');
END;

CREATE TRIGGER IF NOT EXISTS decision_lookups_write_protect_delete
BEFORE DELETE ON decision_lookups
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: decision_lookups table requires active builder session.');
END;

-- EVENT_LOOKUPS protection
CREATE TRIGGER IF NOT EXISTS event_lookups_write_protect_insert
BEFORE INSERT ON event_lookups
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: event_lookups table requires active builder session.');
END;

CREATE TRIGGER IF NOT EXISTS event_lookups_write_protect_update
BEFORE UPDATE ON event_lookups
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: event_lookups table requires active builder session.');
END;

CREATE TRIGGER IF NOT EXISTS event_lookups_write_protect_delete
BEFORE DELETE ON event_lookups
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: event_lookups table requires active builder session.');
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
        conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
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
        # Drop all tables for fresh start
        conn.executescript("""
            -- Core tables (order matters for FKs)
            DROP TABLE IF EXISTS localization_refs;
            DROP TABLE IF EXISTS localization_entries;
            DROP TABLE IF EXISTS refs;
            DROP TABLE IF EXISTS symbols;
            DROP TABLE IF EXISTS trait_lookups;
            DROP TABLE IF EXISTS decision_lookups;
            DROP TABLE IF EXISTS event_lookups;
            DROP TABLE IF EXISTS qbuilder_queue;
            DROP TABLE IF EXISTS build_runs;
            DROP TABLE IF EXISTS build_lock;
            DROP TABLE IF EXISTS builder_sessions;
            DROP TABLE IF EXISTS asts;
            DROP TABLE IF EXISTS parsers;
            DROP TABLE IF EXISTS files;
            DROP TABLE IF EXISTS file_contents;
            DROP TABLE IF EXISTS content_versions;
            DROP TABLE IF EXISTS db_metadata;
            
            -- Lookup tables
            DROP TABLE IF EXISTS province_lookup;
            DROP TABLE IF EXISTS character_lookup;
            DROP TABLE IF EXISTS dynasty_lookup;
            DROP TABLE IF EXISTS title_lookup;
            DROP TABLE IF EXISTS title_history_lookup;
            DROP TABLE IF EXISTS holy_site_lookup;
            
            -- FTS tables
            DROP TABLE IF EXISTS file_content_fts;
            DROP TABLE IF EXISTS symbols_fts;
            DROP TABLE IF EXISTS refs_fts;
            
            -- Views
            DROP VIEW IF EXISTS v_builder_session_active;
            
            -- DEPRECATED TABLES (to be removed)
            DROP TABLE IF EXISTS ingest_blocks;
            DROP TABLE IF EXISTS ingest_log;
            DROP TABLE IF EXISTS processing_log;
            DROP TABLE IF EXISTS builder_steps;
            DROP TABLE IF EXISTS builder_runs;
            DROP TABLE IF EXISTS work_queue;
            DROP TABLE IF EXISTS file_state;
            DROP TABLE IF EXISTS snapshots;
            DROP TABLE IF EXISTS snapshot_members;
            DROP TABLE IF EXISTS change_log;
            DROP TABLE IF EXISTS file_changes;
            DROP TABLE IF EXISTS exemplar_mods;
            DROP TABLE IF EXISTS contribution_units;
            DROP TABLE IF EXISTS conflict_units;
            DROP TABLE IF EXISTS conflict_candidates;
            DROP TABLE IF EXISTS resolution_choices;
            DROP TABLE IF EXISTS cu_to_files;
            DROP TABLE IF EXISTS conflict_types;
            DROP TABLE IF EXISTS playsets;
            DROP TABLE IF EXISTS playset_mods;
            DROP TABLE IF EXISTS builds;
        """)
    
    # Create schema
    conn.executescript(SCHEMA_SQL)
    conn.executescript(FTS_TRIGGERS_SQL)
    
    # Apply write protection triggers (optional)
    try:
        conn.executescript(WRITE_PROTECTION_SQL)
    except sqlite3.OperationalError:
        pass
    
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


# ============================================================================
# Builder Session Management
# ============================================================================

def start_builder_session(
    conn: sqlite3.Connection,
    purpose: str,
    ttl_minutes: int = 60,
) -> str:
    """
    Start a builder session to allow writes to protected tables.
    """
    import secrets
    from datetime import datetime, timedelta
    
    token = f"builder-{secrets.token_hex(16)}"
    expires_at = (datetime.now() + timedelta(minutes=ttl_minutes)).isoformat()
    
    conn.execute("""
        INSERT INTO builder_sessions (token, purpose, expires_at)
        VALUES (?, ?, ?)
    """, (token, purpose, expires_at))
    conn.commit()
    
    return token


def end_builder_session(conn: sqlite3.Connection, token: str) -> bool:
    """End a builder session."""
    from datetime import datetime
    
    result = conn.execute("""
        UPDATE builder_sessions 
        SET is_active = 0, ended_at = ?
        WHERE token = ? AND is_active = 1
    """, (datetime.now().isoformat(), token))
    conn.commit()
    
    return result.rowcount > 0


def has_active_builder_session(conn: sqlite3.Connection) -> bool:
    """Check if there's an active builder session."""
    row = conn.execute("""
        SELECT has_active_session FROM v_builder_session_active
    """).fetchone()
    
    return row and row[0] == 1


def cleanup_expired_sessions(conn: sqlite3.Connection) -> int:
    """Mark expired sessions as inactive."""
    from datetime import datetime
    
    result = conn.execute("""
        UPDATE builder_sessions 
        SET is_active = 0, ended_at = ?
        WHERE is_active = 1 AND datetime(expires_at) < datetime('now')
    """, (datetime.now().isoformat(),))
    conn.commit()
    
    return result.rowcount


class BuilderSession:
    """
    Context manager for builder sessions.
    
    Usage:
        conn = get_connection()
        with BuilderSession(conn, "Extracting symbols") as session:
            conn.execute("INSERT INTO symbols ...")
    """
    
    def __init__(self, conn: sqlite3.Connection, purpose: str, ttl_minutes: int = 60):
        self.conn = conn
        self.purpose = purpose
        self.ttl_minutes = ttl_minutes
        self.token: Optional[str] = None
        self._last_renewed: Optional[float] = None
    
    def __enter__(self) -> "BuilderSession":
        self.token = start_builder_session(self.conn, self.purpose, self.ttl_minutes)
        self._last_renewed = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            end_builder_session(self.conn, self.token)
        return False
    
    def renew(self) -> bool:
        """Extend the session expiration."""
        if not self.token:
            return False
        
        from datetime import datetime, timedelta
        new_expires = datetime.now() + timedelta(minutes=self.ttl_minutes)
        
        result = self.conn.execute("""
            UPDATE builder_sessions 
            SET expires_at = ?
            WHERE token = ? AND is_active = 1
        """, (new_expires.isoformat(), self.token))
        self.conn.commit()
        
        if result.rowcount > 0:
            self._last_renewed = time.time()
            return True
        return False
    
    def renew_if_needed(self, threshold_minutes: int = 30) -> bool:
        """Renew session if more than threshold_minutes since last renewal."""
        if self._last_renewed is None:
            return self.renew()
        
        elapsed_minutes = (time.time() - self._last_renewed) / 60
        if elapsed_minutes >= threshold_minutes:
            return self.renew()
        return False
