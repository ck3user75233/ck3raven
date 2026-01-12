# QBuilder Architecture

> **Status:** In Development  
> **Last Updated:** January 11, 2026  
> **Location:** `qbuilder/`

---

## Overview

QBuilder is an envelope-based queue daemon for CK3 mod file processing. It replaces the old `builder/daemon.py` with a simpler, more robust architecture.

### Core Principle

**The routing table is the SOLE AUTHORITY for what work a file needs.**

No `needs_*` inference, no stage detection, no artifact-based skipping. Each file gets ONE envelope that defines ALL steps to execute.

---

## Architecture

### Components

| File | Purpose |
|------|---------|
| `qbuilder/routing_table.json` | Machine-readable routing rules (13 envelopes, 32 file types) |
| `qbuilder/routing.py` | `Router` class - routes files to envelopes |
| `qbuilder/schema.py` | Queue table DDL (`qbuilder_queue`) |
| `qbuilder/enqueue.py` | File discovery and queue population |
| `qbuilder/worker.py` | `Worker` class - claims work, executes steps, handles errors |
| `qbuilder/executors.py` | Step executor functions (INGEST, PARSE, SYMBOLS, etc.) |
| `qbuilder/cli.py` | CLI subcommands for queue management |

### Envelope Model

Each file is assigned exactly ONE envelope based on its path pattern:

```
File: common/traits/00_traits.txt
  → Envelope: SCRIPT_FULL
  → Steps: [INGEST, PARSE, SYMBOLS, REFS]
```

Envelopes are defined in `routing_table.json`:

| Envelope | Steps | File Count |
|----------|-------|------------|
| LOCALIZATION | INGEST, LOCALIZATION | 14,108 |
| SCRIPT_FULL | INGEST, PARSE, SYMBOLS, REFS | 8,521 |
| LOOKUP_EVENTS | INGEST, PARSE, SYMBOLS, REFS, LOOKUP_EVENTS | 1,087 |
| INGEST_ONLY | INGEST | 1,011 |
| LOOKUP_DECISIONS | INGEST, PARSE, SYMBOLS, REFS, LOOKUP_DECISIONS | 254 |
| LOOKUP_TITLES | INGEST, PARSE, SYMBOLS, REFS, LOOKUP_TITLES | 242 |
| SCRIPT_NO_REFS | INGEST, PARSE, SYMBOLS | 78 |
| LOOKUP_TRAITS | INGEST, PARSE, SYMBOLS, REFS, LOOKUP_TRAITS | 51 |

---

## Schema Specification

### Design Principles

1. **Simple column names** - `file_id` not `defining_file_id` or `using_file_id`
2. **Keep valuable features** - `content_version_id` for playset filtering, `ast_node_path` for navigation
3. **Add precision** - `column_number` for IDE click-to-navigate
4. **Fresh DB assumption** - No migration, just clean schema

---

### Column Renames

#### `symbols` Table

| Old Column | New Column | Rationale |
|------------|------------|-----------|
| `defining_file_id` | `file_id` | Simpler, unambiguous in context |
| `defining_ast_id` | `ast_id` | Simpler |
| `symbol_type` | `symbol_type` | Keep as-is (matches CK3 terminology) |
| `line_number` | `line_number` | Keep as-is |
| *(new)* | `column_number` | Add for IDE precision |

#### `refs` Table

| Old Column | New Column | Rationale |
|------------|------------|-----------|
| `using_file_id` | `file_id` | Simpler, unambiguous in context |
| `using_ast_id` | `ast_id` | Simpler |
| `ref_type` | `ref_type` | Keep as-is |
| `line_number` | `line_number` | Keep as-is |
| *(new)* | `column_number` | Add for IDE precision |

#### `localization_entries` Table

| Old Column | New Column | Rationale |
|------------|------------|-----------|
| `content_hash` | `file_id` | Join on file_id like other tables |
| All others | Keep as-is | Schema is clean |

---

### Final DDL

#### `symbols` (revised)

```sql
CREATE TABLE symbols (
    symbol_id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Location
    file_id INTEGER NOT NULL,                -- FK to files
    content_version_id INTEGER NOT NULL,     -- FK to content_versions (for playset filtering)
    ast_id INTEGER,                          -- FK to asts
    ast_node_path TEXT,                      -- JSON path to AST node (for navigation)
    line_number INTEGER,
    column_number INTEGER,                   -- NEW: for IDE click-to-navigate
    
    -- Identity
    symbol_type TEXT NOT NULL,               -- 'trait', 'event', 'decision', 'scripted_effect', etc.
    name TEXT NOT NULL,                      -- The symbol name/ID
    scope TEXT,                              -- Namespace (e.g., event namespace)
    
    -- Metadata
    metadata_json TEXT,                      -- Extensible additional data
    
    FOREIGN KEY (ast_id) REFERENCES asts(ast_id),
    FOREIGN KEY (file_id) REFERENCES files(file_id),
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
);

CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_symbols_type ON symbols(symbol_type);
CREATE INDEX idx_symbols_file ON symbols(file_id);
CREATE INDEX idx_symbols_cvid ON symbols(content_version_id);
```

#### `refs` (revised)

```sql
CREATE TABLE refs (
    ref_id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Location
    file_id INTEGER NOT NULL,                -- FK to files
    content_version_id INTEGER NOT NULL,     -- FK to content_versions (for playset filtering)
    ast_id INTEGER,                          -- FK to asts
    ast_node_path TEXT,                      -- JSON path to AST node
    line_number INTEGER,
    column_number INTEGER,                   -- NEW: for IDE click-to-navigate
    
    -- Identity
    ref_type TEXT NOT NULL,                  -- Type of reference ('trait_ref', 'event_ref', etc.)
    name TEXT NOT NULL,                      -- Referenced symbol name
    context TEXT,                            -- Context (which effect/trigger contains this)
    
    -- Resolution
    resolution_status TEXT NOT NULL DEFAULT 'unknown',  -- 'resolved', 'unresolved', 'dynamic', 'unknown'
    resolved_symbol_id INTEGER,              -- FK to symbols if resolved
    candidates_json TEXT,                    -- Best-guess candidates if unresolved
    
    FOREIGN KEY (ast_id) REFERENCES asts(ast_id),
    FOREIGN KEY (file_id) REFERENCES files(file_id),
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id),
    FOREIGN KEY (resolved_symbol_id) REFERENCES symbols(symbol_id)
);

CREATE INDEX idx_refs_name ON refs(name);
CREATE INDEX idx_refs_type ON refs(ref_type);
CREATE INDEX idx_refs_file ON refs(file_id);
CREATE INDEX idx_refs_cvid ON refs(content_version_id);
CREATE INDEX idx_refs_status ON refs(resolution_status);
```

#### `localization_entries` (revised)

```sql
CREATE TABLE localization_entries (
    loc_id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Location
    file_id INTEGER NOT NULL,                -- FK to files (changed from content_hash)
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

CREATE INDEX idx_loc_key ON localization_entries(loc_key);
CREATE INDEX idx_loc_lang ON localization_entries(language);
CREATE INDEX idx_loc_file ON localization_entries(file_id);
CREATE INDEX idx_loc_cvid ON localization_entries(content_version_id);
```

---

### Tables to DROP

#### Deprecated Logging/Daemon Tables

```sql
DROP TABLE IF EXISTS ingest_blocks;      -- Old daemon block logging
DROP TABLE IF EXISTS processing_log;     -- Old work events
DROP TABLE IF EXISTS builder_steps;      -- Old step tracking
DROP TABLE IF EXISTS work_queue;         -- Old daemon queue
DROP TABLE IF EXISTS file_state;         -- Old daemon state
```

#### Unused Feature Tables

```sql
DROP TABLE IF EXISTS snapshots;          -- Never used
DROP TABLE IF EXISTS snapshot_members;   -- Never used
DROP TABLE IF EXISTS change_log;         -- Never used
DROP TABLE IF EXISTS file_changes;       -- Never used
DROP TABLE IF EXISTS exemplar_mods;      -- Banned concept
```

#### Conflict Tables (archive for redesign)

```sql
DROP TABLE IF EXISTS contribution_units; -- Conflict model being redesigned
DROP TABLE IF EXISTS conflict_units;     -- Conflict model being redesigned
DROP TABLE IF EXISTS cu_to_files;        -- Conflict model being redesigned
DROP TABLE IF EXISTS conflict_types;     -- Conflict model being redesigned
```

---

### New Tables

#### `build_runs` (new)

```sql
CREATE TABLE build_runs (
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
```

---

## Table Dispositions Summary

### Core Tables (KEEP, with schema changes)

| Table | Changes | Rows |
|-------|---------|------|
| `files` | None | 25,352 |
| `asts` | None | varies |
| `symbols` | Rename columns, add `column_number` | 159,407 |
| `refs` | Rename columns, add `column_number` | 217,754 |
| `localization_entries` | `content_hash` → `file_id`, add `content_version_id` | 1,579,585 |
| `localization_refs` | None | 1,174,353 |
| `content_versions` | None | varies |
| `playsets` | None | varies |

### QBuilder Tables (KEEP)

| Table | Purpose | Rows |
|-------|---------|------|
| `qbuilder_queue` | Envelope-based work queue | 25,352 |
| `build_runs` | Run-level tracking (new) | 0 |
| `build_lock` | Single-writer mutex | 1 |

### Tables to DROP

| Table | Reason |
|-------|--------|
| `ingest_blocks` | Old daemon block logging - superseded by JSONL logs |
| `processing_log` | Old work events - superseded by envelope state |
| `builder_steps` | Old step tracking - superseded by JSONL logs |
| `work_queue` | Old daemon queue - superseded by `qbuilder_queue` |
| `file_state` | Old daemon state - superseded by queue status |
| `snapshots` | Unused snapshot feature |
| `snapshot_members` | Unused snapshot feature |
| `change_log` | Unused change tracking |
| `file_changes` | Unused file diff tracking |
| `exemplar_mods` | **Banned concept** |
| `contribution_units` | Conflict model being redesigned |
| `conflict_units` | Conflict model being redesigned |
| `cu_to_files` | Conflict model being redesigned |
| `conflict_types` | Conflict model being redesigned |

---

## Logging Architecture

### Principle: Tables for State, Files for Details

| Medium | Use For |
|--------|---------|
| **Database tables** | Queryable state (runs, aggregate stats) |
| **File logs (JSONL)** | Detailed diagnostics (step timing, error details) |
| **Envelope status** | Primary work tracking (already in `qbuilder_queue`) |

### Step-Level Diagnostics: JSONL Logs

Location: `~/.ck3raven/logs/qbuilder_YYYY-MM-DD.jsonl`

Each line is a self-contained JSON object:

```json
{"ts": "2026-01-11T15:30:42", "run_id": 7, "file_id": 12345, "step": "symbols", "duration_ms": 8, "symbols_found": 23}
{"ts": "2026-01-11T15:30:42", "run_id": 7, "file_id": 12345, "step": "refs", "duration_ms": 12, "refs_found": 47}
{"ts": "2026-01-11T15:30:43", "run_id": 7, "file_id": 12346, "step": "parse", "error": "unexpected token", "line": 42}
```

**Why JSONL files for step details:**
- No write contention with main DB
- Easy to grep/stream/tail during runs
- Can rotate/archive old logs automatically
- JSONL format is trivially parseable

**Why table for runs:**
- Query "show me all builds from today"
- Track aggregate success rates over time
- Correlate with `qbuilder_queue` state

---

## Queue Schema

```sql
CREATE TABLE qbuilder_queue (
    queue_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    content_version_id INTEGER NOT NULL,
    relpath TEXT NOT NULL,
    content_hash TEXT,
    envelope TEXT NOT NULL,
    steps_json TEXT NOT NULL,      -- ["INGEST", "PARSE", ...]
    current_step INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending', -- pending, processing, done, error
    error_message TEXT,
    lease_holder TEXT,
    lease_expires_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

## CLI Commands

```bash
# Validate routing table
python -m qbuilder.cli validate-routing-table

# Test routing on sample files
python -m qbuilder.cli route --sample 25

# Reset queue tables
python -m qbuilder.cli reset --fresh-db

# Enqueue all files from active playset
python -m qbuilder.cli enqueue

# Process queue items
python -m qbuilder.cli run --limit 100

# Check queue status
python -m qbuilder.cli status
```

---

## Current Status

### ✅ Completed

1. **Routing Table** - `routing_table.json` with 13 envelopes, 32 file patterns
2. **Router** - Routes files to envelopes based on path patterns
3. **Queue Schema** - `qbuilder_queue` table created
4. **Enqueue** - Successfully queues 25,352 files from active playset
5. **Worker** - Lease-based work claiming with timeout recovery
6. **CLI** - All subcommands implemented
7. **Schema Analysis** - Decided to adapt existing schema with simplifications
8. **Logging Strategy** - `build_runs` table + JSONL files for details
9. **Schema Specification** - Documented exact column renames and final DDL

### 🔴 Pending

1. **Schema Changes** - Apply column renames and drops to database
2. **Executor Fixes** - Rewrite executors to use new schema
3. **Logging Infrastructure** - Implement `build_runs` table and JSONL logging

---

## Implementation Plan

### Phase 1: Schema Changes

| Task | Description |
|------|-------------|
| Drop deprecated tables | Remove 14 unused tables |
| Recreate core tables | `symbols`, `refs`, `localization_entries` with new columns |
| Add `build_runs` | New run tracking table |

### Phase 2: Fix Executors

| Task | Description |
|------|-------------|
| Rewrite `execute_symbols()` | Use `file_id`, `ast_id`, `column_number` |
| Rewrite `execute_refs()` | Use `file_id`, `ast_id`, `column_number` |
| Rewrite `execute_localization()` | Use `file_id`, `content_version_id` |
| Fix lookup executors | Use correct column names |

### Phase 3: Add Logging

| Task | Description |
|------|-------------|
| Implement JSONL logging | `~/.ck3raven/logs/qbuilder_*.jsonl` |
| Update worker | Log step timing, create run records |

### Phase 4: End-to-End Testing

| Task | Description |
|------|-------------|
| `reset --fresh-db` | Create clean database with new schema |
| `enqueue` | Queue all 25,352 files |
| `run --limit 100` | Process batch, verify no errors |
| `run` | Process all files to completion |
| Verify convergence | `status` shows 0 pending, 0 errors |

### Phase 5: Integration

| Task | Description |
|------|-------------|
| Daemon mode | Add `python -m qbuilder.cli daemon` |
| MCP integration | Connect QBuilder to CK3 Lens tools |
| Deprecate old builder | Remove/archive `builder/daemon.py` |

---

## Canonical Compliance

This implementation follows the canonical architecture:

1. **No `needs_*` inference** - Routing table determines work
2. **No stage detection** - Envelopes define all steps upfront  
3. **No artifact-based skipping** - Steps execute unconditionally
4. **Fresh DB assumption** - No migration logic
5. **Idempotent executors** - Can re-run without duplicates
6. **Lease-based recovery** - Crashed work items auto-recover
7. **content_version_id preserved** - Essential for playset filtering

---

## Files to Modify

### Phase 1: Schema

| File | Changes |
|------|---------|
| `src/ck3raven/db/schema.py` | Update DDL for symbols, refs, localization_entries |
| `qbuilder/schema.py` | Add `build_runs` DDL |

### Phase 2: Executors

| File | Changes |
|------|---------|
| `qbuilder/executors.py` | Rewrite all executors with new column names |

### Phase 3: Logging

| File | Changes |
|------|---------|
| `qbuilder/worker.py` | Add JSONL logging, run tracking |
| `qbuilder/cli.py` | Update `reset --fresh-db` for new tables |
