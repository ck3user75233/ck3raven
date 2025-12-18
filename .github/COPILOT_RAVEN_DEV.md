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
4. **Emulates** the final game state with full provenance tracking

---

## Current Status (December 2025)

| Module | Status | Description |
|--------|--------|-------------|
| `parser/` | ⚠️ 99% Complete | 100% regex-free, 100% vanilla parse rate, **missing to_dict()** |
| `resolver/` | ✅ Complete | 4 merge policies, 15+ content type configs |
| `db/` | ✅ Complete | SQLite with content-addressed storage, FTS5 search |
| `tools/ck3lens_mcp/` | ⚠️ Phase 1 | 20 MCP tools, needs symbol population |
| `emulator/` | 🔲 Stubs | Full game state building (Phase 2) |
| CLI | 🔲 Minimal | Basic structure only |

### Known Issues (Fix These)

| Issue | Location | Problem | Solution |
|-------|----------|---------|----------|
| **AST Serialization** | `parser/parser.py` | AST nodes lack `to_dict()` method | Add `to_dict()` to RootNode, BlockNode, etc. |
| ~~Version detection~~ | `scripts/build_database.py:43` | ~~Wrong path~~ | ✅ FIXED 2025-12-18 |
| ~~Empty playsets~~ | Database | ~~0 rows~~ | ✅ FIXED 2025-12-18 (105 mods) |
| Empty symbols | Database | `symbols` table has 0 rows | Blocked by AST serialization fix |

### Database Status

| Table | Count | Notes |
|-------|-------|-------|
| vanilla_versions | 1 | Version shows 1.13.x (BUG - should be 1.18.2) |
| mod_packages | 102 | ✅ All mods indexed |
| content_versions | 106 | ✅ |
| file_contents | 77,121 | ✅ 26 GB deduplicated |
| files | 80,968 | ✅ |
| playsets | 0 | ❌ Not created yet |
| symbols | 0 | ❌ Not extracted yet |

---

## Architecture

```
ck3raven/
├── src/ck3raven/
│   ├── parser/           # Lexer + Parser → AST
│   │   ├── lexer.py      # Token stream (100% regex-free)
│   │   └── parser.py     # RootNode, BlockNode, AssignmentNode, ValueNode, ListNode
│   │
│   ├── resolver/         # Merge/Override Resolution
│   │   ├── policies.py   # 4 merge policies + content type configs
│   │   └── resolver.py   # Conflict resolution with provenance
│   │
│   ├── db/               # Database Storage Layer
│   │   ├── schema.py     # SQLite schema, DEFAULT_DB_PATH, init_database()
│   │   ├── models.py     # 13 dataclass models
│   │   ├── content.py    # Content-addressed storage (SHA256)
│   │   ├── ingest.py     # Vanilla/mod ingestion
│   │   ├── ast_cache.py  # AST cache by (content_hash, parser_version)
│   │   ├── symbols.py    # Symbol/ref extraction
│   │   ├── search.py     # FTS5 search
│   │   ├── playsets.py   # Playset management (max 5 active)
│   │   └── cryo.py       # Snapshot export/import
│   │
│   └── emulator/         # (Phase 2) Full game state
│
├── tools/ck3lens_mcp/    # MCP Server
│   ├── server.py         # FastMCP with 20 tools
│   └── ck3lens/
│       ├── workspace.py  # Live mod whitelist
│       └── db_queries.py # Query layer
│
├── scripts/              # Utility scripts
│   ├── build_database.py
│   ├── create_playset.py
│   └── populate_symbols.py
│
└── tests/                # Pytest suite
```

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

### Phase 4: Compatch Helper
- [ ] Conflict unit extraction
- [ ] Risk scoring
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
