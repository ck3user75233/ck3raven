# Builder Design: Current State (December 2024)

> **Status**: Work in progress. This document captures the AS-IS state with open questions.

---

## Overview

The ck3raven database builder (`builder/daemon.py`) processes CK3 game files into a SQLite database for querying via MCP tools. It runs as a detached daemon with PID file, heartbeat, and log output.

---

## Current Architecture

### File Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CURRENT BUILD PHASES                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Phase 1: VANILLA INGEST                                                     │
│    Scan vanilla game files → file_contents table                             │
│    Set file_type based on file_routes.py                                     │
│                                                                              │
│  Phase 2: MOD INGEST                                                         │
│    Scan all Steam Workshop + local mods → file_contents table                │
│    Same file_type tagging                                                    │
│                                                                              │
│  Phase 3: PARSING (multi-route based on file_type)                           │
│    - file_type='script' → Script Parser → AST → asts table                   │
│    - file_type='localization' → Loc Parser → localization_entries (TODO)     │
│    - file_type='lookups' → NO PARSING (ingest only, future: extractors)      │
│    - file_type='skip' → NO PARSING                                           │
│                                                                              │
│  Phase 4: SYMBOL EXTRACTION (from ASTs only)                                 │
│    Walk ASTs → Extract trait, event, decision definitions → symbols table    │
│                                                                              │
│  Phase 5: REFERENCE EXTRACTION (from ASTs only)                              │
│    Walk ASTs → Extract symbol usages → refs table                            │
│                                                                              │
│  Phase 6: DONE                                                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### File Routing (file_routes.py)

Defines 4 routes - canonical source of truth for file classification:

| Route | file_type | Description | Current Status |
|-------|-----------|-------------|----------------|
| `SCRIPT` | 'script' | Parse → AST → symbols → refs | ✅ Implemented |
| `LOCALIZATION` | 'localization' | Parse .yml → localization_entries | 🔄 Parser exists, daemon doesn't call it |
| `LOOKUPS` | 'lookups' | Ingest only; future: specialized extractors | ✅ Tagged at ingest, skipped in parsing |
| `SKIP` | 'skip' | Binary files, GFX, audio | ✅ Implemented (no processing) |

**LOOKUPS route** covers files that will eventually need specialized extractors (not full AST):
- `history/provinces/` - province ID lookups
- `history/characters/` - character ID lookups  
- `history/titles/` - title holder lookups
- `common/dynasties/` - dynasty ID lookups
- `name_lists/`, `/names/` - name validation
- `coat_of_arms/coat_of_arms/` - CoA ID lookups

These are **ingested** (stored in file_contents) but **not parsed** in Phase 3. Future specialized extractors will populate lookup tables from these files using lightweight key-value extraction, not full AST.

---

## Current Parser (`ck3raven/parser/`)

### Components

| File | Purpose | Lines |
|------|---------|-------|
| `lexer.py` | Tokenizer for Paradox script | ~480 |
| `parser.py` | Builds AST from tokens | ~1020 |
| `localization.py` | Parses .yml localization files | ~180 |

### Lexer Notes

The lexer is a hand-written tokenizer (no regex). It handles:
- Identifiers with special chars: `_.|&'-:/%`
- Quoted strings with escapes
- Numbers (int, float, negative)
- Operators: `=`, `<`, `>`, `<=`, `>=`, `!=`, `==`, `?=`
- Comments (# to EOL)
- Params (`$PARAM$`)
- Scripted values (`@my_value`)

**Open question**: Is this lexer suitable for lookup data extraction? Probably yes - the token stream is the same, we just need different consumers (extractors vs full AST builder).

### AST Node Types

```python
class NodeType(Enum):
    ROOT = auto()           # Top-level container
    BLOCK = auto()          # name = { ... }
    ASSIGNMENT = auto()     # key = value
    VALUE = auto()          # standalone value (in a list)
    LIST = auto()           # { item1 item2 item3 }
    OPERATOR_EXPR = auto()  # key < value, key >= value, etc.
```

### AST Dataclasses

- `ValueNode(value, value_type)` - string, number, identifier, bool
- `AssignmentNode(key, operator, value)` - key-value pair
- `BlockNode(name, children, operator)` - nested block
- `ListNode(items)` - list of values
- `RootNode(children)` - top-level container

All nodes have `line`, `column`, `to_pdx()`, `to_dict()` methods.

### Operators Supported

`=`, `<`, `>`, `<=`, `>=`, `!=`, `==`, `?=`

### Token Types

Identifiers, strings, numbers, booleans, braces, brackets, operators, comments, params (`$PARAM$`), scripted values (`@my_value`).

---

## Open Questions

### 1. AST for Everything?

**Current approach**: All `.txt` files in script folders get full AST parsing.

**User challenge**: Is full AST overkill for lookup data like:
- `history/provinces/*.txt` (just need province ID → data mapping)
- `common/dynasties/*.txt` (just need dynasty ID → name mapping)  
- `common/cultures/*.txt` (just need culture definitions)
- Name lists, religion definitions, etc.

**Key insight from user**: 
> "using full blown AST format will be tremendously expensive in terms of size and usability compared to treating those as lookups"

**Proposal**: Different output formats for different purposes:
- **Script files** (events, decisions, scripted_effects): Full AST for modification support
- **Lookup files** (provinces, dynasties, names): Lightweight key-value extraction

### 2. What Existing Parsers Do

| Parser | Language | Approach | AST? | Speed |
|--------|----------|----------|------|-------|
| **CWTools** | F# | Full AST + schema validation | Yes | Medium |
| **jomini** (Rust) | Rust | "Tape" parser, serde-like deserialization | Flexible | 1+ GB/s |
| **pyradox** | Python | Tree structure (dict-like) | Partial | Slow |
| **ck3raven** | Python | Full AST with node types | Yes | Medium |

**jomini's approach** is particularly interesting:
- Uses "tape parsing" (similar to simdjson)
- Can deserialize directly to structs OR provide mid-level iteration
- Doesn't force full AST for everything

**CWTools' approach**:
- Schema-driven validation
- Processes into game-specific structures after parsing
- Separate handling for different file types

### 3. Lookup Data Handler

**Current gap**: No handler for "lookup data" - files that populate reference tables.

**Proposal**: A new concept:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PROPOSED: LOOKUP DATA HANDLERS                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Same parser (tokens), different OUTPUT:                                     │
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   Lexer      │───▶│   Parser     │───▶│   Output     │                   │
│  │  (tokens)    │    │  (structure) │    │  (varies)    │                   │
│  └──────────────┘    └──────────────┘    └──────────────┘                   │
│                              │                                               │
│                     ┌────────┴────────┐                                      │
│                     ▼                 ▼                                      │
│              ┌─────────────┐   ┌─────────────┐                              │
│              │  Full AST   │   │  Lookup     │                              │
│              │  (scripts)  │   │  Extractor  │                              │
│              └─────────────┘   └─────────────┘                              │
│                     │                 │                                      │
│                     ▼                 ▼                                      │
│              ┌─────────────┐   ┌─────────────┐                              │
│              │  asts table │   │  provinces  │                              │
│              │  symbols    │   │  dynasties  │                              │
│              │  refs       │   │  cultures   │                              │
│              └─────────────┘   └─────────────┘                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4. Phase Ordering

**User feedback**:
> "if I'm designing the builder I have no idea why this comes after symbol extraction. I'd say all parsing/lookup table assembly happens in phase 3 - parsing"

**Agreed**. Phase 3 should be:
```
Phase 3: PARSING (all routes)
  - file_type='script' → Script Parser → AST
  - file_type='localization' → Loc Parser → localization_entries
  - file_type='reference' → Lookup Extractor → lookup tables
  
Phase 4: SYMBOL EXTRACTION (from ASTs only)
Phase 5: REFERENCE EXTRACTION (from ASTs only)
```

Localization and lookup data don't need subsequent phases - they produce final tables directly.

### 5. Reference Data vs Reference Extraction

**Terminology confusion**:

| Term | Meaning |
|------|---------|
| **Reference Data** (route) | Files that populate lookup tables (provinces, characters, dynasties) |
| **Reference Extraction** (phase) | Extracting "who calls whom" from ASTs (event X fires event Y) |

These are completely different concepts with unfortunately similar names.

**Proposal**: Rename file route from `REFERENCE_DATA` to `LOOKUP_DATA` to avoid confusion.

---

## External Parser References

### Worth Studying

1. **CWTools** (F#) - https://github.com/cwtools/cwtools
   - Best for: AST structure, diagnostics, schema-driven validation
   - Powers VS Code extension for Paradox modding
   - Handles all Paradox games

2. **jomini** (Rust) - https://github.com/rakaly/jomini
   - Best for: Performance, correctness, flexible output
   - 1+ GB/s parsing speed
   - Tape-based parsing (efficient memory)
   - Powers pdx.tools EU4 analyzer

3. **pyradox** (Python) - https://github.com/ajul/pyradox
   - Best for: Python patterns, Tree structure
   - Uses regex tokenizer + state machine parser
   - Tree combines dict and ElementTree aspects

4. **Clausewitz syntax reference** - https://pdx.tools/blog/a-tour-of-pds-clausewitz-syntax
   - Essential reading for edge cases
   - Documents undocumented format quirks

### Key Insights from External Parsers

**From jomini**:
- Don't force full AST - allow direct struct deserialization
- Tape parsing is memory-efficient
- Binary and text formats differ significantly

**From CWTools**:
- Schema-driven validation catches errors early
- Game-specific post-processing is necessary
- Comments and formatting preservation matters for round-tripping

**From pyradox**:
- State machine parser handles edge cases well
- Color parsing is a special case
- Groups vs trees need lookahead to distinguish

**From Clausewitz syntax tour**:
- `{}` can be empty array OR empty object
- Duplicate keys are valid (append to list)
- Missing operators are sometimes valid (`foo{bar=qux}`)
- Files can have trailing `}` without matching open
- Scalars can be numbers, dates, booleans, strings, variables

---

## Development Areas

### Immediate (Current Sprint)

1. **Finish file_routes consolidation**
   - Remove skip_rules.py (currently still imported)
   - All file classification in one place

2. **Config file for paths**
   - Hardcoded vanilla, workshop, mods paths → config file
   - Support multiple installations

3. **Test daemon on fixture**
   - Need reliable test data
   - Validate each phase

### Short-term

4. **Localization parsing in daemon**
   - Parser exists, need to call it in Phase 3
   - Populate localization_entries table

5. **Lookup data extraction**
   - Province IDs, dynasty definitions, culture mappings
   - Lightweight extraction without full AST

### Medium-term

6. **Parser improvements**
   - Study jomini for performance patterns
   - Study CWTools for error recovery patterns
   - Consider hybrid approach: fast lexer + pluggable output

7. **Schema validation**
   - CWTools-style schema for validation
   - Catch "undefined symbol" errors

---

## Files Involved

```
builder/
  daemon.py                    # Main daemon (1234 lines)

src/ck3raven/
  parser/
    lexer.py                   # Tokenizer (481 lines)
    parser.py                  # AST builder (1023 lines)
    localization.py            # Loc parser (178 lines)
    __init__.py                # Exports
  
  db/
    file_routes.py             # File classification (336 lines)
    content.py                 # File ingestion
    skip_rules.py              # TO BE REMOVED (legacy)
    symbols.py                 # Symbol extraction
    references.py              # Reference extraction
    schema.py                  # Database schema
    work_detection.py          # Incremental build detection
```

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2024-12 | file_routes.py is canonical | Single source of truth for file classification |
| 2024-12 | Daemon uses file_type column | SQL filtering instead of scattered LIKE patterns |
| 2024-12 | Phase 3 = all parsing | Localization/lookup shouldn't follow symbol extraction |
| TBD | Full AST vs lightweight extraction | Need to decide per-folder what output format |
| TBD | Rename REFERENCE_DATA → LOOKUP_DATA | Avoid confusion with reference extraction phase |

---

## Questions for User

1. Should lookup extraction reuse the lexer but skip AST building?
2. What specific lookup tables do we need first? (provinces, dynasties, cultures?)
3. Should we study jomini's Rust code for patterns even if we stay in Python?
4. Is round-trip preservation (parse → modify → write) a requirement?
