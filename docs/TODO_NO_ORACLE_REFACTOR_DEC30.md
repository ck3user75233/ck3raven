# NO-ORACLE Refactor Outstanding TODOs - December 30, 2025

## Branch: `agent/no-oracle-refactor-dec30`

---

## Completed This Session (Session 2 - Evening)

### Machine-Specific Path Fixes
1. ✅ Removed all "AI Workspace" hardcoded paths from runtime code
2. ✅ Removed `.venv-1` machine-specific naming convention from setupWizard.ts
3. ✅ Fixed pythonBridge.ts - now uses `CK3RAVEN_PATH` env var or `.ck3raven/ck3raven`
4. ✅ Fixed mcpServerProvider.ts - removed duplicate venv checks
5. ✅ Fixed rulesView.ts - uses `~/.ck3raven/` for config
6. ✅ Fixed workspace.py - DEFAULT_CONFIG_PATH now `~/.ck3raven/ck3lens_config.yaml`
7. ✅ Fixed server.py - LEGACY_PLAYSET_FILE now `~/.ck3raven/active_mod_paths.json`
8. ✅ Fixed bridge/server.py - uses env var first, then standard locations
9. ✅ Fixed test_policy_demo.py and test_policy_health.py - repo-relative paths
10. ✅ Updated .gitignore - added VS Code MCP configs and ck3lens configs

### NO-ORACLE Refactor Progress
11. ✅ Removed 3 unauthorized allowlist entries from canonical_phase1_lint.py
12. ✅ Refactored script_sandbox.py - removed WIP shortcuts, uses WorldAdapter
13. ✅ Refactored unified_tools.py `_file_list()` - uses WorldAdapter.resolve()
14. ✅ Moved semantic.py to scripts/ck3_syntax_learner.py (standalone tool, not MCP layer)

---

## ⚠️ CRITICAL PENDING: BANNED Concepts Still in Codebase

### 1. `editable_mods` / `editable_mods_list` (server.py) - GUILTY

**Same as `local_mods` - a BANNED parallel authority list!**

| Line | Code |
|------|------|
| 349 | `editable_mods = [...]` - being created |
| 360 | `editable_mods_list` |
| 381 | reference |
| 5286 | reference |
| 7629 | reference |

**Action:** Destroy completely. Editability is DERIVED from `mods[]` + `local_mods_folder` containment check, never stored as a separate list.

### 2. `build_lens_from_scope()` (db_queries.py lines 220-324) - GUILTY

**User verdict: "BANNED CONCEPTS CLUBBING TOGETHER FOR A BANNED IDEA RIOT"**

This function:
- Creates parallel path normalization outside WorldAdapter
- Builds mod lists and filters them
- Uses `Path.resolve()` outside canonical boundary
- Basically reimplements what WorldAdapter should do

**Action:** Destroy and replace with WorldAdapter-based resolution.

### 3. `normalize_path_for_comparison()` (world_adapter.py) - VERDICT PENDING

Added during this session as utility at top of world_adapter.py. User questioned whether this is itself a BANNED splinter concept that fails to go through WorldAdapter.

**Analysis needed:** Is this a bootstrap utility (OK if used by WorldAdapter itself) or an oracle bypass (BANNED)?

---

## ⚠️ MAJOR PENDING: Contract & Token System

User identified this as a significant open area:

1. **Contract validation** - not being properly enforced
2. **Tokens** - either auto-granted or adherence not checked at closure
3. **Closure step** - not validating work matched contract scope

This is architecturally complex and needs dedicated session.

---

## PENDING: Setup Wizard

Need a proper installation/setup wizard so users can:
- Clone repo anywhere and get it running
- No machine-specific paths in committed code
- Auto-detect or prompt for: Python venv, CK3 install path, workshop path, local mods folder

A setupWizard.ts exists but may need review for completeness.

---

## PENDING: Documentation Updates (Low Priority)

These files have hardcoded paths in documentation/examples (not runtime code):
- `tools/ck3lens_mcp/docs/TESTING.md` - has "AI Workspace" paths
- `tools/ck3lens_mcp/docs/SETUP.md` - has "AI Workspace" paths
- `tools/ck3lens-explorer/DESIGN.md` - mentions `.venv-1`

**Action:** Update to use portable/relative paths or placeholders like `<your-ck3raven-path>`.

---

## Previous Session (Session 1) Completed Items

1. ✅ Deleted `local_mods.py` module entirely
2. ✅ Inlined file operations into `unified_tools.py`
3. ✅ Removed `local_mods` import from `server.py`
4. ✅ Archived legacy MCP tools (deregistered `ck3_list_local_mods`, etc.)
5. ✅ Fixed `ck3_playset(command="add_mod")` to add to `mods[]` not `local_mods[]`
6. ✅ Fixed playset scope loading to derive editable mods from `mods[]` + path
7. ✅ Created root `.vscode/launch.json` and `tasks.json`

---

## Previous Session Outstanding Items (Still Need Fixing)

### `ck3_create_override_patch()` - BROKEN
- Line 4033: `local_mods.write_file()` - calls deleted module!
- **Action:** Update to use inlined file ops or `ck3_file()`

### Bridge Server Schema
- `bridge/server.py` lines 179, 187
- Reads wrong schema - needs to read `mods[]` and filter by path

### WIP Workspace
- `policy/wip_workspace.py` lines 442, 467
- `local_mods` references

---

## Next Session Priority Order

1. **DESTROY** `editable_mods` in server.py (same BANNED idea as `local_mods`)
2. **DESTROY** `build_lens_from_scope()` in db_queries.py (BANNED idea riot)
3. **VERDICT** on `normalize_path_for_comparison()` - keep or destroy
4. **FIX** `ck3_create_override_patch()` - broken import
5. **FIX** remaining `local_mods` references
6. **DESIGN** contract/token validation architecture
7. **REVIEW** setup wizard for completeness

---

## Git Status

- Branch: `agent/no-oracle-refactor-dec30`
- Previous commits: 28+ ahead of main
- This session: Multiple files changed, needs commit/push
