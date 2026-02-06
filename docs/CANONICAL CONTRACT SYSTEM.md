# CANONICAL CONTRACT SYSTEM

Status: CANONICAL  
Applies to: ck3raven-dev, ck3lens  
Authority Level: HARD LAW

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

### Geographic Authority Principle

All authorization is derived solely from filesystem geography.

Authority is determined by:

- root category
- execution mode
- requested operation
- capability matrix

Semantic meaning is irrelevant.

Conceptual relationships are irrelevant.

Only physical path containment matters.

---

## 1.1 Visibility Versus Authority

Visibility and authority are not equivalent.

- visibility defines what may be discovered
- authority defines what may be modified

Discovery never grants permission.

---

## 2. Contracts

A contract is a declaration of intent and scope.

A contract must explicitly state:

- what will be done
- where it will occur
- which operations are permitted

No authority may be inferred from runtime state.

---

## 3. Zero Compatibility Rule

Legacy contracts are not supported.

Contracts containing deprecated or banned fields are invalid.

Examples of banned concepts include:

- semantic domains
- active mod authority
- inferred scope
- compatibility fallbacks

Legacy contracts may be archived but must not be executed.

---

## 4. Root Categories

Each contract operates in exactly one root category.

Defined roots:

- ROOT_REPO
- ROOT_USER_DOCS
- ROOT_WIP
- ROOT_STEAM
- ROOT_GAME
- ROOT_UTILITIES
- ROOT_LAUNCHER

Rules:

- one root per contract
- multi-root work requires multiple contracts
- root defines enforcement boundary

---

## 5. Contract Schema Version 1

A valid contract must include:

- contract identifier
- execution mode
- root category
- intent summary
- requested operations
- explicit targets
- work declaration
- author attribution

Unknown fields invalidate the contract.

---

## 6. Operations

Allowed operations:

- READ
- WRITE
- DELETE
- RENAME
- EXECUTE
- DB_WRITE
- GIT_WRITE

All mutating operations must be explicitly declared.

---

## 7. Targets

Targets define the visibility boundary.

Targets must:

- be relative to the root
- never escape containment
- never be inferred

Targets do not grant authority.

---

## 8. Work Declaration

Each contract must include a work declaration describing:

- planned changes
- intended approach
- excluded scope
- symbol intent

The purpose is auditability, not instruction.

---

## 9. Symbol Intent

All new identifiers must be declared.

This includes:

- classes
- functions
- exported values
- CK3 script identifiers

Undeclared symbols are violations.

---

## 10. Forbidden Concepts

The following are permanently banned:

- semantic authorization
- launcher derived permission
- agent created allowlists
- silent rule suppression

No component may reintroduce them.

---

## 11. Execution Modes

### ck3lens

- limited write authority
- may modify user mods and launcher data
- must operate conservatively

### ck3raven-dev

- development mode
- write access limited to repository and sandbox
- may not modify user mods or launcher state

Mode modifies capability, not geography.

---

## 12. Capability Matrix

Authorization is determined only by:

(mode, root_category, operation)

No other inputs are permitted.

The capability matrix defines, for each combination of:

- mode (ck3lens or ck3raven-dev)
- root category (ROOT_*)
- operation (READ, WRITE, DELETE, RENAME, EXECUTE, DB_WRITE, GIT_WRITE)

whether the operation is permitted.

### 12.1 Capability Levels

This document uses the following capability levels:

- ALLOW: permitted without additional approval
- DENY: forbidden regardless of contract intent

If a requested operation is DENY for the given (mode, root_category), the contract is invalid.

### 12.2 Canonical Capability Matrix

Key:
- A = ALLOW
- D = DENY

Operations:
- R = READ
- W = WRITE
- Del = DELETE
- Ren = RENAME
- X = EXECUTE
- DB = DB_WRITE
- Git = GIT_WRITE

Mode: ck3lens

| Root           | R | W | Del | Ren | X | DB | Git |
|----------------|---|---|-----|-----|---|----|-----|
| ROOT_REPO      | A | D | D   | D   | D | D  | D   |
| ROOT_USER_DOCS | A | A | A   | A   | D | D  | D   |
| ROOT_WIP       | A | A | A   | A   | D | D  | D   |
| ROOT_STEAM     | A | D | D   | D   | D | D  | D   |
| ROOT_GAME      | A | D | D   | D   | D | D  | D   |
| ROOT_UTILITIES | A | D | D   | D   | D | D  | D   |
| ROOT_LAUNCHER  | A | A | A   | A   | D | D  | D   |

Mode: ck3raven-dev

| Root           | R | W | Del | Ren | X | DB | Git |
|----------------|---|---|-----|-----|---|----|-----|
| ROOT_REPO      | A | A | A   | A   | A | A  | A   |
| ROOT_USER_DOCS | A | D | D   | D   | D | D  | D   |
| ROOT_WIP       | A | A | A   | A   | A | A  | A   |
| ROOT_STEAM     | A | D | D   | D   | D | D  | D   |
| ROOT_GAME      | A | D | D   | D   | D | D  | D   |
| ROOT_UTILITIES | A | D | D   | D   | D | D  | D   |
| ROOT_LAUNCHER  | A | D | D   | D   | D | D  | D   |

Notes:

- ROOT_STEAM and ROOT_GAME are read-only in all modes.
- ROOT_UTILITIES is read-only in all modes.
- ck3lens may mutate ROOT_LAUNCHER only for repair of launcher registry.
- ck3raven-dev has read access to all roots but write authority only in ROOT_REPO and ROOT_WIP.

---

## 13. Enforcement Philosophy

All enforcement is deterministic.

Agents may not:

- self authorize
- reinterpret rules
- grant themselves exceptions

All deviations require explicit tokens.

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

Phase 1.5 strengthens enforcement readiness.

### Properties introduced

1. Locked rulebooks

Static analysis configurations are content hashed.

Outputs must declare the rule hash used.

Mismatched hashes invalidate the result.

2. Symbol inventories

Authoritative symbol indexes exist for:

- ck3raven source symbols
- ck3lens CK3 script symbols

Symbol existence is no longer subjective.

3. Tokenized exceptions

Two exception tokens exist:

- NST: New Symbol Token
- LXE: Lint Exception Token

Tokens are:

- contract bound
- scope bound
- non transferable

No blanket exceptions exist.

4. Compliance evidence

All write activity must produce artifacts proving:

- rules applied
- symbols changed
- exceptions exercised

Absence of evidence constitutes failure.

---

## Phase 2: Deterministic Gates

Phase 2 introduces contract open time gates.

Gates:

- evaluate declared scope only
- do not mutate
- do not execute
- do not interpret semantics

Gate outcomes:

- AUTO_APPROVE
- REQUIRE_APPROVAL
- AUTO_DENY

---

## Phase 3: Execution Enforcement

Phase 3 binds:

- contracts
- evidence artifacts
- symbol deltas
- exception tokens

into a single execution boundary.

---

## 14. Safety Rule

If legality cannot be determined with certainty:

- stop
- report
- await instruction

Speculation is forbidden.

---

## 15. Final Principle

Determinism over speed.  
Authority over inference.  
Evidence over assertion.

---

# COMPLIANCE TOOLS USER GUIDE

> **Status:** CANONICAL  
> **Added:** January 20, 2026  
> **Audience:** Agents operating in ck3raven-dev or ck3lens modes  
> **Authority:** Phase 1.5 Deterministic Evidence Infrastructure

---

## Overview

This section documents the compliance tools that support Phase 1.5 deterministic evidence.

All tools are located in `tools/compliance/`.

| Tool | Purpose |
|------|---------|
| `linter_lock.py` | Hash-lock arch_lint ruleset |
| `run_arch_lint_locked.py` | Run arch_lint with lock verification and watermarking |
| `symbols_lock.py` | Playset-scoped symbol snapshots and comparison |

---

## Directory Structure

```
ck3raven/
├── policy/
│   └── locks/
│       └── linter.lock.json         # THE active approved linter lock
│
├── artifacts/
│   ├── locks/
│   │   └── proposed/
│   │       └── linter.lock.json     # Agent-proposed lock (pending approval)
│   ├── lint/
│   │   └── <contract_id>.arch_lint.json    # Watermarked lint reports
│   │   └── <contract_id>.arch_lint.txt
│   └── symbols/
│       └── <snapshot_id>.symbols.json      # Symbol snapshots
│
└── tools/
    └── compliance/
        ├── __init__.py
        ├── linter_lock.py
        ├── run_arch_lint_locked.py
        └── symbols_lock.py
```

---

## Tool 1: Linter Lock (`linter_lock.py`)

### Purpose

Hash-locks the arch_lint ruleset to ensure deterministic lint behavior.
Changes to lint rules must be explicitly proposed and approved.

### Scope

Only `tools/arch_lint/*.py` and `tools/arch_lint/requirements.txt` are locked.
Ruff is explicitly OUT of scope for Phase 1.5.

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

### Key Functions

| Function | Purpose |
|----------|---------|
| `create_lock()` | Create lock from current arch_lint files |
| `verify_lock()` | Verify working tree matches stored lock |
| `create_proposed_lock()` | Create proposed lock at `artifacts/locks/proposed/` |
| `diff_lock()` | Compute diff between active and proposed locks |
| `check_closure_eligibility()` | Returns `(eligible, reason)` tuple |

### Workflow: Agent Modifies arch_lint

1. Agent modifies files in `tools/arch_lint/`
2. Agent calls `create_proposed_lock()` → writes to `artifacts/locks/proposed/`
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

### Verification Output

```
Verifying linter lock...
Lock verified: 8454fe20a5d0eb3e...
```

Or if tampered:

```
Verifying linter lock...
Lock verification FAILED: 1 file(s) modified, hash mismatch

Modified files:
  tools/arch_lint/config.py
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

### Example

```bash
python -m tools.compliance.run_arch_lint_locked v1-2026-01-20-abc123
```

### Output

Creates two files in `artifacts/lint/`:

| File | Format | Purpose |
|------|--------|---------|
| `<contract_id>.arch_lint.json` | JSON | Structured report for programmatic use |
| `<contract_id>.arch_lint.txt` | Text | Human-readable report |

### Report Fields

| Field | Description |
|-------|-------------|
| `contract_id` | Associated contract |
| `lock_hash` | Hash of verified linter lock (full 64 chars) |
| `lock_verified` | Boolean, always `true` (fails otherwise) |
| `timestamp` | ISO-8601 UTC timestamp |
| `hash_algorithm` | Always `sha256` |
| `tool_path` | `tools/arch_lint` |
| `tool_version` | Extracted from arch_lint config |
| `exit_code` | arch_lint exit code |
| `stdout` | Full stdout output |
| `stderr` | Full stderr output |
| `error_count` | Number of errors detected |
| `warning_count` | Number of warnings detected |

### Watermark

Every report includes a cryptographic watermark:

```
WATERMARK: lock=8454fe20a5d0eb3e... alg=sha256 ts=2026-01-20T08:08:01+00:00
```

This watermark proves which linter version produced the output.

### Failure Modes

If lock verification fails, the wrapper exits immediately:

```
Running locked arch_lint for contract: test-001

FAILED: Lock verification failed: Lock verification FAILED: 1 file(s) modified
```

---

## Tool 3: Symbols Lock (`symbols_lock.py`)

### Purpose

Playset-scoped symbol snapshot and comparison system.
Detects new symbols added during a contract session.

### Key Properties

| Property | Value |
|----------|-------|
| Scope | Playset-scoped (filters by active CVIDs) |
| Detection | New symbols only (not full regeneration) |
| Source tagging | None (vanilla/mod/workshop already in DB) |

### Commands

```bash
# Show current symbol counts
python -m tools.compliance.symbols_lock status

# Create snapshot for contract
python -m tools.compliance.symbols_lock snapshot <contract_id>

# Compare two snapshots
python -m tools.compliance.symbols_lock diff <baseline_path> <current_path>

# Check for new symbols since baseline
python -m tools.compliance.symbols_lock check-new <baseline_path>
```

### Workflow: Contract Symbol Audit

1. At contract open: `snapshot <contract_id>` → creates baseline
2. Agent performs work
3. At closure audit: `check-new <baseline_path>` → detects new symbols
4. If new symbols found:
   - Agent must declare them via NST token (Phase 1.5 C)
   - Or closure is blocked

### Example: Create Snapshot

```bash
$ python -m tools.compliance.symbols_lock snapshot v1-2026-01-20-test

Creating symbols snapshot for contract: v1-2026-01-20-test
Snapshot created: artifacts/symbols/v1-2026-01-20-test_2026-01-20T08-13-51.symbols.json
  Symbols: 145542
  CVIDs: 123
  Hash: 0ff658e89a79e484...

Symbol counts by type:
  event: 31648
  definition: 28713
  script_value: 13031
  modifier: 11212
  ...
```

### Example: Check for New Symbols

```bash
$ python -m tools.compliance.symbols_lock check-new artifacts/symbols/baseline.json

No new symbols detected.
Baseline hash: 0ff658e89a79e484...
Current hash:  0ff658e89a79e484...
```

Or if new symbols exist:

```bash
$ python -m tools.compliance.symbols_lock check-new artifacts/symbols/baseline.json

NEW SYMBOLS DETECTED: 7

New symbols by type:
  + class: 2
  + function: 5

New symbols:
  + class:LinterLock in tools/compliance/linter_lock.py
  + class:LockedFile in tools/compliance/linter_lock.py
  + function:create_lock in tools/compliance/linter_lock.py
  + function:verify_lock in tools/compliance/linter_lock.py
  ...
```

### Snapshot Schema

```json
{
  "snapshot_id": "<contract_id>_<timestamp>",
  "contract_id": "...",
  "playset_name": "...",
  "created_at": "ISO-8601",
  "cvid_count": 123,
  "symbol_count": 145542,
  "snapshot_hash": "<sha256>",
  "symbols_by_type": {"event": 31648, "definition": 28713, ...},
  "symbols": [...]
}
```

### Key Functions

| Function | Purpose |
|----------|---------|
| `create_symbols_snapshot(contract_id)` | Create playset-scoped snapshot |
| `diff_symbols(baseline, current)` | Compute added/removed symbols |
| `check_new_symbols(baseline_path)` | Returns `(has_new, diff)` tuple |
| `query_symbols(cvids)` | Query symbols filtered by content version IDs |
| `compute_snapshot_hash(symbols)` | Deterministic hash for comparison |

---

## Integration with Contracts

### At Contract Open

```python
# Take baseline symbol snapshot
from tools.compliance.symbols_lock import create_symbols_snapshot

snapshot = create_symbols_snapshot(contract_id)
snapshot.save()  # → artifacts/symbols/<id>.symbols.json
```

### At Contract Close (Audit)

```python
from tools.compliance.linter_lock import check_closure_eligibility
from tools.compliance.symbols_lock import check_new_symbols
from tools.compliance.run_arch_lint_locked import run_arch_lint_locked

# 1. Check linter lock state
eligible, reason = check_closure_eligibility()
if not eligible:
    raise AuditError(f"Linter lock: {reason}")

# 2. Run watermarked lint
report = run_arch_lint_locked(contract_id)
if report.exit_code != 0:
    raise AuditError(f"Lint failed with {report.error_count} errors")

# 3. Check for new symbols
has_new, diff = check_new_symbols(baseline_snapshot_path)
if has_new:
    # Require NST tokens for new symbols
    raise AuditError(f"New symbols detected: {diff.added_count}")

# All checks pass → closure allowed
```

---

## Canonical Locations

| Artifact | Location | Git-Tracked |
|----------|----------|-------------|
| Active linter lock | `policy/locks/linter.lock.json` | Yes |
| Proposed linter lock | `artifacts/locks/proposed/linter.lock.json` | Yes |
| Lint reports | `artifacts/lint/<contract_id>.arch_lint.json` | Yes |
| Symbol snapshots | `artifacts/symbols/<id>.symbols.json` | Yes |

---

## Prohibited Actions

Agents MUST NOT:

1. Write directly to `policy/locks/` (human approval required)
2. Delete or modify the active linter lock
3. Skip lock verification before lint runs
4. Close contracts with unverified lint evidence
5. Introduce undeclared new symbols

---

## Phase 1.5 Component Status

| Component | Status | Description |
|-----------|--------|-------------|
| A. Linter Lock | ✅ Complete | `tools/compliance/linter_lock.py` - immutable arch_lint rules |
| B. Symbols Lock | ✅ Complete | `tools/compliance/symbols_lock.py` - symbol change tracking |
| C. Token Registry | ⚠️ Partial | Validation stubs exist, creation tools missing |
| D. Scoped Lint | ✅ Complete | `run_arch_lint_locked.py` - base_commit + git diff scoping |

---

## Phase 1.5C: Token Registry Specification

### Purpose

Tokens are signed declarations that explicitly authorize exceptions to normal rules.
They are the **only** mechanism for:

1. **NST (New Symbol Token)**: Declaring intentionally new identifiers
2. **LXE (Lint Exception Token)**: Granting temporary lint rule exceptions
3. **MIT (Mode Initialization Token)**: Authorizing agent switch to ck3raven-dev mode

### Token Schema

```json
{
  "schema_version": "v1",
  "token_type": "NST" | "LXE",
  "token_id": "<uuid4>",
  "contract_id": "<parent-contract>",
  "created_at": "ISO-8601",
  "expires_at": "ISO-8601",
  "status": "proposed" | "approved" | "rejected" | "expired",
  "justification": "<human-readable reason>",
  "scope": {
    "root_category": "ROOT_REPO" | "ROOT_USER_DOCS" | ...,
    "target_paths": ["relative/path/..."],
    "symbol_names": ["for NST only"]
  },
  "signature": "<hmac-sha256 of canonical JSON>"
}
```

### Token Lifecycle

```
Agent proposes → Human approves/rejects → Token valid during TTL → Auto-expires
```

1. **Proposed**: Agent creates token at `artifacts/tokens_proposed/<id>.token.json`
2. **Approved**: Human moves to `policy/tokens/<id>.token.json`
3. **Rejected**: Human deletes proposed token
4. **Expired**: Status changes after `expires_at` timestamp

### NST (New Symbol Token)

Required when introducing new:
- Python classes, functions, module-level constants
- CK3 script identifiers (traits, events, decisions)
- Any exported symbol not in baseline snapshot

**Proposal Requirements:**
```python
{
    "token_type": "NST",
    "scope": {
        "symbol_names": ["MyNewClass", "my_new_function"],
        "target_paths": ["tools/ck3lens_mcp/ck3lens/new_module.py"]
    },
    "justification": "Adding new capability for X feature"
}
```

### LXE (Lint Exception Token)

Required when:
- An arch_lint rule must be temporarily bypassed
- The violation is intentional and documented
- A proper fix is not feasible in current scope

**Proposal Requirements:**
```python
{
    "token_type": "LXE",
    "scope": {
        "target_paths": ["path/to/file.py"],
        "rule_codes": ["ORACLE-01", "TRUTH-01"]
    },
    "justification": "Legacy code being phased out in Phase 2",
    "max_violations": 5  # Optional cap
}
```

### MIT (Mode Initialization Token)

MIT tokens are fundamentally different from NST/LXE - they authorize agent initialization, not contract exceptions.

**Purpose:** Prevent agent self-initialization. User must click "Initialize Agent" to authorize.

**Lifecycle (different from NST/LXE):**
1. Extension generates token at MCP spawn, passes via env var `CK3LENS_MIT_TOKEN`
2. User clicks "Initialize Agent" in VS Code sidebar (selects mode)
3. Token is injected into chat (user authorization act)
4. Agent passes token to `ck3_get_mode_instructions(mode="...", mit_token="...")`
5. Server validates and **consumes** token (single-use)

**Key Properties:**
- **Single-use**: Token is invalidated after successful initialization
- **User-initiated**: Agent cannot retrieve or generate tokens
- **Session-scoped**: New token generated each VS Code window
- **Required for ALL modes**: Both ck3lens and ck3raven-dev require MIT
- **Not a contract exception**: MIT authorizes initialization, not rule-breaking

### Token Validation at Contract Close

```python
from tools.compliance.audit_contract_close import validate_tokens

# At closure, all NST/LXE tokens are validated:
# 1. Signature integrity check
# 2. Status == "approved" (not proposed/rejected/expired)
# 3. Scope matches actual changes
# 4. NST covers all new symbols in diff
# 5. LXE covers all lint exceptions claimed
```

### Implementation Requirements

**Files to create:**
1. `tools/compliance/tokens.py` - Token creation and validation
2. `policy/tokens/` - Directory for approved tokens (git-tracked)
3. `artifacts/tokens_proposed/` - Directory for proposed tokens

**Key Functions:**
| Function | Purpose |
|----------|---------|
| `propose_nst()` | Create proposed NST token |
| `propose_lxe()` | Create proposed LXE token |
| `validate_token()` | Verify signature and status |
| `check_nst_coverage()` | Verify all new symbols covered |
| `check_lxe_coverage()` | Verify all exceptions covered |

---

## Phase 1.5 Trailing Work

### Remaining Implementation Tasks

1. **Create `tools/compliance/tokens.py`**
   - Token schema validation
   - HMAC signature generation/verification
   - NST/LXE proposal functions
   - Coverage verification for contract close

2. **Create Token Directories**
   - `policy/tokens/` (human-approved, git-tracked)
   - `artifacts/tokens_proposed/` (agent-created, git-tracked)

3. **Update `audit_contract_close.py`**
   - Integrate token validation into closure gate
   - Verify NST covers all new symbols in `symbols_lock` diff
   - Verify LXE covers all claimed lint exceptions

4. **Fix Error Count Parsing**
   - `run_arch_lint_locked.py` parses `[ERROR]` but arch_lint outputs `ERROR `
   - Fix to parse summary line: `Errors: N  Warnings: M`

### Verification Criteria

Phase 1.5C is complete when:
- [ ] Token proposal CLI works: `python -m tools.compliance.tokens propose-nst ...`
- [ ] Token validation works: `python -m tools.compliance.tokens validate <id>`
- [ ] Contract close rejects missing NST for new symbols
- [ ] Contract close rejects missing LXE for lint exceptions
- [ ] End-to-end test passes with real token workflow

---

## Strategic Analysis: Architectural Debt

### Problem Summary

Running arch_lint v2.35 against recent changes revealed **510 real violations**.
Analysis confirms ~99% are legitimate architectural issues, not linter bugs.

### Primary Violation Categories

| Category | Count (est.) | Root Cause |
|----------|-------------|------------|
| Path classification duplication | ~200 | `ck3lens_rules.py` duplicates WorldAdapter |
| Oracle patterns | ~150 | `allowed_*`, `is_*` checks scattered |
| Banned terminology | ~80 | "local mod" vs ROOT_USER_DOCS |
| SQL mutations outside builder | ~30 | Direct DELETE/INSERT in MCP tools |
| Mode-specific types | ~20 | `CK3LensTokenType` should be unified |
| Legacy compatibility code | ~30 | Dead code paths for old formats |

### Specific Files Requiring Refactor

**1. `ck3lens_rules.py` (800 lines)**

Lines 105-170: `classify_path_domain()` - This entire function should not exist.
Path classification is WorldAdapter's job per CANONICAL_ARCHITECTURE.md Section 2.

Lines 173-288: Contains permission-like logic that duplicates enforcement.py.
This violates the ONE ENFORCEMENT BOUNDARY rule.

Lines 315-391: Uses banned concepts like `_looks_like_mod_path()` and 
hardcoded path checks. Must be deleted or moved to WorldAdapter.

**Recommended action:** Delete ~500 lines. Keep only:
- Extension constants (`CK3_ALLOWED_EXTENSIONS`, etc.)
- Pure validation helpers with no path logic

**2. `enforcement.py`**

Line 417: Does path resolution that should use WorldAdapter.
Per canonical architecture, paths should be pre-normalized before enforcement.

Line 581: Uses `allowed_paths` - banned oracle concept.

Line 956: Uses "local mod" - banned term, should be ROOT_USER_DOCS.

**Recommended action:** Refactor to receive already-resolved `CanonicalAddress`,
not raw paths. Remove all path classification logic.

**3. `types.py`**

Line 60: `CK3LensTokenType` - Mode-specific token types violate the
unified token architecture. Tokens should have a single `TokenType` enum
used by both modes.

**Recommended action:** Create unified token types in `policy/tokens/types.py`.

**4. `server.py`**

Line 39: Uses `Path(...).resolve()` instead of WorldAdapter.

Line 1125: SQL DELETE executed directly - must go through qbuilder.

**Recommended action:** Route all DB mutations through daemon IPC.

### Recommended Cleanup Sequence

**Phase 2A: Path Consolidation (High Impact)**
1. Move ALL path classification to WorldAdapter
2. Delete `classify_path_domain()` from ck3lens_rules.py
3. Delete `_looks_like_mod_path()` and similar helpers
4. Update enforcement.py to receive `CanonicalAddress` not raw paths
5. **Expected reduction:** 400-500 violations

**Phase 2B: Terminology Normalization**
1. Replace all "local mod" → ROOT_USER_DOCS domain
2. Replace all "workshop mod" → ROOT_STEAM domain
3. Update error messages and comments
4. **Expected reduction:** 80-100 violations

**Phase 2C: Token Type Unification**
1. Create `policy/tokens/types.py` with unified `TokenType`
2. Deprecate `CK3LensTokenType` 
3. Update all token references
4. **Expected reduction:** 20-30 violations

**Phase 2D: SQL Mutation Routing**
1. Audit all direct SQL mutations in MCP layer
2. Route through `daemon_client.py` IPC
3. Verify read-only DB mode in all MCP servers
4. **Expected reduction:** 30-50 violations

### Success Criteria

Architectural cleanup is complete when:
- `arch_lint` returns 0 errors on full codebase
- No LXE tokens required for production code
- All path resolution flows through WorldAdapter
- All DB mutations flow through qbuilder daemon
- No banned terms in executable code

---

## References

- [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) - Sections 1-5 (Core Rules)
- [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) - Section 11 (arch_lint)
- [SINGLE_WRITER_ARCHITECTURE.md](SINGLE_WRITER_ARCHITECTURE.md) - DB mutation routing
- `tools/arch_lint/` - Linter being locked
- `tools/compliance/` - Phase 1.5 compliance tools
