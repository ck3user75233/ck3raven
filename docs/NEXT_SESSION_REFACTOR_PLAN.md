# NO-ORACLE REFACTOR IMPLEMENTATION PLAN

> **Created:** December 29, 2025  
> **Status:** READY FOR NEXT SESSION  
> **Reference:** `docs/CANONICAL REFACTOR INSTRUCTIONS.md`

---

## CURRENT STATE ASSESSMENT

### Playset JSON: MOSTLY CORRECT ✅
- `mods[]` exists as single array
- `local_mods_folder` exists
- BUT: `live_mods` key found in example_playset.json (BANNED IDEA)

### Code: PRE-REFACTOR STATE ❌
The following banned patterns still exist:

| Pattern | Files Affected |
|---------|----------------|
| `can_write_path` | mod_files.py |
| `is_path_allowed` | local_mods.py, workspace.py, tests |
| `is_path_writable` | playset_scope.py |
| `is_writable` | 16 occurrences across unified_tools.py, world_adapter.py |
| `mod_roots` | 50+ occurrences across many files |
| `mod_root` | 80+ occurrences (legitimate as `_session.mod_root` for folder path) |

---

## QUESTIONS BEFORE PROCEEDING

### Q1: `mod_root` vs `local_mods_folder` disambiguation

The CANONICAL INSTRUCTIONS ban `mod_roots` and suggest `mod_paths` as replacement.

However, `Session.mod_root` currently holds the path to the local mods folder:
```
C:\Users\nateb\Documents\Paradox Interactive\Crusader Kings III\mod
```

**Question:** Should this be renamed to `local_mods_folder` (matching the playset JSON key)?

My recommendation: YES - rename `_session.mod_root` → `_session.local_mods_folder`

### Q2: `mod_roots` (plural) vs `mod_paths`

`PlaysetScope.mod_roots: Set[Path]` holds paths to all active mods.

Per CANONICAL INSTRUCTIONS:
- ❌ `mod_roots` (banned - implies authority)
- ✅ `mod_paths` (allowed - describes structure)

**Question:** Confirm the rename `mod_roots` → `mod_paths` everywhere?

### Q3: `local_mod_roots` handling

Currently `local_mod_roots` is used to track which mod paths are under `local_mods_folder`.

Options:
1. Rename to `local_mod_paths` (structural fact)
2. Eliminate entirely - derive at enforcement boundary via path check

My recommendation: Option 2 - eliminate the derived set, compute at enforcement

### Q4: Playset JSON `live_mods` key

The example_playset.json has a `live_mods` key which is a BANNED IDEA.

**Question:** Should I remove this from the example file?

---

## IMPLEMENTATION PLAN

### Phase 1: Update PLAYSET_ARCHITECTURE.md
- Remove all references to `mod_roots`
- Replace with `mod_paths` where structural descriptor needed
- Ensure NO permission-check language
- Add explicit cross-reference to CANONICAL REFACTOR INSTRUCTIONS

### Phase 2: Terminology Replacement (File by File)

#### 2.1 playset_scope.py
```
is_path_writable() → path_under_local_mods()
mod_roots → mod_paths
local_mod_roots → REMOVE (compute at enforcement)
```

#### 2.2 world_adapter.py
```
is_writable → ui_hint_potentially_editable
All 16 occurrences
Update docstrings with NO-ORACLE RULE
```

#### 2.3 workspace.py
```
mod_root → local_mods_folder
is_path_allowed → REMOVE
LocalMod class → verify data-only
```

#### 2.4 unified_tools.py
```
Remove early denial checks based on is_writable
Update all references to ui_hint_potentially_editable
Ensure NO control flow based on this field
```

#### 2.5 mod_files.py
```
can_write_path → REMOVE
Verify _enforce_write_boundary is the ONLY permission gate
```

#### 2.6 local_mods.py
```
is_path_allowed → REMOVE
```

#### 2.7 server.py
```
mod_root references → local_mods_folder
mod_roots references → mod_paths
Verify no permission oracles
```

#### 2.8 Policy files (hard_gates.py, ck3lens_rules.py, etc.)
```
local_mod_roots → compute at enforcement OR pass mod_paths
mod_roots → mod_paths
Verify NO early denial outside enforcement
```

### Phase 3: Remove Banned Keys from JSON
- Remove `live_mods` from example_playset.json

### Phase 4: Verification
1. Run mechanical no-oracle linter (grep for banned patterns)
2. Test Python imports
3. Clear pycache
4. Reload VS Code
5. Initialize MCP with ck3raven-dev mode
6. Run smoke tests

---

## STOP CONDITION

Per CANONICAL INSTRUCTIONS, stop when:
1. Banned terms removed
2. No-oracle linter passes
3. MCP smoke tests pass

NO further cleanup, improvements, or renames after this.

---

## FILES TO MODIFY (Ordered by Dependency)

1. `workspace.py` - Core data structures
2. `playset_scope.py` - Visibility descriptors
3. `world_adapter.py` - Resolution results
4. `world_router.py` - Docstrings
5. `mod_files.py` - Enforcement boundary
6. `git_ops.py` - Enforcement boundary
7. `local_mods.py` - Remove permission helpers
8. `unified_tools.py` - Remove early denials
9. `server.py` - Update references
10. `hard_gates.py` - Policy enforcement
11. `ck3lens_rules.py` - Policy rules
12. `script_sandbox.py` - Sandbox enforcement
13. `lensworld_sandbox.py` - Sandbox enforcement
14. `PLAYSET_ARCHITECTURE.md` - Documentation

---

## ESTIMATED CHANGES

| Category | Count |
|----------|-------|
| `mod_roots` → `mod_paths` | ~50 |
| `local_mod_roots` → remove/compute | ~20 |
| `is_writable` → `ui_hint_potentially_editable` | ~16 |
| `is_path_writable` → `path_under_local_mods` | ~3 |
| `mod_root` → `local_mods_folder` | ~10 |
| Remove permission oracles | ~5 |
| Update docstrings | ~10 |

**Total: ~114 changes across 14 files**

