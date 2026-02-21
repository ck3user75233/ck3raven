# ck3_exec Keystone Migration — Final Execution Policy

> **Issued:** February 17, 2026 — Nate
> **Updated:** February 22, 2026 — Agent (directed by Nate)
> **Status:** Active (partially implemented — see §12)
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

**Signer exists in Python:** `sign_script_for_contract()` in `contract_v1.py` produces valid HMAC signatures. 22 unit tests pass covering round-trip, tamper detection, cross-contract forgery, etc. However, **nothing calls it** — there is no human trigger.

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

**DEFERRED.** While the overall canonical addressing refactor is only a small percentage complete, agents see host paths from many other tools anyway. Leak-scanning ck3_exec output in isolation creates a false sense of coverage. Revisit when ck3_file and ck3_git are migrated to WA2.

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

## 8) Implementation Status (Original)

> Superseded by §12. Retained for history.

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
- Leak protection (deferred)

This is strong for an interim break-glass model. It is not security sandboxing. But it is **honest governance**.

---

## 9) Detailed Gap Assessment (February 22, 2026)

> Agent: Gap analysis performed by reading implementation code (server.py, capability_matrix_v2.py, contract_v1.py, enforcement_v2.py) against §1–§8 requirements.

### 9.1 What IS implemented and working

| Component | Location | Status |
|-----------|----------|--------|
| WA2 resolution for working_dir | `server.py` L4075–4085 | **DONE** — defaults to `root:ck3raven_data/wip` |
| `enforce()` v2 integration | `server.py` L4115–4123 | **DONE** — calls enforce with mode, tool, root_key, subdirectory, context kwargs |
| OPERATIONS_MATRIX gating | `capability_matrix_v2.py` L519–523 | **DONE** — `EXEC_COMMANDS` at `("*", "ck3raven_data", "wip")` only, with `_EXEC_GATE` condition |
| `exec_gate()` condition predicate | `capability_matrix_v2.py` L142–197 | **DONE** — 3-branch: whitelist → script signing → deny |
| `_is_command_whitelisted()` | `capability_matrix_v2.py` L252–261 | **DONE** — prefix matching, cached |
| `_load_command_whitelist()` | `capability_matrix_v2.py` L215–250 | **DONE** — reads `policy/command_whitelist.json` |
| `policy/command_whitelist.json` | `policy/command_whitelist.json` | **EXISTS** — but `"commands": []` (empty) |
| `sign_script_for_contract()` | `contract_v1.py` L506–552 | **EXISTS** — HMAC signing, stores on contract |
| `validate_script_signature()` | `contract_v1.py` L556–598 | **EXISTS** — HMAC verification |
| `_detect_script_path()` | `server.py` L4009–4041 | **DONE** — extracts script from `python <path>` |

### 9.2 What is NOT working / NOT hooked up

#### §1 Inline ban — HALF-DONE

Whitelist machinery exists but `commands: []` is empty. `_is_command_whitelisted()` always returns `false`. The policy doc says "only `python <path>` is allowed", but no patterns are in the file.

**Practical effect:** The empty whitelist combined with `exec_gate` branch 3 means non-script, non-whitelisted commands are denied. This is **correct by accident** — the inline ban is effectively enforced because nothing is whitelisted and the script signing path is also broken (see §3 below).

**Fix:** Populate `policy/command_whitelist.json` per §10 recommendations below.

#### §2 Script path resolution via WA2 — NOT DONE

Only `working_dir` is resolved via WA2 (`server.py` L4075–4085). The script path extracted by `_detect_script_path` is a raw host-absolute path. It is passed to `enforce()` via the `script_host_path` context kwarg but never goes through `wa2.resolve()`.

**Consequence:** Enforcement receives the working_dir's `root_key`/`subdirectory`, not the script's. If the working dir is `wip` but the script is elsewhere (e.g., `python /some/other/path.py` while cwd is wip), enforcement would wrongly allow it.

**Fix:** After `_detect_script_path`, resolve the detected script path through `wa2.resolve()` to get the script's own coordinates.

#### §3 HMAC signer — EXISTS in Python, NO human trigger

`sign_script_for_contract()` exists and works — 22 unit tests pass. But **nothing calls it**:

- No extension UI button exists for script approval
- No MCP tool exposes a signing endpoint
- No TypeScript code references script signing

**Consequence:** `contract.script_signature` is always `None` → `validate_script_signature()` always returns `False` → Branch 2 of `exec_gate` always fails → **script execution is impossible.**

The signing mechanism was designed to require a human trigger (Sigil-based, NOT HAT shield-click — per §3 of this document). The Python-side signer/verifier pair is complete and tested, but the human entry point was never built.

**Fix:** This is a Priority 4 item (extension UI). See §11 for interim approach.

#### §5 Leak scanning — DEFERRED

Stdout/stderr are returned without `check_no_host_paths()`. The leak detector exists (`leak_detector.py`) and is wired into `ck3_dir`, but not `ck3_exec`.

**Demotion rationale:** While the overall canonical addressing refactor is only a small percentage complete, agents see host paths from many other tools anyway. Leak-scanning ck3_exec output in isolation creates a false sense of coverage. This item is deferred until the broader tool migration (ck3_file, ck3_git) brings leak scanning to a meaningful percentage of MCP output surface.

#### §7 Return type — NOT DONE

`_ck3_exec_internal` signature is `Reply | dict` (`server.py` L4052). Success/timeout/error paths return raw dicts. The wrapper `ck3_exec()` converts some to `Reply` (`server.py` L3948–3980) but it's case-by-case and fragile.

**Fix:** Normalize all code paths in `_ck3_exec_internal` to return `Reply`.

---

## 10) Command Whitelist Recommendations

> Direction from Nate: "I want the git commands, the qbuilder, the linters and if there are any other regular processes that are part of our operational work and executed with in-line python."

### 10.1 Proposed whitelist entries

```json
{
  "schema_version": "1",
  "description": "Commands whitelisted for ck3_exec without script signing. HAT-protected.",
  "commands": [
    "git status",
    "git diff",
    "git log",
    "git add",
    "git commit",
    "git push",
    "git pull",
    "git branch",
    "git checkout",
    "git stash",
    "git rev-parse",
    "git show",
    "git remote",
    "python -m pytest",
    "python -m tools.compliance.run_arch_lint_locked",
    "python -m tools.arch_lint",
    "python builder/daemon.py",
    "python --version",
    "pip list",
    "pip show"
  ]
}
```

### 10.2 Rationale by category

| Category | Commands | Why |
|----------|----------|-----|
| **Git** | `git status`, `git diff`, `git log`, `git add`, `git commit`, `git push`, `git pull`, `git branch`, `git checkout`, `git stash`, `git rev-parse`, `git show`, `git remote` | Core development workflow. Git operations already have their own tool (`ck3_git`) but agents use `ck3_exec` as fallback when `ck3_git` lacks a subcommand (e.g., `git stash`, `git remote`). |
| **Testing** | `python -m pytest` | Running test suites is fundamental dev workflow. Pytest is read-only + stdout. |
| **Linting** | `python -m tools.compliance.run_arch_lint_locked`, `python -m tools.arch_lint` | Arch lint runner. Used during contract close and code quality checks. |
| **QBuilder** | `python builder/daemon.py` | Daemon control (start, stop, status). Already has its own MCP tool but ck3_exec is the fallback for direct invocation. |
| **Environment** | `python --version`, `pip list`, `pip show` | Diagnostic/introspection commands. Read-only. |

### 10.3 Commands intentionally EXCLUDED

| Excluded | Why |
|----------|-----|
| `python -c` | Inline execution ban (§1) |
| `python -m` (bare) | Too broad — only specific modules whitelisted |
| `pip install` | Package mutation requires deliberate action, not whitelist |
| `rm`, `del`, `rmdir` | Destructive — not part of normal workflow |
| `powershell`, `cmd`, `bash` | Shell interpreters — whitelist specific commands, not shells |
| `curl`, `wget` | Network operations — not part of normal dev flow |

### 10.4 Match semantics

The current `_is_command_whitelisted()` uses **prefix matching**: `cmd_stripped == pattern or cmd_stripped.startswith(pattern + " ")`. This means:

- `"git status"` matches `git status` and `git status --short` but not `git statusx`
- `"python -m pytest"` matches `python -m pytest` and `python -m pytest tests/sprint0/ -v` but not `python -m pytestx`

This is correct behavior for both safety and usability.

### 10.5 Awaiting Nate's review

The above is a recommendation. Before writing to `policy/command_whitelist.json`:

- **Review the git set** — do you want `git push` whitelisted, or should it require contract/approval?
- **Review the pytest entry** — this allows running arbitrary test files. Acceptable?
- **Any additional operational commands** you use regularly via ck3_exec?

---

## 11) Extended Test Plan

> The existing 22 tests in `test_script_signing.py` all pass, but they test **isolated components** (signer, verifier, exec_gate predicate). They do NOT test the actual `_ck3_exec_internal` function or the end-to-end flow through enforcement. This is why they pass — they never hit the broken integration points.

### 11.1 Why current tests are insufficient

The 22 passing tests prove:
- `sign_script_for_contract()` produces valid HMAC → True
- `validate_script_signature()` rejects tampered content → True
- `exec_gate()` predicate returns correct booleans → True

But they **don't test**:
- Whether `_ck3_exec_internal` actually calls `enforce()` correctly
- Whether the whitelist file is loaded and checked end-to-end
- Whether WA2 resolution of the script path works
- Whether enforcement denial produces the right Reply codes
- Whether the raw dict return paths in `_ck3_exec_internal` are valid
- Whether `_detect_script_path` feeds correct data to `exec_gate`
- What happens when an agent sends `python -c "print('hi')"` (inline ban)
- What happens when an agent sends a non-whitelisted, non-script command

### 11.2 Proposed additional tests

#### Category A: Whitelist integration (end-to-end)

| Test ID | Description | Expected |
|---------|-------------|----------|
| EXEC-WL-01 | Whitelisted command (e.g., `git status`) passes enforcement | `enforce()` returns ALLOW |
| EXEC-WL-02 | Non-whitelisted, non-script command (e.g., `curl http://evil.com`) denied | `enforce()` returns DENY |
| EXEC-WL-03 | Whitelisted prefix with args (e.g., `git status --short`) passes | ALLOW |
| EXEC-WL-04 | Near-miss to whitelisted (e.g., `git statusx`) denied | DENY |
| EXEC-WL-05 | Empty whitelist file → all non-script commands denied | DENY |
| EXEC-WL-06 | Missing whitelist file → all non-script commands denied | DENY |
| EXEC-WL-07 | Malformed JSON in whitelist → graceful fallback to empty list | DENY |

#### Category B: Inline execution ban

| Test ID | Description | Expected |
|---------|-------------|----------|
| EXEC-BAN-01 | `python -c "code"` — rejected even with contract | DENY |
| EXEC-BAN-02 | `python -m module` — rejected (unless specifically whitelisted module) | DENY for non-whitelisted |
| EXEC-BAN-03 | `python -m pytest` — allowed (whitelisted) | ALLOW |
| EXEC-BAN-04 | Shell pipeline `echo x \| python` — denied | DENY |
| EXEC-BAN-05 | Multiple commands `git status && rm -rf /` — denied | DENY |

#### Category C: Script path WA2 resolution

| Test ID | Description | Expected |
|---------|-------------|----------|
| EXEC-WA2-01 | Script in wip dir → WA2 resolves to `(ck3raven_data, wip)` | Correct coordinates to enforce() |
| EXEC-WA2-02 | Script outside wip dir → WA2 resolves to different subdirectory | DENY (no EXEC_COMMANDS rule) |
| EXEC-WA2-03 | Script with path traversal (`python ../../etc/passwd`) → WA2 rejects | DENY |
| EXEC-WA2-04 | Script doesn't exist on disk → `_detect_script_path` returns None | Falls through to branch 3 → DENY |

#### Category D: `_ck3_exec_internal` integration

| Test ID | Description | Expected |
|---------|-------------|----------|
| EXEC-INT-01 | Full flow: whitelisted `git status` → enforcement → subprocess | Reply with exit_code, output |
| EXEC-INT-02 | Full flow: denied command → enforcement → no subprocess | Reply with DENY, no execution |
| EXEC-INT-03 | Enforcement returns DENY → `_ck3_exec_internal` returns Reply (not dict) | isinstance(result, Reply) |
| EXEC-INT-04 | Enforcement returns ALLOW → execution success → returns Reply (not dict) | isinstance(result, Reply) |
| EXEC-INT-05 | Subprocess timeout → returns Reply with timeout info | Reply with exit_code -1 |
| EXEC-INT-06 | dry_run=True → checks policy only, no execution | Reply with executed=False |

#### Category E: Return type verification

| Test ID | Description | Expected |
|---------|-------------|----------|
| EXEC-RT-01 | All code paths return Reply (not dict) | After normalization: no dict returns |
| EXEC-RT-02 | Enforcement denial → Reply with denied status | reply.is_denied is True |
| EXEC-RT-03 | Success execution → Reply with EN-EXEC-S-001 | reply.code == "EN-EXEC-S-001" |
| EXEC-RT-04 | Dry run → Reply with EN-EXEC-S-002 | reply.code == "EN-EXEC-S-002" |
| EXEC-RT-05 | Timeout → Reply with MCP-SYS-E-001 | Error reply, not raw dict |

#### Category F: Edge cases

| Test ID | Description | Expected |
|---------|-------------|----------|
| EXEC-EDGE-01 | No WA2 available → graceful failure | Reply with error |
| EXEC-EDGE-02 | Working dir doesn't exist → WA2 returns Invalid | Reply with WA-RES-I-001 |
| EXEC-EDGE-03 | Command is empty string → exec_gate rejects | DENY |
| EXEC-EDGE-04 | Command is None → type error handled | Graceful error |
| EXEC-EDGE-05 | Timeout = 0 → clamped to 1 | Execution proceeds with timeout=1 |
| EXEC-EDGE-06 | Timeout = 999 → clamped to 300 | Execution proceeds with timeout=300 |

### 11.3 Test implementation priorities

**Before any code changes:**

1. **Categories A + B first** — validate the whitelist and inline ban behavior against the CURRENT code. These tests should FAIL or show exactly where the gaps are (empty whitelist, no WA2 on script path).
2. **Category D next** — integration tests for `_ck3_exec_internal`. These require mocking subprocess but test the real enforce() flow.
3. **Categories C + E after code changes** — these test the fixes (WA2 script resolution, return type normalization).
4. **Category F last** — edge cases for hardening.

---

## 12) Revised Implementation Status

> Updated February 22, 2026. Supersedes §8.

| Requirement | Status | Notes |
|-------------|--------|-------|
| §1 Inline ban | **HALF-DONE** | Whitelist machinery exists but file is empty. Inline ban is enforced by accident (nothing passes exec_gate). See §10 for whitelist population. |
| §2 Script location | **PARTIALLY** | OPERATIONS_MATRIX gating exists. Script path not resolved via WA2 (only working_dir is). |
| §3 HMAC verifier | **EXISTS** | `validate_script_signature()` tested 22/22 green |
| §3 HMAC signer | **EXISTS** | `sign_script_for_contract()` exists and is tested. No human trigger / extension UI to invoke it. |
| §4 Working directory | **IMPLEMENTED** | Resolved via WA2, defaults to `root:ck3raven_data/wip` |
| §5 Leak scanning | **DEFERRED** | Demoted: premature while other tools still emit host paths. Revisit when ck3_file and ck3_git are migrated. |
| §7 Return type | **NOT DONE** | Mixed Reply\|dict — needs normalization |
| §10 Whitelist | **NOT POPULATED** | File exists, commands list is empty. Recommendations in §10. |
| §11 Tests | **COMPONENT ONLY** | 22 unit tests pass on isolated components. No integration or end-to-end tests. |

### Immediate priorities (Tier 1)

1. **Write extended tests** (§11 Categories A + B) — validate current behavior, expose gaps
2. **Populate whitelist** (§10) — restore operational functionality
3. **Resolve script path via WA2** (§2 gap) — correct enforcement coordinates
4. **Normalize return types** (§7) — Reply throughout

### Deferred (Tier 2)

5. **Extension UI for script signing** — human approval trigger (Priority 4, extension work)
6. **Leak scanning** — when other tools are migrated
