# CANONICAL CONTRACT LAW

Status: CANONICAL — Phase 2 Baseline  
Authority Level: HARD LAW  
Last Updated: February 11, 2026

---

## 0. Authority and Scope

This document defines the **binding law** of the CK3Raven Canonical Contract System.

- It is the **single source of truth** for:
  - what a contract *is*
  - how a contract becomes *valid*
  - what authority a contract *can and cannot confer*
- Any behavior not permitted by this document is **forbidden**, regardless of tooling, precedent, or historical documentation.
- Operational guidance, validators, workflows, and tooling are **non-canonical** unless explicitly referenced by this law.

---

## 1. Purpose of the Contract System

The Canonical Contract System exists to:

1. Bind agent actions to an explicit, auditable **intent**
2. Gate execution based on **mode**, **capability**, and **geographic scope**
3. Produce a durable **audit artifact** of planned work
4. Prevent silent escalation of authority across sessions

The contract system is **not**:

- a permission oracle
- a sandbox
- a diff-level write validator
- a substitute for enforcement

---

## 2. Core Definitions

### 2.1 Contract

A **contract** is a structured declaration of *intended work*, created within a single MCP session and verified for origin.

A contract:

- may enable certain operations to be *considered*
- does **not** grant blanket permission
- does **not** validate individual file writes

### 2.2 Session

A **session** is the lifetime of a single VS Code window activation.

- New window → new session
- New session → all prior contracts are invalid

### 2.3 Agent

An **agent** is any autonomous or semi-autonomous system operating through MCP tools.

Agents have **no inherent authority**. All authority flows from:

- mode initialization
- enforcement rules
- valid contracts (where required)

---

## 3. Geographic Authority (Roots)

All file operations are evaluated relative to **canonical roots**.

**Authoritative source:** the **capability matrix** (`capability_matrix.py`) defines the closed set of recognized roots, their subdirectory entries, and the operations permitted in each mode.

Any list of roots appearing in documentation is **illustrative only** and MUST NOT be used as a substitute for consulting the capability matrix.

Subdirectories within a root may have distinct capability entries. Where the capability matrix defines subdirectory-level entries, those subdirectories have independent read/write/delete permissions. This is stated in the capability matrix, not invented by other components.

### 3.1 Rules

- Each contract operates in exactly **one** root category
- Multi-root work requires multiple contracts
- Root defines enforcement boundary
- Path containment is the only criterion — semantic meaning is irrelevant

---

## 4. Modes

A **mode** defines the global capability envelope of an agent.

- Modes are **explicitly initialized**
- Mode initialization requires a valid, session-scoped Sigil signature (HAT)
- Agents cannot self-initialize modes

A contract **cannot** elevate, expand, or override mode capabilities.

Mode modifies capability, not geography.

---

## 5. Contract Identity and Validity

### 5.1 Identity

Each contract is uniquely identified by:

- `contract_id`
- `created_at`

These fields are immutable.

### 5.2 Origin Proof (Sigil)

A contract is valid **only if** it carries a verifiable **Sigil signature** over:

```
contract:{contract_id}|{created_at}
```

This signature proves:

- the contract originated from a trusted system component
- the contract was created in the **current session**

### 5.3 Session Isolation

Contracts from prior sessions:

- MUST fail signature verification
- MUST be treated as inert
- MUST NOT be activated, loaded, or reused

---

## 6. Contract Schema Law

### 6.1 Required Fields

A canonical contract MUST include:

- `contract_id`
- `created_at`
- `mode`
- `root_category`
- `intent`
- `operations`
- `targets`
- `work_declaration`
- `author`
- `session_signature`

### 6.2 Unknown Fields

Contracts containing **unknown or undeclared fields** are **non-canonical** and MUST be rejected by canonical loaders.

Schema evolution occurs only through explicit revision of this law.

---

## 7. Operations

### 7.1 Canonical Operations

The canonical set of contract operations is:

- **READ** — discovery and reading (does not require contract)
- **WRITE** — any mutation (requires contract, with exceptions defined in capability matrix)
- **DELETE** — file or resource deletion (requires contract)

No other operation types are recognized by enforcement.

### 7.2 Enforcement Mapping

Enforcement evaluates three operation types. All contract-declared operations resolve to one of these three. If an operation is not READ or DELETE, it is WRITE.

---

## 8. Decision Model

Enforcement decisions are expressed as **Replies**:

| Reply | Meaning |
|-------|---------|
| **S** (Success) | Operation permitted. Result returned with info. |
| **D** (Deny) | Operation refused. Reason returned with info. |

The info field of a D reply carries the reason for denial. If a contract is required, the info states this (e.g., *"write operations to ROOT_REPO require a contract"*). There is no separate decision type for "needs contract" — it is a denial reason.

### 8.1 Rules

- Enforcement produces Replies. There are no other decision surfaces.
- REQUIRE_CONTRACT is a **forbidden concept** as a decision type or reply type. It is banned by arch-lint (`BANNED_DECISION_LEAKS`).
- The need for a contract is communicated as info in a D (Deny) reply.
- Contracts do not introduce new reply types or decision states.

---

## 9. Enforcement Boundary

### 9.1 Enforcement Is Authoritative

All execution decisions are made by **enforcement**, based on:

- mode
- operation
- root
- path visibility
- contract presence (where required)

### 9.2 Contracts Are Not Enforcement

A contract:

- enables certain actions to be *considered*
- does **not** validate file paths
- does **not** constrain individual writes
- does **not** override enforcement logic

### 9.3 Explicit Limitation (Phase 2 Baseline)

**Work declarations are audit artifacts only.**

At this phase:

- enforcement does **not** verify that writes match `work_declaration`
- enforcement does **not** diff planned vs actual changes

This limitation is deliberate and canonical.

---

## 10. Protected Files Law

### 10.1 Protected Files

Certain paths are designated **protected** and require explicit human approval.

Protected status is **independent** of:

- mode
- capability
- contract presence

### 10.2 Human Authorization Requirement

To open a contract that addresses a protected file, a HAT is required. If HAT approval is not provided, the request to open the contract is invalid.

HAT approval is also required for manifest-mutation tools that modify protected file entries.

### 10.3 Placement of Approval

Protected-file approval:

- occurs during **contract opening** (for contracts addressing protected paths)
- occurs in **manifest-mutation tools** (for modifying the manifest itself)
- does **not** occur in enforcement.py

---

## 11. Sigil and Approval Semantics (Normative)

### 11.1 Sigil (Cryptographic Substrate)

**Sigil is a session-scoped cryptographic signing substrate.**

Sigil:

- signs payloads using HMAC-SHA256
- verifies payload origin
- provides no semantic meaning on its own

Sigil signatures may be produced:

- automatically by the system (e.g., contract origin signing)
- as part of a human-mediated flow (e.g., HAT approval, mode initialization)

Sigil itself **does not imply human approval**.

### 11.2 Human Authorization (HAT)

**HAT is a semantic act**, not a cryptographic primitive.

HAT exists when:

- a human explicitly approves an action via extension UI
- the resulting approval is bound to a payload using Sigil

HAT is not a policy exception token. HAT IS the policy for operations that require human authorization.

HAT approvals:

- are session-scoped
- are non-persistent (no audit trail beyond logs)
- are single-use (consumed on use, cannot be replayed)
- do not create ongoing authority beyond the approved scope

### 11.3 Compliance Verification (NST)

**NST (New Symbol Token) is an in-policy compliance verification**, not a policy exception.

Creating new symbols that have been approved and agreed with the user is **within policy**. NST exists to verify and record that this in-policy action occurred intentionally:

- Declares intentionally new identifiers introduced during a contract
- Ephemeral: session-scoped, not persisted to git-tracked directories
- Generated at contract close time, consumed during audit
- Required when semantic validator detects new symbols in changed files

NST is NOT an exception token. It does not exempt the agent from any rule. It confirms that new symbol creation was deliberate and user-approved.

### 11.4 Exception Tokens (LXE)

**LXE (Lint Exception Token) is an exception token** — it represents an explicit, human-approved deviation from a compliance requirement.

- Grants temporary exceptions to lint rule violations
- Persistent: git-tracked, reviewable, contract-bound
- Follows propose-approve lifecycle (agent proposes, human approves)
- TTL: 8 hours

LXE exempts the agent from failing the lint requirement at contract closeout, with user approval.

### 11.5 Token Rules

Tokens (both NST and LXE):

- MUST NOT be interchangeable with Sigil signatures or HAT approvals
- MUST NOT rely on agent-accessible persistent secrets
- Are scope-bound and non-transferable

---

## 12. Phase Model (Normative)

### Phase 1: Contract Law

- Contracts gate certain operations
- Enforcement independent of work declaration
- Geographic authority established

### Phase 1.5: Deterministic Evidence

- Semantic validation via git-diff-based analysis
- Locked linter rulesets with content-hashed verification
- NST for in-policy symbol creation verification
- LXE for declared deviations from lint requirements
- Compliance evidence artifacts for audit trail

### Phase 2: Deterministic Gates (Future)

- Contract open-time gates evaluate declared scope against capability matrix
- Close-time audit gates reconcile declared work against actual changes
- No silent escalation paths
- Close-time is the **sole reconciliation point** between declared and actual work

Gate outcomes align with the Canonical Reply System:

- **CT layer** gates produce: S (passed), I (declaration infeasible or incomplete), E (system error)
- CT gates **never produce D** (Denied). Governance refusals are EN-layer decisions only.
- If a CT gate returns I (e.g., scope infeasible), the tool handler rejects the request. The gate itself does not deny.

Only Phase 2 behavior may assume deterministic closure.

---

## 13. Contract Continuity

Contracts are ephemeral (session-scoped, TTL-limited). Work frequently spans multiple contracts due to session interruptions, expiry, or scope changes. This section defines the canonical mechanisms for maintaining audit continuity across contract boundaries.

### 13.1 Baseline SHA

When a contract is opened, the system records `git rev-parse HEAD` as `baseline_sha` on the contract. This establishes the point-in-time state of the repository at contract creation.

At close time, `git diff <baseline_sha>..HEAD` enumerates all changes made under the contract. This diff is the canonical input to the close audit gate (Phase 2, §12).

- `baseline_sha` is immutable after contract creation
- `baseline_sha` is inherited on renewal (§13.2)

### 13.2 Contract Renewal

When a contract expires with uncommitted work in the working tree, the agent may **renew** rather than open a new contract.

Renewal inherits from the expired contract:

- `root_category`
- `operations`
- `targets`
- `work_declaration`
- `baseline_sha` (from the original contract, not current HEAD)

Renewal produces a **new contract** (new `contract_id`, new Sigil signature, new TTL). It is not a mutation of the expired contract — the expired contract remains closed/expired.

The purpose of renewal is to eliminate agent error in re-declaring scope for ongoing work. Scope is inherited, not re-guessed.

### 13.3 Carry-Over Detection

When opening a **new** contract (not a renewal), if `git status` reveals uncommitted changes in the working tree, the open gate detects them as **carry-over files**.

Carry-over files are grouped by origin contract:

- Files whose paths match declared `targets` of a recently expired contract are attributed to that contract
- Files not attributable to any expired contract are placed in an "unattributed" cluster

The open gate response includes a **suggested contract template** with carry-over files pre-populated as targets. The `edit_kind` for each file is inferred from git status (M → modify, A → add, D → delete, untracked → add).

### 13.4 Carry-Over Escalation

Carry-over files that persist across multiple contract opens without being committed or stashed are escalated:

| Contract Opens With Same Carry-Over | Severity | Behavior |
|--------------------------------------|----------|----------|
| 1st occurrence | Informational | Template suggested, agent may proceed with different scope |
| 2nd occurrence | Warning | Template suggested, logged as persistent carry-over |
| 3rd occurrence | Required | Carry-over files **must** be included as targets or explicitly stashed |

Escalation state is tracked per-file, not per-contract. A file's escalation counter resets when it is committed or stashed.

### 13.5 Carry-Over Stash (HAT-Gated)

An agent may explicitly dismiss a carry-over cluster via:

```
ck3_contract(command="stash_carry_over", contract_id="<expired_contract_id>")
```

Stashing requires **HAT approval** (same shield-icon flow as protected file approval). This ensures that dismissing uncommitted work is an auditable human decision, not a silent agent action.

Stashed files:

- Are reverted or set aside (implementation-defined: git stash, git checkout, etc.)
- Are logged as stashed with the HAT approval reference
- Reset their escalation counter

### 13.6 Rules

- Renewal preserves audit continuity. The close audit gate evaluates all changes from `baseline_sha` through final HEAD, spanning the original and renewed contracts.
- Carry-over detection is an open gate (CT layer). It produces I (informational/warning) or S (no carry-over), never D.
- Stashing is a human-authorized action. Agents cannot stash carry-over without HAT.
- Contract reuse across sessions remains **forbidden** (§5.3). Renewal creates a new contract within the same session, or in a new session if the original expired.

---

## 14. Forbidden Concepts

The following are explicitly **forbidden**:

- implicit authority
- semantic authorization (authorization derived from what something means, not where it lives)
- symbol-level locks (replaced by semantic validator + git diff)
- self-issued approval tokens
- contract reuse across sessions
- persistent agent-accessible signing keys
- enforcement bypass via documentation ambiguity
- REQUIRE_TOKEN as a decision type (banned by arch-linter)
- REQUIRE_CONTRACT as a decision type or reply type (banned by arch-linter `BANNED_DECISION_LEAKS`)
- vestigial semantic operations (RENAME, EXECUTE, DB_WRITE, GIT_WRITE) in enforcement
- direct DB mutation from MCP tools (daemon-only)
- launcher derived permission
- agent created allowlists
- silent rule suppression

---

## 15. Canonical Priority Rule

In case of conflict, authority is resolved in the following order:

1. **This law**
2. Enforcement code
3. Sigil invariants
4. Validators and tooling
5. Documentation and commentary

Anything contradicting this law is **invalid**, regardless of age or precedent.

---

### End of Canonical Law
