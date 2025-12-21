# Database Builder Architecture

## Overview

The ck3raven database stores parsed CK3 content for fast querying by the MCP tools. This document covers the build system, incremental updates, and future roadmap.

## Current Scripts

| Script | Purpose | Status |
|--------|---------|--------|
| `scripts/rebuild_database.py` | Original rebuild script (runs in terminal) | ⚠️ Deprecated |
| `scripts/rebuild_daemon.py` | Detached daemon for long-running rebuilds | ✅ Active |
| `scripts/build_database.py` | Lightweight build orchestrator | 🔲 Stub |

## Daemon Usage

The daemon runs completely detached from terminals (avoids Ctrl+C injection issues).

```bash
# Start a full rebuild
python scripts/rebuild_daemon.py start --db ~/.ck3raven/ck3raven.db

# Force restart (kills existing daemon)
python scripts/rebuild_daemon.py start --force

# Check status
python scripts/rebuild_daemon.py status

# View logs
python scripts/rebuild_daemon.py logs
python scripts/rebuild_daemon.py logs -f  # Follow mode

# Stop daemon
python scripts/rebuild_daemon.py stop
```

### Daemon Files

Located in `~/.ck3raven/daemon/`:

| File | Purpose |
|------|---------|
| `rebuild.pid` | Process ID for monitoring |
| `rebuild_status.json` | Current phase, progress, counts |
| `rebuild.log` | Full log output |
| `heartbeat` | Timestamp updated every 30s |

### Build Phases

1. **Ingest** - Scan vanilla + Steam Workshop mods, store files with content hashing
2. **AST Generation** - Parse .txt/.yml files into AST, skip non-script files (gfx/, etc.)
3. **Symbol Extraction** - Extract traits, decisions, events, etc. from ASTs
4. **Reference Extraction** - Extract references to symbols (has_trait, trigger_event, etc.)

---

## Current Limitations (Need Fixing)

### 🔴 Full Rebuild Only

**Problem:** The current system rebuilds EVERYTHING from scratch. If one mod updates with 10 files changed, all 200,000+ files are re-processed.

**Impact:** Rebuilds take hours instead of seconds.

### 🔴 No Staleness Detection

**Problem:** No way to detect which files changed since last build.

**Current state:** Files table has `deleted` flag but no `stale` or `needs_rebuild` tracking.

### 🔴 No Mod Version Tracking

**Problem:** No tracking of mod versions or update timestamps.

**Impact:** Can't tell if a mod was updated on Steam Workshop.

### 🔴 Schema Changes Cause Data Loss

**Problem:** Any schema change requires full rebuild with data loss.

**Ideal:** Schema migrations should preserve existing data.

---

## Roadmap: Incremental Rebuild System

### Core Principle: Filesystem Monitoring is Default

The builder should NOT scan all files on every run. Instead:

1. **Track mtime** (last modified timestamp) for every file in the database
2. **On rebuild**, only check files whose folder mtime changed
3. **Use filesystem events** (watchdog) for live editing scenarios

### Rebuild Modes

| Command | Behavior | When to Use |
|---------|----------|-------------|
| `rebuild` | Check mtime, rebuild only changed files | **Default** - after editing mods |
| `rebuild --rescan` | Scan all files, compare content_hash | After Steam Workshop updates, game patches |
| `rebuild --full` | Drop all data, rebuild from scratch | Schema changes, corrupted database |

### Phase 1: File-Level Staleness Detection

Track which files actually changed using **mtime** (filesystem last modified time):

```sql
-- Add to files table
ALTER TABLE files ADD COLUMN file_mtime INTEGER;  -- Unix timestamp from os.stat().st_mtime
ALTER TABLE files ADD COLUMN needs_ast_rebuild BOOLEAN DEFAULT 0;
ALTER TABLE files ADD COLUMN needs_symbol_rebuild BOOLEAN DEFAULT 0;

-- Add to mods table  
ALTER TABLE mods ADD COLUMN last_scanned_at INTEGER;
ALTER TABLE mods ADD COLUMN folder_mtime INTEGER;
```

**Default rebuild logic (mtime-based, fast):**
```python
for file_path in mod_folder.rglob("*"):
    disk_mtime = file_path.stat().st_mtime
    db_mtime = get_stored_mtime(file_path)
    
    if db_mtime is None:
        # New file - ingest and parse
        ingest_file(file_path)
    elif disk_mtime > db_mtime:
        # Changed file - re-ingest and mark for rebuild
        mark_needs_rebuild(file_path)
    # else: unchanged, skip entirely
```

**`--rescan` logic (content_hash based, thorough):**
```python
for file_path in mod_folder.rglob("*"):
    disk_hash = compute_sha256(file_path.read_bytes())
    db_hash = get_stored_hash(file_path)
    
    if disk_hash != db_hash:
        # Content actually changed
        update_content(file_path, disk_hash)
        mark_needs_rebuild(file_path)
```

### Phase 2: Cascading Invalidation

When a file changes, only rebuild what depends on it:

```
File changed → AST rebuild → Symbol extraction → Reference updates
                              ↓
                    Mark refs to old symbols as orphaned
                    Insert refs to new symbols
```

**Key insight:** If a file's content_hash is unchanged, skip ALL downstream processing.

### Phase 3: Mod-Level Tracking

```sql
-- Track Steam Workshop mod versions
CREATE TABLE mod_versions (
    mod_id TEXT PRIMARY KEY,
    steam_workshop_id TEXT,
    version_string TEXT,
    last_updated_at INTEGER,
    files_count INTEGER,
    needs_full_rescan BOOLEAN DEFAULT 0
);
```

**Detection methods:**
1. Check `.mod` file mtime
2. Parse version from `descriptor.mod`
3. (Future) Steam Workshop API for update timestamps

### Phase 4: Surgical Rebuild Commands

```bash
# Rebuild only changed files in a specific mod
python scripts/rebuild_daemon.py incremental --mod "MyMod"

# Rebuild only files that failed parsing last time
python scripts/rebuild_daemon.py retry-failed

# Rebuild AST/symbols for files matching pattern
python scripts/rebuild_daemon.py rebuild-path "common/traits/*.txt"

# Force rebuild of specific file
python scripts/rebuild_daemon.py rebuild-file "common/decisions/my_decision.txt"
```

### Phase 5: Watch Mode

Daemon monitors filesystem for changes and rebuilds in real-time:

```bash
python scripts/rebuild_daemon.py watch --mods "MSC,VanillaPatch"
```

**Components:**
1. `watchdog` library for filesystem events
2. Debounce (wait 2s after last change before rebuild)
3. Queue of changed files
4. Background thread processing queue

---

## Schema Changes and Migrations

### When Full Rebuild is Required

- New required columns without defaults
- Index strategy changes affecting dedup
- Parser version bump (AST format changed)
- Content hash algorithm change

### When Incremental Migration Works

- New nullable columns
- New tables
- New indexes on existing columns
- Adding constraints (may need validation pass)

### Migration Script Pattern

```python
# scripts/migrate_add_foo.py
def migrate(conn):
    # 1. Check if migration already applied
    if column_exists(conn, 'files', 'new_column'):
        return "Already migrated"
    
    # 2. Add column with safe default
    conn.execute("ALTER TABLE files ADD COLUMN new_column TEXT DEFAULT NULL")
    
    # 3. Backfill if needed (incremental, resumable)
    cursor = conn.execute("SELECT file_id FROM files WHERE new_column IS NULL LIMIT 1000")
    while rows := cursor.fetchall():
        for row in rows:
            # Compute value
            conn.execute("UPDATE files SET new_column = ? WHERE file_id = ?", (value, row[0]))
        conn.commit()
```

---

## Garbage Collection: Deleted File Cleanup

When files are deleted from source, we don't just mark them - we need to actually remove data.

### Cleanup Strategy

**Phase 1: Mark deleted** (during rescan)
```sql
-- Mark files that no longer exist on disk
UPDATE files SET deleted = 1 WHERE file_id IN (
    SELECT file_id FROM files WHERE mod_id = ? AND relpath NOT IN (?)
);
```

**Phase 2: Cascade delete derived data** (immediate)
```sql
-- Remove symbols extracted from deleted files
DELETE FROM symbols WHERE file_id IN (SELECT file_id FROM files WHERE deleted = 1);

-- Remove references from deleted files  
DELETE FROM refs WHERE file_id IN (SELECT file_id FROM files WHERE deleted = 1);
```

**Phase 3: Orphan content cleanup** (periodic, expensive)
```sql
-- Find content_hashes no longer referenced by any active file
DELETE FROM file_contents WHERE content_hash NOT IN (
    SELECT DISTINCT content_hash FROM files WHERE deleted = 0
);

-- Same for ASTs
DELETE FROM asts WHERE content_hash NOT IN (
    SELECT DISTINCT content_hash FROM files WHERE deleted = 0
);
```

### When Garbage Collection Runs

| Event | GC Action |
|-------|-----------|
| File deleted from source | Mark deleted + cascade delete symbols/refs |
| `rebuild --rescan` | Full orphan cleanup |
| `rebuild --full` | N/A (drops everything anyway) |
| Manual `gc` command | Full orphan cleanup on demand |

### Content Deduplication Consideration

Because content is deduplicated by `content_hash`, a file's content might be shared across mods:
- `mod_A/common/traits/foo.txt` and `mod_B/common/traits/foo.txt` may have same content_hash
- Deleting `mod_A/traits/foo.txt` should NOT delete the content if `mod_B` still uses it
- This is why orphan cleanup checks "no active files reference this hash"

---

## File Skip Patterns

Not all files in the game folders are CK3 scripts. The builder skips:

| Pattern | Reason |
|---------|--------|
| `gfx/` | Graphics data (meshes, textures, cameras) - NOT scripts |
| `/generated/` | Auto-generated content |
| `#backup/` | Editor backups |
| `/fonts/`, `/sounds/`, `/music/` | Assets, not scripts |
| `moreculturalnames` | Massive localization databases (50MB+) |
| `.dds`, `.png`, `.tga` | Binary image files |

**Legitimate CK3 script folders:**
- `common/` - Game mechanics
- `events/` - Event scripts
- `history/` - Character/title history
- `localization/` - Text strings (yml)
- `gui/` - UI definitions
- `decisions/` - Player decisions

---

## Performance Targets

| Operation | Current | Target |
|-----------|---------|--------|
| Full rebuild (vanilla + 648 mods) | 8+ hours | 2-3 hours |
| Incremental (10 files changed) | 8+ hours | 10 seconds |
| Single file rebuild | N/A | <1 second |
| Watch mode latency | N/A | <3 seconds |

---

## Implementation Priority

1. **HIGH:** File mtime tracking + staleness detection
2. **HIGH:** Incremental AST rebuild (skip unchanged content_hash)
3. **MEDIUM:** Mod version tracking  
4. **MEDIUM:** Surgical rebuild commands
5. **LOW:** Watch mode (nice-to-have)
6. **LOW:** Steam Workshop API integration

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - Overall system architecture
- [tools/ck3lens_mcp/docs/SETUP.md](../tools/ck3lens_mcp/docs/SETUP.md) - MCP server setup
- [.github/PROPOSED_TOOLS.md](../.github/PROPOSED_TOOLS.md) - Proposed MCP tools including `ck3_rebuild_index`
