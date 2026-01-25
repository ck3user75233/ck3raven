# Proposed Canonical Logging Architecture

> **Status:** PROPOSAL  
> **Created:** January 25, 2026  
> **Purpose:** Unified logging for ck3raven infrastructure (excluding QBuilder)

---

## Problem Statement

Current logging is fragmented:

| Component | Current Approach | Problems |
|-----------|-----------------|----------|
| MCP Server | `trace.log()` to JSONL | No structured categories, no levels |
| VS Code Extension | `Logger` class to Output Channel | Not persisted, lost on reload |
| Contract System | Inline `trace.log()` calls | Mixed with other trace events |
| Session/Mode | No logging | Invisible state changes |

**Key Issues:**
1. **No unified log file** for debugging cross-component issues
2. **Extension logs lost on reload** - can't debug deactivate() behavior
3. **No log levels** - can't filter DEBUG vs INFO vs ERROR
4. **No categories** - can't isolate MCP vs Extension vs Contract events
5. **QBuilder has its own logging** (correct) but other components don't

---

## Scope

### IN SCOPE (This Proposal)
- MCP Server (`tools/ck3lens_mcp/`)
- VS Code Extension (`tools/ck3lens-explorer/`)
- Contract System
- Session/Mode management
- Policy enforcement

### OUT OF SCOPE (Separate System)
- QBuilder daemon (`builder/`) - has its own `daemon.log`
- Database operations - use QBuilder logging
- Parser internals - use Python logging

---

## Proposed Architecture

### 1. Log File Location

```
~/.ck3raven/logs/
├── ck3lens.log           # Main unified log (current day)
├── ck3lens.log.1         # Previous day (rotated)
├── ck3lens.log.2         # 2 days ago
├── extension.log         # VS Code extension (persisted)
└── daemon.log            # QBuilder (existing, unchanged)
```

### 2. Log Format

**JSONL format** (one JSON object per line):

```json
{"ts": "2026-01-25T14:32:01.234Z", "level": "INFO", "cat": "mcp.init", "inst": "kiak", "msg": "Mode initialized", "data": {"mode": "ck3raven-dev"}}
{"ts": "2026-01-25T14:32:01.456Z", "level": "DEBUG", "cat": "contract", "inst": "kiak", "msg": "Contract opened", "data": {"contract_id": "c-abc123"}}
{"ts": "2026-01-25T14:32:02.789Z", "level": "ERROR", "cat": "mcp.tool", "inst": "kiak", "msg": "Tool failed", "data": {"tool": "ck3_file", "error": "Path not found"}}
```

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `ts` | ISO8601 | Timestamp with milliseconds |
| `level` | string | DEBUG, INFO, WARN, ERROR |
| `cat` | string | Category (dot-separated hierarchy) |
| `inst` | string | Instance ID (for multi-window isolation) |
| `msg` | string | Human-readable message |
| `data` | object | Structured context (optional) |

### 3. Log Levels

| Level | When to Use |
|-------|-------------|
| `DEBUG` | Detailed diagnostic info, function entry/exit, state dumps |
| `INFO` | Normal operations: mode changes, tool calls, contract lifecycle |
| `WARN` | Recoverable issues: fallback behavior, deprecated usage |
| `ERROR` | Failures: tool errors, policy denials, exceptions |

### 4. Categories

Hierarchical dot-separated categories:

```
mcp.init          # MCP server initialization
mcp.tool          # Tool invocations
mcp.dispose       # Server shutdown/disposal

ext.activate      # Extension activation
ext.deactivate    # Extension deactivation
ext.mcp           # MCP registration/disposal

contract.open     # Contract opened
contract.close    # Contract closed
contract.cancel   # Contract cancelled

session.mode      # Mode changes
session.playset   # Playset changes

policy.enforce    # Policy enforcement decisions
policy.token      # Token requests/validation
```

### 5. Implementation

#### Python (MCP Server)

```python
# tools/ck3lens_mcp/ck3lens/logging.py

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

_LOG_DIR = Path.home() / ".ck3raven" / "logs"
_LOG_FILE = _LOG_DIR / "ck3lens.log"
_INSTANCE_ID = os.environ.get("CK3LENS_INSTANCE_ID", "default")

def _ensure_log_dir():
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

def log(level: str, category: str, msg: str, data: dict[str, Any] | None = None):
    """Write structured log entry."""
    _ensure_log_dir()
    
    entry = {
        "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "level": level,
        "cat": category,
        "inst": _INSTANCE_ID,
        "msg": msg,
    }
    if data:
        entry["data"] = data
    
    with open(_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def debug(category: str, msg: str, **data): log("DEBUG", category, msg, data or None)
def info(category: str, msg: str, **data): log("INFO", category, msg, data or None)
def warn(category: str, msg: str, **data): log("WARN", category, msg, data or None)
def error(category: str, msg: str, **data): log("ERROR", category, msg, data or None)
```

**Usage:**
```python
from ck3lens.logging import info, debug, error

info("mcp.init", "Mode initialized", mode="ck3raven-dev")
debug("contract.open", "Opening contract", intent="Fix bug")
error("mcp.tool", "Tool failed", tool="ck3_file", error=str(e))
```

#### TypeScript (Extension)

```typescript
// tools/ck3lens-explorer/src/utils/structuredLogger.ts

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

const LOG_DIR = path.join(os.homedir(), '.ck3raven', 'logs');
const LOG_FILE = path.join(LOG_DIR, 'extension.log');

interface LogEntry {
    ts: string;
    level: 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';
    cat: string;
    inst: string;
    msg: string;
    data?: Record<string, unknown>;
}

export class StructuredLogger {
    private instanceId: string;
    
    constructor(instanceId: string) {
        this.instanceId = instanceId;
        fs.mkdirSync(LOG_DIR, { recursive: true });
    }
    
    private write(entry: LogEntry): void {
        fs.appendFileSync(LOG_FILE, JSON.stringify(entry) + '\n');
    }
    
    log(level: LogEntry['level'], category: string, msg: string, data?: Record<string, unknown>): void {
        this.write({
            ts: new Date().toISOString(),
            level,
            cat: category,
            inst: this.instanceId,
            msg,
            ...(data && { data })
        });
    }
    
    debug(cat: string, msg: string, data?: Record<string, unknown>) { this.log('DEBUG', cat, msg, data); }
    info(cat: string, msg: string, data?: Record<string, unknown>) { this.log('INFO', cat, msg, data); }
    warn(cat: string, msg: string, data?: Record<string, unknown>) { this.log('WARN', cat, msg, data); }
    error(cat: string, msg: string, data?: Record<string, unknown>) { this.log('ERROR', cat, msg, data); }
}
```

**Usage:**
```typescript
const structuredLog = new StructuredLogger(instanceId);

structuredLog.info('ext.activate', 'Extension activating');
structuredLog.debug('ext.mcp', 'Registering MCP provider', { instanceId });
structuredLog.info('ext.deactivate', 'Extension deactivating');
```

### 6. Log Rotation

**Daily rotation with 7-day retention:**

```python
# Called on MCP server startup
def rotate_logs():
    """Rotate logs if current log is from a previous day."""
    if not _LOG_FILE.exists():
        return
    
    log_mtime = datetime.fromtimestamp(_LOG_FILE.stat().st_mtime)
    if log_mtime.date() < datetime.now().date():
        # Rotate existing logs
        for i in range(6, 0, -1):
            old = _LOG_DIR / f"ck3lens.log.{i}"
            new = _LOG_DIR / f"ck3lens.log.{i+1}"
            if old.exists():
                if i == 6:
                    old.unlink()  # Delete oldest
                else:
                    old.rename(new)
        
        _LOG_FILE.rename(_LOG_DIR / "ck3lens.log.1")
```

### 7. Reading Logs

**MCP Tool: `ck3_logs` enhancement**

Add support for querying the new structured logs:

```python
@mcp.tool()
def ck3_logs(
    source: Literal["error", "game", "debug", "crash", "ck3lens"] = "error",
    # ... existing params ...
    category: str | None = None,  # Filter by category prefix
    level: str | None = None,     # Filter by level
    instance: str | None = None,  # Filter by instance ID
):
    if source == "ck3lens":
        return _query_structured_log(category, level, instance, limit)
```

### 8. Migration Path

**Phase 1: Add new logging (non-breaking)**
1. Create `ck3lens/logging.py` with proposed API
2. Create `structuredLogger.ts` for extension
3. Add logs to key lifecycle points (init, dispose, contract open/close)

**Phase 2: Instrument key paths**
1. MCP tool entry/exit
2. Contract lifecycle
3. Policy enforcement
4. Extension activate/deactivate

**Phase 3: Enhance ck3_logs tool**
1. Add `source="ck3lens"` support
2. Add category/level filters
3. Add log rotation on startup

---

## Key Logging Points

### MCP Server

| Event | Category | Level | Data |
|-------|----------|-------|------|
| Server starting | `mcp.init` | INFO | `{instance_id}` |
| Mode set | `session.mode` | INFO | `{mode, previous}` |
| Tool called | `mcp.tool` | DEBUG | `{tool, params}` |
| Tool succeeded | `mcp.tool` | DEBUG | `{tool, result_size}` |
| Tool failed | `mcp.tool` | ERROR | `{tool, error}` |
| Server disposing | `mcp.dispose` | INFO | `{instance_id}` |

### Extension

| Event | Category | Level | Data |
|-------|----------|-------|------|
| Activate start | `ext.activate` | INFO | `{version}` |
| MCP registration | `ext.mcp` | INFO | `{instance_id}` |
| MCP registration failed | `ext.mcp` | ERROR | `{error}` |
| Deactivate start | `ext.deactivate` | INFO | - |
| MCP disposal | `ext.mcp` | DEBUG | `{instance_id}` |
| Deactivate complete | `ext.deactivate` | INFO | - |

### Contracts

| Event | Category | Level | Data |
|-------|----------|-------|------|
| Contract opened | `contract.open` | INFO | `{contract_id, intent}` |
| Contract closed | `contract.close` | INFO | `{contract_id, commit}` |
| Contract cancelled | `contract.cancel` | INFO | `{contract_id, reason}` |

---

## Relationship to Existing Systems

| System | Purpose | Log Location |
|--------|---------|--------------|
| `trace.log` (JSONL) | MCP tool audit trail | `~/.ck3raven/ck3lens_trace.jsonl` |
| `daemon.log` | QBuilder operations | `~/.ck3raven/daemon/daemon.log` |
| **NEW: ck3lens.log** | Cross-component debugging | `~/.ck3raven/logs/ck3lens.log` |
| **NEW: extension.log** | Extension lifecycle | `~/.ck3raven/logs/extension.log` |

**Trace vs Log:**
- `trace.log` = Audit trail (what tools were called, for policy validation)
- `ck3lens.log` = Debugging (detailed state changes, errors, diagnostics)

Both are complementary, not replacements.

---

## Open Questions

1. **Should extension.log be separate or merged into ck3lens.log?**
   - Separate: Easier to isolate extension issues
   - Merged: Single file to search for cross-component issues

2. **Log level configuration?**
   - Environment variable: `CK3LENS_LOG_LEVEL=DEBUG`
   - Config file: `~/.ck3raven/config.json`
   - VS Code setting: `ck3lens.logLevel`

3. **Should we add log viewing to the extension UI?**
   - Could add "View Logs" command that opens log file
   - Could add log viewer webview panel

---

## QBuilder Logging (OUT OF SCOPE)

QBuilder daemon logging is **not documented** in existing qbuilder docs. It uses:

| File | Destination | Purpose |
|------|-------------|---------|
| `builder/daemon.py` | `~/.ck3raven/daemon/daemon.log` | Daemon lifecycle, phase progress |
| `builder/daemon.py` | `~/.ck3raven/qbuilder_build.log` | Build run details |

This proposal leaves QBuilder logging as-is. A separate effort should document QBuilder logging in `docs/QBUILDER_LOGGING.md` if needed.

---

## Appendix: Current Logging Inventory

**All existing logging events in ck3raven (excluding QBuilder `builder/` directory).**

Use this inventory to plan migration to the new structured logging.

### A. MCP Server - Trace Log (`trace.log()`)

**Destination:** `~/.ck3raven/ck3lens_trace.jsonl`

| File | Line | Event Name | Purpose |
|------|------|------------|---------|
| `tools/ck3lens_mcp/server.py` | 807 | `ck3lens.close_db` | DB connection closed successfully |
| `tools/ck3lens_mcp/server.py` | 814 | `ck3lens.close_db` | DB close failed |
| `tools/ck3lens_mcp/server.py` | 854 | `ck3lens.db.status` | DB status query |
| `tools/ck3lens_mcp/server.py` | 875 | `ck3lens.db.disable` | DB disabled for maintenance |
| `tools/ck3lens_mcp/server.py` | 880 | `ck3lens.db.enable` | DB re-enabled |
| `tools/ck3lens_mcp/server.py` | 1136-1293 | `ck3lens.db_delete` | DB delete operations (8 call sites) |
| `tools/ck3lens_mcp/server.py` | 1332 | `ck3lens.get_policy_status` | Policy health check |
| `tools/ck3lens_mcp/server.py` | 1421 | `ck3lens.logs` | Log query |
| `tools/ck3lens_mcp/server.py` | 1538 | `ck3lens.conflicts.symbols` | Symbol conflicts query |
| `tools/ck3lens_mcp/server.py` | 1593 | `ck3lens.conflicts.files` | File conflicts query |
| `tools/ck3lens_mcp/server.py` | 1647 | `ck3lens.conflicts.summary` | Conflict summary |
| `tools/ck3lens_mcp/server.py` | 2655 | `ck3lens.repair` | Repair query |
| `tools/ck3lens_mcp/server.py` | 2665 | `ck3lens.repair` | Launcher diagnosis |
| `tools/ck3lens_mcp/server.py` | 2682 | `ck3lens.repair` | Launcher backup |
| `tools/ck3lens_mcp/server.py` | 2749 | `ck3lens.repair` | Cache delete |
| `tools/ck3lens_mcp/server.py` | 2842 | `ck3lens.repair` | Path migration |
| `tools/ck3lens_mcp/server.py` | 3095 | `ck3lens.contract.open` | Contract opened |
| `tools/ck3lens_mcp/server.py` | 3207 | `ck3lens.contract.close` | Contract closed |
| `tools/ck3lens_mcp/server.py` | 3232 | `ck3lens.contract.cancel` | Contract cancelled |
| `tools/ck3lens_mcp/server.py` | 3322 | `ck3lens.contract.flush` | Old contracts archived |
| `tools/ck3lens_mcp/server.py` | 3334 | `ck3lens.contract.archive_legacy` | Legacy contracts archived |
| `tools/ck3lens_mcp/server.py` | 3548 | `ck3lens.exec.sandbox_start` | Shell command execution |
| `tools/ck3lens_mcp/server.py` | 3905 | `ck3lens.token.issue` | Token issued |
| `tools/ck3lens_mcp/server.py` | 3966 | `ck3lens.token.revoke` | Token revoked |
| `tools/ck3lens_mcp/server.py` | 4105 | `ck3lens.search` | Symbol/content search |
| `tools/ck3lens_mcp/server.py` | 4187 | `ck3lens.grep_raw` | Raw grep start |
| `tools/ck3lens_mcp/server.py` | 4243 | `ck3lens.grep_raw.result` | Raw grep result |
| `tools/ck3lens_mcp/server.py` | 4317 | `ck3lens.file_search` | File search start |
| `tools/ck3lens_mcp/server.py` | 4341 | `ck3lens.file_search.result` | File search result |
| `tools/ck3lens_mcp/server.py` | 4402 | `ck3lens.parse_content` | Parse CK3 content |
| `tools/ck3lens_mcp/server.py` | 4469 | `ck3lens.report_validation_issue` | Validation issue reported |
| `tools/ck3lens_mcp/server.py` | 4537 | `ck3lens.get_agent_briefing` | Agent briefing fetched |
| `tools/ck3lens_mcp/server.py` | 4628 | `ck3lens.search_mods` | Mod search |
| `tools/ck3lens_mcp/server.py` | 4735 | `ck3lens.mode_initialized` | Agent mode set |
| `tools/ck3lens_mcp/server.py` | 5354 | `ck3_qbuilder.status` | QBuilder status |
| `tools/ck3lens_mcp/server.py` | 5387 | `ck3_qbuilder.build` | QBuilder build started |
| `tools/ck3lens_mcp/server.py` | 5433 | `ck3_qbuilder.discover` | QBuilder discovery |

### B. MCP Server - Unified Tools Trace

| File | Line | Event Name | Purpose |
|------|------|------------|---------|
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 699 | `ck3lens.file.get` | Get file from DB |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 737 | `ck3lens.file.read` | Read file from FS |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 798 | `ck3lens.file.read_live` | Read live mod file |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 819 | `ck3lens.file.write` | Write file (policy deny) |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 856 | `ck3lens.file.write` | Write file (success) |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 903 | `ck3lens.file.write_raw` | Raw file write |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 974 | `ck3lens.file.edit_raw` | Raw file edit |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1046 | `ck3lens.file.edit` | File edit |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1085 | `ck3lens.file.delete` | File delete |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1139 | `ck3lens.file.rename` | File rename |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1168 | `ck3lens.file.refresh` | File refresh |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1221 | `ck3lens.file.list` | List files |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1254 | `ck3lens.file.delete_raw` | Raw file delete |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1281 | `ck3lens.file.rename_raw` | Raw file rename |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1321 | `ck3lens.file.list_raw` | Raw file list |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1445 | `ck3lens.file.create_patch` | Create override patch |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1655 | `ck3lens.folder.list` | List folder |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1741 | `ck3lens.folder.contents` | Folder contents from DB |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1776 | `ck3lens.folder.top_level` | Top-level folders |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1797 | `ck3lens.folder.mod_folders` | Mod folders |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2205 | `ck3lens.git.safe_push_autogrant` | Git push auto-granted |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2222 | `ck3lens.git.*` | Git command (ck3raven) |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2274 | `ck3lens.git.*` | Git command (mod) |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2349 | `ck3lens.validate.syntax` | Syntax validation |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2403 | `ck3lens.validate.python` | Python validation (OK) |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2408 | `ck3lens.validate.python` | Python validation (fail) |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2436 | `ck3lens.validate.references` | Reference validation |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2463 | `ck3lens.validate.bundle` | Bundle validation |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2564 | `ck3lens.vscode.ping` | VS Code IPC ping |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2572 | `ck3lens.vscode.diagnostics` | VS Code diagnostics |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2583 | `ck3lens.vscode.all_diagnostics` | All VS Code diagnostics |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2591 | `ck3lens.vscode.errors_summary` | VS Code errors summary |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2600 | `ck3lens.vscode.validate_file` | VS Code file validation |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2607 | `ck3lens.vscode.open_files` | VS Code open files |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2614 | `ck3lens.vscode.active_file` | VS Code active file |

### C. MCP Server - Python Standard Logging

**Destination:** `stderr` (not persisted)

| File | Line | Level | Purpose |
|------|------|-------|---------|
| `tools/ck3lens_mcp/server.py` | 159 | WARN | Session cache issue |
| `tools/ck3lens_mcp/server.py` | 203 | WARN | Playset detection issue |
| `tools/ck3lens_mcp/ck3lens/daemon_client.py` | 43 | (logger) | Daemon client module |
| `tools/ck3lens_mcp/ck3lens/db_api.py` | 279 | WARN | Mutation query in read-only mode |
| `tools/ck3lens_mcp/ck3lens/runtime_env.py` | 40 | (logger) | Runtime environment module |
| `tools/ck3lens_mcp/ck3lens/runtime_env.py` | 89 | WARN | CWD fallback warning |
| `tools/ck3lens_mcp/ck3lens/workspace.py` | 55 | (logger) | Workspace module |
| `tools/ck3lens_mcp/ck3lens/workspace.py` | 184 | WARN | JSON parse failure |
| `tools/ck3lens_mcp/ck3lens/workspace.py` | 187 | WARN | Config load failure |
| `tools/ck3lens_mcp/ck3lens/workspace.py` | 255 | WARN | Config load error |
| `tools/ck3lens_mcp/ck3lens/workspace.py` | 283 | WARN | Playset file not found |
| `tools/ck3lens_mcp/ck3lens/world_router.py` | 49 | (logger) | World router module |
| `tools/ck3lens_mcp/ck3lens/world_router.py` | 157 | WARN | Resolution fallback |
| `tools/ck3lens_mcp/ck3lens/world_router.py` | 163 | INFO | Resolution success |

### D. MCP Server - Policy Audit Trail

| File | Line | Event Name | Purpose |
|------|------|------------|---------|
| `tools/ck3lens_mcp/ck3lens/policy/audit.py` | 197 | `policy.operation_start` | Operation beginning |
| `tools/ck3lens_mcp/ck3lens/policy/audit.py` | 212 | `policy.enforcement_result` | Enforcement decision |
| `tools/ck3lens_mcp/ck3lens/policy/audit.py` | 237 | `policy.validation_result` | Validation result |
| `tools/ck3lens_mcp/ck3lens/policy/audit.py` | 261 | `policy.operation_complete` | Operation finished |

### E. VS Code Extension - Logger Output Channel

**Destination:** "CK3 Lens" Output Channel (not persisted to disk)

#### extension.ts (Core Lifecycle)

| Line | Level | Purpose |
|------|-------|---------|
| 86 | INFO | Cleaned up stale mode files |
| 89 | DEBUG | Mode file cleanup error |
| 100 | INFO | Extension activating |
| 120 | INFO | MCP instance ID |
| 132 | INFO | Blanked agent mode |
| 134 | ERROR | Failed to blank agent mode |
| 244 | INFO | IPC server started |
| 246 | ERROR | IPC server start failed |
| 270 | INFO | Token watcher started |
| 272 | DEBUG | Token watcher skipped |
| 275 | INFO | Extension activated |
| 282 | INFO | Auto-initializing session |
| 285 | ERROR | Auto-init failed |
| 324 | ERROR | Session init failed |
| 485 | ERROR | Database rebuild failed |
| 651 | ERROR | Navigation failed |
| 693 | ERROR | Conflict detail failed |
| 1029 | DEBUG | DB cleanup skipped (no Python) |
| 1047 | INFO | Running DB cleanup |
| 1055 | INFO | DB cleanup result |
| 1058 | DEBUG | DB cleanup stderr |
| 1061 | DEBUG | DB cleanup failed |

#### mcpServerProvider.ts (MCP Registration)

| Line | Level | Purpose |
|------|-------|---------|
| 79 | DEBUG | Using configured Python |
| 86-93 | DEBUG | Using venv Python |
| 98-102 | ERROR | No Python found (FATAL) |
| 114 | DEBUG | Using configured ck3ravenPath |
| 125-165 | DEBUG | Found ck3raven root (various paths) |
| 170 | INFO | Could not find ck3raven root |
| 194 | INFO | MCP provider initialized |
| 201 | INFO | Configuration changed |
| 217-229 | INFO | Cannot provide MCP server (various reasons) |
| 248 | DEBUG | Injected venv into PATH |
| 259-263 | INFO/DEBUG | Providing MCP server |
| 278 | ERROR | Failed to create McpStdioServerDefinition |
| 331 | ERROR | MCP API not available |
| 357-358 | INFO | MCP provider registered |
| 363 | ERROR | MCP registration failed |

#### session.ts (Session Operations)

| Line | Level | Purpose |
|------|-------|---------|
| 108 | INFO | Initializing session |
| 125 | INFO | Session initialized |
| 129 | ERROR | Session init failed |
| 152-655 | ERROR | Various operation failures (15 error handlers) |

#### pythonBridge.ts (Python Process)

| Line | Level | Purpose |
|------|-------|---------|
| 46-47 | INFO | Config paths |
| 67-75 | INFO | Dev mode bridge found |
| 108-109 | WARN | Configured path doesn't exist |
| 122 | INFO | Auto-detected venv Python |
| 128-131 | ERROR | No Python found (FATAL) |
| 138 | ERROR | Python path invalid |
| 142-144 | INFO | Starting Python bridge |
| 163 | ERROR | Python stderr |
| 167 | ERROR | Python process error |
| 172 | INFO | Python process exited |
| 205 | ERROR | Python process failed to start |
| 233 | DEBUG | Non-JSON output |
| 255 | DEBUG | Notification |
| 284 | DEBUG | Sent request |

#### agentView.ts (Agent State)

| Line | Level | Purpose |
|------|-------|---------|
| 203 | INFO | MCP tools refreshed |
| 244 | DEBUG | MCP check |
| 246 | ERROR | MCP status check error |
| 259 | INFO | MCP disconnected |
| 275 | INFO | Restored agents from storage |
| 351 | INFO | Watching mode file |
| 376 | ERROR | Mode file load failed |
| 398 | ERROR | Trace directory creation failed |
| 412 | INFO | Watching trace file |
| 426 | DEBUG | Skipping trace check (startup delay) |
| 494 | INFO | Re-checking MCP status |
| 700 | INFO | All agents cleared |
| 723 | INFO | Agent initialized (default mode) |
| 817 | INFO | Agent mode changed |
| 835 | INFO | Agent created |

#### diagnosticsServer.ts (IPC Server)

| Line | Level | Purpose |
|------|-------|---------|
| 60 | INFO | IPC port in use, trying next |
| 64 | ERROR | IPC server error |
| 72 | INFO | IPC server listening |
| 96 | DEBUG | Wrote IPC port file |
| 98 | ERROR | Port file write failed |
| 107 | DEBUG | IPC client connected |
| 143 | DEBUG | IPC client disconnected |
| 147 | ERROR | IPC socket error |

#### Other Extension Files

| File | Lines | Purpose |
|------|-------|---------|
| `lensWidget.ts` | 117-700 | Widget state, agent init, debug trace |
| `statusBar.ts` | 46 | Status bar initialized |
| `lintingProvider.ts` | 269-272 | Lint results and errors |
| `definitionProvider.ts` | 30-51 | Definition lookup |
| `referenceProvider.ts` | 31-61 | Reference lookup |
| `hoverProvider.ts` | 58 | Hover lookup failed |
| `completionProvider.ts` | 60 | Completion failed |
| `conflictsView.ts` | 96 | Conflicts load failed |
| `explorerView.ts` | 187 | Get children failed |
| `issuesView.ts` | 123-181 | Issues/errors/conflicts load |
| `playsetView.ts` | 107-194 | Mod reorder, playset load |
| `studioPanel.ts` | 546-658 | File creation, copy from vanilla |
| `symbolsView.ts` | 137 | Symbols load failed |
| `astViewerPanel.ts` | 128-210 | AST viewer operations |

### F. Core Library - Python Logging

**Destination:** `stderr` (Python logging, not persisted)

| File | Line | Level | Purpose |
|------|------|-------|---------|
| `src/ck3raven/db/ast_cache.py` | 20 | (logger) | AST cache module |
| `src/ck3raven/db/cleanup.py` | 15 | (logger) | Cleanup module |
| `src/ck3raven/db/cleanup.py` | 238 | INFO | Cleanup stats |
| `src/ck3raven/db/symbols.py` | 30 | (logger) | Symbols module |
| `src/ck3raven/db/symbols.py` | 895-1152 | INFO/WARN/DEBUG | Symbol/ref extraction progress |
| `src/ck3raven/db/work_detection.py` | 30 | (logger) | Work detection module |
| `src/ck3raven/db/work_detection.py` | 161 | WARN | Error reading file |
| `src/ck3raven/db/work_detection.py` | 611 | INFO | Insufficient samples |
| `src/ck3raven/emulator/builder.py` | 27 | (logger) | Emulator builder module |
| `src/ck3raven/emulator/builder.py` | 181-248 | INFO/WARN/DEBUG | Game state building |

---

## Next Steps

1. Review and approve this proposal
2. Implement Phase 1 (logging infrastructure)
3. Add logging to MCP disposal path (immediate need)
4. Incrementally instrument other components
