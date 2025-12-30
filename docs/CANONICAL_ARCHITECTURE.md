# CK3Raven / CK3Lens — Canonical Architecture

> **Status:** AUTHORITATIVE  
> **Last Updated:** December 30, 2025  
> **Purpose:** Single source of truth for all architectural decisions

---

## Canonical Permissions Model

**Permissions apply to mutation actions (read / write / delete) executed against concrete filesystem targets.**

- In **ck3lens mode**, `mods[]` exist only to provide path roots and canonical addressing for targets.
- In **ck3raven-dev mode**, mods are not part of the execution or permission model; only paths and mutation actions exist.

Nothing elsewhere in this document may contradict this formulation.

---

## Quick Reference (Read This First)

Every agent working on this codebase MUST understand these 5 rules:

| # | Rule | Violation Example |
|---|------|-------------------|
| 1 | **ONE enforcement boundary** — only `enforcement.py` may deny operations | Adding `if not can_write(path)` anywhere else |
| 2 | **NO permission oracles** — never ask "am I allowed?" outside enforcement | Creating `is_path_writable()` helper |
| 3 | **mods[] is THE mod list** — no parallel lists | Creating `local_mods[]` or `editable_mods[]` |
| 4 | **WorldAdapter = resolution** — it resolves paths to canonical addresses, NOT permission decisions | Using `adapter.resolve()` result to gate writes |
| 5 | **Enforcement = decisions** — it decides allow/deny at execution time | Pre-checking permissions before calling enforcement |

---

## Table of Contents

| Section | Summary | Link |
|---------|---------|------|
| **1. Enforcement** | Single gate for all policy decisions | [→ Details](#1-enforcement-architecture) |
| **2. Resolution** | WorldAdapter resolves paths to canonical addresses | [→ Details](#2-resolution-architecture) |
| **3. Playsets** | How mods are grouped and filtered | [→ Details](#3-playset-architecture) |
| **4. Path Resolution** | Canonical path normalization pipeline | [→ Details](#4-path-resolution) |
| **5. MCP Tools** | Canonical pattern for all MCP tool implementations | [→ Details](#5-mcp-tool-architecture) |
| **6. Banned Terms** | Hard-banned naming patterns | [→ Details](#6-banned-terms) |
| **7. File Locations** | Where canonical implementations live | [→ Details](#7-file-locations) |

---

## 1. Enforcement Architecture

**Canonical File:** `tools/ck3lens_mcp/ck3lens/policy/enforcement.py`

### Key Points

- **ALL** "can I do X?" questions go through `enforce_policy()` or `_enforce_ck3lens_write()`
- Returns `ALLOW`, `DENY`, or `REQUIRE_TOKEN` — never throws for policy denial
- Enforcement happens at **execution time**, not at planning/validation time
- No pre-checks, no early denials, no "fail fast" permission logic

### Enforcement Scope

Enforcement evaluates whether a specific **mutation action** (`file_read`, `file_write`, `file_delete`) may be applied to a **resolved target**.

- Enforcement does **not** evaluate mods, directories, or abstract containers.
- Enforcement targets are derived from `CanonicalAddress` after resolution.
- Launcher registry is a **path domain only**. Mutation actions targeting `LAUNCHER_REGISTRY` paths return `REQUIRE_TOKEN`. All registry changes are executed as standard file mutations and are not a separate operation type.

### Usage Pattern

```python
from ck3lens.policy.enforcement import enforce_policy, EnforcementRequest

result = enforce_policy(EnforcementRequest(
    operation=OperationType.FILE_WRITE,
    mode="ck3lens",
    tool_name="ck3_file",
    mod_name="MSC",
    rel_path="common/traits/zzz_fix.txt",
))

if result.decision != Decision.ALLOW:
    return {"error": result.reason}
```

### What Enforcement Checks

| Domain | Decision |
|--------|----------|
| WIP workspace writes | Always ALLOW |
| Local mod writes | ALLOW with contract |
| Workshop/vanilla writes | DENY (absolute) |
| Launcher registry | REQUIRE_TOKEN |
| File deletion | REQUIRE_TOKEN |

---

## 2. Resolution Architecture

**Canonical File:** `tools/ck3lens_mcp/ck3lens/world_adapter.py`

### Key Points

- **ALL** "does X exist?" and "where is X?" questions go through `WorldAdapter.resolve()`
- Resolution is **structural identity**, not permission — it answers what/where, never allowed/denied
- Returns `ResolutionResult` with `found`, `address`, `absolute_path`, `domain`, etc.
- The `ui_hint_potentially_editable` field is for **display only** — **NEVER use in control flow**

### What Resolution Does

| Responsibility | Yes/No |
|----------------|--------|
| Parse user input into canonical address | ✅ |
| Determine domain (WIP, LOCAL_MOD, VANILLA, WORKSHOP, LAUNCHER_REGISTRY) | ✅ |
| Compute absolute filesystem path | ✅ |
| Fail for invalid address format | ✅ |
| Fail for path not found (for reads) | ✅ |
| Decide "allowed" or "denied" | ❌ |
| Pre-check writability | ❌ |
| Branch on domain to deny mutation | ❌ |

### Usage Pattern

```python
adapter = LensWorldAdapter(lens, db, config)
result = adapter.resolve("common/traits/00_traits.txt")

if not result.found:
    raise FileNotFoundError(...)  # NOT PermissionError - structural error only
```

### Resolution vs Enforcement

| Question | Go To | Error Type |
|----------|-------|------------|
| "Does this file exist?" | WorldAdapter | FileNotFoundError |
| "What is the canonical address?" | WorldAdapter | ValueError (invalid format) |
| "Can I write to this file?" | enforcement.py | PermissionError (via DENY) |
| "What source provides this file?" | WorldAdapter | N/A (returns metadata) |

---

## 3. Playset Architecture

**Canonical File:** `src/ck3raven/db/lens.py` (PlaysetLens)

### Key Points

- A **Playset** is a named collection of mods with load order
- `PlaysetLens` is the runtime filter that scopes all DB queries to one playset
- `Session.mods[]` is THE authoritative list of mods — no parallel lists
- `Session.local_mods_folder` is a single `Path` for containment checks

### Data Flow

```
Launcher Playset → playsets/*.json → PlaysetLens → DB Queries (filtered)
```

### Mod Types

| Type | Source | Writable |
|------|--------|----------|
| Vanilla | Steam game install | Never |
| Workshop | Steam Workshop | Never |
| Local | Documents/mod/ folder | Yes (if in local_mods_folder) |

**Full Details:** [PLAYSET_ARCHITECTURE.md](PLAYSET_ARCHITECTURE.md)

---

## 4. Path Resolution

### Canonical Path Normalization Pipeline (MANDATORY)

1. **User-supplied input is interpreted only as a request to identify a target, never as a permission query.**

2. **All tools must call `WorldAdapter.resolve()` exactly once per target.**

3. **`ResolutionResult.address` is the sole canonical identity of the target.**

4. **For ck3lens mod mutations**, enforcement targets are derived from `(mod_name, rel_path)` contained in the address.

5. **For non-mod domains** (vanilla, workshop, wip, ck3raven, launcher registry), enforcement targets are expressed as canonical addresses.

6. **`ResolutionResult.absolute_path` is used exclusively for filesystem execution.**

7. **No secondary path derivation, normalization, or inference is permitted outside this pipeline.**

### Prohibited Patterns

- Computing relative paths outside WorldAdapter
- Inferring mod identity from filesystem paths
- Branching control flow based on domain classification
- Using UI hint metadata in execution or permission logic

### Canonical Path Utility Requirement

A single shared path normalization utility must exist and be used by all tools.

Its responsibilities are limited to:
- Parsing user input
- Calling `WorldAdapter.resolve()`
- Exposing enforcement targets derived from canonical addresses
- Exposing execution paths derived from absolute paths

**This utility must not perform permission checks or eligibility logic.**

### Domain Classification

| Path Pattern | Domain |
|--------------|--------|
| Under `~/.ck3raven/wip/` | `WIP` |
| Under `local_mods_folder` | `LOCAL_MOD` |
| Under vanilla game folder | `VANILLA` |
| Under Steam Workshop | `WORKSHOP` |
| Under launcher DB | `LAUNCHER_REGISTRY` |

### Resolution Flow

```
user_input → WorldAdapter.resolve() → ResolutionResult {
    found: bool,
    address: CanonicalAddress,  # sole identity
    absolute_path: Path,        # for execution only
    domain: str,                # structural classification
    ui_hint_potentially_editable: bool  # display only, NEVER control flow
}
```

---

## 5. MCP Tool Architecture

**⚠️ CRITICAL: Any new MCP tool MUST follow this canonical pattern.**

### Required Components

Every MCP tool must use these canonical components:

| Component | Purpose | Import From |
|-----------|---------|-------------|
| `WorldAdapter` / `get_world()` | Path resolution + visibility | `ck3lens.world_router` |
| `enforce_policy()` | All write/delete operations | `ck3lens.policy.enforcement` |
| `Session` | Agent mode + playset context | `ck3lens.session` |
| `CanonicalAddress` | Uniform path representation | `ck3lens.world_adapter` |

### Canonical Tool Pattern

```python
from ck3lens.world_router import get_world
from ck3lens.policy.enforcement import enforce_policy, EnforcementRequest, OperationType

def ck3_example_tool(
    path: str,
    content: str | None = None,
) -> dict:
    """Example MCP tool following canonical pattern."""
    
    # 1. Get session context
    session = _get_session()
    db = _get_db()
    
    # 2. Get WorldAdapter for visibility/path resolution
    world = get_world(db=db, lens=_get_lens())
    
    # 3. Resolve path through WorldAdapter
    result = world.resolve(path)
    if not result.found:
        return {"error": f"Not found in LensWorld: {path}"}
    
    # 4. For READ operations: use result.absolute_path directly
    if content is None:
        return {"content": result.absolute_path.read_text()}
    
    # 5. For WRITE operations: call enforcement.py (NEVER pre-check!)
    enforcement_result = enforce_policy(EnforcementRequest(
        operation=OperationType.FILE_WRITE,
        mode=session.mode,
        tool_name="ck3_example_tool",
        mod_name=result.address.identifier,
        rel_path=result.address.relative_path,
    ))
    
    if enforcement_result.decision != Decision.ALLOW:
        return {"error": enforcement_result.reason}
    
    # 6. Execute the write
    result.absolute_path.write_text(content)
    return {"success": True}
```

### NO-ORACLE RULES for MCP Tools

**FORBIDDEN in MCP tools:**

```python
# ❌ NEVER pre-check writability
if not is_path_writable(path):
    return {"error": "Not writable"}

# ❌ NEVER use ResolutionResult for permission
if not result.ui_hint_potentially_editable:
    return {"error": "Cannot edit"}

# ❌ NEVER create local permission helpers
def can_write_to_mod(mod_name: str) -> bool:
    ...

# ❌ NEVER gate on visibility metadata
if result.source == "vanilla":
    return {"error": "Cannot write to vanilla"}
```

**REQUIRED pattern:**

```python
# ✅ ALWAYS call enforcement.py for write operations
result = enforce_policy(EnforcementRequest(...))
if result.decision != Decision.ALLOW:
    return {"error": result.reason}
```

### No-Oracle Invariant

**Any logic that answers "is this allowed?" outside enforcement is forbidden.**

Helper functions using `is_*`, `can_*`, or capability-style naming are not permitted.

### Canonical Tool Flow

```
1. Resolve via WorldAdapter (identity only — structural errors only)
2. Enforce at boundary (ALLOW / DENY / REQUIRE_TOKEN)
3. Execute (impl functions: syntax validation + filesystem mutation)
```

### Mode-Aware Behavior

MCP tools MUST be mode-aware. The mode is available from `session.mode`:

| Mode | Behavior |
|------|----------|
| `ck3lens` | Write to live mods only, use mod_name + rel_path |
| `ck3raven-dev` | Write to ck3raven source, use contract + token |

### Execution Model

- **In ck3lens**, mods provide path context only; they never confer permission.
- **In ck3raven-dev**, mods are not part of the execution model.
- **In all modes**, permissions apply only to mutation actions on resolved targets.

```python
session = _get_session()
if session.mode == "ck3lens":
    # Uses mod_name + rel_path addressing
    ...
elif session.mode == "ck3raven-dev":
    # Uses raw path with contract validation
    ...
```

### Address Types

Use `CanonicalAddress` for uniform path handling:

| Address Type | Example | Purpose |
|--------------|---------|---------|
| `mod:MSC/common/traits/fix.txt` | Live mod file | Write target |
| `vanilla:/common/traits/00_traits.txt` | Vanilla file | Read-only reference |
| `wip:/analysis.py` | WIP workspace | Script execution |
| `ck3raven:/src/parser.py` | ck3raven source | Dev mode only |

---

## 6. Banned Terms

These terms are banned by **concept, not spelling**. Semantic equivalents are equally forbidden.

Use is permitted **only** in documentation describing the ban itself.

### Permission / Capability Oracles (HARD BAN)

```
can_write
can_edit
can_delete
is_writable
is_editable
is_allowed
is_path_allowed
is_path_writable
writable_mod
editable_mod
mod_write
mod_read
mod_delete
```

### Parallel Authority Structures (HARD BAN)

```
editable_mods
writable_mods
local_mods (as derived or filtered lists)
live_mods
mod_whitelist
whitelist
blacklist
mod_roots
```

### Required Replacements

| ❌ Banned | ✅ Replacement | Reason |
|-----------|----------------|--------|
| `mod_roots` | `mod_paths` | "roots" implies authority |
| `is_writable` | `ui_hint_potentially_editable` | explicit non-authority |
| `local_mods[]` | `mods[]` + containment check | no parallel lists |
| `can_write_to_mod()` | N/A — delete entirely | oracle function |
| `is_path_allowed()` | N/A — delete entirely | oracle function |

**Full Details:** [CANONICAL REFACTOR INSTRUCTIONS.md](CANONICAL%20REFACTOR%20INSTRUCTIONS.md)

---

## 7. File Locations

### Canonical Source Files

| Responsibility | File |
|----------------|------|
| Enforcement (all policy) | `tools/ck3lens_mcp/ck3lens/policy/enforcement.py` |
| Resolution (WorldAdapter) | `tools/ck3lens_mcp/ck3lens/world_adapter.py` |
| Playset filtering | `src/ck3raven/db/lens.py` |
| Session state | `tools/ck3lens_mcp/ck3lens/session.py` |
| Path classification | `tools/ck3lens_mcp/ck3lens/policy/ck3lens_rules.py` |
| Tokens | `tools/ck3lens_mcp/ck3lens/policy/tokens.py` |
| WIP workspace | `tools/ck3lens_mcp/ck3lens/policy/wip_workspace.py` |

### Archived (DO NOT USE)

| File | Reason | Location |
|------|--------|----------|
| `hard_gates.py` | Superseded by enforcement.py | `archive/deprecated_policy/` |
| `script_sandbox.py` (policy) | Moved to tools layer | `archive/deprecated_policy/` |
| `lensworld_sandbox.py` | Merged into WorldAdapter | `archive/deprecated_policy/` |

---

## Related Documents

| Document | Purpose |
|----------|---------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Full system overview, directory structure |
| [PLAYSET_ARCHITECTURE.md](PLAYSET_ARCHITECTURE.md) | Deep dive on playset management |
| [CANONICAL REFACTOR INSTRUCTIONS.md](CANONICAL%20REFACTOR%20INSTRUCTIONS.md) | Banned terms, NO-ORACLE rules |
| [CK3LENS_POLICY_ARCHITECTURE.md](CK3LENS_POLICY_ARCHITECTURE.md) | ck3lens mode policy details |
| [CK3RAVEN_DEV_POLICY_ARCHITECTURE.md](CK3RAVEN_DEV_POLICY_ARCHITECTURE.md) | ck3raven-dev mode policy details |

---

## Checklist for New Code

Before submitting any code, verify:

- [ ] No permission checks outside `enforcement.py`
- [ ] No banned terms in executable code
- [ ] No parallel mod lists created
- [ ] No helper answers permission questions outside enforcement
- [ ] WorldAdapter used for resolution only, not permission
- [ ] Enforcement called at execution time, not planning time
- [ ] `mods[]` is the only mod list referenced
- [ ] All mutations flow: resolve → enforce → execute
- [ ] Launcher registry treated only as a path domain
- [ ] No section treats mods as permission objects
