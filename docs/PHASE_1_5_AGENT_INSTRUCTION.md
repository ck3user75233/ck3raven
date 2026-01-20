# Agent Instruction — Phase 1.5 Infrastructure Design & Implementation

This document is agent-facing and MUST be followed exactly.

---

## Core Principle

Agents may not self-authorize deviations.

All authority must be explicit, verifiable, human-approved, and evidenced.

If evidence cannot be produced, the operation must fail.

---

## Phase 1.5 Purpose

Phase 1.5 establishes deterministic evidence infrastructure prior to Phase 2 enforcement gates.

It does NOT block individual writes at runtime.

It blocks contract closure and commit eligibility if compliance cannot be proven.

---

## Canonical Flow

1. User requests work.
2. Agent opens a contract.
3. Agent performs edits under enforcement.
4. Agent generates compliance evidence.
5. Agent runs audit.
6. If audit fails:
   - fix issues OR
   - request explicit tokens.
7. Only after audit passes:
   - contract may close
   - commit may proceed.

---

## Exception Tokens

Tokens are NOT runtime permissions.

They are closure-time exceptions.

NST — New Symbol Token  
Required for new top-level symbols.

LXE — Lint Exception Token  
Required for locked lint violations.

---

## Token Issuance Model

Agents may generate proposed tokens only.

Proposed tokens location:

artifacts/tokens_proposed/

Approved tokens location:

policy/tokens/

Audit MUST reject tokens not in policy/tokens/.

---

## Linter Lock System

The linter ruleset is treated as a published standard.

Agents may not weaken lint rules.

Canonical lock:

policy/locks/linter.lock.json

---

## Lock Requirements

The lock must include:

- glob manifests
- expanded file list
- sha256 hash per file
- final lock_hash

Coverage must include:

- full arch_lint directory
- pyproject.toml
- all lint config files

Partial coverage is forbidden.

---

## Linter Verification

Before lint runs:

1. Expand globs
2. Hash files
3. Compare against approved lock
4. Fail on mismatch

Lint output must include lock_hash watermark.

Audit rejects unstamped reports.

---

## Linter Ruleset Updates

Changing lint rules requires:

- dedicated contract
- root_category = ROOT_REPO
- intent_type = linter_ruleset_update

Agent generates proposed lock:

artifacts/locks/proposed/linter.lock.vNEXT.json

Only user approval promotes it to:

policy/locks/linter.lock.json

Agents may not self-approve.

---

## Lock Version Policy

Single active lock.

If lock changes, in-flight contracts must re-run lint.

---

## Symbols Locker System

Two lockers required:

1. Python symbols (ck3raven)
2. CK3 script symbols (ck3lens)

Same schema.

---

## Symbol Extraction

Python:

- use AST
- extract top-level classes, functions, exports

CK3:

- query ck3raven database symbols table
- do not write new parser

---

## Symbol Locker Output

Location:

artifacts/symbols/

Must be deterministic and content-hashed.

---

## Audit Tool Responsibilities

Audit must verify:

1. symbol deltas
2. NST coverage
3. lint lock hash validity
4. LXE coverage
5. diff scope alignment

Failure blocks contract closure.

---

## Implementation Order

1. Linter lock and verifier
2. Symbols locker extractors
3. Token schemas and mint tool
4. Audit integration

---

## Hard Law

If compliance cannot be proven deterministically:

stop, block closure, escalate to user.
