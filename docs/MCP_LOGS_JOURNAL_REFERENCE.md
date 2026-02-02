# MCP Tool Reference: ck3_logs and ck3_journal

> **Last Updated:** February 2, 2026  
> **Status:** REFERENCE DOCUMENTATION

---

## Table of Contents

1. [ck3_logs - CK3 Game Log Analysis](#ck3_logs---ck3-game-log-analysis)
2. [ck3_journal - Copilot Chat Session Archives](#ck3_journal---copilot-chat-session-archives)
3. [debug_get_logs - Infrastructure Debugging](#debug_get_logs---infrastructure-debugging)

---

## ck3_logs - CK3 Game Log Analysis

Unified tool for analyzing CK3 log files: `error.log`, `game.log`, `debug.log`, and crash reports.

### Signature

```python
ck3_logs(
    source: "error" | "game" | "debug" | "crash" = "error",
    command: "summary" | "list" | "search" | "detail" | "categories" | "cascades" | "read" | "raw" = "summary",
    # Filters
    priority: int | None = None,           # Max priority 1-5 (error source only)
    category: str | None = None,           # Filter by category
    mod_filter: str | None = None,         # Filter by mod name (substring)
    mod_filter_exact: bool = False,        # If True, exact match for mod_filter
    exclude_cascade_children: bool = True, # Skip cascade child errors
    # Search
    query: str | None = None,              # Search text
    # Detail (crash only)
    crash_id: str | None = None,           # Crash folder name
    # Read raw
    lines: int = 100,                      # Lines to return
    from_end: bool = True,                 # Tail (True) vs head (False)
    # Pagination
    limit: int = 50,                       # Max results
    # Custom source (FR-1)
    source_path: str | None = None,        # Custom log file path
    # Export (FR-2)
    export_to: str | None = None,          # Export results to WIP
)
```

### Command Matrix

| Source | Command | Purpose |
|--------|---------|---------|
| **error** | `summary` | Error counts by priority/category/mod |
| **error** | `list` | Filtered error list with fix hints |
| **error** | `search` | Search errors by message |
| **error** | `cascades` | Cascading error patterns (root causes) |
| **game** | `summary` | Game log summary with categories |
| **game** | `list` | Game log errors |
| **game** | `search` | Search game log |
| **game** | `categories` | Category breakdown with descriptions |
| **debug** | `summary` | System info, DLCs, mod list |
| **crash** | `summary` | Recent crash reports list |
| **crash** | `detail` | Full crash report (crash_id required) |
| *any* | `read` | Raw log content (last N lines) |
| *any* | `raw` | Complete raw file (⚠️ 100KB limit) |

### Memory Safety

**⚠️ CRITICAL:** The `command="raw"` option has a **100KB file size limit** to prevent Out-of-Memory crashes in the Extension Development Host.

For files larger than 100KB:
- Use `command="read"` with `lines=` parameter for tail/head access
- Use `command="summary"` for parsed analysis
- Use `command="list"` for filtered errors
- Use `command="search"` for targeted queries

When `command="raw"` is rejected due to size:
```python
{
    "error": "File too large (9.2MB). command='raw' is limited to 100KB.",
    "file_path": "...",
    "file_size": 9648123,
    "suggestion": "For large log files, use targeted access instead:\n..."
}
```

### Examples

```python
# Get error summary
ck3_logs(source="error", command="summary")

# List high-priority errors from a specific mod
ck3_logs(source="error", command="list", priority=2, mod_filter="RICE")

# Search for specific symbol in errors
ck3_logs(source="error", command="search", query="brave_trait")

# Get cascade patterns (fix root causes first)
ck3_logs(source="error", command="cascades")

# Game log categories
ck3_logs(source="game", command="categories")

# Get last 200 lines of game.log
ck3_logs(source="game", command="read", lines=200)

# Get first 50 lines (from beginning)
ck3_logs(source="game", command="read", lines=50, from_end=False)

# System info from debug.log
ck3_logs(source="debug", command="summary")

# Analyze a backup log file from WIP
ck3_logs(source="error", command="summary", source_path="wip:/backups/error_2026-02-01.log")

# Export results to WIP
ck3_logs(source="error", command="summary", export_to="wip:/analysis/error_summary.md")
```

### Log File Locations

Default CK3 log directory:
```
~/Documents/Paradox Interactive/Crusader Kings III/logs/
├── error.log           # Parser/validation errors
├── game.log            # Runtime errors with file/line info
├── debug.log           # System info, mod list
├── setup.log           # Startup/initialization
├── gui_warnings.log    # GUI definition warnings
└── database_conflicts.log  # Database conflict info
```

### Priority Levels (error.log)

| Priority | Meaning | Action |
|----------|---------|--------|
| 1 | Critical - game-breaking | Fix immediately |
| 2 | High - visible bugs | Fix before release |
| 3 | Medium - functionality issues | Should fix |
| 4 | Low - cosmetic/warnings | Nice to fix |
| 5 | Info/unknown | Review if relevant |

### Known Limitations

1. **Mod Attribution:** Workshop IDs require debug.log or launcher lookup to resolve to names
2. **Cross-Log Correlation:** Errors appearing in both logs aren't automatically linked
3. **Cascade Detection:** Within-file patterns only; cross-mod cascades not yet linked

---

## ck3_journal - Copilot Chat Session Archives

Access archived Copilot Chat sessions from the CCE (Copilot Chat Extractor) system.

### Signature

```python
ck3_journal(
    command: "list" | "read" | "search" | "status" = "status",
    # List parameters
    target: "workspaces" | "windows" | "sessions" | None = None,
    workspace_key: str | None = None,      # SHA-256 workspace identifier
    window_id: str | None = None,          # Window identifier
    # Read parameters
    session_id: str | None = None,         # Session UUID to read
    format: "json" | "markdown" = "markdown",
    # Search parameters
    pattern: str | None = None,            # Tag pattern (* = wildcard)
    limit: int = 50,                       # Max results
)
```

### Commands

| Command | Purpose | Required Parameters |
|---------|---------|---------------------|
| `status` | Get journal system status | None |
| `list` | List workspaces/windows/sessions | `target` |
| `read` | Read session content | `workspace_key`, `window_id`, `session_id` |
| `search` | Search tags across journals | `pattern` |

### Hierarchy

```
Journals Root (~/.ck3raven/journals/)
└── {workspace_key}/              # SHA-256 of workspace root path
    └── windows/
        └── {window_id}/          # e.g., 2026-02-02T06-38-25Z_window-4703
            ├── manifest.json     # Session metadata, export info
            ├── tags.jsonl        # Tag index
            ├── {session_id}.json # Raw session data
            └── {session_id}.md   # Markdown export
```

### Examples

```python
# Check journal status
ck3_journal(command="status")

# List all workspaces
ck3_journal(command="list", target="workspaces")

# List windows in a workspace
ck3_journal(command="list", target="windows", workspace_key="1b1e02b5...")

# List sessions in a window
ck3_journal(command="list", target="sessions", workspace_key="1b1e02b5...", window_id="2026-02-02T06-38-25Z_window-4703")

# Read a specific session as markdown
ck3_journal(command="read", workspace_key="1b1e02b5...", window_id="2026-02-02T06-38-25Z_window-4703", session_id="85f3306f-e8c2-4cdb-a4e9-5a8700bc4ad1")

# Read as raw JSON
ck3_journal(command="read", ..., format="json")

# Search for tagged moments
ck3_journal(command="search", pattern="bug*")
ck3_journal(command="search", pattern="*fix*")
```

### Tag Syntax

In chat sessions, use inline tags for searchable moments:
```
*tag: discovery-logic*
*tag: memory-bug*
*tag: arch-decision*
```

These are indexed in `tags.jsonl` and searchable via `command="search"`.

### Windows vs Sessions

- **Window:** A time period during VS Code usage (opened → closed/extracted)
- **Session:** A single Copilot Chat conversation within a window

Multiple sessions can exist in one window. Windows are identified by timestamp + random suffix.

### Workspace Identity

The `workspace_key` is a SHA-256 hash of the normalized, lowercase absolute path of the workspace root. This ensures stable identification even if VS Code moves its internal storage directories.

---

## debug_get_logs - Infrastructure Debugging

Access ck3raven infrastructure logs (MCP server, VS Code extension, QBuilder daemon).

**Note:** This is for debugging ck3raven itself, NOT CK3 game logs. Use `ck3_logs` for game log analysis.

### Signature

```python
debug_get_logs(
    lines: int = 50,                       # Max lines to return
    level: "DEBUG" | "INFO" | "WARN" | "ERROR" | None = None,
    category: str | None = None,           # Filter by category prefix
    trace_id: str | None = None,           # Filter by trace ID
    source: "all" | "mcp" | "ext" | "daemon" = "all",
)
```

### Log Sources

| Source | File | Purpose |
|--------|------|---------|
| `mcp` | `~/.ck3raven/logs/ck3raven-mcp.log` | MCP server (Python) |
| `ext` | `~/.ck3raven/logs/ck3raven-ext.log` | VS Code extension (Node) |
| `daemon` | `~/.ck3raven/daemon/daemon.log` | QBuilder daemon |

### Examples

```python
# Get recent logs from all sources
debug_get_logs(lines=100)

# Only errors
debug_get_logs(level="ERROR")

# Filter by category
debug_get_logs(category="mcp.tool")

# Trace a specific operation
debug_get_logs(trace_id="a1b2c3d4")

# Only extension logs
debug_get_logs(source="ext")
```

### Log Format (JSONL)

```json
{"ts": "2026-02-02T12:34:56.789Z", "level": "INFO", "cat": "mcp.tool", "inst": "tt79", "trace_id": "a1b2c3d4", "msg": "Tool called", "data": {"tool": "ck3_logs"}}
```

### Categories

| Category | Description |
|----------|-------------|
| `mcp.init` | MCP server initialization |
| `mcp.tool` | Tool invocations |
| `mcp.dispose` | Server shutdown |
| `ext.activate` | Extension activation |
| `ext.deactivate` | Extension deactivation |
| `ext.mcp` | MCP registration |
| `contract.*` | Contract lifecycle |
| `session.*` | Session/mode changes |
| `policy.*` | Policy enforcement |

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [CANONICAL_LOGS.md](CANONICAL_LOGS.md) | Logging architecture specification |
| [JOURNAL_EXTRACTOR_SPEC.md](JOURNAL_EXTRACTOR_SPEC.md) | CCE design brief |
| [ck3_logs_tool_feedback.md](Requests%20and%20Reports/ck3_logs_tool_feedback.md) | Bug reports & feature requests |
