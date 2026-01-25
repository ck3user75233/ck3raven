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

## Next Steps

1. Review and approve this proposal
2. Implement Phase 1 (logging infrastructure)
3. Add logging to MCP disposal path (immediate need)
4. Incrementally instrument other components
