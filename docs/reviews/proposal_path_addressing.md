# Proposal: Fix ck3_file Path Addressing

**Date**: 2026-02-07 (V3: +Reply conformance, +no-fallback rule)  
**Bug Reference**: [docs/bugs/bug_mod_name_wip_asymmetry.md](../bugs/bug_mod_name_wip_asymmetry.md)  
**Status**: Approved for implementation — Option A with B-forward design

---

## Problem

`mod_name="wip"` works for write but fails for read/list/refresh because `normalize_path_input()` is only called for write commands. Read commands pass `mod_name` directly to `session.get_mod()`, which searches the playset — "wip" isn't a mod.

---

## Design Instructions (from review)

### Instruction 1: Hard Invariant for `ck3_file`

> **All commands must call `normalize_path_input()` before dispatch, and dispatch must consume a resolved target object (`ResolutionResult`), not `mod_name`/`path` ad hoc.**

This means:

1. `ck3_file_impl` resolves `(path, mod_name, rel_path)` → `ResolutionResult` **once**, at the top, for **every** command.
2. Command handlers receive `resolution: ResolutionResult`, not raw `mod_name`/`path` kwargs.
3. No command handler calls `session.get_mod()` directly — the resolution already provides `absolute_path`, `root_category`, `mod_name`, etc.
4. The old `_file_read_live()` (which does its own `session.get_mod()` lookup) becomes dead code and is deleted.
5. The old `_file_list()` (which does its own `session.get_mod()` lookup) routes through `_file_list_raw()` with the resolved `absolute_path`.

**Exception**: `command=get` uses database lookup by relpath — it doesn't need filesystem resolution. It remains unchanged.

**Applicability to other tools**: After `ck3_file` is done, assess `ck3_git_impl` (line 2570: `session.get_mod(mod_name)` for enforcement) and `ck3_folder_impl`. These are lower priority because they work correctly today, but the same invariant would improve consistency. Tracked as a follow-up, not part of this PR.

### Instruction 2: End-State Code Organization

> **`mod_name` stays forever, but is redefined as: only real playset mod names.**  
> **`wip`, `vanilla`, etc. are schemes, not "pseudo mods".**

This means:

1. `normalize_path_input()` continues to accept `mod_name="wip"` and translate it to `wip:/` — but this is a **compatibility shim**, not the primary path.
2. The **primary** way to address non-mod targets is `path="wip:/..."`, `path="vanilla:/..."`, etc. (canonical addresses).
3. `mod_name` parameter description is updated: *"A real mod name from the active playset. For non-mod targets, use `path` with canonical addresses (wip:/, vanilla:/, data:/, ck3raven:/)."*
4. Option B (deprecation cycle) becomes purely documentation + deprecation warnings. No new refactor needed because Option A already routes everything through `normalize_path_input()` → `ResolutionResult`.

---

### Instruction 3: Reply Conformance

> **Do not return raw `{"error": ...}` dicts. All returns must use the Reply system with proper codes from `reply_registry.py`.**

This means:

1. Every error path returns `Reply.info(code, data)` or `Reply.error(code, data)`, not `{"error": "message"}`.
2. The pseudocode in this proposal uses dicts for brevity/readability. The **actual implementation** must return Reply objects via `_create_reply_builder()`.
3. Relevant reply codes already exist: `WA-RES-I-001` (not found), `WA-RES-D-001` (outside roots), `WA-RES-E-001` (internal error), `FILE-OP-S-001` (success), `FILE-OP-I-001` (file not found), `FILE-OP-E-001` (file op error).
4. The current dual-path (Reply if `trace_info` provided, raw dict otherwise) must be eliminated. All responses go through Reply.

### Instruction 4: No Hidden Fallback

> **If resolution is computed at the top, every file-operating command must use `resolution.absolute_path` or fail. No hidden fallback to "try `session.get_mod()` anyway".**

This means:

1. Once `normalize_path_input()` returns a `ResolutionResult`, that is the **single source of truth** for the file path.
2. If `resolution.found` is False, the command returns an error Reply immediately. It does **not** silently try `session.get_mod(mod_name)` as a backup.
3. The only exception is `command=create_patch`, where both `mod_name` and `source_mod` are genuine playset mod names and `session.get_mod()` is the correct lookup.
4. This prevents the "ghost path" bug class where a failed resolution silently falls through to a different lookup that resolves to an unintended location.

---

## Implementation Plan: Option A (with B-forward structure)

### What changes

| Area | Change |
|------|--------|
| **Dispatch gate** | Move `normalize_path_input()` call to top of `ck3_file_impl`, outside `write_commands` guard. All commands (except `get`) go through it. |
| **Read dispatch** | Remove dual branch (`_file_read_raw` vs `_file_read_live`). Single path: `resolution.absolute_path` → `_file_read_raw()`. |
| **List dispatch** | Remove dual branch (`_file_list` vs `_file_list_raw`). Single path: `resolution.absolute_path` → `_file_list_raw()`. |
| **Refresh dispatch** | Use `resolution.absolute_path` instead of `session.get_mod()` → `mod.path / rel_path`. |
| **Delete `_file_read_live`** | ~68 lines removed. Redundant once resolution provides absolute paths. |
| **Delete `_file_list`** | ~40 lines removed. Redundant once resolution provides absolute paths for listing. |
| **Enforcement gate** | Already correct for write commands. Add optional `enforce()` call for reads (ck3lens mode, visibility check). |

### What stays the same

| Area | Why |
|------|-----|
| `_file_read_raw()` | Already takes a path and does `world.resolve()` internally — but now receives pre-resolved `ResolutionResult` path, so its internal resolve becomes a no-op/validation. |
| `normalize_path_input()` | No changes to its logic. It already handles wip/vanilla/mod translation correctly. |
| `_file_write_raw()`, `_file_edit_raw()`, `_file_delete_raw()`, `_file_rename_raw()` | Already consume absolute paths from resolution. No changes. |
| `_file_get()` | Database lookup by relpath, no filesystem resolution needed. |
| `_file_create_patch()` | ck3lens-only, uses `session.get_mod()` for genuine mod lookup. This is correct — both `mod_name` and `source_mod` here are real playset mods. |

### Pseudocode: New dispatch structure

```python
def ck3_file_impl(command, path, mod_name, rel_path, ..., world, session, ...):
    mode = get_agent_mode()
    
    # ======================================================================
    # HARD INVARIANT: Resolve target before dispatch (all commands except get)
    # ======================================================================
    resolution = None
    if command != "get" and world is not None and (path or mod_name):
        resolution = normalize_path_input(world, path=path, mod_name=mod_name, rel_path=rel_path)
        if not resolution.found:
            # IMPLEMENTATION NOTE: Return Reply.info(WA-RES-I-001), not raw dict
            return {"error": resolution.error_message, "visibility": "NOT_FOUND"}
    
    # ======================================================================
    # ENFORCEMENT GATE (write commands only — unchanged)
    # ======================================================================
    write_commands = {"write", "edit", "delete", "rename"}
    if command in write_commands and mode and resolution and resolution.absolute_path:
        # ... existing enforce() logic unchanged ...
    
    # ======================================================================
    # DISPATCH (all handlers receive resolution, not raw mod_name)
    # ======================================================================
    if command == "get":
        return _file_get(path, include_ast, max_bytes, db, trace, visibility)
    
    elif command == "read":
        if resolution and resolution.absolute_path:
            return _file_read_raw(str(resolution.absolute_path), start_line, end_line, ...)
        else:
            return {"error": "path or mod_name+rel_path required for read"}
    
    elif command == "write":
        # ... already uses resolution.absolute_path (unchanged) ...
    
    elif command == "list":
        if resolution and resolution.absolute_path:
            return _file_list_raw(str(resolution.absolute_path), pattern, trace, world)
        else:
            return {"error": "path or mod_name+rel_path required for list"}
    
    elif command == "refresh":
        if resolution and resolution.absolute_path:
            return _file_refresh_resolved(resolution, session, trace)
        else:
            return {"error": "path or mod_name+rel_path required for refresh"}
    
    elif command == "create_patch":
        # Unchanged — mod_name here is a real playset mod
        return _file_create_patch(mod_name=mod_name, ...)
```

---

## Risk Management: Protecting MCP Tools During Refactor

### Risk: MCP tool regression during refactor

The `ck3_file` tool is the most-used MCP tool. A bug in the refactor could break file reads, writes, or listings — silently (wrong path) or loudly (exceptions). The agent would lose the ability to work.

### Mitigation strategy

#### 1. Pre-refactor: Capture behavioral baselines

Before touching any code, run the following calls and save expected outputs:

| Test case | Tool call | Expected |
|-----------|-----------|----------|
| Read by raw path | `ck3_file(command="read", path="wip:/test.txt")` | Success or "not found" (not crash) |
| Read by mod_name | `ck3_file(command="read", mod_name="<real_mod>", rel_path="descriptor.mod")` | Content |
| Read by mod_name="wip" | `ck3_file(command="read", mod_name="wip", rel_path="test.txt")` | **Currently fails** — this is the bug we're fixing |
| Write to wip | `ck3_file(command="write", mod_name="wip", rel_path="test.txt", content="test")` | Success |
| List mod files | `ck3_file(command="list", mod_name="<real_mod>", pattern="*.txt")` | File list |
| List wip files | `ck3_file(command="list", mod_name="wip")` | **Currently fails** — this is the bug |
| Get from DB | `ck3_file(command="get", path="common/traits/00_traits.txt")` | DB content |

#### 2. During refactor: Incremental, not big-bang

The refactor has a natural ordering:

1. **Move resolution gate up** (the hard invariant). This is the only structural change.
2. **Rewire `read` dispatch** to use `resolution.absolute_path` → `_file_read_raw`. Test.
3. **Rewire `list` dispatch** to use `resolution.absolute_path` → `_file_list_raw`. Test.
4. **Rewire `refresh` dispatch**. Test.
5. **Delete dead code** (`_file_read_live`, `_file_list`). This is cleanup, not behavioral change.

Each step is independently committable and testable. If step 2 breaks reads, we revert step 2 without losing step 1.

#### 3. Post-refactor: Verify baselines hold

Re-run all test cases from step 1. Additionally:

- New case: `ck3_file(command="read", mod_name="wip", rel_path="test.txt")` now succeeds.
- New case: `ck3_file(command="list", mod_name="wip")` now succeeds.
- Regression check: `ck3_file(command="read", mod_name="<real_mod>", rel_path="descriptor.mod")` still works.

#### 4. Canary: `_file_read_raw` already resolves internally

`_file_read_raw()` already calls `world.resolve()` internally (line ~1065). After the refactor, it receives a pre-resolved path. The internal `world.resolve()` call becomes a redundant identity operation (resolve an already-absolute path). This is safe — `world.resolve()` on an absolute path within scope returns the same path. We do **not** remove the internal resolve in this PR to avoid a second risk surface. It can be cleaned up later as a no-behavior-change followup.

#### 5. Fallback: Feature flag (optional, may not be needed)

If the refactor proves more complex than expected, a temporary feature flag can gate the new dispatch:

```python
_USE_RESOLVED_DISPATCH = True  # Set to False to revert to old behavior
```

This is likely unnecessary given the incremental approach, but it's available.

---

## Option B: What Remains After Option A

Once Option A is implemented, Option B becomes documentation + deprecation only:

| Task | Type | Effort |
|------|------|--------|
| Update `mod_name` parameter description in tool schema | Doc | 5min |
| Update copilot instructions to prefer `path="wip:/..."` | Doc | 10min |
| Add deprecation log when `mod_name="wip"` or `mod_name="vanilla"` used | Code (1 line) | 2min |
| Eventually remove pseudo-mod translation from `normalize_path_input()` | Code (6 lines) | Phase 3 |

No structural refactor needed. The invariant from Option A guarantees everything goes through `normalize_path_input()`, so the deprecation is just removing the `if mod_name.lower() == "wip"` branch — all callers will have migrated to `path="wip:/..."` by then.

---

## Files Affected (Option A)

| File | Change |
|------|--------|
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | Move `normalize_path_input()` before dispatch; rewire read/list/refresh; delete `_file_read_live` and `_file_list` |
| `tools/ck3lens_mcp/ck3lens/world_adapter.py` | No changes |
| `tools/ck3lens_mcp/ck3lens/policy/enforcement.py` | No changes |

---

## Other Tools Assessment

| Tool | Uses `session.get_mod(mod_name)` | Same invariant applicable? | Priority |
|------|----------------------------------|---------------------------|----------|
| `ck3_git_impl` | Yes (line 2570, 2659) | Yes — but `mod_name` here is always a real mod. No pseudo-mod bug. | Low (follow-up) |
| `ck3_folder_impl` | Possibly via content_version_id | Different pattern (DB-centric). Not affected. | N/A |
| `ck3_validate_impl` | No | N/A | N/A |
| `ck3_logs_impl` | No | N/A | N/A |

**Recommendation**: After `ck3_file` is proven, apply the same resolve-before-dispatch pattern to `ck3_git_impl` as a separate follow-up PR. It doesn't have the pseudo-mod bug, but the pattern would make it consistent.
