# MCP Server Architecture

> **Status:** AUTHORITATIVE  
> **Last Updated:** January 17, 2026  
> **Purpose:** Lock in the per-instance MCP server architecture to prevent drift

---

## Critical Architecture Decision

**CK3 Lens uses DYNAMIC per-instance MCP server registration, NOT static mcp.json.**

This is non-negotiable. Any agent that resurrects a static `mcp.json` file is breaking the architecture.

---

## Why Per-Instance Matters

### The Problem (Pre-December 2025)

When using a static `mcp.json`:
1. All VS Code windows share ONE MCP server definition
2. All windows share ONE `agent_mode.json` file
3. **Initializing mode in Window A changes the mode in Window B**
4. Cross-window corruption causes agents to operate in wrong mode

### The Solution: Per-Instance IDs

Each VS Code window:
1. Gets a unique `CK3LENS_INSTANCE_ID` (UUID)
2. Has its own mode file: `~/.ck3raven/agent_mode_{instanceId}.json`
3. MCP server receives the instance ID as an environment variable
4. Mode changes are isolated per-window

---

## Architecture Components

### 1. Extension: mcpServerProvider.ts

**Location:** `tools/ck3lens-explorer/src/mcp/mcpServerProvider.ts`

**Responsibility:** Dynamically register MCP server with VS Code

```typescript
// Generates unique instance ID per window
const instanceId = uuidv4();

// Registers dynamic MCP server definition
vscode.lm.registerMcpServerDefinitionProvider('ck3lens', {
    provideMcpServerDefinitions: () => [{
        label: 'CK3 Lens MCP Server',
        type: 'stdio',
        command: 'python',
        args: ['-m', 'ck3lens_mcp.server'],
        env: {
            CK3LENS_INSTANCE_ID: instanceId,  // <-- THE KEY
            // ... other env vars
        }
    }]
});
```

### 2. Extension: package.json Contribution

**Location:** `tools/ck3lens-explorer/package.json`

**Required contribution point:**
```json
{
  "contributes": {
    "mcpServerDefinitionProviders": [
      {
        "id": "ck3lens",
        "label": "CK3 Lens MCP Server"
      }
    ]
  }
}
```

**NOTE:** `enabledApiProposals` is NOT needed - this API is stable as of VS Code 1.96.

### 3. MCP Server: agent_mode.py

**Location:** `tools/ck3lens_mcp/ck3lens/agent_mode.py`

**Responsibility:** Read/write mode using instance-specific files

```python
def _get_mode_file() -> Path:
    """Get mode file path based on instance ID."""
    instance_id = os.environ.get("CK3LENS_INSTANCE_ID", "default")
    return Path.home() / ".ck3raven" / f"agent_mode_{instance_id}.json"
```

### 4. Extension: agentView.ts

**Location:** `tools/ck3lens-explorer/src/views/agentView.ts`

**Responsibility:** UI for mode initialization

The agent view provides buttons/prompts for:
- Initializing ck3lens mode
- Initializing ck3raven-dev mode

When user selects a mode, the extension:
1. Writes to the instance-specific mode file
2. The MCP server reads from that file on next call

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        VS Code Window (Instance A)                       │
├─────────────────────────────────────────────────────────────────────────┤
│  1. Extension activates                                                  │
│  2. mcpServerProvider generates instanceId = "abc-123"                   │
│  3. Registers MCP server with env: CK3LENS_INSTANCE_ID=abc-123           │
│  4. User clicks "Initialize ck3lens mode"                                │
│  5. Extension writes to ~/.ck3raven/agent_mode_abc-123.json              │
│  6. MCP server reads from agent_mode_abc-123.json                        │
│  7. Agent operates in ck3lens mode                                       │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                        VS Code Window (Instance B)                       │
├─────────────────────────────────────────────────────────────────────────┤
│  1. Extension activates (separate instance)                              │
│  2. mcpServerProvider generates instanceId = "xyz-789"                   │
│  3. Registers MCP server with env: CK3LENS_INSTANCE_ID=xyz-789           │
│  4. User clicks "Initialize ck3raven-dev mode"                           │
│  5. Extension writes to ~/.ck3raven/agent_mode_xyz-789.json              │
│  6. MCP server reads from agent_mode_xyz-789.json                        │
│  7. Agent operates in ck3raven-dev mode (INDEPENDENT of Window A)        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## BANNED: Static mcp.json

**ALL of these locations are banned:**

| Banned File | Why |
|-------------|-----|
| `.vscode/mcp.json` (in workspace) | Creates duplicate server with instance `default` |
| `%APPDATA%\Code\User\mcp.json` | Same problem, affects all workspaces |
| `mcp.servers` block in User Settings | Deprecated - VS Code warns against this |

**How to identify the problem:** If you see `mcp_ck3lens_*` tools with instance `default`, a static config exists somewhere.

If any of these exist with a ck3lens server definition:
- **DELETE IT** immediately
- It overrides the dynamic provider
- All windows will share one server definition
- Instance isolation will be broken

**Required User Setting:**
```json
"chat.mcp.discovery.enabled": true
```

This setting enables VS Code to discover extension-provided MCP servers.

### How to Check

```powershell
# Check if static mcp.json exists with ck3lens
Get-Content "$env:APPDATA\Code\User\mcp.json" 2>$null | Select-String "ck3lens"
```

If output shows ck3lens, the file needs to be removed/renamed.

---

## Troubleshooting

### Symptom: Mode changes in one window affect another

**Cause:** Static mcp.json is being used instead of dynamic provider

**Fix:**
1. Check `%APPDATA%\Code\User\mcp.json` - remove ck3lens entries
2. Reload VS Code windows
3. Verify each window has different instance ID in MCP server logs

### Symptom: CK3LENS_INSTANCE_ID is empty or "default"

**Cause:** Dynamic provider not working

**Fix:**
1. Verify `mcpServerDefinitionProviders` in package.json
2. Check extension activation logs for errors
3. Ensure VS Code version >= 1.96.0

### Symptom: MCP server not starting

**Cause:** Various

**Diagnostics:**
```powershell
# Check if extension registered the provider
# Look in Output > CK3 Lens for "MCP server provider registered"

# Check MCP server logs
Get-Content "$env:USERPROFILE\.ck3raven\mcp_server.log" -Tail 50
```

---

## File Locations Summary

| Component | Path |
|-----------|------|
| Extension activation | `tools/ck3lens-explorer/src/extension.ts` |
| MCP provider registration | `tools/ck3lens-explorer/src/mcp/mcpServerProvider.ts` |
| Package contribution | `tools/ck3lens-explorer/package.json` |
| Mode file pattern | `~/.ck3raven/agent_mode_{instanceId}.json` |
| MCP server entry | `tools/ck3lens_mcp/server.py` |
| Mode logic | `tools/ck3lens_mcp/ck3lens/agent_mode.py` |

---

## For Agents: DO NOT

1. **DO NOT** create or resurrect `%APPDATA%\Code\User\mcp.json`
2. **DO NOT** read/write to `agent_mode.json` without instance ID
3. **DO NOT** assume mode state is shared across windows
4. **DO NOT** use `enabledApiProposals` for this API (it's stable)

## For Agents: DO

1. **DO** check `CK3LENS_INSTANCE_ID` environment variable
2. **DO** use `agent_mode_{instanceId}.json` pattern
3. **DO** log the instance ID for debugging
4. **DO** fail loudly if instance ID is missing (not silently fallback)

---

## Database Access: Read-Only MCP, Single-Writer Daemon

**As of January 2026, MCP servers connect to SQLite in read-only mode.**

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           QBuilder Daemon                                │
│  - Holds exclusive writer lock                                          │
│  - Opens DB in read-write mode                                          │
│  - Owns: ASTs, symbols, refs, diagnostics, conflicts, build_queue       │
│  - Exposes IPC API on localhost:19876                                   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                          IPC (NDJSON/TCP)
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                        MCP Server (per window)                          │
│  - Opens DB with: sqlite3.connect(f"file:{path}?mode=ro", uri=True)     │
│  - SELECT only - no INSERT/UPDATE/DELETE                                │
│  - Mutations via daemon_client.py IPC calls                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### Why Read-Only?

| Problem | Solution |
|---------|----------|
| Multiple VS Code windows = multiple MCP servers | All use read-only, no contention |
| "Database is locked" errors | Impossible - only daemon writes |
| Partial writes from crashed MCP | Impossible - MCP cannot write |
| Build queue corruption | Queue owned by daemon only |

### MCP Tool Pattern

```python
# ✅ CORRECT - read-only DB, mutations via IPC
db = _get_db()  # Opens with mode=ro
result = db.query(...)  # SELECT only

# If file was changed, notify daemon
from ck3lens.daemon_client import daemon
daemon.notify_file_changed(mod_name, rel_path)

# ❌ WRONG - direct DB write from MCP
db.conn.execute("INSERT INTO symbols ...")  # FAILS: read-only
```

### File Locations

| Component | Path |
|-----------|------|
| Read-only DB API | `tools/ck3lens_mcp/ck3lens/db_api.py` |
| Daemon IPC client | `tools/ck3lens_mcp/ck3lens/daemon_client.py` |
| Daemon IPC server | `qbuilder/ipc_server.py` |
| Writer lock | `qbuilder/writer_lock.py` |
| Full spec | `docs/SINGLE_WRITER_ARCHITECTURE.md` |

---

## Related Documents

| Document | Purpose |
|----------|---------|
| [SINGLE_WRITER_ARCHITECTURE.md](SINGLE_WRITER_ARCHITECTURE.md) | Full single-writer spec |
| [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) | Main architecture |
