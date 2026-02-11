# CANONICAL CONTRACT SYSTEM v2

Status: CANONICAL  
Applies to: ck3raven-dev, ck3lens  
Authority Level: HARD LAW  
Last Updated: February 11, 2026  
Supersedes: CANONICAL CONTRACT SYSTEM (v1)

---

## 0. Purpose

The Canonical Contract System defines how agents are permitted to act.

Its purpose is to ensure that:

- all write operations are explicitly authorized
- all scope is declared, never inferred
- all deviations are intentional and reviewable
- all authority is geographic, not semantic

Failure is preferable to ambiguity.

---

## 1. Foundational Principle

### 1.1 Geographic Authority Principle

All authorization is derived solely from filesystem geography.

Authority is determined by:

- root category
- execution mode
- requested operation
- capability matrix

Semantic meaning is irrelevant.

Conceptual relationships are irrelevant.

Only physical path containment matters.

### 1.2 Visibility Versus Authority

Visibility and authority are not equivalent.

- visibility defines what may be discovered
- authority defines what may be modified

Discovery never grants permission.

---

## 2. Material Changes since v1

This section documents substantive changes from the Canonical Contract System v1 to v2.

### 2.1 Removed

- **REQUIRE_TOKEN decision type.** The Decision enum in `enforcement.py` is a closed set of three values: ALLOW, DENY, REQUIRE_CONTRACT. REQUIRE_TOKEN was removed. Human-in-the-loop approval is provided by HAT through the extension sidebar, not through a decision type. REQUIRE_TOKEN is now a forbidden concept (see section 11) and will be added to arch-linter rules.

- **Semantic operation types reduced.** The Operation enum in contract declarations previously included 7 values (READ, WRITE, DELETE, RENAME, EXECUTE, DB_WRITE, GIT_WRITE). Enforcement has always recognized only three: READ, WRITE, DELETE. The extra values have been removed from `contract_v1.py`. The canonical set of contract operations is READ, WRITE, DELETE.

- **Symbols lock system.** A symbols lock was envisioned as part of Phase 1.5 to provide baseline/diff guarantees via snapshot comparison. The semantic validator provides this guarantee more effectively by analyzing changed files identified through git diff. The symbols lock module has been removed from canonical documentation.

- **Phantom root categories.** ROOT_WIP, ROOT_UTILITIES, and ROOT_LAUNCHER were referenced in v1 but never existed in the `RootCategory` enum. All references have been removed. WIP is a subdirectory of ROOT_CK3RAVEN_DATA. Utilities and launcher functionality are covered by existing roots.

### 2.2 Changed

- **NST reclassified as in-policy compliance verification.** NST is not an exception token. Creating new symbols that have been approved and agreed with the user is within policy. NST verifies that new symbol creation was intentional. LXE remains the sole exception token type.

- **NST is now ephemeral.** NST tokens are no longer persisted to git-tracked directories or subject to the propose-approve lifecycle. They are session-scoped, generated at contract close time, and consumed during audit. LXE remains persistent with the propose-approve lifecycle.

- **Decision Model uses Reply System.** Enforcement decisions (ALLOW, DENY, REQUIRE_CONTRACT) are internal. MCP tools surface all outcomes through the Reply System: S (Success) with info, or D (Deny) with info. REQUIRE_CONTRACT translates to D with an informational message. No MCP tool may emit REQUIRE_CONTRACT as a reply type.

- **HAT wording clarified.** HAT is not a policy exception token. HAT IS the policy for protected file operations and mode initialization. It represents direct human authorization, not an exception to a rule.

- **Protected files contract requirement.** To open a contract that addresses a protected file, a HAT is required. If HAT approval is not provided, the request to open the contract is invalid. The term "enforced" is not used for this mechanism — it is a precondition, not an enforcement action.

- **Phase 2 gate outcomes.** Gate outcomes use contract-aligned terminology: Success, Invalid, Deny. These are informational outcomes, not Decision enum values. See section on Phase 2 for details.

- **Direct DB mutation ban made explicit.** MCP tools are read-only clients. All database mutations flow through the QBuilder daemon per SINGLE_WRITER_ARCHITECTURE.md. This was implicit in v1; it is now explicit.

### 2.3 Added

- **Sigil cryptographic foundation.** HMAC-SHA256 signing primitive documented as a first-class component. Provides contract signing, HAT verification, and token signatures.

- **Contract signing.** Contracts are cryptographically signed at creation using Sigil. Unsigned or invalid-signature contracts are rejected at load time.

- **Protected files mechanism.** SHA256-hashed manifest protecting critical files with HAT-gated modification. Operates as an independent layer from the capability matrix.

- **Compliance tools user guide.** Canonical documentation of all Phase 1.5 compliance tools, their commands, schemas, and workflows.

---

## 3. Contracts

A contract is a declaration of intent and scope.

A contract must explicitly state:

- what will be done
- where it will occur
- which operations are permitted

No authority may be inferred from runtime state.

---

## 4. Zero Compatibility Rule

Legacy contracts are not supported.

Contracts containing deprecated or banned fields are invalid.

Examples of banned concepts include:

- semantic domains
- active mod authority
- inferred scope
- compatibility fallbacks

Legacy contracts may be archived but must not be executed.

---

## 5. Root Categories

Each contract operates in exactly one root category.

### 5.1 Canonical Roots

The following roots are defined in the `RootCategory` enum (`ck3lens/paths.py`):

| Root | Description |
|------|-------------|
| ROOT_REPO | ck3raven source repository |
| ROOT_CK3RAVEN_DATA | ck3raven data directory |
| ROOT_GAME | CK3 vanilla game installation |
| ROOT_STEAM | Steam Workshop mod directory |
| ROOT_USER_DOCS | CK3 user documents directory |
| ROOT_VSCODE | VS Code user settings and workspace configuration |
| ROOT_EXTERNAL | Catch-all for paths outside all known roots (always denied) |

### 5.2 Subdirectory-Aware Roots

Two roots use subdirectory-level capability resolution:

**ROOT_CK3RAVEN_DATA:**

| Subdirectory | Purpose | Notes |
|--------------|---------|-------|
| wip | Agent scratch workspace | Writable without contract |
| config | Workspace configuration | Writable |
| playsets | Playset definitions | Writable |
| logs | ck3raven component logs | Writable |
| journal | Session journal archives | Writable |
| cache | Cached data | Writable |
| artifacts | Compliance artifacts | Writable |
| db | SQLite database | Read-only (owned by QBuilder daemon) |
| daemon | Daemon state files | Read-only (owned by QBuilder daemon) |

**ROOT_USER_DOCS:**

| Subdirectory | Purpose | Notes |
|--------------|---------|-------|
| mod | Local mod directories | Subfolders writable (ck3lens mode only) |
| (base) | Launcher DB, saves, etc. | Read-only |

### 5.3 Rules

- one root per contract
- multi-root work requires multiple contracts
- root defines enforcement boundary

---

## 6. Contract Schema Version 1

A valid contract must include:

- contract identifier
- execution mode
- root category
- intent summary
- requested operations
- explicit targets
- work declaration
- author attribution

Unknown fields are forbidden in canonical contracts. The schema validator (`contract_v1.py`) is authoritative on rejection.

### 6.1 Contract Signing

Contracts are cryptographically signed at creation using Sigil (see section 17).

Signature payload: `HMAC-SHA256(CK3LENS_SIGIL_SECRET, contract_id|created_at)`

Verification occurs at load time. Invalid signatures reject the contract.

Implementation: `_contract_signing_payload()` and `_verify_contract_signature()` in `contract_v1.py`.

---

## 7. Operations

### 7.1 Contract Operations

The following operations may appear in contract declarations:

- READ
- WRITE
- DELETE

Note: The `Operation` enum in `contract_v1.py` currently contains vestigial values (RENAME, EXECUTE, DB_WRITE, GIT_WRITE) that enforcement does not recognize. These are scheduled for removal. See section 2.1.

### 7.2 Enforcement Operations

Enforcement evaluates three operation types (defined in `enforcement.py`):

| Enforcement Type | Covers | Requires Contract |
|-----------------|--------|-------------------|
| READ | Discovery and reading | No |
| WRITE | All mutations (write, rename, execute, git, db) | Yes |
| DELETE | File or resource deletion | Yes |

Note: WIP writes do not require a contract. This is evident from the capability matrix (section 13).

All mutating operations must be explicitly declared.

---

## 8. Targets

Targets define the visibility boundary.

Targets must:

- be relative to the root
- never escape containment
- never be inferred

Targets do not grant authority.

---

## 9. Work Declaration

Each contract must include a work declaration describing:

- planned changes (work_plan)
- intended approach (work_summary)
- excluded scope (out_of_scope)
- specific edits (edits[])

### 9.1 Enforcement Status

Work declarations are **audit artifacts, not enforcement gates.**

`enforcement.py` validates:

- mode and operation type
- root category containment
- active contract exists (for mutating operations)

`enforcement.py` does **not** validate:

- writes match `work_declaration.edits[]`
- actual files modified match declared targets
- symbol changes match symbol intent

This is a deliberate design choice for Phase 1. Phase 2 gates may optionally enforce edit-level matching. The gap is documented, not hidden.

### 9.2 Audit Role

Work declarations serve as:

- human-readable intent communication
- evidence for contract close audit (`audit_contract_close.py`)
- scope documentation for future review

The purpose is auditability, not instruction.

---

## 10. Symbol Intent

All new identifiers must be declared.

This includes:

- classes
- functions
- exported values
- CK3 script identifiers

Undeclared symbols require NST tokens (see section 16.2) for contract closure.

---

## 11. Forbidden Concepts

The following are permanently banned:

- semantic authorization
- launcher derived permission
- agent created allowlists
- silent rule suppression
- REQUIRE_TOKEN as a decision type (legacy architecture, will be added to arch-linter)
- direct DB mutation from MCP tools (daemon-only, per SINGLE_WRITER_ARCHITECTURE)
- vestigial semantic operations (RENAME, EXECUTE, DB_WRITE, GIT_WRITE) in enforcement — the canonical operations are READ, WRITE, DELETE

No component may reintroduce them.

---

## 12. Execution Modes

### ck3lens

- limited write authority
- may modify user mods (nested paths in ROOT_USER_DOCS/mod)
- must operate conservatively

### ck3raven-dev

- development mode
- write access to ROOT_REPO and ROOT_CK3RAVEN_DATA (except db/daemon)
- may not modify user mods or launcher state

Mode modifies capability, not geography.

---

## 13. Capability Matrix

Authorization is determined only by:

`(mode, root_category, subdirectory, operation)`

No other inputs are permitted.

### 13.1 Global Invariants

These override the matrix and are enforced in `enforcement.py`:

1. **Contract required** for all WRITE/DELETE operations outside of WIP
2. **db/ and daemon/** subdirectories are NEVER writable (owned by QBuilder daemon)
3. **ROOT_EXTERNAL** is always DENY for all operations

### 13.2 ck3lens Mode

Source of truth: `capability_matrix.py`

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
| ROOT_REPO | — | D | D | D | Not visible in ck3lens mode |
| ROOT_EXTERNAL | — | D | D | D | Always denied |

### 13.3 ck3raven-dev Mode

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

### 13.4 Canonical Authority

The capability matrix in `capability_matrix.py` is authoritative. If this document and the code diverge, the code governs and this document must be updated.

Phase 2 must not start until this document and the code are in agreement.

---

## 14. Enforcement Philosophy

All enforcement is deterministic.

Agents may not:

- self authorize
- reinterpret rules
- grant themselves exceptions

All deviations require explicit tokens (see section 16).

---

## 15. Protected Files

Certain critical files are protected by a SHA256-hashed manifest.

### 15.1 Mechanism

| Component | Location |
|-----------|----------|
| Manifest | `policy/protected_files.json` |
| Implementation | `tools/compliance/protected_files.py` |
| MCP tool | `ck3_protect(command="list\|verify\|add\|remove")` |

### 15.2 Contract Open Requirement

To open a contract that addresses a protected file, a HAT is required. If HAT approval is not provided, the request to open the contract is invalid.

Protected file checks also occur in the MCP tool layer before any write to a protected path. Both the capability matrix and the protected files manifest must pass for a write to succeed.

### 15.3 Relationship to Capability Matrix

- Capability matrix: geographic authorization (`mode + root + subdirectory` → `ALLOW/DENY`)
- Protected files: per-file authorization (`specific path` → `HAT required`)

These are complementary, not alternatives.

---

## 16. Token Architecture

Tokens authorize specific operations or exceptions. They are the mechanism for human-in-the-loop control.

### 16.1 HAT (Human Authorization Token)

HAT provides interactive human approval for:

- Mode initialization (agent startup)
- Protected file operations (manifest modifications)
- Contract open for protected paths

**Key properties:**

- Ephemeral: not persisted, no audit trail beyond logs
- Single-use: consumed on use, cannot be replayed
- Session-scoped: bound to current VS Code window
- Signed with Sigil (see section 17)

**Two delivery mechanisms:**

| Variant | Delivery | Consumption |
|---------|----------|-------------|
| HAT (init) | Sigil-signed inline token in chat prompt | `ck3_get_mode_instructions()` validates and consumes |
| HAT (protect) | Ephemeral approval file written by extension | `consume_hat_approval()` reads, validates, and deletes file |

**HAT init lifecycle:**

1. Extension generates Sigil-signed token at MCP spawn
2. User clicks "Initialize Agent" in VS Code sidebar
3. Token is injected into chat prompt (user authorization act)
4. Agent passes token to `ck3_get_mode_instructions(mode="...", hat_token="...")`
5. Server validates Sigil signature and 5-minute expiry, then consumes

**HAT is not a policy exception token. HAT IS the policy.** It represents direct human authorization for operations that require it.

### 16.2 NST (New Symbol Token) — In-Policy Compliance Verification

NST is **not an exception token**. Creating new symbols that have been approved and agreed with the user is **within policy**. NST declares intentionally new identifiers introduced during a contract, verifying that this in-policy action occurred deliberately.

**Key properties:**

- Ephemeral: session-scoped, not persisted to git-tracked directories
- Generated at contract close time
- Consumed during the close audit pipeline
- Covers all new symbols detected in git diff
- TTL: 24 hours (session-bound, typically consumed immediately)

**When required:**

The semantic validator identifies new symbols in changed files via git diff. If new symbols are found, NST coverage is required for contract closure. Uncovered new symbols block closure.

### 16.3 LXE (Lint Exception Token) — Persistent

LXE grants temporary exceptions to lint rule violations.

**Key properties:**

- Persistent: git-tracked, reviewable
- Contract-bound: tied to a specific contract
- Scope-bound: declares specific rule codes
- Non-transferable
- TTL: 8 hours

**Lifecycle:**

1. **Proposed:** Agent creates token at `artifacts/tokens_proposed/<id>.token.json`
2. **Approved:** Human moves to `policy/tokens/<id>.token.json`
3. **Rejected:** Human deletes proposed token
4. **Expired:** Status changes after `expires_at` timestamp

**Token schema:**

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

### 16.4 Validation at Contract Close

Token validation during contract close audit:

1. **NST:** All new symbols detected in git diff must be covered. Ephemeral NST is generated and validated within the same audit pass.
2. **LXE:** Signature integrity check, status must be `"approved"`, scope must match actual violations, and token must not be expired.

See the Contract Close Audit Pipeline section for the full close sequence.

### 16.5 Implementation

| Component | Location |
|-----------|----------|
| Token types and lifecycle | `tools/compliance/tokens.py` |
| Approved LXE tokens | `policy/tokens/<id>.token.json` |
| Proposed LXE tokens | `artifacts/tokens_proposed/<id>.token.json` |
| Sigil signing | `tools/compliance/sigil.py` |

---

## 17. Sigil: Cryptographic Foundation

Sigil is the canonical HMAC-SHA256 signing primitive used throughout the contract system.

### 17.1 Purpose

Sigil provides:

- HAT token signing and verification
- Contract signing at creation
- LXE token signature verification

### 17.2 Implementation

| Component | Location |
|-----------|----------|
| Functions | `sigil_sign()`, `sigil_verify()`, `sigil_available()` |
| Module | `tools/compliance/sigil.py` |
| Secret | `CK3LENS_SIGIL_SECRET` environment variable |
| Full specification | `docs/SIGIL_ARCHITECTURE.md` (28 invariants) |

### 17.3 Key Properties

- HMAC-SHA256 using shared secret
- Secret provided by extension at MCP spawn
- If secret unavailable, `sigil_available()` returns False
- All signing operations fail safe (deny) when secret missing

---

# PHASE MODEL

---

## Phase 1: Contract Law

Phase 1 defines the legal structure of the system.

It establishes:

- contract schema
- root categories
- capability matrix
- forbidden concepts
- zero compatibility rule

Phase 1 defines what may occur.

---

## Phase 1.5: Deterministic Evidence and Symbol Control

Phase 1.5 establishes trust in compliance claims.

No mutation is valid without verifiable evidence.

### Properties Introduced

1. **Locked rulebooks**

Static analysis configurations are content-hashed. Outputs must declare the rule hash used. Mismatched hashes invalidate the result.

2. **Symbol change detection**

New symbols are detected via git diff and the semantic validator. Symbol existence is determined by analyzing changed files, not by snapshot comparison.

3. **Tokenized compliance and exceptions**

Two token types exist with distinct roles:

- NST: New Symbol Token — in-policy compliance verification (ephemeral)
- LXE: Lint Exception Token — exception from lint requirements (persistent)

Tokens are contract-bound, scope-bound, and non-transferable. No blanket exceptions exist.

4. **Compliance evidence**

All write activity must produce artifacts proving:

- rules applied (watermarked lint reports)
- symbols changed (semantic validator output)
- exceptions exercised (approved tokens)

Absence of evidence constitutes failure.

---

## Phase 2: Deterministic Gates (Future)

Phase 2 will introduce contract open-time gates.

**These are not yet implemented. The following describes intended behavior.**

Gates:

- evaluate declared scope only
- do not mutate
- do not execute
- do not interpret semantics

Gate outcomes are informational messages aligned with contract terminology:

| Outcome | Meaning | Example |
|---------|---------|---------|
| Success | Contract opens | "Contract opened" |
| Invalid | Request is malformed or incomplete | "Contracts involving write operations must include target files" |
| Deny | Capability matrix rejects the operation | "Write operation to ROOT_STEAM not within capability of ck3raven-dev" |

These outcomes are not Decision enum values. They are informational results of gate evaluation.

### Phase 2 Prerequisites

The following must be complete before Phase 2 work begins:

1. **Capability matrix alignment:** Section 13 must match `capability_matrix.py` (verified)
2. **Audit pipeline update:** `audit_contract_close.py` must use `semantic_validator` directly for symbol change detection
3. **Pre-commit hook:** Install via `tools/compliance/install_hooks.py`

### Phase 2 Deliverables

- `contract_gates.py`: Open-time gate evaluation
- `close_gates.py`: Close-time gate evaluation

---

## Phase 3: Execution Enforcement (Future)

Phase 3 will bind:

- contracts
- evidence artifacts
- symbol deltas
- exception tokens

into a single execution boundary.

---

## 18. Safety Rule

If legality cannot be determined with certainty:

- stop
- report
- await instruction

Speculation is forbidden.

---

## 19. Final Principle

Determinism over speed.  
Authority over inference.  
Evidence over assertion.

---

# COMPLIANCE TOOLS USER GUIDE

> **Status:** CANONICAL  
> **Updated:** February 11, 2026  
> **Audience:** Agents operating in ck3raven-dev or ck3lens modes  
> **Authority:** Phase 1.5 Deterministic Evidence Infrastructure

---

## Overview

This section documents the compliance tools that support Phase 1.5 deterministic evidence.

All tools are located in `tools/compliance/`.

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

## Directory Structure

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

## Tool 1: Linter Lock (`linter_lock.py`)

### Purpose

Hash-locks the arch_lint ruleset to ensure deterministic lint behavior.
Changes to lint rules must be explicitly proposed and approved.

### Scope

Only `tools/arch_lint/*.py` and `tools/arch_lint/requirements.txt` are locked.
Ruff is explicitly out of scope for Phase 1.5.

### Commands

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

### Workflow: Agent Modifies arch_lint

1. Agent modifies files in `tools/arch_lint/`
2. Agent calls `create_proposed_lock()` — writes to `artifacts/locks/proposed/`
3. `verify_lock()` now FAILS (working tree differs from active lock)
4. Human reviews diff via `diff` command
5. Human either:
   - **Approves:** Copies `artifacts/locks/proposed/linter.lock.json` to `policy/locks/linter.lock.json`
   - **Rejects:** Deletes proposed lock, agent reverts changes
6. After promotion, `verify_lock()` passes again

### Lock File Schema

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

## Tool 2: Locked Lint Runner (`run_arch_lint_locked.py`)

### Purpose

Wrapper that:
1. Verifies the linter lock FIRST
2. Runs arch_lint
3. Stamps output with cryptographic watermark

### Usage

```bash
python -m tools.compliance.run_arch_lint_locked <contract_id> [arch_lint args...]
```

### Output

Creates two files in `artifacts/lint/`:

| File | Format | Purpose |
|------|--------|---------|
| `<contract_id>.arch_lint.json` | JSON | Structured report for programmatic use |
| `<contract_id>.arch_lint.txt` | Text | Human-readable report |

### Watermark

Every report includes a cryptographic watermark:

```
WATERMARK: lock=8454fe20a5d0eb3e... alg=sha256 ts=2026-01-20T08:08:01+00:00
```

This watermark proves which linter version produced the output.

---

## Tool 3: Semantic Validator (`semantic_validator.py`)

### Purpose

Evidence generator for contract close audit. Analyzes files changed during a contract to detect new symbol definitions and unresolved references.

**The semantic validator is a SENSOR, not a JUDGE.** It observes reality and emits evidence. All enforcement decisions occur during contract audit and closure.

### Dual-Path Analysis

| File Type | Parser Used | Detects |
|-----------|-------------|---------|
| Python (`.py`) | Python `ast` module | Classes, functions, imports, references |
| CK3 script (`.txt`) | `ck3raven.parser.parse_source()` | Events, traits, decisions, scripted effects |

### Output Schema

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

### Symbol Change Detection

The semantic validator provides the symbol change detection guarantee:

| Guarantee | How Provided |
|-----------|-------------|
| **Baseline** | Git diff of contract branch vs base commit identifies changed files |
| **Diff** | Semantic validator analyzes changed files, extracts `definitions_added` |
| **Coverage requirement** | NST tokens must cover all new definitions found |
| **Evidence artifact** | `SemanticReport` saved as JSON artifact for audit trail |

Git diff is the source of truth for what changed; the semantic validator extracts structured meaning from those changes.

### Usage

```bash
python -m tools.compliance.semantic_validator file1.py file2.txt --out report.json
python -m tools.compliance.semantic_validator --files-from manifest.txt --out report.json
```

### Integration with Contract Close

`audit_contract_close.py` calls `check_symbols_diff()` which:

1. Gets list of changed files from git diff
2. Runs semantic validator on each changed file
3. Collects all `definitions_added`
4. Checks that NST tokens cover all new definitions
5. Returns pass/fail with evidence

---

## Tool 4: Token Registry (`tokens.py`)

### Purpose

Manages the full lifecycle of NST, LXE, and HAT tokens.

### Key Functions

| Function | Purpose |
|----------|---------|
| `propose_lxe()` | Create proposed LXE token |
| `validate_token()` | Verify signature and status |
| `save_proposed_token()` | Write to `artifacts/tokens_proposed/` |
| `write_hat_request()` | Write HAT request for extension approval |
| `consume_hat_approval()` | Consume ephemeral HAT approval file |

### Token Directories

| Directory | Purpose | Git-Tracked |
|-----------|---------|-------------|
| `policy/tokens/` | Human-approved LXE tokens | Yes |
| `artifacts/tokens_proposed/` | Agent-created LXE proposals | Yes |

---

## Tool 5: Protected Files (`protected_files.py`)

### Purpose

SHA256-hashed manifest protecting critical files from unauthorized modification.

### Key Functions

| Function | Purpose |
|----------|---------|
| `load_manifest()` | Load protected files list |
| `save_manifest()` | Save updated manifest |
| `is_protected()` | Check if a path is protected |
| `verify_all_hashes()` | Verify SHA256 integrity of all protected files |
| `check_edits_against_manifest()` | Check if proposed edits touch protected files |

---

## Contract Close Audit Pipeline

### Purpose

`audit_contract_close.py` implements a 6-check pipeline that validates all contract work before closure.

### Pipeline

| Step | Function | Validates |
|------|----------|-----------|
| 1 | `check_linter_lock()` | arch_lint rules unchanged during contract |
| 2 | `check_arch_lint()` | Watermarked lint passes on changed files |
| 3 | `check_playset_drift()` | Playset hasn't changed during contract |
| 4 | `check_symbols_diff()` | New symbols detected via git diff + semantic validator |
| 5 | `validate_nst_tokens()` | NST tokens cover all new symbols |
| 6 | `validate_lxe_tokens()` | Approved LXE tokens cover all lint exceptions |

### Close Flow

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

## Phase 1.5 Component Status

| Component | Status | Description |
|-----------|--------|-------------|
| A. Linter Lock | Complete | `linter_lock.py` — immutable arch_lint rules |
| B. Scoped Lint | Complete | `run_arch_lint_locked.py` — watermarked lint with lock verification |
| C. Semantic Validator | Complete | `semantic_validator.py` — git-diff-based symbol change detection |
| D. Token Registry | Complete | `tokens.py` — NST, LXE, HAT lifecycle management |
| E. Protected Files | Complete | `protected_files.py` + `policy/protected_files.json` |
| F. Sigil Crypto | Complete | `sigil.py` + `SIGIL_ARCHITECTURE.md` |
| G. Contract Close Audit | Complete | `audit_contract_close.py` — 6-check pipeline |

---

## Prohibited Actions

Agents MUST NOT:

1. Write directly to `policy/locks/` (human approval required)
2. Delete or modify the active linter lock
3. Skip lock verification before lint runs
4. Close contracts with unverified lint evidence
5. Introduce undeclared new symbols without NST tokens
6. Write to protected files without HAT approval
7. Execute direct DB mutations in MCP tools (daemon-only)

---

## Canonical Locations

| Artifact | Location | Git-Tracked |
|----------|----------|-------------|
| Active linter lock | `policy/locks/linter.lock.json` | Yes |
| Proposed linter lock | `artifacts/locks/proposed/linter.lock.json` | Yes |
| Lint reports | `artifacts/lint/<contract_id>.arch_lint.json` | Yes |
| Protected files manifest | `policy/protected_files.json` | Yes |
| Approved LXE tokens | `policy/tokens/<id>.token.json` | Yes |
| Proposed LXE tokens | `artifacts/tokens_proposed/<id>.token.json` | Yes |

---

## References

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

Running arch_lint v2.35 against the codebase revealed **510 real violations**.
Analysis confirmed ~99% are legitimate architectural issues.

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
