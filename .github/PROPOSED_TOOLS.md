# CK3 Lens - Proposed Tool Enhancements

> **Purpose:** Tools to add, improve, or create for better AI agent support
> **Last Updated:** December 18, 2025

---

## Current Tool Gaps

### 1. Database Health Check Tool

**Problem:** No way for the agent to verify database status (playsets, symbols, version).

**Proposal:** Add `ck3_db_status` MCP tool

```python
@mcp.tool()
def ck3_db_status() -> dict:
    """
    Get database health and population status.
    
    Returns:
        - vanilla_version: Current indexed version
        - mod_count: Number of indexed mods
        - file_count: Total files indexed
        - symbol_count: Extracted symbols
        - playset_count: Created playsets
        - active_playset: Currently active playset name
        - issues: List of detected problems
    """
```

**Why:** Agent can self-diagnose "why are my searches empty?" without external scripts.

---

### 2. Content Type Lookup Tool

**Problem:** Agent often forgets which merge policy applies to a folder.

**Proposal:** Add `ck3_get_merge_policy` MCP tool

```python
@mcp.tool()
def ck3_get_merge_policy(folder_path: str) -> dict:
    """
    Get the merge policy for a CK3 content folder.
    
    Args:
        folder_path: e.g., "common/on_action" or "common/traits"
    
    Returns:
        - policy: OVERRIDE | CONTAINER_MERGE | PER_KEY_OVERRIDE | FIOS
        - behavior: Human-readable description
        - warnings: Special considerations (e.g., on_action effect/trigger traps)
    """
```

**Why:** Prevents agent from making on_action mistakes.

---

### 3. Symbol Type Validator

**Problem:** Agent uses wrong scope types, triggers in effect blocks, etc.

**Proposal:** Add `ck3_validate_symbol_usage` MCP tool

```python
@mcp.tool()
def ck3_validate_symbol_usage(
    symbol_name: str,
    context: Literal["trigger", "effect", "modifier", "scope"]
) -> dict:
    """
    Check if a symbol can be used in a given context.
    
    Args:
        symbol_name: e.g., "is_adult", "add_prestige", "martial"
        context: Where it's being used
    
    Returns:
        - valid: bool
        - correct_context: Where this symbol should be used
        - parameters: Required/optional parameters
        - examples: Usage examples from vanilla
    """
```

**Why:** Prevents "invalid trigger" errors from mixing up contexts.

---

### 4. Load Order Analyzer

**Problem:** Agent can't easily see which mod wins for a specific file/symbol.

**Proposal:** Enhance `ck3_get_conflicts` or add `ck3_trace_symbol`

```python
@mcp.tool()
def ck3_trace_symbol(
    symbol_name: str,
    symbol_type: Optional[str] = None
) -> dict:
    """
    Trace a symbol through all sources in load order.
    
    Returns:
        - definitions: List of all definitions with mod/file/line
        - winner: Which definition the game uses
        - losers: Overridden definitions
        - merge_policy: How conflict was resolved
        - recommendation: How to patch if needed
    """
```

**Why:** Essential for compatch work - understanding who overwrites whom.

---

### 5. Localization Key Lookup

**Problem:** No tool specifically for localization keys.

**Proposal:** Add `ck3_search_localization` MCP tool

```python
@mcp.tool()
def ck3_search_localization(
    key: str,
    language: str = "english"
) -> dict:
    """
    Search for localization keys across all mods.
    
    Returns:
        - matches: List of (mod, file, key, value)
        - winner: Final value after override
        - missing_languages: Languages without this key
    """
```

**Why:** Localization is a major source of mod errors.

---

### 6. Batch Validation Tool

**Problem:** Validating multiple files one at a time is slow.

**Proposal:** Add `ck3_validate_mod` MCP tool

```python
@mcp.tool()
def ck3_validate_mod(
    mod_name: str,
    path_filter: Optional[str] = None
) -> dict:
    """
    Validate all files in a live mod.
    
    Args:
        mod_name: One of the whitelisted mods
        path_filter: Optional glob pattern (e.g., "common/traits/*")
    
    Returns:
        - total_files: Count of files checked
        - valid_files: Count passing validation
        - errors: List of (file, line, error) for failures
    """
```

**Why:** Quick health check after batch edits.

---

## Existing Tool Improvements

### `ck3_search_symbols` Improvements

1. **Return file content snippet** - Show 5 lines around the symbol definition
2. **Include provenance** - Which mod defined it, load order position
3. **Show override status** - Is this symbol overridden by another mod?

### `ck3_get_file` Improvements

1. **Fix column name bug** - Use `content_text`/`content_blob` not `content`
2. **Add mod name** - Include which mod/vanilla the file is from
3. **Add load order position** - Where in load order this version sits

### `ck3_parse_content` Improvements

1. **Return warnings** - Not just hard errors (e.g., deprecated syntax)
2. **Suggest fixes** - For common errors, propose corrections
3. **Context validation** - Check if triggers/effects are in correct blocks

---

## Infrastructure Tools (for ck3raven-dev mode)

### `ck3_rebuild_index` (Admin Tool)

```python
@mcp.tool()
def ck3_rebuild_index(
    scope: Literal["symbols", "playsets", "all"]
) -> dict:
    """
    Rebuild database indices.
    
    Args:
        scope: What to rebuild
    
    Returns:
        - duration: Time taken
        - records: Count of records processed
    """
```

**Why:** Self-healing when database gets out of sync.

### `ck3_create_playset_from_active` (Setup Tool)

```python
@mcp.tool()
def ck3_create_playset_from_active(
    name: str = "Active Playset"
) -> dict:
    """
    Create a playset from active_mod_paths.json.
    
    Returns:
        - playset_id: Created playset ID
        - mod_count: Mods added
        - skipped: Mods not in database
    """
```

**Why:** One-click playset creation without running external scripts.

---

## Python Helper Scripts (Not MCP)

These should live in `scripts/` for direct Python invocation:

### `scripts/diagnose_db.py`
Check database health, report issues, suggest fixes.

### `scripts/export_symbol_table.py`
Export symbols to JSON for external analysis.

### `scripts/compare_playsets.py`
Diff two playsets to see what changed.

### `scripts/extract_error_log.py`
Parse CK3's error.log into structured format.

---

## Priority Order

| Priority | Tool | Effort | Impact |
|----------|------|--------|--------|
| 🔴 High | `ck3_db_status` | Low | Enables self-diagnosis |
| 🔴 High | Fix `ck3_get_file` columns | Low | Fixes broken tool |
| 🟠 Medium | `ck3_get_merge_policy` | Low | Prevents on_action errors |
| 🟠 Medium | `ck3_trace_symbol` | Medium | Essential for compatch |
| 🟡 Low | `ck3_validate_symbol_usage` | High | Nice to have |
| 🟡 Low | `ck3_validate_mod` | Medium | Batch convenience |

---

## Implementation Notes

All new MCP tools should:
1. Use existing `db/` module functions, not raw SQL
2. Include proper error handling with helpful messages
3. Return structured data (dicts/lists), not formatted strings
4. Be documented in `tools/ck3lens_mcp/docs/TOOLS.md`
5. Have test coverage in `tests/test_mcp_tools.py`
