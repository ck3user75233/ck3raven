# Proposed Edits: Playset Visibility & Scope Fixes

> **Status:** DRAFT — Awaiting User Approval  
> **Created:** 2026-02-03  
> **Related Fix Plan:** [FIX_PLAN_playset_visibility_issues.md](FIX_PLAN_playset_visibility_issues.md)

---

## Overview

This document contains the specific code edits that will be made for each phase of the fix plan. **No edits will be made until user approves.**

---

## Phase 1: Data Fix (Immediate) ✅ Quick Win

**File:** `playsets/MSC Religion Expanded Jan 28th_playset.json`

**Problem:** Missing `local_mods_folder` field causes playset loading to partially fail.

**Edit:** Add missing field at end of JSON (before final `}`):

```json
    },
    "local_mods_folder": "C:\\Users\\nateb\\Documents\\Paradox Interactive\\Crusader Kings III\\mod"
}
```

**Change Type:** JSON data fix  
**Risk:** Low  
**Estimated Time:** 2 minutes

---

## Phase 2: Schema Validation ✅ Quick Win

**File:** `tools/ck3lens_mcp/server.py` (around line 327-402)

**Problem:** `_load_playset_from_json()` silently accepts missing required fields.

**Edit:** Add validation at start of function:

```python
REQUIRED_PLAYSET_FIELDS = ["name", "mods", "local_mods_folder"]

def _load_playset_from_json(playset_path: Path) -> dict:
    """Load playset from JSON file with schema validation."""
    data = json.loads(playset_path.read_text())
    
    # Validate required fields
    missing = [f for f in REQUIRED_PLAYSET_FIELDS if f not in data]
    if missing:
        raise ValueError(f"Playset {playset_path.name} missing required fields: {missing}")
    
    # ... rest of existing loading logic unchanged
```

**Change Type:** Python code addition  
**Risk:** Low (fail-fast validation)  
**Estimated Time:** 5 minutes

---

## Phase 3: Move Playsets to User Domain ⚠️ NEEDS DECISION

**Problem:** Playsets in `ck3raven/playsets/` are classified as `CK3RAVEN_SOURCE`, so ck3lens mode cannot edit them.

**Proposed Solution:** Move playsets to `~/.ck3raven/playsets/`

**Files Affected:**
1. `tools/ck3lens_mcp/server.py` — Update manifest path logic
2. `tools/ck3lens_mcp/ck3lens/world_adapter.py` — Add path classification for new location
3. Migration script to move existing playsets

**Code Changes (if approved):**

```python
# In server.py or config:
def get_playset_folder() -> Path:
    """Get playset folder in user data directory."""
    user_data = Path.home() / ".ck3raven"
    playset_folder = user_data / "playsets"
    playset_folder.mkdir(parents=True, exist_ok=True)
    return playset_folder

# Migration (one-time):
# Move ck3raven/playsets/*.json → ~/.ck3raven/playsets/*.json
# Update manifest to point to new location
```

**Change Type:** Architecture change + migration  
**Risk:** Medium (path changes throughout codebase)  
**Estimated Time:** 30-60 minutes

### ❓ QUESTION 1: Move playsets to `~/.ck3raven/playsets/`?

| Option | Description |
|--------|-------------|
| **Yes** | Move to user data folder, full implementation |
| **No** | Keep in repo, add ck3lens exception for playset files only |
| **Defer** | Skip this phase for now |

---

## Phase 4: Remove Oracle Functions

**Problem:** `is_wip_path()` and similar functions violate NO-ORACLE architectural rule.

**File:** `tools/ck3lens_mcp/ck3lens/policy/wip_workspace.py`

**Edit 1:** Delete `is_wip_path()` function (around line 182):

```python
# DELETE THIS FUNCTION:
def is_wip_path(path: str | Path) -> bool:
    """Check if path is within WIP workspace."""
    # ... function body ...
```

**Edit 2:** Delete `is_any_wip_path()` function (around line 199):

```python
# DELETE THIS FUNCTION:
def is_any_wip_path(path: str | Path) -> bool:
    """Check if path is within any WIP workspace."""
    # ... function body ...
```

**Edit 3:** Update all callers to use resolution pattern:

```python
# BEFORE (banned oracle pattern):
if is_wip_path(path):
    return ScopeDomain.WIP_WORKSPACE

# AFTER (canonical resolution pattern):
result = world_adapter.resolve(path)
if result.root_category == RootCategory.ROOT_WIP:
    # handle WIP path
```

**Files to Update (callers):**
- Need to grep for `is_wip_path` and `is_any_wip_path` usages

**Change Type:** Refactor (oracle removal)  
**Risk:** Medium (must update all callers)  
**Estimated Time:** 20-30 minutes

### ❓ QUESTION 2: Include oracle removal in this fix batch?

| Option | Description |
|--------|-------------|
| **Yes** | Remove oracles as part of this fix |
| **Defer** | Separate architectural cleanup task |

---

## Phase 5: Visibility Filtering ⚠️ NEEDS DECISION

**Problem:** `ck3_db_query` and `ck3_search_mods` return data from mods outside the active playset.

### Part A: Fix `ck3_search_mods`

**File:** `tools/ck3lens_mcp/server.py` — `ck3_search_mods` function

**Edit:** Add CVID filtering to query:

```python
def ck3_search_mods(...):
    # Get active playset CVIDs
    active_cvids = _get_active_playset_cvids()
    
    # Filter mod search to active playset only
    if active_cvids:
        query = """
            SELECT * FROM mod_packages 
            WHERE content_version_id IN ({})
            AND name LIKE ?
        """.format(','.join('?' * len(active_cvids)))
        params = list(active_cvids) + [f"%{search_term}%"]
    else:
        # No filter if no playset (shouldn't happen in ck3lens mode)
        query = "SELECT * FROM mod_packages WHERE name LIKE ?"
        params = [f"%{search_term}%"]
```

### Part B: Handle `ck3_db_query` (raw SQL)

**Options:**

| Option | Implementation | Pros | Cons |
|--------|----------------|------|------|
| **A: Auto-filter** | Route through DbHandle with CVID filter | Transparent, safe | May filter when not wanted |
| **B: Warning** | Add warning to output: "Unfiltered data" | Preserves power-user access | Easy to miss warning |
| **C: Deny** | Reject raw SQL in ck3lens mode | Maximum safety | Breaks legitimate use cases |

### ❓ QUESTION 3: How should `ck3_db_query` handle visibility?

| Option | Description |
|--------|-------------|
| **A** | Auto-filter via DbHandle (transparent) |
| **B** | Add warning in output that data is unfiltered |
| **C** | Deny raw SQL in ck3lens mode entirely |

---

## Phase 6: Fix Vanilla/Mod Write Enforcement 🔴 Critical Security Bug

**Problem:** In ck3raven-dev mode, `ck3_file write` to `mod_name="vanilla"` succeeds when it should be absolutely denied.

**Evidence:**
```
Mode: ck3raven-dev
Tool: ck3_file(command="write", mod_name="vanilla", rel_path="common/test.txt")
Expected: EN-WRITE-D-xxx (DENY)
Actual: EN-WRITE-S-001 (SUCCESS!) — wrote to vanilla game folder!
```

**File:** `tools/ck3lens_mcp/ck3lens/policy/enforcement.py`

**Edit:** Add check in enforcement logic:

```python
def enforce_policy(request: EnforcementRequest) -> EnforcementResult:
    """Enforce policy for the given request."""
    
    # ABSOLUTE PROHIBITION: ck3raven-dev cannot write to mod/vanilla/workshop
    if request.mode == "ck3raven-dev":
        if request.operation in [OperationType.FILE_WRITE, OperationType.FILE_DELETE]:
            # Check if target is mod/vanilla/workshop filesystem
            target_domain = _classify_target_domain(request)
            if target_domain in [
                ScopeDomain.VANILLA,
                ScopeDomain.WORKSHOP, 
                ScopeDomain.LOCAL_MOD,
                ScopeDomain.MOD_FILESYSTEM,
            ]:
                return EnforcementResult(
                    decision=Decision.DENY,
                    reason="ABSOLUTE PROHIBITION: ck3raven-dev cannot write to mod/vanilla/workshop files",
                    code="EN-WRITE-D-002",
                )
    
    # ... rest of existing enforcement logic
```

**Change Type:** Security fix  
**Risk:** Low (adding denial, not allowing)  
**Estimated Time:** 15 minutes  
**Priority:** 🔴 CRITICAL

---

## Phase 7: Fix ck3raven-dev Addressing 🔴 Critical Bug

**Problem:** In ck3raven-dev mode, addressing is inverted:
- `mod_name="Artifact Manager"` with `rel_path` → WORKS (shouldn't)
- Raw `path` to Steam workshop file → FAILS (should work for reads)

**Evidence:**
```
# mod_name addressing (should NOT work in ck3raven-dev)
ck3_file(read, mod_name="Artifact Manager", rel_path="descriptor.mod")
Result: WA-READ-S-001 (SUCCESS - unexpected)

# Raw path addressing (SHOULD work in ck3raven-dev for reads)
ck3_file(read, path="C:\Program Files (x86)\Steam\steamapps\workshop\...\descriptor.mod")
Result: WA-RES-I-001 (FAIL - unexpected)
```

**File:** `tools/ck3lens_mcp/ck3lens/world_adapter.py`

**Edit:** Fix mode-aware addressing in `resolve()`:

```python
def resolve(self, path_or_address: str, mod_name: str | None = None, rel_path: str | None = None) -> ResolutionResult:
    """Resolve path with mode-aware addressing."""
    
    if self._mode == "ck3raven-dev":
        # ck3raven-dev mode: raw paths are primary
        if mod_name and not path_or_address:
            # Reject or warn: mod_name addressing not intended for ck3raven-dev
            # Option A: Hard reject
            return ResolutionResult.invalid(
                "ck3raven-dev mode uses raw paths, not mod_name addressing"
            )
            # Option B: Translate to raw path and continue
        
        if path_or_address:
            # Resolve raw path - should work for ROOT_STEAM, ROOT_GAME, etc.
            return self._resolve_raw_path(path_or_address)
    
    elif self._mode == "ck3lens":
        # ck3lens mode: mod_name + rel_path is primary
        if mod_name and rel_path:
            return self._resolve_mod_path(mod_name, rel_path)
        elif path_or_address:
            return self._resolve_raw_path(path_or_address)
    
    # ... existing logic
```

**Change Type:** Bug fix  
**Risk:** Medium (addressing behavior change)  
**Estimated Time:** 30 minutes  
**Priority:** 🔴 CRITICAL

---

## Summary: Questions Requiring User Decision

| # | Phase | Question | Options |
|---|-------|----------|---------|
| 1 | Phase 3 | Move playsets to `~/.ck3raven/playsets/`? | Yes / No / Defer |
| 2 | Phase 4 | Include oracle removal in this fix batch? | Yes / Defer |
| 3 | Phase 5 | How should `ck3_db_query` handle visibility? | Auto-filter / Warning / Deny |

---

## Recommended Implementation Order

| Priority | Phase | Description | Time Est. |
|----------|-------|-------------|-----------|
| 🔴 1 | Phase 6 | Fix vanilla/mod write enforcement | 15 min |
| 🔴 2 | Phase 7 | Fix ck3raven-dev addressing | 30 min |
| 🟢 3 | Phase 1 | Add missing `local_mods_folder` to playset | 2 min |
| 🟢 4 | Phase 2 | Add schema validation | 5 min |
| 🟡 5 | Phase 5A | Fix `ck3_search_mods` filtering | 15 min |
| 🟡 6 | Phase 3 | Move playsets (if approved) | 30-60 min |
| 🟡 7 | Phase 4 | Remove oracle functions (if approved) | 20-30 min |
| 🟡 8 | Phase 5B | Handle `ck3_db_query` (based on decision) | 15 min |

**Total Estimated Time:** 2-3 hours

---

## User Decisions (2026-02-03)

| # | Question | Decision |
|---|----------|----------|
| 1 | Move playsets to `~/.ck3raven/playsets/`? | **YES** — Create ROOT_CK3RAVEN_DATA domain |
| 2 | Include oracle removal? | **YES** — Include now to reduce regression risk |
| 3 | Raw SQL handling? | **AUTO-FILTER** with explicit `unfiltered=True` opt-out |

### Additional Non-Negotiables (from review)

1. **Schema validation must fail closed** — Malformed playset blocks switching with I-type reply
2. **Visibility scoping cannot be opt-in** — All reads scoped by default; unfiltered requires explicit flag + loud warning
3. **Ungoverned system writes are MCP-owned** — Not routed through EN; attributed to MCP layer

### Approved Implementation Order

| Priority | Phase | Description |
|----------|-------|-------------|
| 🔴 1 | Phase 6 | Fix vanilla/mod write enforcement (security) |
| 🔴 2 | Phase 7 | Fix ck3raven-dev addressing (security) |
| 🟢 3 | Phase 1 | Add missing `local_mods_folder` to playset |
| 🟢 4 | Phase 2 | Add schema validation (fail closed, I-type reply) |
| 🟡 5 | Phase 5 | Visibility filtering (auto-filter + unfiltered flag) |
| 🟡 6 | Phase 3 | Move playsets to `~/.ck3raven/playsets/` |
| 🟡 7 | Phase 4 | Remove oracle functions |

---

## Validation Battery (Post-Implementation)

| Gate | Test | Expected Result |
|------|------|-----------------|
| A | Load playset missing `local_mods_folder` | I-type reply naming missing field; playset unchanged |
| B | `ck3_playset(command="mods")` after fix | Non-empty list, `playset_name` populated |
| C | `ck3_search_mods(query="KGD")` | Empty (KGD not in playset) |
| C | `ck3_db_query(...mod_packages LIKE '%KGD%')` | Empty or denied |
| C | `ck3_db_query(...symbols...brave...)` | No KGD CVIDs |
| D | `ck3_search(query="brave", symbol_type="trait")` | Includes vanilla (cv=1) |
| E | `ck3_get_workspace_config()` | No `playset_name`, no `local_mods_folder` |
| F | ck3raven-dev: raw Steam path read | Succeeds |
| F | ck3raven-dev: mod_name addressing | Rejected/deprioritized |

---

## Status: APPROVED — Implementation Starting
