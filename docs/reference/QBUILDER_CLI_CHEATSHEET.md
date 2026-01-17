# QBuilder CLI Cheatsheet

> **Reference for QBuilder CLI Tools**  
> Last updated: January 17, 2026

---

## CLI Commands

### `qbuilder daemon` ⭐ PRIMARY
Start the QBuilder daemon with IPC server. **This is the primary entry point for production.**

```bash
python -m qbuilder.cli daemon
python -m qbuilder.cli daemon --port 19877  # Custom port
```

The daemon:
- Acquires exclusive writer lock (`{db_path}.writer.lock`)
- Starts IPC server on `localhost:19876` (default)
- Opens database in read-write mode
- Processes queue items continuously
- Releases lock on shutdown (Ctrl+C)

**Note:** Only one daemon can run per database. Multiple VS Code windows connect via IPC.

### `qbuilder build`
Process pending items in queue (runs as subprocess). **Use `daemon` for production.**

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

## Python API

### File Operations

#### `enqueue_file(mod_name, rel_path, content=None, priority=PRIORITY_FLASH)`
Enqueue a file for processing.

```python
from qbuilder.api import enqueue_file, PRIORITY_FLASH
result = enqueue_file("MyMod", "common/traits/test.txt", priority=PRIORITY_FLASH)
# EnqueueResult(success=True, build_id=123, file_id=456, message="Enqueued with priority=1")
```

#### `delete_file(mod_name, rel_path)`
Mark a file as deleted and remove from database.

```python
from qbuilder.api import delete_file
result = delete_file("MyMod", "common/traits/old.txt")
# {"success": True, "message": "File deleted", "file_id": 456}
```

### Status Queries

#### `get_queue_stats()`
Get queue statistics.

```python
from qbuilder.api import get_queue_stats
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
from qbuilder.api import start_background_build
result = start_background_build()
# {
#     "success": True,
#     "pid": 12345,
#     "log_file": "~/.ck3raven/logs/qbuilder_2026-01-11.jsonl",
#     "command": "python -m qbuilder.cli build"
# }
```

---

## Priority System

| Priority | Constant | Use Case |
|----------|----------|----------|
| 0 | `PRIORITY_NORMAL` | Batch discovery, full rebuilds |
| 1 | `PRIORITY_FLASH` | Single file updates after mutations |

Worker claims work with `ORDER BY priority DESC, build_id ASC`:
- Flash items (priority=1) always processed first
- Within same priority, FIFO ordering

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

## Envelope Types

| Envelope | Description | Steps |
|----------|-------------|-------|
| `E_SCRIPT` | Paradox script files (.txt) | Parse → Symbols → Refs |
| `E_LOC` | Localization files (.yml) | Parse → Loc entries |
| `E_GUI` | GUI files (.gui) | Parse |
| `E_SKIP` | Skip processing | None |

---

## Performance

| Operation | Typical Time |
|-----------|--------------|
| Full rebuild (vanilla + 648 mods) | ~2-4 hours |
| Incremental (10 files changed) | ~10-30 seconds |
| Single file (flash priority) | <1 second |

### Optimizations

- **WAL mode**: Concurrent reads while daemon writes
- **Content dedup**: Same content = same hash = shared storage
- **Priority queue**: Flash items processed immediately
- **mtime filtering**: Skip unchanged files without reading
