# Protected Files & HAT — Implementation Plan

> **Status:** PENDING REVIEW  
> **Depends On:** [PROTECTED_FILES_AND_HAT.md](PROTECTED_FILES_AND_HAT.md) (architecture doc)  
> **Estimated Phases:** 4 sequential phases  
> **Rule:** No code until this plan is approved.

---

## Phase 1: Deprecated Code Cleanup

**Goal:** Remove all `token_id='confirm'` and `REQUIRE_TOKEN` references. This is prerequisite housekeeping — the old system must be gone before HAT is built.

### 1.1 `enforcement.py` (3 edits)

| Edit | File | What |
|------|------|------|
| 1a | `enforcement.py` line 12 | Docstring: change `"DELETE: deletion with token confirmation"` → `"DELETE: deletion (requires contract)"` |
| 1b | `enforcement.py` line 32 | Remove `REQUIRE_TOKEN = auto()` from `Decision` enum |
| 1c | `enforcement.py` line 43 | Docstring: change `"DELETE = deletion (requires token)"` → `"DELETE = deletion (requires contract)"` |

**Ripple check:** grep for any code that references `Decision.REQUIRE_TOKEN` and update/remove.

### 1.2 `unified_tools.py` (1 edit)

| Edit | File | What |
|------|------|------|
| 1d | `unified_tools.py` ~line 1600-1620 | In `_file_delete_raw`: remove `token_id` parameter check. Function should rely on enforcement (contract required), not a separate token gate. |

### 1.3 `server.py` (1 edit)

| Edit | File | What |
|------|------|------|
| 1e | `server.py` ~lines 4420-4440 | In `ck3_token` tool docstring: remove all `token_id='confirm'` references. Update to mention HAT replaces legacy tokens. |

### 1.4 Verification

- `grep -rn "token_id.*confirm\|REQUIRE_TOKEN" tools/` should return zero hits (excluding exports/archive)
- All existing tests pass
- `ck3_file(command="delete")` still works (enforced by contract, not token)

---

## Phase 2: HAT Token Infrastructure

**Goal:** Build the HAT token type, validation, and storage. No integration yet — just the plumbing.

### 2.1 `tokens.py` additions

| Edit | What |
|------|------|
| 2a | Add `HAT = "HAT"` to `TokenType` enum |
| 2b | Add `HATScope` enum: `MODE_INIT`, `PROTECTED_FILE_WRITE`, `PROTECTED_FILE_MANAGE` |
| 2c | Add `HATToken` dataclass (hat_id, scope, created_at, signature, target_paths, consumed) |
| 2d | Add `generate_hat(scope, target_paths) -> HATToken` — creates HMAC-signed token, writes to `~/.ck3raven/config/hat_pending.json` |
| 2e | Add `validate_hat(hat_id, expected_scope, expected_paths) -> tuple[bool, str]` — loads pending token, verifies HMAC + scope + paths, marks consumed |

### 2.2 Secret key management

| Edit | What |
|------|------|
| 2f | Add `_get_or_create_hat_secret() -> bytes` — reads `~/.ck3raven/config/hat_secret.key`, creates if missing (32 random bytes) |

### 2.3 Verification

- Unit test: generate HAT → validate HAT → consumed (returns false on reuse)
- Unit test: tampered signature → rejected
- Unit test: wrong scope → rejected

---

## Phase 3: Protected Files Manifest & Contract Gate

**Goal:** Create the manifest, integrate HAT check into contract open, build startup verification.

### 3.1 New module: `tools/compliance/protected_files.py`

| Function | Purpose |
|----------|---------|
| `load_manifest() -> dict` | Load `policy/protected_files.json`, return parsed entries |
| `save_manifest(manifest: dict)` | Write manifest back to disk |
| `is_protected(rel_path: str, manifest: dict) -> bool` | Check path against file entries (exact) and folder entries (prefix) |
| `compute_file_hash(abs_path: str) -> str` | SHA256 of file content |
| `verify_all_hashes(manifest: dict, repo_root: str) -> list[dict]` | Check all file entries, return mismatches |
| `check_edits_against_manifest(edits: list[dict], manifest: dict) -> list[str]` | Return list of protected paths from edits |

### 3.2 Contract gate integration (`contract_v1.py`)

| Edit | What |
|------|------|
| 3a | Modify `open_contract()` — before creating ContractV1, call `check_edits_against_manifest()` |
| 3b | If protected paths found and no `hat_id` param → raise ValueError with descriptive message |
| 3c | If `hat_id` provided → call `validate_hat(hat_id, "protected_file_write", protected_paths)` |
| 3d | Add `hat_id: Optional[str] = None` parameter to `open_contract()` |

### 3.3 Mode init integration

**Deferred.** MIT continues to handle mode initialization unchanged. The `HATScope.MODE_INIT` value exists in the enum for future use. Swapping MIT → HAT for init is a separate, trivial task.

### 3.4 Startup hash verification

| Edit | What |
|------|------|
| 3g | In mode initialization: after loading manifest, call `verify_all_hashes()` |
| 3h | Log mismatches as warnings (not errors, not blocks) |

### 3.5 Create initial manifest

| Edit | What |
|------|------|
| 3i | Create `policy/protected_files.json` with the 3 instruction files, compute real SHA256 hashes |

### 3.6 Manifest self-protection

| Edit | What |
|------|------|
| 3j | In `open_contract()` gate: always add `"policy/protected_files.json"` to the protected check, regardless of manifest contents |

### 3.7 Verification

- Integration test: contract open with protected file edit + no HAT → rejected
- Integration test: contract open with protected file edit + valid HAT → succeeds
- Integration test: contract open with non-protected file edit → normal (no HAT needed)
- Manifest self-protection: contract editing manifest without HAT → rejected

---

## Phase 4: `ck3_protect` Tool & Git Hook

**Goal:** Expose manifest management to agents (with HAT) and install git safety net.

### 4.1 New MCP tool: `ck3_protect`

| Edit | What |
|------|------|
| 4a | Register tool in `server.py` with commands: list, verify, add, remove |
| 4b | `list` — calls `load_manifest()`, returns entries |
| 4c | `verify` — calls `verify_all_hashes()`, returns mismatches |
| 4d | `add` — validates HAT(scope=`protected_file_manage`), adds entry, saves manifest |
| 4e | `remove` — validates HAT(scope=`protected_file_manage`), removes entry, saves manifest |

### 4.2 Git pre-commit hook

| Edit | What |
|------|------|
| 4f | Add `check-staged` CLI command to `tools/compliance/protected_files.py` |
| 4g | Script: loads manifest, checks `git diff --cached --name-only`, looks for `HAT-AUTHORIZED:` in commit message |
| 4h | Create hook installer script (not the hook itself — hooks aren't in git) |

### 4.3 Extension UI (deferred)

Extension sidebar "Authorize" button for HAT generation is a separate task. For initial deployment, HATs can be generated via CLI or test helper. Extension integration follows in a separate PR.

### 4.4 Verification

- `ck3_protect(command="list")` returns 3 entries
- `ck3_protect(command="verify")` shows all hashes match
- `ck3_protect(command="add", ...)` without HAT → rejected
- Pre-commit hook blocks protected file commit without marker

---

## Dependency Graph

```
Phase 1 (cleanup) ──→ Phase 2 (HAT infra) ──→ Phase 3 (manifest + gate) ──→ Phase 4 (tool + hook)
                                                      │
                                                      └─── Initial manifest created here
```

Phases are strictly sequential. Each phase is independently committable.

---

## Files Modified/Created Summary

| Phase | File | Action |
|-------|------|--------|
| 1 | `policy/enforcement.py` | Edit (remove REQUIRE_TOKEN, update docstrings) |
| 1 | `ck3lens/unified_tools.py` | Edit (remove token_id check in delete) |
| 1 | `server.py` | Edit (update ck3_token docstring) |
| 2 | `tools/compliance/tokens.py` | Edit (add HAT type, HATScope, validation — MIT untouched) |
| 3 | `tools/compliance/protected_files.py` | **Create** (manifest operations) |
| 3 | `policy/protected_files.json` | **Create** (initial manifest with 3 files) |
| 3 | `policy/contract_v1.py` | Edit (HAT gate in open_contract) |
| 4 | `server.py` | Edit (register ck3_protect tool) |
| 4 | `tools/compliance/protected_files.py` | Edit (add check-staged CLI) |

---

## Out of Scope

- Extension UI for HAT generation (separate task)
- OS read-only file attributes (optional, not in v1)
- Protecting additional files beyond the 3 instruction docs
- Modifying Contract v1 schema (no changes needed)
- WIP workspace (excluded from protection)
