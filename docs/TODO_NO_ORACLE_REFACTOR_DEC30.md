# NO-ORACLE Refactor Outstanding TODOs - December 30, 2025

## Branch: `agent/no-oracle-refactor-dec30`

## Completed This Session

1. ✅ Deleted `local_mods.py` module entirely
2. ✅ Inlined file operations into `unified_tools.py` (no more BANNED imports)
3. ✅ Removed `local_mods` import from `server.py`
4. ✅ Archived legacy MCP tools in `server.py` (deregistered `ck3_list_local_mods`, etc.)
5. ✅ Fixed `ck3_playset(command="add_mod")` to add to `mods[]` not `local_mods[]`
6. ✅ Fixed playset scope loading to derive editable mods from `mods[]` + `local_mods_folder` path
7. ✅ Created root `.vscode/launch.json` and `tasks.json` for extension development

---

## Outstanding: Remaining `local_mods` Linter Errors (35 total)

### High Priority - MCP Server (`server.py`)

| Line | Issue |
|------|-------|
| 637 | `local_mods: Optional[list[str]] = None` - Parameter in deprecated `ck3_init_session()` |
| 4033 | `local_mods.write_file()` call in `ck3_create_override_patch()` - **BROKEN** (module deleted!) |
| 4086 | Another `local_mods` reference in same function |

**Action:** `ck3_create_override_patch()` needs to be updated to use inlined file ops or call `ck3_file()`.

### Medium Priority - Bridge Server (VS Code Extension)

| File | Line | Issue |
|------|------|-------|
| `bridge/server.py` | 179 | `local_mods_result = self.list_local_mods({})` |
| `bridge/server.py` | 187 | `local_mods = local_mods_result.get("local_mods", ...)` |

**Action:** Bridge has its own `list_local_mods()` method that reads wrong schema. Needs to read `mods[]` and filter by `local_mods_folder`.

### Medium Priority - WIP Workspace

| File | Line | Issue |
|------|------|-------|
| `policy/wip_workspace.py` | 442 | `local_mods` reference |
| `policy/wip_workspace.py` | 467 | `local_mods` reference |

---

## Outstanding: Path Resolution Linter Errors

These are `.resolve()` and `.relative_to()` calls outside canonical path modules. Some may be legitimate (WIP sandbox paths, etc.) but need review:

### `script_sandbox.py` (8 errors)
- Lines: 125, 130, 153, 158, 208, 295, 315
- These are for WIP sandbox containment checks - may need `# noqa` if legitimate

### `semantic.py` (9 errors)
- Lines: 262, 302, 367, 389, 412, 720, 771, 791, 813
- These appear to be for display purposes (formatting relative paths)

### `server.py` (5 errors)
- Lines: 359, 2150, 2186, 4230, 4238
- Mixed - some for folder resolution, some for path display

### `unified_tools.py` (1 error)
- Line 1532: `.relative_to()` call

### `db_queries.py` (1 error)
- Line 286: `Path(...).resolve()`

---

## Outstanding: Extension Dev Host Python Path

The extension tries to use:
```
c:\Users\nateb\Documents\CK3 Mod Project 1.18\.venv-1\Scripts\python.exe
```

But the correct path is:
```
c:\Users\nateb\Documents\CK3 Mod Project 1.18\ck3raven\.venv\Scripts\python.exe
```

**Location:** Check `ck3lens-explorer/src/extension.ts` or bridge configuration for Python path setting.

---

## Schema Clarification

### Correct Playset Schema (per `playset.schema.json`):

```json
{
  "mods": [...],           // THE list - all mods with load_order, enabled, path
  "local_mods_folder": "C:\\...\\mod"  // Path for containment check
}
```

### BANNED Pattern (was in code, never in schema):

```json
{
  "local_mods": [...]  // ❌ DOES NOT EXIST - editability is DERIVED
}
```

**Editability derivation:**
```python
editable = mod["path"].startswith(local_mods_folder)
```

---

## Next Session Priorities

1. **CRITICAL:** Fix `ck3_create_override_patch()` - it calls deleted `local_mods.write_file()`
2. Fix remaining `local_mods` references in server.py line 637 (parameter name)
3. Fix bridge server to use correct schema
4. Fix extension Python path configuration
5. Consider adding `# noqa: P1-A3` comments for legitimate `.resolve()` calls in sandbox code
6. Run linter again to verify all fixes

---

## Git Status

- Branch: `agent/no-oracle-refactor-dec30`
- 28+ commits ahead of main (before today's changes)
- Today's changes: NOT YET COMMITTED

**Recommend:** Commit today's changes before shutdown:
```bash
git add -A
git commit -m "Delete local_mods.py, archive legacy tools, fix playset schema usage"
```
