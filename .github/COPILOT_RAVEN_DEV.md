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
| files | ~54,000 | ✅ Vanilla + mods indexed |
| asts | ~13,000 | ✅ Parsed ASTs |
| symbols | ~120,000 | ✅ Definitions extracted |
| refs | ~130,000 | ✅ Symbol references |
| localization_entries | ~1,600,000 | ✅ Loc keys (THIS is 1.6M) |
| trait_lookups | ~650 | ✅ Trait metadata |
| event_lookups | ~18,000 | ✅ Event metadata |
| decision_lookups | ~700 | ✅ Decision metadata |
| playsets | 1+ | ✅ Active playset configured |

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

## Code Validation Requirements (MANDATORY)

**All Python code MUST pass validation before being considered complete.**

### Policy Enforcement (CRITICAL)

**Definition of "Done":** A task is complete ONLY when `git commit` succeeds.

The pre-commit hook runs `ck3_validate_policy` and blocks commits that fail validation.
This is the only definition of completion - not "I wrote the code" or "tests pass".

```
✅ "Done" = Commit succeeded (implies validation passed)
❌ "Done" ≠ "I finished writing"
❌ "Done" ≠ "It compiles"
❌ "Done" ≠ "I think it's ready"
```

**Before committing:**
1. All Python files pass `get_errors` 
2. Policy validation passes: `ck3_validate_policy(mode="ck3raven-dev")`
3. Then and only then: `git commit`

The hook is at `.githooks/pre-commit`. It reads the trace log and validates all tool calls.

### Before Making Changes
1. Run `get_errors` on target files to understand existing state
2. Check if imports exist using terminal or `mcp_pylance_mcp_s_pylanceRunCodeSnippet`

### After Making Changes  
1. **Run `get_errors`** on all modified Python files
2. **Code is NOT complete** until `get_errors` returns clean (no errors)
3. If errors remain, fix them before reporting completion

### Import Validation
For any new imports, verify they exist at runtime:
```python
# Use terminal to test imports before committing code:
& "C:\Users\Nathan\Documents\AI Workspace\.venv\Scripts\python.exe" -c "from module import Class; print('OK')"
```

Or use `mcp_pylance_mcp_s_pylanceRunCodeSnippet` to validate imports.

### Validation Checklist
- [ ] `get_errors` returns no errors for modified files
- [ ] All new imports tested and confirmed working
- [ ] TypeScript files compiled successfully (`npm run compile`)
- [ ] No syntax errors in any modified files

**Do NOT report a task as complete if validation fails.**

---

## Debugging Policy (CRITICAL)

### NO SIDE SCRIPTS

**All debugging code MUST live inside ck3raven source directories.**

When diagnosing issues (build failures, performance problems, data anomalies):

✅ **DO:**
- Use existing daemon flags: `--debug-refs N`, `--test`, `--symbols-only`
- Add new flags/functions to `builder/daemon.py` for diagnostic features
- Add debug modes to existing library code
- Create proper modules in `builder/`, `src/ck3raven/`, or `scripts/`

❌ **DO NOT:**
- Create one-off Python scripts in AI Workspace or other external folders
- Write temporary debugging scripts outside ck3raven source
- Develop features in side scripts that should be library code
- Use Jupyter notebooks for debugging (use proper test files instead)

### Rationale
Side scripts cause problems:
1. **Lost context** - Scripts get lost, duplicated, or forgotten
2. **No testing** - Side scripts bypass the test suite
3. **Code rot** - Features developed outside the library never get maintained
4. **Policy bypass** - Side scripts skip pre-commit validation

### Builder-Daemon Debug Interface

**Unified debug mode for any daemon phase:**
```bash
# Debug any phase with detailed timing (outputs to ~/.ck3raven/daemon/debug_output.json)
& $VENV_PYTHON builder/daemon.py start --debug PHASE --debug-limit N

# Available phases:
#   all          - Run ALL phases sequentially
#   ingest       - File discovery and content storage
#   parse        - Content → AST parsing
#   symbols      - AST → symbol extraction
#   refs         - AST → reference extraction  
#   localization - YML → localization entries
#   lookups      - Symbol → lookup tables

# Examples:
& $VENV_PYTHON builder/daemon.py start --debug all --debug-limit 10
& $VENV_PYTHON builder/daemon.py start --debug refs --debug-limit 20
& $VENV_PYTHON builder/daemon.py start --debug parse --debug-limit 50

# Run synchronously with full output (no background daemon)
& $VENV_PYTHON builder/daemon.py start --test

# Skip mods (vanilla only)
& $VENV_PYTHON builder/daemon.py start --test --skip-mods
```

**Debug output includes:**
- Per-file timing breakdown (decode_ms, extract_ms, total_ms)
- Input/output sizes (bloat measurement)
- Efficiency metrics (items per KB, ms per KB)
- Summary statistics with projected rates

When you need new debugging capability, add it to the daemon or create a proper 
module in `builder/` or `scripts/`.

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
# IMPORTANT: Always use the venv Python!
VENV_PYTHON="C:\Users\Nathan\Documents\AI Workspace\.venv\Scripts\python.exe"

# Build database (detached daemon - runs in background)
& $VENV_PYTHON builder/daemon.py start

# Force full rebuild (clears all data)
& $VENV_PYTHON builder/daemon.py start --force

# Build only active playset mods
& $VENV_PYTHON builder/daemon.py start --playset-file "path/to/active_mod_paths.json"

# Check build status
& $VENV_PYTHON builder/daemon.py status

# View build logs (follow mode)
& $VENV_PYTHON builder/daemon.py logs -f

# Stop daemon
& $VENV_PYTHON builder/daemon.py stop

# Run tests
pytest tests/ -v

# Start MCP server
python -m tools.ck3lens_mcp.server
```

---

## Immediate Tasks (Priority Order)

1. **Database build in progress** - daemon running, check with `python builder/daemon.py status`
2. **Localization phase order** - move to Phase 3 (after parsing, before symbols)
3. **Add more lookup extractors** - currently have trait/event/decision, need culture/religion
4. **Test MCP tools** with `ck3_init_session` → `ck3_search` → verify results
