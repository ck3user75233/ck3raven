# CK3 Lens MCP Tools Reference

CK3 Lens provides MCP tools for AI agents to work with CK3 mod content safely and accurately.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            AI Agent (Copilot)                               │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ MCP Protocol
┌───────────────────────────────────▼─────────────────────────────────────────┐
│                         CK3 Lens MCP Server                                 │
│  ┌───────────────┐  ┌────────────────┐  ┌─────────────┐  ┌──────────────┐  │
│  │ Query Tools   │  │ Conflict Tools │  │ Write Tools │  │  Git Tools   │  │
│  │ (DB read)     │  │ (fast symbols) │  │ (sandbox)   │  │  (live mods) │  │
│  └───────┬───────┘  └───────┬────────┘  └──────┬──────┘  └──────┬───────┘  │
└──────────┼──────────────────┼──────────────────┼────────────────┼──────────┘
           │                  │                  │                │
┌──────────▼──────────────────▼──────────────────┼────────────────┼──────────┐
│                     ck3raven SQLite Database                    │          │
│  ┌─────────────┐  ┌────────────────┐  ┌───────────────────┐    │          │
│  │ files       │  │ symbols        │  │ playsets          │    │          │
│  │ file_content│  │ refs           │  │ playset_mods      │    │          │
│  │ asts        │  │                │  │                   │    │          │
│  └─────────────┘  └────────────────┘  └───────────────────┘    │          │
└────────────────────────────────────────────────────────────────┼──────────┘
                                                                 │
┌────────────────────────────────────────────────────────────────▼──────────┐
│                           Live Mod Directories                             │
│  ┌─────────────┐  ┌───────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ MSC         │  │ LocalizationP │  │ VanillaPatch │  │ CrashFixes    │  │
│  └─────────────┘  └───────────────┘  └──────────────┘  └───────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

**Key Principle:** All mod content is pre-parsed and stored in ck3raven's SQLite database. The agent reads from the database, never from raw files. Writes go only to whitelisted "live mod" directories.

---

## Tool Categories

### 1. Unified Search Tool (PRIMARY)

#### `ck3_search`

**THE primary search tool** - searches symbols, content, and files in one call.

```python
ck3_search(
    query: str,                    # Search term(s)
    file_pattern: str = None,      # SQL LIKE pattern for paths
    source_filter: str = None,     # "vanilla" or mod name
    mod_filter: list[str] = None,  # List of mod names
    game_folder: str = None,       # e.g., "events", "common/traits"
    symbol_type: str = None,       # "trait", "event", "decision", etc.
    adjacency: str = "auto",       # "strict", "auto", "fuzzy"
    limit: int = 25,               # Max results per category
    definitions_only: bool = False,  # Skip references (faster)
    verbose: bool = False,         # More detail
    no_lens: bool = False          # Search ALL content
) -> {
    "query": str,
    "symbols": {
        "count": int,
        "results": [...],           # Symbol definitions
        "adjacencies": [...],       # Similar names
        "definitions_by_mod": {...},
        "references_by_mod": {...}  # Where symbols are USED
    },
    "content": {
        "count": int,
        "results": [...]            # Line-by-line text matches
    },
    "files": {
        "count": int,
        "results": [...]            # Matching file paths
    },
    "truncated": bool,
    "guidance": str                 # Suggestions if truncated
}
```

**Query Syntax for Content Search:**
- Space-separated words: AND search (all must appear in file)
- `"quoted phrase"`: Exact phrase search
- Single word: Simple text search

**Examples:**
```python
ck3_search("brave")                         # All uses of 'brave'
ck3_search("melkite localization")          # Files with BOTH terms
ck3_search("on_yearly_pulse", game_folder="common/on_action")
ck3_search("brave", mod_filter=["MSC"])     # Only in MSC mod
ck3_search("has_trait", limit=100, verbose=True)
```

**Adjacency modes:**
- `strict`: Exact match only
- `auto`: Exact + prefix + token decomposition (default)
- `fuzzy`: All above + similar spellings

---

### 2. Symbol Validation Tools

#### `ck3_confirm_not_exists`

**REQUIRED** before claiming something doesn't exist. Runs exhaustive adjacency search.

```python
ck3_confirm_not_exists(
    name: str,
    symbol_type: str = None,
    no_lens: bool = False
) -> {
    "can_claim_not_exists": bool,  # True ONLY if exhaustive search found nothing
    "similar_matches": [...],       # Symbols you might have meant
    "searched_patterns": [...]
}
```

---

### 3. Conflict Analysis Tools

#### `ck3_get_symbol_conflicts`

**Fast ID-level conflict detection** using the symbols table (instant query).

Automatically filters out conflicts involving "compatch" mods (compatibility patches)
since they are DESIGNED to conflict - that's their purpose.

```python
ck3_get_symbol_conflicts(
    symbol_type: str = None,       # "trait", "event", "decision", etc.
    game_folder: str = None,       # "common/traits", "events", etc.
    limit: int = 100,
    include_compatch: bool = False # Set True to include compatch conflicts
) -> {
    "conflict_count": int,
    "conflicts": [
        {
            "name": str,
            "symbol_type": str,
            "source_count": int,    # How many mods define this
            "sources": [{"mod": str, "file": str, "line": int}],
            "is_compatch_conflict": bool
        }
    ],
    "compatch_conflicts_hidden": int  # Filtered out count
}
```

**Compatch Detection:** Mods with names containing "compatch", "compatibility", 
"patch", "compat", "fix", "hotfix", "tweak", or "override" are recognized
as compatibility patches and filtered out by default.

**Examples:**
```python
ck3_get_symbol_conflicts()                    # All non-compatch conflicts
ck3_get_symbol_conflicts(symbol_type="trait") # Only trait conflicts
ck3_get_symbol_conflicts(game_folder="common/on_action")
ck3_get_symbol_conflicts(include_compatch=True)  # Include compatch
```

#### `ck3_qr_conflicts`

Quick-resolve conflicts using load order. Shows what "wins" based on CK3 merge rules.

```python
ck3_qr_conflicts(
    path_pattern: str = None,
    symbol_name: str = None,
    symbol_type: str = None
) -> {
    "conflicts": [...],
    "winner": {...},
    "losers": [...]
}
```

#### `ck3_scan_unit_conflicts`

Full conflict scan extracting ContributionUnits (slower, more detailed).

```python
ck3_scan_unit_conflicts(
    folder_filter: str = None  # e.g., "common/on_action"
) -> {
    "conflicts_found": int,
    "summary": {...},
    "elapsed_seconds": float
}
```

#### `ck3_get_unit_content`

Compare all candidates for a unit_key side-by-side.

```python
ck3_get_unit_content(
    unit_key: str,                  # e.g., "on_action:on_yearly_pulse"
    source_filter: str = None
) -> {
    "unit_key": str,
    "count": int,
    "contributions": [...]
}
```

---

### 4. File Access Tools

#### `ck3_get_file`

Get file content from the database.

```python
ck3_get_file(
    file_path: str,           # Relative path
    include_ast: bool = False,
    max_bytes: int = 200000,
    no_lens: bool = False
) -> {
    "content": str,
    "relpath": str,
    "mod": str,
    "ast": {...}              # If include_ast=True
}
```

---

### 5. Live Mod File Operations

Write access to whitelisted "live mod" directories only.

#### `ck3_write_file`

Write or create a file in a live mod.

```python
ck3_write_file(
    mod_id: str,
    relpath: str,
    content: str
) -> {"success": bool, "bytes_written": int}
```

#### `ck3_edit_file`

Edit a portion of an existing file with search-replace.

```python
ck3_edit_file(
    mod_id: str,
    relpath: str,
    old_content: str,
    new_content: str
) -> {"success": bool, "replacements": int}
```

#### `ck3_delete_file`

Delete a file from a live mod.

```python
ck3_delete_file(mod_id: str, relpath: str) -> {"success": bool}
```

#### `ck3_create_override_patch`

Create a patch file that overrides a vanilla or mod file.

```python
ck3_create_override_patch(
    source_path: str,        # Path being overridden
    target_mod: str,         # Live mod to create patch in
    mode: str,               # "override_patch" or "full_replace"
    initial_content: str = None
) -> {
    "success": bool,
    "created_path": str,     # e.g., "common/traits/zzz_msc_00_traits.txt"
    "full_path": str
}
```

---

### 6. Validation Tools

#### `ck3_validate_references`

Check if all references in content are defined in the database.

```python
ck3_validate_references(
    content: str,
    filename: str = "inline.txt"
) -> {
    "success": bool,  # True if no errors
    "errors": [...],
    "warnings": [...]
}
```

---

### 7. Session/Context Tools

#### `ck3_get_scope_info`

Get current lens (playset) information.

```python
ck3_get_scope_info() -> {
    "lens_active": bool,
    "playset_id": int,
    "playset_name": str,
    "mod_count": int,
    "mods": [{"name": str, "workshop_id": str}]
}
```

#### `ck3_get_db_status`

Check database build status.

```python
ck3_get_db_status() -> {
    "is_complete": bool,
    "phase": str,
    "files_indexed": int,
    "symbols_extracted": int,
    "needs_rebuild": bool
}
```

---

## Query Syntax

### Multi-term Content Search

`ck3_search` supports multi-term queries:

| Query | Behavior |
|-------|----------|
| `brave` | Simple text search |
| `melkite localization` | Files containing BOTH "melkite" AND "localization" |
| `"has_trait"` | Exact phrase search |
| `"on_yearly_pulse" on_action` | Files with exact "on_yearly_pulse" AND "on_action" |

### Adjacency Search (Symbols)

Symbol searches default to `adjacency="auto"` which expands queries:

| Query | Patterns Searched |
|-------|-------------------|
| `tradition_warrior_culture` | Exact + prefix + token decomposition |
|  | `tradition*warrior*culture*` (flex) |

**Modes:** `strict` (exact only), `auto` (default), `fuzzy` (typo tolerance)

---

## Compatch Filtering

Compatibility patches are **designed** to override other mods - that's their purpose.
`ck3_get_symbol_conflicts` automatically filters these out by default.

**Detected patterns:** "compatch", "compatibility", "patch", "compat", "fix", "hotfix", "tweak", "override"

Set `include_compatch=True` to include these conflicts.

---

## Security Model

1. **Database queries**: Read-only, filtered to active playset
2. **Live mod writes**: Whitelisted directories only
3. **Path validation**: No `..` or escaping sandbox
4. **Trace logging**: All tool invocations logged

---

## Implementation Status

| Tool | Status | Description |
|------|--------|-------------|
| **Search** | | |
| `ck3_search` | ✅ | Unified search (symbols + content + files) |
| `ck3_confirm_not_exists` | ✅ | Exhaustive validation before claiming missing |
| **Conflict Analysis** | | |
| `ck3_get_symbol_conflicts` | ✅ | **NEW** Fast symbols-based detection |
| `ck3_qr_conflicts` | ✅ | Quick-resolve with load order |
| `ck3_scan_unit_conflicts` | ✅ | Unit extraction (slower) |
| `ck3_get_unit_content` | ✅ | Content comparison |
| **File Access** | | |
| `ck3_get_file` | ✅ | Read from DB |
| **Live Mod Operations** | | |
| `ck3_write_file` | ✅ | Write files |
| `ck3_edit_file` | ✅ | Search-replace edit |
| `ck3_delete_file` | ✅ | Delete files |
| `ck3_create_override_patch` | ✅ | Create patch files |
| **Validation** | | |
| `ck3_validate_references` | ✅ | Reference checking |
| **Session** | | |
| `ck3_get_scope_info` | ✅ | Playset info |
| `ck3_get_db_status` | ✅ | Build status |

---

## Deprecated Tools (REMOVED)

The following tools were removed - use `ck3_search` instead:
- ~~`ck3_search_symbols`~~ → Use `ck3_search(query, symbol_type="...")`
- ~~`ck3_search_files`~~ → Use `ck3_search(query, file_pattern="...")`
- ~~`ck3_search_content`~~ → Use `ck3_search(query)`

---

## Unified Tools (NEW - Power Tools)

These consolidated tools replace many granular tools, reducing cognitive load while providing more capability.

### `ck3_logs` - Unified Log Analysis

Consolidated tool for all log operations (replaces 11 deprecated tools).

```python
ck3_logs(
    source: "error" | "game" | "crash" | "all",
    command: "summary" | "list" | "search" | "read" | "categories" | "cascades" | "detail",
    # For list/search:
    priority: int = None,           # 1=critical, 2=high, 3=medium, 4=low, 5=info
    category: str = None,           # e.g., "missing_reference", "script_error"
    mod_filter: str = None,         # Filter by mod name
    limit: int = 50,
    # For search:
    query: str = None,
    # For read:
    log_type: str = None,           # "error", "game", "console", "system"
    lines: int = 100,
    from_end: bool = True,
    # For crash detail:
    crash_id: str = None
) -> dict
```

**Commands:**
| Command | Source | Description |
|---------|--------|-------------|
| `summary` | error | Error counts by priority/category/mod |
| `list` | error | Filtered error list with fix hints |
| `search` | error | Search for specific error patterns |
| `cascades` | error | Detect cascading error patterns |
| `categories` | game | List all game.log categories with counts |
| `read` | game/error | Read raw log content |
| `detail` | crash | Get crash report details |

**Examples:**
```python
ck3_logs("error", "summary")                      # Overview of all errors
ck3_logs("error", "list", priority=2, limit=20)   # High-priority errors
ck3_logs("error", "search", query="brave")        # Find errors mentioning "brave"
ck3_logs("crash", "detail", crash_id="ck3_20251225_120000")
ck3_logs("game", "read", lines=500)               # Last 500 lines of game.log
```

### `ck3_conflicts` - Unified Conflict Management

Consolidated tool for all conflict operations (replaces 8 deprecated tools).

```python
ck3_conflicts(
    command: "summary" | "list" | "scan" | "detail" | "content" | "resolve" | "report" | "high_risk",
    # For list:
    risk_filter: str = None,        # "critical", "high", "medium", "low"
    domain_filter: str = None,      # "on_action", "traits", "decisions", etc.
    status_filter: str = None,      # "unresolved", "resolved"
    limit: int = 50,
    # For scan:
    folder_filter: str = None,      # e.g., "common/on_action"
    force: bool = False,
    # For detail/content/resolve:
    unit_key: str = None,           # e.g., "on_action:on_yearly_pulse"
    conflict_id: str = None,
    # For resolve:
    resolution: str = None,         # "adopt_last", "merge", "manual", etc.
    rationale: str = None,
    # For report:
    include_resolved: bool = False
) -> dict
```

**Commands:**
| Command | Description |
|---------|-------------|
| `summary` | Conflict overview with counts by risk/domain/status |
| `list` | Filtered conflict list |
| `scan` | Full conflict scan (slower, extracts ContributionUnits) |
| `detail` | Detailed info for one conflict |
| `content` | Side-by-side content comparison for a unit |
| `resolve` | Record resolution decision |
| `report` | Generate conflict report document |
| `high_risk` | Get prioritized high-risk conflicts |

**Examples:**
```python
ck3_conflicts("summary")                          # Overview
ck3_conflicts("list", risk_filter="high")         # High-risk conflicts only
ck3_conflicts("detail", unit_key="on_action:on_yearly_pulse")
ck3_conflicts("resolve", unit_key="...", resolution="merge", rationale="Combined triggers")
ck3_conflicts("high_risk", limit=10)              # Top 10 priority conflicts
```

### `ck3_contract` - Work Contract Management (CLW)

Manages work contracts for CLI wrapping - defines scope and constraints for agent tasks.

```python
ck3_contract(
    command: "open" | "close" | "cancel" | "status" | "list" | "flush",
    # For open:
    intent: str = None,             # What work will be done
    canonical_domains: list = None, # ["parser", "routing", "builder", "extraction", "query", "cli"]
    allowed_paths: list = None,     # Glob patterns for allowed files
    capabilities: list = None,      # Requested capabilities
    expires_hours: float = 8.0,
    notes: str = None,
    # For close/cancel:
    contract_id: str = None,
    closure_commit: str = None,     # Git SHA for close
    cancel_reason: str = None,
    # For list:
    status_filter: str = None,
    include_archived: bool = False
) -> dict
```

**Canonical Domains:**
- `parser` - Lexer/parser/AST code
- `routing` - File routing and classification
- `builder` - Database building and ingestion
- `extraction` - Symbol/reference extraction
- `query` - Database queries and search
- `cli` - CLI tools and MCP server

**Examples:**
```python
ck3_contract("status")                            # Check active contract
ck3_contract("open", intent="Fix trait extraction", canonical_domains=["extraction"])
ck3_contract("close", closure_commit="abc123")    # Close after work complete
ck3_contract("list", status_filter="active")
```

### `ck3_exec` - Policy-Enforced Command Execution (CLW)

Execute shell commands with policy enforcement - the ONLY safe way for agents to run commands.

```python
ck3_exec(
    command: str,                   # Shell command
    working_dir: str = None,
    target_paths: list = None,      # Files being affected
    token_id: str = None,           # Approval token for risky commands
    dry_run: bool = False           # Check policy without executing
) -> {
    "allowed": bool,
    "executed": bool,
    "output": str,
    "exit_code": int,
    "policy": {
        "decision": "ALLOW" | "DENY" | "REQUIRE_TOKEN",
        "reason": str,
        "required_token_type": str,
        "category": str
    }
}
```

**Policy Decisions:**
| Category | Examples | Decision |
|----------|----------|----------|
| Safe | `cat`, `git status`, `python -c` | ALLOW |
| Risky | `rm *.py`, `git push` | REQUIRE_TOKEN |
| Blocked | `rm -rf /`, `git push --force origin main` | DENY |

**Examples:**
```python
ck3_exec("git status")                            # Safe - allowed
ck3_exec("git push", dry_run=True)                # Check if would be allowed
ck3_exec("rm test.py", token_id="tok-abc123")     # Risky - needs token
```

### `ck3_token` - Approval Token Management (CLW)

Manage HMAC-signed approval tokens for risky operations.

```python
ck3_token(
    command: "request" | "list" | "validate" | "revoke",
    # For request:
    token_type: str = None,         # See TOKEN_TYPES below
    reason: str = None,             # Why this token is needed
    path_patterns: list = None,     # Allowed paths
    command_patterns: list = None,  # Allowed commands
    ttl_minutes: int = None,        # Override default TTL
    # For validate/revoke:
    token_id: str = None,
    capability: str = None,
    path: str = None
) -> dict
```

**Token Types:**
| Type | Risk | Default TTL | Use Case |
|------|------|-------------|----------|
| `FS_DELETE_CODE` | High | 30 min | Delete .py/.txt files |
| `FS_WRITE_OUTSIDE_CONTRACT` | High | 60 min | Write outside contract scope |
| `CMD_RUN_DESTRUCTIVE` | High | 15 min | DROP TABLE, etc. |
| `CMD_RUN_ARBITRARY` | Critical | 10 min | curl\|bash patterns |
| `GIT_PUSH` | Medium | 60 min | Push to remote |
| `GIT_FORCE_PUSH` | Critical | 10 min | Force push |
| `GIT_REWRITE_HISTORY` | Critical | 15 min | Rebase, reset |
| `DB_SCHEMA_MIGRATE` | High | 30 min | Schema changes |
| `DB_DELETE_DATA` | Critical | 15 min | Delete DB rows |

**Examples:**
```python
ck3_token("list")                                 # List active tokens
ck3_token("request", token_type="FS_DELETE_CODE", reason="Remove test file")
ck3_token("validate", token_id="tok-abc", capability="FS_DELETE_CODE", path="test.py")
ck3_token("revoke", token_id="tok-abc")
```

---

## Tool Count Summary

| Category | Count | Tools |
|----------|-------|-------|
| **Search** | 2 | `ck3_search`, `ck3_confirm_not_exists` |
| **Unified Logs** | 1 | `ck3_logs` (replaces 11 tools) |
| **Unified Conflicts** | 1 | `ck3_conflicts` (replaces 8 tools) |
| **CLI Wrapping** | 3 | `ck3_contract`, `ck3_exec`, `ck3_token` |
| **File Access** | 1 | `ck3_get_file` |
| **Live Mod Ops** | 5 | `ck3_write_file`, `ck3_edit_file`, `ck3_delete_file`, `ck3_create_override_patch`, etc. |
| **Validation** | 2 | `ck3_validate_references`, `ck3_validate_artifact_bundle` |
| **Session** | 3 | `ck3_get_scope_info`, `ck3_get_db_status`, `ck3_db_query` |
| **Total Active** | ~20 | Down from ~80 (deprecated 19 tools) |

---

## Deprecated Tools Reference

### Log Tools (Use `ck3_logs` instead)
| Old Tool | New Equivalent |
|----------|---------------|
| `ck3_get_error_summary` | `ck3_logs("error", "summary")` |
| `ck3_get_errors` | `ck3_logs("error", "list", ...)` |
| `ck3_search_errors` | `ck3_logs("error", "search", query=...)` |
| `ck3_get_error_cascades` | `ck3_logs("error", "cascades")` |
| `ck3_get_crash_reports` | `ck3_logs("crash", "summary")` |
| `ck3_get_crash_detail` | `ck3_logs("crash", "detail", crash_id=...)` |
| `ck3_read_log` | `ck3_logs("game", "read", ...)` |
| `ck3_list_game_logs` | `ck3_logs("game", "list")` |
| `ck3_get_game_log_categories` | `ck3_logs("game", "categories")` |

### Conflict Tools (Use `ck3_conflicts` instead)
| Old Tool | New Equivalent |
|----------|---------------|
| `ck3_scan_unit_conflicts` | `ck3_conflicts("scan", ...)` |
| `ck3_get_conflict_summary` | `ck3_conflicts("summary")` |
| `ck3_list_conflict_units` | `ck3_conflicts("list", ...)` |
| `ck3_get_conflict_detail` | `ck3_conflicts("detail", ...)` |
| `ck3_resolve_conflict` | `ck3_conflicts("resolve", ...)` |
| `ck3_get_unit_content` | `ck3_conflicts("content", ...)` |
| `ck3_generate_conflict_report` | `ck3_conflicts("report", ...)` |
| `ck3_get_high_risk_conflicts` | `ck3_conflicts("high_risk", ...)` |
