# arch_lint v2.2 Complete Violation Report

> **Date:** December 31, 2025  
> **Status:** Pending cleanup  
> **Next Session:** Address violations systematically

---

## Executive Summary

| Rule ID | Count | Severity | Description |
|---------|-------|----------|-------------|
| **MUTATOR-01** | 37 | ERROR | SQL mutations outside builder |
| **MUTATOR-03** | 19 | ERROR | Subprocess calls outside builder |
| **ORACLE-02** | 12 | ERROR | Permission branching in if-conditions |
| **CONCEPT-03** | 8 | WARN | Lens concept explosion |
| **ORACLE-01** | 5 | ERROR | Oracle-style symbol names |
| **PATH-01** | 61 | WARN | Inline path normalization |
| **UNUSED-01** | 260+ | WARN | Unused API stubs |

---

## Critical Issues Identified This Session

### 1. Trace Folder NOT Excluded from Linter

**Location:** `tools/.wip/traces/ck3lens_trace.jsonl`

The linter was scanning the trace log file, which contains audit entries with terms like `enforce_fs_read`. This is NOT a codebase term - it's trace log terminology.

**Evidence:**
```
tools\.wip\traces\ck3lens_trace.jsonl:1773: "command": "findstr /s /i \"enforce_fs_read\" *.py *.ts *.md *.json"
```

**Fix Required:**
- Add `.wip` to `exclude_dirs` in `scripts/arch_lint/config.py`
- Add `.wip` to `EXCLUDE_DIRS` in `scripts/export_for_review.py`

### 2. Export Script Missing ck3lens-explorer

The export script at `scripts/export_for_review.py` excludes `node_modules` but appears to NOT exclude:
- `ck3lens-explorer/` directory (TypeScript VS Code extension)
- `.wip/` workspace directory
- `traces/` folder

**Current EXCLUDE_DIRS in export_for_review.py:**
```python
EXCLUDE_DIRS = {
    ".git",
    ".githooks", 
    # ... missing .wip, traces
}
```

**Fix Required:**
Add to EXCLUDE_DIRS:
```python
".wip",
"traces",
```

### 3. live_mods_config References

**Found in:**
- `docs/HARD CODING TO FIX.md` (line 19) - documentation only
- `exports/ck3raven_export_dec30.md` - export of above

**Status:** This is documentation about hardcoding to fix, not active code. The term exists only in docs describing what to fix.

### 4. Root Cause: Why Search Failed

**User's search found `enforce_fs_read` but agent's git grep did not.**

**Root Cause Analysis:**
1. `git grep` only searches **tracked files** (files committed to git)
2. The trace file `tools/.wip/traces/ck3lens_trace.jsonl` is in `.gitignore`
3. The agent's search was correct for tracked files - the term does NOT exist in codebase
4. User's search (likely Windows Search or VS Code search) includes untracked files

**Confirmation:**
```powershell
git grep -n "enforce_fs_read" -- "*.py" "*.ts" "*.md" "*.json"
# Result: No matches in tracked files
```

```powershell
Select-String -Path "tools\.wip\traces\*" -Pattern "enforce_fs_read"
# Result: Found in ck3lens_trace.jsonl
```

**Lesson:** The term `enforce_fs_read` is trace log terminology, not codebase terminology. It appears in the audit log as an operation type name.

---

## MUTATOR-01: SQL Mutations (37 items)

### Location Summary

| File | Count | Purpose |
|------|-------|---------|
| scripts/ingest_localization.py | 4 | Clear localization tables |
| src/ck3raven/db/cleanup.py | 1 | Remove soft-deleted files |
| src/ck3raven/db/ingest.py | 6 | Content version cleanup |
| src/ck3raven/db/schema.py | 1 | Symbol insertion |
| src/ck3raven/db/symbols.py | 3 | Symbol/ref cleanup |
| src/ck3raven/resolver/conflict_analyzer.py | 1 | Clear conflict units |
| tools/ck3lens_mcp/ck3lens/db_queries.py | 1 | Playset activation |
| tools/ck3lens_mcp/ck3lens/unified_tools.py | 2 | Playset switching |
| tools/ck3lens_mcp/server.py | 20 | ck3_db_delete tool |

### Analysis

**Legitimate Builder Layer (should be allowlisted):**
- `src/ck3raven/db/` - This IS the builder layer
- `scripts/ingest_localization.py` - Builder script

**MCP Layer (needs enforcement routing):**
- `tools/ck3lens_mcp/ck3lens/db_queries.py` - UPDATE for playset
- `tools/ck3lens_mcp/ck3lens/unified_tools.py` - UPDATE for playset
- `tools/ck3lens_mcp/server.py` - ck3_db_delete is designed for this

**Recommendation:**
Add to allowlist in `scripts/arch_lint/config.py`:
```python
allow_mutators_in: tuple[str, ...] = (
    "builder",
    "src/ck3raven/db/",
    "scripts/ingest_",
    "server.py",  # ck3_db_delete tool
)
```

---

## MUTATOR-03: Subprocess Calls (19 items)

### Location Summary

| File | Line | Purpose | Legitimate? |
|------|------|---------|-------------|
| scripts/arch_lint/rules.py | 42 | Rule definition regex | ✅ False positive |
| scripts/guards/code_diff_guard.py | 416 | Git diff for guard | ✅ Guard infra |
| src/ck3raven/db/parser_version.py | 32 | `git rev-parse HEAD` | ✅ Version track |
| tools/ck3lens-explorer/bridge/server.py | 961 | Subprocess for TS | ⚠️ Review |
| tools/ck3lens_mcp/ck3lens/git_ops.py | 33 | Git subprocess | ✅ Git module |
| tools/ck3lens_mcp/ck3lens/runtime_env.py | 135, 315 | Python check | ✅ Runtime |
| tools/ck3lens_mcp/ck3lens/unified_tools.py | 2387, 2646, 2666 | Git/validation | Should route through git_ops |
| tools/ck3lens_mcp/ck3lens/work_contracts.py | 537, 545, 559, 597 | Git for contracts | ✅ Contract layer |
| tools/ck3lens_mcp/server.py | 1946, 1954, 3288, 3299, 4718 | Builder/git | Mixed |

### Recommendation

Add to allowlist:
```python
allow_subprocess_in: tuple[str, ...] = (
    "git_ops.py",
    "work_contracts.py",
    "runtime_env.py",
    "parser_version.py",
    "code_diff_guard.py",
)
```

Refactor:
- `unified_tools.py` git calls → use `git_ops.py`
- `server.py` git calls → use `git_ops.py`

---

## ORACLE-02: Permission Branches (12 items)

### Detailed Analysis

| File | Line | Condition | Verdict |
|------|------|-----------|---------|
| playset_scope.py | 75 | `if not self.local_mods_folder` | ⚠️ Use mods[] |
| playset_scope.py | 113 | `if not self.local_mods_folder` | ⚠️ Use mods[] |
| ck3lens_rules.py | 144 | `if local_mods_folder` | ✅ Enforcement |
| types.py | 438 | `if scope.get("local_mods_folder")` | ⚠️ Review |
| wip_workspace.py | 468 | `if mod_name not in allowed_write_mods` | ❌ **ORACLE** |
| workspace.py | 242 | `if "local_mods_folder" in data` | ✅ Config |
| workspace.py | 287 | `if "local_mods_folder" in data` | ✅ Config |
| work_contracts.py | 183 | `if allowed_paths` | ✅ Contract |
| work_contracts.py | 734 | `if allowed_paths` | ✅ Contract |
| world_adapter.py | 600 | `if local_mods_folder` | ⚠️ Resolution |
| world_adapter.py | 965 | `if local_mods_folder` | ⚠️ Resolution |
| canonical_phase1_lint.py | 329 | `if "local_mods_folder" in line_text` | ✅ Lint |

### Critical Violation

**wip_workspace.py:468** - `allowed_write_mods` is a parallel permission structure. Must route through enforcement.py.

---

## CONCEPT-03: Lens Explosions (8 items)

| File | Line | Symbol | Action |
|------|------|--------|--------|
| db_queries.py | 17 | `invalidate_lens_cache` | DELETE |
| db_queries.py | 143 | `invalidate_lens_cache` call | DELETE |
| audit.py | 253 | `log_lensworld_resolution` | RENAME → `log_resolution` |
| workspace.py | 17 | `PlaysetLens` | REFACTOR to mods[] |
| world_router.py | 26 | `lens` param | USE mods[] |
| world_router.py | 27 | `PlaysetLens` import | DELETE |
| world_router.py | 116 | `_build_lens_adapter` | RENAME → `_build_adapter` |
| world_router.py | 126 | `_build_lens_adapter` call | (follows above) |

---

## ORACLE-01: Oracle Symbols (5 items)

| File | Line | Symbol | Verdict |
|------|------|--------|---------|
| ck3raven_dev_rules.py | 35 | `ALLOWED_PYTHON_PATHS` | ✅ Enforcement layer |
| validate.py | 18 | `ALLOWED_TOPLEVEL` | ✅ Validation layer |
| canonical_phase1_lint.py | 118 | `ALLOWED_RESOLVE_BASE_NAMES` | ✅ Lint allowlist |
| canonical_phase1_lint.py | 136 | `ALLOWED_PATH_LOGIC_SUBSTRINGS` | ✅ Lint allowlist |
| canonical_phase1_lint.py | 173 | `ALLOWED_ENFORCEMENT_CALLERS_SUBSTRINGS` | ✅ Lint allowlist |

**Status:** All acceptable - in enforcement/lint layers only.

---

## PATH-01: Inline Path Normalizations (61 items)

### Top Offenders

| File | Count |
|------|-------|
| world_adapter.py | 12 |
| enforcement.py | 9 |
| ck3raven_dev_rules.py | 8 |
| ck3lens_rules.py | 6 |
| server.py | 4 |
| unified_tools.py | 4 |
| work_contracts.py | 4 |
| paths.py | 4 |

### ⚠️ ARCHITECTURAL CONCERN

**paths.py is itself a potential violation.** Per CANONICAL_ARCHITECTURE.md:
> "All tools must call `WorldAdapter.resolve()` exactly once per target."
> "No secondary path derivation, normalization, or inference is permitted outside this pipeline."

A standalone `paths.py` with normalization functions is likely a parallel path resolution layer. This file needs architectural review.

### Correct Fix

All path normalization MUST go through `WorldAdapter.resolve()`. The 61 inline `.replace("\\", "/")` calls should be:
1. Removed if they pre-process before WorldAdapter
2. Moved INTO WorldAdapter if they're internal implementation
3. Eliminated by ensuring callers use WorldAdapter from the start

---

## UNUSED-01: Unused Symbols (260+ items)

### Categories

**Test Classes (130+ items):** Expected - test discovery handles these.

**Builder API (20+ items):** Intentional public API surface:
- `get_config`, `write_default_config`
- `extract_characters`, `extract_dynasties`, etc.
- `refresh_files_batch`, `check_playset_build_status`

**DB API (40+ items):** Intentional public API:
- `parse_file_cached`, `get_ast_stats`
- `search_all`, `find_definition`, `find_references`

**MCP Implementation Gaps (10+ items):**
- `git_status`, `git_diff`, `git_add`, `git_push`, `git_pull`, `git_log` @ git_ops.py
- These SHOULD be called by unified_tools.py but aren't

**Policy Layer (30+ items):** Review needed for actual usage.

### Recommendation

Focus on:
1. git_ops.py functions - integrate or delete
2. Trace helpers - verify usage
3. Token functions - verify usage

---

## Action Items for Next Session

### Priority 1: Fix Linter/Export Exclusions

1. **Update `scripts/arch_lint/config.py`:**
```python
exclude_dirs: tuple[str, ...] = (
    ".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build",
    ".mypy_cache", ".pytest_cache",
    ".wip",  # ADD: Trace logs
    "traces",  # ADD: Explicit
)
```

2. **Update `scripts/export_for_review.py`:**
```python
EXCLUDE_DIRS = {
    ".git", ".githooks", "__pycache__", "node_modules", "dist", "build",
    ".wip",  # ADD
    "traces",  # ADD
    "exports",  # ADD: Don't re-export exports
}
```

3. **Re-run linter** after exclusion fix to get clean results.

### Priority 2: Linter Output Enhancement

Update linter to include in JSON output:
- `filename` (just the name)
- `relpath` (relative to repo root)
- `line` (already present)
- `col` (already present)

Current output already has `path` (absolute) and `line`. Consider adding:
```python
"filename": Path(path).name,
"relpath": Path(path).relative_to(repo_root),
```

### Priority 3: Oracle Removal

Fix `wip_workspace.py:468` - remove `allowed_write_mods` oracle and route through enforcement.

### Priority 4: Lens Concept Removal

1. Delete `invalidate_lens_cache` from db_queries.py
2. Rename `log_lensworld_resolution` → `log_resolution`
3. Refactor `PlaysetLens` → use `mods[]` directly
4. Rename `_build_lens_adapter` → `_build_adapter`

### Priority 5: Path Normalization Consolidation - **CORRECTION**

**⚠️ AGENT ERROR:** The original recommendation to "create `normalize_path()` in paths.py" was a BANNED IDEA.

**Canonical Architecture States:**
> "All tools must call `WorldAdapter.resolve()` exactly once per target."
> "No secondary path derivation, normalization, or inference is permitted outside this pipeline."

**Correct Fix:**
All 61 inline `.replace("\\", "/")` calls must be refactored to use `world.resolve()` or removed entirely if they're pre-processing paths before resolution.

**paths.py Review Required:**
The file `tools/ck3lens_mcp/ck3lens/policy/paths.py` itself is potentially dangerous as it may be creating a parallel path normalization layer. Needs architectural review to determine:
1. Whether it should exist at all
2. Whether its functions should be absorbed into WorldAdapter
3. Whether callers should be refactored to use WorldAdapter directly

### Priority 6: git_ops Integration

Either:
- Route unified_tools.py git calls through git_ops.py, OR
- Delete unused git_ops functions

---

## Root Cause Documentation

### Why Agent Search Didn't Find enforce_fs_read

| Search Method | Scope | Result |
|---------------|-------|--------|
| `git grep` | Tracked files only | ✅ Correct: Not in codebase |
| Windows Search | All files | Found in `.wip/traces/` |
| VS Code Search | Workspace (may include untracked) | Found in traces |

**Conclusion:** The term `enforce_fs_read` is trace log terminology (audit entries), NOT codebase terminology. The agent's search was correct for tracked files. The issue was the linter scanning the untracked traces folder.

---

## Files to Delete/Expunge

### Files Requiring Review for Deletion

1. **`tools/ck3lens_mcp/ck3lens/policy/paths.py`** - Potential parallel path normalization layer. Violates canonical architecture if it provides normalization outside WorldAdapter.

### Confirmed Safe to Delete

None confirmed yet - requires deeper analysis.

### Documentation Updates Needed

- `docs/HARD CODING TO FIX.md` - Contains `live_mods_config` as example of what to fix. Should be updated when hardcoding is removed.

---

## Agent Self-Correction Notes

### Error 1: Recommending `normalize_path()` in paths.py

**Original recommendation:** "Create `normalize_path()` in paths.py and refactor all to use it."

**Why this was wrong:** This is exactly the BANNED pattern - creating a parallel path resolution layer. CANONICAL_ARCHITECTURE.md clearly states all path normalization must go through `WorldAdapter.resolve()`.

**Lesson:** Before recommending any path/permission utility, check CANONICAL_ARCHITECTURE.md first.

### Error 2: Claiming `live_mods_config` only in docs

**Original claim:** "Only exists in documentation"

**Status:** User reports this exists in workspace.py. Search didn't find `live_mods_config` but did find `live_mods` in lint rules. Need thorough review of workspace.py for any `live_*` patterns.

### Recommendation: Lint the Recommendations

Before issuing architectural recommendations, cross-check against:
1. CANONICAL_ARCHITECTURE.md banned terms
2. arch_lint rules
3. The 5 canonical rules (ONE enforcement boundary, NO permission oracles, etc.)

---

*Report generated from arch_lint v2.2 run on December 31, 2025*
