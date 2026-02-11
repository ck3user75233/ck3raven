# CONTRACT OPERATIONS GUIDE

Status: CANONICAL  
Applies to: ck3raven-dev, ck3lens  
Authority: Phase 1.5 Deterministic Evidence Infrastructure  
Last Updated: February 11, 2026  
Governed by: [CANONICAL_CONTRACT_LAW.md](CANONICAL_CONTRACT_LAW.md)

---

## Purpose

This document provides operational guidance for the CK3Raven Canonical Contract System.

It describes:

- how contracts are created, signed, used, and closed
- the capability matrix and enforcement details
- compliance tools, workflows, and schemas
- the audit pipeline and evidence requirements

This document is **subordinate** to [CANONICAL_CONTRACT_LAW.md](CANONICAL_CONTRACT_LAW.md). If any operational detail here conflicts with the Law document, the Law governs.

---

# PART 1: CONTRACT OPERATIONS

---

## 1. Contract Schema (Version 1)

### 1.1 Required Fields

A valid contract must include:

| Field | Type | Description |
|-------|------|-------------|
| `contract_id` | string | Unique identifier (immutable) |
| `created_at` | ISO-8601 | Creation timestamp (immutable) |
| `mode` | enum | `ck3lens` or `ck3raven-dev` |
| `root_category` | enum | One of the `RootCategory` values |
| `intent` | string | Human-readable description of work |
| `operations` | list | Canonical operations: READ, WRITE, DELETE |
| `targets` | list | Target declarations with path and description |
| `work_declaration` | object | Planned changes (see section 1.4) |
| `author` | string | Attribution |
| `session_signature` | string | Sigil-signed origin proof |

### 1.2 Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `expires_at` | ISO-8601 | Expiry timestamp (default: 8 hours) |
| `status` | string | Contract lifecycle state |
| `closed_at` | ISO-8601 | When contract was closed |
| `notes` | string | Free-form notes |
| `schema_version` | string | Schema version identifier |

### 1.3 Unknown Fields

Contracts containing unknown or undeclared fields are non-canonical and MUST be rejected by canonical loaders. The schema validator in `contract_v1.py` is authoritative on field acceptance.

### 1.4 Work Declaration

Each contract must include a work declaration describing:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `work_summary` | string | Yes | Brief description of the work |
| `work_plan` | list[string] | Yes (1-15 items) | Ordered list of planned steps |
| `out_of_scope` | list[string] | No | What this work does NOT include |
| `edits` | list[edit] | Yes for WRITE/DELETE | Specific file edits planned |

Each edit entry:

| Field | Type | Description |
|-------|------|-------------|
| `file` | string | Relative path to file |
| `edit_kind` | string | `add`, `modify`, `delete`, or `rename` |
| `location` | string | Description of where in file |
| `change_description` | string | What changes are being made |

### 1.5 Enforcement Status of Work Declarations

Work declarations are **audit artifacts, not enforcement gates**.

`enforcement.py` validates:

- mode and operation type
- root category containment
- active contract exists (for mutating operations)

`enforcement.py` does **not** validate:

- writes match `work_declaration.edits[]`
- actual files modified match declared targets
- symbol changes match symbol intent

This is a deliberate Phase 1 design choice. Phase 2 close-time audit gates may validate work declaration completeness against actual changes. The gap is documented, not hidden.

Work declarations serve as:

- human-readable intent communication
- evidence for contract close audit
- scope documentation for future review

---

## 2. Contract Signing

Contracts are cryptographically signed at creation using Sigil.

### 2.1 Signing

Signature payload: `contract:{contract_id}|{created_at}`

Signed using: `HMAC-SHA256(CK3LENS_SIGIL_SECRET, payload)`

Implementation: `_contract_signing_payload()` and `_sign_contract()` in `contract_v1.py`

### 2.2 Verification

Verification occurs at load time via `_verify_contract_signature()`.

Invalid signatures cause the contract to be rejected. Reasons for failure:

- Sigil secret unavailable (extension not running)
- Secret has changed (different session)
- Payload tampered with
- Signature missing

---

## 3. Contract Lifecycle

```
1. Open
   - Agent calls ck3_contract(command="open", ...)
   - Contract ID generated, timestamp set
   - Sigil signs the identity payload
   - Contract persisted to active contract file

2. Active
   - Agent performs work under contract scope
   - Enforcement checks contract presence for WRITE/DELETE
   - Evidence artifacts generated

3. Close (normal)
   - Agent calls ck3_contract(command="close")
   - Audit pipeline validates all evidence
   - If audit passes: status = "closed"
   - If audit fails: closure blocked, agent must fix issues

4. Cancel (abnormal)
   - Agent calls ck3_contract(command="cancel")
   - Contract marked cancelled with reason
   - No audit required

5. Expired
   - Contract past expires_at timestamp
   - Treated as invalid, cannot be used for operations
```

---

## 4. Operations

### 4.1 Canonical Operations

| Operation | Enforcement Type | Requires Contract |
|-----------|-----------------|-------------------|
| READ | READ | No |
| WRITE | WRITE | Yes (except WIP) |
| DELETE | DELETE | Yes (except WIP) |

All mutating operations must be explicitly declared in the contract's operations list.

### 4.2 Enforcement Mapping

Enforcement recognizes three `OperationType` values defined in `enforcement.py`:

- `OperationType.READ` — read operations
- `OperationType.WRITE` — all mutations
- `OperationType.DELETE` — file/resource deletion

All contract-declared operations map to one of these three for enforcement evaluation.

---

## 5. Targets

Targets define the scope boundary of a contract.

### 5.1 Requirements

Targets must:

- be relative to the root category
- never escape containment (no `../` paths)
- never be inferred from runtime state

Each target has:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | Yes | Relative path within root |
| `description` | string | Yes | Human-readable purpose |
| `target_type` | string | No | Type classification |

### 5.2 Target Authority

Targets do not grant authority. They declare intent. Enforcement validates operations against the capability matrix independently of target declarations.

---

## 6. Execution Modes

### 6.1 ck3lens Mode

- Limited write authority
- May modify user mods (nested paths in ROOT_USER_DOCS/mod, 3+ path components)
- May not write to ROOT_REPO
- Must operate conservatively
- Intended for CK3 modding workflows

### 6.2 ck3raven-dev Mode

- Full development mode
- Write access to ROOT_REPO and ROOT_CK3RAVEN_DATA (except db/daemon)
- May not modify user mods or launcher state
- Intended for infrastructure development

### 6.3 Mode Initialization

Mode initialization requires HAT (Human Authorization Token):

1. Extension generates Sigil-signed token at MCP spawn
2. User selects mode in VS Code sidebar
3. Token injected into chat prompt
4. Agent passes token to `ck3_get_mode_instructions(mode="...", hat_token="...")`
5. Server validates Sigil signature and 5-minute expiry

---

# PART 2: CAPABILITY MATRIX

---

## 7. Capability Matrix

Authorization is determined by: `(mode, root_category, subdirectory, operation)`

No other inputs are permitted.

Source of truth: `tools/ck3lens_mcp/ck3lens/capability_matrix.py`

### 7.1 Global Invariants

These override the matrix and are enforced in `enforcement.py`:

1. **Contract required** for all WRITE/DELETE operations outside of WIP
2. **db/ and daemon/** subdirectories are NEVER writable (owned by QBuilder daemon)
3. **ROOT_EXTERNAL** is always DENY for all operations

### 7.2 ck3lens Mode

Key: A = ALLOW, D = DENY

| Root | Subdirectory | R | W | Del | Notes |
|------|-------------|---|---|-----|-------|
| ROOT_GAME | — | A | D | D | Vanilla game files |
| ROOT_STEAM | — | A | D | D | Workshop mods |
| ROOT_USER_DOCS | (base) | A | D | D | Launcher DB, saves |
| ROOT_USER_DOCS | mod | A | A | A | Subfolders only (3+ path components) |
| ROOT_CK3RAVEN_DATA | (base) | A | D | D | Root-level read-only |
| ROOT_CK3RAVEN_DATA | wip | A | A | A | No contract required |
| ROOT_CK3RAVEN_DATA | config | A | A | D | |
| ROOT_CK3RAVEN_DATA | playsets | A | A | A | |
| ROOT_CK3RAVEN_DATA | logs | A | A | D | |
| ROOT_CK3RAVEN_DATA | journal | A | A | D | |
| ROOT_CK3RAVEN_DATA | cache | A | A | A | |
| ROOT_CK3RAVEN_DATA | artifacts | A | A | D | |
| ROOT_CK3RAVEN_DATA | db | A | D | D | Daemon-owned |
| ROOT_CK3RAVEN_DATA | daemon | A | D | D | Daemon-owned |
| ROOT_VSCODE | — | A | D | D | |
| ROOT_REPO | — | D | D | D | Not visible |
| ROOT_EXTERNAL | — | D | D | D | Always denied |

### 7.3 ck3raven-dev Mode

| Root | Subdirectory | R | W | Del | Notes |
|------|-------------|---|---|-----|-------|
| ROOT_REPO | — | A | A | A | Full access (with contract) |
| ROOT_GAME | — | A | D | D | Read-only reference |
| ROOT_STEAM | — | A | D | D | Read-only reference |
| ROOT_USER_DOCS | (base) | A | D | D | |
| ROOT_USER_DOCS | mod | A | D | D | No mod writes in dev mode |
| ROOT_CK3RAVEN_DATA | (base) | A | D | D | Root-level read-only |
| ROOT_CK3RAVEN_DATA | wip | A | A | A | No contract required |
| ROOT_CK3RAVEN_DATA | config | A | A | A | |
| ROOT_CK3RAVEN_DATA | playsets | A | A | A | |
| ROOT_CK3RAVEN_DATA | logs | A | A | A | |
| ROOT_CK3RAVEN_DATA | journal | A | A | A | |
| ROOT_CK3RAVEN_DATA | cache | A | A | A | |
| ROOT_CK3RAVEN_DATA | artifacts | A | A | A | |
| ROOT_CK3RAVEN_DATA | db | A | D | D | Daemon-owned |
| ROOT_CK3RAVEN_DATA | daemon | A | D | D | Daemon-owned |
| ROOT_VSCODE | — | A | A | D | Write settings, no delete |
| ROOT_EXTERNAL | — | D | D | D | Always denied |

### 7.4 Subdirectory Resolution

For ROOT_CK3RAVEN_DATA and ROOT_USER_DOCS, the capability matrix uses subdirectory-specific entries. If `WorldAdapter.resolve()` returns a path within these roots without a recognized subdirectory, enforcement will DENY the operation with a diagnostic failure (`EN-SUBDIR-I-001`).

### 7.5 Subfolders-Writable Behavior

ROOT_USER_DOCS/mod uses `subfolders_writable`. This means:

- Files directly in `mod/` (like `*.mod` descriptor files) are NOT writable
- Files nested inside mod subfolders (e.g., `mod/MyMod/common/traits/my_trait.txt`) ARE writable
- Enforcement checks path depth: 3+ components required (e.g., `mod/MyMod/file.txt`)

### 7.6 Canonical Authority

The capability matrix in `capability_matrix.py` is authoritative. If this document and the code diverge, the code governs and this document must be updated.

---

# PART 3: PROTECTED FILES AND TOKENS

---

## 8. Protected Files

### 8.1 Mechanism

| Component | Location |
|-----------|----------|
| Manifest | `policy/protected_files.json` |
| Implementation | `tools/compliance/protected_files.py` |
| MCP tool | `ck3_protect(command="list\|verify\|add\|remove")` |

### 8.2 Contract Open Requirement

To open a contract that addresses a protected file, a HAT is required. If HAT approval is not provided, the request to open the contract is invalid.

Protected file checks also occur in the MCP tool layer before any write to a protected path. Both the capability matrix and the protected files manifest must pass for a write to succeed.

### 8.3 Key Functions

| Function | Purpose |
|----------|---------|
| `load_manifest()` | Load protected files list |
| `save_manifest()` | Save updated manifest |
| `is_protected()` | Check if a path is protected |
| `verify_all_hashes()` | Verify SHA256 integrity of all protected files |
| `check_edits_against_manifest()` | Check if proposed edits touch protected files |

---

## 9. Token Operations

### 9.1 HAT (Human Authorization Token)

HAT provides interactive human approval for:

- Mode initialization
- Protected file operations
- Contract open for protected paths

**Delivery mechanisms:**

| Variant | Delivery | Consumption |
|---------|----------|-------------|
| HAT (init) | Sigil-signed inline token in chat prompt | `ck3_get_mode_instructions()` validates and consumes |
| HAT (protect) | Ephemeral approval file written by extension | `consume_hat_approval()` reads, validates, and deletes file |

**HAT init lifecycle:**

1. Extension generates Sigil-signed token at MCP spawn
2. User clicks "Initialize Agent" in VS Code sidebar
3. Token injected into chat prompt
4. Agent passes to `ck3_get_mode_instructions(mode="...", hat_token="...")`
5. Server validates Sigil signature and 5-minute expiry, consumes

**Properties:** ephemeral, single-use, session-scoped, Sigil-signed.

### 9.2 NST (New Symbol Token) — In-Policy Compliance Verification

NST is **not an exception token**. Creating new symbols that have been approved and agreed with the user is **within policy**.

NST declares intentionally new identifiers introduced during a contract, verifying that new symbol creation was deliberate:

- Ephemeral: session-scoped, not persisted to git-tracked directories
- Generated at contract close time, consumed during the close audit pipeline
- Covers all new symbols detected in git diff by the semantic validator
- TTL: 24 hours (session-bound, typically consumed immediately)

**When required:** The semantic validator identifies new symbols in changed files via git diff. If new symbols are found, NST coverage is required for contract closure. This is compliance verification (confirming intentional creation), not an exception to policy.

### 9.3 LXE (Lint Exception Token) — Exception Token

LXE is an **exception token** — it exempts the agent from failing the lint requirement at contract closeout, with user approval. Unlike NST, LXE represents an explicit deviation from a compliance requirement.

- Persistent: git-tracked, reviewable
- Contract-bound, scope-bound, non-transferable
- TTL: 8 hours

**Lifecycle:**

```
Agent proposes → Human approves/rejects → Token valid during TTL → Auto-expires
```

1. **Proposed:** Agent creates at `artifacts/tokens_proposed/<id>.token.json`
2. **Approved:** Human moves to `policy/tokens/<id>.token.json`
3. **Rejected:** Human deletes proposed token
4. **Expired:** Status changes after `expires_at` timestamp

**LXE Token Schema:**

```json
{
  "schema_version": "v1",
  "token_type": "LXE",
  "token_id": "<uuid4>",
  "contract_id": "<parent-contract>",
  "created_at": "ISO-8601",
  "expires_at": "ISO-8601",
  "status": "proposed | approved | rejected | expired",
  "justification": "<human-readable reason>",
  "scope": {
    "root_category": "ROOT_REPO",
    "target_paths": ["relative/path/..."],
    "rule_codes": ["RULE_CODE_1"],
    "max_violations": null
  },
  "signature": "<hmac-sha256 of canonical JSON>"
}
```

### 9.4 Token Registry Functions

| Function | Purpose |
|----------|---------|
| `propose_lxe()` | Create proposed LXE token |
| `validate_token()` | Verify signature and status |
| `save_proposed_token()` | Write to `artifacts/tokens_proposed/` |
| `write_hat_request()` | Write HAT request for extension approval |
| `consume_hat_approval()` | Consume ephemeral HAT approval file |

### 9.5 Token Directories

| Directory | Purpose | Git-Tracked |
|-----------|---------|-------------|
| `policy/tokens/` | Human-approved LXE tokens | Yes |
| `artifacts/tokens_proposed/` | Agent-created LXE proposals | Yes |

---

## 10. Sigil Operations

Sigil is the canonical HMAC-SHA256 signing primitive.

### 10.1 Purpose

- HAT token signing and verification
- Contract signing at creation
- LXE token signature verification

### 10.2 Implementation

| Component | Location |
|-----------|----------|
| Functions | `sigil_sign()`, `sigil_verify()`, `sigil_available()` |
| Module | `tools/compliance/sigil.py` |
| Secret | `CK3LENS_SIGIL_SECRET` environment variable |
| Full specification | `docs/SIGIL_ARCHITECTURE.md` (28 invariants) |

### 10.3 Properties

- HMAC-SHA256 using shared secret
- Secret provided by extension at MCP spawn
- If secret unavailable, `sigil_available()` returns False
- All signing operations fail safe (deny) when secret missing

---

# PART 4: COMPLIANCE TOOLS

---

## 11. Overview

All compliance tools are located in `tools/compliance/`.

| Tool | Purpose | Status |
|------|---------|--------|
| `linter_lock.py` | Hash-lock arch_lint ruleset | Active |
| `run_arch_lint_locked.py` | Run arch_lint with lock verification and watermarking | Active |
| `semantic_validator.py` | Git-diff-based symbol change detection | Active |
| `tokens.py` | NST/LXE/HAT token lifecycle management | Active |
| `protected_files.py` | SHA256 manifest for critical file protection | Active |
| `sigil.py` | HMAC-SHA256 cryptographic signing primitive | Active |
| `audit_contract_close.py` | Contract close audit pipeline | Active |

---

## 12. Linter Lock (`linter_lock.py`)

### 12.1 Purpose

Hash-locks the arch_lint ruleset to ensure deterministic lint behavior. Changes to lint rules must be explicitly proposed and approved.

### 12.2 Scope

Only `tools/arch_lint/*.py` and `tools/arch_lint/requirements.txt` are locked. Ruff is explicitly out of scope for Phase 1.5.

### 12.3 Commands

```bash
# Create active lock (human use only)
python -m tools.compliance.linter_lock create

# Verify current files against active lock
python -m tools.compliance.linter_lock verify

# Show lock status and verification
python -m tools.compliance.linter_lock status

# Create proposed lock (agent use)
python -m tools.compliance.linter_lock propose

# Diff active vs proposed lock
python -m tools.compliance.linter_lock diff

# Check if contract closure is allowed
python -m tools.compliance.linter_lock check-closure
```

### 12.4 Workflow: Agent Modifies arch_lint

1. Agent modifies files in `tools/arch_lint/`
2. Agent calls `create_proposed_lock()` — writes to `artifacts/locks/proposed/`
3. `verify_lock()` now FAILS (working tree differs from active lock)
4. Human reviews diff via `diff` command
5. Human either:
   - **Approves:** Copies proposed to `policy/locks/linter.lock.json`
   - **Rejects:** Deletes proposed lock, agent reverts changes
6. After promotion, `verify_lock()` passes again

### 12.5 Lock File Schema

```json
{
  "schema_version": "v1",
  "lock_hash": "<sha256>",
  "created_at": "ISO-8601",
  "created_by": "system|agent",
  "description": "...",
  "manifests": [{"glob": "...", "description": "..."}],
  "files": [{"path": "...", "sha256": "...", "size_bytes": N}],
  "file_count": N,
  "total_bytes": N
}
```

---

## 13. Locked Lint Runner (`run_arch_lint_locked.py`)

### 13.1 Purpose

Wrapper that:
1. Verifies the linter lock FIRST
2. Runs arch_lint
3. Stamps output with cryptographic watermark

### 13.2 Usage

```bash
python -m tools.compliance.run_arch_lint_locked <contract_id> [arch_lint args...]
```

### 13.3 Output

Creates two files in `artifacts/lint/`:

| File | Format | Purpose |
|------|--------|---------|
| `<contract_id>.arch_lint.json` | JSON | Structured report for programmatic use |
| `<contract_id>.arch_lint.txt` | Text | Human-readable report |

### 13.4 Watermark

Every report includes a cryptographic watermark:

```
WATERMARK: lock=8454fe20a5d0eb3e... alg=sha256 ts=2026-01-20T08:08:01+00:00
```

This proves which linter version produced the output.

---

## 14. Semantic Validator (`semantic_validator.py`)

### 14.1 Purpose

Evidence generator for contract close audit. Analyzes files changed during a contract to detect new symbol definitions and unresolved references.

**The semantic validator is a SENSOR, not a JUDGE.** It observes reality and emits evidence. All enforcement decisions occur during contract audit and closure.

### 14.2 Dual-Path Analysis

| File Type | Parser Used | Detects |
|-----------|-------------|---------|
| Python (`.py`) | Python `ast` module | Classes, functions, imports, references |
| CK3 script (`.txt`) | `ck3raven.parser.parse_source()` | Events, traits, decisions, scripted effects |

### 14.3 Output Schema

```json
{
  "tool": "semantic_validator",
  "version": "1.0.0",
  "contract_id": "...",
  "files_scanned": ["..."],
  "ck3": {
    "definitions_added": [],
    "undefined_refs": [],
    "parse_errors": []
  },
  "python": {
    "definitions_added": [],
    "undefined_refs": [],
    "syntax_errors": []
  }
}
```

### 14.4 Symbol Change Detection

| Guarantee | How Provided |
|-----------|-------------|
| **Baseline** | Git diff of contract branch vs base commit identifies changed files |
| **Diff** | Semantic validator analyzes changed files, extracts `definitions_added` |
| **Coverage** | NST tokens must cover all new definitions found |
| **Evidence** | `SemanticReport` saved as JSON artifact for audit trail |

Git diff is the source of truth for what changed; the semantic validator extracts structured meaning from those changes.

### 14.5 Usage

```bash
python -m tools.compliance.semantic_validator file1.py file2.txt --out report.json
python -m tools.compliance.semantic_validator --files-from manifest.txt --out report.json
```

### 14.6 Integration with Contract Close

`audit_contract_close.py` calls `check_symbols_diff()` which:

1. Gets list of changed files from git diff
2. Runs semantic validator on each changed file
3. Collects all `definitions_added`
4. Checks that NST tokens cover all new definitions
5. Returns pass/fail with evidence

---

## 15. Contract Close Audit Pipeline

### 15.1 Purpose

`audit_contract_close.py` implements a 6-check pipeline that validates all contract work before closure.

### 15.2 Pipeline

| Step | Function | Validates |
|------|----------|-----------|
| 1 | `check_linter_lock()` | arch_lint rules unchanged during contract |
| 2 | `check_arch_lint()` | Watermarked lint passes on changed files |
| 3 | `check_playset_drift()` | Playset hasn't changed during contract |
| 4 | `check_symbols_diff()` | New symbols detected via git diff + semantic validator |
| 5 | `validate_nst_tokens()` | NST tokens cover all new symbols |
| 6 | `validate_lxe_tokens()` | Approved LXE tokens cover all lint exceptions |

### 15.3 Close Flow

```
1. Close gates (Phase 2, future)
   - Contract not expired
   - Required evidence files exist
   - Linter lock valid

2. Contract close audit (current)
   - All 6 checks above
   - Produces pass/fail with detailed reasons

3. If audit passes: contract status = "closed"
```

---

# PART 5: PHASE MODEL

---

## 16. Phase 1: Contract Law

Phase 1 defines the legal structure of the system.

Established:

- contract schema
- root categories
- capability matrix
- forbidden concepts
- zero compatibility rule

Phase 1 defines what may occur.

**Status: Complete.**

---

## 17. Phase 1.5: Deterministic Evidence

Phase 1.5 establishes trust in compliance claims.

### 17.1 Properties

1. **Locked rulebooks** — Static analysis configurations are content-hashed. Outputs must declare the rule hash used. Mismatched hashes invalidate the result.

2. **Symbol change detection** — New symbols detected via git diff and the semantic validator. Symbol existence determined by analyzing changed files, not snapshot comparison.

3. **Tokenized exceptions** — NST (ephemeral) and LXE (persistent). Contract-bound, scope-bound, non-transferable.

4. **Compliance evidence** — All write activity must produce artifacts proving rules applied, symbols changed, and exceptions exercised. Absence of evidence constitutes failure.

### 17.2 Component Status

| Component | Status | Description |
|-----------|--------|-------------|
| A. Linter Lock | Complete | `linter_lock.py` — immutable arch_lint rules |
| B. Scoped Lint | Complete | `run_arch_lint_locked.py` — watermarked lint with lock verification |
| C. Semantic Validator | Complete | `semantic_validator.py` — git-diff-based symbol change detection |
| D. Token Registry | Complete | `tokens.py` — NST, LXE, HAT lifecycle management |
| E. Protected Files | Complete | `protected_files.py` + `policy/protected_files.json` |
| F. Sigil Crypto | Complete | `sigil.py` + `SIGIL_ARCHITECTURE.md` |
| G. Contract Close Audit | Complete | `audit_contract_close.py` — 6-check pipeline |

**Status: Complete.**

---

## 18. Phase 2: Deterministic Gates (Future)

**Not yet implemented. The following describes intended behavior.**

Phase 2 introduces deterministic gates at two lifecycle points:

1. **Open-time gates** — Validate that declared contract scope is feasible given mode and capability matrix
2. **Close-time gates** — Reconcile declared work against actual changes (sole reconciliation point)

There are **no execution-time gates**. During execution, enforcement (`enforce()`) operates independently of contract declarations, as it does today (Phase 1/1.5).

### 18.1 Gate Layer Ownership

Gates conform to the Canonical Reply System (`reply_codes.py`):

| Layer | Area | Allowed Types | Usage |
|-------|------|---------------|-------|
| CT | GATE | S, I, E | Contract scope/declaration validation |
| EN | WRITE/EXEC/OPEN | S, D, E | Enforcement decisions (unchanged) |

CT-layer gates **never produce D** (Denied). If a gate returns I (Invalid), the tool handler decides whether to reject the request. Governance refusals (D) originate only from the EN layer.

### 18.2 Gate Outcomes

| Code Pattern | Meaning | Example |
|--------------|---------|---------|
| CT-GATE-S-NNN | Gate passed | Scope feasibility confirmed |
| CT-GATE-I-NNN | Gate failed (declaration issue) | WRITE to ROOT_GAME infeasible in ck3lens mode |
| CT-GATE-E-NNN | Gate error (system failure) | Capability matrix lookup failed unexpectedly |

### 18.3 Gate Logging

Gate invocations are logged per Canonical Logs specification (`CANONICAL_LOGS.md`):

- Category: `contract.gate` (sub-categories `contract.gate.open`, `contract.gate.close`)
- Required fields: `gate_name`, `contract_id`, `root_category`, `reply_code`
- Redaction: Never log Sigil signatures, absolute host paths, or file contents
- Evidence: Use `debug_get_logs(category="contract.gate", trace_id=...)` for verification

### 18.4 Close-Time as Sole Reconciliation Point

Open-time gates validate **feasibility** (can you do what you declare?). Close-time gates validate **completeness** (did you do what you declared?). No gate operates at execution time. This separation ensures:

- Enforcement remains THE single decision boundary at execution time
- Contracts do not validate individual file paths at write time (Law §9.2)
- Reconciliation between declared and actual work happens once, at close

### 18.5 Deliverables

- `policy/contract_gates.py`: All gate functions (open-time and close-time)

### 18.6 Prerequisites

1. **Capability matrix alignment:** Sections 7.2/7.3 must match `capability_matrix.py` (verified)
2. **Reply code registry:** CT-GATE-* codes registered in `reply_codes.py`
3. **Canonical logs compliance:** Gate logging uses JSONL format with trace_id correlation

---

## 19. Phase 3: Execution Enforcement (Future)

Phase 3 will bind contracts, evidence artifacts, symbol deltas, and exception tokens into a single execution boundary.

---

# PART 6: REFERENCE

---

## 20. Prohibited Actions

Agents MUST NOT:

1. Write directly to `policy/locks/` (human approval required)
2. Delete or modify the active linter lock
3. Skip lock verification before lint runs
4. Close contracts with unverified lint evidence
5. Introduce undeclared new symbols without NST tokens
6. Write to protected files without HAT approval
7. Execute direct DB mutations in MCP tools (daemon-only)

---

## 21. Directory Structure

```
ck3raven/
  policy/
    locks/
      linter.lock.json                   # Active approved linter lock
    tokens/
      <id>.token.json                    # Approved LXE tokens
    protected_files.json                 # Protected files manifest

  artifacts/
    locks/
      proposed/
        linter.lock.json                 # Agent-proposed lock (pending approval)
    lint/
      <contract_id>.arch_lint.json       # Watermarked lint reports
    tokens_proposed/
      <id>.token.json                    # Agent-proposed LXE tokens (pending approval)

  tools/
    compliance/
      __init__.py
      linter_lock.py
      run_arch_lint_locked.py
      semantic_validator.py
      tokens.py
      protected_files.py
      sigil.py
      audit_contract_close.py
```

---

## 22. Canonical Locations

| Artifact | Location | Git-Tracked |
|----------|----------|-------------|
| Active linter lock | `policy/locks/linter.lock.json` | Yes |
| Proposed linter lock | `artifacts/locks/proposed/linter.lock.json` | Yes |
| Lint reports | `artifacts/lint/<contract_id>.arch_lint.json` | Yes |
| Protected files manifest | `policy/protected_files.json` | Yes |
| Approved LXE tokens | `policy/tokens/<id>.token.json` | Yes |
| Proposed LXE tokens | `artifacts/tokens_proposed/<id>.token.json` | Yes |
| Active contract | Managed by `contract_v1.py` | No (session state) |
| Capability matrix | `tools/ck3lens_mcp/ck3lens/capability_matrix.py` | Yes |
| Enforcement | `tools/ck3lens_mcp/ck3lens/policy/enforcement.py` | Yes |

---

## 23. References

- [CANONICAL_CONTRACT_LAW.md](CANONICAL_CONTRACT_LAW.md) — Binding law (this document is subordinate)
- [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) — Core architectural rules
- [SIGIL_ARCHITECTURE.md](SIGIL_ARCHITECTURE.md) — Cryptographic signing (28 invariants)
- [PROTECTED_FILES_AND_HAT.md](PROTECTED_FILES_AND_HAT.md) — Protected file authorization
- [SINGLE_WRITER_ARCHITECTURE.md](SINGLE_WRITER_ARCHITECTURE.md) — QBuilder daemon (single writer)
- `tools/compliance/` — Phase 1.5 compliance tools
- `tools/ck3lens_mcp/ck3lens/capability_matrix.py` — Authoritative capability matrix

---

# APPENDIX: Strategic Analysis of Architectural Debt

> **Note:** This analysis is time-bound. Violation counts were accurate as of January 2026. Re-run arch_lint for current numbers.

### Problem Summary

Running arch_lint v2.35 against the codebase revealed **510 real violations**. Analysis confirmed ~99% are legitimate architectural issues.

### Primary Violation Categories

| Category | Count (est.) | Root Cause |
|----------|-------------|------------|
| Path classification duplication | ~200 | `ck3lens_rules.py` duplicates WorldAdapter |
| Oracle patterns | ~150 | `allowed_*`, `is_*` checks scattered |
| Banned terminology | ~80 | "local mod" vs ROOT_USER_DOCS |
| SQL mutations outside builder | ~30 | Direct DELETE/INSERT in MCP tools |
| Mode-specific types | ~20 | `CK3LensTokenType` should be unified |
| Legacy compatibility code | ~30 | Dead code paths for old formats |

### Recommended Cleanup Sequence

**Phase 2A: Path Consolidation (High Impact)**
1. Move ALL path classification to WorldAdapter
2. Delete `classify_path_domain()` from ck3lens_rules.py
3. Update enforcement.py to receive `CanonicalAddress` not raw paths
4. Expected reduction: 400-500 violations

**Phase 2B: Terminology Normalization**
1. Replace all "local mod" → ROOT_USER_DOCS domain
2. Replace all "workshop mod" → ROOT_STEAM domain
3. Expected reduction: 80-100 violations

**Phase 2C: Token Type Unification**
1. Deprecate `CK3LensTokenType`
2. Update all token references to unified `TokenType`
3. Expected reduction: 20-30 violations

**Phase 2D: SQL Mutation Routing**
1. Route all direct SQL mutations through daemon IPC
2. Verify read-only DB mode in all MCP servers
3. Expected reduction: 30-50 violations

### Success Criteria

Cleanup is complete when:
- `arch_lint` returns 0 errors on full codebase
- No LXE tokens required for production code
- All path resolution flows through WorldAdapter
- All DB mutations flow through QBuilder daemon
- No banned terms in executable code
