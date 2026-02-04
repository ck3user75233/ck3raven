# Bug Report: Dual Session Systems Causing Playset State Failure

**Date**: 2026-02-04  
**Reporter**: AI Agent (ck3lens mode)  
**Severity**: Critical  
**Component**: `tools/ck3lens_mcp/server.py` - Session Management  
**Status**: Root Cause Identified, Fix Drafted

---

## Summary

There are **two parallel session systems** in server.py that do the same thing. One works (`_get_session()`), one is broken (`_get_session_scope()`). The broken one is used by all `ck3_playset` commands, causing session state to always be null/empty.

---

## Root Cause: Dual Session Systems

### System 1: `_get_session()` - **WORKS**

| Location | Line 159 of server.py |
|----------|----------------------|
| Returns | `Session` object (from `ck3lens.workspace.load_config()`) |
| Used by | `ck3_get_workspace_config`, DB operations, WorldAdapter |
| Result | `session.playset_name` = "MSC Religion Expanded Jan 28th" ✅ |

### System 2: `_get_session_scope()` - **BROKEN**

| Location | Line 500 of server.py |
|----------|----------------------|
| Returns | `dict` with playset info |
| Used by | ALL `ck3_playset` commands (`get`, `mods`, `switch`, etc.) |
| Result | `scope.get("playset_name")` = `None` ❌ |

---

## The Specific Bug in `_get_session_scope()`

**Path Mismatch Bug** (lines 326-330, 531):

```python
# Line 326: HARDCODED at module load time
PLAYSETS_DIR = REPO_PLAYSETS_DIR  # Always points to ck3raven/playsets/

# Line 330: DYNAMIC function call
PLAYSET_MANIFEST_FILE = _get_playsets_dir() / "playset_manifest.json"
# If ~/.ck3raven/playsets/ exists, points there
# Otherwise points to ck3raven/playsets/

# Line 531: THE BUG - uses wrong variable
active_file = PLAYSETS_DIR / active_filename  # Uses hardcoded path!
```

If `~/.ck3raven/playsets/` exists:
- `PLAYSET_MANIFEST_FILE` → `~/.ck3raven/playsets/playset_manifest.json`
- `PLAYSETS_DIR` → `ck3raven/playsets/` (hardcoded!)
- Result: Manifest found in user folder, but playset file lookup fails in repo folder

Even when it "works" (both point to same dir), the code is duplicating logic that already exists in `load_config()`.

---

## Evidence: Two Different Results

### `ck3_get_workspace_config()` - Uses `_get_session()`
```json
{
    "playset_name": "MSC Religion Expanded Jan 28th",  // ✅ WORKS
    "local_mods_folder": "C:\\Users\\nateb\\Documents\\Paradox Interactive\\Crusader Kings III\\mod"
}
```

### `ck3_playset(command="get")` - Uses `_get_session_scope()`
```json
{
    "playset_name": null,     // ❌ BROKEN
    "source": "none",
    "mod_count": 0,
    "vanilla_root": null
}
```

---

## Affected Code Paths

| Function | Line | Uses | Broken? |
|----------|------|------|---------|
| `_ck3_playset_internal` (get) | 2514 | `_get_session_scope()` | ❌ Yes |
| `_ck3_playset_internal` (mods) | 2535 | `_get_session_scope()` | ❌ Yes |
| `_ck3_playset_internal` (switch) | 2270 | `_get_session_scope()` | ❌ Yes |
| `_ck3_playset_internal` (add_mod) | 2552 | `_get_session_scope()` | ❌ Yes |
| `ck3_get_workspace_config` | 5280 | `_get_session()` | ✅ Works |
| `ck3_folder` | 2100 | `_get_session()` | ✅ Works |

---

## Fix: Delete `_get_session_scope()`, Use `_get_session()` Everywhere

### Why This Is The Right Fix

The `Session` object (from `ck3lens.workspace.load_config()`) already has everything needed:
- `session.playset_name` - Human-readable name
- `session.mods` - List of `ModEntry` objects with full mod data
- `session.local_mods_folder` - Path to editable mods
- `session.db_path` - Database location
- `session.vanilla_root` - Path to vanilla game files (if implemented)

There's no reason to have a second system that reimplements this poorly.

---

## Fix Instructions

### Step 1: Delete `_get_session_scope()` (lines 500-557)

Remove the entire function. It's ~60 lines of broken duplicate logic.

### Step 2: Delete `_session_scope` Global

Remove:
```python
_session_scope: Optional[dict] = None  # wherever declared
```

And all `global _session_scope` declarations.

### Step 3: Refactor `_ck3_playset_internal` to Use `_get_session()`

**Before** (broken):
```python
elif command == "get":
    scope = _get_session_scope()
    return {
        "playset_name": scope.get("playset_name"),
        "source": scope.get("source"),
        "mod_count": len(scope.get("active_mod_ids", set())),
    }
```

**After** (fixed):
```python
elif command == "get":
    session = _get_session()
    return {
        "playset_name": session.playset_name,
        "source": "json" if session.playset_name else "none",
        "mod_count": len(session.mods),
        "vanilla_root": str(session.vanilla_root) if session.vanilla_root else None,
        "local_mods_folder": str(session.local_mods_folder) if session.local_mods_folder else None,
    }
```

### Step 4: Fix `mods` Command

**Before**:
```python
elif command == "mods":
    scope = _get_session_scope()
    mod_list = scope.get("mod_list", [])
    enabled = [m for m in mod_list if m.get("enabled", True)]
```

**After**:
```python
elif command == "mods":
    session = _get_session()
    # session.mods is already a list of ModEntry objects
    enabled = [m for m in session.mods if m.enabled]
    disabled = [m for m in session.mods if not m.enabled]
    
    # Convert ModEntry objects to dicts for JSON serialization
    return {
        "playset_name": session.playset_name,
        "enabled_count": len(enabled),
        "disabled_count": len(disabled),
        "mods": [m.to_dict() for m in (enabled[:limit] if limit else enabled)],
    }
```

### Step 5: Fix `switch` Command

The switch command needs to reload the session after updating the manifest:

**After**:
```python
elif command == "switch":
    # ... (find playset file, update manifest) ...
    
    # Clear cached session to force reload
    global _session
    _session = None
    
    # Reload session with new playset
    session = _get_session()
    
    return {
        "success": True,
        "playset_name": session.playset_name,
        "mod_count": len(session.mods),
        # ... build status ...
    }
```

### Step 6: Ensure `Session` Class Has Required Properties

Verify `tools/ck3lens_mcp/ck3lens/workspace.py` `Session` class has:
- `playset_name: str`
- `mods: list[ModEntry]`
- `vanilla_root: Optional[Path]`
- `local_mods_folder: Optional[Path]`

If `vanilla_root` is missing, add it to `load_config()`.

### Step 7: Add `ModEntry.to_dict()` Method If Missing

```python
class ModEntry:
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path) if self.path else None,
            "load_order": self.load_order,
            "enabled": self.enabled,
            "steam_id": self.steam_id,
            "is_compatch": self.is_compatch,
            "cvid": self.cvid,
        }
```

---

## Files To Modify

1. **`tools/ck3lens_mcp/server.py`**
   - Delete `_get_session_scope()` function (lines 500-557)
   - Delete `_session_scope` global
   - Refactor `_ck3_playset_internal()` to use `_get_session()`
   - Update all commands: get, mods, switch, add_mod, remove_mod, reorder

2. **`tools/ck3lens_mcp/ck3lens/workspace.py`**
   - Add `vanilla_root` property to `Session` if missing
   - Add `to_dict()` method to `ModEntry` if missing
   - Ensure `load_config()` reads vanilla path from playset

---

## Validation Checklist

After fix, verify:

- [ ] `ck3_playset(command="get")` returns `playset_name`, `mod_count`, `vanilla_root`
- [ ] `ck3_playset(command="mods")` returns full mod list
- [ ] `ck3_playset(command="switch")` updates session state
- [ ] `ck3_get_workspace_config()` still works (should be unchanged)
- [ ] No duplicate session globals (`_session_scope` removed)
- [ ] WorldAdapter visibility uses `session.mods` correctly

---

## Related Issues

- Schema validation requires `vanilla` object - design decision: should vanilla be auto-added as mods[0]?
- `PLAYSETS_DIR` hardcoded vs `_get_playsets_dir()` dynamic - consolidate after main fix
- WorldAdapter visibility bypass - ensure session.mods is used for boundaries

---

## Test Commands

```python
# After fix, these should all work:
ck3_get_mode_instructions(mode="ck3lens")
ck3_playset(command="switch", playset_name="MSC Religion Expanded Jan 28th")
# → playset_name: "MSC Religion Expanded Jan 28th", mod_count: 121

ck3_playset(command="get")
# → playset_name, vanilla_root, mod_count all populated

ck3_playset(command="mods", limit=5)
# → mods: [{name, path, load_order, ...}, ...]
```
