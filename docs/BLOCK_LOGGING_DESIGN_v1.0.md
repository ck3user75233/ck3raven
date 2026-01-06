# Block-Based Logging System - Design Brief v1.0

> **Status:** APPROVED FOR IMPLEMENTATION  
> **Author:** CK3 Raven Dev Agent  
> **Date:** January 6, 2026  
> **Purpose:** Define architecture for block-based daemon logging with metrics and persistence

---

## 1. Problem Statement

The current daemon logging has several issues:
1. **No visibility into batch progress** - Only per-file or per-phase logging
2. **No aggregated metrics** - Cannot easily see throughput, error rates, or bottlenecks
3. **No persistence** - Log analysis requires parsing text files
4. **Heartbeat staleness** - Long-running operations appear hung
5. **Hard to identify slowdowns** - No timing data per batch to find outliers

## 2. Solution Overview

Introduce **block-based logging** where daemon operations are grouped into blocks:
- Each block represents a batch of work (500 files OR 50MB, whichever comes first)
- Blocks have aggregated metrics (files, bytes, duration, errors)
- Blocks are persisted to SQLite for querying
- Status command shows recent blocks with throughput

---

## 3. Architecture

### 3.1 Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                     BlockTracker                             │
│  - Manages current block state                               │
│  - Decides when to close/open blocks                         │
│  - Computes metrics and hashes                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     BlockLog (dataclass)                     │
│  - Immutable record of a completed block                     │
│  - Contains all metrics, timing, hash                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  system_ingest_log (SQLite)                  │
│  - Persisted block records                                   │
│  - Queryable by phase, time, build_id                        │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Data Flow

```
Phase Loop (e.g., ingest, symbol_extraction)
    │
    ├─► BlockTracker.record_file(path, size, status)
    │       │
    │       └─► If block thresholds met:
    │               BlockTracker.close_block()
    │                   │
    │                   ├─► Compute metrics
    │                   ├─► Compute block hash
    │                   ├─► Create BlockLog
    │                   ├─► Persist to DB
    │                   └─► Open new block
    │
    └─► On phase complete:
            BlockTracker.flush() → close any partial block
```

---

## 4. Data Structures

### 4.1 BlockLog (Immutable Record)

```python
@dataclass(frozen=True)
class BlockLog:
    """Immutable record of a completed block."""
    
    # Identity
    block_id: str              # UUID for this block
    build_id: str              # Parent build UUID
    phase: str                 # e.g., "ingest", "symbol_extraction"
    block_number: int          # Sequence within phase (1, 2, 3...)
    
    # Timing
    started_at: datetime
    ended_at: datetime
    duration_sec: float
    
    # File Metrics
    files_scanned: int         # Total files examined
    files_processed: int       # Files that produced output
    files_skipped_uptodate: int  # Skipped (hash unchanged)
    files_skipped_error: int   # Skipped (parse/read error)
    files_skipped_ignored: int # Skipped (not in scope, e.g., .dds)
    
    # Byte Metrics
    bytes_scanned: int         # Total bytes read from disk
    bytes_stored: int          # Bytes written to DB (AST blobs, etc.)
    
    # Integrity
    block_hash: str            # Merkle root of file hashes in block
    
    # Error Manifest (optional)
    error_manifest: Optional[List[Dict]]  # [{path, error_type, message}]
```

### 4.2 StageSummary (Phase Aggregation)

```python
@dataclass
class StageSummary:
    """Aggregated metrics for an entire phase."""
    
    phase: str
    build_id: str
    total_blocks: int
    
    # Aggregated metrics
    total_files_scanned: int
    total_files_processed: int
    total_files_skipped: int
    total_bytes_scanned: int
    total_bytes_stored: int
    total_duration_sec: float
    
    # Derived
    avg_throughput_files_sec: float
    avg_throughput_mb_sec: float
    error_rate: float  # files_skipped_error / files_scanned
    
    # Block stats
    slowest_block_id: str
    slowest_block_duration: float
    fastest_block_id: str
    fastest_block_duration: float
```

### 4.3 BlockTracker (Runtime Manager)

```python
class BlockTracker:
    """Manages block lifecycle during daemon execution."""
    
    # Thresholds (configurable)
    FILE_THRESHOLD: int = 500
    BYTE_THRESHOLD: int = 50 * 1024 * 1024  # 50MB
    
    def __init__(self, conn: sqlite3.Connection, build_id: str, phase: str):
        ...
    
    def record_file(
        self,
        path: str,
        size_bytes: int,
        status: Literal["processed", "uptodate", "error", "ignored"],
        content_hash: Optional[str] = None,
        bytes_stored: int = 0,
        error_info: Optional[Dict] = None,
    ) -> Optional[BlockLog]:
        """Record a file operation. Returns BlockLog if block was closed."""
        ...
    
    def close_block(self) -> BlockLog:
        """Force-close current block, persist, and return record."""
        ...
    
    def flush(self) -> Optional[BlockLog]:
        """Close partial block if any files recorded. Called at phase end."""
        ...
    
    def get_current_stats(self) -> Dict:
        """Get stats for in-progress block (for status display)."""
        ...
```

---

## 5. Database Schema

### 5.1 New Table: system_ingest_log

```sql
CREATE TABLE IF NOT EXISTS system_ingest_log (
    -- Identity
    block_id TEXT PRIMARY KEY,
    build_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    block_number INTEGER NOT NULL,
    
    -- Timing
    started_at TEXT NOT NULL,  -- ISO8601
    ended_at TEXT NOT NULL,
    duration_sec REAL NOT NULL,
    
    -- File metrics
    files_scanned INTEGER NOT NULL DEFAULT 0,
    files_processed INTEGER NOT NULL DEFAULT 0,
    files_skipped_uptodate INTEGER NOT NULL DEFAULT 0,
    files_skipped_error INTEGER NOT NULL DEFAULT 0,
    files_skipped_ignored INTEGER NOT NULL DEFAULT 0,
    
    -- Byte metrics
    bytes_scanned INTEGER NOT NULL DEFAULT 0,
    bytes_stored INTEGER NOT NULL DEFAULT 0,
    
    -- Integrity
    block_hash TEXT,
    
    -- Error manifest (JSON array)
    error_manifest TEXT,
    
    -- Indexing
    UNIQUE(build_id, phase, block_number)
);

CREATE INDEX IF NOT EXISTS idx_ingest_log_build 
    ON system_ingest_log(build_id);
CREATE INDEX IF NOT EXISTS idx_ingest_log_phase 
    ON system_ingest_log(phase);
CREATE INDEX IF NOT EXISTS idx_ingest_log_time 
    ON system_ingest_log(ended_at DESC);
```

---

## 6. CLI Integration

### 6.1 Status Command Enhancement

```bash
# Default: show last 5 blocks
python builder/daemon.py status

# Output:
Daemon running: True
PID: 34028
Last heartbeat: 2.1s ago

Current Phase: symbol_extraction (4/7)
Current Block: #12 | 234/500 files | 12.3MB | 45s elapsed

Recent Blocks:
  #11 | symbol_extraction | 500 files | 23.4MB | 52s | 9.6 files/s | ✓
  #10 | symbol_extraction | 500 files | 45.1MB | 89s | 5.6 files/s | ✓
  #9  | symbol_extraction | 500 files | 18.2MB | 31s | 16.1 files/s | ✓
  #8  | ast_generation    | 500 files | 67.8MB | 124s | 4.0 files/s | 2 errors
  #7  | ast_generation    | 500 files | 51.2MB | 98s | 5.1 files/s | ✓
```

### 6.2 Verbose Mode

```bash
python builder/daemon.py status --verbose

# Additional output:
Block #8 Errors:
  - common/character_interactions/esr_override.txt: ParseTimeout (30s)
  - common/scripted_effects/broken.txt: SyntaxError line 45
```

### 6.3 JSON Format

```bash
python builder/daemon.py status --format=json

# Output:
{
  "daemon_running": true,
  "pid": 34028,
  "current_phase": "symbol_extraction",
  "current_block": {
    "number": 12,
    "files_processed": 234,
    "bytes_processed": 12943872,
    "elapsed_sec": 45.2
  },
  "recent_blocks": [...]
}
```

---

## 7. New Symbols/Tokens

### 7.1 Summary Table

| Symbol | Type | Location | Rationale |
|--------|------|----------|-----------|
| `BlockLog` | dataclass | `builder/block_logging.py` | Immutable record for completed blocks - core data structure |
| `StageSummary` | dataclass | `builder/block_logging.py` | Aggregated phase metrics for reporting |
| `BlockTracker` | class | `builder/block_logging.py` | Runtime manager - encapsulates block lifecycle logic |
| `FileStatus` | Literal type | `builder/block_logging.py` | Type-safe status enum: "processed", "uptodate", "error", "ignored" |
| `system_ingest_log` | table | `src/ck3raven/db/schema.py` | Persistence layer for block records |
| `FILE_THRESHOLD` | constant | `builder/block_logging.py` | Configurable block size (default 500 files) |
| `BYTE_THRESHOLD` | constant | `builder/block_logging.py` | Configurable block size (default 50MB) |
| `compute_merkle_root()` | function | `builder/block_logging.py` | Hash integrity - detect data corruption/tampering |

### 7.2 Detailed Rationale

#### `BlockLog` (dataclass)
- **Why frozen:** Blocks are historical records that should never be mutated
- **Why separate from tracker:** Clean separation between runtime state and persisted records
- **Why all these metrics:** Enable post-hoc analysis of build performance

#### `BlockTracker` (class)
- **Why class not functions:** Needs to maintain state across file operations
- **Why threshold-based:** Balances granularity (too small = overhead) vs. visibility (too large = no progress)
- **Why 500 files / 50MB:** Based on typical mod sizes - ~100-500 files per mod, 50MB captures large AST files

#### `FileStatus` (Literal)
- **Why Literal not Enum:** Simpler serialization, works directly with SQLite
- **Why these 4 statuses:**
  - `processed`: Work done, output generated
  - `uptodate`: Hash matched, skipped (incremental)
  - `error`: Failed to process (parse error, timeout, etc.)
  - `ignored`: Out of scope (binary files, localization in symbol phase, etc.)

#### `system_ingest_log` (table)
- **Why "system_" prefix:** Distinguishes from content tables (files, symbols, refs)
- **Why separate from builder_runs:** builder_runs tracks phases, this tracks granular blocks
- **Why JSON for error_manifest:** Variable-length, rarely queried, simple to extend

#### `compute_merkle_root()` (function)
- **Why Merkle not simple hash:** Can verify individual files if needed
- **Why include:** Enables integrity checks, reproducibility verification

---

## 8. Integration Points

### 8.1 Files to Modify

| File | Changes |
|------|---------|
| `builder/daemon.py` | Import BlockTracker, instrument phase loops |
| `builder/block_logging.py` | NEW - all block logging code |
| `src/ck3raven/db/schema.py` | Add system_ingest_log table |

### 8.2 Phase Instrumentation

Each phase loop needs to call `BlockTracker.record_file()`:

```python
# Example: ingest phase
tracker = BlockTracker(conn, build_id, "ingest")

for file_path in files_to_process:
    size = file_path.stat().st_size
    
    try:
        if is_uptodate(file_path):
            tracker.record_file(file_path, size, "uptodate")
            continue
        
        content = file_path.read_bytes()
        store_file(content)
        tracker.record_file(file_path, size, "processed", bytes_stored=len(content))
        
    except Exception as e:
        tracker.record_file(file_path, size, "error", error_info={"type": type(e).__name__, "msg": str(e)})

tracker.flush()  # Close final partial block
```

---

## 9. Performance Considerations

### 9.1 Overhead

- **Memory:** BlockTracker holds ~500 file paths and hashes per block (~50KB max)
- **CPU:** Merkle hash computation is O(n) per block, negligible vs. AST parsing
- **I/O:** One INSERT per block (every 500 files), not per file

### 9.2 Query Patterns

Indexed for common queries:
- "Show last N blocks" → `idx_ingest_log_time`
- "Show blocks for this build" → `idx_ingest_log_build`
- "Show blocks for phase X" → `idx_ingest_log_phase`

---

## 10. Success Criteria

1. **Status shows live block progress** - Current block file/byte counts visible
2. **Identify slow blocks** - Can find blocks with anomalous duration
3. **Error aggregation** - Errors grouped by block, not scattered in logs
4. **Reproducible queries** - `SELECT * FROM system_ingest_log WHERE ...`
5. **Minimal overhead** - <1% slowdown vs. current implementation

---

## 11. Open Questions (Resolved)

1. **Should blocks span phases?** → No, each phase starts fresh at block #1
2. **Retention policy?** → Keep last 10 builds, auto-cleanup older
3. **Block hash algorithm?** → SHA256 (standard, secure)
4. **Threshold tuning?** → Start with 500 files / 50MB, tune based on data

---

## 12. Implementation Plan

| Phase | Deliverable | Effort |
|-------|-------------|--------|
| 1 | Create `block_logging.py` with dataclasses | 30 min |
| 2 | Add `system_ingest_log` table to schema | 15 min |
| 3 | Implement `BlockTracker.record_file()` | 45 min |
| 4 | Implement `BlockTracker.close_block()` with Merkle hash | 30 min |
| 5 | Instrument daemon phases | 60 min |
| 6 | Update status command | 45 min |
| 7 | Add `--verbose` and `--format=json` | 30 min |
| 8 | Testing and tuning | 60 min |

**Total estimated effort:** ~5-6 hours

---

## Appendix A: Example Block Record

```json
{
  "block_id": "blk-a1b2c3d4",
  "build_id": "55e5fccd-d6c7-4269-b305-baee92a7664e",
  "phase": "symbol_extraction",
  "block_number": 7,
  "started_at": "2026-01-06T07:20:00.000000",
  "ended_at": "2026-01-06T07:21:32.456789",
  "duration_sec": 92.456789,
  "files_scanned": 500,
  "files_processed": 423,
  "files_skipped_uptodate": 72,
  "files_skipped_error": 2,
  "files_skipped_ignored": 3,
  "bytes_scanned": 52428800,
  "bytes_stored": 8945632,
  "block_hash": "a3f8b2c1d4e5f6789012345678901234",
  "error_manifest": [
    {"path": "common/foo.txt", "type": "ParseTimeout", "message": "30s timeout"},
    {"path": "common/bar.txt", "type": "SyntaxError", "message": "line 45"}
  ]
}
```
