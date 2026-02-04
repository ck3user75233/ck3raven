# Bug Report: `ck3_playset(command="mods")` Fails with AttributeError

**Date:** 2026-02-04  
**Severity:** High (breaks core functionality)  
**Component:** `tools/ck3lens_mcp/server.py` - `_ck3_playset_internal()`

---

## Summary

The `ck3_playset(command="mods")` command fails with:

```
AttributeError: 'ModEntry' object has no attribute 'enabled'
```

The `mods` command in `server.py` expects `ModEntry` to have attributes that don't exist in the current `ModEntry` dataclass definition.

---

## Root Cause

**Schema mismatch between `server.py` expectations and `ModEntry` dataclass.**

### What `server.py` expects (lines 2499-2511):

```python
# Line 2499-2500: Filter by .enabled
enabled = [m for m in session.mods if m.enabled]
disabled = [m for m in session.mods if not m.enabled]

# Lines 2509-2511: Serialize with these attributes
"enabled": m.enabled,
"steam_id": m.steam_id,
"is_compatch": m.is_compatch,
```

### What `ModEntry` actually has (`ck3lens/workspace.py` lines 59-84):

```python
@dataclass
class ModEntry:
    mod_id: str
    name: str
    path: Path
    load_order: int = 0
    cvid: Optional[int] = None
    workshop_id: Optional[str] = None  # Note: called workshop_id, not steam_id
```

### Missing attributes in `ModEntry`:

| Expected by server.py | Exists in ModEntry | Notes |
|----------------------|-------------------|-------|
| `enabled` | ❌ NO | Not defined |
| `steam_id` | ❌ NO | Called `workshop_id` instead |
| `is_compatch` | ❌ NO | Not defined |

---

## Evidence

**1. `switch` command works:**
```
ck3_playset(command="switch", playset_name="MSC Religion Expanded Jan 28th")
→ SUCCESS: mod_count=122
```

**2. `get` command works:**
```
ck3_playset(command="get")
→ SUCCESS: playset_name="MSC Religion Expanded Jan 28th", mod_count=122
```

**3. `mods` command fails:**
```
ck3_playset(command="mods", limit=5)
→ ERROR: AttributeError: 'ModEntry' object has no attribute 'enabled'
```

---

## Files Involved

| File | Lines | Issue |
|------|-------|-------|
| `tools/ck3lens_mcp/server.py` | 2499-2511 | References non-existent attributes |
| `tools/ck3lens_mcp/ck3lens/workspace.py` | 59-84 | `ModEntry` dataclass missing attributes |

---

## Fix Options

### Option A: Add missing attributes to ModEntry (Recommended)

Update `workspace.py` to add the missing fields:

```python
@dataclass
class ModEntry:
    mod_id: str
    name: str
    path: Path
    load_order: int = 0
    cvid: Optional[int] = None
    workshop_id: Optional[str] = None
    # ADD THESE:
    enabled: bool = True  # All mods in active playset are enabled
    is_compatch: bool = False  # Optional: detect from mod name/path
```

Then update `server.py` line 2510 to use `workshop_id` instead of `steam_id`:
```python
"steam_id": m.workshop_id,  # Fix attribute name
```

### Option B: Fix server.py to match current ModEntry schema

Update `server.py` lines 2499-2522:

```python
elif command == "mods":
    session = _get_session()
    
    # All mods in session.mods are enabled (they're in the active playset)
    # No need to filter by enabled/disabled
    mods_list = session.mods
    
    def mod_to_dict(m):
        return {
            "name": m.name,
            "mod_id": m.mod_id,
            "path": str(m.path) if m.path else None,
            "load_order": m.load_order,
            "workshop_id": m.workshop_id,  # Use correct attribute name
            "cvid": m.cvid,
            "is_indexed": m.is_indexed,  # Property that exists
            "is_vanilla": m.is_vanilla,  # Property that exists
        }
    
    mods_to_return = mods_list[:limit] if limit else mods_list
    
    return {
        "success": True,
        "playset_name": session.playset_name,
        "mod_count": len(mods_list),
        "mods": [mod_to_dict(m) for m in mods_to_return],
        "truncated": limit is not None and len(mods_list) > limit,
    }
```

---

## Recommendation

**Option B is cleaner** because:

1. All mods in `session.mods` are already "enabled" - they're part of the active playset
2. The concept of "disabled" mods doesn't apply here - disabled mods wouldn't be in the session
3. `enabled`/`disabled` filtering was likely from an older design where the session held ALL mods
4. Less schema changes required

---

## Verification Test

After fix, this should work:

```python
ck3_playset(command="mods", limit=5)
# Expected:
{
    "success": True,
    "playset_name": "MSC Religion Expanded Jan 28th",
    "mod_count": 122,
    "mods": [
        {"name": "...", "mod_id": "...", "load_order": 0, ...},
        ...
    ]
}
```
