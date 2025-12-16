# ck3raven 🪶

**CK3 Game State Emulator** - A Python toolkit for parsing, merging, and resolving mod conflicts in Crusader Kings III.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## What is ck3raven?

ck3raven answers the question: **"What does the game actually see?"**

Given a playset (vanilla + mods in load order), ck3raven:

1. **Parses** all CK3/Paradox script files into AST (100% regex-free)
2. **Resolves** conflicts using accurate merge rules (OVERRIDE/MERGE/FIOS)
3. **Stores** everything in a deduplicated database for fast queries
4. **Emulates** the final game state with full provenance tracking

Essential for compatch authors, mod compatibility analysis, and understanding complex mod interactions.

---

## Current Status

| Module | Status | Description |
|--------|--------|-------------|
| `parser/` | ✅ Complete | 100% regex-free lexer/parser, 100% vanilla parse rate |
| `resolver/` | ✅ Complete | 4 merge policies, conflict detection, per-content-type rules |
| `db/` | ✅ Complete | SQLite with content-addressed storage, AST cache, FTS search |
| `emulator/` | 🔲 Not Started | Full game state building from playset |
| CLI | 🔲 Minimal | Basic structure only |

---

## Architecture

```
ck3raven/
├── src/ck3raven/
│   ├── parser/           # Lexer + Parser → AST
│   │   ├── lexer.py      # Token stream (100% regex-free)
│   │   └── parser.py     # AST: RootNode, BlockNode, AssignmentNode, ValueNode, ListNode
│   │
│   ├── resolver/         # Merge/Override Resolution
│   │   ├── policies.py   # 4 merge policies + 15 content type configs
│   │   └── resolver.py   # Conflict resolution engine with provenance
│   │
│   ├── db/               # Database Storage Layer
│   │   ├── schema.py     # SQLite schema (17 tables, FTS5)
│   │   ├── models.py     # 13 dataclass models
│   │   ├── content.py    # Content-addressed storage (SHA256 dedup)
│   │   ├── ingest.py     # Vanilla/mod ingestion with incremental updates
│   │   ├── parser_version.py  # Parser versioning for AST cache invalidation
│   │   ├── ast_cache.py  # AST cache keyed by (content_hash, parser_version)
│   │   ├── symbols.py    # Symbol/reference extraction from AST
│   │   ├── search.py     # FTS5 search (symbols, refs, content)
│   │   ├── playsets.py   # Playset management (max 5 active)
│   │   └── cryo.py       # Snapshot export/import for offline analysis
│   │
│   ├── emulator/         # (Future) Full game state building
│   └── cli.py            # Command-line interface
│
├── docs/                 # Design documentation (8 docs)
├── tests/                # Test suite
└── scripts/              # Utility scripts
```

---

## Key Specifications

### Parser
- **100% regex-free** lexer using character-by-character state machine
- **100% vanilla parse rate** on CK3 1.13.x
- **99.8% mod parse rate** (remaining 0.2% are mod syntax bugs)
- Handles edge cases: `29%`, `-$PARAM$`, `<=` as values, BOM, single quotes in Jomini

### Merge Policies

| Policy | Behavior | Used By |
|--------|----------|---------|
| `OVERRIDE` | Last definition wins completely | ~95% of content |
| `CONTAINER_MERGE` | Container merges, sublists append | on_actions only |
| `PER_KEY_OVERRIDE` | Each key independent, last wins | localization, defines |
| `FIOS` | First definition wins | GUI types/templates |

### Database Storage
- **Content-addressed**: SHA256 hash, same content stored once across all mods
- **Version identity**: Root hash = SHA256 of sorted (relpath, content_hash) pairs
- **AST cache**: Keyed by (content_hash, parser_version) - no redundant parsing
- **FTS5 search**: Full-text search across content, symbols, references
- **Playsets**: Max 5 active to conserve resources
- **Cryo snapshots**: Export/import frozen state for sharing

---

## Installation

```bash
git clone https://github.com/youruser/ck3raven.git
cd ck3raven
pip install -e ".[dev]"
```

## Quick Start

### Parse a File

```python
from ck3raven.parser import parse_file, parse_source

ast = parse_file("path/to/traditions.txt")
for block in ast.children:
    if hasattr(block, 'name') and block.name.startswith("tradition_"):
        print(f"Found: {block.name}")
```

### Resolve Conflicts

```python
from ck3raven.resolver import resolve_folder, SourceFile

sources = [
    SourceFile(Path("vanilla/common/culture/traditions"), "vanilla", 0),
    SourceFile(Path("mod1/common/culture/traditions"), "mod1", 1),
    SourceFile(Path("mod2/common/culture/traditions"), "mod2", 2),
]

state = resolve_folder("common/culture/traditions", sources)

for conflict in state.conflicts:
    print(f"{conflict.key}: {conflict.winner.source.source_name} wins over {[l.source.source_name for l in conflict.losers]}")
```

### Database Operations

```python
from ck3raven.db import init_database, ingest_vanilla, search_all, SearchScope

conn = init_database()
ingest_vanilla(conn, Path("path/to/game"), "1.13.2")

# Search for anything mentioning "brave"
results = search_all(conn, "brave", scope=SearchScope.ALL)
for r in results:
    print(f"{r.kind}: {r.name} in {r.file_path}")
```

---

## Documentation

| Doc | Description |
|-----|-------------|
| [00_ORIGINAL_CONCEPT](docs/00_ORIGINAL_CONCEPT.md) | Original vision and goals |
| [01_PARSER_AND_MERGER_CONCEPTS](docs/01_PARSER_AND_MERGER_CONCEPTS.md) | What is parsing? Why not regex? |
| [02_EXISTING_TOOLS_AND_FEASIBILITY](docs/02_EXISTING_TOOLS_AND_FEASIBILITY.md) | Landscape analysis |
| [03_TRADITION_RESOLVER_V0_DESIGN](docs/03_TRADITION_RESOLVER_V0_DESIGN.md) | Initial prototype design |
| [04_VIRTUAL_MERGE_EXPLAINED](docs/04_VIRTUAL_MERGE_EXPLAINED.md) | Multi-source comparison concept |
| [05_ACCURATE_MERGE_OVERRIDE_RULES](docs/05_ACCURATE_MERGE_OVERRIDE_RULES.md) | CK3's actual merge behavior |
| [06_CONTAINER_MERGE_OVERRIDE_TABLE](docs/06_CONTAINER_MERGE_OVERRIDE_TABLE.md) | Complete reference by folder |
| [07_TEST_MOD_AND_LOGGING_COMPATCH](docs/07_TEST_MOD_AND_LOGGING_COMPATCH.md) | Testing and instrumentation ideas |

---

## Roadmap

### Phase 1: Foundation ✅ Complete
- [x] Parser/lexer with 100% vanilla coverage
- [x] Merge policy definitions (4 policies, 15+ content types)
- [x] Conflict resolution engine with provenance
- [x] Database storage layer with content dedup
- [x] AST caching with parser versioning
- [x] Symbol/reference extraction
- [x] FTS search infrastructure
- [x] Playset management
- [x] Cryo snapshot export/import

### Phase 2: Game State Emulator (Next)
- [ ] `emulator/` module: load playset → resolve all folders → final state
- [ ] Full provenance tracking: which mod contributed each definition
- [ ] Export resolved files with source annotations
- [ ] Conflict report generation

### Phase 3: Developer Tools
- [ ] CLI for common operations (parse, resolve, search, export)
- [ ] Vanilla diff tool: compare versions for parser updates
- [ ] Conflict reporter: human-readable HTML/markdown reports
- [ ] Compatch suggester: auto-generate patch candidates

### Phase 4: Integration
- [ ] VS Code extension for in-editor conflict highlighting
- [ ] MCP server for AI-assisted modding workflows

---

## Credits

Inspired by:
- [ck3tiger](https://github.com/amtep/ck3tiger) - The excellent CK3 validator
- [Gambo's Super Compatch](https://steamcommunity.com/sharedfiles/filedetails/?id=2941627704) - Compatch patterns reference
- [Paradox Wiki Modding Guide](https://ck3.paradoxwikis.com/Modding) - Official documentation

## License

MIT License - see [LICENSE](LICENSE)

---

*ck3raven is not affiliated with Paradox Interactive.*
