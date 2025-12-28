# Next Session TODOs

> **Date:** December 28, 2025
> **Contract:** wcp-2025-12-28-70e797
> **Branch:** agent/wcp-2025-12-28-70e797-enforcement-gate

---

## Priority Fixes

### 1. Fix Enforcement Order (WorldAdapter BEFORE Enforcement)

**Problem:** Phase 2 wiring added enforcement at tool boundary in `ck3_file_impl`, but WorldAdapter check happens later in helper functions.

**Correct order:**
1. WorldAdapter.resolve() → NOT_FOUND if path not visible
2. enforce_policy() → DENY/REQUIRE_TOKEN if policy violation
3. Implementation → perform operation

**Files to update:**
- `tools/ck3lens_mcp/ck3lens/unified_tools.py` - ck3_file_impl, ck3_git_impl

---

### 2. Wire ck3_exec to Use Centralized enforcement.py

**Problem:** ck3_exec currently uses CLW (`policy/clw.py`) for policy decisions. This is a separate policy engine from the new centralized `enforcement.py`.

**Goal:** Route ck3_exec through `enforce_and_log()` like the other tools for consistency.

**Current state:**
- ck3_exec uses `evaluate_policy()` from clw.py
- Has structured audit logging added (Phase 2)
- CLW classifies commands as READ_ONLY, GIT_SAFE, GIT_MODIFY, GIT_DANGEROUS, etc.

**Approach:**
- Map CLW categories to enforcement.py OperationType
- Call `enforce_and_log()` at top of ck3_exec
- Keep CLW for command classification, use enforcement.py for decisions
- Ensure SAFE PUSH auto-grant works for git push on agent branches

**File to update:**
- `tools/ck3lens_mcp/server.py` - ck3_exec function

---

### 3. NOT_FOUND vs DENY Consistency

**Problem:** Lens violations should return `Decision.NOT_FOUND` (path doesn't exist in your world) not `Decision.DENY` (path exists but forbidden).

**Files to check:**
- `tools/ck3lens_mcp/ck3lens/policy/enforcement.py`
- `tools/ck3lens_mcp/ck3lens/world_adapter.py` (if exists)

---

## Lower Priority

### 4. Fix ck3_git Hanging Issue

**Problem:** `ck3_git` tool hangs (noted in docstring as known issue with GitLens conflicts).

**Workaround:** Using `ck3_exec` with git commands works fine.

**Long-term:** Investigate root cause or formally deprecate in favor of ck3_exec.

---

## Review Items

- [docs/drafts/INITIALIZATION_PROPOSAL.md](docs/drafts/INITIALIZATION_PROPOSAL.md) - Canonical initialization instructions
- [docs/drafts/WIP_SCRIPTING_PROPOSAL.md](docs/drafts/WIP_SCRIPTING_PROPOSAL.md) - Script sandboxing architecture

