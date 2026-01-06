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
