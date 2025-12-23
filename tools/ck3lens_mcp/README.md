# CK3 Lens

CK3 Lens is the MCP (Model Context Protocol) server component of ck3raven that provides AI agents with safe, structured access to CK3 mod content.

## Architecture

```
ck3raven (core)          →  Parse, ingest, resolve, emulate
    ↓
ck3lens (MCP server)     →  Expose tools to AI agents
    ↓
Agent (Copilot, etc.)    →  Search, read, write, validate
```

## Key Principles

1. **Database as source of truth**: All mod content is pre-parsed into ck3raven's SQLite database. Agents query the DB, never raw files.

2. **Sandboxed writes**: Agents can only write to whitelisted "live mod" directories.

3. **Adjacency search**: Automatic pattern expansion (e.g., "combat_skill" → "combat_*_skill", "*_combat_skill"). Agents cannot claim something "doesn't exist" without exhaustive fuzzy search.

4. **Validation before write**: Content must parse and pass reference checks before writing.

## Documentation

- **[SETUP.md](docs/SETUP.md)** - Complete installation and configuration guide
- **[TOOLS.md](docs/TOOLS.md)** - Full tool reference with signatures and examples

## Quick Start

### 1. Install Dependencies

```bash
cd ck3raven/tools/ck3lens_mcp
pip install -e .
```

### 2. Configure VS Code MCP

Create `.vscode/mcp.json`:

```jsonc
{
  "servers": {
    "ck3lens": {
      "type": "stdio",
      "command": "${workspaceFolder}\\.venv\\Scripts\\python.exe",
      "args": ["tools/ck3lens_mcp/server.py"]
    }
  }
}
```

### 3. Reload VS Code and Start Using

Ask Copilot:
```
Initialize CK3 Lens and search for traits related to "combat"
```

See [SETUP.md](docs/SETUP.md) for complete setup instructions.

## Available Tools (20 total)

### Query Tools (Database Read-Only)
- `ck3_init_session` - Initialize session with DB and live mods
- `ck3_search_symbols` - Search with adjacency expansion
- `ck3_confirm_not_exists` - Exhaustive search before claiming missing
- `ck3_get_file` - Get file content (raw or AST)
- `ck3_qr_conflicts` - Quick-resolve conflict analysis

### Live Mod Tools (Sandboxed Writes)
- `ck3_list_live_mods` - List writable mods
- `ck3_read_live_file` - Read from live mod
- `ck3_write_file` - Write with syntax validation
- `ck3_edit_file` - Search-replace edit
- `ck3_delete_file` - Delete file
- `ck3_list_live_files` - List files in mod

### Validation Tools
- `ck3_parse_content` - Parse CK3 script, return AST/errors
- `ck3_validate_patchdraft` - Validate PatchDraft contract

### Git Tools
- `ck3_git_status`, `ck3_git_diff`, `ck3_git_add`, `ck3_git_commit`
- `ck3_git_push`, `ck3_git_pull`, `ck3_git_log`

## Default Live Mods Whitelist

These mods can be written to (if present on disk):
- PVP2
- Mini Super Compatch (MSC)
- MSCRE
- Lowborn Rise Expanded (LRE)
- More Raiding and Prisoners (MRP)

## Requirements

- Python 3.11+
- ck3raven SQLite database (built by indexer)
- VS Code with GitHub Copilot
