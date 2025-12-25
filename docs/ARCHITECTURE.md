# ck3raven Architecture

> **Last Updated:** December 25, 2025

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
│  │ (DB read)     │  │ (unit-level)   │  │ (filesystem)│  │  (live mods) │  │
│  └───────┬───────┘  └───────┬────────┘  └──────┬──────┘  └──────┬───────┘  │
└──────────┼──────────────────┼──────────────────┼────────────────┼──────────┘
           │                  │                  │                │
           │ READ             │ READ             │ WRITE          │ WRITE
           ▼                  ▼                  ▼                ▼
┌──────────────────────────────────────┐  ┌───────────────────────────────────┐
│      ck3raven SQLite Database        │  │         Configuration             │
│  ┌─────────────┐  ┌────────────────┐ │  │  ┌─────────────┐  ┌────────────┐ │
│  │ files       │  │ symbols        │ │  │  │ playsets/   │  │ live mods  │ │
│  │ file_conten │  │ refs           │ │  │  │ (JSON)      │  │ (files)    │ │
│  │ asts        │  │ lookups        │ │  │  └─────────────┘  └────────────┘ │
│  └─────────────┘  └────────────────┘ │  └───────────────────────────────────┘
│         ▲                            │
│         │ WRITE (only)               │
│         │                            │
└─────────┼────────────────────────────┘
          │
┌─────────┴───────────────────────────────────────────────────────────────────┐
│                           Builder Daemon                                    │
│  Reads: vanilla game, mods, playset JSON                                    │
│  Writes: database only                                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

> **Status:** Current structure shown with planned changes marked [PLANNED]

```
ck3raven/
│
├── src/ck3raven/                 # SHARED LIBRARIES (importable by all consumers)
│   │
│   ├── parser/                   # Text → AST transformation
│   │   ├── lexer.py              # 100% regex-free tokenizer
│   │   └── parser.py             # Recursive descent → RootNode, BlockNode, etc.
│   │
│   ├── resolver/                 # Conflict resolution logic
│   │   ├── policies.py           # 4 merge policies (OVERRIDE, CONTAINER_MERGE, etc.)
│   │   ├── sql_resolver.py       # File-level and symbol-level resolution
│   │   ├── contributions.py      # Data contracts (ContributionUnit, ConflictUnit)
│   │   ├── conflict_analyzer.py  # Unit extraction, grouping, risk scoring
│   │   └── manager.py            # ContributionsManager lifecycle
│   │
│   ├── db/                       # Database schema + READ operations
│   │   ├── schema.py             # All table definitions (CREATE TABLE statements)
│   │   ├── models.py             # Dataclass models for type safety
│   │   ├── connection.py         # Connection management, retries, locking
│   │   ├── queries/              # READ operations [PLANNED - currently flat]
│   │   │   ├── symbols.py        # Symbol search, adjacency matching
│   │   │   ├── files.py          # File content retrieval
│   │   │   ├── conflicts.py      # Conflict queries
│   │   │   └── lookups.py        # Lookup table queries
│   │   ├── search.py             # FTS5 full-text search
│   │   ├── lens.py               # Runtime playset filter (reads JSON, filters queries)
│   │   └── cryo.py               # Snapshot export/import
│   │
│   ├── logs/                     # CK3 log parsing [PARTIAL]
│   │   ├── error_parser.py       # Parse error.log
│   │   └── crash_parser.py       # Parse crash folders
│   │
│   ├── emulator/                 # Game state building [FUTURE]
│   │
│   └── cli.py                    # Command-line interface
│
├── builder/                      # BUILD PIPELINE (WRITE operations)
│   │
│   ├── daemon.py                 # Build orchestration, phase runner
│   ├── config.py                 # Paths, vanilla detection, settings
│   ├── file_router.py            # Route files to pipelines [PLANNED]
│   │
│   ├── debug/                    # Debug infrastructure
│   │   ├── __init__.py
│   │   └── session.py            # DebugSession with span/emit pattern
│   │
│   ├── extractors/               # Populate database [PLANNED - currently in daemon.py]
│   │   ├── __init__.py
│   │   ├── ingest.py             # File discovery and storage
│   │   ├── ast.py                # Parse files → AST blobs
│   │   ├── symbols.py            # AST → symbol definitions
│   │   ├── refs.py               # AST → symbol references
│   │   ├── localization.py       # YAML → localization_entries
│   │   │
│   │   └── lookups/              # Data files → lookup tables [PLANNED]
│   │       ├── __init__.py
│   │       ├── province.py       # definition.csv + history/provinces/
│   │       ├── character.py      # history/characters/
│   │       ├── dynasty.py        # common/dynasties/
│   │       ├── holy_site.py      # common/religion/holy_sites/
│   │       ├── name_list.py      # common/culture/name_lists/
│   │       └── culture.py        # common/culture/cultures/
│   │
│   └── modes/                    # Build strategies [PLANNED]
│       ├── full.py               # Complete rebuild
│       ├── incremental.py        # Only changed files
│       └── partial.py            # Specific phases only
│
├── tools/                        # CONSUMER APPLICATIONS
│   │
│   ├── ck3lens_mcp/              # MCP Server for AI Agents
│   │   ├── server.py             # FastMCP with 30+ tools
│   │   ├── ck3lens/
│   │   │   ├── workspace.py      # Live mod whitelist
│   │   │   └── db_queries.py     # Query layer for tools
│   │   └── docs/
│   │       ├── SETUP.md
│   │       ├── TOOLS.md
│   │       └── DESIGN.md
│   │
│   └── ck3lens-explorer/         # VS Code Extension
│       ├── src/
│       │   ├── extension.ts      # Entry point, activation
│       │   ├── session.ts        # Python bridge lifecycle
│       │   ├── bridge/           # JSON-RPC communication
│       │   ├── linting/          # Real-time validation
│       │   ├── views/            # UI panels (explorer, AST viewer, studio)
│       │   └── widget/           # Floating mode widget
│       └── bridge/
│           └── server.py         # Python JSON-RPC server
│
├── scripts/                      # Utility scripts
│   ├── hooks/                    # Git hooks
│   │   └── pre-commit            # Policy enforcement
│   ├── install-hooks.py          # Hook installer
│   ├── pre-commit-policy-check.py
│   └── sample_db.py              # Database sampling for review
│
├── docs/                         # Documentation
│   ├── ARCHITECTURE.md           # This file
│   ├── COPILOT_RAVEN_DEV.md      # AI agent rules
│   └── *.md                      # Design documents
│
└── tests/                        # Pytest suite
    ├── test_parser.py
    ├── test_resolver.py
    ├── test_builder_daemon.py
    └── ...
```

### Architectural Boundaries

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CONSUMERS                                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │ MCP Server      │  │ VS Code Ext     │  │ CLI             │              │
│  │ (tools/)        │  │ (tools/)        │  │ (src/)          │              │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘              │
└───────────┼────────────────────┼────────────────────┼────────────────────────┘
            │                    │                    │
            │ READ               │ READ               │ READ
            ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SHARED LIBRARIES (src/ck3raven/)                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │ db/             │  │ parser/         │  │ resolver/       │              │
│  │ (schema+query)  │  │ (text→AST)      │  │ (conflicts)     │              │
│  └────────┬────────┘  └─────────────────┘  └─────────────────┘              │
└───────────┼─────────────────────────────────────────────────────────────────┘
            │
            │ SCHEMA
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SQLite Database                                 │
│                         (~/.ck3raven/ck3raven.db)                           │
└───────────▲─────────────────────────────────────────────────────────────────┘
            │
            │ WRITE
            │
┌───────────┴─────────────────────────────────────────────────────────────────┐
│                           BUILDER (builder/)                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │ daemon.py       │  │ file_router.py  │  │ extractors/     │              │
│  │ (orchestration) │  │ (routing)       │  │ (population)    │              │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Separation of Concerns

| Layer | Location | Responsibility | Database | Config |
|-------|----------|----------------|----------|--------|
| **Consumers** | `tools/`, CLI | User-facing applications | READ | READ/WRITE |
| **Shared Libraries** | `src/ck3raven/` | Schema, queries, parsing | READ | READ |
| **Builder** | `builder/` | Database population | WRITE | READ |
| **Database** | `~/.ck3raven/db` | Indexed content | - | - |
| **Config** | `~/.ck3raven/playsets/` | Playset definitions | - | - |

### Key Principles

**1. The builder is the ONLY component that writes to the database.**

- `src/ck3raven/db/` defines schema and provides READ queries
- `builder/extractors/` populates tables using that schema
- Consumers (MCP, VS Code, CLI) only READ through `src/ck3raven/db/`

**2. Playsets are configuration, not content.**

- Stored as JSON files in `~/.ck3raven/playsets/`
- Managed by MCP server and CLI (not in database)
- Applied as runtime filter to database queries

**3. Agent file edits flow through builder.**

- Agent writes to filesystem (live mod directories)
- Builder refreshes changed files into database
- No direct database writes from consumers

---

## Core Modules

### Builder Daemon (`builder/`)

**Purpose:** Detached background process that builds the database.

| File | Description |
|------|-------------|
| `daemon.py` | Multi-phase pipeline with file routing |
| `config.py` | Paths, vanilla detection, config loading |
| `debug/session.py` | `DebugSession` class for phase-agnostic instrumentation |

**Current Phases (7):**
1. **Vanilla Ingest** - Discover and store vanilla CK3 files
2. **Mod Ingest** - Discover and store mod files (active playset)
3. **AST Generation** - Parse files into ASTs
4. **Symbol Extraction** - Extract trait, event, decision definitions
5. **Ref Extraction** - Extract symbol references
6. **Localization Parsing** - Parse YML localization files
7. **Lookup Tables** - ~~trait_lookups, event_lookups, decision_lookups~~ (to be replaced)

**Debug Mode:**
```bash
python builder/daemon.py start --debug all --debug-limit 10
```

Outputs:
- `~/.ck3raven/daemon/debug_trace.jsonl` - JSONL event stream
- `~/.ck3raven/daemon/debug_summary.json` - Aggregated stats per phase

---

## File Routing

> **Last Updated:** December 25, 2025

Different CK3 file types serve different purposes and require different processing pipelines.
Files are routed based on their path patterns to the appropriate processing pipeline.

### Routing Decision Tree

```
File Discovered
     │
     ├─ Is it graphics/generated? ──────────────→ SKIP (no output)
     │     (gfx/, ethnicities/, dna_data/, coat_of_arms/, *.dds, *.png)
     │
     ├─ Is it localization YAML? ───────────────→ YAML Parser → localization_entries
     │     (localization/**/*.yml)
     │
     ├─ Is it ID-keyed data? ───────────────────→ Lookup Extractor → lookup tables
     │     (history/provinces, history/characters, dynasties, name_lists, holy_sites, definition.csv)
     │
     └─ Is it script with logic? ───────────────→ AST → Symbols → Refs
           (events, scripted_*, on_action, decisions, traits, buildings, etc.)
```

### Complete Routing Table

| Folder / Pattern | Pipeline | Output Tables | Status |
|-----------------|----------|---------------|--------|
| **DATA FILES → LOOKUP ONLY** ||||
| `map_data/definition.csv` | CSV Parser → Lookup | `province_lookup` | 🔴 NOT BUILT |
| `history/provinces/*.txt` | Lookup Extractor | `province_lookup` | 🔴 NOT BUILT |
| `history/characters/*.txt` | Lookup Extractor | `character_lookup` | 🔴 NOT BUILT |
| `common/dynasties/*.txt` | Lookup Extractor | `dynasty_lookup` | 🔴 NOT BUILT |
| `common/culture/name_lists/*.txt` | Lookup Extractor | `name_list_lookup` | 🔴 NOT BUILT |
| `common/religion/holy_sites/*.txt` | Lookup Extractor | `holy_site_lookup` | 🔴 NOT BUILT |
| `common/culture/cultures/*.txt` | AST + Lookup | AST, symbols, refs, `culture_lookup` | 🟡 AST only |
| **LOCALIZATION → SPECIALIZED** ||||
| `localization/**/*.yml` | YAML Parser | `localization_entries` | 🟢 BUILT |
| **SCRIPT FILES → AST + SYMBOLS + REFS** ||||
| `events/**/*.txt` | AST → Symbols → Refs | `asts`, `symbols`, `refs` | 🟢 BUILT |
| `common/scripted_effects/*.txt` | AST → Symbols → Refs | `asts`, `symbols`, `refs` | 🟢 BUILT |
| `common/scripted_triggers/*.txt` | AST → Symbols → Refs | `asts`, `symbols`, `refs` | 🟢 BUILT |
| `common/on_action/*.txt` | AST → Symbols → Refs | `asts`, `symbols`, `refs` | 🟢 BUILT |
| `common/decisions/*.txt` | AST → Symbols → Refs | `asts`, `symbols`, `refs` | 🟢 BUILT |
| `common/traits/*.txt` | AST → Symbols → Refs | `asts`, `symbols`, `refs` | 🟢 BUILT |
| `common/buildings/*.txt` | AST → Symbols → Refs | `asts`, `symbols`, `refs` | 🟢 BUILT |
| `common/government/*.txt` | AST → Symbols → Refs | `asts`, `symbols`, `refs` | 🟢 BUILT |
| `common/laws/*.txt` | AST → Symbols → Refs | `asts`, `symbols`, `refs` | 🟢 BUILT |
| `common/religion/religions/*.txt` | AST → Symbols → Refs | `asts`, `symbols`, `refs` | 🟢 BUILT |
| `common/landed_titles/*.txt` | AST → Symbols → Refs | `asts`, `symbols`, `refs` | 🟢 BUILT |
| `history/titles/*.txt` | AST → Symbols → Refs | `asts`, `symbols`, `refs` | 🟢 BUILT |
| **SKIP ENTIRELY** ||||
| `gfx/**/*` | Skip | None | N/A |
| `common/ethnicities/**` | Skip | None | N/A |
| `common/dna_data/**` | Skip | None | N/A |
| `common/coat_of_arms/**` | Skip | None | N/A |
| `map_data/*.png` | Skip | None | N/A |

### Why Lookup vs AST?

**Lookup tables** are for **ID-keyed data** where:
- You encounter an opaque ID (e.g., `capital = 2333`, `dynasty = 1687`)
- You need to resolve it to a name/definition
- The data has minimal logic (no triggers/effects)
- Query pattern is: "What is ID X?" or "Find all with property Y"

**AST + Symbols + Refs** are for **logic-heavy files** where:
- Content contains triggers, effects, conditions, modifiers
- You need to understand code flow and dependencies
- Query pattern is: "Where is X used?" or "What does X do?"

### Lookup Tables Schema (Planned)

#### `province_lookup` 🔴 NOT BUILT
```sql
CREATE TABLE province_lookup (
    province_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,                    -- From definition.csv
    rgb_r INTEGER, rgb_g INTEGER, rgb_b INTEGER,
    culture TEXT,                          -- From history/provinces (at latest date)
    religion TEXT,
    holding_type TEXT,
    terrain TEXT,
    content_version_id INTEGER             -- Source mod
);
```

#### `character_lookup` 🔴 NOT BUILT
```sql
CREATE TABLE character_lookup (
    character_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    dynasty_id INTEGER,
    dynasty_house TEXT,
    culture TEXT,
    religion TEXT,
    birth_date TEXT,
    death_date TEXT,
    father_id INTEGER,
    mother_id INTEGER,
    traits_json TEXT,                      -- JSON array of trait names
    content_version_id INTEGER
);
```

#### `dynasty_lookup` 🔴 NOT BUILT
```sql
CREATE TABLE dynasty_lookup (
    dynasty_id INTEGER PRIMARY KEY,
    name_key TEXT NOT NULL,                -- e.g., "dynn_Orsini"
    prefix TEXT,                           -- e.g., "dynnp_de"
    culture TEXT,
    motto TEXT,
    content_version_id INTEGER
);
```

#### `holy_site_lookup` 🔴 NOT BUILT
```sql
CREATE TABLE holy_site_lookup (
    holy_site_key TEXT PRIMARY KEY,        -- e.g., "jerusalem"
    county_key TEXT NOT NULL,              -- e.g., "c_jerusalem"
    province_id INTEGER,
    faith_key TEXT,                        -- Owning faith
    flag TEXT,
    content_version_id INTEGER
);
```

#### `name_list_lookup` 🔴 NOT BUILT
```sql
CREATE TABLE name_list_lookup (
    name_list_key TEXT PRIMARY KEY,        -- e.g., "name_list_french"
    male_names_json TEXT,                  -- JSON array
    female_names_json TEXT,
    dynasty_names_json TEXT,
    content_version_id INTEGER
);
```

#### `culture_lookup` 🔴 NOT BUILT
```sql
CREATE TABLE culture_lookup (
    culture_key TEXT PRIMARY KEY,          -- e.g., "french"
    heritage TEXT,                         -- e.g., "heritage_frankish"
    ethos TEXT,                            -- e.g., "ethos_bellicose"
    language TEXT,
    martial_custom TEXT,
    name_list_key TEXT,
    traditions_json TEXT,                  -- JSON array
    parents_json TEXT,                     -- JSON array of parent cultures
    content_version_id INTEGER
);
```

### Tables to DELETE (Wrong Approach)

These tables were incorrectly implemented - they denormalize AST data that's already
searchable via symbols:

| Table | Reason for Deletion |
|-------|---------------------|
| `trait_lookups` | Traits are string-keyed, use symbols + AST |
| `event_lookups` | Events are string-keyed, use symbols + AST |
| `decision_lookups` | Decisions are string-keyed, use symbols + AST |

### Builder Daemon Updates Required

#### Phase Changes

| Current | Planned | Notes |
|---------|---------|-------|
| Phase 7: "Lookup Tables" | Phase 7: "Lookup Extraction" | Complete rewrite |
| - trait_lookups | REMOVE | |
| - event_lookups | REMOVE | |
| - decision_lookups | REMOVE | |
| | ADD: province_lookup | From definition.csv + history/provinces/ |
| | ADD: character_lookup | From history/characters/ |
| | ADD: dynasty_lookup | From common/dynasties/ |
| | ADD: holy_site_lookup | From common/religion/holy_sites/ |
| | ADD: name_list_lookup | From common/culture/name_lists/ |
| | ADD: culture_lookup | From common/culture/cultures/ |

#### New Files Required

| File | Purpose |
|------|---------|
| `src/ck3raven/db/lookups_v2.py` | New lookup extractors for all 8 tables |
| `src/ck3raven/db/csv_parser.py` | Parse map_data/definition.csv |
| `builder/file_router.py` | Centralized routing logic |

#### File Router Implementation

```python
# builder/file_router.py (PLANNED)

class FileRoute(Enum):
    SKIP = "skip"
    AST_PIPELINE = "ast"              # → asts, symbols, refs
    LOCALIZATION = "localization"      # → localization_entries
    LOOKUP_PROVINCE = "lookup_province"
    LOOKUP_CHARACTER = "lookup_character"
    LOOKUP_DYNASTY = "lookup_dynasty"
    LOOKUP_HOLY_SITE = "lookup_holy_site"
    LOOKUP_NAME_LIST = "lookup_name_list"
    LOOKUP_CULTURE = "lookup_culture"

def route_file(relpath: str) -> FileRoute:
    """Determine processing pipeline for a file."""
    
    # Skip patterns (graphics, generated, DNA)
    skip_patterns = [
        'gfx/', 'common/ethnicities/', 'common/dna_data/',
        'common/coat_of_arms/', '.dds', '.png', '.tga'
    ]
    if any(p in relpath.lower() for p in skip_patterns):
        return FileRoute.SKIP
    
    # Localization
    if relpath.startswith('localization/') and relpath.endswith('.yml'):
        return FileRoute.LOCALIZATION
    
    # Province lookups
    if relpath == 'map_data/definition.csv':
        return FileRoute.LOOKUP_PROVINCE
    if relpath.startswith('history/provinces/'):
        return FileRoute.LOOKUP_PROVINCE
    
    # Character lookups
    if relpath.startswith('history/characters/'):
        return FileRoute.LOOKUP_CHARACTER
    
    # Dynasty lookups
    if relpath.startswith('common/dynasties/'):
        return FileRoute.LOOKUP_DYNASTY
    
    # Holy site lookups
    if relpath.startswith('common/religion/holy_sites/'):
        return FileRoute.LOOKUP_HOLY_SITE
    
    # Name list lookups (skip AST)
    if relpath.startswith('common/culture/name_lists/'):
        return FileRoute.LOOKUP_NAME_LIST
    
    # Culture lookups (ALSO goes to AST for symbol extraction)
    if relpath.startswith('common/culture/cultures/'):
        return FileRoute.LOOKUP_CULTURE  # Special: AST + lookup
    
    # Default: AST pipeline for script files
    if relpath.endswith('.txt'):
        return FileRoute.AST_PIPELINE
    
    return FileRoute.SKIP
```

#### Daemon Phase Updates

```python
# In builder/daemon.py (PLANNED CHANGES)

def run_rebuild(...):
    # Existing phases
    phase_1_vanilla_ingest(...)
    phase_2_mod_ingest(...)
    phase_3_ast_generation(...)      # Only for FileRoute.AST_PIPELINE files
    phase_4_symbol_extraction(...)
    phase_5_ref_extraction(...)
    phase_6_localization(...)        # Only for FileRoute.LOCALIZATION files
    
    # NEW Phase 7: Lookup Extraction
    phase_7_lookup_extraction(...)   # For all LOOKUP_* routes
    
def phase_7_lookup_extraction(conn, logger, status):
    """Extract lookup tables from data files."""
    from ck3raven.db.lookups_v2 import (
        extract_province_lookups,
        extract_character_lookups,
        extract_dynasty_lookups,
        extract_holy_site_lookups,
        extract_name_list_lookups,
        extract_culture_lookups,
    )
    
    # Each extractor reads from files table and writes to lookup table
    extract_province_lookups(conn, logger, status)      # definition.csv + history/provinces/
    extract_character_lookups(conn, logger, status)     # history/characters/
    extract_dynasty_lookups(conn, logger, status)       # common/dynasties/
    extract_holy_site_lookups(conn, logger, status)     # common/religion/holy_sites/
    extract_name_list_lookups(conn, logger, status)     # common/culture/name_lists/
    extract_culture_lookups(conn, logger, status)       # common/culture/cultures/
```

---

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

---

### Playset Configuration (`playsets/`)

**Purpose:** Define which mods to include and in what order. Playsets are configuration files, NOT database content.

> **Note:** As of December 2025, playsets are stored as JSON files in the `playsets/` folder.
> The database tables `playsets` and `playset_mods` are deprecated.

#### Storage Structure

```
ck3raven/
├── ck3raven.db              # Indexed content ONLY (no playset config)
└── playsets/
    ├── playset.schema.json       # JSON Schema for validation
    ├── example_playset.json      # Template to copy
    ├── sub_agent_templates.json  # Sub-agent briefing templates
    └── MSC.json                  # User playset (created by user)
```

#### Playset JSON Schema

```json
{
  "name": "MSC",
  "description": "Mini Super Compatch testing playset",
  "created_at": "2025-12-25T10:00:00Z",
  "mods": [
    {"name": "EPE", "steam_id": "2216659254", "enabled": true, "load_order": 1},
    {"name": "CFP", "steam_id": "2216670956", "enabled": true, "load_order": 2},
    {"name": "MSC", "path": "C:/Users/.../mod/MSC", "enabled": true, "load_order": 3}
  ],
  "live_mods": ["MSC", "LocalizationPatch", "CrashFixes"],
  "agent_briefing": {
    "context": "Developing MSC compatibility patch",
    "error_analysis_notes": [
      "Errors from Morven's compatch target mods are expected",
      "Focus on steady-play errors, not loading errors"
    ],
    "conflict_resolution_notes": [
      "Morven's compatch handles the 8 mods before it",
      "Don't duplicate conflict resolution Morven already does"
    ],
    "priorities": ["1. Crashes", "2. Gameplay bugs", "3. Visual issues"]
  },
  "sub_agent_config": {
    "error_analysis": {"enabled": true, "auto_spawn_threshold": 50}
  }
}
```

#### Key Fields

| Field | Description |
|-------|-------------|
| `name` | Playset identifier (used in MCP tools) |
| `mods` | Ordered list of mods with load order |
| `live_mods` | Mods the agent can write to (whitelist) |
| `agent_briefing` | Context notes for sub-agents |
| `sub_agent_config` | Auto-spawn settings for sub-agents |

#### Runtime Filter Pattern

Playset is applied as a runtime filter to any database query:

```python
def _get_session_scope() -> dict:
    """Read active playset JSON, return session scope."""
    # Find .json files in playsets/
    playset_dir = Path("playsets/")
    playset_files = list(playset_dir.glob("*.json"))
    
    if not playset_files:
        return {"playset_name": None, "mods": [], "live_mods": []}
    
    # Use first playset found (or implement active selection)
    playset = json.loads(playset_files[0].read_text())
    return {
        "playset_name": playset["name"],
        "mods": [m["name"] for m in playset["mods"] if m.get("enabled", True)],
        "live_mods": playset.get("live_mods", []),
        "agent_briefing": playset.get("agent_briefing", {})
    }
```

#### MCP Tools for Playset Management

| Tool | Purpose |
|------|---------|
| `ck3_list_playsets()` | List all playset JSON files |
| `ck3_get_active_playset()` | Get current playset configuration |
| `ck3_switch_playset(name)` | Switch to a different playset |
| `ck3_get_agent_briefing()` | Get briefing notes for sub-agents |

#### Importing from CK3 Launcher

```bash
python scripts/launcher_to_playset.py "My Playset Export.json" -o playsets/MyPlayset.json
```

See [playsets/README.md](../playsets/README.md) for full documentation.

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
| `mod_packages` | Known mods with source paths |
| `content_versions` | Mod versions linking to mod_packages |
| `contribution_units` | Unit-level contributions |
| `conflict_units` | Grouped conflicts with risk scores |
| `resolution_choices` | User conflict decisions |

> **Note:** `playsets` and `playset_mods` tables are deprecated. Playsets are now JSON config files.

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

#### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            AI Agent (Copilot)                               │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ MCP Protocol
┌───────────────────────────────────▼─────────────────────────────────────────┐
│                         CK3 Lens MCP Server                                 │
│  ┌───────────────┐  ┌────────────────┐  ┌─────────────┐  ┌──────────────┐  │
│  │ Query Tools   │  │ Conflict Tools │  │ Write Tools │  │ Policy Layer │  │
│  │ (DB read)     │  │ (unit-level)   │  │ (sandboxed) │  │ (validation) │  │
│  └───────────────┘  └────────────────┘  └─────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Tool Categories (~30 tools)

| Category | Tools | Purpose |
|----------|-------|---------|
| **Session** | `ck3_init_session`, `ck3_get_workspace_config` | Initialize and configure |
| **Search** | `ck3_search`, `ck3_confirm_not_exists` | Find symbols with adjacency matching |
| **Files** | `ck3_get_file`, `ck3_list_live_files`, `ck3_list_dir` | Read content from database |
| **Playset** | `ck3_list_playsets`, `ck3_get_active_playset`, `ck3_switch_playset`, `ck3_get_agent_briefing` | Manage playset JSON files |
| **Conflicts** | `ck3_scan_unit_conflicts`, `ck3_list_conflict_units`, `ck3_get_symbol_conflicts` | Unit-level conflict analysis |
| **Live Ops** | `ck3_write_file`, `ck3_edit_file`, `ck3_create_override_patch` | Sandboxed file modifications |
| **Git** | `ck3_git_status`, `ck3_git_commit`, `ck3_git_push` | Version control for live mods |
| **Validation** | `ck3_validate_syntax`, `ck3_validate_python`, `ck3_validate_policy` | Pre-write validation |
| **Logs** | `ck3_parse_error_log`, `ck3_get_crash_report` | Error analysis |
| **Database** | `ck3_get_db_status`, `ck3_db_delete`, `ck3_refresh_file` | Database management |

#### Agent Modes

The server supports two modes with different capabilities:

| Mode | Purpose | Allowed Operations |
|------|---------|-------------------|
| `ck3lens` | CK3 modding | Search, read, write CK3 files in live mods |
| `ck3raven-dev` | Infrastructure | All operations including Python editing |

Mode is determined by the work context and enforced by policy rules.

#### Adjacency Search

Automatic pattern expansion for fuzzy matching:
- `brave` → also matches `trait_brave`, `is_brave`, `brave_modifier`
- Modes: `strict`, `auto`, `fuzzy`

#### Work Contracts (CLW)

For privileged operations, agents use HMAC-signed work contracts:

```python
# Request a contract token
token = ck3_request_token(
    scope="edit_python",
    reason="Fix parsing bug in lexer.py",
    files=["src/ck3raven/parser/lexer.py"]
)

# Execute with token
result = ck3_exec(token, operation="edit", ...)
```

See [TOOLS.md](../tools/ck3lens_mcp/docs/TOOLS.md) for complete tool reference.

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
| `ck3lens` | CK3 modding with database search and live mod editing |
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

### Update Detection System (Implemented)
- Detect when vanilla/mod source directories have changed via **file-level mtime comparison**
- Trigger automatic re-ingestion when mtime differs from stored value
- Re-extract symbols for changed files  
- Uses `files.mtime` column for per-file change detection

> **Deprecation note:** The `content_versions.is_stale` and `content_versions.source_mtime` 
> columns are deprecated and not used. Change detection happens at file level, not content_version level.

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

### Map Mod Conversion Agent (Phase 5)
- Specialized agent mode for compatching total conversion map mods (MB+, TFE, etc.)
- Build mapping indices: vanilla↔map_mod for titles, regions, holy sites
- Auto-mapping with confidence scoring (EXACT, HIGH, MEDIUM, LOW, UNMAPPED)
- Apply conversions across gameplay mods to generate comaptches
- See [08_MAP_MOD_CONVERSION_AGENT.md](08_MAP_MOD_CONVERSION_AGENT.md) for full design

---

## VS Code Extension (`tools/ck3lens-explorer/`)

The CK3 Lens Explorer extension provides an IDE-like experience for CK3 mod development.

### Architecture

```
VS Code Extension (TypeScript)
        │
        │ JSON-RPC (stdio)
        ▼
Python Bridge Server (bridge/server.py)
        │
        ▼
ck3raven Library (parser, database, resolver)
```

### Components

| Component | File | Description |
|-----------|------|-------------|
| Entry Point | `extension.ts` | Activation, command registration |
| Session | `session.ts` | Python bridge lifecycle |
| Quick Validator | `linting/quickValidator.ts` | Instant TS-based syntax checks |
| Linting Provider | `linting/lintingProvider.ts` | Full Python parser validation |
| Explorer View | `views/explorerView.ts` | Database-driven file tree |
| Playset View | `views/playsetView.ts` | Load order with drag-and-drop reordering |
| AST Viewer | `views/astViewerPanel.ts` | File content + AST webview |
| Studio Panel | `views/studioPanel.ts` | Template-based file creation |
| Widget | `widget/lensWidget.ts` | Mode switching, status overlay |

### Playset Management

The playset view shows mods in the active playset with load order position.
Users can reorder mods using **drag-and-drop** to change load priority:

- **Drag a mod** → Drop on another mod to insert before it
- **Drop on header** → Move to first position (after vanilla)
- Changes are persisted to the database immediately

Setup workflows are accessible from the playset view title bar:
- **+ Add mods** → Add mods to playset
- **Switch playset** → View all playsets and switch active

### Validation Pipeline

```
User types → Quick TS validator (~10ms) → Show blocking errors
           ↓ (300ms debounce)
           Full Python parse (~200ms) → Complete diagnostics
           ↓
           Status bar updated (errors/warnings/valid)
```

### Templates (Studio Panel)

11 templates for common CK3 content types:
- Events, Decisions, Traits
- Character Interactions
- Cultures, Traditions, Buildings
- Court Positions
- Scripted Effects/Triggers, On-Actions

See `tools/ck3lens-explorer/DESIGN.md` for full design documentation.

---

### Compatch Helper (Phase 4)

#### Error/Conflict Explorer

Unified view showing both **parse errors** (from error.log) and **load-order conflicts** (from database):

```
┌────────────────────────────────────────────────────────────────┐
│ CK3 Lens: Issues                                         [⟳] │
├────────────────────────────────────────────────────────────────┤
│ Filter: [Priority ▾] [Mod ▾] [Status ▾]    🔍 search          │
├────────────────────────────────────────────────────────────────┤
│ ▼ CRITICAL (2)                                                 │
│   🔴 Script parse error in events/ww_events.txt:45            │
│      Mod: World Wonders | [Navigate] [Create Patch ▾]         │
│   🔴 Missing trait 'brave_custom' in decisions/knight.txt:12  │
│      Mod: Knight Overhaul | [Navigate] [Create Patch ▾]       │
│                                                                │
│ ▼ HIGH RISK CONFLICTS (5)                                     │
│   ⚠️ on_action:yearly_ruler_pulse (4 mods)                    │
│      EPE, CFP, RICE, Vanilla | [Compare] [Create Patch ▾]     │
│                                                                │
│ ▼ MEDIUM (12)  ▼ LOW (45)                                      │
└────────────────────────────────────────────────────────────────┘
```

#### One-Click Navigation Flow

1. **Click error/conflict** → Opens source file at exact line
2. Real-time linting shows red squiggly + reference validation
3. Status bar shows file provenance (which mod, load order position)

#### Override Patch Creation

When error is in **vanilla or non-live mod**, user can create an override patch:

**"Create Patch" Dropdown Options:**

| Option | File Created | Use Case |
|--------|--------------|----------|
| **Add Override Patch** | `zzz_msc_[original_name].txt` | Add/modify specific units while preserving others |
| **Replace Entire File** | `[original_name].txt` | Full replacement, last-wins |

**Target Mod Selection:**
- Dropdown shows all live mods (editable mods in whitelist)
- Default: "Mini Super Compatch" or last-used mod
- Creates correct directory structure automatically

**Example:**
```
Error in: common/traits/00_traits.txt (Vanilla)
User clicks: Create Patch → Add Override Patch → MSC

Creates: MSC/common/traits/zzz_msc_00_traits.txt
         (containing only the specific trait being fixed)
```

#### AI-Assisted Merge Modes (Future)

| Mode | Description |
|------|-------------|
| **Merge All** | AI merges all mods touching this file, reports unplaceable conflicts |
| **Merge Subset** | User selects which mods to merge, others get overwritten |
| **Re-Assert Original** | Original (vanilla/origin mod) wins, all override mods ignored |

**Provenance Tracking:**
- Every AI merge records which versions were merged
- Undo capability via git history on live mods

#### MCP Tools for Agent Support

| Tool | Agent Use |
|------|-----------|
| `ck3_get_errors(priority=2, mod_filter="MyMod")` | Focus on high-priority issues in specific mod |
| `ck3_list_conflict_units(risk_filter="high")` | See high-risk conflicts needing compatch |
| `ck3_get_conflict_detail(id)` | Get full content of all candidates |
| `ck3_create_override_patch(path, target_mod, mode)` | Create override file in correct location |


---

## Validation Tool Architecture

### Overview

ck3raven has a layered validation architecture with distinct purposes:

```
                    
                           Agent / User Request          
                    -
                                     
        
                                                                
                                                                
    
   quickValidator       validate.py          semantic.py     
   (TypeScript)         (Python)             (Python)        
   ~10ms                ~200ms               ~50ms lookup    
-    -
                                                     
                                                     
    SYNTAX SCAN            FULL PARSE            SEMANTIC CHECK
    - Brace balance        - AST generation      - Trigger exists?
    - Unterminated ""      - Block structure     - Effect exists?
    - Basic structure      - All syntax errors   - Scope valid?
                                                 - Fuzzy suggest
```

### Components

| Layer | File | Purpose | Performance |
|-------|------|---------|-------------|
| **Quick Scan** | `quickValidator.ts` | Immediate feedback while typing | ~10ms |
| **Full Parse** | `validate.py` | Complete AST with all errors | ~200ms |
| **Semantic** | `semantic.py` (TODO) | Validate names exist in vanilla | ~50ms |

### Current State

1. **quickValidator.ts** -  Implemented
   - Located: `tools/ck3lens-explorer/src/linting/quickValidator.ts`
   - Fast client-side checks for blocking errors

2. **validate.py** -  Implemented  
   - Located: `tools/ck3lens_mcp/ck3lens/validate.py`
   - Uses ck3raven parser for full AST generation
   - Called via Python bridge from VS Code extension

3. **semantic.py** -  To Be Consolidated
   - Currently exists as `AI Workspace/ck3_syntax_validator.py` (standalone)
   - Validates trigger/effect names against vanilla database
   - Provides fuzzy matching for typo suggestions
   - **PLAN: Move into ck3raven as `tools/ck3lens_mcp/ck3lens/semantic.py`**

### Consolidation Plan

#### Phase 1: Move ck3_syntax_validator.py into ck3raven

**From:** `AI Workspace/ck3_syntax_validator.py`
**To:** `ck3raven/tools/ck3lens_mcp/ck3lens/semantic.py`

Changes required:
- Rename class to `SemanticValidator`
- Update imports to use ck3raven modules
- Add MCP tool wrappers (`validate_trigger`, `suggest_similar`)

#### Phase 2: Integrate with symbols.py vs refdb.py

**Key Question:** Two tools do similar things:

| Tool | Output | Used By |
|------|--------|---------|
| `db/symbols.py` | SQLite (`symbols`, `refs` tables) | ck3lens database, MCP queries |
| `tools/refdb.py` | JSON (`refdb.json`) | Standalone CLI, offline analysis |

**Resolution:**
- `symbols.py` is the **canonical implementation** (database-backed, incremental)
- `refdb.py` is a **convenience CLI** that can export to JSON for offline use
- **No code duplication** - refdb.py should import from symbols.py

#### Phase 3: Versioned Vanilla Database

**Problem:** Current databases have `game_version: "CK3 (extracted from vanilla)"` - no specific version.

**Solution:**
1. Extract CK3 version from game files at build time
2. Store as `ck3_version: "1.14.0"` in database metadata
3. Create versioned exports: `vanilla_syntax_1.14.0.json`
4. When CK3 updates: freeze old version, create new version file

**Version Detection:**
```python
# From launcher-settings.json or game files
version_file = game_path / "launcher" / "launcher-settings.json"
# Or parse from game binary/version file
```

### Database Files (Canonical Locations)

| File | Location | Purpose | Keep? |
|------|----------|---------|-------|
| `ck3lens.db` | `ck3raven/data/` | Full SQLite database |  Canonical |
| `ck3_syntax_db.json` | `AI Workspace/` | Trigger/effect lookup |  Keep for now |
| `refdb.json` | Generated | Cross-reference export |  Regenerate as needed |

### Tools to Archive/Remove

These are superseded by ck3raven equivalents:

| File | Status | Replacement |
|------|--------|-------------|
| `ck3_parser_ARCHIVED/` |  Archived | `ck3raven/src/ck3raven/parser/` |
| `build_ck3_syntax_db.py` | Move to ck3raven | Integrate with ingest.py |
| `ck3_syntax_validator.py` | Move to ck3raven | `ck3lens/semantic.py` |
| `validator/` folder | Review | May merge useful parts |

---

## Policy Enforcement & CLI Wrapping Layer (CLW)

### Overview

The CLI Wrapping Layer (CLW) provides comprehensive policy enforcement for AI agents,
ensuring they follow defined rules during development. The system enforces rules at
multiple levels: tool call tracing, pre-commit hooks, CI gates, and runtime validation.

### Agent Modes

| Mode | Purpose | File Restrictions |
|------|---------|-------------------|
| `ck3lens` | CK3 modding work | Can ONLY edit CK3 files (.txt, .gui, .gfx, .yml) in live mods |
| `ck3raven-dev` | Infrastructure development | Can edit Python, YAML, JSON in allowed paths |

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Agent Tool Calls                                 │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ 1. Pre-validation (path restrictions)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Policy Rules Engine (ck3lens_rules.py, ck3raven_dev_rules.py)             │
│  ├─ enforce_ck3lens_file_restrictions() - blocks Python from ck3lens       │
│  ├─ validate_path_policy() - checks allowed paths                          │
│  └─ validate_artifact_bundle() - validates output structure                │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ 2. Tool execution
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ck3lens_trace.jsonl (logged tool calls)                                   │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ 3. Pre-commit validation
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Pre-commit Hooks                                                          │
│  ├─ .pre-commit-config.yaml - hook configuration                           │
│  ├─ scripts/code-diff-guard.py - pattern detection                         │
│  └─ scripts/pre-commit-policy-check.py - policy validation                 │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ 4. CI gate
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  GitHub Actions (.github/workflows/ck3raven-ci.yml)                        │
│  ├─ Runs pre-commit hooks on push/PR                                       │
│  └─ Blocks merge on violations                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Validation Rules

Rules are defined in `ck3lens_config.yaml` and enforced at multiple stages:

| Rule | Mode | Severity | Purpose |
|------|------|----------|---------|
| `allowed_python_paths` | ck3lens | ERROR | Blocks Python/infrastructure editing |
| `scripts_must_be_documented` | ck3raven-dev | ERROR | Prevents orphan scripts |
| `ephemeral_scripts_location` | ck3raven-dev | ERROR | Forces temp scripts to .artifacts/ |
| `bugfix_requires_core_change` | ck3raven-dev | ERROR | No workaround scripts |
| `bugfix_requires_test` | ck3raven-dev | ERROR | Tests required for fixes |
| `architecture_intent_required` | ck3raven-dev | ERROR | Document rationale |
| `python_validation_required` | ck3raven-dev | ERROR | Syntax validation before commit |
| `schema_change_declaration` | ck3raven-dev | WARNING | Declare breaking changes |
| `preserve_uncertainty` | ck3raven-dev | WARNING | Document unknowns |

### File Restrictions (ck3lens mode)

When in `ck3lens` mode, agents can ONLY edit CK3 modding files:

**Allowed extensions:**
```
.txt, .gui, .gfx, .yml, .dds, .png, .tga, .shader, .fxh
```

**Forbidden paths (always blocked):**
```
src/, builder/, tools/ck3lens_mcp/ck3lens/, scripts/,
tests/, .github/, .vscode/, ck3lens_config.yaml,
pyproject.toml, *.py
```

### Policy Files

| File | Description |
|------|-------------|
| `ck3lens_config.yaml` | Main configuration with validation_rules section |
| `tools/ck3lens_mcp/ck3lens/policy/agent_policy.yaml` | Policy specifications (VS Code reads this) |
| `tools/ck3lens_mcp/ck3lens/policy/ck3lens_rules.py` | CK3 modding rules implementation |
| `tools/ck3lens_mcp/ck3lens/policy/ck3raven_dev_rules.py` | Infrastructure rules implementation |
| `docs/NO_DUPLICATE_IMPLEMENTATIONS.md` | Duplicate prevention policy |
| `docs/CLW_DECISIONS.md` | Implementation decisions record |

### Pre-commit Hooks

Install hooks after cloning:

```bash
pip install pre-commit
pre-commit install
```

Or manually:
```bash
python scripts/install-hooks.py
```

### Emergency Bypass

```bash
git commit --no-verify  # Use sparingly, document why in commit message
```

---

## Debug Infrastructure

### DebugSession (`builder/debug/`)

Phase-agnostic instrumentation for the daemon pipeline.

**Design Principles:**
1. **Observe, don't re-implement** - Hooks into real phases, not separate logic
2. **Phase-agnostic** - Phases call `debug.emit()`/`debug.span()`, session handles output
3. **Data-driven** - Collect timings, row deltas, sizes uniformly
4. **Non-invasive** - No phase-specific logic in debug layer

**Usage:**

```python
from builder.debug import DebugSession

with DebugSession.from_config(output_dir, sample_limit=100) as debug:
    debug.phase_start("parse")
    
    for file in files:
        with debug.span("file", phase="parse", path=file.path) as s:
            ast = parse(file.content)
            s.add(output_bytes=len(ast), output_count=node_count)
    
    debug.phase_end("parse")
```

**Output:**
- `debug_trace.jsonl` - JSONL event stream (machine-readable)
- `debug_summary.json` - Aggregated stats per phase

**CLI:**
```bash
python builder/daemon.py start --debug all --debug-limit 100
```
