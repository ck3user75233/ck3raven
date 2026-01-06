# Block-Based Logging System - Design Brief v1.1

> **Status:** IMPLEMENTED  
> **Author:** CK3 Raven Dev Agent  
> **Date:** January 6, 2026  
> **Purpose:** Simplified architecture for block-based daemon logging with empirical tracking

---

## 1. Problem Statement

The original v1.0 design proposed a separate BlockTracker class with file-level callbacks. This was problematic:

1. **Library coupling** - Required modifying ingest/extraction library functions
2. **Dual tracking** - BlockTracker duplicated work already done by BuildTracker
3. **Complexity** - Two separate tracking systems to maintain

## 2. Solution: Unified BuildTracker with Empirical Logging

Instead of instrumenting library functions, we:

1. **Log empirically** - Query the database after each phase to find what was processed
2. **Unified tracking** - All logging lives in BuildTracker (no separate BlockTracker)
3. **Reconstruct blocks** - Generate block summaries from per-file log entries post-hoc

---

## 3. Architecture

### 3.1 Simplified Flow

```
Phase executes (library functions unchanged)
    │
    ├─► BuildTracker.log_phase_delta_*() 
    │       │
    │       └─► Query DB to find files processed in this phase
    │           └─► Bulk insert to ingest_log table
    │
    └─► On build complete:
            BuildTracker.reconstruct_blocks()
                │
                └─► Partition log entries into blocks
                    └─► Insert block summaries to ingest_blocks
```

### 3.2 Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| No file-level callbacks | Libraries remain untouched, less coupling |
| Delta queries after phases | Empirical - ask DB what changed, not instrument |
| Post-hoc block reconstruction | Blocks are for audit/debugging, not real-time |
| All methods in BuildTracker | Single class handles all build/log concerns |

---

## 4. Database Schema

### 4.1 ingest_log (Per-File Records)

```sql
CREATE TABLE IF NOT EXISTS ingest_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    
    -- File identification
    file_id INTEGER,                   -- FK to files table
    content_version_id INTEGER,        -- Which mod/vanilla
    relpath TEXT NOT NULL,             -- Relative path within mod
    
    -- Processing result
    status TEXT NOT NULL DEFAULT 'processed',  -- processed/skipped/error
    size_raw INTEGER,                  -- Bytes read from disk
    size_stored INTEGER,               -- Bytes stored (AST, etc.)
    content_hash TEXT,                 -- File content hash
    
    -- Error details (if status='error')
    error_type TEXT,
    error_msg TEXT,
    
    FOREIGN KEY (build_id) REFERENCES builder_runs(build_id),
    FOREIGN KEY (file_id) REFERENCES files(file_id)
);

CREATE INDEX IF NOT EXISTS idx_ingest_log_build ON ingest_log(build_id);
CREATE INDEX IF NOT EXISTS idx_ingest_log_phase ON ingest_log(build_id, phase);
```

### 4.2 ingest_blocks (Reconstructed Summaries)

```sql
CREATE TABLE IF NOT EXISTS ingest_blocks (
    block_id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    block_number INTEGER NOT NULL,
    
    -- Timing (derived from log entries)
    started_at TEXT,
    ended_at TEXT,
    duration_sec REAL,
    
    -- Aggregated metrics
    files_count INTEGER NOT NULL DEFAULT 0,
    files_processed INTEGER NOT NULL DEFAULT 0,
    files_error INTEGER NOT NULL DEFAULT 0,
    bytes_raw INTEGER NOT NULL DEFAULT 0,
    bytes_stored INTEGER NOT NULL DEFAULT 0,
    
    -- Integrity
    merkle_hash TEXT,                  -- Hash of file hashes in block
    
    -- Log entry range
    log_id_start INTEGER,
    log_id_end INTEGER,
    
    UNIQUE(build_id, phase, block_number),
    FOREIGN KEY (build_id) REFERENCES builder_runs(build_id)
);

CREATE INDEX IF NOT EXISTS idx_ingest_blocks_build ON ingest_blocks(build_id);
```

---

## 5. BuildTracker Methods

### 5.1 Per-File Logging

```python
def log_file(self, phase: str, file_id: int, relpath: str, 
             status: str = "processed", **kwargs) -> None:
    """Log a single file operation."""

def log_files_bulk(self, phase: str, entries: list[dict]) -> int:
    """Bulk insert file log entries. Returns count inserted."""
```

### 5.2 Delta-Query Logging

```python
def log_phase_delta_ingest(self, phase: str) -> int:
    """Log files ingested during ingest phases by querying DB.
    
    Finds files in `files` table that aren't logged yet for this phase.
    Returns count of files logged.
    """

def log_phase_delta_ast(self, phase: str = "ast_generation") -> int:
    """Log AST generation results by querying files with ASTs.
    
    Finds files that now have AST column populated.
    Returns count of files logged.
    """
```

### 5.3 Block Reconstruction

```python
def reconstruct_blocks(self, block_size: int = 500) -> int:
    """Partition ingest_log entries into blocks and store summaries.
    
    Called after build completes. Creates ingest_blocks records
    with aggregated metrics and Merkle hashes.
    
    Returns count of blocks created.
    """
```

### 5.4 Error Queries

```python
def get_phase_errors(self, phase: str | None = None) -> list[dict]:
    """Get logged errors, optionally filtered by phase."""
```

---

## 6. Integration Points

### 6.1 Phase Instrumentation

After each phase's `end_step()`, call the appropriate delta-query logger:

```python
# After vanilla ingest
logged = build_tracker.log_phase_delta_ingest("vanilla_ingest")
logger.debug(f"Logged {logged} vanilla files to ingest_log")
build_tracker.end_step("vanilla_ingest", StepStats(rows_out=vanilla_files))

# After mod ingest
logged = build_tracker.log_phase_delta_ingest("mod_ingest")

# After AST generation
logged = build_tracker.log_phase_delta_ast("ast_generation")
```

### 6.2 Build Completion

At build end, reconstruct blocks for audit trail:

```python
block_count = build_tracker.reconstruct_blocks()
logger.debug(f"Reconstructed {block_count} ingest blocks")
build_tracker.complete(build_counts)
```

---

## 7. Comparison with v1.0

| Aspect | v1.0 (BlockTracker) | v1.1 (Unified BuildTracker) |
|--------|---------------------|------------------------------|
| Separate class | BlockTracker | No - all in BuildTracker |
| Library changes | Required callbacks | None - queries DB |
| Real-time blocks | Yes | No - reconstructed post-hoc |
| Merkle hash timing | During processing | During reconstruction |
| Complexity | Higher | Lower |
| Table | system_ingest_log | ingest_log + ingest_blocks |

---

## 8. Archived Code

The original BlockTracker implementation was archived:
- From: `builder/block_logging.py`
- To: `archive/deprecated_builder/block_logging.py`

---

## 9. Files Changed

| File | Changes |
|------|---------|
| `builder/daemon.py` | Added BuildTracker methods, removed BlockTracker imports |
| `src/ck3raven/db/schema.py` | Added ingest_log + ingest_blocks tables |
| `builder/block_logging.py` | Archived to deprecated folder |

---

## 10. Success Criteria

1. ✅ **No library modifications** - Ingest/extraction functions unchanged
2. ✅ **Unified tracking** - Single BuildTracker class handles all logging
3. ✅ **Empirical approach** - Query DB for what happened, don't instrument
4. ✅ **Block reconstruction** - Can generate summaries for audit/debugging
5. ✅ **Simpler codebase** - One less class to maintain
