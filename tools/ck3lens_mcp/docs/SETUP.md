# CK3 Lens MCP Server Setup Guide

Complete guide to setting up and using CK3 Lens MCP server with VS Code and GitHub Copilot.

> **Last Updated:** December 31, 2025  
> **Architecture:** Per-instance isolation with dynamic MCP registration

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [How It Works](#how-it-works)
5. [Agent Mode Initialization](#agent-mode-initialization)
6. [Verifying the Setup](#verifying-the-setup)
7. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

### Per-Instance Isolation

CK3 Lens uses **per-instance isolation** to support multiple VS Code windows simultaneously:

```
┌──────────────────────┐     ┌──────────────────────┐
│  VS Code Window A    │     │  VS Code Window B    │
│  Instance: abc123    │     │  Instance: def456    │
└──────────┬───────────┘     └──────────┬───────────┘
           │                            │
           ▼                            ▼
┌──────────────────────┐     ┌──────────────────────┐
│  MCP Server          │     │  MCP Server          │
│  CK3LENS_INSTANCE_ID │     │  CK3LENS_INSTANCE_ID │
│  = abc123            │     │  = def456            │
└──────────┬───────────┘     └──────────┬───────────┘
           │                            │
           ▼                            ▼
┌──────────────────────┐     ┌──────────────────────┐
│  agent_mode_abc123   │     │  agent_mode_def456   │
│  .json               │     │  .json               │
└──────────────────────┘     └──────────────────────┘
```

Each window:
- Gets a **unique instance ID** (random, survives window reload)
- Runs its **own MCP server process** with that ID in environment
- Has its **own agent mode file** (`~/.ck3raven/agent_mode_{id}.json`)
- Does **NOT interfere** with other windows

### Dynamic MCP Registration

The CK3 Lens Explorer VS Code extension **automatically registers** the MCP server:

- No manual `mcp.json` configuration needed
- Extension finds ck3raven root and Python automatically
- Server registered via VS Code's `McpServerDefinitionProvider` API

---

## Prerequisites

### Required Software

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.11+ | MCP server runtime |
| VS Code | 1.96+ | IDE with MCP support |
| GitHub Copilot | Latest | AI agent |
| CK3 Lens Explorer | Latest | Extension that registers MCP |

### Required Data

CK3 Lens requires a populated **ck3raven SQLite database**:

```
~/.ck3raven/ck3raven.db
```

Build with:
```bash
cd ck3raven
python builder/daemon.py start --symbols-only
```

---

## Installation

### Step 1: Clone ck3raven

```bash
git clone <repo> ck3raven
cd ck3raven
```

### Step 2: Create Python Environment

```powershell
# Windows
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
pip install -e tools/ck3lens_mcp
```

### Step 3: Install CK3 Lens Explorer Extension

The extension is in `tools/ck3lens-explorer/`. Install in development mode:

1. Open `tools/ck3lens-explorer/` in VS Code
2. Press `F5` to launch Extension Development Host
3. Or build VSIX: `npm run package`

### Step 4: Build Database

```bash
python builder/daemon.py start --symbols-only
```

---

## How It Works

### Extension Startup Flow

When VS Code starts with CK3 Lens Explorer:

1. **Extension activates** → Creates unique `instanceId` for this window
2. **Registers MCP server** → Passes `CK3LENS_INSTANCE_ID` in environment
3. **Blanks mode file** → Clears `~/.ck3raven/agent_mode_{instanceId}.json`
4. **Cleans stale files** → Deletes mode files older than 24 hours

### Agent Initialization Flow

When an agent starts working:

1. Agent calls `ck3_get_mode_instructions(mode="ck3lens")` or `mode="ck3raven-dev"`
2. Server writes mode to `~/.ck3raven/agent_mode_{instanceId}.json`
3. All subsequent tool calls read mode from that file
4. Mode is instance-specific, not shared across windows

### Canonical Mode Detection

**File:** `tools/ck3lens_mcp/ck3lens/agent_mode.py`

```python
# Mode stored per-instance
MODE_DIR = Path.home() / ".ck3raven"

def _get_mode_file(instance_id: Optional[str] = None) -> Path:
    """Get instance-specific mode file path."""
    if instance_id is None:
        instance_id = os.environ.get("CK3LENS_INSTANCE_ID", "default")
    safe_id = sanitize(instance_id)
    return MODE_DIR / f"agent_mode_{safe_id}.json"

def get_agent_mode(instance_id: Optional[str] = None) -> AgentMode:
    """Read mode from instance-specific file."""
    mode_file = _get_mode_file(instance_id)
    if not mode_file.exists():
        return None
    data = json.loads(mode_file.read_text())
    return data.get("mode")

def set_agent_mode(mode: AgentMode, instance_id: Optional[str] = None) -> None:
    """Write mode to instance-specific file."""
    mode_file = _get_mode_file(instance_id)
    mode_file.write_text(json.dumps({"mode": mode, ...}))
```

**Key points:**
- `CK3LENS_INSTANCE_ID` environment variable is set by extension
- All functions read this env var automatically if `instance_id` not passed
- Each MCP server process has its own env, so isolation is guaranteed

---

## Agent Mode Initialization

### The Canonical Entry Point

**CRITICAL:** Agents must call `ck3_get_mode_instructions()` FIRST.

```
ck3_get_mode_instructions(mode="ck3lens")
```

This single call:
1. Initializes database connection
2. Sets mode (persisted to instance file)
3. Initializes WIP workspace
4. Detects active playset
5. Returns instructions + policy boundaries

### Available Modes

| Mode | Purpose | Write Access |
|------|---------|--------------|
| `ck3lens` | CK3 modding | Local mods only |
| `ck3raven-dev` | Infrastructure development | ck3raven source |

### Deprecated: ck3_init_session

`ck3_init_session()` is **DEPRECATED**. Use `ck3_get_mode_instructions()` instead.

---

## Verifying the Setup

### Step 1: Check Extension

1. Open Output panel (`Ctrl+Shift+U`)
2. Select "CK3 Lens" output channel
3. Look for: `MCP instance ID for this window: abc123`

### Step 2: Check Mode File

After agent initialization:
```bash
ls ~/.ck3raven/agent_mode_*.json
cat ~/.ck3raven/agent_mode_abc123.json  # Use your instance ID
```

Should show:
```json
{
  "mode": "ck3lens",
  "instance_id": "abc123",
  "set_at": "2025-12-31T..."
}
```

### Step 3: Test with Agent

Ask Copilot:
```
Initialize CK3 Lens in ck3lens mode
```

Should call `ck3_get_mode_instructions(mode="ck3lens")` and return instructions.

### Step 4: Verify Instance Isolation

1. Open **two** VS Code windows with ck3raven workspace
2. Initialize one in `ck3lens` mode
3. Initialize other in `ck3raven-dev` mode
4. Verify they don't interfere with each other

---

## Troubleshooting

### "MCP server not found"

**Cause:** Extension didn't register the MCP server.

**Fix:**
1. Check that CK3 Lens Explorer is installed and activated
2. Check Output → CK3 Lens for errors
3. Reload window (`Ctrl+Shift+P` → "Developer: Reload Window")

### "Mode not initialized"

**Cause:** Agent didn't call `ck3_get_mode_instructions()`.

**Fix:** Call `ck3_get_mode_instructions(mode="ck3lens")` first.

### "Database not found"

**Cause:** ck3raven database doesn't exist.

**Fix:**
```bash
python builder/daemon.py start --symbols-only
```

### Mode Persisting Across Windows

**Symptom:** Mode from another window affecting this window.

**Cause:** Likely using old shared mode file.

**Fix:** 
1. Delete old file: `rm ~/.ck3raven/agent_mode.json`
2. Reload window

### Stale Mode Files Accumulating

**Cause:** Normal - each window creates a file.

**Fix:** Extension auto-cleans files older than 24 hours on startup.

Manual cleanup:
```bash
# Delete all mode files older than 24 hours
find ~/.ck3raven -name "agent_mode_*.json" -mtime +1 -delete
```

---

## File Locations

| File | Purpose |
|------|---------|
| `~/.ck3raven/ck3raven.db` | Main database |
| `~/.ck3raven/agent_mode_{id}.json` | Per-instance mode |
| `~/.ck3raven/wip/` | WIP workspace (ck3lens mode) |
| `ck3raven/.wip/` | WIP workspace (ck3raven-dev mode) |
| `ck3raven/playsets/` | Playset definitions |

---

## Extension Components

| Component | Location | Purpose |
|-----------|----------|---------|
| MCP Provider | `src/mcp/mcpServerProvider.ts` | Registers MCP server dynamically |
| Mode Blanking | `src/extension.ts` | Clears mode on startup |
| Stale Cleanup | `src/extension.ts` | Cleans old mode files |

---

## For Developers

### Environment Variables

| Variable | Set By | Purpose |
|----------|--------|---------|
| `CK3LENS_INSTANCE_ID` | Extension | Unique window identifier |
| `PYTHONPATH` | Extension | Includes ck3raven/src |
| `CK3LENS_CONFIG` | User (optional) | Custom config path |

### Instance ID Generation

The instance ID is:
- Random: `{timestamp_base36}-{random_hex}` (e.g., `abc1-def456`)
- Stored in `globalState` per window process (survives reload)
- Cleaned up when VS Code process ends

### Adding New Mode-Aware Tools

```python
from ck3lens.agent_mode import get_agent_mode

def my_tool():
    mode = get_agent_mode()  # Auto-reads CK3LENS_INSTANCE_ID
    if mode is None:
        return {"error": "Call ck3_get_mode_instructions first"}
    # ... mode-aware logic
```
