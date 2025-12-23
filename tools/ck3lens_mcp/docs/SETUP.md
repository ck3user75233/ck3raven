# CK3 Lens Setup Guide

Complete guide to setting up and using CK3 Lens MCP server with VS Code and GitHub Copilot.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [VS Code Configuration](#vs-code-configuration)
4. [Verifying the Setup](#verifying-the-setup)
5. [Using CK3 Lens](#using-ck3-lens)
6. [Live Mods Configuration](#live-mods-configuration)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.11+ | Runtime for the MCP server |
| VS Code | Latest | IDE with Copilot integration |
| GitHub Copilot | Latest | AI agent that will use CK3 Lens tools |
| Git | 2.x | For git operations on live mods |

### Required Data

CK3 Lens requires a populated **ck3raven SQLite database** at:

```
~/.ck3raven/ck3raven.db    (default location)
```

**Status: ✅ Database is built** with 80,968 files from vanilla CK3 and 105 active mods.

To rebuild the database:
```bash
cd "C:\Users\Nathan\Documents\AI Workspace\ck3raven"
python scripts/build_database.py
```

---

## Installation

### Step 1: Clone/Navigate to ck3raven

```bash
cd "C:\Users\Nathan\Documents\AI Workspace\ck3raven"
```

### Step 2: Create Python Virtual Environment (if not exists)

```powershell
# Windows
python -m venv .venv
.\.venv\Scripts\activate

# macOS/Linux
python -m venv .venv
source .venv/bin/activate
```

### Step 3: Install Dependencies

```bash
# Install ck3lens MCP server dependencies
pip install -e tools/ck3lens_mcp

# Or install manually
pip install "mcp[cli]" pydantic fs structlog typer
```

### Step 4: Verify Installation

```bash
cd tools/ck3lens_mcp
python -c "from server import mcp; print('CK3 Lens loaded successfully')"
```

---

## VS Code Configuration

### Method 1: Workspace MCP Configuration (Recommended)

Create or edit `.vscode/mcp.json` in your ck3raven workspace:

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

**For macOS/Linux:**

```jsonc
{
  "servers": {
    "ck3lens": {
      "type": "stdio",
      "command": "${workspaceFolder}/.venv/bin/python",
      "args": ["tools/ck3lens_mcp/server.py"]
    }
  }
}
```

### Method 2: User-Level MCP Configuration

Add to your VS Code settings (`settings.json`):

```jsonc
{
  "mcp.servers": {
    "ck3lens": {
      "type": "stdio",
      "command": "C:\\Users\\Nathan\\Documents\\AI Workspace\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\Nathan\\Documents\\AI Workspace\\ck3raven\\tools\\ck3lens_mcp\\server.py"]
    }
  }
}
```

### Reload VS Code

After configuring, reload VS Code:
- Press `Ctrl+Shift+P` → "Developer: Reload Window"

---

## Verifying the Setup

### Check MCP Server Status

1. Open VS Code Command Palette (`Ctrl+Shift+P`)
2. Run: "MCP: List Servers"
3. You should see `ck3lens` listed as active

### Test Tool Availability

Ask Copilot in chat:
```
@workspace What CK3 Lens tools are available?
```

Copilot should recognize and list the CK3 Lens tools.

### Quick Test

Ask Copilot:
```
Use ck3_init_session to initialize the CK3 Lens session
```

Expected response includes:
- `mod_root` path
- List of live mods
- Database path confirmation

---

## Using CK3 Lens

### Session Initialization

Before using other tools, initialize the session:

```
Initialize CK3 Lens with the default settings
```

This calls `ck3_init_session()` which:
- Connects to the ck3raven SQLite database
- Loads the live mods whitelist
- Sets up tool tracing

### Common Workflows

#### 1. Searching for Symbols

```
Search for all traits related to "combat"
```

Uses `ck3_search_symbols` with adjacency expansion:
- Finds `combat_prowess`, `good_combat_skill`, `combat_*` patterns

#### 2. Confirming Something Doesn't Exist

```
Does a trait called "master_duelist" exist in any active mod?
```

Uses `ck3_confirm_not_exists` for exhaustive fuzzy search before claiming missing.

#### 3. Reading File Content

```
Show me the contents of common/traits/00_traits.txt
```

Uses `ck3_get_file` to retrieve from database (with optional AST).

#### 4. Checking Conflicts

```
What conflicts exist in the common/on_action folder?
```

Uses `ck3_qr_conflicts` to show load-order winners/losers.

#### 5. Writing to Live Mods

```
Create a new file common/traits/zzz_my_trait.txt in Mini Super Compatch with a custom trait
```

Uses `ck3_write_file` (with syntax validation) to write to whitelisted mod.

#### 6. Git Operations

```
Show git status for MSC mod
```

Uses `ck3_git_status` to check uncommitted changes.

---

## Live Mods Configuration

### Default Whitelist

By default, CK3 Lens allows writes to these mods (if they exist on disk):

| Mod Folder Name | Description |
|-----------------|-------------|
| `PVP2` | PVP2 mod |
| `Mini Super Compatch` | MSC main mod |
| `MSCRE` | MSC Religion Expanded |
| `Lowborn Rise Expanded` | LRE mod |
| `More Raiding and Prisoners` | MRP mod |

### Custom Live Mods

Override via `ck3_init_session`:

```python
ck3_init_session(
    live_mods=["My Custom Mod", "Another Mod"]
)
```

### Adding New Mods to Whitelist

Edit `ck3lens/workspace.py`:

```python
DEFAULT_LIVE_MODS = [
    "PVP2",
    "Mini Super Compatch",
    "MSCRE",
    "Lowborn Rise Expanded",
    "More Raiding and Prisoners",
    "Your New Mod Here",  # Add new mod
]
```

---

## Tool Reference Quick Card

### Query Tools (Database Read-Only)

| Tool | Purpose |
|------|---------|
| `ck3_search_symbols` | Search symbols with adjacency expansion |
| `ck3_confirm_not_exists` | Exhaustive search before claiming missing |
| `ck3_get_file` | Get file content (raw or AST) |
| `ck3_qr_conflicts` | Quick-resolve conflict analysis |

### Live Mod Tools (Sandboxed Writes)

| Tool | Purpose |
|------|---------|
| `ck3_list_live_mods` | List writable mods |
| `ck3_read_live_file` | Read from live mod |
| `ck3_write_file` | Write with syntax validation |
| `ck3_edit_file` | Search-replace edit |
| `ck3_delete_file` | Delete file |
| `ck3_list_live_files` | List files in mod |

### Validation Tools

| Tool | Purpose |
|------|---------|
| `ck3_parse_content` | Parse CK3 script, return AST/errors |
| `ck3_validate_patchdraft` | Validate PatchDraft contract |

### Git Tools

| Tool | Purpose |
|------|---------|
| `ck3_git_status` | Check uncommitted changes |
| `ck3_git_diff` | View diffs |
| `ck3_git_add` | Stage files |
| `ck3_git_commit` | Commit changes |
| `ck3_git_push` / `ck3_git_pull` | Sync with remote |
| `ck3_git_log` | View commit history |

See [TOOLS.md](TOOLS.md) for complete signatures and examples.

---

## Troubleshooting

### "MCP server not found"

1. Check `.vscode/mcp.json` exists and has correct paths
2. Verify Python path is correct (use absolute path if needed)
3. Reload VS Code window

### "Module not found: ck3lens"

```bash
cd tools/ck3lens_mcp
pip install -e .
```

### "Database not found"

Ensure ck3raven database exists at the expected location:
- Default: `~/.ck3raven/ck3raven.db`
- Or specify via `ck3_init_session(db_path="...")`

### "Cannot write to mod"

Check that:
1. Mod folder name is in the whitelist
2. Mod folder exists on disk
3. Path is correct in CK3 mod directory

### "Syntax validation failed"

The content has CK3 script syntax errors. Use `ck3_parse_content` to see detailed error messages with line numbers.

### Check Tool Trace

All tool invocations are logged to:
```
C:\Users\Nathan\Documents\Paradox Interactive\Crusader Kings III\mod\ck3lens_trace.jsonl
```

Review this file to see what tools were called and their results.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Copilot Agent                     │
└─────────────────────────┬───────────────────────────────────┘
                          │ MCP Protocol (stdio)
┌─────────────────────────▼───────────────────────────────────┐
│                   CK3 Lens MCP Server                       │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Query Tools  │  │ Write Tools  │  │ Git Tools    │       │
│  │ (DB read)    │  │ (sandbox)    │  │              │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
└─────────┼─────────────────┼─────────────────┼───────────────┘
          │                 │                 │
┌─────────▼─────────┐ ┌─────▼─────────┐ ┌─────▼──────┐
│ ck3raven SQLite   │ │ Live Mod Dir  │ │ Git Repos  │
│ (parsed AST)      │ │ (whitelisted) │ │            │
│ ~/.ck3raven/      │ │ CK3/mod/MSC/  │ │            │
└───────────────────┘ └───────────────┘ └────────────┘
```

**Key Principles:**

1. **Database is source of truth** - All reads come from pre-parsed SQLite
2. **Sandboxed writes** - Only whitelisted mods can be modified
3. **Adjacency search** - Never claim something doesn't exist without exhaustive search
4. **Syntax validation** - Content validated before writing

---

## Next Steps

1. ✅ Complete this setup
2. Build the ck3raven database with your active playset
3. Start asking Copilot to help with CK3 modding tasks
4. Use git tools to track your changes

For questions or issues, check the ck3raven repository documentation.
