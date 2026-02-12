# CK3_EXEC — Phase 2 Deterministic Execution Directive

**Status:** DRAFT FOR SPRINT 0 IMPLEMENTATION  
**Authority:** CANONICAL_CONTRACT_LAW.md §8–§13  
**Integrates With:** PHASE_2_DETERMINISTIC_GATES_PLAN.md  
**Sequencing:** After Phase 2 completion (see §7 of Phase 2 plan)  
**Date:** February 12, 2026

---

## Design Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| Feb 11, 2026 | Mechanism 2 (runtime audit hook / `sys.addaudithook`) **deferred** | Close-time git diff audit (Mechanism 1) provides geographic containment for all tools. Runtime hooks may be unnecessary. Revisit post-Phase-2. |
| Feb 12, 2026 | Post-exec git diff audit (Mechanism 1) is the primary containment mechanism | Works tool-agnostically via git. Not an enforcement surface — it's a precondition for commit, like schema validation is a precondition for contract open. |
| Feb 12, 2026 | `_ck3_exec_internal` carved out of Phase 2.1 Reply conversion | Will be rewritten by this directive. Avoids double-work. |

---

## 0. Purpose

ck3_exec is currently an authority compression failure point. It allows arbitrary Python execution that may:

- Bypass contract intent
- Bypass deterministic gates
- Evade audit clarity
- Introduce mutation outside declared scope

This directive converts ck3_exec into a **contract-scoped execution lane** fully aligned with:

- Contract Law
- Capability Matrix
- Phase 2 Deterministic Gates model
- Close-time reconciliation as the sole audit authority

---

## 1. Non-Negotiable Law Constraints

The following constraints derive directly from Canonical Law and are binding:

1. **Enforcement remains the only decision boundary.**
2. **Contracts do not grant authority.**
3. **Gates validate declarations, not execution.**
4. **No new Decision enums.**
5. **REQUIRE_CONTRACT remains banned from tool surfaces.**
6. **No execution-time contract validation gates.**
7. **Close-time remains the sole reconciliation point.**
8. ck3_exec must comply with all of the above.

---

## 2. Architectural Positioning

ck3_exec operates under:

- **EN layer** enforcement for WRITE/DELETE
- **CT layer** open/close gates
- Phase 1.5 deterministic evidence infrastructure

It **MUST NOT**:

- Become a new enforcement surface
- Introduce execution-time contract gates
- Validate work_declaration at runtime
- Bypass semantic validator / audit pipeline

---

## 3. Phase 2 Execution Model

### 3.1 Inline Execution Removal

Inline `-c` execution is **forbidden** in normal agent mode. It is allowed **only** in:

- mode-init
- break-glass

All other execution must:

1. Execute a file
2. Located inside the canonical staging directory
3. Bound to a contract

### 3.2 Execution Staging Area

All executable scripts must reside in:

```
~/.ck3raven/exec_queue/<contract_id>/<script_name>.py
```

**Rules:**

- Path must be canonical-resolved
- Script must be immutable after HAT signing
- Script must hash-match at execution time
- Execution outside this directory is **DENIED** by the EN layer

### 3.3 Contract Binding

Each executable script must bind to:

- contract_id
- Declared targets
- Declared operations
- SHA256(script bytes)

**Execution requires:**

- Valid contract
- Valid Sigil signature (session-scoped)
- Matching script hash
- Matching declared target manifest

If any mismatch occurs → **EN layer D reply**.

---

## 4. Runtime Guard Model (DEFERRED — Mechanism 2)

> **Status: DEFERRED** to post-Phase-2 evaluation.
>
> The original design called for `sys.addaudithook` to intercept file operations
> in real-time during script execution. This has been deferred because:
>
> 1. Close-time git diff audit (Mechanism 1) provides geographic containment
> 2. Runtime hooks create a second denial path, complicating Rule 1
> 3. The complexity cost is high relative to the incremental benefit
>
> If post-Phase-2 evaluation reveals gaps that git diff cannot catch
> (network calls, subprocess spawning, etc.), Mechanism 2 will be revisited.
>
> See Phase 2 plan §7 for sequencing details.

---

## 5. Geographic Containment Rule

Allowed writes must satisfy:

```python
canonical_realpath(target)
    is_within(contract_root)
    AND
    is_within(declared_targets)
```

- **Equality comparison is forbidden.**
- **Containment must:**
  - Resolve symlinks
  - Normalize case (Windows)
  - Deny escape attempts
  - Deny unresolved paths

**Enforcement point:** Post-exec git diff audit (Mechanism 1). Not runtime interception.

---

## 6. HAT Execution Signature Model

**Before execution:**

User must approve a HAT packet containing:

- Script hash
- contract_id
- declared_targets
- Mode
- Timestamp

This produces:

```
script.py.hat.json
```

**Runtime verifies:**

1. Signature valid
2. Session valid
3. Hash matches
4. Contract matches

If invalid → **EN D reply**. This is consistent with HAT semantics.

---

## 7. Git Post-Execution Audit (Mechanism 1)

**This is the primary containment mechanism.**

**After execution:**

1. Snapshot pre-exec git state (already captured as `baseline_sha` on contract — Law §13.1)
2. Snapshot post-exec git state
3. Compute diff

**If any changed file is:**

- Not in declared_targets
- Not inside contract root

→ **Commit is blocked** (not by enforcement — by the close audit gate flagging the mismatch).

Close-time audit remains the authoritative reconciliation point. This is analogous to how invalid contract templates are rejected at open — it's a precondition, not an enforcement decision.

---

## 8. Explicit Non-Goals

This design does **NOT**:

- Replace OS sandboxing
- Validate symbol intent at runtime
- Inspect semantic meaning
- Allow agent-defined allowlists
- Introduce new token types
- Override capability matrix
- Bypass protected file HAT rules

---

## 9. Deterministic Gate Alignment

ck3_exec must integrate cleanly with Phase 2 gates:

| Lifecycle | Layer | Responsibility |
|-----------|-------|---------------|
| **Contract Open** | CT | Scope feasibility gate |
| **Execution** | EN | enforce() only |
| **Close** | CT | Sole reconciliation (git diff audit) |

ck3_exec **MUST NOT** introduce:

- Execution-time contract validation gates
- Enforcement bypass logic
- Semantic authorization

---

## 10. Sprint 0 Acceptance Criteria

The following **MUST** be demonstrably true:

- **A.** Inline execution blocked: Attempt inline exec → EN D reply.
- **B.** Execution requires staging path: Script outside staging dir → EN D.
- **C.** Script hash binding enforced: Modify script after HAT → execution denied.
- **D.** Post-exec git diff audit: Files changed outside declared targets → commit blocked at close.
- **E.** No REQUIRE_CONTRACT leaks: grep for string in tool surfaces → zero.
- **F.** Close-time reconciliation unchanged: Close contract still uses audit pipeline as defined.

**Removed from original criteria:**
- ~~Runtime containment enforced~~ (Mechanism 2 deferred)
- ~~Subprocess blocked~~ (Mechanism 2 deferred)

---

## 11. Risk Register

| Risk | Mitigation |
|------|------------|
| False belief of sandbox | Documentation explicitly states "containment only" |
| Path resolution bug | Canonical path resolver used (WorldAdapter) |
| Post-exec git diff misses in-memory side effects | Known limitation. Mechanism 2 revisit post-Phase-2. |
| Gate/enforcement confusion | Layer ownership strictly enforced |

---

## 12. Pre-Implementation: Canonical Document Review

Before implementing Sprint 0, the agent must check whether ck3_exec's special handling requires updates to:

1. **CANONICAL_CONTRACT_LAW.md** — §13 (Contract Continuity) now covers baseline_sha and close-time audit. Confirm no further changes needed.
2. **CONTRACT_OPERATIONS_GUIDE.md** — Likely needs additions. Document staging directory, HAT script binding, post-exec git diff audit.

---

## 13. MCP-Call Test Battery

### T0 — Baseline: no contract → ck3_exec denied

**Preconditions:** Mode initialized. No active contract.

- `ck3_exec(command="run_script", ...)` → **EN-layer Deny**. Must not include "REQUIRE_CONTRACT".

### T1 — Inline execution is blocked

- `ck3_exec(command="...", python="-c", code="print('hi')")` → **EN-layer Deny**: inline execution forbidden.

### T2 — Staging directory required

**Preconditions:** Valid contract open.

- `ck3_exec(command="run_script", script_path="<ROOT_REPO>/docs/outside_staging.py")` → **Denied**: not under staging dir.

### T3 — HAT-signed script required

- Script in staging but unsigned → **EN-layer Deny**: missing HAT signature.

### T4 — HAT hash binding

- Run 1 (signed script): Success.
- Mutate script. Run 2: **Denied**: hash mismatch.

### T5 — Post-exec git diff audit

- Contract targets = `docs/allowed.txt`. Script writes to `src/forbidden.txt`.
- Close contract → CT-GATE-I-004: undeclared file `src/forbidden.txt` in diff.

### T6 — Close-time reconciliation unchanged

- Normal contract lifecycle. Close behavior per existing audit pipeline.

---

*End of CK3 Exec Sprint 0 Directive*
