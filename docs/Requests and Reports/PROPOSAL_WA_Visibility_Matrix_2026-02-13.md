# Proposal: WorldAdapter Visibility Matrix

**Date:** 2026-02-13  
**Status:** Proposal — Awaiting Review  
**Scope:** `world_adapter.py`, new `visibility_matrix.py`, `CANONICAL_ARCHITECTURE.md`  
**Risk:** Medium — Changes core resolution flow

---

## Terminology

| Term | Meaning | Module |
|------|---------|--------|
| **Resolution** | Structural classification: which RootCategory does this path belong to? What is the absolute path? | `WorldAdapter.classify_path()`, `_translate_raw_path()` |
| **Visibility** | Mode-aware filtering: can this agent **see** paths in this RootCategory? | New `visibility_matrix.py`, walked by `WorldAdapter.resolve()` |
| **Permission** | Operation gating: can this agent **do X** to this resolved path? | `enforcement.py` + `capability_matrix.py` |

Resolution and visibility are NOT the same thing. Resolution answers "where is this?" Visibility answers "does this exist for you?"

---

## Problem Statement

During the consolidation of `LensWorldAdapter` / `DevWorldAdapter` into a single `WorldAdapter`, inline mode-branching was correctly removed. The replacement — a visibility matrix that gates which RootCategories are visible per agent mode — was never built.

### Current State

1. **WA is mode-blind.** `self._mode` is stored but only checked for `"uninitiated"` rejection. Resolution and classification never read mode.
2. **CANONICAL_ARCHITECTURE.md Section 10** says: *"Resolution does NOT filter based on agent mode."*
3. **Section 9** says visibility differs by mode:
   - `ck3lens`: "Filtered to active playset (vanilla + enabled mods)"
   - `ck3raven-dev`: "ck3raven source + WIP workspace (mods NOT part of execution model)"
4. **Sections 9 and 10 contradict each other.** Resolution was made mode-agnostic; the visibility filtering was deleted but never replaced.


### What Works Today

- `_mod_paths` is built from playset mods. Those absolute paths ARE physically inside ROOT_STEAM — WA iterates them in `_translate_raw_path()` and matches mods correctly. No separate ROOT_STEAM handler is needed because the mod paths are Steam paths.
- Enforcement gates writes via the capability matrix.

### What's Broken

- A `ck3raven-dev` agent can resolve `mod:SomeMod/file.txt` if mods were passed at init. A `ck3lens` agent can resolve `ck3raven:/some/file.py` if ROOT_REPO is configured. WA doesn't know who's asking.
- `visible_cvids` is a dead field — stored at init, never queried during resolution.
- The doc promise in Section 9 (mode-filtered visibility) is unimplemented.

---

## Proposed Design

### Principle

> **WA describes what exists TO THE AGENT.**

The capability matrix defines what the agent can **do**. A visibility matrix defines what the agent can **see**. These are distinct concerns.

### Visibility Matrix (New File: `tools/ck3lens_mcp/ck3lens/visibility_matrix.py`)

Pure-data matrix keyed by `(mode, RootCategory)`, same pattern as `capability_matrix.py`:

```python
# visibility_matrix.py — pure data, walked by WorldAdapter

from ck3lens.paths import RootCategory

VISIBILITY_MATRIX: dict[tuple[str, RootCategory], bool] = {
    # ck3lens: game content, workshop mods, user docs, data, vscode — no repo
    ("ck3lens", RootCategory.ROOT_GAME):           True,
    ("ck3lens", RootCategory.ROOT_STEAM):          True,
    ("ck3lens", RootCategory.ROOT_USER_DOCS):      True,
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA):  True,
    ("ck3lens", RootCategory.ROOT_VSCODE):         True,
    ("ck3lens", RootCategory.ROOT_REPO):           False,
    ("ck3lens", RootCategory.ROOT_EXTERNAL):       False,

    # ck3raven-dev: repo, data, vanilla (reference), vscode — no workshop mods, no user docs
    ("ck3raven-dev", RootCategory.ROOT_REPO):           True,
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA):  True,
    ("ck3raven-dev", RootCategory.ROOT_GAME):            True,
    ("ck3raven-dev", RootCategory.ROOT_VSCODE):          True,
    ("ck3raven-dev", RootCategory.ROOT_STEAM):           False,
    ("ck3raven-dev", RootCategory.ROOT_USER_DOCS):       False,
    ("ck3raven-dev", RootCategory.ROOT_EXTERNAL):        False,
}

def is_visible(mode: str, root_category: RootCategory) -> bool:
    """Pure lookup. Returns False for unknown combinations."""
    return VISIBILITY_MATRIX.get((mode, root_category), False)
```

### WA Change

In `resolve()`, after `_resolve_to_absolute()` produces a `ResolutionResult` with `root_category`, check visibility. Resolution stays structural and mode-agnostic; the visibility gate happens after:

```python
def resolve(self, path_or_address: str) -> ResolutionResult:
    if self._mode == "uninitiated":
        return ResolutionResult.not_found(...)

    address = self._parse_or_translate(path_or_address)
    if address.address_type == AddressType.UNKNOWN:
        return ResolutionResult.not_found(...)

    result = self._resolve_to_absolute(address)
    if not result.found:
        return result

    # Visibility gate — is this root category visible to this agent?
    from ck3lens.visibility_matrix import is_visible
    if result.root_category and not is_visible(self._mode, result.root_category):
        return ResolutionResult.not_found(
            path_or_address,
            f"Not visible in {self._mode} mode"
        )

    return result
```

WA walks the visibility matrix the same way enforcement walks the capability matrix. No inline branching. Pure data drives behavior.

### Cleanup

1. Delete `visible_cvids` from `__init__`, `create()`, and the instance variable — dead field.
2. Delete the `frozenset(m.cvid ...)` extraction block in `create()`.

### Doc Updates

1. **Section 10**: Replace *"Resolution does NOT filter based on agent mode"* with: *"Resolution is structural and mode-agnostic. Visibility filtering happens after resolution using the visibility matrix (`visibility_matrix.py`), which gates by (mode, RootCategory)."*
2. **Section 9**: Reference `visibility_matrix.py` as the implementation of mode-specific visibility.
3. **Resolve the Section 9/10 contradiction** — they now agree: visibility matrix is the mechanism.

---

## What This Does NOT Change

- **Resolution** (`classify_path`, `_translate_raw_path`) stays structural, mode-agnostic.
- **Enforcement** remains the ONLY gate for allow/deny on operations.
- **`_mod_paths`** continues scoping mod resolution to playset mods.
- **`classify_path()`** unchanged — used by enforcement, not visibility.

---

## Implementation Steps

1. Create `tools/ck3lens_mcp/ck3lens/visibility_matrix.py` (~30 lines, pure data)
2. Add visibility gate to `WorldAdapter.resolve()` (~5 lines, after resolution)
3. Delete `visible_cvids` from WA (`__init__`, `create()`)
4. Update `CANONICAL_ARCHITECTURE.md` Sections 9 and 10
5. Re-lock linter lock
6. Add `visibility_matrix.py` to linter lock tracked files
