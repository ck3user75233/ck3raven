# Phase 2 Audit Report — February 13, 2026

> **Auditor:** Agent (Copilot session)  
> **Date:** February 13, 2026  
> **Method:** Codebase grep verification against PHASE_2_PROGRESS.md claims  
> **Scope:** Phase 2.1 completion status, Phase 2.2–2.5 readiness, staleness issues  
> **Reference Documents:**  
> - `docs/phase2contracts/PHASE_2_PROGRESS.md`  
> - `docs/phase2contracts/PHASE_2_DETERMINISTIC_GATES_PLAN.md` (Revision 3)  
> - `docs/phase2contracts/CK3_EXEC_SPRINT_0_DIRECTIVE.md`

---

## Phase 2 Progress Audit — Verified Against Codebase

### Progress Report Claims vs. Reality

| Claimed Item | Report Status | **Actual Status** | Evidence |
|---|---|---|---|
| `EnforcementResult` deleted | DONE | **CONFIRMED** | grep returns zero matches in enforcement.py |
| `enforce()` returns Reply via rb | DONE | **CONFIRMED** | enforcement.py has no dict returns, no EnforcementResult |
| `_gate()` collects ALL failures | DONE | **CONFIRMED** | commit ff24a5d |
| `Decision` enum eliminated from surface | DONE | **CONFIRMED** | only the word "decision" in a docstring context |
| server.py wrappers: `rb=rb` + `isinstance(Reply)` passthrough | DONE | **CONFIRMED** | Lines 1873 and 3968 show the pattern |
| `reply_linter.py` created | DONE | **SUPERSEDED** | commit fb65b1e merged it into TASL. **File no longer exists.** Progress report is stale on this row — should say "merged into TASL" |
| `_create_reply_builder` deleted | DONE | **CONFIRMED** | zero grep matches |
| `_file_read_raw` → Reply | DONE | **CONFIRMED** | returns `rb.success()`/`rb.invalid()` |
| `_file_write` → Reply | DONE | **CONFIRMED** | |
| `_file_write_raw` → Reply | DONE | **CONFIRMED** | |
| `_file_create_patch` → Reply | DONE | **CONFIRMED** | |
| TASL linter | DONE | **CONFIRMED** | `tools/compliance/tasl.py` exists, expanded to 17+ checks |
| Zero Pylance errors | DONE | **STALE** | We introduced/fixed a Pylance error in paths_doctor.py today. Needs re-verification across full workspace. |

### Phase 2.1 "What Remains" — Verified Status

#### A. `policy_decision` String Elimination (~5 sites in server.py)

**NOT DONE.** The progress report says ~5 sites remain. I confirmed **5 matches still exist** in server.py:

| Line | Context | Still a dict consumer? |
|---|---|---|
| 1879 | `policy_decision = result.get("policy_decision", "")` | **YES** — `ck3_file_impl` wrapper, dict fallback path. The `isinstance(result, Reply)` passthrough on L1873 catches Reply returns, but the dict path on L1879+ is still live for unconverted sub-functions. |
| 1883 | `if policy_decision == "DENY"` | **YES** — paired with above |
| 3973 | `policy_decision = result.get("policy", {}).get("decision", "")` | **YES** — `_ck3_exec_internal` wrapper, dict fallback path |
| 3976 | `if policy_decision == "PATH_NOT_FOUND"` | **YES** — paired with above |

**Assessment:** These are **migration seams**, not bugs. They handle dict returns from not-yet-converted sub-functions. They'll become dead code once all sub-functions return Reply. The L1879 site handles `ck3_file_impl` dict returns. The L3973 site handles `_ck3_exec_internal` dict returns.

#### B. Remaining Dict-Returning Sub-Functions

The progress report claimed ~18. Actual count from the codebase:

**unified_tools.py — functions with `-> dict:` or `-> Reply | dict:`:**

| Function | Return type | Category |
|---|---|---|
| `ck3_file_impl` (L780) | `Reply \| dict` | File ops dispatcher — still has dict paths |
| `_file_edit_raw` (L1169) | implicit dict | File ops |
| `_file_delete_raw` (L1430) | implicit dict | File ops |
| `_file_rename_raw` (L1453) | implicit dict | File ops |
| `_file_list_raw` (L1480) | implicit dict | File ops |
| `_folder_list_raw` (L1855) | implicit dict | Folder ops |
| `ck3_folder_impl` (L1818) | `-> dict:` | Folder ops dispatcher |
| `ck3_git_impl` (L2265) | `Reply \| dict` | Git dispatcher |
| `_git_ops_for_path` (L2091) | implicit dict | Git helper |
| All 6+ internal git helpers | implicit dict | Git helpers |
| `ck3_validate_impl` (L2441) | `-> dict:` | Validation dispatcher |
| `ck3_qbuilder_impl` (L2658) | `-> dict:` | QBuilder dispatcher |

That's roughly **15-18 functions** still returning dicts. The `return {` grep found **80+ dict returns** across unified_tools.py. This matches the progress report's ~18 function estimate.

However, commit `022f0f2` (Feb 12) says "Convert all dict-returning functions to Reply in server.py and unified_tools.py". **This commit message is misleading** — it appears to have converted the *major* ones (file read/write/patch) but left the above functions unconverted. The progress report is more accurate than the commit message.

#### C. `baseline_sha` Schema Addition

**NOT DONE.** Zero matches for `baseline_sha` in contract_v1.py. The ContractV1 dataclass does not have this field yet.

### Phase 2.2–2.5 Status

| Phase | Status | Verified |
|---|---|---|
| 2.2: Gate Infrastructure (`contract_gates.py`) | Not started | **CONFIRMED** — file does not exist |
| 2.3: Open Gates + Continuity | Not started | **CONFIRMED** |
| 2.4: Close Gates | Not started | **CONFIRMED** |
| 2.5: Escalation + Stash + Tests | Not started | **CONFIRMED** — no test_contract*.py or test_enforcement*.py exist |

### Progress Report Staleness Issues

1. **reply_linter.py row**: Says "created" but it was merged into TASL and deleted (commit fb65b1e). The progress report predates that merge.
2. **TASL linter row**: Says "8 checks" but TASL now has 17+ checks (commits 1d68eae, 71ab842, d91dca0 added many more). The progress report was written before these expansions.
3. **Date**: Says "February 12, 2026 (updated from Feb 11)" but commits on Feb 12-13 added significant work not reflected in the "What Remains" section.

---

## Recommended Next Steps

### Immediate (This Sprint — Phase 2.1 Completion)

**Priority 1: `baseline_sha` field addition**
- Add `baseline_sha: str | None = None` to `ContractV1` dataclass in contract_v1.py
- Minimal change, no behavior, unblocks Phase 2.3
- **Effort: 5 minutes**

**Priority 2: Remaining dict-returning functions → Reply**
- The ~15-18 functions listed above in unified_tools.py
- This is the largest remaining 2.1 work item
- **Sub-agent recommendation:** A focused sub-agent given ONLY unified_tools.py + Reply/ReplyBuilder patterns could convert these mechanically. Give it:
  - The 5 already-converted functions as templates (e.g., `_file_read_raw`, `_file_write_raw`)
  - A list of the ~15 target functions
  - Rule: every function must take `rb=None` param and return `Reply`, never `return {}`
- **Effort: 2-3 hours of careful work**

**Priority 3: Server.py migration seam cleanup**
- Once all sub-functions return Reply, the `policy_decision` dict-sniffing at L1879 and L3973 becomes dead code
- Replace with clean Reply passthrough
- The `_ck3_exec_internal` wrapper (L3973) is carved out per the exec directive — this seam stays until the exec rewrite
- **Effort: 30 minutes (once Priority 2 is done)**

### After Phase 2.1

**Phase 2.2: `contract_gates.py` + GateResult**
- New file with pure-function gates
- Register CT-GATE-* reply codes
- First gate: `gate_scope_feasibility` (mode × root × operation vs capability matrix)
- This is design-heavy, benefits from a single agent with full context of the capability matrix and enforcement.py

**Phase 2.3-2.5**: Sequential, each blocked by the prior

### Orthogonal Work (Not Phase 2)

These are from the current session's todo list and are independent of Phase 2:

| Item | Status | Dependency |
|---|---|---|
| Protect arch-lint files via `ck3_protect` | Pending HAT approval | None |
| Launcher DB resolution via WorldAdapter | Not started | None |
| Update progress report (staleness fixes) | Needed | After 2.1 completion |

---

## Sub-Agent Recommendations

**Sub-Agent A: "Dict→Reply Converter"** (for Priority 2)
- Scope: unified_tools.py only
- Task: Convert each of the ~15 dict-returning functions to Reply pattern
- Input context: 3 already-converted exemplars + ReplyBuilder API + reply code registry
- Question per function: "Does this function return `{...}` anywhere? Convert to `rb.success()`/`rb.invalid()`/`rb.error()`"
- Benefits from limited context (won't get distracted by server.py, enforcement, etc.)

**Sub-Agent B: "Pylance Error Sweep"** (validation)
- Scope: All .py files under tools/ck3lens_mcp/
- Task: Run Pylance diagnostics, report all errors
- Simple question: "Are there any type errors?"
- Should run after each batch of Dict→Reply conversions

---

## Session Context: Architectural Cleanup (Same Day)

In addition to Phase 2 auditing, the following architectural cleanup was performed in this session:

### Constants Demolished
- `DB_PATH` deleted from `paths.py` — canonical: `ROOT_CK3RAVEN_DATA / "ck3raven.db"` inline
- `LOCAL_MODS_FOLDER` deleted from `paths.py` — canonical: `ROOT_USER_DOCS / "mod"` inline
- `DEFAULT_CK3_MOD_DIR`, `DEFAULT_VANILLA_PATH`, `DEFAULT_DB_PATH` all replaced with canonical ROOT_* expressions

### Banned Terms Added (arch-lint)
- `DB_PATH`, `DEFAULT_CK3_MOD_DIR`, `DEFAULT_VANILLA_PATH`, `DEFAULT_DB_PATH`, `LOCAL_MODS_FOLDER` added to `BANNED_PATH_ORACLES` in `tools/arch_lint/patterns.py`
- Removed `local_mods_folder` from `RAW_ALLOWLIST_SUBSTRINGS` and `ALLOWLIST_TOKEN_SEQUENCES`

### Files Modified
- `tools/ck3lens_mcp/ck3lens/paths.py` — deleted DB_PATH and LOCAL_MODS_FOLDER constants
- `tools/ck3lens_mcp/ck3lens/paths_doctor.py` — replaced all imports/usages with inline ROOT_USER_DOCS/ROOT_CK3RAVEN_DATA expressions
- `tools/ck3lens_mcp/ck3lens/workspace.py` — import and defaults changed to canonical
- `tools/ck3lens_mcp/server.py` — import command uses ROOT_USER_DOCS / "mod" inline
- `tools/arch_lint/patterns.py` — banned terms expanded, allowlists cleaned

---

*End of Phase 2 Audit Report — February 13, 2026*
