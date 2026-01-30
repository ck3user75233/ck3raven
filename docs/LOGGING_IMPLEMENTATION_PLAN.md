# Logging Implementation Plan

> **Status:** IMPLEMENTATION PLAN  
> **Created:** January 31, 2026  
> **Based On:** [PROPOSED_CANONICAL_LOGS.md](./PROPOSED_CANONICAL_LOGS.md)  
> **Purpose:** Step-by-step plan to implement unified logging for ck3raven

---

## Executive Summary

This document provides a detailed, phased implementation plan for the canonical logging architecture. The work is divided into 4 phases, each with specific deliverables and verification criteria.

**Total Estimated Effort:** 4-6 hours  
**Risk Level:** Low (additive changes, non-breaking)

---

## Current State Analysis

### MCP Server (`tools/ck3lens_mcp/`)

| Aspect | Current State | Target State |
|--------|---------------|--------------|
| **Trace Logging** | `trace.py` → `ck3lens_trace.jsonl` | Keep (audit trail) |
| **Debug Logging** | None structured | New `ck3raven-mcp.log` |
| **Log Levels** | None | DEBUG/INFO/WARN/ERROR |
| **Categories** | None | Hierarchical (`mcp.init`, `contract.open`, etc.) |
| **Trace ID** | None | Session-wide correlation |

**Current Files:**
- `ck3lens/trace.py` - Tool call audit trail (keep as-is)
- No structured debug logging exists

### VS Code Extension (`tools/ck3lens-explorer/`)

| Aspect | Current State | Target State |
|--------|---------------|--------------|
| **Logger** | `utils/logger.ts` → Output Channel | Keep + add file logging |
| **Persistence** | Lost on reload | New `ck3raven-ext.log` |
| **Categories** | None | Hierarchical (`ext.activate`, etc.) |
| **Trace ID** | None | Cross-component correlation |

**Current Files:**
- `src/utils/logger.ts` - 65 lines, writes to VS Code Output Channel only
- Logs are lost on extension reload/window close

### QBuilder Daemon (`qbuilder/`)

| Aspect | Current State | Target State |
|--------|---------------|--------------|
| **Logging** | `~/.ck3raven/logs/daemon_YYYY-MM-DD.log` | Keep (already separate) |
| **Timestamp Format** | Mixed | Standardize to ISO 8601 UTC |

**No changes needed** except timestamp format standardization.

---

## Phase 1: Python Logging Infrastructure

**Goal:** Create the core Python logging module for MCP server.

### Step 1.1: Create Logging Module

**File:** `tools/ck3lens_mcp/ck3lens/logging.py`

**Action:** Create new file with the following implementation:

```python
#!/usr/bin/env python3
"""
Structured logging for CK3 Lens MCP server.

Writes JSONL to ~/.ck3raven/logs/ck3raven-mcp.log
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Configuration from environment
_LOG_DIR = Path.home() / ".ck3raven" / "logs"
_LOG_FILE = _LOG_DIR / "ck3raven-mcp.log"
_INSTANCE_ID = os.environ.get("CK3LENS_INSTANCE_ID", "default")
_LOG_LEVEL = os.environ.get("CK3LENS_LOG_LEVEL", "INFO").upper()

_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
_initialized = False

# Thread-local trace_id context
_trace_context = threading.local()


def set_trace_id(trace_id: str) -> None:
    """Set trace ID for current operation context."""
    _trace_context.trace_id = trace_id


def get_trace_id() -> str:
    """Get current trace ID or 'no-trace'."""
    return getattr(_trace_context, "trace_id", "no-trace")


def clear_trace_id() -> None:
    """Clear trace ID after operation completes."""
    _trace_context.trace_id = "no-trace"


def _ensure_log_dir() -> None:
    global _initialized
    if not _initialized:
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            _initialized = True
        except Exception:
            pass  # Fail silently - will use stderr fallback


def _should_log(level: str) -> bool:
    return _LEVEL_ORDER.get(level, 1) >= _LEVEL_ORDER.get(_LOG_LEVEL, 1)


def _sanitize(data: dict[str, Any]) -> dict[str, Any]:
    """Remove or mask sensitive data."""
    if not data:
        return data
    sanitized = {}
    for k, v in data.items():
        # Mask potential secrets
        if "key" in k.lower() or "token" in k.lower() or "secret" in k.lower():
            sanitized[k] = "***REDACTED***"
        # Truncate large string values
        elif isinstance(v, str) and len(v) > 1000:
            sanitized[k] = v[:1000] + "...[truncated]"
        else:
            sanitized[k] = v
    return sanitized


def _format_timestamp() -> str:
    """Format timestamp as ISO 8601 UTC with milliseconds."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def log(
    level: str,
    category: str,
    msg: str,
    data: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> None:
    """Write structured log entry with fail-safe behavior."""
    if not _should_log(level):
        return

    _ensure_log_dir()

    entry = {
        "ts": _format_timestamp(),
        "level": level,
        "cat": category,
        "inst": _INSTANCE_ID,
        "trace_id": trace_id or get_trace_id(),
        "msg": msg,
    }
    if data:
        entry["data"] = _sanitize(data)

    line = json.dumps(entry, ensure_ascii=False) + "\n"

    # Fail-safe: try file, fall back to stderr
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        try:
            sys.stderr.write(f"[LOG FALLBACK] {line}")
        except Exception:
            pass  # Last resort: silently drop


def debug(category: str, msg: str, **data: Any) -> None:
    log("DEBUG", category, msg, data or None)


def info(category: str, msg: str, **data: Any) -> None:
    log("INFO", category, msg, data or None)


def warn(category: str, msg: str, **data: Any) -> None:
    log("WARN", category, msg, data or None)


def error(category: str, msg: str, **data: Any) -> None:
    log("ERROR", category, msg, data or None)


def bootstrap(msg: str) -> None:
    """Log during bootstrap phase (before full init). Always writes to stderr."""
    ts = _format_timestamp()
    sys.stderr.write(f"[BOOTSTRAP {ts}] {msg}\n")
```

**Lines:** ~110  
**Verification:**
1. Import in Python REPL: `from ck3lens.logging import info, debug`
2. Call `info("test", "Hello")` and check `~/.ck3raven/logs/ck3raven-mcp.log`

### Step 1.2: Create Log Rotation Utility

**File:** `tools/ck3lens_mcp/ck3lens/log_rotation.py`

**Action:** Create new file:

```python
#!/usr/bin/env python3
"""
Log rotation for ck3raven logs.

Daily rotation with 7-day retention.
"""
from datetime import datetime, timezone
from pathlib import Path


def rotate_if_needed(log_file: Path, max_backups: int = 7) -> bool:
    """
    Rotate log if it's from a previous day.
    
    Args:
        log_file: Path to current log file
        max_backups: Number of backup files to keep
        
    Returns:
        True if rotation occurred, False otherwise
    """
    if not log_file.exists():
        return False
    
    try:
        log_mtime = datetime.fromtimestamp(log_file.stat().st_mtime, tz=timezone.utc)
        today = datetime.now(timezone.utc).date()
        
        if log_mtime.date() >= today:
            return False  # Log is current, no rotation needed
        
        log_dir = log_file.parent
        stem = log_file.stem
        suffix = log_file.suffix
        
        # Rotate existing backups (shift numbers up)
        for i in range(max_backups - 1, 0, -1):
            old = log_dir / f"{stem}{suffix}.{i}"
            new = log_dir / f"{stem}{suffix}.{i + 1}"
            if old.exists():
                if i == max_backups - 1:
                    old.unlink()  # Delete oldest
                else:
                    old.rename(new)
        
        # Rotate current log to .1
        log_file.rename(log_dir / f"{stem}{suffix}.1")
        return True
        
    except Exception:
        return False  # Don't fail startup due to rotation issues
```

**Lines:** ~50  
**Verification:** Unit test with mock files

### Step 1.3: Add Logging to Server Initialization

**File:** `tools/ck3lens_mcp/server.py`

**Location:** Top of file, after imports

**Action:** Add import and initialization logging:

```python
# Add import near top (after other ck3lens imports)
from ck3lens.logging import info, debug, error, bootstrap, set_trace_id
from ck3lens.log_rotation import rotate_if_needed
from pathlib import Path

# Add at start of server initialization (near line 100-150)
# Rotate logs on startup
_LOG_FILE = Path.home() / ".ck3raven" / "logs" / "ck3raven-mcp.log"
rotate_if_needed(_LOG_FILE)

bootstrap("MCP server starting")
```

**Verification:** Restart MCP server, check log file created

### Step 1.4: Add Logging to Key MCP Events

**File:** `tools/ck3lens_mcp/server.py`

**Locations to instrument:**

| Event | Location | Category | Level |
|-------|----------|----------|-------|
| Mode initialization | `ck3_get_mode_instructions()` | `mcp.init` | INFO |
| Tool start | `@mcp_safe_tool` decorator | `mcp.tool` | DEBUG |
| Tool success | `@mcp_safe_tool` decorator | `mcp.tool` | DEBUG |
| Tool error | `@mcp_safe_tool` decorator | `mcp.tool` | ERROR |
| Contract open | `ck3_contract()` | `contract.open` | INFO |
| Contract close | `ck3_contract()` | `contract.close` | INFO |

**Example for `ck3_get_mode_instructions`:**

```python
@mcp.tool()
def ck3_get_mode_instructions(mode: Literal["ck3lens", "ck3raven-dev"]) -> dict:
    """Initialize mode and return instructions."""
    from ck3lens.logging import info
    
    info("mcp.init", "Mode initialization requested", mode=mode)
    # ... existing code ...
    info("mcp.init", "Mode initialized successfully", mode=mode, playset=playset_name)
    return result
```

**Verification:** Call `ck3_get_mode_instructions`, check log entries

---

## Phase 2: TypeScript Logging Infrastructure

**Goal:** Create the structured logger for VS Code extension with file persistence.

### Step 2.1: Create Structured Logger

**File:** `tools/ck3lens-explorer/src/utils/structuredLogger.ts`

**Action:** Create new file:

```typescript
/**
 * Structured logger for CK3 Lens Explorer extension.
 * 
 * Writes JSONL to ~/.ck3raven/logs/ck3raven-ext.log
 * Also mirrors to VS Code Output Channel.
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as vscode from 'vscode';

const LOG_DIR = path.join(os.homedir(), '.ck3raven', 'logs');
const LOG_FILE = path.join(LOG_DIR, 'ck3raven-ext.log');
const MAX_BUFFER_SIZE = 50;
const FLUSH_INTERVAL_MS = 1000;

type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';

interface LogEntry {
    ts: string;
    level: LogLevel;
    cat: string;
    inst: string;
    trace_id: string;
    msg: string;
    data?: Record<string, unknown>;
}

const LEVEL_ORDER: Record<LogLevel, number> = {
    DEBUG: 0,
    INFO: 1,
    WARN: 2,
    ERROR: 3
};

export class StructuredLogger {
    private instanceId: string;
    private outputChannel: vscode.OutputChannel | null;
    private buffer: string[] = [];
    private flushTimer: NodeJS.Timeout | null = null;
    private logLevel: LogLevel = 'INFO';
    private currentTraceId: string = 'no-trace';

    constructor(instanceId: string, outputChannel?: vscode.OutputChannel) {
        this.instanceId = instanceId;
        this.outputChannel = outputChannel || null;

        try {
            fs.mkdirSync(LOG_DIR, { recursive: true });
        } catch {
            // Will use console fallback
        }

        this.flushTimer = setInterval(() => this.flush(), FLUSH_INTERVAL_MS);
    }

    setTraceId(traceId: string): void {
        this.currentTraceId = traceId;
    }

    generateTraceId(): string {
        const id = Math.random().toString(36).substring(2, 10);
        this.currentTraceId = id;
        return id;
    }

    setLevel(level: LogLevel): void {
        this.logLevel = level;
    }

    private shouldLog(level: LogLevel): boolean {
        return LEVEL_ORDER[level] >= LEVEL_ORDER[this.logLevel];
    }

    private sanitize(data?: Record<string, unknown>): Record<string, unknown> | undefined {
        if (!data) return undefined;
        const sanitized: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(data)) {
            if (
                k.toLowerCase().includes('key') ||
                k.toLowerCase().includes('token') ||
                k.toLowerCase().includes('secret')
            ) {
                sanitized[k] = '***REDACTED***';
            } else if (typeof v === 'string' && v.length > 1000) {
                sanitized[k] = v.substring(0, 1000) + '...[truncated]';
            } else {
                sanitized[k] = v;
            }
        }
        return sanitized;
    }

    private write(entry: LogEntry): void {
        const line = JSON.stringify(entry);

        this.buffer.push(line);

        if (this.outputChannel) {
            this.outputChannel.appendLine(`[${entry.level}] ${entry.cat}: ${entry.msg}`);
        }

        if (this.buffer.length >= MAX_BUFFER_SIZE) {
            this.flush();
        }
    }

    flush(): void {
        if (this.buffer.length === 0) return;

        const lines = this.buffer.join('\n') + '\n';
        this.buffer = [];

        try {
            fs.appendFileSync(LOG_FILE, lines);
        } catch {
            console.error('[LOG FALLBACK]', lines);
        }
    }

    log(level: LogLevel, category: string, msg: string, data?: Record<string, unknown>): void {
        if (!this.shouldLog(level)) return;

        this.write({
            ts: new Date().toISOString(),
            level,
            cat: category,
            inst: this.instanceId,
            trace_id: this.currentTraceId,
            msg,
            ...(data && { data: this.sanitize(data) })
        });
    }

    debug(cat: string, msg: string, data?: Record<string, unknown>): void {
        this.log('DEBUG', cat, msg, data);
    }

    info(cat: string, msg: string, data?: Record<string, unknown>): void {
        this.log('INFO', cat, msg, data);
    }

    warn(cat: string, msg: string, data?: Record<string, unknown>): void {
        this.log('WARN', cat, msg, data);
    }

    error(cat: string, msg: string, data?: Record<string, unknown>): void {
        this.log('ERROR', cat, msg, data);
    }

    bootstrap(msg: string): void {
        const ts = new Date().toISOString();
        console.log(`[BOOTSTRAP ${ts}] ${msg}`);
    }

    dispose(): void {
        if (this.flushTimer) {
            clearInterval(this.flushTimer);
            this.flushTimer = null;
        }
        this.flush();
    }
}

// Singleton factory
let _logger: StructuredLogger | null = null;

export function getStructuredLogger(
    instanceId?: string,
    outputChannel?: vscode.OutputChannel
): StructuredLogger {
    if (!_logger && instanceId) {
        _logger = new StructuredLogger(instanceId, outputChannel);
    }
    return _logger!;
}

export function disposeStructuredLogger(): void {
    if (_logger) {
        _logger.dispose();
        _logger = null;
    }
}
```

**Lines:** ~170  
**Verification:** Compile with `npm run compile`, no TypeScript errors

### Step 2.2: Integrate Logger into Extension

**File:** `tools/ck3lens-explorer/src/extension.ts`

**Location:** `activate()` function

**Action:** Replace/augment existing logger usage:

```typescript
import { getStructuredLogger, disposeStructuredLogger, StructuredLogger } from './utils/structuredLogger';

let structuredLogger: StructuredLogger;

export async function activate(context: vscode.ExtensionContext) {
    // Create structured logger first
    const instanceId = generateInstanceId();
    structuredLogger = getStructuredLogger(instanceId, outputChannel);
    
    structuredLogger.info('ext.activate', 'Extension activating', { 
        version: context.extension.packageJSON.version 
    });
    
    // ... existing code ...
    
    structuredLogger.info('ext.activate', 'Extension activated successfully');
}

export async function deactivate() {
    structuredLogger?.info('ext.deactivate', 'Extension deactivating');
    
    // ... existing cleanup ...
    
    structuredLogger?.info('ext.deactivate', 'Extension deactivated');
    disposeStructuredLogger();
}
```

**Verification:** Reload extension, check `~/.ck3raven/logs/ck3raven-ext.log` exists

### Step 2.3: Add MCP Provider Logging

**File:** `tools/ck3lens-explorer/src/mcp/mcpServerProvider.ts` (or equivalent)

**Action:** Log MCP registration and disposal:

```typescript
structuredLogger.info('ext.mcp', 'Registering MCP server provider', { instanceId });

// On disposal:
structuredLogger.info('ext.mcp', 'MCP server disposed', { instanceId });
```

---

## Phase 3: Log Aggregator Tool

**Goal:** Create MCP tool to read and merge logs from all sources.

### Step 3.1: Create Aggregator Tool

**File:** `tools/ck3lens_mcp/server.py`

**Location:** Add new tool near other debug tools

**Action:** Add `debug_get_logs` tool:

```python
@mcp.tool()
def debug_get_logs(
    lines: int = 50,
    level: Literal["DEBUG", "INFO", "WARN", "ERROR"] | None = None,
    category: str | None = None,
    trace_id: str | None = None,
    source: Literal["all", "mcp", "ext", "daemon"] = "all",
) -> dict:
    """
    Get recent logs from all ck3raven components, merged chronologically.
    
    Args:
        lines: Maximum total lines to return (default 50)
        level: Filter by minimum level
        category: Filter by category prefix
        trace_id: Filter by trace ID (for debugging specific operations)
        source: Which log sources to include
    
    Returns:
        Merged, chronologically sorted log entries
    """
    from pathlib import Path
    import json
    
    log_files = {
        "mcp": Path.home() / ".ck3raven" / "logs" / "ck3raven-mcp.log",
        "ext": Path.home() / ".ck3raven" / "logs" / "ck3raven-ext.log",
        "daemon": Path.home() / ".ck3raven" / "logs" / f"daemon_{datetime.now().strftime('%Y-%m-%d')}.log",
    }
    
    level_order = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
    min_level = level_order.get(level or "DEBUG", 0)
    
    entries = []
    sources_found = []
    
    for src, path in log_files.items():
        if source != "all" and source != src:
            continue
        if not path.exists():
            continue
        
        sources_found.append(src)
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line_text in f:
                    try:
                        entry = json.loads(line_text.strip())
                        entry["_source"] = src
                        
                        # Apply level filter
                        entry_level = level_order.get(entry.get("level", "INFO"), 1)
                        if entry_level < min_level:
                            continue
                        
                        # Apply category filter
                        if category and not entry.get("cat", "").startswith(category):
                            continue
                        
                        # Apply trace_id filter
                        if trace_id and entry.get("trace_id") != trace_id:
                            continue
                        
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            continue
    
    # Sort by timestamp
    entries.sort(key=lambda e: e.get("ts", ""))
    
    # Return most recent
    recent = entries[-lines:] if len(entries) > lines else entries
    
    return {
        "entries": recent,
        "total_available": len(entries),
        "truncated": len(entries) > lines,
        "sources_checked": list(log_files.keys()),
        "sources_found": sources_found,
    }
```

**Lines:** ~70  
**Verification:** Call `debug_get_logs()` and get merged results

---

## Phase 4: Instrumentation & Polish

**Goal:** Add logging to remaining key points, ensure QBuilder compatibility.

### Step 4.1: Contract Lifecycle Logging

**File:** `tools/ck3lens_mcp/server.py`

**Tool:** `ck3_contract`

**Action:** Add logging for open/close/cancel:

```python
# In contract open:
info("contract.open", "Contract opened", 
     contract_id=contract_id, intent=intent, root_category=root_category)

# In contract close:
info("contract.close", "Contract closed", 
     contract_id=contract_id, closure_commit=closure_commit)

# In contract cancel:
info("contract.cancel", "Contract cancelled", 
     contract_id=contract_id, reason=cancel_reason)
```

### Step 4.2: Policy Enforcement Logging

**File:** `tools/ck3lens_mcp/ck3lens/policy/enforcement.py`

**Action:** Add logging for policy decisions:

```python
from ck3lens.logging import debug, warn

# After decision is made:
if result.decision == Decision.DENY:
    warn("policy.enforce", "Operation denied", 
         operation=request.operation, reason=result.reason)
else:
    debug("policy.enforce", "Operation allowed", 
          operation=request.operation, decision=result.decision.name)
```

### Step 4.3: Session/Mode Logging

**File:** `tools/ck3lens_mcp/ck3lens/agent_mode.py`

**Action:** Log mode changes:

```python
from ck3lens.logging import info

def set_mode(mode: str) -> None:
    info("session.mode", "Mode changing", previous=get_mode(), new=mode)
    # ... existing code ...
    info("session.mode", "Mode set", mode=mode)
```

### Step 4.4: QBuilder Timestamp Standardization

**File:** `qbuilder/worker.py` (or equivalent logging module)

**Action:** Ensure daemon logs use ISO 8601 UTC format:

```python
# Change from:
logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# To:
class UTCFormatter(logging.Formatter):
    converter = time.gmtime
    
    def formatTime(self, record, datefmt=None):
        ct = self.converter(record.created)
        return f"{time.strftime('%Y-%m-%dT%H:%M:%S', ct)}.{int(record.msecs):03d}Z"
```

---

## Verification Checklist

### Phase 1 Verification

- [ ] `~/.ck3raven/logs/` directory created
- [ ] `ck3raven-mcp.log` file created on MCP server start
- [ ] Log entries are valid JSONL
- [ ] Timestamp format is `YYYY-MM-DDTHH:MM:SS.mmmZ`
- [ ] Log rotation works (test by backdating file mtime)
- [ ] Instance ID appears in all log entries
- [ ] Sensitive data is redacted

### Phase 2 Verification

- [ ] TypeScript compiles without errors
- [ ] `ck3raven-ext.log` created on extension activate
- [ ] Extension activate/deactivate logged
- [ ] MCP registration logged
- [ ] Log flush happens on interval and dispose
- [ ] Output Channel still works (dual output)

### Phase 3 Verification

- [ ] `debug_get_logs()` tool registered
- [ ] Tool returns entries from all log sources
- [ ] Entries are sorted chronologically
- [ ] Filters work (level, category, trace_id, source)
- [ ] Truncation works for large log files

### Phase 4 Verification

- [ ] Contract lifecycle events logged
- [ ] Policy decisions logged
- [ ] Mode changes logged
- [ ] QBuilder logs have UTC timestamps
- [ ] Cross-component trace_id correlation works

---

## Files Changed Summary

### New Files

| File | Lines | Purpose |
|------|-------|---------|
| `tools/ck3lens_mcp/ck3lens/logging.py` | ~110 | MCP structured logging |
| `tools/ck3lens_mcp/ck3lens/log_rotation.py` | ~50 | Log rotation utility |
| `tools/ck3lens-explorer/src/utils/structuredLogger.ts` | ~170 | Extension structured logging |

### Modified Files

| File | Changes |
|------|---------|
| `tools/ck3lens_mcp/server.py` | Add imports, log rotation call, `debug_get_logs` tool, instrumentation at key points |
| `tools/ck3lens-explorer/src/extension.ts` | Import structured logger, add logging to activate/deactivate |
| `tools/ck3lens-explorer/src/mcp/mcpServerProvider.ts` | Add MCP registration logging |
| `tools/ck3lens_mcp/ck3lens/policy/enforcement.py` | Add policy decision logging |
| `tools/ck3lens_mcp/ck3lens/agent_mode.py` | Add mode change logging |
| `qbuilder/worker.py` | Standardize timestamp format |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| File locking conflicts | Low | Medium | Separate log files per runtime (already designed) |
| Performance degradation | Low | Low | Default INFO level, async buffered writes |
| Disk space exhaustion | Low | Medium | 7-day rotation, reasonable file sizes |
| Breaking existing trace.py | None | N/A | Completely additive, trace.py unchanged |

---

## Success Criteria

1. **Debugging deactivate issues** - Can trace extension deactivate → MCP dispose timeline
2. **Cross-component correlation** - trace_id links UI action → MCP tool → result
3. **Persistence** - Logs survive VS Code reload/restart
4. **Discoverability** - Agent can use `debug_get_logs()` to find relevant logs
5. **Non-breaking** - All existing functionality unchanged

---

## Next Steps

1. **Review this plan** with user for approval
2. **Phase 1** - Create Python logging infrastructure (1-2 hours)
3. **Phase 2** - Create TypeScript logging infrastructure (1-2 hours)
4. **Phase 3** - Create aggregator tool (30 min)
5. **Phase 4** - Instrument key points (1 hour)
6. **Documentation** - Update PROPOSED_CANONICAL_LOGS.md to CANONICAL status
