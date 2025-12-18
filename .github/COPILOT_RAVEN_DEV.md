# CK3 Raven Development Mode - AI Agent Instructions

> **Mode:** `ck3raven-dev`  
> **Purpose:** Core infrastructure development for the CK3 game state emulator  
> **Last Updated:** December 18, 2025

---

## Quick Identity Check

**Am I in the right mode?**
- ✅ You're writing Python code for ck3raven internals
- ✅ You're modifying database schema, parsers, resolvers
- ✅ You're building the emulator, MCP tools, or CLI
- ✅ You're fixing infrastructure bugs
- ❌ If you're editing CK3 mod files (.txt, .yml) → Switch to `ck3lens` mode

---

## Project Overview

**ck3raven** is a Python toolkit that answers: *"What does the game actually see?"*

Given a playset (vanilla + mods in load order), it:
1. **Parses** CK3 script files into AST (100% regex-free)
2. **Resolves** conflicts using accurate merge rules
3. **Stores** everything in a deduplicated SQLite database
4. **Analyzes** unit-level conflicts with risk scoring
5. **Emulates** the final game state with full provenance tracking

---

## Current Status (December 2025)

| Module | Status | Description |
|--------|--------|-------------|
| `parser/` | ✅ Complete | 100% regex-free, 100% vanilla parse rate |
| `resolver/` | ✅ Complete | 4 merge policies, file/symbol/unit-level resolution |
| `db/` | ✅ Complete | SQLite with content-addressed storage, FTS5 search |
| `tools/ck3lens_mcp/` | ✅ Phase 1.5 | 25+ MCP tools including conflict analyzer |
| `emulator/` | 🔲 Stubs | Full game state building (Phase 2) |
| CLI | 🔲 Minimal | Basic structure only |

### Database Status

| Table | Count | Notes |
|-------|-------|-------|
| mod_packages | ~105 | ✅ All mods indexed |
| content_versions | ~110 | ✅ |
| file_contents | ~80,000 | ✅ 26 GB deduplicated |
| files | ~85,000 | ✅ |
| symbols | ~1,200,000 | ✅ Extracted |
| playsets | 1 | ✅ Active playset configured |

---

## Architecture

```
ck3raven/
├── src/ck3raven/
│   ├── parser/               # Lexer + Parser → AST
│   │   ├── lexer.py          # 100% regex-free tokenizer
│   │   └── parser.py         # AST nodes: RootNode, BlockNode, etc.
│   │
│   ├── resolver/             # Conflict Resolution Layer
│   │   ├── policies.py           # 4 merge policies + content type configs
│   │   ├── sql_resolver.py       # File-level and symbol-level resolution
│   │   ├── contributions.py      # Data contracts (ContributionUnit, ConflictUnit)
│   │   └── conflict_analyzer.py  # Unit extraction, grouping, risk scoring
│   │
│   ├── db/                   # Database Storage Layer
│   │   ├── schema.py         # SQLite schema, DEFAULT_DB_PATH
│   │   ├── models.py         # Dataclass models
│   │   ├── content.py        # Content-addressed storage (SHA256)
│   │   ├── ingest.py         # Vanilla/mod ingestion
│   │   ├── ast_cache.py      # AST cache by (content_hash, parser_version)
│   │   ├── symbols.py        # Symbol/ref extraction
│   │   ├── search.py         # FTS5 search
│   │   ├── playsets.py       # Playset management
│   │   └── cryo.py           # Snapshot export/import
│   │
│   └── emulator/             # (Phase 2) Full game state
│
├── tools/ck3lens_mcp/        # MCP Server
│   ├── server.py             # FastMCP with 25+ tools
│   └── ck3lens/
│       ├── workspace.py      # Live mod whitelist
│       └── db_queries.py     # Query layer
│
├── docs/                     # Design documentation
│   └── ARCHITECTURE.md       # Comprehensive architecture guide
│
└── tests/                    # Pytest suite
```

See [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) for detailed documentation.

---

## Database Schema (Key Tables)

### file_contents (Content-Addressed Storage)
```sql
content_hash TEXT PRIMARY KEY,  -- SHA256 of content
content_blob BLOB,              -- Binary content
content_text TEXT,              -- Text content (if not binary)
size INTEGER,                   -- Byte size
encoding_guess TEXT,
is_binary INTEGER,
created_at TEXT
```

### files
```sql
file_id INTEGER PRIMARY KEY,
content_version_id INTEGER,     -- FK to content_versions
relative_path TEXT,             -- e.g., "common/traits/00_traits.txt"
content_hash TEXT               -- FK to file_contents
```

### playsets
```sql
playset_id INTEGER PRIMARY KEY,
name TEXT,
vanilla_version_id INTEGER,
description TEXT,
is_active INTEGER,
created_at TEXT,
updated_at TEXT
```

### playset_mods
```sql
playset_id INTEGER,
content_version_id INTEGER,
load_order_index INTEGER,
enabled INTEGER
```

### symbols
```sql
symbol_id INTEGER PRIMARY KEY,
name TEXT,
symbol_type TEXT,               -- trait, decision, event, etc.
file_id INTEGER,
line_number INTEGER,
metadata TEXT                   -- JSON
```

---

## Merge Policies (Core Knowledge)

| Policy | Behavior | Used By |
|--------|----------|---------|
| `OVERRIDE` | Last definition wins completely | ~95% of content |
| `CONTAINER_MERGE` | Container merges, sublists append | on_actions ONLY |
| `PER_KEY_OVERRIDE` | Each key independent | localization, defines |
| `FIOS` | First definition wins | GUI types/templates |

See `docs/05_ACCURATE_MERGE_OVERRIDE_RULES.md` for complete reference.

---

## Development Guidelines

### Before Creating New Code
1. **Search existing modules** - ck3raven has comprehensive infrastructure
2. **Check `db/`** for database operations (use playsets.py, not raw SQL)
3. **Check `parser/`** before any parsing work
4. **Check `scripts/`** for existing utilities

### Key Entry Points
```python
# Database
from ck3raven.db.schema import DEFAULT_DB_PATH, get_connection, init_database
from ck3raven.db.playsets import create_playset, add_mod_to_playset
from ck3raven.db.ingest import ingest_vanilla, ingest_mod

# Parser
from ck3raven.parser import parse_file, parse_source

# Resolver
from ck3raven.resolver import resolve_folder, SourceFile
```

### Code Style
- Python 3.10+ with type hints
- Dataclasses for models (see `db/models.py`)
- SQLite with `row_factory` for dict access
- Logging via `logging.getLogger(__name__)`

### Testing
```bash
pytest tests/ -v
```

---

## Roadmap

### Phase 2: Game State Emulator (NEXT)
- [ ] `emulator/` module: load playset → resolve all folders → final state
- [ ] Full provenance: which mod contributed each definition
- [ ] Export resolved files with source annotations
- [ ] Conflict report generation

### Phase 3: Explorer UI
- [ ] VS Code extension with Activity Bar
- [ ] Sidebar webview (Explorer, Compatch, Reports)
- [ ] Node detail panel (Syntax ⇄ AST toggle)

### Phase 4: Compatch Helper (IN PROGRESS)
- [x] Conflict unit extraction and grouping
- [x] Risk scoring algorithm
- [x] Unit-level MCP tools (scan, list, detail, resolve)
- [ ] Decision card UI (winner selection)
- [ ] Merge editor with AI assistance
- [ ] Patch file generation

---

## External Paths

| Resource | Path |
|----------|------|
| Database | `~/.ck3raven/ck3raven.db` |
| Active mods config | `AI Workspace/active_mod_paths.json` |
| CK3 vanilla | `Steam/steamapps/common/Crusader Kings III/game` |
| CK3 mods | `Documents/Paradox Interactive/Crusader Kings III/mod` |
| CK3 version file | `Steam/.../Crusader Kings III/launcher/launcher-settings.json` |

---

## Quick Commands

```bash
# Build database (indexes vanilla + mods)
python scripts/build_database.py

# Create playset from active mods
python scripts/create_playset.py

# Extract symbols from indexed content
python scripts/populate_symbols.py

# Run tests
pytest tests/ -v

# Start MCP server
python -m tools.ck3lens_mcp.server
```

---

## Immediate Tasks (Priority Order)

1. **Fix version detection** in `build_database.py` line 43
2. **Fix column names** in `db_queries.py` (content → content_text/blob, file_size → size)
3. **Run `create_playset.py`** to populate playsets table
4. **Run `populate_symbols.py`** to extract symbols
5. **Test MCP tools** with `ck3_init_session` → `ck3_search_symbols`
