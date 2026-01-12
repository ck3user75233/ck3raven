# QBuilder - CK3Raven Build System

> **Status:** IMPLEMENTATION REFERENCE  
> **Last Updated:** January 11, 2026  
> **Location:** `qbuilder/`  
> **Canonical Authority:** [QBUILDER CANONICAL.md](QBUILDER%20CANONICAL.md)

---

## CANONICAL ARCHITECTURE

This document is an **implementation reference**. For authoritative rules, banned concepts, 
and non-negotiable constraints, see **[QBUILDER CANONICAL.md](QBUILDER%20CANONICAL.md)**.

Key canonical rules:
- **Single queue** - build_queue is the only scheduler
- **No vanilla/mod CVID distinction** - all content_versions are uniform
- **Signature-based validity** - AST rows valid only if signature matches
- **No stage scans** - no "missing AST/symbol" inference

---

## Overview

QBuilder is the canonical build system for CK3Raven. It handles:
- Parsing CK3 script files into ASTs
- Extracting symbols (traits, events, decisions, etc.)
- Extracting references (symbol usages)
- Storing all data in SQLite database

**Key Design Principles:**
1. **Single queue** - All work goes through `build_queue` table
2. **Priority-based** - Flash updates (mutations) before batch work
3. **Fingerprint correctness** - Work items bound to (mtime, size, hash)
4. **Non-blocking** - Enqueue returns immediately, worker processes async

---

## Quick Start

### Run a Full Build (Subprocess)
```bash
cd ck3raven
python -m qbuilder.cli build
```

### Background Build
```python
from qbuilder.api import start_background_build
result = start_background_build()
print(f"PID: {result['pid']}, Log: {result['log_file']}")
```

### Flash Update (After File Mutation)
```python
from qbuilder.api import enqueue_file, PRIORITY_FLASH
result = enqueue_file("MyMod", "common/traits/fix.txt", priority=PRIORITY_FLASH)
print(f"Build ID: {result.build_id}")
```

### Check Queue Status
```python
from qbuilder.api import get_queue_stats
stats = get_queue_stats()
print(f"Pending: {stats['pending']}, Completed: {stats['completed']}")
```

---

## Architecture

### Components

| Component | File | Purpose |
|-----------|------|---------|
| **Schema** | `schema.py` | SQLite table definitions |
| **Discovery** | `discovery.py` | File scanning and queue population |
| **Router** | `routing.py` | Route files to processing envelopes |
| **Worker** | `worker.py` | Process queue items |
| **CLI** | `cli.py` | Command-line interface |
| **API** | `api.py` | Public API for MCP tools |
| **Logging** | `logging.py` | JSONL structured logging |

### Data Flow

```
Files on Disk
    |
Discovery (scan folders, compute fingerprints)
    |
build_queue (pending items with envelope + fingerprint)
    |
Worker (claim -> process -> complete)
    |
files, asts, symbols, refs tables
```

### Priority System

| Priority | Constant | Use Case |
|----------|----------|----------|
| 0 | `PRIORITY_NORMAL` | Batch discovery, full rebuilds |
| 1 | `PRIORITY_FLASH` | Single file updates after mutations |

Worker claims work with `ORDER BY priority DESC, build_id ASC`:
- Flash items (priority=1) always processed first
- Within same priority, FIFO ordering

---

## Database Schema

### build_queue Table

```sql
CREATE TABLE build_queue (
    build_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    envelope TEXT NOT NULL,          -- E_SCRIPT, E_LOC, etc.
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    work_file_mtime REAL,
    work_file_size INTEGER,
    work_file_hash TEXT,
    created_at REAL,
    started_at REAL,
    completed_at REAL,
    error_message TEXT,
    UNIQUE(file_id, envelope, work_file_mtime, work_file_size, 
           COALESCE(work_file_hash, ''))
)
```

### AST Signature Fields (Validity Binding)

```sql
-- Added to asts table for signature-based validity
asts.file_id INTEGER        -- FK to files
asts.src_file_mtime REAL    -- Source file mtime at parse time
asts.src_file_size INTEGER  -- Source file size at parse time
asts.src_file_hash TEXT     -- Source file hash at parse time
```

An AST row is valid **only if** its signature fields match the current file fingerprint.

### Envelope Types

| Envelope | Description | Steps |
|----------|-------------|-------|
| `E_SCRIPT` | Paradox script files (.txt) | Parse -> Symbols -> Refs |
| `E_LOC` | Localization files (.yml) | Parse -> Loc entries |
| `E_GUI` | GUI files (.gui) | Parse |
| `E_SKIP` | Skip processing | None |

---

## API Reference

### File Operations

#### `enqueue_file(mod_name, rel_path, content=None, priority=PRIORITY_FLASH)`
Enqueue a file for processing.

```python
result = enqueue_file("MyMod", "common/traits/test.txt", priority=PRIORITY_FLASH)
# EnqueueResult(success=True, build_id=123, file_id=456, message="Enqueued with priority=1")
```

#### `delete_file(mod_name, rel_path)`
Mark a file as deleted and remove from database.

```python
result = delete_file("MyMod", "common/traits/old.txt")
# {"success": True, "message": "File deleted", "file_id": 456}
```

### Status Queries

#### `get_queue_stats()`
Get queue statistics.

```python
stats = get_queue_stats()
# {
#     "pending": 100,
#     "processing": 1,
#     "completed": 500,
#     "error": 5,
#     "flash_pending": 0,
#     "normal_pending": 100,
#     "has_work": True
# }
```

### Background Builds

#### `start_background_build()`
Launch a background build subprocess.

```python
result = start_background_build()
# {
#     "success": True,
#     "pid": 12345,
#     "log_file": "~/.ck3raven/logs/qbuilder_2026-01-11.jsonl",
#     "command": "python -m qbuilder.cli build"
# }
```

---

## CLI Commands

### `qbuilder build`
Process pending items in queue (runs as subprocess).

```bash
python -m qbuilder.cli build
python -m qbuilder.cli build --max-tasks 100
```

### `qbuilder discover`
Scan files and populate build queue.

```bash
python -m qbuilder.cli discover
```

### `qbuilder status`
Show queue statistics.

```bash
python -m qbuilder.cli status
```

---

## Logging

QBuilder writes structured JSONL logs to `~/.ck3raven/logs/qbuilder_YYYY-MM-DD.jsonl`.

Log entry types:
- `run_start` - Build run started
- `run_complete` - Build run finished  
- `item_claimed` - Work item claimed
- `item_complete` - Work item finished
- `item_error` - Work item failed
- `step_start/complete/error` - Executor step events

---

## Migration from Old Builder

The old `builder/` module is archived in `legacy/old_builder/`. All MCP tools now use `qbuilder.api`.

| Old Import | New Import |
|------------|------------|
| `from builder.incremental import refresh_single_file` | `from qbuilder.api import enqueue_file` |
| `from builder.incremental import mark_file_deleted` | `from qbuilder.api import delete_file` |
| `from builder.incremental import check_playset_build_status` | `from qbuilder.api import check_playset_build_status` |
| `from builder.daemon import is_daemon_running` | `from qbuilder.api import is_build_running` |
| `from builder.db_health import check_and_recover` | `from qbuilder.api import check_and_recover` |
