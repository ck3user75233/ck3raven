# ck3raven Architecture

> **Last Updated:** December 20, 2025

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
│   └── ck3lens-explorer/         # VS Code Extension
│       ├── src/
│       │   ├── extension.ts      # Entry point, command registration
│       │   ├── session.ts        # CK3LensSession lifecycle
│       │   ├── bridge/           # Python JSON-RPC bridge
│       │   ├── linting/          # Real-time validation
│       │   │   ├── lintingProvider.ts   # Full Python validation
│       │   │   └── quickValidator.ts    # Quick TS validation
│       │   ├── views/            # UI panels
│       │   │   ├── explorerView.ts      # Database-driven tree
│       │   │   ├── astViewerPanel.ts    # AST viewer webview
│       │   │   └── studioPanel.ts       # File creation studio
│       │   └── widget/           # Floating widget
│       └── bridge/
│           └── server.py         # Python JSON-RPC server
│
├── builder/                      # Detached build daemon
│   ├── daemon.py                 # Main daemon with 7-phase pipeline
│   ├── config.py                 # Configuration and paths
│   └── debug/                    # Debug infrastructure
│       ├── session.py            # DebugSession class with span/emit
│       └── __init__.py
│
├── scripts/                      # Utility scripts
│   ├── hooks/                    # Git hooks (install with install-hooks.py)
│   │   └── pre-commit            # Policy enforcement hook
│   ├── install-hooks.py          # Hook installer
│   └── pre-commit-policy-check.py  # Policy validation logic
│
├── docs/                         # Design documentation
├── tests/                        # Pytest suite
└── scripts/                      # Utility scripts
```

---

## Core Modules

### Builder Daemon (`builder/`)

**Purpose:** Detached background process that builds the database.

| File | Description |
|------|-------------|
| `daemon.py` | 7-phase pipeline: ingest → parse → symbols → refs → localization → lookups |
| `config.py` | Paths, vanilla detection, config loading |
| `debug/session.py` | `DebugSession` class for phase-agnostic instrumentation |

**Phases:**
1. **Vanilla Ingest** - Discover and store vanilla CK3 files
2. **Mod Ingest** - Discover and store mod files (active playset)
3. **AST Generation** - Parse files into ASTs
4. **Symbol Extraction** - Extract trait, event, decision definitions
5. **Ref Extraction** - Extract symbol references
6. **Localization Parsing** - Parse YML localization files
7. **Lookup Tables** - Build trait_lookups, event_lookups, decision_lookups

**Debug Mode:**
```bash
python builder/daemon.py start --debug all --debug-limit 10
```

Outputs:
- `~/.ck3raven/daemon/debug_trace.jsonl` - JSONL event stream
- `~/.ck3raven/daemon/debug_summary.json` - Aggregated stats per phase

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
| **Playset** | `ck3_get_active_playset`, `ck3_add_mod_to_playset`, `ck3_import_playset_from_launcher`, `ck3_reorder_mod_in_playset` | Manage mod collections |
| **Conflicts** | `ck3_scan_unit_conflicts`, `ck3_list_conflict_units` | Unit-level conflict analysis |
| **Live Ops** | `ck3_write_file`, `ck3_edit_file` | Sandboxed file modifications |
| **Git** | `ck3_git_status`, `ck3_git_commit` | Version control for live mods |

#### Playset Import from Launcher

The `ck3_import_playset_from_launcher` tool enables importing playsets directly from
CK3 Launcher's exported JSON files:

```python
# Import a playset from launcher export
result = ck3_import_playset_from_launcher(
    launcher_json_path="C:/path/to/MSC_Playset.json",
    local_mod_paths=["C:/Users/.../mod/LocalMod"],  # Optional local mods
    set_active=True
)
# Returns: { playset_id: 2, mods_linked: 102, mods_skipped: [...] }
```

**Workflow:**
1. Export playset from Paradox Launcher (Settings → Export Playset)
2. Call `ck3_import_playset_from_launcher` with the JSON path
3. Tool matches Steam IDs to indexed mods and creates playset
4. Optionally adds local mods at end of load order

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

## Policy Enforcement

### Overview

Policy enforcement ensures AI agents follow defined rules during development.
The system uses a git pre-commit hook as the primary enforcement mechanism.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Agent Tool Calls                                 │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ Traced to JSONL
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ck3lens_trace.jsonl (~/Documents/Paradox Interactive/CK3/mod/)            │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ Read by hook
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  .git/hooks/pre-commit → scripts/pre-commit-policy-check.py                │
│  ├─ Reads trace log                                                        │
│  ├─ Calls validate_for_mode("ck3raven-dev", trace)                        │
│  ├─ Exit 0 if passed → commit allowed                                      │
│  └─ Exit 1 if failed → commit blocked                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Installing Hooks

After cloning the repository:

```bash
python scripts/install-hooks.py
```

This copies `scripts/hooks/pre-commit` to `.git/hooks/pre-commit`.

### Policy Files

| File | Description |
|------|-------------|
| `tools/ck3lens_mcp/ck3lens/policy/agent_policy.yaml` | Policy definitions |
| `tools/ck3lens_mcp/ck3lens/policy/validator.py` | `validate_for_mode()` function |
| `tools/ck3lens_mcp/ck3lens/policy/ck3raven_dev_rules.py` | Rules for dev mode |
| `tools/ck3lens_mcp/ck3lens/policy/ck3lens_rules.py` | Rules for modding mode |

### Emergency Bypass

```bash
git commit --no-verify  # Use sparingly, document why
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
