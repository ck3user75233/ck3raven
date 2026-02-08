# Bug Report: mod_name="wip" Path Resolution Asymmetry

**Date**: 2026-02-07  
**Severity**: Medium (breaks read, list, refresh for WIP; write works by accident)  
**Component**: `ck3_file` tool — `unified_tools.py` + `world_adapter.py`  
**Status**: **RESOLVED** — 2026-02-07, commit `6f1d4ad` (Option A refactor per proposal_path_addressing.md V3)

---

## Summary

`ck3_file(command="write", mod_name="wip", rel_path="file.md")` **succeeds**, but  
`ck3_file(command="read", mod_name="wip", rel_path="file.md")` **fails** with `"Unknown mod_id: wip"`.

The root cause is that `normalize_path_input()` (which correctly translates `mod_name="wip"` → `wip:/` canonical address) is **only called for write commands**. Read, list, refresh, and get commands bypass it entirely and pass `mod_name` directly to `session.get_mod()`, which searches the playset mod list — where "wip" does not exist.

## Affected Commands

| Command | mod_name="wip" | mod_name="vanilla" | Actual mod name |
|---------|---------------|--------------------|-----------------| 
| write   | ✅ Works      | ✅ Works           | ✅ Works        |
| edit    | ✅ Works      | ✅ Works           | ✅ Works        |
| delete  | ✅ Works      | ✅ Works           | ✅ Works        |
| rename  | ✅ Works      | ✅ Works           | ✅ Works        |
| **read**    | ❌ "Unknown mod_id: wip" | ❌ Fails | ✅ Works |
| **list**    | ❌ "Unknown mod_id: wip" | ❌ Fails | ✅ Works |
| **refresh** | ❌ "Unknown mod_id: wip" | ❌ Fails | ✅ Works |
| get     | N/A (uses path, not mod_name) | N/A | N/A |

## Root Cause

In `unified_tools.py` `ck3_file_impl()` (line ~870):

```python
write_commands = {"write", "edit", "delete", "rename"}

if command in write_commands and world is not None:
    # ✅ Uses normalize_path_input() — correctly handles mod_name="wip"
    resolution = normalize_path_input(world, path=path, mod_name=mod_name, rel_path=rel_path)
```

But for read (line ~952):
```python
elif command == "read":
    if path:
        return _file_read_raw(path, ...)       # ✅ Works (raw path)
    elif mod_name and rel_path:
        return _file_read_live(mod_name, ...)   # ❌ Calls session.get_mod("wip") → None
```

`_file_read_live()` calls `session.get_mod(mod_name)` which searches the playset mod list. "wip" is not a mod, so it returns `None` → `"Unknown mod_id: wip"`.

The same pattern applies to `_file_list()` and `_file_refresh()`.

## Workaround (current)

Use `path=` with absolute path instead of `mod_name="wip"`:
```
ck3_file(command="read", path="C:\\Users\\nateb\\.ck3raven\\wip\\myfile.md")
```

## Proposed Fix: Unify All Commands Through normalize_path_input

### Option A: Minimal fix (extend normalize_path_input to all commands)

Move path resolution to the top of `ck3_file_impl`, before the command dispatch:

```python
# ALWAYS resolve path, not just for write commands
if world is not None and (path or mod_name):
    resolution = normalize_path_input(world, path=path, mod_name=mod_name, rel_path=rel_path)
    if not resolution.found:
        return {"error": resolution.error_message}

# Then route commands using resolution.absolute_path
if command == "read":
    return _file_read_raw(str(resolution.absolute_path), start_line, end_line, ...)
```

This eliminates the dual code paths (`_file_read_raw` vs `_file_read_live`) for resolved addresses.

### Option B: Replace mod_name pseudo-values with explicit addressing (user preference)

The user's preference is to **stop overloading `mod_name`** for non-mod targets. Instead, use the existing canonical address scheme or root_category-based addressing:

**Current (confusing):**
```python
mod_name="wip"        # Not a mod
mod_name="vanilla"    # Not a mod  
mod_name="My Real Mod"  # Actual mod
```

**Proposed — use `path` with canonical addresses:**
```python
path="wip:/docs/bugs/report.md"           # WIP workspace
path="vanilla:/common/traits/00_traits.txt"  # Vanilla game
path="mod:My Real Mod/common/traits.txt"   # Actual mod
path="data:/config/settings.json"          # ~/.ck3raven/config/
path="ck3raven:/src/parser/lexer.py"       # Repo source
```

This aligns with the existing `_parse_canonical()` method in WorldAdapter which already handles all these address types. The `mod_name` parameter would be reserved exclusively for actual mod names in the active playset.

**Benefits:**
1. No more "is this a mod or a keyword?" ambiguity
2. All commands go through the same `normalize_path_input()` → `world.resolve()` pipeline  
3. Capability matrix enforcement works uniformly (already keyed on `RootCategory` + subdirectory)
4. Agent can address any domain without fake mod names

**Migration:** The `mod_name="wip"` and `mod_name="vanilla"` translations in `normalize_path_input()` can remain as backward compat during transition, then be deprecated.

## Additional Findings

### 1. _file_read_live is redundant with _file_read_raw

Both ultimately read a file from disk. `_file_read_live` constructs the path from `session.get_mod(mod_name).path / rel_path`, while `_file_read_raw` takes an absolute path. If all commands go through resolution first, `_file_read_live` can be removed — `_file_read_raw` with the resolved absolute path handles all cases.

### 2. _file_list also has two code paths

```python
if path and mode == "ck3raven-dev":
    return _file_list_raw(path, ...)    # Raw path (dev mode only)
elif mod_name:
    return _file_list(mod_name, ...)    # Mod lookup (fails for "wip")
```

Same fix: resolve first, then use the absolute path for listing.

### 3. Enforcement only runs for write commands

Currently, the capability matrix enforcement gate in `ck3_file_impl` is inside `if command in write_commands`. Read operations skip enforcement entirely. This is intentional (reads are governed by visibility/resolution), but worth noting—if read restrictions are ever needed, the enforcement gate must be generalized.

## File Locations

| File | Lines | Role |
|------|-------|------|
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 830-950 | `ck3_file_impl` dispatch (bug location) |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1132-1200 | `_file_read_live` (broken for pseudo-mods) |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 1622-1700 | `_file_list` (broken for pseudo-mods) |
| `tools/ck3lens_mcp/ck3lens/world_adapter.py` | 123-165 | `normalize_path_input` (only called for writes) |
| `tools/ck3lens_mcp/ck3lens/world_adapter.py` | 536-590 | `_parse_canonical` (handles wip:/, vanilla:/, etc.) |
| `tools/ck3lens_mcp/ck3lens/capability_matrix.py` | 40-170 | Capability matrix (already correct) |
| `tools/ck3lens_mcp/server.py` | 1879 | `mod_name` parameter doc (misleading) |
