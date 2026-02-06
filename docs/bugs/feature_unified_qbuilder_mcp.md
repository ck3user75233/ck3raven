# Feature Request: Unified QBuilder MCP Tool

**Priority:** High  
**Component:** tools/ck3lens_mcp  
**Date:** 2026-02-06

---

## Problem Statement

The current qbuilder MCP tooling has several UX and reliability issues:

1. **No Background Process Support:** The MCP tool can only trigger qbuilder operations synchronously, blocking the MCP call
2. **Fragmented Operations:** Different launch modes (fresh, incremental, daemon, one-shot) require different code paths
3. **Playset Switching Pain:** Changing playsets requires manual daemon restart or IPC commands
4. **No Progress Visibility:** Long-running builds provide no feedback to the user
5. **Fresh Reset Bug:** The `--fresh` flag doesn't enqueue discovery after reset (see bug report #1)

## Goals

Create a unified `ck3_qbuilder` MCP tool that:

1. Launches qbuilder as a **background process** (detached from MCP call)
2. Provides a **single entry point** for all qbuilder operations
3. Handles **playset switching** gracefully
4. Reports **progress and status** via polling or streaming
5. Supports **stop/restart** commands without losing work

---

## Proposed API

### Command: `start`

Start qbuilder daemon as a background process.

```python
ck3_qbuilder(
    command="start",
    mode="daemon",           # daemon | oneshot
    fresh=False,             # Reset all data before starting
    playset=None,            # Override active playset (path or name)
    priority_patterns=None,  # Paths to prioritize (list of globs)
)
```

**Behavior:**
- If daemon already running → return status, no restart
- If `fresh=True` → reset all data, then enqueue discovery
- Spawns detached subprocess, returns immediately
- Returns: `{pid, status, run_id}`

### Command: `status`

Query current daemon/worker status.

```python
ck3_qbuilder(command="status")
```

**Returns:**
```json
{
  "running": true,
  "pid": 12345,
  "run_id": "daemon-abc123",
  "discovery": {"pending": 0, "processed": 45},
  "build": {"pending": 120, "processed": 26042},
  "workers": {"active": 1, "idle_seconds": 0},
  "errors": [],
  "started_at": "2026-02-06T10:30:00Z",
  "eta_seconds": 45
}
```

### Command: `stop`

Gracefully stop the daemon.

```python
ck3_qbuilder(command="stop", force=False)
```

**Behavior:**
- Sends shutdown signal via IPC
- If `force=True` → SIGKILL after 5s timeout
- Returns when stopped

### Command: `switch_playset`

Switch to a different playset (triggers re-discovery).

```python
ck3_qbuilder(
    command="switch_playset",
    playset="My Playset Name",  # or path to playset JSON
    incremental=True,           # Keep existing data where possible
)
```

**Behavior:**
- Updates active playset config
- Sends IPC `enqueue_scan` to running daemon
- If no daemon running → start one automatically
- If `incremental=False` → fresh build for new playset

### Command: `logs`

Fetch recent daemon logs.

```python
ck3_qbuilder(
    command="logs",
    lines=100,           # Last N lines
    level="INFO",        # Filter: DEBUG|INFO|WARN|ERROR
    follow=False,        # Stream new logs (if supported)
)
```

### Command: `rebuild_file`

Trigger rebuild of specific file(s).

```python
ck3_qbuilder(
    command="rebuild_file",
    paths=["common/religions/00_christianity.txt"],
)
```

**Use Case:** After manual edit, force re-parse without full rebuild.

---

## Implementation Approach

### Recommended: Hybrid (Subprocess + IPC)

**Mechanism:**
1. `start` command: Spawn daemon via `subprocess.Popen(start_new_session=True)`
2. All other commands: Communicate via existing IPC protocol (port 19876)
3. Daemon writes logs to `~/.ck3raven/logs/qbuilder.log`
4. PID file at `~/.ck3raven/qbuilder.pid` for daemon detection
5. Status includes log tail for recent activity

**Daemon Startup Flow:**
```
ck3_qbuilder(command="start") →
  1. Check if daemon PID exists and is alive
  2. If not: spawn `python -m qbuilder daemon [--fresh]`
  3. Wait up to 5s for IPC port to become available
  4. Query status via IPC
  5. Return {pid, status, run_id}
```

---

## IPC Protocol Extensions

Current IPC server (`qbuilder/ipc_server.py`) handles:
- `enqueue_scan` - trigger playset switch scan
- `get_status` - basic status

**Proposed additions:**

```python
# Extended status with more detail
{"command": "get_status", "verbose": True}
# → Returns full status dict as shown above

# Graceful shutdown
{"command": "shutdown", "timeout_seconds": 30}

# Log tail
{"command": "get_logs", "lines": 100, "level": "INFO"}

# Force rebuild specific paths
{"command": "rebuild", "paths": ["path/to/file.txt"]}
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Daemon not running | `status` returns `{running: false}` |
| IPC timeout | `status` returns `{running: unknown, error: "IPC timeout"}` |
| Daemon crashed | Detect stale PID, clean up, offer to restart |
| Build errors | Surface in status `errors[]` array |
| Playset not found | Return error with available playsets list |

---

## Progress Reporting

For long-running operations, the MCP tool could:

1. **Polling:** Return immediately, user calls `status` repeatedly
2. **Callback URL:** Post status updates to MCP server (complex)
3. **Log File:** Write progress to file, `logs` command reads tail

**Recommendation:** Option 1 (polling) initially. The agent can call `status` in a loop with backoff.

---

## Migration Path

1. **Phase 1:** Add `ck3_qbuilder` tool with `start`, `status`, `stop` commands
2. **Phase 2:** Add `switch_playset` command, integrate with existing playset tools
3. **Phase 3:** Add `logs` and `rebuild_file` commands
4. **Phase 4:** Deprecate old daemon-related workarounds

---

## Open Questions

1. Should `start` block until some minimum progress (e.g., discovery complete)?
2. How to handle multiple concurrent MCP sessions wanting daemon control?
3. Should we support Windows services / systemd units for daemon lifecycle?
4. Is there value in websocket streaming for real-time progress?

---

## Success Criteria

- Agent can start qbuilder with one MCP call
- Agent can monitor progress without blocking
- Playset switches are seamless (no manual restart)
- Errors surface clearly in status response
- Works reliably on Windows (user's OS)
