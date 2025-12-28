# Next Session TODO

## Completed This Session (Dec 29, 2025)

### WIP Script Execution Policy ✅
Wired ck3_exec to enforcement.py for WIP script runs:
- `WIP_SCRIPT_RUN` operation type added to enforcement.py
- `SCRIPT_RUN_WIP` token requirement (Tier A, auto-grantable)
- Script hash binding (token tied to specific script content)
- WIP workaround detection (repeated script execution without core changes = AUTO_DENY)
- Integration with `<repo>/.wip/` (ck3raven-dev mode)

**Files changed:**
- `tools/ck3lens_mcp/ck3lens/policy/enforcement.py` - Added WIP script enforcement
- `tools/ck3lens_mcp/ck3lens/policy/wip_workspace.py` - Added workaround detection tracking
- `tools/ck3lens_mcp/server.py` - Added `_detect_wip_script()` and routing
- `tools/ck3lens_mcp/ck3lens/unified_tools.py` - Added `record_core_source_change()` calls

Reference: `docs/CK3RAVEN_DEV_POLICY_ARCHITECTURE.md` Section 8 (WIP Scripts)

## Priority 1: Test the Phase 2 Commits

Verify the Phase 2 fixes work correctly:
1. `5b20f90` - Import path + CommandCategory enum fixes
2. `1153275` - Centralized path normalization
3. `3603943` - WorldAdapter BEFORE enforcement order
4. `8faaf79` - NOT_FOUND vs DENY semantic consistency
5. `a105d95` - WIP script execution policy

Run through common workflows:
- `ck3_file read/write/edit` on contract-allowed paths
- `ck3_file read` on paths outside contract (should work for reads)
- `ck3_exec` with various command types
- WIP script execution test (create .wip/ script, try to run)
- Verify workaround detection (same script twice without core changes)

## Priority 2: Push and Merge

- Push branch `agent/wcp-2025-12-28-70e797-enforcement-gate`
- Review and merge to main
- Close contract `wcp-2025-12-28-70e797` (old session)
- Close contract `wcp-2025-12-29-35c9de` (current session)

## Priority 3: Additional WIP Script Features (Future)

Consider adding:
- WIP intent declaration in token request (currently requires separate tracking)
- Auto-wipe WIP directory on session start (already in wip_workspace.py, needs wiring)
- VS Code UI for WIP script approval (Tier A auto-grant with notification)

## Completed Previously (Dec 28-29, 2025)

- ✅ Fix CommandCategory.WRITE → WRITE_IN_SCOPE/WRITE_OUT_OF_SCOPE
- ✅ Fix import path: `.work_contracts` → `..work_contracts`
- ✅ Centralized path normalization in enforcement.py
- ✅ WorldAdapter visibility check BEFORE enforcement gate
- ✅ NOT_FOUND vs DENY semantic consistency
