# ck3_exec Keystone Migration — Final Execution Policy

> **Issued:** February 17, 2026 — Nate
> **Updated:** February 21, 2026 — Agent (directed by Nate)
> **Status:** Active (partially implemented — see §8)
> **Parent Directive:** Phase 2 Keystone Migration Directive
> **Tool:** ck3_exec

---

## 0) Classification

- `ck3_exec` is a **privileged break-glass execution tool** requiring explicit human authorization.
- It is **not sandboxed**.

---

## 1) Inline Execution Ban

The following are **prohibited**:

- `python -c`
- `python -m`
- Arbitrary shell strings
- Pipelines
- Multiple commands

**Only allowed execution form:**

```
python <script_path>
```

### Enforcement mechanism

The inline ban MUST be enforced via a **condition predicate + command whitelist** in the enforcement layer, NOT via validation logic in the tool handler.

**Rationale:** Tool handlers are forbidden from becoming parallel permission oracles. Enforcement shall handle this. The `enforce()` function in `enforcement_v2.py` is the single enforcement boundary — per Canonical Architecture Rule 1.

**Implementation design:**

1. A protected file `policy/command_whitelist.json` defines allowed command patterns (initially: `python <path>` only).
2. A condition factory `command_whitelisted()` returns a `Condition` that checks the shell command against the whitelist.
3. The condition is added to the `EXEC_COMMANDS` rule in `OPERATIONS_MATRIX`.
4. `enforce()` evaluates the condition like any other — True passes, False denies.

The tool handler passes the raw command string to `enforce()` via the context dict. It does NOT inspect or validate the command itself.

---

## 2) Script Location Restriction (Mandatory)

The script must:

- Resolve via WA2 with `require_exists=True`
- Be under: `root:ck3raven_data/wip/`

Any script outside this subtree:
→ **Invalid**
→ Do not execute

**No exceptions.**

### Enforcement mechanism

This is structural: the OPERATIONS_MATRIX only has ck3_exec entries at `("*", "ck3raven_data", "wip")`. Any other `(root_key, subdirectory)` tuple has no matching rule → `enforce()` returns DENY. No tool-handler logic needed.

### Current gap

The script path is not yet resolved via WA2 in the implementation. Only the working directory is resolved via WA2. The script path resolution must be added so that `enforce()` receives the correct `root_key` and `subdirectory` from the script's location, not the working directory's.

---

## 3) Approval Token (HMAC)

Execution requires a valid approval token binding:

- Canonical `session_abs` script path
- SHA256 script hash
- Session-bound expiration (existing system behavior)

Server must verify:

- HMAC valid
- Path matches
- Hash matches current contents
- Session valid

Any failure:
→ **Invalid**
→ Do not execute

### Implementation status

**Verifier exists:** `validate_script_signature()` in `contract_v1.py` checks the HMAC via Sigil. This is accessed through the `exec_signed()` condition predicate in `capability_matrix_v2.py`, which enforcement evaluates as part of the OPERATIONS_MATRIX rule for ck3_exec.

**Signer does NOT exist:** There is no `sign_script_for_contract()` function. The signing flow — where a human approves a script and the extension produces a signed token — has not been implemented.

### Signing mechanism (NOT HAT)

HAT (Human Authorization Token) is unsuitable for script execution approval. HAT is designed for initialization-type operations (e.g., protected file manifest edits during contract open). It is ephemeral and consumed once.

Script execution approval needs a **Sigil-based signing mechanism with a human trigger** — similar to Sigil's HMAC signing but requiring a human to explicitly click an approval button in the extension UI.

**Important:** This is a distinct mechanism from the HAT shield-click. Previous attempts to extend shield-click for other purposes caused crashes. The extension UI for script approval must be designed separately.

---

## 4) Working Directory

If provided:

- Must resolve via WA2
- Must be within canonical roots
- Must not escape

If omitted:

- Default to script's parent directory (derived via WA2)
- **Never** default silently to process cwd

---

## 5) Output Leak Protection

Before returning reply:

- Leak-scan stdout/stderr
- Block if host paths detected

### Implementation status

Not yet wired up. The leak scanning logic must be added to `_ck3_exec_internal` before returning stdout/stderr contents in the Reply.

---

## 6) Explicit Non-Goals

We are **NOT** implementing:

- Filesystem syscall interception
- CPython audit hooks
- I/O API enforcement
- Sandboxing
- AST script inspection

This remains a privileged tool requiring human oversight.

---

## 7) Return Type

`_ck3_exec_internal` must return `Reply` consistently.

### Current gap

The implementation currently returns a mixed `Reply | dict` type. Some paths return `Reply` objects (via enforcement denials), while execution success paths return raw dicts. This must be normalized to `Reply` throughout.

---

## 8) Implementation Status

| Requirement | Status | Notes |
|-------------|--------|-------|
| §1 Inline ban | **NOT IMPLEMENTED** | No condition predicate, no command whitelist. Currently allows arbitrary shell commands. |
| §2 Script location | **PARTIALLY** | OPERATIONS_MATRIX gating exists. Script path not yet resolved via WA2 (only working_dir is). |
| §3 HMAC verifier | **EXISTS** | `validate_script_signature()` in contract_v1.py, surfaced via `exec_signed()` condition |
| §3 HMAC signer | **NOT IMPLEMENTED** | No signing function, no extension UI for approval |
| §4 Working directory | **IMPLEMENTED** | Resolved via WA2 |
| §5 Leak scanning | **NOT IMPLEMENTED** | Stdout/stderr returned without scanning |
| §7 Return type | **PARTIALLY** | Mixed Reply\|dict — needs normalization |

### What IS working

- WA2 resolution for working directory
- `enforce()` integration (v2 enforcement)
- OPERATIONS_MATRIX gating to `("*", "ck3raven_data", "wip")`
- `exec_signed()` condition predicate (verifier side)

---

## Strategic Note

This provides:

- Addressing governance (WA2)
- Execution location restriction (OPERATIONS_MATRIX)
- Human approval binding (HMAC — verifier only, signer pending)
- Leak protection (pending)

This is strong for an interim break-glass model. It is not security sandboxing. But it is **honest governance**.
