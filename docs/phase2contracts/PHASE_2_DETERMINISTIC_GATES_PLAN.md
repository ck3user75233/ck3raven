# Phase 2: Deterministic Gates — Implementation Plan

Status: DRAFT — Revision 3 (Contract Continuity Integrated)  
Authority: CANONICAL_CONTRACT_LAW.md §12, §13  
Author: Agent (for Nate's review)  
Date: February 12, 2026

---

## 1. Scope and Goals

### 1.1 What "Deterministic Gates" Means

A **gate** is a validation checkpoint that evaluates a contract declaration against known rules and produces a deterministic Reply:

| Reply | Layer | Meaning | Example |
|-------|-------|---------|---------|
| **S** (Success) | CT | Gate passed, continue | Contract scope matches capability matrix |
| **I** (Invalid) | CT | Declaration infeasible or incomplete | Missing `work_declaration` for WRITE |

Gates are **pure functions** of their inputs. Same inputs → same reply. No ambient state, no side effects, no network calls.

Gates are in the **CT (Contract) layer**. They produce S, I, or E. They **never produce D** (Denied). Governance refusals (D) originate only from the EN (Enforcement) layer.

### 1.2 Two Gate Families

| Family | When | What It Checks |
|--------|------|----------------|
| **Open Gates** | `open_contract()` | Declared scope (root, operations, targets) is achievable given mode + capability matrix |
| **Close Gates** | `close_contract()` | Audit evidence is complete, declared edits vs. actual changes |

There are **no execution-time gates**. During execution, enforcement (`enforce()`) operates independently of contract declarations, as it does today. Close-time is the **sole reconciliation point** between declared and actual work.

### 1.3 In Scope

- Open-time scope validation (declared root_category × operations × mode vs. capability matrix)
- Open-time target path containment (targets resolve within declared root)
- Open-time carry-over detection with template generation (Law §13.3)
- Close-time audit gate via git diff against baseline_sha (Law §13.1)
- Close-time evidence gate (compliance fields populated)
- Contract renewal with scope inheritance (Law §13.2)
- Carry-over escalation tracking (Law §13.4)
- Carry-over stash with HAT approval (Law §13.5)
- Baseline SHA capture at contract open (Law §13.1)
- Elimination of `REQUIRE_CONTRACT` from all tool response surfaces
- Replacement of leaked `"policy_decision": "REQUIRE_CONTRACT"` dicts with Reply D (EN-OPEN-D-001)
- Gate logging conformant with Canonical Logs specification
- Test infrastructure for contracts and enforcement

### 1.4 Out of Scope

- Changes to the capability matrix values (rows remain as-is)
- Changes to Sigil's cryptographic implementation
- Changes to protected files manifest format
- New enforcement decision enum values (Phase 2 adds ZERO new enums)
- Moving protected file approval logic into enforcement.py
- Symbol-level write validation (remains in semantic validator)
- Any new token types
- Execution-time gates or execution-time contract scope checking
- Runtime audit hooks on Python execution (Mechanism 2 — deferred to post-Phase-2 evaluation)
- ck3_exec execution model rewrite (separate directive: CK3_EXEC_SPRINT_0_DIRECTIVE.md)

### 1.5 Law Boundary Re-Statement

From CANONICAL_CONTRACT_LAW.md §12 (Phase Model):

> Phase 2: Deterministic Gates
> - Contract open-time gates evaluate declared scope against capability matrix
> - Close-time audit gates reconcile declared work against actual changes
> - No silent escalation paths
> - Close-time is the **sole reconciliation point** between declared and actual work

From §13 (Contract Continuity):

> - `baseline_sha` recorded at contract open, inherited on renewal
> - Carry-over detection at open time with template generation
> - Escalating severity for persistent carry-over files
> - HAT-gated stash for dismissing carry-over clusters

From §9.2:

> A contract enables certain actions to be *considered*. It does NOT validate file paths. It does NOT constrain individual writes. It does NOT override enforcement logic.

**Critical constraint:** Gates validate *declarations*, not *execution*. They do not bypass or override `enforce()`. Enforcement remains THE single decision boundary (Canonical Architecture Rule 1).

---

## 2. Current-State Mapping

### 2.1 What Exists Today (Phase 1/1.5)

| Component | File | Current Behavior | Phase 2 Change |
|-----------|------|------------------|----------------|
| **enforce()** | `policy/enforcement.py` | Checks mode × root × cap matrix × contract presence. Returns Reply via rb. | No changes. |
| **open_contract()** | `policy/contract_v1.py:640` | HAT gate for protected files → generate ID → validate schema → Sigil sign → save. No scope validation against capability matrix. | Add open gates: scope feasibility, target containment, work declaration completeness, carry-over detection. Add `baseline_sha` capture. |
| **close_contract()** | `policy/contract_v1.py:755` | Minimal: load → verify sig → mark closed → save. No audit gates. | Add close gates: git-diff-based declared-vs-actual reconciliation, compliance evidence check. |
| **ContractV1** | `policy/contract_v1.py` | Dataclass with targets, work_declaration. No `baseline_sha`. | Add `baseline_sha: str \| None` field. |
| **ck3_file enforcement** | `unified_tools.py` | resolve → get_active_contract → enforce() → Reply. | No changes (already Reply). |
| **ck3_git enforcement** | `unified_tools.py` | Same pattern. | Verify no dict leaks remain. |
| **server.py consumers** | `server.py` (5 sites) | Some still check `policy_decision` strings in dict results. | Replace with Reply code/type checks. |
| **ck3_exec enforcement** | `server.py` | Direct enforce() call. | Carve-out: `_ck3_exec_internal` deferred to exec directive. Fix only the surface leak sites. |
| **Trace logging** | `server.py` (20+ sites) | `trace.log("ck3lens.<category>", inputs, outputs)` | Gate invocations logged per Canonical Logs spec via structured logger. |
| **Test infrastructure** | None | No test files for contracts or enforcement. | New: `tests/test_contract_gates.py`, `tests/test_enforcement_integration.py`, `tests/test_contract_lifecycle.py` |

### 2.2 Integration Points (Exhaustive)

**Sites that check `"policy_decision"` strings in server.py (THE leak points):**

1. `server.py` — ck3_db_delete consumer sites (~3)
2. `server.py` — ck3_exec consumer site (~1)
3. `server.py` — any remaining dict-interpretation blocks (~1)

**Note:** `unified_tools.py` has zero `REQUIRE_CONTRACT` / `policy_decision` references (verified by grep, Feb 11 2026).

**Sites that call `get_active_contract()`:**

1. `unified_tools.py` — ck3_file, ck3_file edit, ck3_file delete, ck3_git
2. `server.py` — ck3_contract status/open checks

---

## 3. Proposed Architecture

### 3.1 New Module: `policy/contract_gates.py`

This module contains all gate functions. Each gate is a pure function returning a structured result.

```
policy/
├── enforcement.py          (unchanged — THE decision boundary)
├── contract_v1.py          (modified — calls gates from open/close, baseline_sha, renewal)
├── contract_gates.py       (NEW — all gate logic)
└── __init__.py
```

**Gate return type:**

```python
@dataclass
class GateResult:
    """Result from a contract gate evaluation."""
    passed: bool
    code: str          # CT-GATE-{S|I}-NNN
    reply_type: str    # "S" or "I" (never "D")
    message: str
    data: dict         # Gate-specific payload
```

**Construction-time invariants enforced:**
1. Code matches `LAYER-AREA-TYPE-NNN` format
2. `reply_type` matches TYPE from code string
3. Layer/type pairing respects `LAYER_ALLOWED_TYPES` (CT cannot produce D)

**Gate functions:**

```python
# === OPEN GATES ===

def gate_scope_feasibility(
    mode: str,
    root_category: RootCategory,
    operations: list[Operation],
) -> GateResult:
    """Verify mode × root × operations is achievable per capability matrix."""

def gate_target_containment(
    root_category: RootCategory,
    targets: list[ContractTarget],
) -> GateResult:
    """Verify all target paths resolve within declared root."""

def gate_work_declaration_completeness(
    operations: list[Operation],
    work_declaration: WorkDeclaration,
) -> GateResult:
    """Verify work_declaration has required fields for declared operations."""

def gate_carry_over(
    git_status: list[dict],
    declared_targets: list[ContractTarget],
    expired_contracts: list[ContractV1],
    escalation_state: dict[str, int],
) -> GateResult:
    """Detect uncommitted carry-over files and generate template.
    
    Returns CT-GATE-S-006 if no carry-over, or CT-GATE-I-006 with:
    - carry_over_files grouped by origin contract
    - suggested_template with pre-populated targets
    - escalation_level per file
    """

# === CLOSE GATES ===

def gate_close_audit(
    contract: ContractV1,
    baseline_sha: str,
    current_head: str,
    actual_changes: list[str],
) -> GateResult:
    """Reconcile declared edits against git diff from baseline_sha.
    
    The git diff (baseline_sha..HEAD) is the canonical source of truth
    for what actually changed under this contract.
    """

def gate_close_evidence(
    contract: ContractV1,
) -> GateResult:
    """Verify compliance evidence fields are populated."""
```

### 3.2 Reply Ownership Table

| Operation | Owner Layer | Area | Allowed Reply Types | Notes |
|-----------|-------------|------|---------------------|-------|
| Contract open/close gate checks | CT | GATE | S / I / E | CT never produces D |
| Contract lifecycle results (opened, closed, renewed) | CT | OPEN / CLOSE | S / I / E | Final lifecycle state |
| Enforcement decisions (root/subdir/op) | EN | WRITE / EXEC / OPEN | S / D / E | EN never produces I |
| WorldAdapter resolution | WA | RES / VIS | S / I / E | WA never produces D |

**Close gate advisory semantics:** In Phase 2 baseline, close gates operate in **advisory mode only**. A CT-GATE-I close result is logged and saved to contract notes, but does not alter closure eligibility. Close gates provide structured CT-layer diagnostics for audit review.

**Carry-over gate semantics:** The carry-over open gate (CT-GATE-I-006) is informational at escalation levels 1-2. At escalation level 3, carry-over files become required targets — the open gate returns I with `escalation_required: true` and the contract open is rejected until carry-over files are included as targets or stashed.

### 3.3 Contract Continuity Architecture

#### 3.3.1 baseline_sha

New field on `ContractV1`:

```python
baseline_sha: str | None = None  # git rev-parse HEAD at open time
```

Captured automatically in `open_contract()` via `git rev-parse HEAD`. Immutable after creation. Inherited on renewal.

#### 3.3.2 Renewal Flow

```
Agent calls: ck3_contract(command="renew", contract_id="v1-expired-xxx")

open_contract():
  1. Load expired contract
  2. Verify same session (or new session is acceptable if work persists)
  3. Inherit: root_category, operations, targets, work_declaration, baseline_sha
  4. Generate new contract_id, Sigil signature, TTL
  5. Run open gates (scope feasibility — should pass since scope is inherited)
  6. Save new contract
  7. Return new contract with lineage reference to expired contract
```

#### 3.3.3 Carry-Over Detection Flow

```
Agent calls: ck3_contract(command="open", ...) [NEW contract, not renewal]

open_contract():
  1. Run git status to detect uncommitted changes
  2. If no uncommitted changes → skip carry-over gate
  3. If uncommitted changes exist:
     a. Load recently expired contracts
     b. Match files to expired contract targets → group by origin
     c. Check escalation state per file
     d. Build suggested template
     e. Return CT-GATE-I-006 with carry_over_files + suggested_template
  4. If escalation level 3 for any file:
     a. Reject open unless those files are in declared targets
     b. Or agent stashes first (HAT required)
```

#### 3.3.4 Escalation State Persistence

Escalation counters are stored per-file in `~/.ck3raven/config/carry_over_state.json`:

```json
{
  "files": {
    "tools/compliance/tasl.py": {"count": 2, "first_seen": "2026-02-12T08:00:00"},
    "src/parser/lexer.py": {"count": 1, "first_seen": "2026-02-12T09:00:00"}
  }
}
```

Counters reset when a file is committed or stashed. The file is lightweight and non-critical — if deleted, all counters reset to 0 (conservative restart).

### 3.4 REQUIRE_CONTRACT Elimination at Tool Surface

**New pattern:**
```python
if result.is_denied:
    return result  # Reply D passthrough — no string checking
```

**Key change:** The string `"REQUIRE_CONTRACT"` never appears in any dict returned to callers. Consumers check Reply type instead of magic strings.

### 3.5 Gate Outcomes → Reply Code Mapping

| Gate | Reply on Pass | Reply on Fail | Who Produces |
|------|---------------|---------------|--------------|
| gate_scope_feasibility | CT-GATE-S-001 | CT-GATE-I-001 | contract_gates.py (CT layer) |
| gate_target_containment | CT-GATE-S-002 | CT-GATE-I-002 | contract_gates.py (CT layer) |
| gate_work_declaration_completeness | CT-GATE-S-003 | CT-GATE-I-003 | contract_gates.py (CT layer) |
| gate_close_audit | CT-GATE-S-004 | CT-GATE-I-004 | contract_gates.py (CT layer) |
| gate_close_evidence | CT-GATE-S-005 | CT-GATE-I-005 | contract_gates.py (CT layer) |
| gate_carry_over | CT-GATE-S-006 | CT-GATE-I-006 | contract_gates.py (CT layer) |
| REQUIRE_CONTRACT → D | — | EN-OPEN-D-001 | enforcement surface in tools (EN layer) |

### 3.6 Gate Logging Contract

Gate invocations are logged per Canonical Logs specification.

**Category hierarchy:**

| Category | When Used | Log Level |
|----------|-----------|-----------|
| `contract.gate.open` | Open-time gate invocations | INFO |
| `contract.gate.close` | Close-time gate invocations | INFO |
| `contract.continuity` | Renewal, carry-over, stash events | INFO |

**Required fields per log entry:**

| Field | Type | Description |
|-------|------|-------------|
| `gate_name` | string | Function name (e.g., `scope_feasibility`) |
| `contract_id` | string | Contract ID (if available) |
| `root_category` | string | Root being validated |
| `reply_code` | string | Gate result code |
| `passed` | bool | Whether gate passed |

**Redaction rules (MUST NOT log):**
- Sigil signatures or secret material
- Absolute host paths (use root_category + relative_path)
- File content or payloads
- Full work_declaration (log work_summary only)

### 3.7 Prohibited Changes (Hard Constraints)

1. **No new Decision enum values.** Only the surface translation changes.
2. **No REQUIRE_TOKEN or REQUIRE_HAT decision types.** HAT remains a precondition check.
3. **No moving protected file approval into enforcement.py.**
4. **No new enforcement entry points.** `enforce()` remains THE single function.
5. **Gates do not call enforce().** Separate concerns.
6. **Gates do not produce Reply D.** Only EN layer produces D.
7. **No execution-time gates.** Close-time is the sole reconciliation point.
8. **No runtime audit hooks.** Mechanism 2 is deferred to post-Phase-2 evaluation.

---

## 4. Implementation Phases

### Phase 2.1: REQUIRE_CONTRACT Surface Elimination + Schema

**Goal:** Remove all `"REQUIRE_CONTRACT"` / `"policy_decision"` strings from tool response dicts. Add `baseline_sha` to ContractV1.

**Files Changed:**
- `server.py` — ~5 consumer sites checking `policy_decision` strings
- `policy/contract_v1.py` — Add `baseline_sha: str | None` field to ContractV1

**Carve-out:** `_ck3_exec_internal` is NOT converted to Reply in this phase. It will be rewritten in the exec directive. Only the surface leak sites in server.py are fixed.

**Acceptance Test:**
1. With no contract active, call `ck3_file(command="write", ...)` targeting ROOT_REPO.
2. Response must contain Reply D with code and NOT contain the string `"REQUIRE_CONTRACT"`.
3. `grep -r "policy_decision" server.py` in response-building code paths → zero matches.
4. `ContractV1` has `baseline_sha` field (schema test).


### Phase 2.2: Gate Infrastructure (`contract_gates.py`)

**Goal:** Create the gate module with `GateResult` dataclass and the first gate function. Register CT-GATE-* codes in `reply_codes.py`.

**Files Changed:**
- `policy/contract_gates.py` — NEW file with GateResult + gate_scope_feasibility
- `reply_codes.py` — Register CT-GATE-S-001..006 and CT-GATE-I-001..006
- `tests/test_contract_gates.py` — NEW file

**Acceptance Test:**
1. `gate_scope_feasibility("ck3lens", ROOT_GAME, [WRITE])` → I-001 (infeasible)
2. `gate_scope_feasibility("ck3raven-dev", ROOT_REPO, [WRITE])` → S-001 (feasible)
3. `GateResult(code="CT-GATE-D-001", ...)` → ValueError (CT cannot produce D)
4. Unit tests validate all mode × root × operation combinations against real capability matrix


### Phase 2.3: Open Gates Integration + Renewal + Carry-Over

**Goal:** Wire open gates into `open_contract()`. Add baseline_sha capture. Implement contract renewal and carry-over detection.

**Files Changed:**
- `policy/contract_v1.py` — `open_contract()` calls gates, captures baseline_sha, supports renewal
- `policy/contract_gates.py` — Add gate_target_containment, gate_work_declaration_completeness, gate_carry_over
- New: `~/.ck3raven/config/carry_over_state.json` (runtime state file)

**Acceptance Test:**
1. Contract open with infeasible scope → REJECTED with CT-GATE-I-001
2. Contract open with feasible scope → SUCCEEDS, `baseline_sha` populated
3. Contract renewal inherits scope from expired contract
4. Opening new contract with uncommitted files → response includes `carry_over_files` and `suggested_template`
5. Protected files HAT gate still fires correctly (no regression)

**Expected Evidence:**
- `debug_get_logs(category="contract.gate.open")` shows gate entries
- `debug_get_logs(category="contract.continuity")` shows renewal/carry-over events


### Phase 2.4: Close Gates Integration

**Goal:** Wire close gates into `close_contract()`. Close-time is the sole reconciliation point. Git diff from baseline_sha is the canonical audit input.

**Advisory mode:** Close gates do NOT block closure in Phase 2 baseline.

**Files Changed:**
- `policy/contract_v1.py` — `close_contract()` calls close gates, logs results, saves to notes
- `policy/contract_gates.py` — Add gate_close_audit (git diff based), gate_close_evidence

**Acceptance Test:**
1. Open contract → make changes → close → `gate_close_audit` compares git diff against declared edits
2. Changes outside declared targets → CT-GATE-I-004 logged (advisory, close still succeeds)
3. All changes match declared targets → CT-GATE-S-004 logged
4. Contract notes contain gate result codes

**Key implementation detail:** `gate_close_audit` receives `git diff <baseline_sha>..HEAD` output. This covers ALL tools (ck3_file, ck3_exec, ck3_git, manual edits) — it's tool-agnostic.


### Phase 2.5: Carry-Over Escalation + Stash + Test Suite

**Goal:** Implement carry-over escalation tracking, HAT-gated stash command, comprehensive test suite.

**Files Changed:**
- `policy/contract_v1.py` — Escalation state management, stash_carry_over command
- `policy/contract_gates.py` — Escalation-aware carry-over gate
- `tests/test_contract_gates.py` — All gate unit tests
- `tests/test_enforcement_integration.py` — NEW
- `tests/test_contract_lifecycle.py` — NEW, includes renewal/carry-over/stash scenarios

**Acceptance Test:**
1. File appears as carry-over across 3 contract opens → 3rd open rejects unless file included or stashed
2. `ck3_contract(command="stash_carry_over", ...)` without HAT → REJECTED
3. After HAT approval, stash succeeds → escalation counter resets
4. Full lifecycle: open → write → close → renew → close → verify gate sequence in logs

---

## 5. Migration and Compatibility

### 5.1 Zero Compatibility Requirement

Phase 2 introduces **no backward compatibility obligations**:

| Scenario | Behavior |
|----------|----------|
| Existing open contracts from Phase 1/1.5 | Session isolation rejects them. Within session, gates apply only to newly opened contracts. |
| Contracts without `baseline_sha` | Close audit gate skips git diff (no baseline to diff from). Logged as CT-GATE-I-004 with reason "no baseline". |
| Unsigned contracts on disk | Rejected by `load_contract()` as before. |
| Legacy pre-v1 contracts | Already archived. |

### 5.2 Migration Order

Phase 2.1 **must** complete before Phases 2.3-2.4. If gates produce Reply-coded results but consumers still check `"REQUIRE_CONTRACT"` strings, the consumers break.

### 5.3 Rollback

Each phase is independently revertable via git. No database migrations. `carry_over_state.json` is non-critical (deletion = safe reset).

---

## 6. Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Gate produces S but enforcement would DENY | HIGH | Gates do not override enforcement. Gate S ≠ ALLOW. |
| Gate accidentally creates enforcement bypass | HIGH | Gates are CT layer (cannot produce D). Layer ownership enforced by GateResult validation. |
| REQUIRE_CONTRACT elimination breaks tool flow | MEDIUM | Phase 2.1 is isolated. Test before proceeding. |
| Carry-over escalation too aggressive | LOW | Threshold is 3 consecutive opens. Stash provides escape valve. |
| baseline_sha stale after rebase/amend | LOW | Renewal inherits original baseline. Close audit advisory only. |
| carry_over_state.json corruption | LOW | Deletion is safe reset. Non-critical state. |

---

## 7. Relationship to ck3_exec Directive

The CK3 Exec Sprint 0 Directive (`CK3_EXEC_SPRINT_0_DIRECTIVE.md`) is a **downstream consumer** of Phase 2 gates. It depends on:

- Phase 2.3 open gates (scope feasibility for execution contracts)
- Phase 2.4 close audit (git diff reconciliation covers exec-produced changes)
- REQUIRE_CONTRACT elimination (Phase 2.1)

The exec directive is sequenced **after** Phase 2 completion:

| Phase 2 | Exec Directive |
|---------|---------------|
| 2.1: Surface elimination | Prerequisite |
| 2.2: Gate infrastructure | Prerequisite |
| 2.3: Open gates + continuity | Prerequisite |
| 2.4: Close gates (git diff audit) | Prerequisite — audit covers exec |
| 2.5: Test suite | Prerequisite |
| — | Exec Sprint 0 begins |

**Carve-out in Phase 2.1:** `_ck3_exec_internal` is NOT converted to Reply. Only the server.py surface leak sites are fixed. The exec internal function will be rewritten by the exec directive.

**Mechanism 2 (runtime audit hooks):** Deferred to post-Phase-2 evaluation. The close-time git diff audit (Mechanism 1) provides geographic containment for all tools including ck3_exec. Runtime hooks may be unnecessary once the landscape is assessed.

---

## 8. Gate Verification Protocol

### Test Case 1: Scope Feasibility

**Mode:** ck3lens, **Root:** ROOT_GAME, **Op:** WRITE → CT-GATE-I-001  
**Mode:** ck3raven-dev, **Root:** ROOT_REPO, **Op:** WRITE → CT-GATE-S-001

### Test Case 2: Target Containment

**Root:** ROOT_REPO, **Target path:** `../../outside` → CT-GATE-I-002  
**Root:** ROOT_REPO, **Target path:** `src/parser/lexer.py` → CT-GATE-S-002

### Test Case 3: Carry-Over Detection

**Setup:** Uncommitted files from expired contract  
**Open new contract** → CT-GATE-I-006 with carry_over_files and suggested_template

### Test Case 4: Close Audit

**Setup:** Contract with baseline_sha, declared edits for file A, actual changes to A + B  
**Close** → CT-GATE-I-004 with mismatch for undeclared file B

### Test Case 5: Renewal

**Setup:** Expired contract with uncommitted work  
**Renew** → New contract with inherited scope and original baseline_sha

### Test Case 6: Full Lifecycle

**Open → write → close → verify gate sequence in logs:**
- CT-GATE-S-001 (scope), CT-GATE-S-002 (targets), CT-GATE-S-003 (work_decl)
- CT-GATE-*-004 (close audit), CT-GATE-*-005 (close evidence)

---

## 9. Review Checkpoints

### Checkpoint A: After Phase 2.1

1. `grep -r "policy_decision" server.py` in response-building code → zero matches
2. `ContractV1.baseline_sha` field exists
3. All existing functionality works
4. Reply D codes appear correctly in tool responses

### Checkpoint B: After Phase 2.2

1. `contract_gates.py` exists with GateResult + gate_scope_feasibility
2. Unit tests pass against real capability matrix
3. CT-GATE-S/I-001..006 registered in reply_codes.py
4. GateResult rejects CT-GATE-D-* (ValueError)

### Checkpoint C: After Phase 2.3

1. Contract open calls gates. Infeasible scope → rejected.
2. baseline_sha captured on open.
3. Renewal works — inherits scope from expired contract.
4. Carry-over detection works — template generated.
5. Protected files HAT gate unaffected.

### Checkpoint D: After Phase 2.4

1. Close audit uses git diff from baseline_sha.
2. Results are advisory (logged, not blocking).
3. Contract notes contain gate codes.
4. Audit covers all tools (tool-agnostic git diff).

### Checkpoint E: After Phase 2.5

1. All tests pass.
2. Escalation tracking works (3-open threshold).
3. Stash requires HAT approval.
4. Full lifecycle test passes with gate sequence verification.

---

## Appendix A: File Change Summary

| File | Change Type | Phase |
|------|-------------|-------|
| `policy/contract_gates.py` | NEW | 2.2, 2.3, 2.4, 2.5 |
| `reply_codes.py` | MODIFY — Register CT-GATE-* codes | 2.2 |
| `policy/contract_v1.py` | MODIFY — baseline_sha, gates, renewal, carry-over, stash | 2.1, 2.3, 2.4, 2.5 |
| `server.py` | MODIFY — policy_decision consumer fix (~5 sites) | 2.1 |
| `~/.ck3raven/config/carry_over_state.json` | NEW runtime state | 2.3 |
| `tests/test_contract_gates.py` | NEW | 2.2, 2.5 |
| `tests/test_enforcement_integration.py` | NEW | 2.5 |
| `tests/test_contract_lifecycle.py` | NEW | 2.5 |
| `policy/enforcement.py` | **NO CHANGES** | — |
| `capability_matrix.py` | **NO CHANGES** | — |
| `sigil.py` | **NO CHANGES** | — |

---

## Appendix B: Reply Code Registry (Phase 2 Additions)

| Code | Layer | Type | Message Key | Description |
|------|-------|------|-------------|-------------|
| CT-GATE-S-001 | CT | S | SCOPE_FEASIBLE | Open gate: scope feasibility passed |
| CT-GATE-S-002 | CT | S | TARGET_CONTAINED | Open gate: target containment passed |
| CT-GATE-S-003 | CT | S | WORK_DECL_COMPLETE | Open gate: work declaration complete |
| CT-GATE-S-004 | CT | S | CLOSE_AUDIT_OK | Close gate: audit reconciliation passed |
| CT-GATE-S-005 | CT | S | CLOSE_EVIDENCE_OK | Close gate: compliance evidence present |
| CT-GATE-S-006 | CT | S | NO_CARRY_OVER | Open gate: no carry-over files detected |
| CT-GATE-I-001 | CT | I | SCOPE_INFEASIBLE | Open gate: declared operations infeasible for mode × root |
| CT-GATE-I-002 | CT | I | TARGET_UNCONTAINED | Open gate: target not resolvable within declared root |
| CT-GATE-I-003 | CT | I | WORK_DECL_INCOMPLETE | Open gate: work declaration incomplete |
| CT-GATE-I-004 | CT | I | CLOSE_AUDIT_MISMATCH | Close gate: declared vs. actual discrepancy |
| CT-GATE-I-005 | CT | I | CLOSE_EVIDENCE_MISSING | Close gate: compliance evidence missing |
| CT-GATE-I-006 | CT | I | CARRY_OVER_DETECTED | Open gate: uncommitted carry-over files from prior work |

---

*End of Phase 2 Implementation Plan — Revision 3*
