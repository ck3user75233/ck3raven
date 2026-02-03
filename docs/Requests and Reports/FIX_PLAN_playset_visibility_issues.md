# Fix Plan: Playset Visibility & Scope Issues

> **Status:** DRAFT — Awaiting Approval  
> **Created:** 2026-02-02  
> **Related Bug Report:** [bug_report_playset_mods_empty_2026-02-02.md](bug_report_playset_mods_empty_2026-02-02.md)

---

## Summary of Issues

Eight interconnected issues were identified:

| # | Issue | Root Cause |
|---|-------|------------|
| 1 | `ck3_search_mods` returns out-of-playset mods | No CVID filtering on `mod_packages` query |
| 2 | `ck3_db_query` returns out-of-playset data | Raw SQL bypasses WorldAdapter entirely |
| 3 | `ck3_playset(mods)` returns empty list | Jan 28th playset missing `local_mods_folder` field |
| 4 | No schema validation on playset load | `_load_playset_from_json()` silently accepts missing fields |
| 5 | ck3lens can't edit playset files | Playsets in `ck3raven/playsets/` classified as `CK3RAVEN_SOURCE` |
| 6 | Oracle functions like `is_wip_path()` | Violates NO-ORACLE rule; should use path resolution |
| 7 | **Vanilla write succeeds in ck3raven-dev** | Enforcement not denying vanilla/mod writes |
| 8 | **ck3raven-dev addressing is inverted** | mod_name works but raw paths fail for ROOT_STEAM |

---

## Canonical Architecture Alignment

### Key Principles (from CANONICAL_ARCHITECTURE.md)

1. **ONE enforcement boundary** — only `enforcement.py` may deny operations
2. **NO permission oracles** — never ask "am I allowed?" outside enforcement
3. **WorldAdapter = resolution** — resolves paths to RootCategory, NOT permission decisions
4. **Enforcement = decisions** — decides allow/deny at execution time only

### Visibility Scope Clarification

Per user clarification:
- **Vanilla should ALWAYS be in active playset** → by that route, always in visibility scope
- **`ck3_search` should NOT filter visibility** — WorldAdapter function should handle scope
- **WIP path is just a config value** → no `is_wip_path()` oracle function needed

---

## Fix Plan

### Phase 1: Data Fix (Immediate)

**Problem:** Jan 28th playset file missing `local_mods_folder` field

**Fix:** Add missing field to playset JSON:
```json
{
  "local_mods_folder": "C:/Users/nateb/Documents/Paradox Interactive/Crusader Kings III/mod"
}
```

**Location:** `playsets/MSC Religion Expanded Jan 28th_playset.json`

**Mode Required:** ck3raven-dev (playset currently classified as CK3RAVEN_SOURCE)

---

### Phase 2: Schema Validation

**Problem:** `_load_playset_from_json()` silently accepts missing required fields

**Fix:** Add validation in `server.py`:
```python
REQUIRED_PLAYSET_FIELDS = ["name", "mods", "local_mods_folder"]

def _load_playset_from_json(playset_path: Path) -> dict:
    data = json.loads(playset_path.read_text())
    
    missing = [f for f in REQUIRED_PLAYSET_FIELDS if f not in data]
    if missing:
        raise ValueError(f"Playset {playset_path.name} missing required fields: {missing}")
    
    # ... rest of loading logic
```

**Location:** `tools/ck3lens_mcp/server.py` lines ~327-402

---

### Phase 3: Move Playsets to User Domain

**Problem:** Playsets are in `ck3raven/playsets/` which is classified as `CK3RAVEN_SOURCE` (ROOT_REPO). ck3lens mode cannot write to ROOT_REPO.

**Current Classification:**
- `ck3raven/playsets/` → RootCategory.ROOT_REPO → ck3lens: read=True, write=False

**Solution Option B (User Preferred):** Move playsets to `~/.ck3raven/playsets/`

This location would fall under a new domain. Options:

| Option | Path | RootCategory | ck3lens write? |
|--------|------|--------------|----------------|
| B1 | `~/.ck3raven/playsets/` | Extend ROOT_WIP scope | Yes |
| B2 | `~/.ck3raven/playsets/` | New ROOT_USERDATA category | Yes |
| B3 | `~/.ck3raven/playsets/` | Under ROOT_UTILITIES | Needs matrix update |

**Recommendation:** Option B1 — Treat `~/.ck3raven/` as user data root, with `wip/` as one subdomain and `playsets/` as another. Both should be writable by ck3lens.

**Implementation:**
1. Rename ROOT_WIP to ROOT_CK3RAVEN_DATA (covers all of `~/.ck3raven/`)
2. Or: Create path classification that routes `~/.ck3raven/*` appropriately
3. Update capability matrix if needed
4. Migrate existing playsets from `ck3raven/playsets/` to `~/.ck3raven/playsets/`
5. Update manifest path logic

---

### Phase 4: Remove Oracle Functions

**Problem:** `is_wip_path()` and similar functions violate NO-ORACLE rule

**Banned Pattern:**
```python
# ❌ BANNED - oracle function
if is_wip_path(path):
    return ScopeDomain.WIP_WORKSPACE
```

**Canonical Pattern:**
```python
# ✓ CORRECT - path resolution returns RootCategory
result = world_adapter.resolve(path)
# result.root_category == RootCategory.ROOT_WIP
# enforcement.py uses root_category for decisions
```

**Fix:**
1. Delete `is_wip_path()` from `wip_workspace.py`
2. Delete `is_any_wip_path()` 
3. WIP path is just a config value: `config.wip_path` or from RootCategory lookup
4. Path classification happens in `WorldAdapter.resolve()` only
5. Replace all usages with proper resolution flow

**Files to Update:**
- `tools/ck3lens_mcp/ck3lens/policy/wip_workspace.py` — remove oracle functions
- `tools/ck3lens_mcp/ck3lens/policy/ck3lens_rules.py` — update `classify_path_domain()`
- Any callers of `is_wip_path()` — use resolution instead

---

### Phase 5: Visibility Filtering Architecture

**Problem:** `ck3_db_query` and `ck3_search_mods` bypass visibility scope

**Clarification from User:**
- `ck3_search` should NOT filter visibility internally
- A WorldAdapter function should handle scope filtering
- Vanilla is always in active playset → always in visibility

**Options:**

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A | DbHandle applies CVID filter automatically | Transparent, hard to bypass | May filter when not wanted |
| B | WorldAdapter provides `get_visible_cvids()` | Explicit, callers opt-in | Easy to forget |
| C | Deny raw SQL in ck3lens mode | Safe, forces proper tools | Breaks power-user queries |

**Recommendation:** Approach A with opt-out

The DbHandle (from Section 8 of CANONICAL_ARCHITECTURE.md) already has `_cvid_filter` field. Tools should:
1. Get DbHandle from WorldAdapter
2. DbHandle auto-filters by playset CVIDs
3. For tools needing unfiltered access, use explicit `unfiltered=True` parameter

**Implementation:**
1. `ck3_search_mods` — query through DbHandle, not raw connection
2. `ck3_db_query` — either:
   - Route through DbHandle (applies filter)
   - Or add prominent warning: "Returns unfiltered data from all indexed content"

---

### Phase 6: Fix Vanilla/Mod Write Enforcement

**Problem:** In ck3raven-dev mode, `ck3_file write` to `mod_name="vanilla"` succeeds when it should be denied.

**Evidence from 2026-02-03 testing:**
```
Tool: ck3_file
Args: command="write", mod_name="vanilla", rel_path="common/test.txt", content="test content"
Expected: EN-WRITE-D-xxx (denial)
Actual: EN-WRITE-S-001 (success!) - wrote to vanilla game folder
```

**Root Cause:** Enforcement is not checking that vanilla/mod writes are absolutely prohibited in ck3raven-dev mode. The mode instructions state:
> "ABSOLUTE PROHIBITION: Cannot write to ANY mod files (local, workshop, vanilla)"

**Fix:**
1. In `enforcement.py`, add check for ck3raven-dev mode
2. If target is mod/vanilla/workshop filesystem → return DENY
3. Only ck3raven source, WIP, and database are writable

---

### Phase 7: Fix ck3raven-dev Addressing (Inverted Behavior)

**Problem:** In ck3raven-dev mode, addressing behavior is inverted:
- `mod_name="Artifact Manager"` with `rel_path` → **WORKS** (should fail - not valid for this mode)
- Raw `path` to Steam workshop file → **FAILS** (should work - ck3raven-dev can read ROOT_STEAM)

**Evidence from 2026-02-03 testing:**
```
# mod_name addressing (should NOT work in ck3raven-dev)
Tool: ck3_file read, mod_name="Artifact Manager", rel_path="descriptor.mod"
Result: WA-READ-S-001 (SUCCESS - unexpected)

# Raw path addressing (SHOULD work in ck3raven-dev for reads)
Tool: ck3_file read, path="C:\Program Files (x86)\Steam\steamapps\workshop\content\1158310\2886417277\descriptor.mod"
Result: WA-RES-I-001 (FAIL - unexpected)
```

**Root Cause:** WorldAdapter is not properly implementing mode-aware addressing:
- In ck3raven-dev, raw paths should be primary
- mod_name addressing should be rejected or deprioritized
- ROOT_STEAM should be visible for reads in ck3raven-dev

**Fix:**
1. Review WorldAdapter path resolution for ck3raven-dev mode
2. Ensure ROOT_STEAM paths resolve correctly for reads
3. Consider rejecting mod_name addressing entirely in ck3raven-dev mode
4. Or: implement fallback (try raw path first, then mod_name if in ck3lens mode)

---

## Questions for User

1. **Phase 3 (Playset Location):** Confirm Option B1 — extend `~/.ck3raven/` as user data root with playsets subdirectory?

2. **Phase 5 (Visibility):** Should `ck3_db_query` raw SQL:
   - Auto-filter via DbHandle (transparent)
   - Require explicit `unfiltered=True` to bypass
   - Or just add warning in output that data is unfiltered?

3. **Phase 4 (Oracle Removal):** Should `is_wip_path()` removal be:
   - Part of this fix
   - Separate architectural cleanup task

---

## Validation Tests

After implementation:

```python
# Test 1: Playset loads with all required fields
scope = _get_session_scope()
assert scope["local_mods_folder"] != ""
assert len(scope["mod_list"]) > 0

# Test 2: ck3_playset(mods) returns mods
result = ck3_playset(command="mods")
assert len(result["mods"]) > 0

# Test 3: ck3_search_mods respects visibility
result = ck3_search_mods(query="KGD")  # Not in active playset
assert len(result["mods"]) == 0  # Should not find it

# Test 4: Playset files writable in ck3lens mode
# (After migration to ~/.ck3raven/playsets/)
result = ck3_file(command="write", path="~/.ck3raven/playsets/test.json", ...)
assert result["success"] == True
```

---

## Appendix: Banned Terms Found

| Term | Location | Violation |
|------|----------|-----------|
| `is_wip_path()` | `wip_workspace.py:182` | ORACLE-01 |
| `is_any_wip_path()` | `wip_workspace.py:199` | ORACLE-01 |
| `classify_path_domain()` returning ScopeDomain | `ck3lens_rules.py:102` | Potentially fine if used for resolution only |

---

## Implementation Order

1. **Phase 1** — Immediate data fix (add `local_mods_folder` to playset)
2. **Phase 2** — Schema validation (prevent future silent failures)
3. **Phase 3** — Move playsets to `~/.ck3raven/playsets/` 
4. **Phase 4** — Remove oracle functions
5. **Phase 5** — Visibility filtering via DbHandle
6. **Phase 6** — Fix vanilla/mod write enforcement in ck3raven-dev
7. **Phase 7** — Fix ck3raven-dev addressing (raw paths should work, mod_name should not)

Phases 1-2 are quick wins. Phases 3-5 are architectural improvements. Phases 6-7 are critical enforcement bugs.
