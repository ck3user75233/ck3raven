# Database Builder Architecture

> **Last Updated:** January 2026  
> **Status:** AUTHORITATIVE

## Overview

The ck3raven database stores parsed CK3 content for fast querying by the MCP tools. The builder (`builder/daemon.py`) runs as a detached daemon, processing files through 7 phases with full incremental support.

---

## Quick Reference

```bash
# Start rebuild (file change detection ON by default)
python builder/daemon.py start

# Check status
python builder/daemon.py status

# View logs (follow mode)
python builder/daemon.py logs -f

# Stop daemon
python builder/daemon.py stop
```

---

## Directory Structure

```
builder/                          # THE database builder (detached daemon)
   daemon.py                      # Main daemon script (~2800 lines)
   incremental.py                 # Single-file refresh for MCP writes
   pending_refresh.py             # Deferred refresh queue (MCP → daemon)
   config.py                      # Configuration (paths, etc.)
   migrations/                    # Schema migration scripts

src/ck3raven/db/                  # Database library functions
   schema.py                      # Schema definition + SCHEMA_VERSION
   ingest.py                      # Directory/mod ingestion
   symbols.py                     # Symbol extraction logic
   references.py                  # Reference extraction logic
   asts.py                        # AST generation logic
   file_routes.py                 # File classification (script/loc/lookup/skip)
```

---

## Daemon Usage

### Commands

| Command | Description |
|---------|-------------|
| `start` | Start rebuild daemon (detaches to background) |
| `status` | Show current phase, progress, heartbeat |
| `logs` | View daemon log output |
| `logs -f` | Follow log output (tail -f style) |
| `stop` | Stop running daemon |

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--force` | Off | Clear all data and rebuild from scratch |
| `--symbols-only` | Off | Skip ingest, only re-extract symbols/refs |
| `--ingest-all` | Off | Ingest ALL mods (not just active playset) |
| `--full-rebuild` | Off | Force full rebuild of all mods |
| `--dry-run` | Off | Show what would be done without making changes |
| `--skip-file-check` | Off | Skip file change detection (faster but may miss changes) |
| `--debug PHASE` | Off | Debug specific phase with detailed timing |
| `--test` | Off | Run synchronously with verbose output |

**Note:** File change detection is ON by default. Use `--skip-file-check` to disable it for faster builds when you know nothing has changed.

### Daemon Files

Located in `~/.ck3raven/daemon/`:

| File | Purpose |
|------|---------|
| `rebuild.pid` | Process ID for monitoring |
| `rebuild_status.json` | Current phase, progress, counts |
| `rebuild.log` | Full log output |
| `heartbeat` | Timestamp updated every 30s |
| `pending_refresh.log` | Deferred file refreshes from MCP |

---

## Build Phases

The daemon processes files through 7 phases. Each phase is **self-skipping** - it queries the database to find work and does nothing if there's none.

| # | Phase | Description |
|---|-------|-------------|
| 1 | **vanilla_ingest** | Scan vanilla game files → `files` table |
| 2 | **mod_ingest** | Scan Workshop + local mods → `files` table |
| 3 | **ast_generation** | Parse script files → `asts` table |
| 4 | **symbol_extraction** | Extract definitions → `symbols` table |
| 5 | **ref_extraction** | Extract usages → `refs` table |
| 6 | **localization_parsing** | Parse .yml files → `localization` table |
| 7 | **lookup_extraction** | Extract lookup tables (provinces, etc.) |

### Phase Self-Skip Behavior

Each phase function checks database state internally:

- **vanilla_ingest**: Checks if vanilla content_version exists
- **mod_ingest**: Compares filesystem mods to database, detects changes via mtime/hash
- **ast_generation**: Queries for files without ASTs (`generate_missing_asts`)
- **symbol_extraction**: Queries for ASTs without extracted symbols
- **ref_extraction**: Queries for ASTs without extracted refs
- **localization_parsing**: Queries for .yml files not yet parsed
- **lookup_extraction**: Queries for lookup files not yet extracted

**Key insight:** The database IS the source of truth for what work needs doing. No separate "resume state" tracking needed.

---

## Incremental Updates

### Core Principle

**Don't rebuild what hasn't changed.** The builder tracks changes at multiple levels:

1. **File level** - `mtime` for fast filtering, `content_hash` for definitive change detection
2. **AST level** - Keyed by `content_hash` (content-addressable, deduped)
3. **Symbol/Ref level** - Keyed by `file_id` (needs mod context for conflicts)

### File Change Detection (Default ON)

When running normally, the daemon:

1. Scans filesystem for all mod files
2. Compares stored `files.mtime` vs actual mtime
3. For changed files: reads content, computes hash
4. Categorizes as: `added`, `removed`, `changed`, `unchanged`
5. Processes only affected files

Use `--skip-file-check` to bypass this (trusts database is current).

### MCP Write Integration

When MCP tools write files to local mods:

1. **If daemon is stopped**: `refresh_single_file()` updates DB immediately
2. **If daemon is running**: Write is queued to `pending_refresh.log`
3. **After build completes**: Daemon processes pending queue

This prevents MCP from blocking on DB locks during builds.

### Pending Refresh Queue

Format (`~/.ck3raven/daemon/pending_refresh.log`):
```
WRITE|mod_name|rel_path
DELETE|mod_name|rel_path
```

The daemon atomically reads and clears this file after Phase 7, processing each entry via `refresh_single_file()` or `mark_file_deleted()`.

---

## BuildTracker (Audit Log)

The `BuildTracker` class records build progress to `builder_runs` and `builder_steps` tables. This is an **audit log only** - it does NOT drive resume behavior.

### Tables

**builder_runs:**
| Column | Description |
|--------|-------------|
| `build_id` | Unique ID (UUID) |
| `started_at` | Build start timestamp |
| `completed_at` | Build completion timestamp |
| `state` | running / complete / failed |
| `error_message` | Error if failed |

**builder_steps:**
| Column | Description |
|--------|-------------|
| `build_id` | Parent build |
| `step_name` | Phase name |
| `started_at` | Step start |
| `completed_at` | Step completion |
| `state` | running / complete / failed / skipped |
| `rows_out` | Rows produced |
| `rows_skipped` | Rows skipped |
| `rows_errored` | Rows with errors |

### Why Not Resume From Audit Log?

The audit log records what happened, but the **database state** is what matters:

- A file without an AST needs an AST (regardless of what the audit log says)
- An AST without symbols needs symbol extraction
- The audit log is for debugging, not control flow

---

## Configuration

The daemon uses `builder/config.py` for paths:

```python
@dataclass
class Config:
    vanilla_path: Path      # CK3 game installation
    workshop_path: Path     # Steam Workshop mods
    local_mods_path: Path   # Local mods folder
    db_path: Path           # SQLite database
```

Default locations (Windows):
- Vanilla: `C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game`
- Workshop: `C:/Program Files (x86)/Steam/steamapps/workshop/content/1158310`
- Local mods: `~/Documents/Paradox Interactive/Crusader Kings III/mod`
- Database: `~/.ck3raven/ck3raven.db`

---

## Performance

| Operation | Typical Time |
|-----------|--------------|
| Full rebuild (vanilla + 648 mods) | ~2-4 hours |
| Incremental (10 files changed) | ~10-30 seconds |
| Single file refresh (MCP write) | <1 second |

### Optimizations

- **WAL mode**: SQLite write-ahead logging for concurrent reads
- **Checkpointing**: After each phase
- **Content deduplication**: Same content = same hash = shared storage
- **mtime filtering**: Skip unchanged files without reading

---

## Debugging

### Debug Mode

```bash
# Debug specific phase
python builder/daemon.py start --debug ast_generation --debug-limit 10

# Debug all phases  
python builder/daemon.py start --debug all
```

Output goes to `~/.ck3raven/daemon/debug_output.json`.

### Test Mode

```bash
# Run synchronously with verbose output
python builder/daemon.py start --test --vanilla-path /path/to/fixture
```

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Daemon already running" | Stale PID file | `daemon.py stop` or delete `rebuild.pid` |
| Hangs at phase start | DB lock contention | Stop other DB connections |
| MCP writes hang | Daemon holding DB lock | Fixed: MCP now queues to pending_refresh |
| Phases re-run unnecessarily | `--force` flag | Remove `--force`, use incremental |

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - Overall system architecture
- [02_BUILDER_DESIGN_CURRENT_STATE.md](02_BUILDER_DESIGN_CURRENT_STATE.md) - Design notes and open questions
- [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) - Architectural principles
