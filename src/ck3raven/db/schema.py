"""
Database Schema for ck3raven

SQLite schema with content-addressed storage, versioning, and full traceability.
All content is deduplicated by SHA256 hash.
"""

import sqlite3
from pathlib import Path
from typing import Optional
import threading
import time

# Schema version - bump when schema changes
DATABASE_VERSION = 3

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
    is_stale INTEGER NOT NULL DEFAULT 1,     -- DEPRECATED: never read, use symbols_extracted_at=NULL instead
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
    symbols_processed_at TEXT,               -- When symbols were extracted (NULL = pending)
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (parser_version_id) REFERENCES parsers(parser_version_id),
    UNIQUE(content_hash, parser_version_id)
);

CREATE INDEX IF NOT EXISTS idx_asts_content_hash ON asts(content_hash);
CREATE INDEX IF NOT EXISTS idx_asts_parse_ok ON asts(parse_ok);
CREATE INDEX IF NOT EXISTS idx_asts_symbols_processed ON asts(symbols_processed_at);

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
CREATE INDEX IF NOT EXISTS idx_symbols_defining_ast_id ON symbols(defining_ast_id);
CREATE INDEX IF NOT EXISTS idx_symbols_defining_file_id ON symbols(defining_file_id);

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
-- PLAYSETS & BUILDS - EXPUNGED 2025-01-02
-- ============================================================================
-- 
-- These tables are EXPUNGED. Playsets are now file-based JSON:
-- - playsets/*.json - playset definitions with mod lists
-- - server.py ck3_playset - MCP tool for playset operations
-- 
-- The database-based playset architecture (playset_id, playset_mods) is BANNED.
-- See docs/CANONICAL_ARCHITECTURE.md for details.
--
-- REMOVED TABLES: playsets, playset_mods, builds
-- These tables will be dropped in a future migration.


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
-- BUILDER PIPELINE TRACKING
-- ============================================================================

-- Builder runs - tracks each full or partial build
CREATE TABLE IF NOT EXISTS builder_runs (
    build_id TEXT PRIMARY KEY,               -- UUID for this build
    builder_version TEXT NOT NULL,           -- e.g., "1.0.0"
    git_commit TEXT,                         -- Git commit hash if available
    schema_version INTEGER NOT NULL,         -- DATABASE_VERSION at build time
    started_at TEXT NOT NULL,
    completed_at TEXT,
    state TEXT NOT NULL DEFAULT 'running',   -- 'running', 'complete', 'failed', 'cancelled'
    error_message TEXT,
    -- Inputs
    vanilla_path TEXT,
    playset_id INTEGER,
    force_rebuild INTEGER DEFAULT 0,
    -- Aggregate counts (populated on completion)
    files_ingested INTEGER DEFAULT 0,
    asts_produced INTEGER DEFAULT 0,
    symbols_extracted INTEGER DEFAULT 0,
    refs_extracted INTEGER DEFAULT 0,
    localization_rows INTEGER DEFAULT 0,
    lookup_rows INTEGER DEFAULT 0,
    FOREIGN KEY (playset_id) REFERENCES playsets(playset_id)
);

-- Builder steps - tracks each phase within a build
CREATE TABLE IF NOT EXISTS builder_steps (
    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id TEXT NOT NULL,                  -- FK to builder_runs
    step_name TEXT NOT NULL,                 -- e.g., 'vanilla_ingest', 'ast_generation'
    step_version TEXT,                       -- Version of step implementation
    step_number INTEGER NOT NULL,            -- Order in pipeline
    started_at TEXT NOT NULL,
    completed_at TEXT,
    duration_sec REAL,
    state TEXT NOT NULL DEFAULT 'running',   -- 'running', 'complete', 'failed', 'skipped'
    error_message TEXT,
    -- Row counts
    rows_in INTEGER DEFAULT 0,               -- Input rows/files processed
    rows_out INTEGER DEFAULT 0,              -- Output rows created
    rows_skipped INTEGER DEFAULT 0,          -- Skipped due to rules
    rows_errored INTEGER DEFAULT 0,          -- Failed to process
    FOREIGN KEY (build_id) REFERENCES builder_runs(build_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_builder_steps_build ON builder_steps(build_id);
CREATE INDEX IF NOT EXISTS idx_builder_steps_name ON builder_steps(step_name);

-- Build lock - prevents concurrent builds
CREATE TABLE IF NOT EXISTS build_lock (
    lock_id INTEGER PRIMARY KEY CHECK (lock_id = 1),  -- Only one row allowed
    build_id TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    pid INTEGER,
    FOREIGN KEY (build_id) REFERENCES builder_runs(build_id)
);

-- Ingest log - per-file logging for daemon operations
-- Each row = one file processed in a build phase
-- BuildTracker reconstructs blocks from this table after each phase
CREATE TABLE IF NOT EXISTS ingest_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id TEXT NOT NULL,                  -- FK to builder_runs
    phase TEXT NOT NULL,                     -- e.g., "ingest", "ast_generation", "symbol_extraction"
    timestamp REAL NOT NULL,                 -- Unix timestamp (time.time())
    
    -- File identity
    file_id INTEGER,                         -- FK to files (NULL if file not yet in DB)
    relpath TEXT NOT NULL,                   -- Relative path for identification
    content_version_id INTEGER,              -- FK to content_versions
    
    -- What happened
    status TEXT NOT NULL,                    -- 'processed', 'skipped_routing', 'skipped_uptodate', 'error'
    
    -- Sizes (for block thresholds and metrics)
    size_raw INTEGER,                        -- Original file size in bytes
    size_stored INTEGER,                     -- Bytes written to DB (may differ)
    
    -- Hashing (for Merkle root computation)
    content_hash TEXT,                       -- SHA256 of content
    
    -- Errors
    error_type TEXT,                         -- e.g., "ParseError", "IOError"
    error_msg TEXT,                          -- Truncated error message
    
    FOREIGN KEY (build_id) REFERENCES builder_runs(build_id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES files(file_id),
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
);

CREATE INDEX IF NOT EXISTS idx_ingest_log_build_phase ON ingest_log(build_id, phase);
CREATE INDEX IF NOT EXISTS idx_ingest_log_timestamp ON ingest_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_ingest_log_status ON ingest_log(build_id, status);

-- Reconstructed blocks - summary records created by BuildTracker after phases complete
-- Each block = chunk of ingest_log entries (500 files OR 50MB threshold)
CREATE TABLE IF NOT EXISTS ingest_blocks (
    block_id TEXT PRIMARY KEY,               -- UUID (e.g., "blk-a1b2c3d4")
    build_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    block_number INTEGER NOT NULL,           -- Sequence within phase (1, 2, 3...)
    
    -- Timing (from first/last log entry in block)
    started_at REAL NOT NULL,                -- Unix timestamp of first entry
    ended_at REAL NOT NULL,                  -- Unix timestamp of last entry
    duration_sec REAL NOT NULL,
    
    -- Aggregated metrics
    files_processed INTEGER NOT NULL DEFAULT 0,
    files_skipped INTEGER NOT NULL DEFAULT 0,
    files_errored INTEGER NOT NULL DEFAULT 0,
    bytes_scanned INTEGER NOT NULL DEFAULT 0,
    bytes_stored INTEGER NOT NULL DEFAULT 0,
    
    -- Integrity
    block_hash TEXT,                         -- Merkle root of content_hash values
    
    -- Range of log entries this block covers
    log_id_start INTEGER NOT NULL,
    log_id_end INTEGER NOT NULL,
    
    UNIQUE(build_id, phase, block_number),
    FOREIGN KEY (build_id) REFERENCES builder_runs(build_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ingest_blocks_build ON ingest_blocks(build_id);

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

-- ============================================================================
-- LOOKUP TABLES - ID-keyed reference data
-- ============================================================================
-- These tables store mappings from numeric IDs to human-readable data.
-- Unlike symbols (which are string-keyed and in ASTs), these are for:
--   - province IDs (e.g., 2333 → Paris)
--   - character IDs (e.g., 163110 → Charlemagne)  
--   - dynasty IDs (e.g., 699 → Karling)
--   - title mappings
--
-- The key insight: lookups are for OPAQUE NUMERIC IDs where you need to
-- know "what does ID 2333 mean?" Symbols are for string keys where you
-- need to know "is brave a valid trait?"

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
-- DEPRECATED LOOKUP TABLES (to be removed)
-- ============================================================================
-- These were based on a misunderstanding: traits, events, decisions are
-- STRING-KEYED and already in the symbols table with full AST data.
-- They don't need separate lookup tables - use symbols + AST queries.
--
-- Keeping temporarily for backward compatibility but not populated.

-- DEPRECATED: Trait lookup table - use symbols table instead
CREATE TABLE IF NOT EXISTS trait_lookups (
    trait_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    category TEXT,                            -- education, personality, lifestyle, etc.
    trait_group TEXT,                         -- group = X value
    level INTEGER,                            -- level = X value (for tiered traits)
    is_genetic INTEGER DEFAULT 0,             -- genetic = yes
    is_physical INTEGER DEFAULT 0,            -- physical = yes
    is_health INTEGER DEFAULT 0,              -- health = yes
    is_fame INTEGER DEFAULT 0,                -- fame = yes
    opposites_json TEXT,                      -- JSON array of opposite trait names
    flags_json TEXT,                          -- JSON array of flag values
    modifiers_json TEXT,                      -- JSON of modifier key/values
    FOREIGN KEY (symbol_id) REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    UNIQUE(symbol_id)
);

CREATE INDEX IF NOT EXISTS idx_trait_name ON trait_lookups(name);
CREATE INDEX IF NOT EXISTS idx_trait_category ON trait_lookups(category);
CREATE INDEX IF NOT EXISTS idx_trait_group ON trait_lookups(trait_group);

-- Decision lookup table - extracted from common/decisions/*.txt ASTs
CREATE TABLE IF NOT EXISTS decision_lookups (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL,               -- FK to symbols table
    name TEXT NOT NULL,                       -- decision name
    is_shown_check TEXT,                      -- is_shown block summary (TBC)
    is_valid_check TEXT,                      -- is_valid block summary (TBC)
    major INTEGER DEFAULT 0,                  -- major = yes
    ai_check_interval INTEGER,                -- ai_check_interval value
    FOREIGN KEY (symbol_id) REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    UNIQUE(symbol_id)
);

CREATE INDEX IF NOT EXISTS idx_decision_name ON decision_lookups(name);

-- Event lookup table - extracted from events/*.txt ASTs  
CREATE TABLE IF NOT EXISTS event_lookups (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL,               -- FK to symbols table
    event_name TEXT NOT NULL,                 -- e.g., 'blackmail.0001'
    namespace TEXT,                           -- extracted namespace
    event_type TEXT,                          -- character_event, letter_event, etc.
    is_hidden INTEGER DEFAULT 0,              -- hidden = yes
    theme TEXT,                               -- theme value
    FOREIGN KEY (symbol_id) REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    UNIQUE(symbol_id)
);

CREATE INDEX IF NOT EXISTS idx_event_name ON event_lookups(event_name);
CREATE INDEX IF NOT EXISTS idx_event_namespace ON event_lookups(namespace);
CREATE INDEX IF NOT EXISTS idx_event_type ON event_lookups(event_type);
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

# ============================================================================
# WRITE PROTECTION TRIGGERS (DB-level enforcement)
# ============================================================================
# These BEFORE triggers prevent writes to derived tables unless a builder
# session is active. This prevents agents from accidentally corrupting
# extracted data through ad-hoc queries.
#
# Protected tables: symbols, refs, *_lookups
# Allowed: builder sessions with valid token
#
# To write to these tables, you must:
# 1. Call start_builder_session() to get a session token
# 2. Store the token in builder_sessions table
# 3. The trigger checks for an active session before allowing writes

WRITE_PROTECTION_SQL = """
-- Builder session tracking for write protection
-- Only active builder sessions can write to derived tables
CREATE TABLE IF NOT EXISTS builder_sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,              -- HMAC-signed session token
    purpose TEXT NOT NULL,                   -- What this session is doing
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,                -- Session expiry
    is_active INTEGER NOT NULL DEFAULT 1,    -- 0 = ended/expired
    ended_at TEXT,
    rows_written INTEGER NOT NULL DEFAULT 0  -- Tracking for audit
);

CREATE INDEX IF NOT EXISTS idx_builder_sessions_active 
    ON builder_sessions(is_active, expires_at);
CREATE INDEX IF NOT EXISTS idx_builder_sessions_token 
    ON builder_sessions(token);

-- Helper view: Is there an active builder session?
-- This is checked by the BEFORE triggers
CREATE VIEW IF NOT EXISTS v_builder_session_active AS
SELECT CASE 
    WHEN EXISTS (
        SELECT 1 FROM builder_sessions 
        WHERE is_active = 1 
        AND datetime(expires_at) > datetime('now')
    ) THEN 1 
    ELSE 0 
END AS has_active_session;

-- ============================================================================
-- BEFORE INSERT/UPDATE/DELETE triggers on protected tables
-- ============================================================================
-- These triggers ABORT if no active builder session exists.
-- This is DB-level enforcement - cannot be bypassed by application code.

-- SYMBOLS table protection
CREATE TRIGGER IF NOT EXISTS symbols_write_protect_insert
BEFORE INSERT ON symbols
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: symbols table requires active builder session. Use start_builder_session().');
END;

CREATE TRIGGER IF NOT EXISTS symbols_write_protect_update
BEFORE UPDATE ON symbols
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: symbols table requires active builder session. Use start_builder_session().');
END;

CREATE TRIGGER IF NOT EXISTS symbols_write_protect_delete
BEFORE DELETE ON symbols
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: symbols table requires active builder session. Use start_builder_session().');
END;

-- REFS table protection
CREATE TRIGGER IF NOT EXISTS refs_write_protect_insert
BEFORE INSERT ON refs
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: refs table requires active builder session. Use start_builder_session().');
END;

CREATE TRIGGER IF NOT EXISTS refs_write_protect_update
BEFORE UPDATE ON refs
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: refs table requires active builder session. Use start_builder_session().');
END;

CREATE TRIGGER IF NOT EXISTS refs_write_protect_delete
BEFORE DELETE ON refs
WHEN (SELECT has_active_session FROM v_builder_session_active) = 0
BEGIN
    SELECT RAISE(ABORT, 'WRITE_PROTECTED: refs table requires active builder session. Use start_builder_session().');
END;

-- TRAIT_LOOKUPS table protection
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

-- DECISION_LOOKUPS table protection
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

-- EVENT_LOOKUPS table protection
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

-- LOCALIZATION_ENTRIES protection (if table exists)
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
    
    # ============================================================================
    # MIGRATIONS - Safe column additions for existing databases
    # ============================================================================
    
    # Migration: Add symbols_processed_at column to asts table
    # This column tracks whether an AST has been processed for symbol extraction,
    # even if it yielded 0 symbols (e.g., empty/comment-only files).
    try:
        conn.execute("ALTER TABLE asts ADD COLUMN symbols_processed_at TEXT")
    except sqlite3.OperationalError:
        # Column already exists, that's fine
        pass
    
    # Migration: Add index for symbols_processed_at if not exists
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_asts_symbols_processed ON asts(symbols_processed_at)")
    except sqlite3.OperationalError:
        pass
    
    # Apply write protection triggers (ignore errors if tables don't exist yet)
    try:
        conn.executescript(WRITE_PROTECTION_SQL)
    except sqlite3.OperationalError:
        # Some tables may not exist yet, that's OK
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
    
    This is REQUIRED before writing to: symbols, refs, *_lookups, localization_entries
    
    Args:
        conn: Database connection
        purpose: Description of what this session will do
        ttl_minutes: Session duration in minutes (default 60)
    
    Returns:
        Session token (store this to end the session later)
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
    """
    End a builder session.
    
    Args:
        conn: Database connection
        token: Session token from start_builder_session()
    
    Returns:
        True if session was found and ended
    """
    from datetime import datetime
    
    result = conn.execute("""
        UPDATE builder_sessions 
        SET is_active = 0, ended_at = ?
        WHERE token = ? AND is_active = 1
    """, (datetime.now().isoformat(), token))
    conn.commit()
    
    return result.rowcount > 0


def has_active_builder_session(conn: sqlite3.Connection) -> bool:
    """
    Check if there's an active builder session.
    
    Args:
        conn: Database connection
    
    Returns:
        True if an active, non-expired session exists
    """
    row = conn.execute("""
        SELECT has_active_session FROM v_builder_session_active
    """).fetchone()
    
    return row and row[0] == 1


def cleanup_expired_sessions(conn: sqlite3.Connection) -> int:
    """
    Mark expired sessions as inactive.
    
    Args:
        conn: Database connection
    
    Returns:
        Number of sessions cleaned up
    """
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
        with BuilderSession(conn, "Extracting symbols from mod X") as session:
            # Can write to protected tables here
            conn.execute("INSERT INTO symbols ...")
            
            # For long-running operations, renew periodically
            session.renew()  # Extends expiration by ttl_minutes
        # Session automatically ended
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
        return False  # Don't suppress exceptions
    
    def renew(self) -> bool:
        """Extend the session expiration by ttl_minutes from now.
        
        Call this periodically during long-running operations to prevent
        session expiration. Automatically called by renew_if_needed().
        
        Returns:
            True if renewal succeeded, False if session not active
        """
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
        """Renew session if more than threshold_minutes since last renewal.
        
        Call this frequently (e.g., in progress callbacks) to ensure the 
        session doesn't expire during long-running operations.
        
        Args:
            threshold_minutes: Renew if this many minutes have passed
            
        Returns:
            True if renewed, False if not needed or failed
        """
        if self._last_renewed is None:
            return self.renew()
        
        elapsed_minutes = (time.time() - self._last_renewed) / 60
        if elapsed_minutes >= threshold_minutes:
            return self.renew()
        return False
