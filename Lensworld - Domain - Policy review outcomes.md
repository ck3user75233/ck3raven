You are absolutely right, and you are not overreacting.

In fact, you have identified the exact mechanism of **Context Poisoning**: using terminology (`LOCAL_MOD`) that is semantically adjacent to a banned concept (`local_mods[]` list) confuses the LLM. It starts treating the *domain classification* as if it were the *banned list*, eventually hallucinating the list back into existence.

Your observation about "MSC" is also spot on—that is a classic hallucination artifact from prior contexts that I failed to scrub, proving your point that "approximate" terminology leaks context.

### The Fix: Physical Geography vs. Semantic Categories

To kill the parallel lists idea forever, we must stop naming things by "what they are" (Local Mod) and name them by "where they physically live" (Root Path).

We will switch to **Geographical Domains**:

1. `LOCAL_MOD` -> **`ROOT_USER_DOCS`** (It's just a file in the Documents folder)
2. `WORKSHOP` -> **`ROOT_STEAM`** (It's just a file in the Steam folder)
3. `VANILLA` -> **`ROOT_GAME`** (It's just a file in the Game folder)

This forces the agent to rely on **Path Containment Logic** (Is this path inside the user's documents folder?) rather than "List Logic" (Is this mod in the 'Local Mods' list?).

Here are the completely redrafted, sanitized documents.

---

### 1. Replacement for `LENSWORLD.md` (Sanitized)

{
type: uploaded file
fileName: LENSWORLD.md
fullContent:

# LensWorld Architecture

> **Status:** CANONICAL
> **Last Updated:** January 5, 2026
> **Scope:** Visibility layer (Resolution & Identity)
> **Compliance:** Strict alignment with `CANONICAL_ARCHITECTURE.md`

---

## 1. What LensWorld Is

**LensWorld is a structural resolution layer.** It answers:

1. "Does this path exist in the current context?"
2. "What is its canonical address?"
3. "Which physical filesystem root contains it?"

LensWorld creates the **Database-Projected View** of the file system. If `WorldAdapter` cannot resolve a path, that path effectively **does not exist** for the agent.

---

## 2. What LensWorld Is Not (CRITICAL)

LensWorld is **NOT** a permission system.

* It **NEVER** answers "Can I write this?"
* It **NEVER** returns `is_writable` or `is_allowed`.
* It **NEVER** categorizes mods into "writable" or "read-only" buckets.

**The output of LensWorld is Identity (`CanonicalAddress`) and Geography (`RootCategory`), not Permission.**

---

## 3. The Single Adapter Architecture

There is exactly **ONE** `WorldAdapter` class. It changes behavior based on `session.mode`.

**Forbidden Patterns (Do Not Use):**

* `LensWorldAdapter` (Banned class)
* `DevWorldAdapter` (Banned class)
* `get_world(mode=...)` (Mode is intrinsic to Session)

### Mode-Aware Resolution

The `WorldAdapter` inspects `session.mode` to determine visibility rules:

| Mode | Visibility Scope | Address Style |
| --- | --- | --- |
| **ck3lens** | Active Playset (Vanilla + Enabled Mods in `mods[]`) | `mod_name` + `rel_path` |
| **ck3raven-dev** | CK3Raven Source + WIP + Raw Reads | Raw `path` |

---

## 4. Resolution Flow

### 4.1 Input

Users or Tools provide a string: `common/traits/00_traits.txt` or `mod:MyMod/descriptor.mod`.

### 4.2 The Process

1. `WorldAdapter.resolve(path)` is called.
2. Adapter normalizes the path based on `session.mode`.
3. Adapter checks existence in the DB (ck3lens) or FS (ck3raven-dev).

### 4.3 Output (`ResolutionResult`)

The *only* data returned for logic flow:

```python
@dataclass
class ResolutionResult:
    found: bool                  # Does it exist?
    address: CanonicalAddress    # The sole Identity
    absolute_path: Path          # For execution ONLY
    
    # GEOGRAPHY ONLY - NO SEMANTIC MEANING
    root_category: str           # ROOT_USER_DOCS, ROOT_STEAM, ROOT_GAME, ROOT_REPO
    
    # DISPLAY ONLY - NEVER USE FOR LOGIC
    ui_hint_potentially_editable: bool 

```

---

## 5. Canonical Geography (Root Categories)

We do not classify files by "Type" (e.g., Local Mod). We classify them by "Location" (e.g., User Documents).

| Root Category | Physical Location |
| --- | --- |
| `ROOT_USER_DOCS` | `Documents/Paradox Interactive/Crusader Kings III/mod/` |
| `ROOT_STEAM` | `steamapps/workshop/content/...` |
| `ROOT_GAME` | `steamapps/common/Crusader Kings III/` |
| `ROOT_REPO` | The `ck3raven` repository root |
| `ROOT_WIP` | `~/.ck3raven/wip/` |
| `ROOT_LAUNCHER` | Paradox Launcher data directory |

### Raw Path Handling

Agents may provide raw paths. `WorldAdapter` immediately translates them to `CanonicalAddress`. If translation fails (e.g., path is outside the lens), resolution fails (`found=False`).

---

## 6. Usage in MCP Tools (The Canonical Pattern)

This is the **only** allowed pattern for using LensWorld.

```python
from ck3lens.world_router import get_world
from ck3lens.policy.enforcement import enforce_policy, EnforcementRequest

def ck3_example_tool(path: str, content: str = None):
    # 1. GET WORLD (Identity)
    world = get_world() 
    
    # 2. RESOLVE (Structure)
    # Returns ResolutionResult. Does NOT check permission.
    result = world.resolve(path)
    
    if not result.found:
        return {"error": "Path not found in current lens"}
        
    # 3. ENFORCE (Policy) - IF writing
    # This is the ONLY place permissions are checked.
    if content is not None:
        policy_result = enforce_policy(EnforcementRequest(
            operation="file_write",
            mode=world.session.mode,
            target=result.address,
            root_category=result.root_category # Pass Geography
        ))
        
        if policy_result.decision != "ALLOW":
            return {"error": policy_result.reason}

    # 4. EXECUTE (Filesystem)
    # Use the absolute_path resolved in step 2
    if content:
        result.absolute_path.write_text(content)

```

---

## 7. Anti-Patterns (BANNED)

| Banned Concept | Why? | Correct Replacement |
| --- | --- | --- |
| `is_writable` | Oracle pattern | `enforce_policy()` |
| `local_mods` (list) | Parallel truth | `mods[]` + `ROOT_USER_DOCS` check |
| `live_mods` | Parallel truth | `mods[]` + `ROOT_USER_DOCS` check |
| `LOCAL_MOD` (Enum) | Implies subset list | `ROOT_USER_DOCS` |
| `WORKSHOP` (Enum) | Implies type | `ROOT_STEAM` |

---

## 8. Implementation Files

| Responsibility | File |
| --- | --- |
| Interface & Logic | `tools/ck3lens_mcp/ck3lens/world_adapter.py` |
| Factory | `tools/ck3lens_mcp/ck3lens/world_router.py` |
| Addresses | `tools/ck3lens_mcp/ck3lens/address.py` |

**There are no other valid files for visibility logic.**
}

### 2. Replacement for `CK3LENS_POLICY_ARCHITECTURE.md` (Sanitized)

{
type: uploaded file
fileName: CK3LENS_POLICY_ARCHITECTURE.md
fullContent:

# CK3LENS Policy Architecture

> **Status:** CANONICAL
> **Scope:** ck3lens agent mode ONLY
> **Last Updated:** January 5, 2026
> **Enforcement Implementation:** `ck3lens/policy/enforcement.py`

---

## 1. The Policy Boundary

Policy is applied **AFTER** resolution and **BEFORE** execution.

1. **Resolution (`WorldAdapter`):** Identifies *where* the target is (e.g., "This path maps to `ROOT_STEAM`").
2. **Enforcement (`enforcement.py`):** Decides if the action is allowed (e.g., "Writes to `ROOT_STEAM` are DENIED").

There is **ONE** enforcement entry point: `enforce_policy()`.

---

## 2. Geography & Permissions

Permissions are determined by the **Root Category** (Physical Location) derived during resolution.

| Root Category | Source | Read | Write | Delete |
| --- | --- | --- | --- | --- |
| **ROOT_USER_DOCS** | `Documents/...` | ✅ | ✅ (Contract) | 🔶 (Token) |
| **ROOT_STEAM** | `steamapps/workshop/...` | ✅ | ❌ DENY | ❌ DENY |
| **ROOT_GAME** | `steamapps/common/...` | ✅ | ❌ DENY | ❌ DENY |
| **ROOT_WIP** | `~/.ck3raven/wip/` | ✅ | ✅ | ✅ |
| **ROOT_REPO** | `ck3raven` source | ✅ (Debug) | ❌ DENY | ❌ DENY |
| **ROOT_LAUNCHER** | `launcher-v2.sqlite` | ✅ | 🔶 (Token) | 🔶 (Token) |

### Key Invariant: The "Path Containment" Rule

There is no "writable mods list".
There is only **`session.mods[]`** and **Physical Geography**.

* If a mod is in `mods[]` AND its path resolves to `ROOT_USER_DOCS` -> Writable.
* If a mod is in `mods[]` AND its path resolves to `ROOT_STEAM` -> Read-Only.

We do not label the mod itself. We label the *storage medium*.

---

## 3. Enforcement Logic (`enforce_policy`)

The `enforce_policy` function evaluates the `EnforcementRequest` and returns a `PolicyResult`.

### Inputs

* `operation`: `FILE_WRITE`, `FILE_DELETE`, `REGISTRY_REPAIR`
* `target`: `CanonicalAddress` (resolved by WorldAdapter)
* `root_category`: `ROOT_USER_DOCS`, `ROOT_STEAM`, etc.
* `contract`: (Optional) Active contract ID

### Outputs (Decision)

* `ALLOW`: Proceed.
* `DENY`: Stop. Raise error.
* `REQUIRE_TOKEN`: Stop. Request specific token from user.

### Logic Flow (Pseudo-code)

```python
def enforce_ck3lens_write(target, root_category):
    if root_category == ROOT_WIP:
        return ALLOW
        
    if root_category == ROOT_STEAM or root_category == ROOT_GAME:
        return DENY("Cannot modify content in controlled storage (Steam/Game)")
        
    if root_category == ROOT_REPO:
        return DENY("ck3lens cannot modify infrastructure")
        
    if root_category == ROOT_USER_DOCS:
        # It's in the user's documents folder, so it is physically editable.
        # Now we check if we have a contract to do so.
        if has_active_contract(target):
            return ALLOW
        return DENY("Write to user mod folder requires active contract")
        
    return DENY("Unknown root category")

```

---

## 4. Contracts (The Write Gate)

Writes to `ROOT_USER_DOCS` require an **Active Contract**.

### Required Intent Types

* `COMPATCH`
* `BUGPATCH`

### Contract Validation

Contracts are validated by `enforcement.py` at the time of the write request.

* The target file must match the contract's `target_files` list or glob.
* If no contract exists, `enforce_policy` returns `DENY`.

---

## 5. Token Tiers

Tokens are required for destructive or high-risk operations. `enforce_policy` returns `REQUIRE_TOKEN` for these cases.

| Action | Token Required |
| --- | --- |
| Delete file in `ROOT_USER_DOCS` | `DELETE_USER_MOD_FILE` |
| Repair Launcher DB | `REGISTRY_REPAIR` |
| Delete Launcher Cache | `CACHE_DELETE` |
| Execute WIP Script | `SCRIPT_EXECUTE` |

---

## 6. CK3Lens WIP Workspace

**Location:** `ROOT_WIP` (maps to `~/.ck3raven/wip/`)

* **Role:** Scratchpad for scripts and analysis.
* **Policy:** strictly open. ck3lens can write/delete here freely.
* **Restriction:** Scripts in WIP cannot be executed without `SCRIPT_EXECUTE` token validation (syntax check + hash binding).

---

## 7. Banned Mechanisms

1. **`hard_gates.py`**: This file is deprecated. Logic moved to `enforcement.py`.
2. **`is_writable` checks**: Tools must not check if a path is writable. They must attempt to write and let `enforce_policy` decide.
3. **`live_mods` / `local_mods**`: These terms trigger hallucinations of parallel lists. Do not use them. Refer to `ROOT_USER_DOCS`.

---

## 8. Implementation Checklist

* [ ] Ensure `ck3_file` calls `enforce_policy` for all mutations.
* [ ] Verify `WorldAdapter` correctly assigns `ROOT_USER_DOCS` vs `ROOT_STEAM` based on path containment.
* [ ] Remove any logic that filters `mods[]` into a separate "writable" list.
* [ ] Ensure `ROOT_REPO` source files return `DENY` for writes in this mode.
}

### 3. Replacement for `CK3RAVEN_DEV_POLICY_ARCHITECTURE.md` (Sanitized)

{
type: uploaded file
fileName: CK3RAVEN_DEV_POLICY_ARCHITECTURE.md
fullContent:

# CK3RAVEN-DEV Policy Architecture

> **Status:** CANONICAL
> **Scope:** ck3raven-dev agent mode ONLY
> **Last Updated:** January 5, 2026
> **Enforcement Implementation:** `ck3lens/policy/enforcement.py`

---

## 1. Purpose & Boundary

**ck3raven-dev** maintains the infrastructure.

* **Can Modify:** `ROOT_REPO` (ck3raven source code, tools, tests).
* **Cannot Modify:** ANY game content (`ROOT_USER_DOCS`, `ROOT_STEAM`, `ROOT_GAME`).

### The Inviolable Rule

`enforcement.py` will **unconditionally DENY** any write operation where:
`root_category` is `ROOT_USER_DOCS`, `ROOT_STEAM`, or `ROOT_GAME`.

There are no tokens to bypass this. To edit mods, you must switch to `ck3lens` mode.

---

## 2. Resolution in Dev Mode

Even in dev mode, we use `WorldAdapter`.

1. **Input:** `src/ck3raven/server.py`
2. **Resolution:** `WorldAdapter` sees `session.mode == ck3raven-dev`.
3. **Identity:** It resolves this to `CanonicalAddress(domain=CK3RAVEN, path=...)` and `root_category=ROOT_REPO`.
4. **Enforcement:** `enforce_policy` checks if writes are allowed to `ROOT_REPO`.

### Addressing Difference

* **ck3lens:** Uses `mod:Name/path`
* **ck3raven-dev:** Uses raw paths relative to repo root (`src/...`).

---

## 3. Policy Matrix (`enforce_policy`)

| Root Category | Read | Write | Delete |
| --- | --- | --- | --- |
| **ROOT_REPO** | ✅ | ✅ (Contract) | 🔶 (Token) |
| **ROOT_WIP** | ✅ | ✅ | ✅ |
| **ROOT_USER_DOCS** | ✅ (Reference) | ❌ **HARD DENY** | ❌ **HARD DENY** |
| **ROOT_STEAM** | ✅ (Reference) | ❌ **HARD DENY** | ❌ **HARD DENY** |
| **ROOT_GAME** | ✅ (Reference) | ❌ **HARD DENY** | ❌ **HARD DENY** |

---

## 4. Contracts (Infrastructure)

Writes to `ROOT_REPO` require a **Contract**.

### Intent Types

* `BUGFIX`
* `REFACTOR`
* `FEATURE`
* `MIGRATION`

### Target Resolution

Contracts in Dev Mode must specify `target_files` (e.g., `src/ck3raven/parser.py`).
`enforce_policy` validates that the operation target matches the contract.

---

## 5. Token System

Operations on Infrastructure that require explicit approval tokens (returned by `enforce_policy` as `REQUIRE_TOKEN`):

* `DELETE_INFRA`: Deleting source files in `ROOT_REPO`.
* `GIT_FORCE_PUSH`: Modifying remote history.
* `GIT_REWRITE_HISTORY`: Rebase/Amend.
* `DB_MIGRATION_DESTRUCTIVE`: Dropping/Altering tables.

---

## 6. Execution (`ck3_exec`)

* **Terminal Access:** `run_in_terminal` is **DENIED** by policy.
* **Allowed Execution:** All execution must occur via `ck3_exec` tool.
* **Scope:** `ck3_exec` is restricted to the repository root and WIP directory.

---

## 7. Banned Concepts

* **`hard_gates.py`**: Banned. Logic is in `enforcement.py`.
* **Mod Writes**: Any attempt to write to a mod path in this mode is an architectural violation, not just a permission error.

---

## 8. Implementation Checklist

* [ ] Ensure `WorldAdapter` in dev mode resolves raw paths correctly to `ROOT_REPO` category.
* [ ] Verify `enforcement.py` contains the block that auto-denies `ROOT_USER_DOCS` when mode is `ck3raven-dev`.
* [ ] Ensure `ck3_exec` validates commands against the Allowlist (Git, Pytest, Python).
}