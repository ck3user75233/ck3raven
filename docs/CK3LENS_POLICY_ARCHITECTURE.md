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
3. **`live_mods` / `local_mods`**: These terms trigger hallucinations of parallel lists. Do not use them. Refer to `ROOT_USER_DOCS`.

---

## 8. Implementation Checklist

* [ ] Ensure `ck3_file` calls `enforce_policy` for all mutations.
* [ ] Verify `WorldAdapter` correctly assigns `ROOT_USER_DOCS` vs `ROOT_STEAM` based on path containment.
* [ ] Remove any logic that filters `mods[]` into a separate "writable" list.
* [ ] Ensure `ROOT_REPO` source files return `DENY` for writes in this mode.
