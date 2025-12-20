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
│  │ (DB read)     │  │ (unit-level)   │  │ (sandbox)   │  │  (live mods) │  │
│  └───────┬───────┘  └───────┬────────┘  └──────┬──────┘  └──────┬───────┘  │
└──────────┼──────────────────┼──────────────────┼────────────────┼──────────┘
           │                  │                  │                │
┌──────────▼──────────────────▼──────────────────┼────────────────┼──────────┐
│                     ck3raven SQLite Database                    │          │
│  ┌─────────────┐  ┌────────────────┐  ┌───────────────────┐    │          │
│  │ files       │  │ symbols        │  │ contribution_units│    │          │
│  │ file_conten │  │ refs           │  │ conflict_units    │    │          │
│  │ asts        │  │ playsets       │  │ resolution_choice │    │          │
│  └─────────────┘  └────────────────┘  └───────────────────┘    │          │
└────────────────────────────────────────────────────────────────┼──────────┘
                                                                 │
┌────────────────────────────────────────────────────────────────▼──────────┐
│                           Live Mod Directories                             │
│  ┌─────────────┐  ┌───────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ MSC         │  │ MSCRE         │  │ LRE          │  │ MRP           │  │
│  └─────────────┘  └───────────────┘  └──────────────┘  └───────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

**Key Principle:** All mod content is pre-parsed and stored in ck3raven's SQLite database. The agent reads from the database, never from raw files. Writes go only to whitelisted "live mod" directories.

---

## Tool Categories

### 1. Database Query Tools

Read-only access to ck3raven's parsed content.

#### `ck3_search_symbols`
Search symbol names/types across the active playset.

```python
ck3_search_symbols(
    query: str,
    symbol_type: str | None = None,  # "trait", "event", "on_action", etc.
    adjacency: str = "auto"          # "strict" | "auto" | "fuzzy"
) -> {
    "results": [
        {"name": str, "symbol_type": str, "file_id": int, "relpath": str, "line": int}
    ],
    "adjacencies": [...],  # Near-matches if adjacency != "strict"
    "query_patterns": [...]  # Patterns searched
}
```

**Adjacency modes:**
- `strict`: Exact match only
- `auto`: Exact + prefix + token decomposition (default)
- `fuzzy`: All above + Levenshtein distance ≤ 2

#### `ck3_search_files`
Search for files by path pattern (SQL LIKE style).

```python
ck3_search_files(
    path_pattern: str,                # e.g., "%on_action%" or "common/traits/%"
    mod_filter: list[str] | None = None,  # Limit to specific mods
    limit: int = 100
) -> {
    "results": [
        {
            "file_id": int,
            "relpath": str,
            "source_name": str,        # "vanilla" or mod name
            "source_kind": str,        # "vanilla" or "mod"
            "file_size": int | None
        }
    ],
    "count": int,
    "truncated": bool
}
```

#### `ck3_search_content`
Full-text grep-style search in file content.

```python
ck3_search_content(
    query: str,                         # Text to search for
    path_filter: str | None = None,     # SQL LIKE pattern, e.g., "%on_action%"
    mod_filter: list[str] | None = None,  # Limit to specific mods
    limit: int = 100
) -> {
    "results": [
        {
            "file_id": int,
            "relpath": str,
            "source_name": str,
            "source_kind": str,
            "line_number": int,
            "snippet": str              # Line content with match
        }
    ],
    "count": int,
    "truncated": bool
}
```

#### `ck3_get_symbol`
Get full details for a specific symbol.

```python
ck3_get_symbol(
    name: str,
    symbol_type: str | None = None
) -> {
    "name": str,
    "symbol_type": str,
    "file_id": int,
    "relpath": str,
    "line": int,
    "content_version": str,  # Which mod/vanilla
    "metadata": dict,
    "ast": dict | None       # Parsed structure if requested
}
```

#### `ck3_get_file`
Read file content by file_id or relpath.

```python
ck3_get_file(
    playset_id: str,
    file_id: int | None = None,
    relpath: str | None = None,
    max_bytes: int = 200000
) -> {
    "file_id": int,
    "relpath": str,
    "mod": str,
    "content": str,
    "size": int
}
```

#### `ck3_list_files`
List files in a folder within the active playset.

```python
ck3_list_files(
    playset_id: str,
    folder: str,             # e.g., "common/on_action"
    pattern: str = "*.txt"
) -> {
    "files": [
        {"file_id": int, "relpath": str, "mod": str, "size": int}
    ]
}
```

#### `ck3_get_conflicts`
Get conflict report for a folder or symbol type.

```python
ck3_get_conflicts(
    playset_id: str,
    folder: str | None = None,
    symbol_type: str | None = None
) -> {
    "folder": str,
    "policy": str,  # "OVERRIDE", "CONTAINER_MERGE", etc.
    "file_overrides": [...],
    "symbol_conflicts": [
        {
            "name": str,
            "winner": {"mod": str, "file": str, "line": int},
            "losers": [{"mod": str, "file": str, "line": int}]
        }
    ]
}
```

#### `ck3_resolve_symbol`
Show what definition "wins" for a symbol plus all competing definitions.

```python
ck3_resolve_symbol(
    playset_id: str,
    name: str,
    symbol_type: str | None = None
) -> {
    "name": str,
    "winner": {"mod": str, "file": str, "line": int, "load_order": int},
    "all_definitions": [...],
    "policy": str
}
```

#### `ck3_get_policy`
Get merge policy for a content path.

```python
ck3_get_policy(
    folder: str
) -> {
    "folder": str,
    "policy": str,
    "description": str
}
```

#### `ck3_confirm_not_exists`
**REQUIRED** before claiming something doesn't exist. Runs exhaustive adjacency search.

```python
ck3_confirm_not_exists(
    query: str,
    symbol_type: str | None = None
) -> {
    "query": str,
    "exact_match": bool,
    "adjacencies": [...],
    "searched_patterns": [...],
    "can_claim_not_exists": bool  # Only true if ALL patterns returned 0 results
}
```

---

### 2. Unit-Level Conflict Analysis Tools

Analyze conflicts at the semantic unit level (decisions, traits, on_actions, etc.) with risk scoring.

#### `ck3_scan_unit_conflicts`
Full conflict scan of the active playset. Extracts all ContributionUnits and groups into ConflictUnits.

```python
ck3_scan_unit_conflicts(
    folder_filter: str | None = None  # e.g., "common/on_action"
) -> {
    "playset_id": int,
    "contributions_extracted": int,
    "conflicts_found": int,
    "summary": {
        "total": int,
        "by_risk": {"low": int, "med": int, "high": int},
        "by_domain": {"on_action": int, "decision": int, ...},
        "unresolved_high_risk": int
    },
    "elapsed_seconds": float
}
```

#### `ck3_get_conflict_summary`
Get summary counts of all conflicts in the playset.

```python
ck3_get_conflict_summary() -> {
    "playset_id": int,
    "total": int,
    "by_risk": {"low": int, "med": int, "high": int},
    "by_domain": {...},
    "by_status": {"unresolved": int, "resolved": int, "deferred": int},
    "unresolved_high_risk": int
}
```

#### `ck3_list_conflict_units`
List conflict units with filters. Returns paginated results.

```python
ck3_list_conflict_units(
    risk_filter: str | None = None,      # "low", "med", "high"
    domain_filter: str | None = None,    # "on_action", "decision", "trait", etc.
    status_filter: str | None = None,    # "unresolved", "resolved", "deferred"
    limit: int = 50,
    offset: int = 0
) -> {
    "playset_id": int,
    "count": int,
    "conflicts": [
        {
            "conflict_unit_id": str,
            "unit_key": str,               # e.g., "on_action:on_yearly_pulse"
            "domain": str,
            "candidate_count": int,
            "merge_capability": str,       # "winner_only", "guided_merge", "ai_merge"
            "risk": str,                   # "low", "med", "high"
            "risk_score": int,             # 0-100
            "uncertainty": str,
            "reasons": [str],
            "resolution_status": str,
            "candidates": [
                {
                    "candidate_id": str,
                    "source_kind": str,    # "vanilla" or "mod"
                    "source_name": str,
                    "load_order_index": int,
                    "is_winner": bool,
                    "relpath": str,
                    "line_number": int,
                    "summary": str
                }
            ]
        }
    ]
}
```

#### `ck3_get_conflict_detail`
Get full details for a specific conflict unit, including content previews.

```python
ck3_get_conflict_detail(
    conflict_unit_id: str
) -> {
    "conflict_unit_id": str,
    "unit_key": str,
    "domain": str,
    "candidates": [
        {
            "candidate_id": str,
            "source_name": str,
            "content_preview": str,        # First 2000 chars of file
            "symbols_defined": [...],
            "refs_used": [...]
        }
    ],
    "resolution": {...} | None             # If already resolved
}
```

#### `ck3_resolve_conflict`
Record a resolution decision for a conflict unit.

```python
ck3_resolve_conflict(
    conflict_unit_id: str,
    decision_type: str,                    # "winner" or "defer"
    winner_candidate_id: str | None = None,
    notes: str | None = None
) -> {
    "success": bool,
    "resolution_id": str,
    "unit_key": str,
    "decision_type": str
}
```

#### `ck3_get_unit_content`
Get all candidate contents for a unit_key for side-by-side comparison.

```python
ck3_get_unit_content(
    unit_key: str,                         # e.g., "on_action:on_yearly_pulse"
    source_filter: str | None = None
) -> {
    "unit_key": str,
    "count": int,
    "contributions": [
        {
            "source_name": str,
            "relpath": str,
            "content": str                 # Up to 5000 chars
        }
    ]
}
```

---

### 3. Live Mod File Operations

Write access to whitelisted "live mod" directories only.

#### `ck3_list_live_mods`
List mods the agent is allowed to write to.

```python
ck3_list_live_mods() -> {
    "mods": [
        {"mod_id": str, "name": str, "path": str}
    ]
}
```

#### `ck3_read_live_file`
Read a file from a live mod (current disk state, not DB).

```python
ck3_read_live_file(
    mod_id: str,
    relpath: str
) -> {
    "mod_id": str,
    "relpath": str,
    "content": str,
    "exists": bool
}
```

#### `ck3_write_file`
Write or create a file in a live mod.

```python
ck3_write_file(
    mod_id: str,
    relpath: str,
    content: str,
    create_dirs: bool = True
) -> {
    "success": bool,
    "mod_id": str,
    "relpath": str,
    "bytes_written": int
}
```

#### `ck3_edit_file`
Edit a portion of an existing file.

```python
ck3_edit_file(
    mod_id: str,
    relpath: str,
    old_content: str,
    new_content: str
) -> {
    "success": bool,
    "mod_id": str,
    "relpath": str,
    "replacements": int
}
```

#### `ck3_delete_file`
Delete a file from a live mod.

```python
ck3_delete_file(
    mod_id: str,
    relpath: str
) -> {
    "success": bool,
    "mod_id": str,
    "relpath": str
}
```

#### `ck3_list_live_files`
List files currently in a live mod folder (disk state).

```python
ck3_list_live_files(
    mod_id: str,
    folder: str = "",
    pattern: str = "*.txt"
) -> {
    "files": [{"relpath": str, "size": int, "modified": str}]
}
```

---

### 4. Validation Tools

Ensure content is correct before writing.

#### `ck3_parse_content`
Parse CK3 script content, return AST or errors.

```python
ck3_parse_content(
    content: str,
    filename: str = "inline.txt"  # For error messages
) -> {
    "success": bool,
    "ast": dict | None,
    "errors": [{"line": int, "column": int, "message": str}]
}
```

#### `ck3_validate_file`
Full validation: parse + reference checking.

```python
ck3_validate_file(
    playset_id: str,
    content: str,
    relpath: str
) -> {
    "success": bool,
    "parse_ok": bool,
    "parse_errors": [...],
    "unknown_references": [{"name": str, "line": int, "type": str}],
    "warnings": [...]
}
```

#### `ck3_check_references`
Check if all references in content are defined.

```python
ck3_check_references(
    playset_id: str,
    content: str
) -> {
    "references_found": [...],
    "unknown_references": [...],
    "declared_symbols": [...]  # New symbols this content defines
}
```

#### `ck3_preview_resolution`
Preview how a new file would affect conflict resolution.

```python
ck3_preview_resolution(
    playset_id: str,
    mod_id: str,
    relpath: str,
    content: str
) -> {
    "would_override": [...],
    "would_be_overridden_by": [...],
    "new_symbols": [...],
    "conflicts_introduced": [...],
    "conflicts_resolved": [...]
}
```

---

### 5. Git Operations

Version control for live mods.

#### `git_status`
Git status for a live mod.

```python
git_status(
    mod_id: str
) -> {
    "mod_id": str,
    "branch": str,
    "staged": [...],
    "unstaged": [...],
    "untracked": [...]
}
```

#### `git_diff`
Show uncommitted changes.

```python
git_diff(
    mod_id: str,
    staged: bool = False
) -> {
    "mod_id": str,
    "diff": str
}
```

#### `git_add`
Stage files for commit.

```python
git_add(
    mod_id: str,
    files: list[str] | None = None,  # None = all
    all: bool = False
) -> {
    "success": bool,
    "staged": [...]
}
```

#### `git_commit`
Commit staged changes.

```python
git_commit(
    mod_id: str,
    message: str
) -> {
    "success": bool,
    "commit_hash": str,
    "message": str
}
```

#### `git_push`
Push to remote.

```python
git_push(
    mod_id: str,
    remote: str = "origin",
    branch: str | None = None
) -> {
    "success": bool,
    "remote": str,
    "branch": str
}
```

#### `git_pull`
Pull from remote.

```python
git_pull(
    mod_id: str,
    remote: str = "origin",
    branch: str | None = None
) -> {
    "success": bool,
    "commits_pulled": int,
    "conflicts": [...]
}
```

#### `git_log`
Recent commit history.

```python
git_log(
    mod_id: str,
    limit: int = 10
) -> {
    "commits": [
        {"hash": str, "author": str, "date": str, "message": str}
    ]
}
```

---

### 6. Session/Context Tools

Manage the agent's session state.

#### `ck3_init_session`
Initialize the ck3lens session with database connection.

```python
ck3_init_session(
    db_path: str | None = None,   # Uses default ~/.ck3raven/ck3raven.db
    live_mods: list[str] | None = None  # Override live mod whitelist
) -> {
    "initialized": bool,
    "mod_root": str,
    "live_mods": [str],
    "playset_name": str,
    "playset_id": int
}
```

#### `ck3_set_playset`
Set the active playset (loads configuration from DB).

```python
ck3_set_playset(
    playset_id: int
) -> {
    "playset_id": int,
    "name": str,
    "vanilla_version": str,
    "mods": [{"name": str, "load_order": int}]
}
```

#### `ck3_get_playset_mods`
Get mods in the active playset with load order.

```python
ck3_get_playset_mods() -> {
    "mods": [
        {
            "name": str,
            "contentVersionId": int,
            "loadOrder": int,
            "kind": str,  # "vanilla", "steam", or "local"
            "fileCount": int,
            "sourcePath": str | None
        }
    ]
}
```

#### `ck3_add_mod_to_playset`
Add a mod to the active playset with full ingestion.

```python
ck3_add_mod_to_playset(
    mod_identifier: str,           # Workshop ID, name, or path
    position: int | None = None,   # 0-indexed load order position
    before_mod: str | None = None, # Insert before this mod
    after_mod: str | None = None   # Insert after this mod
) -> {
    "success": bool,
    "mod_name": str,
    "workshop_id": str | None,
    "content_version_id": int,
    "load_order_position": int,
    "files_indexed": int,
    "symbols_extracted": int
}
```

#### `ck3_import_playset_from_launcher`
Import a playset directly from CK3 Launcher JSON export.

```python
ck3_import_playset_from_launcher(
    launcher_json_path: str | None = None,    # Path to launcher export
    launcher_json_content: str | None = None, # Raw JSON (alternative)
    playset_name: str | None = None,          # Override name
    local_mod_paths: list[str] | None = None, # Add local mods at end
    set_active: bool = True                   # Make this the active playset
) -> {
    "success": bool,
    "playset_id": int,
    "playset_name": str,
    "mods_linked": int,
    "local_mods_linked": int,
    "mods_skipped": [...] | None,
    "is_active": bool,
    "next_steps": str
}
```

**Workflow:**
1. Export playset from Paradox Launcher (Settings → Export Playset)
2. Call with `launcher_json_path` pointing to the exported JSON
3. Tool matches Steam IDs to mods already in database
4. Creates new playset with matching load order
5. Optionally adds local mod paths at end of load order

#### `ck3_reorder_mod_in_playset`
Move a mod to a new position in the load order.

```python
ck3_reorder_mod_in_playset(
    mod_identifier: str,             # Workshop ID or mod name
    new_position: int | None = None, # Target position (0-indexed)
    before_mod: str | None = None,   # Move before this mod
    after_mod: str | None = None     # Move after this mod
) -> {
    "success": bool,
    "mod_name": str,
    "old_position": int,
    "new_position": int
}
```

#### `ck3_remove_mod_from_playset`
Remove a mod from the active playset.

```python
ck3_remove_mod_from_playset(
    mod_identifier: str  # Workshop ID or mod name
) -> {
    "success": bool,
    "mod_name": str,
    "removed_from_position": int
}
```

#### `ck3_get_playset_info`
Get current playset details.

```python
ck3_get_playset_info() -> {
    "playset_id": int,
    "name": str,
    "vanilla_version": str,
    "mods": [...],
    "live_mods": [...]  # Writable mods
}
```

#### `ck3_refresh_mod`
Re-ingest a mod after changes (updates DB).

```python
ck3_refresh_mod(
    mod_id: str
) -> {
    "success": bool,
    "files_updated": int,
    "symbols_updated": int,
    "errors": [...]
}
```
```

---

### 7. Report Generation Tools

Generate comprehensive conflict reports for analysis and prioritization.

#### `ck3_generate_conflicts_report`
Generate a full conflicts report including file-level and ID-level conflicts.

```python
ck3_generate_conflicts_report(
    playset_id: int | None = None,     # Uses active playset if None
    format: str = "json"               # "json" or "cli"
) -> {
    "$schema": "ck3raven.conflicts.v1",
    "generated_at": str,               # ISO 8601 timestamp
    "ck3raven_version": str,
    "report_version": "1.0.0",
    "context": {
        "playset_id": int,
        "playset_name": str,
        "ck3_version": str,
        "mod_count": int,
        "mods": [{"name": str, "load_order": int}],
        "total_files_in_playset": int,
        "total_symbols": int
    },
    "summary": {
        "file_conflicts_count": int,
        "id_conflicts_count": int,
        "highest_risk_file_conflicts": [...],
        "highest_risk_id_conflicts": [...]
    },
    "file_conflicts": [
        {
            "vpath": str,               # e.g., "common/on_action/yearly.txt"
            "conflict_type": str,       # "OVERRIDE" or "MERGE"
            "risk_score": int,          # 0-100
            "sources": [
                {"source_name": str, "load_order": int, "is_winner": bool}
            ],
            "notes": str
        }
    ],
    "id_conflicts": [
        {
            "unit_key": str,            # e.g., "on_action:on_yearly_pulse"
            "domain": str,
            "risk_score": int,
            "merge_capability": str,
            "candidates": [
                {"source_name": str, "relpath": str, "line": int, "is_winner": bool}
            ]
        }
    ]
}
```

#### `ck3_get_high_risk_conflicts`
Get the highest-risk conflicts for priority review.

```python
ck3_get_high_risk_conflicts(
    playset_id: int | None = None,     # Uses active playset if None
    limit: int = 10,                   # Max conflicts to return
    conflict_type: str = "all"         # "file", "id", or "all"
) -> {
    "file_conflicts": [...],           # Top file conflicts by risk
    "id_conflicts": [...]              # Top ID conflicts by risk
}
```

---

## Adjacency Search Details

All symbol searches default to `adjacency="auto"` which expands queries:

| Query | Patterns Searched |
|-------|-------------------|
| `tradition_warrior_culture` | `tradition_warrior_culture` (exact) |
| | `tradition_warrior_culture*` (prefix) |
| | `tradition_warrior*` (stem) |
| | `tradition AND warrior AND culture` (tokens) |
| | `tradition*warrior*culture*` (flex) |

**Fuzzy mode** adds Levenshtein distance ≤ 2 for catching typos.

**Rule:** Agent cannot claim something "doesn't exist" without calling `ck3_confirm_not_exists` which runs exhaustive fuzzy search.

---

## Security Model

1. **Database queries**: Read-only, filtered to active playset
2. **Live mod writes**: Whitelisted directories only
3. **Git operations**: Restricted to live mod repos
4. **Path validation**: No `..`, absolute paths, or escaping sandbox
5. **Trace logging**: All tool invocations logged

---

## Implementation Status

| Tool | Status |
|------|--------|
| **Query Tools** | |
| `ck3_search_symbols` | ✅ Implemented |
| `ck3_search_files` | ✅ Implemented |
| `ck3_search_content` | ✅ Implemented |
| `ck3_get_symbol` | 🔲 Planned |
| `ck3_get_file` | ✅ Implemented |
| `ck3_list_files` | 🔲 Planned |
| `ck3_get_conflicts` | ✅ Implemented |
| `ck3_resolve_symbol` | 🔲 Planned |
| `ck3_get_policy` | 🔲 Planned |
| `ck3_confirm_not_exists` | ✅ Implemented |
| **Unit-Level Conflict Tools** | |
| `ck3_scan_unit_conflicts` | ✅ Implemented |
| `ck3_get_conflict_summary` | ✅ Implemented |
| `ck3_list_conflict_units` | ✅ Implemented |
| `ck3_get_conflict_detail` | ✅ Implemented |
| `ck3_resolve_conflict` | ✅ Implemented |
| `ck3_get_unit_content` | ✅ Implemented |
| **Report Tools** | |
| `ck3_generate_conflicts_report` | ✅ Implemented |
| `ck3_get_high_risk_conflicts` | ✅ Implemented |
| **Live Mod Tools** | |
| `ck3_list_live_mods` | ✅ Implemented |
| `ck3_read_live_file` | ✅ Implemented |
| `ck3_write_file` | ✅ Implemented |
| `ck3_edit_file` | ✅ Implemented |
| `ck3_delete_file` | ✅ Implemented |
| `ck3_list_live_files` | ✅ Implemented |
| **Validation Tools** | |
| `ck3_parse_content` | ✅ Implemented |
| `ck3_validate_patchdraft` | ✅ Implemented |
| `ck3_check_references` | 🔲 Planned |
| `ck3_preview_resolution` | 🔲 Planned |
| **Git Tools** | |
| `ck3_git_status` | ✅ Implemented |
| `ck3_git_diff` | ✅ Implemented |
| `ck3_git_add` | ✅ Implemented |
| `ck3_git_commit` | ✅ Implemented |
| `ck3_git_push` | ✅ Implemented |
| `ck3_git_pull` | ✅ Implemented |
| `ck3_git_log` | ✅ Implemented |
| **Log Parsing Tools** | |
| `ck3_get_error_summary` | ✅ Implemented |
| `ck3_get_errors` | ✅ Implemented |
| `ck3_search_errors` | ✅ Implemented |
| `ck3_get_cascade_patterns` | ✅ Implemented |
| `ck3_get_crash_reports` | ✅ Implemented |
| `ck3_get_crash_detail` | ✅ Implemented |
| `ck3_read_log` | ✅ Implemented |
| **Session Tools** | |
| `ck3_init_session` | ✅ Implemented |
| `ck3_get_playset_mods` | ✅ Implemented |
| `ck3_add_mod_to_playset` | ✅ Implemented |
| `ck3_import_playset_from_launcher` | ✅ Implemented |
| `ck3_reorder_mod_in_playset` | ✅ Implemented |
| `ck3_remove_mod_from_playset` | ✅ Implemented |
| `ck3_set_playset` | 🔲 Planned |
| `ck3_get_playset_info` | 🔲 Planned |
| `ck3_refresh_mod` | 🔲 Planned |
