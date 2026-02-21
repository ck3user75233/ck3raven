# Outstanding Tasks — Post-Document Sync

> **Date:** February 21, 2026
> **Context:** Identified during document review and codebase audit

---

## Priority 1: ck3_exec Completion

### 1.1 Inline ban condition predicate
- Create `policy/command_whitelist.json` (protected file)
- Implement `command_whitelisted()` condition factory in `capability_matrix_v2.py`
- Add condition to EXEC_COMMANDS rule in OPERATIONS_MATRIX
- Tool handler must NOT inspect commands — enforcement only

### 1.2 Script path resolution via WA2
- Currently only working_dir is resolved via WA2
- Script path must also resolve via WA2 so enforce() gets correct root_key/subdirectory
- Without this, §2 location restriction relies on OPERATIONS_MATRIX but enforcement receives working_dir's coordinates, not the script's

### 1.3 HMAC signer for script approval
- `validate_script_signature()` (verifier) exists in contract_v1.py
- No `sign_script_for_contract()` (signer) exists
- Needs extension UI: Sigil-based signing with human button click
- NOT HAT — HAT is for initialization operations, and extending shield-click caused crashes

### 1.4 Leak scanning on output
- Stdout/stderr returned without scanning
- Must scan for host paths before including in Reply

### 1.5 Return type normalization
- Mixed Reply|dict in `_ck3_exec_internal`
- Normalize all code paths to return Reply

---

## Priority 2: Enforcement Improvements

### 2.1 Area-specific denial codes
- Current: `EN-GATE-D-001` used uniformly for all denials
- Required: Area-specific codes (e.g., `EN-EXEC-D-001`, `EN-WRITE-D-002`)
- Branching should be on reply code, not data dict inspection
- Messages belong in ReplyBuilder registry
- Do AFTER ck3_exec migration is complete

---

## Priority 3: Tool Migration to v2

### 3.1 Migrate ck3_file to WA2 + enforcement_v2
- unified_tools.py still uses v1 enforcement.py and v1 world_adapter.py
- v1 WA only recognizes `mod:` and `ck3raven:/` schemes
- After migration: `root:repo/`, `root:game/`, `mod:Name/` all work uniformly

### 3.2 Migrate ck3_git to WA2 + enforcement_v2
- Same situation as ck3_file

### 3.3 Remove v1 enforcement modules
- Only after ALL tools migrated to v2
- Remove: enforcement.py (v1), world_adapter.py (v1)
- Audit for any remaining v1 imports

---

## Priority 4: Extension UI

### 4.1 Script approval UI
- Distinct from HAT shield-click
- Human clicks button → extension produces Sigil-signed token
- Must not reuse shield-click mechanism (caused crashes)
- Design separately, test carefully

---

## Notes

- Contract v1 `open_contract()` validates root_category but NOT subdirectory. Defense-in-depth relies on OPERATIONS_MATRIX denying operations outside allowed subdirectories at enforcement time.
- `EXEC_COMMANDS` is an empty frozenset used as identity sentinel — `find_operation_rule()` special-cases `tool == "ck3_exec"` via `rule.commands is EXEC_COMMANDS`.
- WA2 is mode-agnostic: reads mode dynamically via `get_agent_mode()`. No cache clearing needed on mode change.
