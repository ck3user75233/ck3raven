# Next Session TODO

## Priority 1: WIP Script Execution Policy

**Status:** NOT DONE

Wire ck3_exec to enforcement.py for WIP script runs:
- `SCRIPT_EXECUTE` token requirement for running Python in WIP
- Script hash binding (token tied to specific script content)
- WIP workaround detection (repeated script execution without core changes = AUTO_DENY)
- Integration with `~/.ck3raven/wip/` (ck3lens) or `<repo>/.wip/` (ck3raven-dev)

Reference: `docs/CK3RAVEN_DEV_POLICY_ARCHITECTURE.md` section on WIP Intents

## Priority 2: Test the 4 Commits

Verify the Phase 2 fixes work correctly:
1. `5b20f90` - Import path + CommandCategory enum fixes
2. `1153275` - Centralized path normalization
3. `3603943` - WorldAdapter BEFORE enforcement order
4. `8faaf79` - NOT_FOUND vs DENY semantic consistency

Run through common workflows:
- `ck3_file read/write/edit` on contract-allowed paths
- `ck3_file read` on paths outside contract (should work for reads)
- `ck3_exec` with various command types
- Verify NOT_FOUND returns for paths outside lens scope

## Priority 3: Push and Merge

- Push branch `agent/wcp-2025-12-28-70e797-enforcement-gate`
- Review and merge to main
- Close contract `wcp-2025-12-28-70e797`

## Completed This Session (Dec 28-29, 2025)

- ✅ Fix CommandCategory.WRITE → WRITE_IN_SCOPE/WRITE_OUT_OF_SCOPE
- ✅ Fix import path: `.work_contracts` → `..work_contracts`
- ✅ Centralized path normalization in enforcement.py
- ✅ WorldAdapter visibility check BEFORE enforcement gate
- ✅ NOT_FOUND vs DENY semantic consistency
