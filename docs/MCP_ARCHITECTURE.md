# MCP Server Architecture

> **Status:** AUTHORITATIVE  
> **Last Updated:** January 31, 2026  
> **Purpose:** Lock in the per-instance MCP server architecture to prevent drift

---

## Changelog

| Date | Changes |
|------|---------|
| 2026-01-31 | Added Diagnostic Logging section (canonical). Logging is now part of MCP lifecycle correctness. |
| 2026-01-31 | Added Lifecycle & Zombie Prevention (canonical). Added Python EOF exit requirement. Resolved enabledApiProposals contradiction. Documented mode blanking behavior. Fixed stale references. |
| 2026-01-17 | Initial per-instance architecture documentation. |

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

## Lifecycle & Zombie Prevention (CANONICAL)

**Status: NON-NEGOTIABLE. These requirements prevent zombie MCP processes.**

The "zombie bug" occurred when VS Code reloads cached stale MCP connections, causing:
- Duplicate tool catalogs
- Old Python processes that never exit
- Memory leaks and process accumulation

### Canonical Requirements

#### 1. Fresh Instance ID Every Activation

**MUST** generate a fresh `CK3LENS_INSTANCE_ID` on every extension activation.

```typescript
// ✅ CORRECT - Fresh random ID every activation
function generateInstanceId(): string {
    const timestamp = Date.now().toString(36).slice(-4);
    const random = crypto.randomBytes(3).toString('hex');
    return `${timestamp}-${random}`;
}

// ❌ WRONG - PID-based or globalState caching
// This causes VS Code to see "same server" and cache connection
const cachedId = context.globalState.get('instanceId');
```

**Why:** If instance ID is stable across reloads, VS Code's MCP system thinks it's the "same server" and caches the connection, preventing proper cleanup.

#### 2. Stable Server Label

**MUST** use a stable label (e.g., "CK3 Lens") that does NOT include the instance ID.

```typescript
// ✅ CORRECT - Stable label
const serverName = 'CK3 Lens';

// ❌ WRONG - Dynamic label with instance ID
const serverName = `CK3 Lens (${instanceId})`;
```

**Why:** VS Code derives server identity from `<extensionId>/<label>`. If label changes, VS Code treats it as a NEW server while still caching the old one → zombies.

#### 3. Provider Shutdown Method

**MUST** implement `shutdown()` that:
1. Sets `isShutdown = true`
2. Fires `onDidChangeMcpServerDefinitions` event
3. Returns `[]` from `provideMcpServerDefinitions()` when `isShutdown` is true

```typescript
class CK3LensMcpServerProvider {
    private isShutdown: boolean = false;
    
    provideMcpServerDefinitions(): McpStdioServerDefinition[] {
        if (this.isShutdown) {
            return [];  // Tell VS Code: no servers available
        }
        return [/* normal definition */];
    }
    
    shutdown(): void {
        this.isShutdown = true;
        this._onDidChangeDefinitions.fire();  // Force VS Code to re-query
    }
}
```

**Why:** VS Code must see empty definitions BEFORE the provider is disposed, otherwise it caches the stale connection.

#### 4. Deactivation Sequence

**MUST** follow this exact sequence in `deactivate()`:

```typescript
export async function deactivate(): Promise<void> {
    // Step 1: Dispose registration (unregisters from VS Code API)
    mcpRegistration?.dispose();
    
    // Step 2: Call shutdown() - sets isShutdown=true and fires change event
    mcpServerProvider?.shutdown();
    
    // Step 3: Yield one tick (gives VS Code event loop opportunity)
    await new Promise(resolve => setTimeout(resolve, 0));
    
    // Step 4: Dispose provider (cleans up resources)
    mcpServerProvider?.dispose();
}
```

**Why:** The yield tick is critical - VS Code needs an event loop opportunity to observe the empty definitions before we fully dispose.

#### 5. Python Server EOF Exit

**MUST** exit cleanly when stdin reaches EOF.

```python
# In server.py main block
try:
    mcp.run()
except EOFError:
    print(f"MCP server: stdin EOF detected, shutting down", file=sys.stderr)
finally:
    print(f"MCP server: main loop ended, exiting", file=sys.stderr)
```

**Why:** When VS Code closes the MCP connection, stdin closes. If the Python process doesn't exit, it becomes a zombie.

### Validation Criteria

To verify zombie prevention is working:

1. **Reload 3× test**: Reload VS Code window 3 times. Each activation should show a DIFFERENT instance ID in logs.

2. **No process accumulation**: After 3 reloads, Task Manager should show only ONE python process for the MCP server (not 3).

3. **EOF shutdown logs**: On each reload, the OLD Python process should log "stdin EOF detected, shutting down".

4. **No duplicate tools**: Copilot should show tools from only ONE instance ID, not duplicates.

### Implementation Files

| Component | File |
|-----------|------|
| Instance ID generation | `tools/ck3lens-explorer/src/mcp/mcpServerProvider.ts` |
| Provider shutdown | `tools/ck3lens-explorer/src/mcp/mcpServerProvider.ts` |
| Deactivation sequence | `tools/ck3lens-explorer/src/extension.ts` |
| Python EOF handling | `tools/ck3lens_mcp/server.py` |

---

## Mode Behavior (Separate from Zombie Prevention)

Mode management is related to but distinct from zombie prevention.

### Mode File Blanking on Activation

**On every activation**, the extension blanks the instance's mode file:

```typescript
// extension.ts - in activate()
fs.writeFileSync(instanceModeFile, JSON.stringify({ 
    mode: null, 
    instance_id: instanceId,
    cleared_at: new Date().toISOString() 
}));
```

**Why:** Mode state should NOT persist across reloads. Each session starts fresh and requires explicit mode initialization via `ck3_get_mode_instructions()`.

**This is intentional, not a bug.** Mode persistence would create confusion when the same window is used for different tasks.

### Stale Mode File Cleanup

Mode files older than 24 hours are automatically deleted:

```typescript
// extension.ts - cleanupStaleModeFiles()
const maxAgeMs = 24 * 60 * 60 * 1000; // 24 hours
// Files older than this are deleted
```

**Why:** Over time, orphaned mode files accumulate from crashed windows or development. This hygiene prevents disk clutter.

### Mode Is NOT a Reason for Stable Instance ID

Some might think: "If mode resets on reload, why not keep instance ID stable so mode persists?"

**Answer:** Mode resetting is DESIRABLE. Fresh instance ID prevents zombies, which is more important than mode persistence. Users should explicitly initialize mode each session via the MCP tool.

---

## Architecture Components

### 1. Extension: mcpServerProvider.ts

**Location:** `tools/ck3lens-explorer/src/mcp/mcpServerProvider.ts`

**Responsibility:** Dynamically register MCP server with VS Code

```typescript
// Generates unique instance ID per activation (not per window!)
const instanceId = generateInstanceId();

// Registers dynamic MCP server definition
vscode.lm.registerMcpServerDefinitionProvider('ck3lens', {
    provideMcpServerDefinitions: () => [/* ... */]
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

**NOTE:** As of VS Code 1.96, the `mcpServerDefinitionProvider` API is STABLE. The `enabledApiProposals` field is NOT required in the canonical architecture.

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

### Symptom: Zombie processes after reload

**Cause:** Deactivation sequence not completing properly

**Diagnostics:**
1. Check Output > CK3 Lens for "MCP deactivate: provider.shutdown()" log
2. Check for Python stderr showing "stdin EOF detected"
3. Verify deactivate() follows the 4-step sequence

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
4. **DO NOT** cache instance ID based on PID or globalState
5. **DO NOT** include instance ID in server label

## For Agents: DO

1. **DO** check `CK3LENS_INSTANCE_ID` environment variable
2. **DO** use `agent_mode_{instanceId}.json` pattern
3. **DO** log the instance ID for debugging
4. **DO** fail loudly if instance ID is missing (not silently fallback)
5. **DO** follow the 4-step deactivation sequence exactly

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
| [CANONICAL_LOGS.md](CANONICAL_LOGS.md) | Structured logging architecture |

---

## Diagnostic Logging (CANONICAL)

**Status: NON-NEGOTIABLE. Logging is part of MCP lifecycle correctness.**

Logging is **not cosmetic** and **not developer convenience**.
It is a **diagnostic contract**:

> If MCP lifecycle fails (zombie server, duplicate tools, reload weirdness),
> the system must leave behind enough evidence to reconstruct exactly what happened.

### Canonical Requirements

#### 1. Separate Log Files Per Runtime

**Windows file locking makes shared log files unsafe.**

| Runtime | Log File |
|---------|----------|
| MCP Server (Python) | `~/.ck3raven/logs/ck3raven-mcp.log` |
| VS Code Extension (Node) | `~/.ck3raven/logs/ck3raven-ext.log` |
| QBuilder Daemon | `~/.ck3raven/logs/daemon_YYYY-MM-DD.log` |

Aggregation happens at **read-time** (via `debug_get_logs` tool), never write-time.

#### 2. ISO 8601 UTC Timestamps

All logs **MUST** use:

```
YYYY-MM-DDTHH:MM:SS.mmmZ
```

Example: `2026-01-31T14:32:01.234Z`

This enables chronological interleaving across all log sources without timezone guesswork.

#### 3. Instance ID in Every Entry

Every log entry **MUST** include:

```json
{"inst": "tt79-6f854d", ...}
```

This is critical for:
- Multi-window debugging
- Reload diagnostics
- Zombie detection

#### 4. Trace ID Correlation

Log entries **MUST** support trace ID propagation:

```
UI action → MCP tool → contract/policy → result
```

The `trace_id` field links related events across components.

#### 5. Fail-Safe Behavior

**Logging failures MUST NOT crash the application.**

| Failure | Behavior |
|---------|----------|
| Log directory doesn't exist | Create it; if that fails, use stderr |
| Log file write fails | Fall back to stderr/console |
| stderr write fails | Silently drop (last resort) |

### Relationship: trace.log vs Debug Logs

These are **complementary**, not replacements:

| System | Purpose | Persistence |
|--------|---------|-------------|
| `trace.log()` → `ck3lens_trace.jsonl` | Audit trail (what tools were called) | Session-based |
| `ck3raven-*.log` | Debugging + lifecycle visibility | Persistent (7-day rotation) |

**Do NOT attempt to merge or simplify these systems.**

### What Must Be Logged

#### MCP Server (Python)

| Event | Category | Level |
|-------|----------|-------|
| Server startup | `mcp.init` | INFO |
| Server shutdown | `mcp.dispose` | INFO |
| stdin EOF detection | `mcp.dispose` | INFO |
| Tool invocation start | `mcp.tool` | DEBUG |
| Tool invocation end | `mcp.tool` | DEBUG |
| Tool exception | `mcp.tool` | ERROR |

#### Extension (TypeScript)

| Event | Category | Level |
|-------|----------|-------|
| Extension activate | `ext.activate` | INFO |
| Extension deactivate | `ext.deactivate` | INFO |
| MCP provider registration | `ext.mcp` | INFO |
| MCP provider shutdown | `ext.mcp` | INFO |
| MCP provider dispose | `ext.mcp` | INFO |

### Validation Criteria

After a window reload, the following **MUST** be verifiable from logs:

1. Old MCP server logged stdin EOF shutdown
2. Old extension logged deactivate sequence
3. New extension logged activate with NEW instance ID
4. New MCP server logged startup with NEW instance ID
5. `debug_get_logs` tool can show before/after in one chronological output

### Implementation Files

| Component | File |
|-----------|------|
| Python logging module | `tools/ck3lens_mcp/ck3lens/logging.py` |
| Python log rotation | `tools/ck3lens_mcp/ck3lens/log_rotation.py` |
| TypeScript logger | `tools/ck3lens-explorer/src/utils/structuredLogger.ts` |
| Log aggregator tool | `tools/ck3lens_mcp/server.py` (`debug_get_logs`) |
| Full spec | `docs/CANONICAL_LOGS.md` |
