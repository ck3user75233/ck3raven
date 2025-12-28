# Next Session TODO

## Completed This Session (Dec 29, 2025)

### LensWorld Sandbox for ck3lens WIP Scripts ✅
Per Canonical Initialization #9: "The system must constrain execution, not rely on script inspection."

**Implementation:**
- `lensworld_sandbox.py` - Runtime sandbox that monkey-patches file operations
  - Intercepts `builtins.open`, `Path.exists/is_file/is_dir`, `os.path.exists`, `os.listdir`, `os.makedirs`
  - All paths validated against allowed set (WIP, active local mods, utility paths)
  - Out-of-scope access returns `FileNotFoundError` (not `PermissionError` - LensWorld principle)
  - Full audit trail of allowed/blocked operations

- `server.py ck3_exec` - Mode-aware WIP script handling:
  - **ck3lens mode**: Token B (SCRIPT_EXECUTE) required + sandboxed execution
  - **ck3raven-dev mode**: Enforcement gate (existing logic, no sandbox - infra mode)

**Files Created:**
- `tools/ck3lens_mcp/ck3lens/policy/lensworld_sandbox.py`

**Files Modified:**
- `tools/ck3lens_mcp/server.py` - Sandbox integration for ck3lens WIP scripts

Commit: `b6a65e4`

### WIP Script Execution Policy (ck3raven-dev) ✅
Wired ck3_exec to enforcement.py for WIP script runs:
- `WIP_SCRIPT_RUN` operation type added to enforcement.py
- `SCRIPT_RUN_WIP` token requirement (Tier A, auto-grantable)
- Script hash binding (token tied to specific script content)
- WIP workaround detection (repeated script execution without core changes = AUTO_DENY)
- Integration with `<repo>/.wip/` (ck3raven-dev mode)

Commit: `a105d95`

## Priority 1: Test the Phase 2 + Sandbox Commits

Verify all fixes work correctly (8 commits ready to push):
1. `5b20f90` - Import path + CommandCategory enum fixes
2. `1153275` - Centralized path normalization
3. `3603943` - WorldAdapter BEFORE enforcement order
4. `8faaf79` - NOT_FOUND vs DENY semantic consistency
5. `a105d95` - WIP script execution policy (ck3raven-dev)
6. `b6a65e4` - LensWorld sandbox (ck3lens)

Run through common workflows:
- `ck3_file read/write/edit` on contract-allowed paths
- `ck3_file read` on paths outside contract (should work for reads)
- `ck3_exec` with various command types
- WIP script sandbox test (ck3lens mode):
  - Create script in WIP
  - Try to access out-of-scope paths (should get FileNotFoundError)
  - Try to write to active local mod (should work with declared path)
- Verify workaround detection (ck3raven-dev mode)

## Priority 2: Push and Merge

- Push branch `agent/wcp-2025-12-28-70e797-enforcement-gate`
- Review and merge to main
- Close contract `wcp-2025-12-28-70e797` (old session)
- Close contract `wcp-2025-12-29-35c9de` (current session)

## Priority 3: Review Remaining Canonical Initialization Sections

User reviewed Section #9 (WIP Scripting) - now implemented.
Remaining sections to review with user:
- #1-8: Content unknown, need user to present or agent to read from `docs/drafts/INITIALIZATION_PROPOSAL.md`

## Priority 4: Additional Features (Future)

Consider adding:
- WIP intent declaration in token request
- Auto-wipe WIP directory on session start (already in wip_workspace.py, needs wiring)
- VS Code UI for WIP script approval (Tier A auto-grant with notification)
- Sandbox coverage for subprocess (currently in-process only)

## Completed Previously (Dec 28-29, 2025)

- ✅ Fix CommandCategory.WRITE → WRITE_IN_SCOPE/WRITE_OUT_OF_SCOPE
- ✅ Fix import path: `.work_contracts` → `..work_contracts`
- ✅ Centralized path normalization in enforcement.py
- ✅ WorldAdapter visibility check BEFORE enforcement gate
- ✅ NOT_FOUND vs DENY semantic consistency
