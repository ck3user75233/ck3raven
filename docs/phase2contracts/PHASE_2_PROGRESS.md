# Phase 2: Deterministic Gates — Progress Report

> **Date:** February 12, 2026 (updated from Feb 11)  
> **Sprint:** Sprint 0 Phase 2.1  
> **Reference:** docs/phase2contracts/PHASE_2_DETERMINISTIC_GATES_PLAN.md (Revision 3)

---

## Current Phase: 2.1 — REQUIRE_CONTRACT Surface Elimination

**Status: ~80% Complete**

Phase 2.1 has two objectives:
1. Replace leaked `"REQUIRE_CONTRACT"` / `"policy_decision"` dicts with Reply D
2. Convert enforcement and sub-functions from dict returns to Reply

### What's Done

| Work Item | Status | Commit | Notes |
|-----------|--------|--------|-------|
| `EnforcementResult` class deleted | DONE | e0d4f4d | Replaced with Reply via rb |
| `enforce()` returns Reply via rb | DONE | e0d4f4d | 63 lines, pure matrix walker |
| `_gate()` collects ALL failures in denials list | DONE | e0d4f4d | No early returns, deterministic |
| `Decision` enum eliminated from surface | DONE | e0d4f4d | Internal only |
| server.py wrappers: all pass `rb=rb` to impl | DONE | e0d4f4d | 34 wrappers updated |
| server.py wrappers: `isinstance(result, Reply)` passthrough | DONE | e0d4f4d | Migration seam |
| `reply_linter.py` created | DONE | 0c965df | 5 checks |
| `_create_reply_builder` deleted | DONE | 05cfe99 | Function removed, 5 callers fixed |
| `_file_read_raw` → Reply via rb | DONE | 05cfe99 | All dict fallbacks removed |
| `_file_write` → Reply via rb | DONE | 05cfe99 | All dict fallbacks removed |
| `_file_write_raw` → Reply via rb | DONE | 05cfe99 | All dict fallbacks removed |
| `_file_create_patch` → Reply via rb | DONE | 05cfe99 | Full rewrite |
| `ck3_file_impl` trace_info removed | DONE | 05cfe99 | Only `rb` param remains |
| Import cleanup | DONE | 05cfe99 | Clean |
| TASL linter created | DONE | 05cfe99 | 8 checks, tools/compliance/tasl.py |
| Zero Pylance errors across core files | DONE | 05cfe99 | enforcement.py, server.py, unified_tools.py |

### What Remains in Phase 2.1

#### A. Server.py policy_decision String Elimination (~5 sites)

`unified_tools.py` is clean (zero `REQUIRE_CONTRACT` / `policy_decision` references). But `server.py` still has ~5 sites checking `policy_decision` strings in dict results from unconverted sub-functions.

#### B. Remaining Dict-Returning Sub-Functions (~18)

**File operations (unified_tools.py):** ~8 functions (_file_edit_raw, _file_delete_raw, etc.)

**Git operations (unified_tools.py):** ck3_git_impl + 6 helpers

**Folder operations (unified_tools.py):** _folder_list_raw

**Exec operations:** _ck3_exec_internal — **CARVED OUT** (deferred to exec directive)

#### C. baseline_sha Schema Addition

Add `baseline_sha: str | None` to ContractV1 dataclass. Minimal change — no behavior change until Phase 2.3 wires it.

---

## Phase 2.1 Carve-Out: ck3_exec

Per the CK3 Exec Sprint 0 Directive (`CK3_EXEC_SPRINT_0_DIRECTIVE.md`), `_ck3_exec_internal` is **NOT** converted to Reply in Phase 2.1. Only the surface leak sites in server.py are fixed. The exec internal function will be rewritten by the exec directive after Phase 2 completion.

---

## Phases 2.2-2.5 Status

| Phase | Title | Status | Blocked By |
|-------|-------|--------|------------|
| 2.1 | Surface Elimination + Schema | **~80% done** | — |
| 2.2 | Gate Infrastructure | Not started | 2.1 |
| 2.3 | Open Gates + Continuity | Not started | 2.2 |
| 2.4 | Close Gates (git diff audit) | Not started | 2.3 |
| 2.5 | Escalation + Stash + Tests | Not started | 2.4 |

---

## Commit History (This Sprint)

| Commit | Description |
|--------|-------------|
| e0d4f4d | Delete EnforcementResult, enforce returns Reply |
| 0c965df | Add reply_linter.py |
| 05cfe99 | Delete _create_reply_builder + add TASL linter |

**All pushed to main** as of Feb 12, 2026.

---

## Companion Documents (Permanent Locations)

| Document | Path |
|----------|------|
| Phase 2 Design Plan (Rev 3) | docs/phase2contracts/PHASE_2_DETERMINISTIC_GATES_PLAN.md |
| CK3 Exec Directive | docs/phase2contracts/CK3_EXEC_SPRINT_0_DIRECTIVE.md |
| Canonical Contract Law (amended §13) | docs/CANONICAL_CONTRACT_LAW.md |

---

*End of Phase 2 Progress Report*
