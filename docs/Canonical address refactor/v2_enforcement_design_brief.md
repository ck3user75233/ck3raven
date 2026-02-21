# V2 Enforcement Architecture — Design Brief

> **Date:** February 18, 2026
> **Status:** Partially implemented — see §9 for current status
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
6. **`resolve()` returns `tuple[Reply, Optional[VisibilityRef]]`.** No intermediate `VisibilityResolution` dataclass.
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
    │   ├─ Accepts: root category paths, mod:Name/path
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

Pure data. Keyed by `(mode, root_key, subdirectory | None)`.

### Current State (implemented)

```python
VISIBILITY_MATRIX: dict[VisibilityKey, VisibilityRule] = {
    # ck3lens mode — steam and user_docs/mod require path_in_session_mods
    ("ck3lens", "game", None):              VisibilityRule(),
    ("ck3lens", "steam", None):             VisibilityRule((path_in_session_mods(),)),
    ("ck3lens", "user_docs", "mod"):        VisibilityRule((path_in_session_mods(),)),
    ("ck3lens", "ck3raven_data", None):     VisibilityRule(),
    ("ck3lens", "vscode", None):            VisibilityRule(),
    ("ck3lens", "repo", None):              VisibilityRule(),

    # ck3raven-dev mode — all roots visible without conditions
    ("ck3raven-dev", "game", None):             VisibilityRule(),
    ("ck3raven-dev", "steam", None):            VisibilityRule(),
    ("ck3raven-dev", "user_docs", None):        VisibilityRule(),
    ("ck3raven-dev", "ck3raven_data", None):    VisibilityRule(),
    ("ck3raven-dev", "vscode", None):           VisibilityRule(),
    ("ck3raven-dev", "repo", None):             VisibilityRule(),
}
```

### Subfolder Visibility Gating — RESOLVED

The VISIBILITY_MATRIX uses `(mode, root_key, subdirectory)` 3-tuple keying with condition predicates. `check_visibility()` does subdirectory-specific lookup first, then root-level fallback.

Key case: ck3lens `steam` and `user_docs/mod` carry a `path_in_session_mods` condition — the resolved host path must fall within a `session.mods` entry. This ensures ck3lens only sees mods in the active playset.

### Mod Visibility

Mods are NOT in the visibility matrix. Mod visibility is structural:
- `session.mods` IS the visible mod list.
- WA consults `session.mods` at resolution time.
- If the mod name isn't in `session.mods`, resolution fails.

---

## 3) COMMAND CLASSIFICATION

Commands are organized as named `frozenset` constants. Each `OperationRule` in the matrix carries its command set directly. Enforcement walks the matrix to find the matching rule — there is no separate `classify_command()` function.

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
```

### ck3_exec special case

`ck3_exec` does not have sub-commands — its `command` parameter IS the shell string. Since there is no finite set of `("ck3_exec", "...")` pairs, `find_operation_rule()` uses an identity check: if `tool == "ck3_exec"` and `rule.commands is EXEC_COMMANDS`, the rule matches. This is an implementation detail — the EXEC rule still carries conditions (e.g., `exec_signed`) that enforcement evaluates normally.

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
        OperationRule(FILE_WRITE_COMMANDS, (has_contract(),)),
    ),
    # ck3raven-dev — repo: reads + writes (with contract)
    ("ck3raven-dev", "repo", None): (
        OperationRule(ALL_READ_COMMANDS),
        OperationRule(FILE_WRITE_COMMANDS, (has_contract(),)),
        OperationRule(GIT_MUTATE_COMMANDS, (has_contract(),)),
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
    # 3. No matching rule → rb.denied(denial_code)
    # 4. Rule has no conditions (read) → rb.success(success_code)
    # 5. Conditions check → rb.denied(denial_code) or rb.success(success_code)
```

No `OperationType`. No `tool_cluster`. No `classify_command()`. The tool handler passes its real `tool` name and `command`. Enforcement scans rules and decides.

### Outstanding: Denial code refactoring

**Current state:** enforcement_v2.py uses `EN-GATE-D-001` uniformly for all denials, with varying detail strings in the data dict.

**Required (post ck3_exec migration):** Denial codes should be area-specific to reflect what the user was trying to do (e.g., `EN-EXEC-D-001` for exec denials, `EN-WRITE-D-002` for write denials). Branching should be on the reply code, and messages should live in the ReplyBuilder registry. This aligns with the canonical reply system where code-based branching, not data-dict inspection, is the standard pattern.

---

## 6) Condition Predicates

Condition predicates are pure True/False checks. They are standalone factory functions that return `Condition` instances. Enforcement evaluates them — conditions do NOT deny, enforcement does.

```python
@dataclass(frozen=True)
class Condition:
    name: str
    check: Callable[..., bool]
```

The `Condition` dataclass has only `name` and `check`. There is no `denial` field — conditions do not own denial codes. Enforcement makes the deny decision and produces the appropriate denial code.

### Implemented condition predicates

| Factory | Purpose | Context keys |
|---------|---------|-------------|
| `has_contract()` | True if `get_active_contract()` returns a contract | `has_contract` (bool) |
| `exec_signed()` | True if active contract has valid script signature for this script. Internally calls `validate_script_signature()` for HMAC verification. | `script_host_path` (str), `content_sha256` (str) |
| `path_in_session_mods()` | True if resolved host path falls within a `session.mods` entry | `session` (object), `host_abs` (Path) |
| `mod_in_session()` | True if mod name is in `session.mods` | `session` (object), `mod_name` (str) |

### Planned condition predicates

| Factory | Purpose | Context keys |
|---------|---------|-------------|
| `command_whitelisted()` | True if ck3_exec command matches a pattern in the protected command whitelist file | `command` (str) |

Conditions receive `**context` from `enforce()`. Tool handlers build the context dict.

---

## 7) world_adapter_v2.py — Key Decisions

### Mode-Agnostic (Dynamic Reads)

WA v2 does NOT store mode at construction. `resolve()` calls `get_agent_mode()` from `agent_mode.py` dynamically on every invocation.

- Constructor: `__init__(*, session, roots)` — no mode parameter
- Factory: `create(*, session)` — no mode parameter
- `mode` property: `return _get_mode() or "uninitiated"`
- `_get_mode()`: module-level function that imports and calls `get_agent_mode()`
- If mode is None → returns `WA-SYS-I-001` ("Agent mode not initialized")
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

Input forms: `root:<key>/<path>`, `mod:Name/<path>`, legacy `ROOT_REPO:/<path>`.
Output: Reply.data["resolved"] preserves input namespace.
Rejected: bare relative paths, host-absolute paths, `root:ROOT_REPO/...`.

---

## 8) Tool Layer Changes

Tool handlers pass real tool+command to enforce:

```python
# In ck3_exec handler (server.py) — PARTIALLY IMPLEMENTED
# Uses v2 enforce() but inline ban, script restriction, HMAC not yet enforced
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

### On Disk (current as of 2026-02-21)

| File | Status | Notes |
|------|--------|-------|
| `capability_matrix_v2.py` | **DONE** | OperationRule + OPERATIONS_MATRIX + VISIBILITY_MATRIX with subfolder gating + conditions |
| `enforcement_v2.py` | **DONE** | Single enforce() with find_operation_rule() scan. Denial codes need area-specific refactor. |
| `world_adapter_v2.py` | **DONE** | Mode-agnostic: reads mode dynamically. No mode param in constructor/factory |
| `server.py _ck3_exec_internal` | **PARTIALLY MIGRATED** | Uses WA2 + enforce_v2, but inline ban, script restriction, command whitelist, HMAC not implemented |
| `server.py _get_world_v2` | **DONE** | No mode param in create() call |
| `server.py _reset_world_cache` | **DONE** | No longer clears v2 cache on mode change |
| `dir_ops.py` | **CLEAN** | Imports VALID_ROOT_KEYS (still valid), no OperationType import |
| `unified_tools.py (ck3_file)` | **NOT MIGRATED** | Still uses v1 enforcement.py |
| `unified_tools.py (ck3_git)` | **NOT MIGRATED** | Still uses v1 enforcement.py |
| Sprint 0 tests | **DONE** | 92/92 passing, committed (4ac8493) |

### Next Steps (Priority Order)

1. **ck3_exec completion** — Implement inline ban, script location restriction, command whitelist condition predicate, HMAC signing flow.
2. **Denial code refactoring** — Area-specific codes (EN-EXEC-D-001, EN-WRITE-D-002, etc.) with ReplyBuilder registry messages.
3. **Migrate ck3_file to v2** — unified_tools.py still uses v1 enforcement.py.
4. **Migrate ck3_git to v2** — unified_tools.py still uses v1 enforcement.py.
5. **Remove v1 modules** — After all tools migrated.

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
- **No `classify_command()` function** — enforcement walks the matrix to find matching rules. There has never been a separate classification function.

---

## 11) Design Decisions from Implementation

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-02-18 | Design brief created with OperationType + Capability + OPERATIONS_MATRIX | Initial design |
| 2026-02-18 | WA v2 made mode-agnostic (dynamic mode reads) | Mode changes shouldn't require WA recreation |
| 2026-02-18 | Removed OperationType enum, Capability class, _RO entries. Introduced OperationRule with command frozensets. | Simpler: enforcement walks data instead of classifying commands separately |
| 2026-02-18 | VISIBILITY_MATRIX uses 3-tuple keying with subfolder conditions | Ported from v1; enables per-subdirectory visibility gating |
| 2026-02-20 | Doc sync: MutationRule/MUTATIONS_MATRIX → OperationRule/OPERATIONS_MATRIX | Naming alignment |
| 2026-02-21 | `exec_signed` condition predicate calls `validate_script_signature()` internally for HMAC verification | Single public API surface (the condition), crypto validation is internal |
| 2026-02-21 | `ck3_exec` matching uses identity check on EXEC_COMMANDS frozenset sentinel | Shell string as command param means no finite (tool, command) pairs — identity sentinel solves this |
| 2026-02-21 | All failed conditions reported by name in denial Reply data | Provides diagnostics without per-condition denial codes — denial codes are enforcement's responsibility |
| 2026-02-21 | `Condition` dataclass has `name` + `check` only, no `denial` field | Conditions are pure predicates; enforcement owns denial decisions |
