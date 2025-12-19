# CK3 Lens Explorer - Design Brief

> **Version:** 0.2.0-dev  
> **Last Updated:** December 19, 2025  
> **Status:** Implementation in Progress

## Overview

CK3 Lens Explorer is a VS Code extension providing an IDE-like experience for CK3 mod development. It bridges the ck3raven Python backend (parser, database, resolver) to VS Code through a JSON-RPC bridge server.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        VS Code Extension (TypeScript)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ Extension   │  │ Explorer    │  │ Studio      │  │ Linting Provider    │ │
│  │ Entry Point │  │ TreeView    │  │ Panel       │  │ (Quick + Full)      │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
│         │                │                │                     │            │
│  ┌──────┴────────────────┴────────────────┴─────────────────────┴──────────┐│
│  │                          CK3LensSession                                 ││
│  │  - Manages Python bridge lifecycle                                      ││
│  │  - Tracks initialization state                                          ││
│  │  - Handles reconnection                                                 ││
│  └─────────────────────────────────┬───────────────────────────────────────┘│
└────────────────────────────────────┼────────────────────────────────────────┘
                                     │ JSON-RPC (stdio)
┌────────────────────────────────────▼────────────────────────────────────────┐
│                      Python Bridge Server (bridge/server.py)                 │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌──────────────┐  │
│  │ init_session  │  │ parse_content │  │ lint_file     │  │ write_file   │  │
│  │ search_symbol │  │ get_file      │  │ list_files    │  │ git_status   │  │
│  └───────────────┘  └───────────────┘  └───────────────┘  └──────────────┘  │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────────┐
│                           ck3raven Python Library                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────────────┐  │
│  │ Parser      │  │ Database    │  │ Resolver    │  │ Symbol Extraction  │  │
│  │ (lexer.py)  │  │ (SQLite)    │  │ (policies)  │  │ (symbols.py)       │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. Extension Entry Point (`extension.ts`)

**Responsibilities:**
- Activate extension on language/workspace match
- Initialize CK3LensSession
- Register all commands, views, providers
- Manage lifecycle (activate/deactivate)

**Key Commands:**
| Command | Description |
|---------|-------------|
| `ck3lens.initSession` | Initialize Python bridge + database connection |
| `ck3lens.validateFile` | Lint current file |
| `ck3lens.searchSymbols` | Open symbol search |
| `ck3lens.openAstViewer` | Open AST viewer for current file |
| `ck3lens.openStudio` | Open file creation studio |
| `ck3lens.openWidget` | Open floating widget panel |

---

### 2. Linting Provider (`linting/lintingProvider.ts`)

**Two-Phase Validation:**

| Phase | Engine | Latency | Checks |
|-------|--------|---------|--------|
| Quick | TypeScript | <10ms | Brace balance, string termination, common typos |
| Full | Python parser | 100-500ms | Complete syntax, semantic warnings, references |

**Features:**
- Debounced validation (300ms default)
- Status bar integration with error/warning counts
- Recovery hints in error messages
- Tracks last valid content for diff/recovery

**Quick Validator Checks (`quickValidator.ts`):**
- Unbalanced braces with precise locations
- Unterminated strings
- Common CK3 structural issues
- Very long lines (>300 chars)

---

### 3. Explorer View (`views/explorerView.ts`)

**Database-Driven Navigation:**
- Queries ck3raven database for folder/file structure
- Shows provenance: `[vanilla]`, `[MSC]`, `[LRE]`, etc.
- Supports file type filtering

**Tree Structure:**
```
📁 common
  📁 traits
    📄 00_traits.txt [vanilla]
    📄 custom_traits.txt [MSC]
  📁 decisions
    ...
📁 events
📁 localization
```

---

### 4. Studio Panel (`views/studioPanel.ts`)

**Purpose:** Create new CK3 files with templates and validation.

**Templates (11 total):**
| Template | Folder | Description |
|----------|--------|-------------|
| Event | `events/` | Character/realm events |
| Decision | `common/decisions/` | Player decisions |
| Trait | `common/traits/` | Character traits |
| Character Interaction | `common/character_interactions/` | Diplomacy actions |
| Culture | `common/culture/cultures/` | Culture definitions |
| Tradition | `common/culture/traditions/` | Culture traditions |
| Building | `common/buildings/` | Holding buildings |
| Court Position | `common/court_positions/` | Court position types |
| Scripted Effect | `common/scripted_effects/` | Reusable effects |
| Scripted Trigger | `common/scripted_triggers/` | Reusable triggers |
| On Action | `common/on_action/` | Event hooks |

**Features:**
- Real-time validation as you edit (500ms debounce)
- Copy from vanilla file option
- Opens file in editor after creation

---

### 5. AST Viewer Panel (`views/astViewerPanel.ts`)

**Purpose:** View file content with syntax highlighting and AST structure.

**Modes:**
- **Source View:** Syntax-highlighted raw content
- **AST View:** Tree structure of parsed file

---

### 6. Floating Widget (`widget/lensWidget.ts`)

**Purpose:** Quick access overlay for mode switching and status.

**Modes:**
| Mode | Icon | Description |
|------|------|-------------|
| ck3lens | 🔀 | Mod integration, conflict resolution |
| ck3raven-dev | 🧪 | Game-state emulator development |
| ck3creator | 💡 | New content creation |

**Status Indicators:**
- Lens enabled/disabled
- MCP connection status
- Agent engagement status
- Session information

---

## Planned Features

### Reference Validation (P1)

**Goal:** Warn when referencing undefined symbols.

**Implementation:**
1. Extract references from current file during lint
2. Query database for symbol existence
3. Report missing references as warnings

**Patterns to Check:**
```
has_trait = <trait_id>         → Check traits table
trigger_event = <event_id>     → Check events table
has_character_flag = <flag>    → Cross-reference flag sets
add_modifier = { modifier = <mod_id> }  → Check modifiers
```

### Scope Validation (P2)

**Goal:** Validate scope context for effects/triggers.

**Implementation:**
1. Parse scope chain: `root.liege.primary_title.holder`
2. Track current scope type at each level
3. Validate effects/triggers are valid for current scope

### Go to Definition (P2)

**Implementation:**
1. Parse token under cursor
2. Classify token type (trait, event, decision, etc.)
3. Query database for definition location
4. Open file and navigate to line

### IntelliSense (P2)

**Autocomplete Categories:**
- Scopes: `root`, `this`, `liege`, `holder`, etc.
- Effects: `add_trait`, `trigger_event`, etc.
- Triggers: `has_trait`, `is_ruler`, etc.
- Custom symbols from database

---

## File Structure

```
tools/ck3lens-explorer/
├── .vscode/
│   ├── launch.json           # Debug configurations
│   └── tasks.json            # Build tasks
├── src/
│   ├── extension.ts          # Entry point
│   ├── session.ts            # CK3LensSession
│   ├── bridge/
│   │   └── pythonBridge.ts   # JSON-RPC client
│   ├── linting/
│   │   ├── lintingProvider.ts    # Full linting with Python
│   │   └── quickValidator.ts     # Quick TS-based validation
│   ├── views/
│   │   ├── explorerView.ts       # Database-driven explorer
│   │   ├── astViewerPanel.ts     # AST viewer webview
│   │   └── studioPanel.ts        # File creation studio
│   ├── widget/
│   │   └── lensWidget.ts         # Floating widget
│   ├── language/
│   │   └── (language features)
│   └── utils/
│       └── logger.ts
├── bridge/
│   └── server.py             # Python JSON-RPC server
├── media/                    # Icons and assets
├── package.json              # Extension manifest
└── tsconfig.json             # TypeScript config
```

---

## Development

### Setup

```bash
cd tools/ck3lens-explorer
npm install
npm run compile
```

### Debug

1. Open `tools/ck3lens-explorer` in VS Code
2. Press F5 → "Run Extension"
3. Extension Development Host window opens

### Watch Mode

```bash
npm run watch
```

### Package

```bash
npm install -g @vscode/vsce
vsce package
```

---

## Database Dependencies

The extension requires a built ck3raven database:

```bash
cd ck3raven
python -m ck3raven.cli ingest --vanilla "path/to/CK3/game"
```

**Database Location:** `~/.ck3raven/ck3raven.db`

**Expected Size:** ~15-20 GB for full vanilla + mods

---

## Error Codes

### Quick Validator (QV)
| Code | Description |
|------|-------------|
| QV001 | Unmatched closing brace |
| QV002 | Unterminated string |
| QV003 | Unclosed brace |
| QV100 | Common typo pattern |
| QV101 | Double equals usage |
| QV102 | Missing equals before brace |
| QV200 | Very long line |

### Parser (LEX/PARSE)
| Code | Description |
|------|-------------|
| LEX001 | Lexer error (invalid character) |
| PARSE001 | Parse error (unexpected token) |
| ERR001 | Generic parse error |

### Style (STYLE/STRUCT)
| Code | Description |
|------|-------------|
| STYLE001 | Line too long (>200 chars) |
| STYLE002 | Mixed tabs and spaces |
| STRUCT001 | Unbalanced braces |

---

## Contributing

1. Fork the repository
2. Create feature branch
3. Make changes with tests
4. Submit pull request

## License

MIT
