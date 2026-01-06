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
