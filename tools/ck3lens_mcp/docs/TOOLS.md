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
