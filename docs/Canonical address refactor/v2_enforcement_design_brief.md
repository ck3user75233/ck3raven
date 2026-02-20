# V2 Enforcement Architecture — Design Brief

> **Date:** February 18, 2026
> **Status:** In Progress — capability_matrix_v2, enforcement_v2, WA v2 on disk, not yet tested
> **Author:** Agent (directed by Nate)
> **Scope:** capability_matrix_v2.py, enforcement_v2.py, world_adapter_v2.py, tool layer changes
> **Supersedes:** PROPOSAL_WA_Visibility_Matrix_2026-02-13.md (partial), deleted enforcement_v2.py

---

## 0) Design Principles

1. **Single `enforce()` function.** No `enforce_exec()`, no `enforce_file()`, no function-name branching.
2. **Declarative matrices with modular condition predicates.** Matrices are pure data. Conditions are standalone callables. Enforcement walks the data.
3. **`session.mods` is the authoritative mod registry.** WA consults `session.mods` directly at resolution time. No `mod_paths` dict, no alias maps, no parallel data structures.
4. **WA walks visibility. EN walks mutations.** Never cross the streams. Reads are resolved by WA visibility alone. EN only sees mutations.
5. **Mod visibility is structural.** `session.mods` IS the playset-scoped list. If a mod isn't in `session.mods`, WA can't resolve it.
6. **`VisibilityResolution` is removed from public API.** WA v2 `resolve()` returns `tuple[Reply, Optional[VisibilityRef]]`. No intermediate dataclass.
7. **Reply.data["resolved"] is the session-absolute path.** For infrastructure roots: `root:<key>/<rel_path>`. For mod-addressed input: `mod:Name/<rel_path>`. Output namespace matches input namespace.
8. **Host paths never appear in Reply.** Reply is semantic. VisibilityRef is capability.
9. **No OperationType enum.** Tool+command pairs are classified explicitly — reads vs mutation categories. The matrix knows what's what.
10. **No _RO entries in the operations matrix.** Reads use `OperationRule` with no conditions. Mutations use `OperationRule` with conditions. Both live in the same `OPERATIONS_MATRIX`.

---

## 1) Architecture Overview

```
Tool Handler (server.py)
    │
    ├─ WA v2: resolve(input) → (Reply, Optional[VisibilityRef])
    │   ├─ Accepts: root category paths, mod:Name/path, bare relative
    │   ├─ Walks VISIBILITY_MATRIX for root category gating
    │   ├─ Consults session.mods for mod name resolution
    │   ├─ Mode read dynamically via get_agent_mode() — not baked at construction
    │   └─ Returns session-absolute path in Reply.data["resolved"]
    │
    ├─ enforce(rb, mode, tool, command, root_key, subdirectory, **context)
    │   ├─ Looks up (mode, root_key, subdirectory) in OPERATIONS_MATRIX
    │   ├─ Scans rules for matching (tool, command)
    │   ├─ "read" commands → no conditions → immediate success
    │   ├─ mutation commands → check conditions → success or denied
    │   ├─ No matching rule → DENY
    │   └─ Conditions check → Returns Reply (success or denied)
    │
    └─ Execute operation using wa.host_path(ref)
```

Three modules, three responsibilities:

| Module | Responsibility | File |
|--------|---------------|------|
| **VISIBILITY_MATRIX** | Binary: can this agent see this root category? | `capability_matrix_v2.py` |
| **OPERATIONS_MATRIX** | What operations are allowed (reads + mutations), with what conditions? | `capability_matrix_v2.py` |
| **COMMAND CLASSIFICATION** | Exact (tool, command) frozensets: reads vs mutations | `capability_matrix_v2.py` |
| **enforcement_v2.py** | Single `enforce()` that looks up (tool, command) in OPERATIONS_MATRIX | `enforcement_v2.py` |
| **world_adapter_v2.py** | `resolve()` → `tuple[Reply, Optional[VisibilityRef]]`, walks VISIBILITY_MATRIX | `world_adapter_v2.py` |

---

## 2) VISIBILITY_MATRIX

Pure data. Keyed by `(mode, root_key)`.

### Current State (root-level only, binary)

```python
VISIBILITY_MATRIX: dict[tuple[str, str], bool] = {
    ("ck3lens", "game"):           True,
    ("ck3lens", "steam"):          True,
    ("ck3lens", "user_docs"):      True,
    ("ck3lens", "ck3raven_data"):  True,
    ("ck3lens", "vscode"):         True,
    ("ck3lens", "repo"):           True,

    ("ck3raven-dev", "game"):           True,
    ("ck3raven-dev", "steam"):          True,
    ("ck3raven-dev", "user_docs"):      True,
    ("ck3raven-dev", "ck3raven_data"):  True,
    ("ck3raven-dev", "vscode"):         True,
    ("ck3raven-dev", "repo"):           True,
}
```

### OPEN DESIGN ISSUE: Subfolder Visibility Gating

The current VISIBILITY_MATRIX is root-level only. This is **insufficient**.

**Problem:** Some subfolders within a visible root need conditional visibility:
- `user_docs` is visible, but mod registry files at the root level should NOT be visible — only the mod folders underneath (listed in session.mods) should be visible.  
- ck3lens should only see mod paths that are in `session.mods`, not arbitrary subdirectories of `user_docs`.

**Required (from v1 matrix, not yet ported to v2):**
- VISIBILITY_MATRIX needs `(mode, root_key, subdirectory)` keying or subfolder conditions
- Condition predicates on visibility entries (e.g., `MOD_IN_SESSION` condition that checks `session.mods`)
- This was already working in v1 capability matrix — must be carried forward

**Status:** Not yet designed for v2. Next sprint item.

### Mod Visibility

Mods are NOT in the visibility matrix. Mod visibility is structural:
- `session.mods` IS the visible mod list.
- WA consults `session.mods` at resolution time.
- If the mod name isn't in `session.mods`, resolution fails.

---

## 3) COMMAND CLASSIFICATION

Commands are organized as named `frozenset` constants. Each `OperationRule` in the matrix carries its command set directly — no separate classification function is needed.

```python
# Read command sets (no conditions — always allowed if visible)
FILE_READ_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    ("ck3_file", "read"), ("ck3_file", "get"), ("ck3_file", "list"), ("ck3_file", "refresh"),
})
DIR_READ_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    ("ck3_dir", "pwd"), ("ck3_dir", "cd"), ("ck3_dir", "list"), ("ck3_dir", "tree"),
})
GIT_READ_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    ("ck3_git", "status"), ("ck3_git", "diff"), ("ck3_git", "log"),
})
FOLDER_READ_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    ("ck3_folder", "list"), ("ck3_folder", "contents"), ("ck3_folder", "top_level"), ("ck3_folder", "mod_folders"),
})
ALL_READ_COMMANDS = FILE_READ_COMMANDS | DIR_READ_COMMANDS | GIT_READ_COMMANDS | FOLDER_READ_COMMANDS

# Mutation command sets
FILE_WRITE_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    ("ck3_file", "write"), ("ck3_file", "edit"), ("ck3_file", "rename"), ("ck3_file", "create_patch"),
})
FILE_DELETE_COMMANDS: frozenset[tuple[str, str]] = frozenset({("ck3_file", "delete")})
GIT_MUTATE_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    ("ck3_git", "add"), ("ck3_git", "commit"), ("ck3_git", "push"), ("ck3_git", "pull"),
})
EXEC_COMMANDS: frozenset[tuple[str, str]] = frozenset({})  # ck3_exec special-cased by tool name
```

Each `OperationRule` carries its command frozenset + conditions. `find_operation_rule()` scans the rules for a matching (tool, command). No separate `classify_command()` function.

**Why file_write and file_delete are separate command sets:** Some locations allow write but not delete (e.g., config, artifacts — writable but not deletable).

---

## 4) OPERATIONS_MATRIX

Pure data. Keyed by `(mode, root_key, subdirectory | None)`. Contains ALL operations — reads AND mutations.

```python
@dataclass(frozen=True)
class OperationRule:
    """Exact (tool, command) pairs this rule governs, plus conditions."""
    commands: frozenset[tuple[str, str]]
    conditions: tuple[Condition, ...] = ()

OperationKey = tuple[str, str, str | None]  # (mode, root_key, subdirectory)

OPERATIONS_MATRIX: dict[OperationKey, tuple[OperationRule, ...]] = {
    # ck3lens — game: read-only
    ("ck3lens", "game", None): (
        OperationRule(ALL_READ_COMMANDS),
    ),
    # ck3lens — user_docs/mod: reads + writes (with contract)
    ("ck3lens", "user_docs", "mod"): (
        OperationRule(ALL_READ_COMMANDS),
        OperationRule(FILE_WRITE_COMMANDS, (_HAS_CONTRACT,)),
    ),
    # ck3raven-dev — repo: reads + writes (with contract)
    # ck3raven-dev — repo: reads + writes (with contract)
    ("ck3raven-dev", "repo", None): (
        OperationRule(ALL_READ_COMMANDS),
        OperationRule(FILE_WRITE_COMMANDS, (_HAS_CONTRACT,)),
        OperationRule(GIT_MUTATE_COMMANDS, (_HAS_CONTRACT,)),
    ),
    # ...
}
```

### Default: DENY

Any `(mode, root_key, subdir)` not in the matrix → DENY.

---

## 5) enforcement_v2.py — Single `enforce()`

```python
def enforce(
    rb,
    mode: str,
    tool: str,
    command: str,
    root_key: str,
    subdirectory: str | None,
    **context,
) -> Reply:
    # 1. Look up (mode, root_key, subdirectory) in OPERATIONS_MATRIX
    # 2. Scan rules for one whose commands contain (tool, command)
    # 3. No matching rule → rb.denied("EN-GATE-D-001")
    # 4. Rule has no conditions (read) → rb.success("EN-READ-S-001")
    # 5. Conditions check → rb.denied(denial_code) or rb.success("EN-WRITE-S-001")
```

No `OperationType`. No `tool_cluster`. No `classify_command()`. The tool handler passes its real `tool` name and `command`. Enforcement scans rules and decides.

---

## 6) Condition Predicates

Standalone callables. Each has a name, a check function, and a denial code.

```python
@dataclass(frozen=True)
class Condition:
    name: str
    check: Callable[..., bool]
    denial: str

VALID_CONTRACT = Condition("contract", lambda has_contract=False, **_: has_contract, "EN-WRITE-D-002")
EXEC_SIGNED = Condition("exec_signed", lambda exec_signature_valid=False, **_: exec_signature_valid, "EN-EXEC-D-001")
```

Conditions receive `**context` from `enforce()`. Tool handlers build the context dict.

---

## 7) world_adapter_v2.py — Key Decisions

### Mode-Agnostic (Dynamic Reads)

WA v2 does NOT store mode at construction. `resolve()` calls `get_agent_mode()` from `agent_mode.py` dynamically on every invocation.

- Constructor: `__init__(*, session, roots)` — no mode parameter
- Factory: `create(*, session)` — no mode parameter  
- `mode` property: `return _get_mode() or "uninitiated"`
- `_get_mode()`: module-level function that imports and calls `get_agent_mode()`
- If mode is None → returns `WA-MODE-I-001` ("Agent mode not initialized")
- `_reset_world_cache()` does NOT clear v2 cache on mode change (v2 is mode-agnostic)

### resolve() Return Contract

```python
def resolve(self, input_str: str, *, require_exists: bool = True, rb=None) -> tuple[Reply, Optional[VisibilityRef]]:
```

Success:
```python
(Reply(code="WA-RES-S-001", data={"resolved": "root:steam/common/...", "root_key": "steam", "subdirectory": None, "relative_path": "common/..."}), VisibilityRef(...))
```

Failure:
```python
(Reply(code="WA-RES-I-001", message="..."), None)
```

### Input Flexibility, Output Determinism

Input forms: `root:<key>/<path>`, `mod:Name/<path>`, legacy `ROOT_REPO:/<path>`, bare relative.
Output: Reply.data["resolved"] preserves input namespace.

---

## 8) Tool Layer Changes

Tool handlers pass real tool+command to enforce:

```python
# In ck3_exec handler (server.py) — IMPLEMENTED
result = enforce(
    rb, mode=wa2.mode,
    tool="ck3_exec", command=command,
    root_key=root_key, subdirectory=subdirectory,
    has_contract=has_contract, exec_signature_valid=False,
)

# In ck3_file handler — NOT YET MIGRATED (still uses v1 enforcement.py)
# In ck3_git handler — NOT YET MIGRATED (still uses v1 enforcement.py)
```

---

## 9) Implementation Status

### On Disk (written, not yet tested — stale module cache blocks testing)

| File | Status | Notes |
|------|--------|-------|
| `capability_matrix_v2.py` | **REWRITTEN** | OperationRule + OPERATIONS_MATRIX architecture. No OperationType, no Capability, no _RO, no classify_command |
| `enforcement_v2.py` | **REWRITTEN** | Single enforce() with find_operation_rule() scan. No classify_command |
| `world_adapter_v2.py` | **REWRITTEN** | Mode-agnostic: reads mode dynamically. No mode param in constructor/factory |
| `server.py _ck3_exec_internal` | **PARTIALLY UPDATED** | Uses new enforce() signature, but ck3_exec is NOT yet functional end-to-end (inline ban, script location restriction, HMAC not implemented) |
| `server.py _get_world_v2` | **UPDATED** | No mode param in create() call |
| `server.py _reset_world_cache` | **UPDATED** | No longer clears v2 cache on mode change |
| `dir_ops.py` | **CLEAN** | Imports VALID_ROOT_KEYS (still valid), no OperationType import |
| `unified_tools.py (ck3_file)` | **NOT MIGRATED** | Still uses v1 enforcement.py |
| `unified_tools.py (ck3_git)` | **NOT MIGRATED** | Still uses v1 enforcement.py |

### Must Be Done Before Testing

1. **Reload VS Code window** — MCP server Python process has stale modules in `sys.modules`. Disk files are correct but the running process loaded old modules at startup. Only fix: Ctrl+Shift+P → "Developer: Reload Window"
2. **Re-initialize mode** — `ck3_get_mode_instructions(mode="ck3raven-dev")` with HAT token after reload

### Next Steps (Priority Order)

1. **VISIBILITY_MATRIX subfolder gating** — Port v1 per-subfolder visibility with conditions to v2. Key case: ck3lens should only see mods in session.mods within user_docs, not arbitrary subdirectories.
2. **Test v2 stack** — Reload window, re-init mode, test ck3_dir (pwd, list root, list mod), test ck3_exec enforcement.
3. **Migrate ck3_file to v2** — unified_tools.py still uses v1 enforcement.py.
4. **Migrate ck3_git to v2** — unified_tools.py still uses v1 enforcement.py.
5. **Remove v1 modules** — After all tools migrated.
6. **Commit** — All v2 changes as single coherent commit.

---

## 10) What This Does NOT Do

- **No sandboxing** — ck3_exec remains a privileged break-glass tool.
- **No AST inspection** of scripts.
- **No permission oracles** — enforcement decides at execution time only.
- **No `mod_paths` dict** — WA consults `session.mods` directly.
- **No host paths in Reply** — Reply is semantic, VisibilityRef is capability.
- **No namespace coercion** — output preserves input namespace.
- **No OperationType enum** — `find_operation_rule()` scans OPERATIONS_MATRIX rules directly.
- **No _RO entries** — reads and mutations both use `OperationRule` in the same OPERATIONS_MATRIX; reads have no conditions.
- **No abstract tool clusters** — real tool+command pairs are the classification key.

---

## 11) Revision History

| Date | Change |
|------|--------|
| 2026-02-18 (initial) | Design brief created with OperationType + Capability + OPERATIONS_MATRIX |
| 2026-02-18 (rev 1) | WA v2 made mode-agnostic (dynamic mode reads) |
| 2026-02-18 (rev 2) | **Major rewrite:** Removed OperationType enum, Capability class, _RO. Introduced OperationRule + OPERATIONS_MATRIX with command frozensets. enforcement_v2 uses find_operation_rule() instead of classify_command. |
| 2026-02-18 (rev 2, addendum) | Identified open design issue: VISIBILITY_MATRIX needs subfolder gating with conditions (from v1, not yet ported) |
| 2026-02-20 (rev 3) | **Doc sync:** Updated all references from MutationRule/MUTATIONS_MATRIX/MutationKey to OperationRule/OPERATIONS_MATRIX/OperationKey to match actual code. Updated ck3_exec status to NOT FUNCTIONAL. Removed classify_command references. |
