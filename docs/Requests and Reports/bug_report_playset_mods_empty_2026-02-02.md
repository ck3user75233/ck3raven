# Bug Report: WorldAdapter Visibility Bypass + Playset Loading Failures

**Date**: 2026-02-02  
**Reporter**: AI Agent (ck3lens mode)  
**Severity**: Critical  
**For**: ck3raven-dev mode investigation

---

## Issues Summary

| # | Issue | Severity |
|---|-------|----------|
| 1 | WorldAdapter visibility completely bypassed | Critical |
| 2 | No schema validation on playset load | High |
| 3 | `ck3_playset(mods)` returns empty despite valid mods | High |
| 4 | Workspace config has hardcoded playset data | Medium |
| 5 | "vanilla_root" terminology should be ROOT_GAME | Low |

---

## Issue 1: WorldAdapter Visibility Bypass (CRITICAL)

### Problem

Agent can access data from mods NOT in the active playset via database queries.

Additionally, vanilla (ROOT_GAME) symbols are NOT being returned by searches even though vanilla should ALWAYS be included when a playset is loaded.

### Evidence

**KGD: The Great Rebalance is NOT in the Jan 28th playset**, verified by grep. Yet:

```python
# SHOULD fail or return empty - returns data instead:
ck3_search_mods(query="KGD")
# Returns: {"name": "KGD: The Great Rebalance", "content_version_id": 131}

# SHOULD fail or return empty - returns data instead:
ck3_db_query(sql="SELECT * FROM mod_packages WHERE name LIKE '%KGD%'")
# Returns: {"name": "KGD: The Great Rebalance"}

# Direct symbol query returns 4 results, 2 outside playset:
ck3_db_query(sql="SELECT ... FROM symbols WHERE name='brave' AND symbol_type='trait'")
# Returns: Vanilla (cv=1), Unofficial Patch (cv=2), More Traditions (cv=50), KGD (cv=131)
# KGD and possibly Vanilla should be filtered
```

**Vanilla symbols missing from searches:**

```python
ck3_search(query="brave", symbol_type="trait")
# Returns: Unofficial Patch, More Traditions v2
# MISSING: Vanilla CK3 (content_version_id=1)
```

Database confirms vanilla has "brave" trait at content_version_id=1, but search doesn't return it. Vanilla should ALWAYS be visible when any playset is loaded.

### Tool Visibility Matrix

| Tool | Enforces Visibility? | Evidence |
|------|---------------------|----------|
| `ck3_search` | Partial/broken | Returns 2/4 brave traits, missing vanilla |
| `ck3_db_query` | **NO** | Returns all 4 brave traits including KGD |
| `ck3_search_mods` | **NO** | Found KGD mod not in playset |
| `ck3_playset(mods)` | Broken | Returns [] |

### Expected Behavior

ALL database access must be scoped to active playset. Either:
- Filter all queries by active playset content_version_ids
- Or deny raw SQL in ck3lens mode entirely

### Files to Investigate

- WorldAdapter class - how does it filter queries?
- `ck3_db_query` implementation - does it call WorldAdapter?
- `ck3_search_mods` implementation - does it respect visibility?

---

## Issue 2: No Schema Validation on Playset Load

### Problem

Jan 28th playset is missing `local_mods_folder` field. No error occurs.

**Working playset (Dec 20th)** ends with:
```json
    "sub_agent_config": { ... }
  },
  "local_mods_folder": "C:\\Users\\nateb\\Documents\\Paradox Interactive\\Crusader Kings III\\mod"
}
```

**Broken playset (Jan 28th)** ends with:
```json
    "sub_agent_config": { ... }
  }
}
```

### Expected Behavior

Playset loading should:
1. Validate against schema with required fields
2. Reject with clear error: `"Missing required field: local_mods_folder"`
3. Refuse to switch to invalid playset

### Current Behavior

- File accepted
- Manifest updated
- Session state broken (`playset_name: null`, `mod_count: 0`)
- No error message

### Files to Investigate

- Playset loading code
- Schema validation (does it exist?)
- Required vs optional field handling

---

## Issue 3: ck3_playset(mods) Returns Empty

### Problem

```python
ck3_playset(command="mods")
# Returns: {"mods": [], "enabled_count": 0, "playset_name": null}
```

But the playset file contains 121 mods, and `switch` command shows `ready_mods: 118`.

### Evidence

```python
ck3_playset(command="switch", playset_name="MSC Religion Expanded Jan 28th")
# Returns:
{
    "success": true,
    "playset_name": null,      # <-- Not populated
    "mod_count": 0,            # <-- Not populated
    "build_status": {
        "ready_mods": 118,     # <-- File WAS read!
        "pending_mods": 3
    }
}
```

### Root Cause Hypothesis

Playset file reading works partially (switch command returns `ready_mods: 118`) but session state hydration fails when `local_mods_folder` is missing.

### Files to Investigate

- Session state hydration code
- Where does `ck3_playset(mods)` get its data from?
- Why does switch command see mods but session state is empty?

---

## Issue 4: Workspace Config Contains Playset Data

### Problem

```python
ck3_get_workspace_config()
# Returns:
{
    "playset_name": "MSC Religion Expanded Jan 28th",
    "local_mods_folder": "C:\\Users\\nateb\\...\\mod"
}
```

### Why This Is Wrong

- Workspace config should be static/structural (paths, modes, database)
- Playset data should come from loaded playset only
- Creates confusion about source of truth
- Where is this `local_mods_folder` coming from if playset file is missing it?

### Expected Structure

```python
ck3_get_workspace_config()
# Should return:
{
    "database": {...},
    "available_modes": [...],
    "root_game": "C:/Program Files.../Crusader Kings III/game"  # User-configured
    # NO playset_name
    # NO local_mods_folder
}
```

---

## Issue 5: Terminology - vanilla_root → ROOT_GAME

### Problem

```python
ck3_playset(command="get")
# Returns: {"vanilla_root": null}
```

### Expected

- Use canonical domain terminology: `ROOT_GAME`
- This is a user-configured path, not playset-specific
- Vanilla is automatically added to every playset when loaded (mod[0] or mod[1])
- The playset file should NOT need a vanilla section

---

## Issue 6: ck3lens Mode Cannot Edit Playset Files

### Problem

```python
ck3_file(command="edit", path="...playsets/Jan 28th_playset.json", ...)
# Returns: "ck3lens mode cannot modify ck3raven source"
```

Playset files are in the `ck3raven/playsets/` folder within the workspace, but ck3lens mode treats them as "ck3raven source" and blocks edits.

### Why This Is Wrong

- Playsets are USER DATA, not ck3raven source code
- Users need to fix broken playsets
- The whole point of having playsets in workspace is for user management
- Agent cannot fix a malformed playset that is breaking the session

### Expected Behavior

ck3lens mode should be able to edit:
- Playset JSON files (`ck3raven/playsets/*.json`)
- Playset manifest (`ck3raven/playsets/playset_manifest.json`)
- Agent briefing files

These are user configuration, not infrastructure code.

### Current Workaround

None. User must manually edit the file or switch to ck3raven-dev mode.

---

## Immediate Fix Required (BLOCKED - see Issue 6)

**File**: `c:\Users\nateb\Documents\CK3 Mod Project 1.18\ck3raven\playsets\MSC Religion Expanded Jan 28th_playset.json`

**Current ending (line 1125-1132)**:
```json
        },
        "conflict_review": {
            "enabled": false,
            "min_risk_score": 70,
            "require_approval": true
        }
    }
}
```

**Fixed ending**:
```json
        },
        "conflict_review": {
            "enabled": false,
            "min_risk_score": 70,
            "require_approval": true
        }
    },
    "local_mods_folder": "C:\\Users\\nateb\\Documents\\Paradox Interactive\\Crusader Kings III\\mod"
}
```

**STATUS**: Cannot be applied by agent - ck3lens mode blocks playset edits.

After fix is applied manually or via ck3raven-dev, test if:
1. `ck3_playset(mods)` returns the 121 mods
2. WorldAdapter visibility is enforced
3. Vanilla (ROOT_GAME) is included in searches

---

## Test Cases for Verification After Fixes

```python
# 1. Schema validation - should REJECT:
# (try loading a playset missing local_mods_folder)
# Expected: Clear error message

# 2. Visibility enforcement - should FAIL or return empty:
ck3_db_query(sql="SELECT * FROM mod_packages WHERE name LIKE '%KGD%'")
# Expected: Error or empty (KGD not in playset)

# 3. Mods command - should work:
ck3_playset(command="mods")
# Expected: 121 mods with names, load_order, enabled status

# 4. Vanilla included in searches:
ck3_search(query="brave", symbol_type="trait")
# Expected: Results from Vanilla CK3 (ROOT_GAME) + mods in playset

# 5. Workspace config clean:
ck3_get_workspace_config()
# Expected: NO playset_name, NO local_mods_folder
```

---

## Reproduction Steps

1. Use Jan 28th playset (missing `local_mods_folder`)
2. Initialize: `ck3_get_mode_instructions(mode="ck3lens")`
3. Check playset: `ck3_playset(command="get")` → shows `mod_count: 0`
4. Try mods: `ck3_playset(command="mods")` → returns empty
5. Query outside playset: `ck3_search_mods(query="KGD")` → returns data (WRONG)
