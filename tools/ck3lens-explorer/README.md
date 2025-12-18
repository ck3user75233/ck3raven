# CK3 Lens Explorer

VS Code extension for CK3 mod development - Game state explorer, conflict resolution, and real-time linting powered by ck3raven.

## Features

### 🔍 Game State Explorer
Browse the complete game state from your playset - see what the game actually sees after all mods are loaded.

### ⚔️ Conflict Detection
Identify which mods are overriding each other and who "wins" for each definition.

### 🔎 Symbol Search
Search for traits, events, decisions, and other symbols across all mods with fuzzy/adjacency matching.

### ✅ Real-Time Linting
Get immediate feedback on syntax errors as you type, powered by ck3raven's 100% regex-free parser.

### 🎯 Go to Definition / Find References
Navigate your mod codebase like a real IDE - jump to definitions and find all usages.

### 💡 IntelliSense
Autocomplete for keywords, scopes, effects, triggers, and your custom symbols.

### 📝 Syntax Highlighting
Proper syntax highlighting for Paradox script files (.txt) and localization (.yml).

### 🔧 Live Mod Editing
Write to whitelisted mods with syntax validation before save.

### 🔗 Git Integration
Track changes, commit, and sync your mod repositories.

## Requirements

- VS Code 1.85.0+
- Python 3.11+
- ck3raven database (built from your playset)

## Installation

### 1. Build ck3raven database

```bash
cd ck3raven
pip install -e .
python scripts/build_database.py
```

### 2. Install extension dependencies

```bash
cd tools/ck3lens-explorer
npm install
npm run compile
```

### 3. Launch extension

Press F5 in VS Code to launch the Extension Development Host.

## Configuration

```json
{
  "ck3lens.databasePath": "",  // Default: ~/.ck3raven/ck3raven.db
  "ck3lens.vanillaPath": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Crusader Kings III\\game",
  "ck3lens.pythonPath": "python",
  "ck3lens.enableRealTimeLinting": true,
  "ck3lens.lintOnSave": true,
  "ck3lens.lintDelay": 500,
  "ck3lens.liveMods": ["Mini Super Compatch", "MSCRE"]
}
```

## Commands

| Command | Description |
|---------|-------------|
| `CK3 Lens: Initialize Session` | Connect to ck3raven database |
| `CK3 Lens: Validate Current File` | Lint the active file |
| `CK3 Lens: Validate Entire Workspace` | Lint all .txt files |
| `CK3 Lens: Search Symbols` | Search for symbols |
| `CK3 Lens: Show Conflicts` | Display mod conflicts |
| `CK3 Lens: Go to Definition` | Jump to symbol definition |
| `CK3 Lens: Find All References` | Find all usages |
| `CK3 Lens: Rebuild Database` | Rebuild ck3raven database |

## Keybindings

| Key | Command |
|-----|---------|
| `F12` | Go to Definition |
| `Shift+F12` | Find All References |
| `Ctrl+Shift+O` | Search Symbols |

## Views

### Game State Explorer
Browse game content organized by folder (common, events, localization, etc.).

### Conflicts
See all detected conflicts with winner/loser information.

### Symbols
Browse and search symbols by type (traits, events, decisions, etc.).

### Live Mods
Manage writable mods with git status integration.

## Architecture

```
VS Code Extension (TypeScript)
        │
        │ JSON-RPC (stdio)
        ▼
Python Bridge Server
        │
        ▼
ck3raven (Parser, Resolver, Database)
```

## License

MIT

## Related Projects

- [ck3raven](../../README.md) - CK3 Game State Emulator core
- [ck3lens_mcp](../ck3lens_mcp/README.md) - MCP server for AI agent integration
