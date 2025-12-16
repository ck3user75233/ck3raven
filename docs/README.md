# ck3raven Documentation

Design documents and specifications for the CK3 Game State Emulator.

## Document Index

| Doc | Description |
|-----|-------------|
| [00_ORIGINAL_CONCEPT](00_ORIGINAL_CONCEPT.md) | Original vision: feed a playset, get resolved game state |
| [01_PARSER_AND_MERGER_CONCEPTS](01_PARSER_AND_MERGER_CONCEPTS.md) | What is parsing? Why regex-free? |
| [02_EXISTING_TOOLS_AND_FEASIBILITY](02_EXISTING_TOOLS_AND_FEASIBILITY.md) | Tool landscape, feasibility analysis |
| [03_TRADITION_RESOLVER_V0_DESIGN](03_TRADITION_RESOLVER_V0_DESIGN.md) | Initial prototype architecture |
| [04_VIRTUAL_MERGE_EXPLAINED](04_VIRTUAL_MERGE_EXPLAINED.md) | Multi-source comparison concept |
| [05_ACCURATE_MERGE_OVERRIDE_RULES](05_ACCURATE_MERGE_OVERRIDE_RULES.md) | CK3's actual merge behavior (corrected) |
| [06_CONTAINER_MERGE_OVERRIDE_TABLE](06_CONTAINER_MERGE_OVERRIDE_TABLE.md) | Complete reference by folder/content type |
| [07_TEST_MOD_AND_LOGGING_COMPATCH](07_TEST_MOD_AND_LOGGING_COMPATCH.md) | Testing and instrumentation ideas |

---

## Project Status (December 2024)

### ✅ Phase 1: Foundation - COMPLETE

| Module | Status | Key Features |
|--------|--------|--------------|
| `parser/` | ✅ | 100% regex-free, 100% vanilla parse rate, handles all edge cases |
| `resolver/` | ✅ | 4 merge policies, 15+ content types, conflict detection |
| `db/` | ✅ | SQLite, content dedup, AST cache, FTS search, playsets, cryo |

### 🔲 Phase 2: Game State Emulator - NEXT

The emulator module will:
1. Load a playset (vanilla + mods in order)
2. Resolve all content folders using appropriate policies
3. Build complete game state with provenance tracking
4. Export resolved files with source annotations

### 🔲 Phase 3: Developer Tools

- CLI for parse/resolve/search/export
- Vanilla diff tool for parser updates
- Conflict reporter (HTML/markdown)
- Compatch suggester

---

## Key Specifications

### Parser Specifications
- **Lexer**: Character-by-character state machine, no regex
- **Tokens**: IDENTIFIER, STRING, NUMBER, OPERATOR, LBRACE, RBRACE, EQUALS, etc.
- **AST Nodes**: RootNode, BlockNode, AssignmentNode, ValueNode, ListNode
- **Edge Cases Handled**:
  - `29%` - percent as part of number
  - `-$AMOUNT$` - negative parameter reference
  - `<= >= != ==` as value tokens (not operators)
  - BOM handling (UTF-8-BOM, UTF-16)
  - Single quotes in Jomini files

### Merge Policy Specifications

| Policy | Behavior | Content Types |
|--------|----------|---------------|
| `OVERRIDE` | Last definition wins entirely | traditions, events, decisions, traits, cultures, religions, buildings, scripted_effects, scripted_triggers, character_interactions, schemes, focuses, perks, lifestyles, dynasties, artifacts, court_positions, casus_belli, laws, governments |
| `CONTAINER_MERGE` | Container merges, sublists append | on_actions only |
| `PER_KEY_OVERRIDE` | Each key independent | localization, defines |
| `FIOS` | First definition wins | GUI types/templates |

### Database Specifications
- **Storage**: SQLite with WAL mode
- **Deduplication**: SHA256 content hash, same file stored once
- **Version Identity**: Root hash = SHA256(sorted (relpath, content_hash) pairs)
- **AST Cache Key**: (content_hash, parser_version_id)
- **Parser Version**: Semantic versioning with git commit tracking
- **FTS**: SQLite FTS5 for content, symbols, references
- **Playsets**: Max 5 active (enforced in code)
- **Cryo**: Gzipped JSON export with manifest and checksum

---

## Architecture Overview

```
User Playset
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│                     ck3raven                             │
│                                                          │
│  ┌──────────┐   ┌───────────┐   ┌──────────────────┐    │
│  │ parser/  │──▶│ resolver/ │──▶│    emulator/     │    │
│  │          │   │           │   │   (Phase 2)      │    │
│  │ lexer.py │   │ policies  │   │                  │    │
│  │ parser.py│   │ resolver  │   │ • Load playset   │    │
│  └──────────┘   └───────────┘   │ • Resolve all    │    │
│       │                         │ • Track sources  │    │
│       ▼                         │ • Export state   │    │
│  ┌──────────────────────────────┴──────────────────┐    │
│  │                    db/                           │    │
│  │  schema • models • content • ingest • ast_cache  │    │
│  │  symbols • search • playsets • cryo              │    │
│  └──────────────────────────────────────────────────┘    │
│                          │                               │
│                          ▼                               │
│                    ┌──────────┐                          │
│                    │ SQLite   │                          │
│                    │ Database │                          │
│                    └──────────┘                          │
└─────────────────────────────────────────────────────────┘
     │
     ▼
Resolved Game State + Conflict Reports
```

---

*These documents originated from AI-assisted design discussions.*
