# CK3Raven / CK3Lens Ã¢â‚¬â€ Canonical Architecture

> **Status:** AUTHORITATIVE  
> **Last Updated:** January 17, 2026  
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
| 1 | **ONE enforcement boundary** Ã¢â‚¬â€ only `enforcement.py` may deny operations | Adding `if not can_write(path)` anywhere else |
| 2 | **NO permission oracles** Ã¢â‚¬â€ never ask "am I allowed?" outside enforcement | Creating `is_path_writable()` helper |
| 3 | **mods[] is THE mod list** Ã¢â‚¬â€ no parallel lists | Creating `local_mods[]` or `editable_mods[]` |
| 4 | **WorldAdapter = resolution** Ã¢â‚¬â€ it resolves paths to canonical addresses, NOT permission decisions | Using `adapter.resolve()` result to gate writes |
| 5 | **Enforcement = decisions** Ã¢â‚¬â€ it decides allow/deny at execution time | Pre-checking permissions before calling enforcement |

---

## Table of Contents

| Section | Summary | Link |
|---------|---------|------|
| **1. Enforcement** | Single gate for all policy decisions | [Ã¢â€ â€™ Details](#1-enforcement-architecture) |
| **2. Resolution** | WorldAdapter resolves paths to canonical addresses | [Ã¢â€ â€™ Details](#2-resolution-architecture) |
| **3. Playsets** | How mods are grouped and filtered | [Ã¢â€ â€™ Details](#3-playset-architecture) |
| **4. Path Resolution** | Canonical path normalization pipeline | [Ã¢â€ â€™ Details](#4-path-resolution) |
| **5. MCP Tools** | Canonical pattern for all MCP tool implementations | [Ã¢â€ â€™ Details](#5-mcp-tool-architecture) |
| **6. Banned Terms** | Hard-banned naming patterns | [Ã¢â€ â€™ Details](#6-banned-terms) |
| **7. File Locations** | Where canonical implementations live | [→ Details](#7-file-locations) |
| **8. Capability Handles** | DbHandle/FsHandle + _CAP_TOKEN pattern | [→ Details](#8-capability-handles-pattern-december-2025) |
| **9. Mode-Aware Addressing** | ck3lens vs ck3raven-dev addressing | [→ Details](#9-mode-aware-addressing) |
| **10. Single WorldAdapter** | One class with mode-specific behavior | [→ Details](#10-single-worldadapter-architecture) |
| **11. arch_lint v2.2** | Automated architecture linter | [→ Details](#11-arch_lint-v22) |
| **12. _*_internal Convention** | Internal method naming pattern | [→ Details](#12-_internal-method-naming-convention) |
| **13. AST Identity Invariant** | Content-identity model for ASTs | [→ Details](#13-ast-identity-invariant-january-2026) |
| **14. Single-Writer DB** | QBuilder daemon as sole DB writer | [→ Details](#14-single-writer-db-architecture-january-2026) |
---

## 1. Enforcement Architecture

**Canonical File:** `tools/ck3lens_mcp/ck3lens/policy/enforcement.py`

### Key Points

- **ALL** "can I do X?" questions go through `enforce_policy()` or `_enforce_ck3lens_write()`
- Returns `ALLOW`, `DENY`, or `REQUIRE_TOKEN` Ã¢â‚¬â€ never throws for policy denial
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
- Resolution is **structural identity**, not permission Ã¢â‚¬â€ it answers what/where, never allowed/denied
- Returns `ResolutionResult` with `found`, `address`, `absolute_path`, `domain`, etc.
- The `ui_hint_potentially_editable` field is for **display only** Ã¢â‚¬â€ **NEVER use in control flow**

### What Resolution Does

| Responsibility | Yes/No |
|----------------|--------|
| Parse user input into canonical address | Ã¢Å“â€¦ |
| Determine domain (WIP, LOCAL_MOD, VANILLA, WORKSHOP, LAUNCHER_REGISTRY) | Ã¢Å“â€¦ |
| Compute absolute filesystem path | Ã¢Å“â€¦ |
| Fail for invalid address format | Ã¢Å“â€¦ |
| Fail for path not found (for reads) | Ã¢Å“â€¦ |
| Decide "allowed" or "denied" | Ã¢ÂÅ’ |
| Pre-check writability | Ã¢ÂÅ’ |
| Branch on domain to deny mutation | Ã¢ÂÅ’ |

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
- `Session.mods[]` is THE authoritative list of mods Ã¢â‚¬â€ no parallel lists
- `Session.local_mods_folder` is a single `Path` for containment checks

### Data Flow

```
Launcher Playset Ã¢â€ â€™ playsets/*.json Ã¢â€ â€™ PlaysetLens Ã¢â€ â€™ DB Queries (filtered)
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

**`normalize_path_input()` in `world_adapter.py` is THE canonical path normalization utility.**

This is THE single entry point for path resolution in MCP tools. All tools must use it.

```python
from ck3lens.world_adapter import normalize_path_input

# Resolve any path input to canonical form
result = normalize_path_input(world, path=user_input)
if not result.found:
    return {"error": result.error_message}
```

Its responsibilities are limited to:
- Parsing user input (absolute paths, canonical addresses, relative paths)
- Calling `WorldAdapter.resolve()`
- Returning a `ResolutionResult` with `address`, `absolute_path`, `domain`, etc.

**This utility must not perform permission checks or eligibility logic.**

#### Related Utility: `WorldAdapter.normalize()`

`WorldAdapter.normalize(path: str)` is a lower-level utility for filesystem path comparison:
- Converts backslashes to forward slashes
- Lowercases for case-insensitive comparison
- Used internally for path matching, NOT for path resolution

Do NOT confuse these two:
| Function | Purpose | Use When |
|----------|---------|----------|
| `normalize_path_input()` | Path resolution entry point | Resolving user input to canonical address |
| `WorldAdapter.normalize()` | Path comparison utility | Comparing filesystem paths |

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
user_input Ã¢â€ â€™ WorldAdapter.resolve() Ã¢â€ â€™ ResolutionResult {
    found: bool,
    address: CanonicalAddress,  # sole identity
    absolute_path: Path,        # for execution only
    domain: str,                # structural classification
    ui_hint_potentially_editable: bool  # display only, NEVER control flow
}
```

---

## 5. MCP Tool Architecture

**Ã¢Å¡Â Ã¯Â¸Â CRITICAL: Any new MCP tool MUST follow this canonical pattern.**

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
# Ã¢ÂÅ’ NEVER pre-check writability
if not is_path_writable(path):
    return {"error": "Not writable"}

# Ã¢ÂÅ’ NEVER use ResolutionResult for permission
if not result.ui_hint_potentially_editable:
    return {"error": "Cannot edit"}

# Ã¢ÂÅ’ NEVER create local permission helpers
def can_write_to_mod(mod_name: str) -> bool:
    ...

# Ã¢ÂÅ’ NEVER gate on visibility metadata
if result.source == "vanilla":
    return {"error": "Cannot write to vanilla"}
```

**REQUIRED pattern:**

```python
# Ã¢Å“â€¦ ALWAYS call enforcement.py for write operations
result = enforce_policy(EnforcementRequest(...))
if result.decision != Decision.ALLOW:
    return {"error": result.reason}
```

### No-Oracle Invariant

**Any logic that answers "is this allowed?" outside enforcement is forbidden.**

Helper functions using `is_*`, `can_*`, or capability-style naming are not permitted.

### Canonical Tool Flow

```
1. Resolve via WorldAdapter (identity only Ã¢â‚¬â€ structural errors only)
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
list_live_mods
getLiveMods
LiveModInfo
no_lens
editable_mods
list_live_mods
list_live_mods
getLiveMods
LiveModInfo
no_lens
editable_mods
getLiveMods
LiveModInfo
mod_whitelist
whitelist
blacklist
mod_roots
```

### Visibility / Scope Caching (HARD BAN - December 2025)

```
_lens_cache
lens_cache
_validate_visibility()
_build_cv_filter()
_derive_*cvid*()
*_cv_filter*
*_visibility* helpers (outside WorldAdapter)
invalidate_lens_cache()
VisibilityScope (replaced by DbHandle)
_VISIBILITY_TOKEN (replaced by _CAP_TOKEN)
db_visibility() as primary API (use db_handle())
```

### Legacy Format Support (HARD BAN - December 2025)

```
_load_legacy_playset()
paths[] key in playsets (use mods[] only)
active_mod_paths.json (deprecated format)
```

### Bridge Playset Duplication (HARD BAN - January 2026)

The VS Code extension bridge (`bridge/server.py`) MUST delegate playset operations to MCP tools.
It MUST NOT duplicate playset logic or cache playset data.

**Banned patterns:**
```
active_playset_data         # Cached playset data = duplicate source of truth
active_playset_file         # Cached file reference = duplicate source of truth  
FROM playset_mods           # SQL against deprecated playset_mods table
playset_id = ?              # Database-based playset queries (use MCP tools)
self.playset_id             # Stored playset ID from deprecated DB queries
```

**Required pattern for bridge methods:**
```python
# ✓ CORRECT - thin wrapper that delegates to MCP tool
def get_playset_mods(self, params: dict) -> dict:
    from server import ck3_playset
    result = ck3_playset(command="mods")
    # Transform to extension format and return
    
# ✗ BANNED - duplicating playset file reading logic
def get_playset_mods(self, params: dict) -> dict:
    manifest = json.loads(manifest_path.read_text())  # Duplicating MCP logic!
    playset_data = json.loads(playset_path.read_text())  # Duplicating!
```

### Required Replacements

| Ã¢ÂÅ’ Banned | Ã¢Å“â€¦ Replacement | Reason |
|-----------|----------------|--------|
| `mod_roots` | `mod_paths` | "roots" implies authority |
| `is_writable` | `ui_hint_potentially_editable` | explicit non-authority |
| `local_mods[]` | `mods[]` + containment check | no parallel lists |
| `can_write_to_mod()` | N/A Ã¢â‚¬â€ delete entirely | oracle function |
| `is_path_allowed()` | N/A Ã¢â‚¬â€ delete entirely | oracle function |

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
- [ ] All mutations flow: resolve Ã¢â€ â€™ enforce Ã¢â€ â€™ execute
- [ ] Launcher registry treated only as a path domain
- [ ] No section treats mods as permission objects

---

## 8. Capability Handles Pattern (December 2025)

### Overview

**Capability handles** are unforgeable tokens that grant specific, scoped access to resources. They replace the oracle pattern where code would ask "am I allowed?" before acting.

Instead of:
```python
# Ã¢ÂÅ’ BANNED - oracle pattern
if can_write_to_db():
    conn.execute("INSERT ...")
```

We use:
```python
# Ã¢Å“â€¦ REQUIRED - capability handle pattern
handle = world.db_handle()  # Handle mints access or raises
handle.execute("INSERT ...")  # Access already validated
```

### DbHandle

**Purpose:** Scoped database access with built-in visibility filtering.

```python
@dataclass
class DbHandle:
    """Unforgeable database access handle."""
    _conn: sqlite3.Connection
    _cvid_filter: Optional[set[int]]  # None = no filter (ck3raven-dev)
    _cap_token: object  # Unforgeable identity token
    
    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        """Execute with automatic CVID filtering."""
        if self._cvid_filter is not None:
            # ck3lens mode: filter to active playset
            sql = self._apply_cvid_filter(sql)
        return self._conn.execute(sql, params)
```

**Key Properties:**
- `_cap_token` is an unforgeable object (created once at module load)
- `_cvid_filter` is `None` for ck3raven-dev (no restrictions), set for ck3lens
- Handles are minted by WorldAdapter, not constructed directly

### FsHandle

**Purpose:** Scoped filesystem access for specific paths.

```python
@dataclass
class FsHandle:
    """Unforgeable filesystem access handle."""
    _root: Path
    _writable: bool
    _cap_token: object
    
    def read(self, rel_path: str) -> str:
        """Read file under this handle's root."""
        full = self._root / rel_path
        return full.read_text()
    
    def write(self, rel_path: str, content: str) -> None:
        """Write file (only if handle is writable)."""
        if not self._writable:
            raise CapabilityError("Handle is read-only")
        full = self._root / rel_path
        full.write_text(content)
```

### _CAP_TOKEN Pattern

The `_CAP_TOKEN` is an unforgeable identity token that prevents handle spoofing:

```python
# At module level - created once, never exported
_CAP_TOKEN = object()

class DbHandle:
    def __init__(self, ..., _cap_token: object):
        if _cap_token is not _CAP_TOKEN:
            raise CapabilityError("Handles must be minted by WorldAdapter")
        self._cap_token = _cap_token
```

**Why this matters:**
- Only code with access to `_CAP_TOKEN` can create handles
- The token is never exported from the module
- External code cannot forge handles
- This is the Python equivalent of capability-based security

### Handle Minting

Only `WorldAdapter` may mint handles:

```python
class WorldAdapter:
    def db_handle(self) -> DbHandle:
        """Mint a database handle for current mode."""
        if self._mode == "ck3lens":
            cvid_filter = self._get_playset_cvids()
        else:
            cvid_filter = None  # ck3raven-dev: no filter
        
        return DbHandle(
            _conn=self._conn,
            _cvid_filter=cvid_filter,
            _cap_token=_CAP_TOKEN,
        )
```

---

## 9. Mode-Aware Addressing

### ck3lens Mode

Uses **mod_name + rel_path** addressing:

```python
# Tool receives:
ck3_file(command="write", mod_name="MSC", rel_path="common/traits/fix.txt", content="...")

# WorldAdapter resolves to:
CanonicalAddress(
    address_type=AddressType.MOD,
    identifier="MSC",  # mod_name
    relative_path="common/traits/fix.txt",
)
```

**Visibility:** Filtered to active playset (vanilla + enabled mods)

### ck3raven-dev Mode

Uses **raw path** addressing:

```python
# Tool receives:
ck3_file(command="write", path="tools/ck3lens_mcp/ck3lens/foo.py", content="...")

# WorldAdapter resolves to:
CanonicalAddress(
    address_type=AddressType.CK3RAVEN,
    identifier=None,
    relative_path="tools/ck3lens_mcp/ck3lens/foo.py",
)
```

**Visibility:** ck3raven source + WIP workspace (mods NOT part of execution model)

### Addressing Summary

| Mode | Primary Addressing | mods[] Used? | Visibility Filter |
|------|-------------------|--------------|-------------------|
| `ck3lens` | `mod_name` + `rel_path` | Yes | Active playset CVIDs |
| `ck3raven-dev` | Raw `path` | No | None (full access) |

---

## 10. Single WorldAdapter Architecture

**CRITICAL: There is ONE WorldAdapter class. Path resolution is MODE-AGNOSTIC.**

Previously, there were separate `LensWorldAdapter` and `DevWorldAdapter` classes. These have been consolidated into a single `WorldAdapter`.

### Path Resolution is Structural, Not Permission-Based

Resolution determines:
- What canonical domain does this path belong to? (ROOT_REPO, ROOT_GAME, ROOT_CK3RAVEN_DATA, etc.)
- What is the absolute filesystem path?
- If a path is invalid (and that includes being invalid because it is not visible to the agent which is requesting that path to be resolved)

Resolution code should endeavour to avoid complex branching logic within World_Adapter, instead relying on the canonical, modular visibility framework. [under construction]


### Mode Matters for Enforcement, Not Resolution

```python
# Resolution is the same regardless of mode
result = world.resolve("C:/path/to/file.txt")
# Returns: ResolutionResult with root_category, absolute_path, address

# Enforcement uses mode + root_category to decide permissions
from ck3lens.policy.capability_matrix import is_authorized
allowed = is_authorized(mode="ck3lens", root=result.root_category, operation="write")
```

### Visibility Filtering Applies to Database Queries Only

The term "visibility" in this architecture refers to **database query filtering**, not path resolution:

| Concept | Where It Applies | How |
|---------|------------------|-----|
| Path Resolution | WorldAdapter.resolve() | Mode-agnostic, structural |
| DB Visibility | DbHandle CVID filter | Filters queries to active playset CVIDs |
| Permissions | enforcement.py | Mode + domain → allow/deny |

### Banned Patterns

```
# Ã¢ÂÅ’ BANNED - separate adapter classes
LensWorldAdapter(...)
DevWorldAdapter(...)

# Ã¢ÂÅ’ BANNED - mod-related params in dev mode
WorldAdapter(mod_paths=..., mods_roots=...)

# Ã¢Å“â€¦ CORRECT - single adapter, mode from session
adapter = WorldAdapter(db=db, mode=session.mode)
```

---

## 11. arch_lint v2.2

**Location:** `scripts/arch_lint/`

### Purpose

Automated linter that detects architectural violations:

- **ORACLE-01**: Oracle-style function/variable names (`can_write`, `is_allowed`)
- **ORACLE-02**: Permission branching in if-conditions
- **TRUTH-01**: Parallel truth symbols (`local_mods`, `editable_mods`)
- **CONCEPT-03**: Lens concept explosion (`PlaysetLens`, `LensWorldAdapter`)
- **IO-01**: Raw IO calls outside handle modules
- **MUTATOR-01/02/03**: SQL/file/subprocess mutations outside builder

### Usage

```bash
# Run on entire codebase
python -m scripts.arch_lint

# JSON output
python -m scripts.arch_lint --json

# Errors only
python -m scripts.arch_lint --errors-only

# Skip unused symbol detection
python -m scripts.arch_lint --no-unused
```

### Configuration

Allowlists are in `scripts/arch_lint/config.py`:

```python
@dataclass(frozen=True)
class LintConfig:
    # Modules where raw IO is allowed
    allow_raw_io_in: tuple[str, ...] = (
        "world_adapter.py",
        "handles/",
        "fs_handle",
    )
    
    # Modules where mutators are allowed
    allow_mutators_in: tuple[str, ...] = (
        "builder",
        "write_handle",
    )
```

### Integration

arch_lint is intended to run in pre-commit hooks to prevent architectural drift.

---

## 12. _*_internal Method Naming Convention

Methods prefixed with `_*_internal` are implementation details that:

1. **Must not be called directly by MCP tools**
2. **May bypass normal validation** for performance
3. **Assume caller has already validated permissions**
4. **Are subject to change without notice**

### Example

```python
class WorldAdapter:
    def resolve(self, path: str) -> ResolutionResult:
        """Public API - validates input, handles errors."""
        if not path:
            return ResolutionResult.not_found("<empty>")
        return self._resolve_internal(path)
    
    def _resolve_internal(self, path: str) -> ResolutionResult:
        """Internal - assumes path is non-empty, may raise."""
        ...
```

### Why This Matters

- Public methods do validation, internal methods assume valid input
- Separating concerns makes code easier to test
- Internal methods can be optimized without changing public API

---

## 13. AST Identity Invariant (January 2026)

**STATUS: CANONICAL LAW — This is a schema law, not an optimization.**

### Core Principle

**ASTs are content-identity objects, not file-identity objects.**

An AST is uniquely identified by:
```
(content_hash, parser_version_id)
```

### Implications

| Rule | Explanation |
|------|-------------|
| Multiple files may share one AST | Two files with identical content reference the same AST row |
| File identity is NOT part of AST identity | `file_id` column in `asts` table is vestigial/historical |
| AST deduplication is intentional and required | This is by design, not a bug |

### Schema Constraint

The `asts` table MUST enforce:
```sql
UNIQUE(content_hash, parser_version_id)
```

### Worker Requirements

Workers MUST:
1. **Skip parsing** if an AST already exists for the same `content_hash`
2. **Resolve ASTs by `content_hash`** (not `file_id`)

```python
# ✅ CORRECT - check by content_hash
existing = conn.execute("""
    SELECT ast_id FROM asts 
    WHERE content_hash = ? AND parser_version_id = 1
""", (content_hash,)).fetchone()

if existing:
    return  # Reuse existing AST

# ❌ WRONG - assumes one AST per file
row = conn.execute("SELECT ast_blob FROM asts WHERE file_id = ?", (file_id,))
```

### Symbol/Reference Extraction

Extraction steps MUST:
- Accept ASTs not originally produced from the same `file_id`
- Look up AST by `content_hash`, not by `file_id`

### Vestigial `file_id` Column

The `file_id` column in `asts` records which file triggered the initial parse. It is:
- **Historical only** — not part of AST identity
- **NOT to be used for AST lookup**
- Harmless but could theoretically be removed

### Compatibility with Envelopes

This invariant is **compatible with the envelope model**:
- Envelopes decide **what steps must happen**
- Content identity decides **whether parsing work is necessary**

These are orthogonal concerns, not contradictory.

### Non-Negotiable

No component may assume:
```
file_id → exactly one AST
```

This invariant must be:
1. Documented here (canonical architecture)
2. Reflected in worker logic
3. Treated as non-negotiable in future refactors

---

## 14. Single-Writer DB Architecture (January 2026)

**STATUS: CANONICAL LAW — Database write authority**

### Core Principle

**Exactly one process may write to the ck3raven SQLite DB: the QBuilder Daemon.**

All MCP servers must open the DB in read-only mode (`mode=ro`).

### Implications

| Rule | Explanation |
|------|-------------|
| MCP servers are query-only | All SELECT, no INSERT/UPDATE/DELETE |
| Mutations go through IPC | MCP calls daemon via `daemon_client.py` |
| Daemon owns derived tables | ASTs, symbols, refs, diagnostics, conflicts |
| Writer lock prevents duplicates | OS-level lock at `{db_path}.writer.lock` |

### Why This Matters

Without single-writer architecture:
- Multiple VS Code windows cause "database locked" errors
- Build processes and MCP tools contend for write locks
- SQLite WAL mode helps reads but writes still serialize

With single-writer architecture:
- Multiple MCP servers can read concurrently (WAL mode)
- All writes go through one serialized daemon
- File mutations trigger IPC notification, not direct DB writes

### Canonical File Locations

| Component | Path |
|-----------|------|
| Full specification | `docs/SINGLE_WRITER_ARCHITECTURE.md` |
| Daemon IPC server | `qbuilder/ipc_server.py` |
| IPC client for MCP | `tools/ck3lens_mcp/ck3lens/daemon_client.py` |
| Writer lock | `qbuilder/writer_lock.py` |
| Read-only DB API | `tools/ck3lens_mcp/ck3lens/db_api.py` |

### MCP Tool Pattern

```python
# ✅ CORRECT - read-only DB, mutations via IPC
db = _get_db()  # Opens in mode=ro
result = db.query(...)  # SELECT only

# If file was changed, notify daemon
from ck3lens.daemon_client import daemon
daemon.notify_file_changed(mod_name, rel_path)

# ❌ WRONG - direct DB write from MCP
db.conn.execute("INSERT INTO symbols ...")
```

### Non-Negotiable

No MCP tool may:
1. Execute INSERT/UPDATE/DELETE on the database
2. Bypass the daemon for queue operations
3. Write to derived tables (symbols, refs, ASTs)

**See [SINGLE_WRITER_ARCHITECTURE.md](SINGLE_WRITER_ARCHITECTURE.md) for full specification.**

