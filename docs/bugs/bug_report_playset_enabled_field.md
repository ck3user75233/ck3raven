# Bug Report: Playset Import Ignores `enabled` Field

**Reported:** February 8, 2026  
**Severity:** High  
**Component:** MCP Server / Session Loading

---

## Summary

The MCP `ck3_playset(command="import")` tool correctly imports the `enabled` status from the CK3 launcher database, but the session loading code in `workspace.py` ignores this field and loads ALL mods into the active session regardless of their enabled/disabled state.

---

## Affected Files

| File | Function | Issue |
|------|----------|-------|
| `tools/ck3lens_mcp/ck3lens/workspace.py` | `_apply_playset()` (lines ~288-320) | Does not filter by `enabled` field |
| `tools/ck3lens_mcp/server.py` | Line ~2532 | Misleading comment claims disabled mods are filtered |

---

## Root Cause

The `_apply_playset()` function iterates over all entries in `data.get("mods", [])` without filtering by the `enabled` field:

```python
# Current (BROKEN) - loads ALL mods regardless of enabled status
for i, m in enumerate(data.get("mods", [])):
    path_str = m.get("path")
    # ... path resolution ...
    
    mod = ModEntry(
        mod_id=m.get("mod_id", m.get("name", "")),
        name=m.get("name", m.get("mod_id", "")),
        path=path,
        load_order=m.get("load_order", i + 1),
        workshop_id=m.get("steam_id", m.get("workshop_id")),
    )
    session.mods.append(mod)  # <- No enabled check!
```

---

## Comparison: Old Script vs New MCP

### Old Script (`scripts/launcher_db_to_playset.py`)
- Correctly reads `enabled` from launcher DB
- Writes `"enabled": true/false` to JSON
- External consumers could filter by enabled status

### New MCP (`server.py` import + `workspace.py` loading)
- Import correctly preserves `enabled` field in JSON ✅
- Session loading ignores `enabled` field entirely ❌
- All mods loaded into `session.mods[]` regardless of status

---

## Evidence

### Playset Comparison: Jan 28th vs Feb 8th (0702)

**Mods that were `enabled: false` in Jan 28th playset:**
- Nameplates
- More Legends
- More Lifestyles
- More Lifestyles - Education Submod
- Houses Traditions
- Regency Rework
- Realistic Army/Fleet Speed
- Japanese Kamon
- Immersive Domain Management
- Adventurer's Beneficiary

**Observed behavior:**
- Feb 8th import from same launcher playset
- Same mods marked disabled in launcher DB
- All mods appear in `ck3_playset(command="mods")` output
- `mod_count` shows 128 instead of expected ~118 enabled

---

## Proposed Fix

### 1. Filter by enabled in `_apply_playset()` (workspace.py)

```python
# FIXED - only load enabled mods
for i, m in enumerate(data.get("mods", [])):
    # Skip disabled mods - they should not be in session.mods[]
    if not m.get("enabled", True):
        continue
    
    path_str = m.get("path")
    # ... rest of existing code ...
```

### 2. Update misleading comment (server.py ~line 2532)

```python
# OLD (misleading):
# All mods in session.mods are "enabled" - they're part of the active playset
# The concept of enabled/disabled doesn't apply here - disabled mods wouldn't be loaded

# NEW (accurate):
# Mods are filtered by enabled=True during session loading in workspace.py.
# Disabled mods are excluded from session.mods[] - only enabled mods are loaded.
```

### 3. Update mod_count calculation in list command

In `_ck3_playset_internal()` list command (around line 2238):

```python
# Current - counts enabled mods for display (correct)
enabled_mods = [m for m in data.get("mods", []) if m.get("enabled", True)]
playsets.append({
    # ...
    "mod_count": len(enabled_mods),  # This is already correct
})
```

This is already correct for the list display, but the session loading needs to match.

---

## Impact

| Area | Impact |
|------|--------|
| Conflict Detection | False positives - disabled mods incorrectly included |
| Search Results | Returns symbols from disabled mods |
| Validation | Validates against disabled mod content |
| Mod Counts | Reports inflated counts |
| Load Order | Disabled mods occupy load positions |

---

## Testing Checklist

1. [ ] Import a playset with some disabled mods
2. [ ] Call `ck3_playset(command="mods")`
3. [ ] Verify disabled mods are NOT in the returned list
4. [ ] Verify `mod_count` matches enabled count only
5. [ ] Verify `ck3_search` does not return results from disabled mods
6. [ ] Verify conflicts only consider enabled mods

---

## Related

- Import code: `server.py` lines ~2720-2910
- Session loading: `workspace.py` `_apply_playset()` function
- Old import script: `scripts/launcher_db_to_playset.py` (reference implementation)
