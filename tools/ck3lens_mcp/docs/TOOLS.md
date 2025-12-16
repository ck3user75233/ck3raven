# CK3 Lens MCP Tools Reference

CK3 Lens provides MCP tools for AI agents to work with CK3 mod content safely and accurately.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent (Copilot)                        │
└─────────────────────────┬───────────────────────────────────┘
                          │ MCP Protocol
┌─────────────────────────▼───────────────────────────────────┐
│                    CK3 Lens MCP Server                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐  │
│  │ Query Tools     │  │ Write Tools     │  │ Git Tools   │  │
│  │ (DB read-only)  │  │ (sandbox only)  │  │ (live mods) │  │
│  └────────┬────────┘  └────────┬────────┘  └──────┬──────┘  │
└───────────┼────────────────────┼─────────────────┼──────────┘
            │                    │                 │
┌───────────▼────────┐  ┌────────▼────────┐  ┌─────▼─────────┐
│  ck3raven SQLite   │  │  Live Mod Dir   │  │  Git Repos    │
│  (all parsed AST)  │  │  (whitelisted)  │  │  (live mods)  │
└────────────────────┘  └─────────────────┘  └───────────────┘
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
    playset_id: str,
    query: str,
    symbol_type: str | None = None,  # "tradition", "event", "on_action", etc.
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

#### `ck3_search_content`
Full-text search in file content.

```python
ck3_search_content(
    playset_id: str,
    query: str,
    folder: str | None = None,       # e.g., "common/traditions"
    limit: int = 50
) -> {
    "results": [
        {"file_id": int, "relpath": str, "mod": str, "snippet": str, "line": int}
    ]
}
```

#### `ck3_get_symbol`
Get full details for a specific symbol.

```python
ck3_get_symbol(
    playset_id: str,
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
    playset_id: str,
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

### 2. Live Mod File Operations

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

### 3. Validation Tools

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

### 4. Git Operations

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

### 5. Session/Context Tools

Manage the agent's session state.

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
| `ck3_search_symbols` | 🔲 Planned |
| `ck3_search_content` | 🔲 Planned |
| `ck3_get_symbol` | 🔲 Planned |
| `ck3_get_file` | 🔲 Planned |
| `ck3_list_files` | 🔲 Planned |
| `ck3_get_conflicts` | 🔲 Planned |
| `ck3_resolve_symbol` | 🔲 Planned |
| `ck3_get_policy` | 🔲 Planned |
| `ck3_confirm_not_exists` | 🔲 Planned |
| **Live Mod Tools** | |
| `ck3_list_live_mods` | 🔲 Planned |
| `ck3_read_live_file` | 🔲 Planned |
| `ck3_write_file` | 🔲 Planned |
| `ck3_edit_file` | 🔲 Planned |
| `ck3_delete_file` | 🔲 Planned |
| `ck3_list_live_files` | 🔲 Planned |
| **Validation Tools** | |
| `ck3_parse_content` | 🔲 Planned |
| `ck3_validate_file` | 🔲 Planned |
| `ck3_check_references` | 🔲 Planned |
| `ck3_preview_resolution` | 🔲 Planned |
| **Git Tools** | |
| `git_status` | 🔲 Planned |
| `git_diff` | 🔲 Planned |
| `git_add` | 🔲 Planned |
| `git_commit` | 🔲 Planned |
| `git_push` | 🔲 Planned |
| `git_pull` | 🔲 Planned |
| `git_log` | 🔲 Planned |
| **Session Tools** | |
| `ck3_set_playset` | 🔲 Planned |
| `ck3_get_playset_info` | 🔲 Planned |
| `ck3_refresh_mod` | 🔲 Planned |
