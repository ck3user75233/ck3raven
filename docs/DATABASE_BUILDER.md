# Database Builder Architecture

## Overview

The ck3raven database stores parsed CK3 content for fast querying by the MCP tools. This document covers the build system, incremental updates, and the library functions that power intelligent rebuilds.

---

## Directory Structure

`
ck3raven/
 builder/                      # THE database builder (detached daemon)
    daemon.py                 # Main daemon script
    migrations/               # Schema migration scripts
        create_loc_tables.py
        init_conflict_tables.py
        migrate_add_staleness_columns.py
        migrate_contribution_lifecycle.py

 src/ck3raven/db/              # Database library functions (used by daemon)
    schema.py                 # Schema definition + SCHEMA_VERSION constant
    ingest.py                 # Directory/mod ingestion + incremental update
    work_detection.py         # Detect what work needs to be done
    skip_rules.py             # Centralized skip patterns for all phases
    symbols.py                # Symbol extraction logic
    references.py             # Reference extraction logic
    content.py                # File record/content storage helpers
    asts.py                   # AST generation logic
│    queries.py                # Read-only query helpers
    db_setup.py               # Connection helpers

 tests/                        # Test suite
    unit/                     # Unit tests (fast, isolated)
    integration/              # Integration tests (use real DB)
    fixtures/                 # Test data files

 scripts/                      # Utility scripts (NOT for building)
     convert_launcher_playset.py
     create_playset.py
     ingest_localization.py
     resolve_traditions.py
`

---

## Daemon Usage

The daemon runs completely detached from terminals (avoids Ctrl+C injection issues).

`ash
# Start a full rebuild
python builder/daemon.py start --db ~/.ck3raven/ck3raven.db

# Force restart (kills existing daemon)
python builder/daemon.py start --force

# Check status
python builder/daemon.py status

# View logs
python builder/daemon.py logs
python builder/daemon.py logs -f  # Follow mode

# Stop daemon
python builder/daemon.py stop
`

### Daemon Files

Located in `~/.ck3raven/daemon/`:

| File | Purpose |
|------|---------|
| `rebuild.pid` | Process ID for monitoring |
| `rebuild_status.json` | Current phase, progress, counts |
| `rebuild.log` | Full log output |
| `heartbeat` | Timestamp updated every 30s |

### Build Phases

The daemon processes files through distinct phases. File routing is determined at ingest time by `file_routes.py` which sets `file_type` on each file.

| Phase | Name | Description |
|-------|------|-------------|
| 1 | **Vanilla Ingest** | Scan vanilla game files, store content, tag with `file_type` |
| 2 | **Mod Ingest** | Scan all Steam Workshop + local mods, same tagging |
| 3 | **Parsing** | Multi-route based on `file_type`: |
|   | - script → | Parse to AST, store in `asts` table |
|   | - localization → | Parse to `localization_entries` table (TODO) |
|   | - reference → | Parse province/character IDs to ref tables (TODO) |
|   | - skip → | No parsing (images, binary, docs) |
| 4 | **Symbol Extraction** | Extract definitions (traits, events, decisions) from ASTs |
| 5 | **Reference Extraction** | Extract symbol USAGES from ASTs (enables dependency analysis) |
| 6 | **Done** | Build complete |

**File Routing**: The canonical file classification is in `src/ck3raven/db/file_routes.py`. This single file determines where each file goes. No scattered skip logic.

---

## Library Functions: Work Detection

The `src/ck3raven/db/work_detection.py` module contains functions that detect what work needs to be done **without performing it**. These enable intelligent, incremental rebuilds.

### Key Classes

| Class | Purpose |
|-------|---------|
| `WorkSummary` | Comprehensive summary of pending work across all phases |
| `SlowParseInfo` | Information about slow parses (statistical outliers) |
| `RebuildRecommendation` | Result of full rebuild checks with severity levels |

### Key Functions

| Function | Purpose |
|----------|---------|
| `get_files_needing_ingest()` | Compare filesystem to DB, returns (new, deleted, changed) files |
| `get_files_needing_ast()` | Files with content but no AST |
| `get_files_with_failed_ast()` | Files that failed parsing |
| `get_asts_needing_symbols()` | ASTs without extracted symbols |
| `get_orphan_counts()` | Count orphaned entries needing cleanup |
| `get_slow_parses()` | Identify statistical outliers in parse times |
| `should_full_rebuild()` | Check if full rebuild warranted (**NEVER auto-approves**) |
| `get_build_status()` | Main function - comprehensive work summary |

### Full Rebuild Detection

The `should_full_rebuild()` function **NEVER auto-approves** a full rebuild. It returns a `RebuildRecommendation` dataclass with:

- `requires_user_approval` - Always True
- `severity` - 'required' | 'recommended' | 'optional'
- `reason` - Human-readable explanation
- `details` - Dict with specifics (e.g., schema versions)

**Why?** Full rebuilds take hours and destroy existing data. The user must explicitly confirm.

**Schema detection:** Compares `SCHEMA_VERSION` constant (in code) against `db_metadata.schema_version` (in DB).

---

## Library Functions: Skip Rules

The `src/ck3raven/db/skip_rules.py` module provides **centralized skip patterns** for all processing phases.

### Skip Categories

| Category | Pattern Examples | Reason |
|----------|------------------|--------|
| `NEVER_PARSE` | gfx/, fonts/, sounds/, #backup/ | Not CK3 scripts |
| `USE_LOCALIZATION_PARSER` | localization/*.yml | Different parser |
| `SKIP_SYMBOL_EXTRACTION` | names/, coat_of_arms/, gui/ | No meaningful symbols |
| `SKIP_REF_EXTRACTION` | history/ | Historical data, not refs |

### Key Functions

| Function | Returns |
|----------|---------|
| `should_skip_ast(relpath)` | bool - Skip AST generation |
| `should_skip_symbols(relpath)` | bool - Skip symbol extraction |
| `should_skip_refs(relpath)` | bool - Skip reference extraction |
| `is_localization_file(relpath)` | bool - Use localization parser |
| `get_ast_eligible_sql_condition()` | SQL WHERE clause for AST-eligible files |
| `get_symbol_eligible_sql_condition()` | SQL WHERE clause for symbol-eligible files |

### Why Centralized?

- **Single source of truth** - All phases use the same logic
- **Consistency** - No divergence between daemon and library
- **Testability** - Easy to test and verify patterns
- **Documentation** - Patterns explained inline with rationale

---

## Symbol Extraction Return Values

The `extract_symbols_for_file()` function in `symbols.py` returns a dict with clear terminology:

`python
{
    'symbols_extracted': 15,   # Total symbols found in AST
    'symbols_inserted': 3,     # Actually inserted (new to DB)
    'duplicates': 12,          # Ignored (INSERT OR IGNORE - already exist)
    'files_skipped': 0         # Files skipped due to skip rules
}
`

**Note:** `duplicates` are expected! Due to content-addressing (files share content by hash), the same symbols may be extracted multiple times. `INSERT OR IGNORE` correctly deduplicates them.

---

## Incremental Update Strategy

### Core Principle: Don't Rebuild What Hasn't Changed

The builder tracks changes at multiple levels:

1. **File level** - mtime for fast filtering, content_hash for definitive change detection
2. **AST level** - Keyed by `content_hash` (content-addressable, deduped across mods)
3. **Symbol level** - Keyed by `file_id` (needs mod/version context for conflicts)

### Why Different Keys?

| Data Type | Primary Key | Reason |
|-----------|-------------|--------|
| `file_contents` | `content_hash` | Same content = same bytes, dedup across mods |
| `asts` | `(content_hash, parser_version)` | Same content parsed by same parser = same AST |
| `symbols` | `symbol_id`, indexed by `defining_file_id` | Same trait in mod A vs mod B has different conflict/priority context |
| `refs` | `ref_id`, indexed by `file_id` | References need file context |

### Incremental Update Process (`incremental_update()` in `ingest.py`)

When a mod is updated (e.g., Steam Workshop update):

1. **Fast mtime scan** - Compare stored `files.mtime` vs filesystem mtime
2. **Hash check for changed** - Only read files where mtime differs, compute hash
3. **Categorize** - Files are `added`, `removed`, `changed`, or `unchanged`
4. **Clean up replaced/removed files**:
   - Delete `symbols` (keyed by file_id)
   - Delete `refs` (keyed by file_id)
   - Delete `asts` (by content_hash, only if no other files reference it)
   - Delete `file_contents` (by content_hash, only if orphaned)
5. **Store new content** - Insert new file_contents and file records with mtime
6. **Clear extraction timestamps** - Set `symbols_extracted_at=NULL` on content_version
7. **Daemon routing** - Existing daemon file routing regenerates ASTs/symbols

> **Note on `is_stale` column**: The `content_versions.is_stale` column is **deprecated** and 
> scheduled for removal. Change detection happens at the **file level** via `files.mtime`, not
> via this flag. The column is always set to 1 and not used for decisions.

### Key Implementation Details

- **First run after mtime fix**: All files will be hash-checked (stored mtime was NULL)
- **Subsequent runs**: Only files with changed mtime are read
- **Content deduplication**: ASTs and file_contents are only deleted if no other files reference them
- **Daemon handles regeneration**: By clearing `symbols_extracted_at`, the daemon's normal file routing kicks in

### Rebuild Modes

| Mode | Behavior | When to Use |
|------|----------|-------------|
| Default | Check mtime, only read changed files | Normal operation, Steam updates |
| `--rescan` | Scan all files, compare content_hash | Force check everything |
| `--full` | Drop all data, rebuild from scratch | Schema changes, corrupted DB |

### When Full Rebuild is Required

- `SCHEMA_VERSION` changed in code
- Parser version changed
- User explicitly requests `--force`

### When Full Rebuild is NOT Required

- New nullable columns (add via migration)
- New tables (add via migration)
- New indexes (add via migration)
- Mod added or removed (incremental)

---

## Migration Scripts

Migrations live in `builder/migrations/` and follow this pattern:

`python
def migrate(conn):
    # 1. Check if migration already applied
    if column_exists(conn, 'files', 'new_column'):
        return "Already migrated"

    # 2. Add column with safe default
    conn.execute("ALTER TABLE files ADD COLUMN new_column TEXT DEFAULT NULL")

    # 3. Backfill if needed (incremental, resumable)
    # ...

    conn.commit()
    return "Migration complete"
`

---

## Performance Targets

| Operation | Current | Target |
|-----------|---------|--------|
| Full rebuild (vanilla + 648 mods) | ~4 hours | 2-3 hours |
| Incremental (10 files changed) | N/A | 10 seconds |
| Single file rebuild | N/A | <1 second |
| Watch mode latency | N/A | <3 seconds |

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - Overall system architecture
- [tools/ck3lens_mcp/docs/SETUP.md](../tools/ck3lens_mcp/docs/SETUP.md) - MCP server setup
