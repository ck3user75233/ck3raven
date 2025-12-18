# ck3raven Architecture

> **Last Updated:** December 18, 2025

## Overview

ck3raven is a CK3 game state emulator that answers: *"What does the game actually see?"*

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            AI Agent (Copilot)                               │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ MCP Protocol
┌───────────────────────────────────▼─────────────────────────────────────────┐
│                         CK3 Lens MCP Server                                 │
│  ┌───────────────┐  ┌────────────────┐  ┌─────────────┐  ┌──────────────┐  │
│  │ Query Tools   │  │ Conflict Tools │  │ Write Tools │  │  Git Tools   │  │
│  │ (DB read)     │  │ (unit-level)   │  │ (sandbox)   │  │  (live mods) │  │
│  └───────┬───────┘  └───────┬────────┘  └──────┬──────┘  └──────┬───────┘  │
└──────────┼──────────────────┼──────────────────┼────────────────┼──────────┘
           │                  │                  │                │
┌──────────▼──────────────────▼──────────────────┼────────────────┼──────────┐
│                     ck3raven SQLite Database                    │          │
│  ┌─────────────┐  ┌────────────────┐  ┌───────────────────┐    │          │
│  │ files       │  │ symbols        │  │ contribution_units│    │          │
│  │ file_conten │  │ refs           │  │ conflict_units    │    │          │
│  │ asts        │  │ playsets       │  │ resolution_choice │    │          │
│  └─────────────┘  └────────────────┘  └───────────────────┘    │          │
└────────────────────────────────────────────────────────────────┼──────────┘
                                                                 │
┌────────────────────────────────────────────────────────────────▼──────────┐
│                           Live Mod Directories                             │
│  ┌─────────────┐  ┌───────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ MSC         │  │ MSCRE         │  │ LRE          │  │ MRP           │  │
│  └─────────────┘  └───────────────┘  └──────────────┘  └───────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
ck3raven/
├── src/ck3raven/
│   ├── parser/                   # Lexer + Parser → AST
│   │   ├── lexer.py              # 100% regex-free tokenizer
│   │   └── parser.py             # AST nodes: RootNode, BlockNode, etc.
│   │
│   ├── resolver/                 # Conflict Resolution Layer
│   │   ├── policies.py           # 4 merge policies + content type configs
│   │   ├── sql_resolver.py       # File-level and symbol-level resolution
│   │   ├── contributions.py      # Data contracts (ContributionUnit, ConflictUnit)
│   │   └── conflict_analyzer.py  # Unit-level conflict extraction and grouping
│   │
│   ├── db/                       # Database Storage Layer
│   │   ├── schema.py             # SQLite schema (20+ tables)
│   │   ├── models.py             # Dataclass models
│   │   ├── content.py            # Content-addressed storage (SHA256)
│   │   ├── ingest.py             # Vanilla/mod ingestion
│   │   ├── ast_cache.py          # AST cache by (content_hash, parser_version)
│   │   ├── symbols.py            # Symbol/reference extraction
│   │   ├── search.py             # FTS5 search
│   │   ├── playsets.py           # Playset management
│   │   └── cryo.py               # Snapshot export/import
│   │
│   ├── emulator/                 # (Future) Full game state building
│   └── cli.py                    # Command-line interface
│
├── tools/
│   ├── ck3lens_mcp/              # MCP Server for AI Agents
│   │   ├── server.py             # FastMCP with 28+ tools
│   │   ├── ck3lens/
│   │   │   ├── workspace.py      # Live mod whitelist
│   │   │   └── db_queries.py     # Query layer: symbols, files, content, conflicts
│   │   └── docs/
│   │       ├── SETUP.md
│   │       ├── TOOLS.md
│   │       ├── TESTING.md
│   │       └── DESIGN.md
│   │
│   └── ck3lens-explorer/         # VS Code Extension (WIP)
│
├── docs/                         # Design documentation
├── tests/                        # Pytest suite
└── scripts/                      # Utility scripts
```

---

## Core Modules

### Parser (`src/ck3raven/parser/`)

**Purpose:** Convert CK3 script text into structured AST.

| File | Description |
|------|-------------|
| `lexer.py` | Character-by-character tokenizer (100% regex-free) |
| `parser.py` | Recursive descent parser producing AST nodes |

**AST Node Types:**
- `RootNode` - Top-level container
- `BlockNode` - Named block with children `{ ... }`
- `AssignmentNode` - Key-value assignment `key = value`
- `ValueNode` - Scalar value (string, number, boolean)
- `ListNode` - List of values

**Key Features:**
- 100% vanilla parse rate
- 99.8% mod parse rate
- Handles edge cases: `29%`, `-$PARAM$`, `<=`, BOM, single quotes

---

### Resolver (`src/ck3raven/resolver/`)

**Purpose:** Determine what wins when multiple sources define the same content.

| File | Description |
|------|-------------|
| `policies.py` | Merge policy definitions and content type configs |
| `sql_resolver.py` | SQL-based file and symbol resolution |
| `contributions.py` | Data contracts for unit-level conflicts |
| `conflict_analyzer.py` | Unit extraction, grouping, risk scoring |

#### Merge Policies

| Policy | Behavior | Used By |
|--------|----------|---------|
| `OVERRIDE` | Last definition wins completely | ~95% of content |
| `CONTAINER_MERGE` | Container merges, sublists append | on_actions only |
| `PER_KEY_OVERRIDE` | Each key independent | localization, defines |
| `FIOS` | First definition wins | GUI types/templates |

#### Resolution Levels

1. **File-level:** Same `relpath` → last mod wins (file replaced entirely)
2. **Symbol-level:** Same symbol name → last mod wins (LIOS)
3. **Unit-level:** Same `unit_key` → grouped into `ConflictUnit` for analysis

---

### Conflict Analyzer (`src/ck3raven/resolver/conflict_analyzer.py`)

**Purpose:** Extract and group conflicts at the semantic unit level.

**Key Concepts:**

| Concept | Description |
|---------|-------------|
| **Unit Key** | Stable identifier like `on_action:on_yearly_pulse` or `trait:brave` |
| **ContributionUnit** | What one source provides for a unit_key |
| **ConflictUnit** | Multiple ContributionUnits competing for same unit_key |
| **Resolution** | User's decision on how to resolve a conflict |

**Risk Scoring (0-100):**

| Factor | Points |
|--------|--------|
| Base by domain | on_action: 30, events: 25, gui: 25, defines: 15 |
| Extra candidates | +10 per candidate beyond 2 |
| Unknown merge semantics | +20 |
| Vanilla overwritten | +5 |
| Unknown references | +15 |

---

### Contributions Manager (`src/ck3raven/resolver/manager.py`)

**Purpose:** Lifecycle-aware management of contribution and conflict data.

The `ContributionsManager` is the primary interface for conflict analysis. It:
- Tracks when contribution data is stale (playset composition changed)
- Automatically refreshes data when needed
- Provides query methods for conflicts with auto-refresh

#### Contribution Lifecycle

```
┌──────────────────────────────────────────────────────────────────────┐
│                      CONTRIBUTION LIFECYCLE                           │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  1. Playset Created/Modified                                          │
│     ├─ add_mod_to_playset() ─────────┐                               │
│     ├─ remove_mod_from_playset() ────┼──→ contributions_stale = 1    │
│     ├─ set_mod_enabled() ────────────┤                               │
│     └─ reorder_mods() ───────────────┘                               │
│                                                                       │
│  2. Data Refresh (automatic or manual)                                │
│     ├─ ContributionsManager.refresh(playset_id)                       │
│     ├─ or auto_refresh=True on any query                              │
│     └─ Triggers:                                                      │
│        ├─ extract_contributions_for_playset()                        │
│        ├─ group_contributions_for_playset()                          │
│        └─ mark_contributions_current()                                │
│                                                                       │
│  3. Query (always checks staleness)                                   │
│     ├─ manager.get_summary(playset_id)                                │
│     ├─ manager.list_conflicts(playset_id)                             │
│     └─ manager.get_conflict_detail(conflict_id)                       │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

#### Staleness Tracking

The `playsets` table tracks contribution state:

| Column | Purpose |
|--------|---------|
| `contributions_stale` | 1 = needs rescan, 0 = up to date |
| `contributions_hash` | Hash of load order for cache validation |
| `contributions_scanned_at` | When last scanned |

When any playset operation changes composition or order, `contributions_stale` is set to 1.
When `ContributionsManager.refresh()` completes successfully, it's set back to 0.

---

### Database (`src/ck3raven/db/`)

**Purpose:** Store all parsed content with full deduplication and versioning.

#### Key Tables

| Table | Purpose |
|-------|---------|
| `file_contents` | Content-addressed storage (SHA256 dedup) |
| `files` | File records linking content to versions |
| `asts` | Cached ASTs by (content_hash, parser_version) |
| `symbols` | Extracted symbol definitions |
| `refs` | Symbol references |
| `playsets` | User-defined mod collections |
| `playset_mods` | Mod membership with load order |
| `contribution_units` | Unit-level contributions |
| `conflict_units` | Grouped conflicts with risk scores |
| `resolution_choices` | User conflict decisions |

#### Content-Addressed Storage

Same content appearing in multiple mods is stored once:
```
SHA256(content) → content_hash → stored once in file_contents
```

#### AST Caching

ASTs are cached by (content_hash, parser_version):
- Same file = same AST
- Parser upgrade = re-parse needed

---

### MCP Server (`tools/ck3lens_mcp/`)

**Purpose:** Expose ck3raven capabilities to AI agents via Model Context Protocol.

#### Tool Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| **Session** | `ck3_init_session` | Initialize database connection |
| **Search** | `ck3_search_symbols`, `ck3_confirm_not_exists` | Find symbols with adjacency matching |
| **Files** | `ck3_get_file`, `ck3_list_live_files` | Read content from database |
| **Playset** | `ck3_get_active_playset`, `ck3_add_mod_to_playset` | Manage mod collections |
| **Conflicts** | `ck3_scan_unit_conflicts`, `ck3_list_conflict_units` | Unit-level conflict analysis |
| **Live Ops** | `ck3_write_file`, `ck3_edit_file` | Sandboxed file modifications |
| **Git** | `ck3_git_status`, `ck3_git_commit` | Version control for live mods |

#### Adjacency Search

Automatic pattern expansion for fuzzy matching:
- `brave` → also matches `trait_brave`, `is_brave`, `brave_modifier`
- Modes: `strict`, `auto`, `fuzzy`

---

## Data Flow

### Ingestion

```
Mod Files → Parser → AST → Database
                           ├── file_contents (deduplicated)
                           ├── files (linked to content_version)
                           ├── asts (cached by hash)
                           └── symbols (extracted from AST)
```

### Conflict Analysis

```
Database → ContributionUnits → ConflictUnits → Risk Scores
              ↓                      ↓              ↓
        (per-file,            (grouped by      (0-100, with
         per-block)            unit_key)        reasons)
```

### Resolution

```
ConflictUnit → User Decision → ResolutionChoice → Patch Generation
                   ↓                 ↓
              (winner or        (stored in
               custom merge)     database)
```

---

## Agent Integration

### Tool Sets (VS Code)

| Tool Set | Description |
|----------|-------------|
| `ck3lens` | Database-only tools for compatching |
| `ck3lens-live` | Full modding including file editing and git |
| `ck3raven-dev` | All tools for infrastructure development |

### Critical Rules for Agents

1. **Database-only:** All searches go through MCP tools, not filesystem
2. **No regex:** Use adjacency search and SQL patterns
3. **Validate before writing:** Always use `ck3_parse_content` first
4. **Commit changes:** Use git tools to track modifications

---

## Database Statistics (Typical)

| Table | Count | Size |
|-------|-------|------|
| mod_packages | ~100 | - |
| content_versions | ~110 | - |
| file_contents | ~80,000 | ~26 GB |
| files | ~85,000 | - |
| symbols | ~1,200,000 | - |
| asts | ~70,000 | ~500 MB |

---

## Key Design Decisions

1. **No file I/O in analysis:** All content is pre-ingested into SQLite
2. **Content-addressed storage:** SHA256 deduplication saves 60%+ space
3. **Parser versioning:** AST cache invalidated on parser changes
4. **Unit-level conflicts:** Semantic grouping rather than just file/symbol level
5. **Risk scoring:** Prioritize high-impact conflicts for review
6. **Sandboxed writes:** Only whitelisted mods can be modified

---

## Future Work

### Update Detection System (Pending)
- Detect when vanilla/mod source directories have changed (mtime comparison)
- Mark content_versions as stale when source files are modified
- Trigger automatic re-ingestion and re-extraction
- Uses `source_mtime` and `is_stale` columns in content_versions table

### Change Logging System (Pending)
- Track when mods/vanilla are updated with detailed summaries
- Record per-file changes with block-level diffs
- Uses `change_log` and `file_changes` tables (schema ready)
- Provides navigable/searchable change history

### Log Parsing Module
- Parse CK3's error.log into structured error data
- Categorize errors by type and priority
- Detect cascading error patterns
- Parse crash folders for exception details
- Located in `src/ck3raven/logs/`

### Emulator (Phase 2)
- Full game state building from resolved content
- Provenance tracking per definition
- Export resolved files with annotations

### Explorer UI (Phase 3)
- VS Code sidebar with tree views
- Syntax ⇄ AST toggle
- Provenance timeline

### Compatch Helper (Phase 4)
- Decision card UI
- Guided merge editor
- AI-assisted conflict resolution
