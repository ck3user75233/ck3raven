# Phase 2 Implementation Plan

> **Status:** DRAFT  
> **Created:** January 26, 2026  
> **Last Updated:** January 26, 2026  
> **Prerequisite:** Phase 1.5 Deterministic Evidence Infrastructure (COMPLETE)

---

## Executive Summary

Phase 2 introduces **Deterministic Gates** - enforcement mechanisms that use Phase 1.5's evidence infrastructure to make allow/deny decisions at contract open time and closure time.

---

## Phase 1.5 Completion Status

### Completed Items (January 2026)

| Item | Status | Commit/Notes |
|------|--------|--------------|
| Linter lock system | ✅ Complete | `tools/compliance/linter_lock.py` |
| Locked lint runner | ✅ Complete | `tools/compliance/run_arch_lint_locked.py` |
| Symbol snapshots | ✅ Complete | `tools/compliance/symbols_lock.py` |
| Contract V1 schema | ✅ Complete | Geographic-only authorization |
| Work declaration enforcement | ✅ Complete | `edits[]` with file/edit_kind/location |
| NST/LXE token types | ✅ Complete | Canonical two-token model |
| WIP workspace isolation | ✅ Complete | Per-mode WIP at `<repo>/.wip/` |
| Python semantic validator | ✅ Complete | VS Code IPC for Pylance diagnostics |
| Instance ID UX | ✅ Complete | Copy/send-to-chat in AgentView |
| Golden Join pattern | ✅ Complete | Consistent symbol query joins |

### Phase 1.5 Bug Fixes (January 26, 2026)

| Bug | Fix | Commit |
|-----|-----|--------|
| BUG-001: search_symbols broken | Fixed cvid_filter import | Prior session |
| BUG-003: refs query broken | Fixed JOIN order | Prior session |
| WIP auto-wipe issue | Disabled auto-wipe on init | `056176f` |
| Python validator fallbacks | Removed, require IPC | `4a423a0` |

---

## Phase 2 Goals

### Primary Objective

Implement deterministic gates that:
1. Evaluate declared scope at contract open time
2. Validate compliance evidence at contract close time
3. Block non-compliant commits at git hook time

### Gate Outcomes

| Outcome | Meaning |
|---------|---------|
| `AUTO_APPROVE` | Contract is valid, work may proceed |
| `REQUIRE_APPROVAL` | Human approval required |
| `AUTO_DENY` | Contract is invalid, cannot proceed |

---

## Phase 2 Components

### 2.1 Contract Open Gates

**Purpose:** Validate contract scope and intent before work begins.

**Location:** `tools/ck3lens_mcp/ck3lens/policy/contract_gates.py`

**Gates to implement:**

| Gate | Check | Outcome |
|------|-------|---------|
| `SCOPE_VALIDATION` | Declared targets exist and are within root | AUTO_DENY if out of bounds |
| `CAPABILITY_CHECK` | (mode, root, operation) is allowed | AUTO_DENY if capability matrix denies |
| `WORK_DECLARATION_COMPLETE` | All required fields present | AUTO_DENY if incomplete |
| `SYMBOL_INTENT_REVIEW` | New symbols declared | REQUIRE_APPROVAL if NST needed |

**Implementation:**

```python
@dataclass
class GateResult:
    gate_name: str
    outcome: Literal["AUTO_APPROVE", "REQUIRE_APPROVAL", "AUTO_DENY"]
    reason: str
    evidence: dict | None = None

def evaluate_open_gates(contract: ContractV1) -> list[GateResult]:
    """Evaluate all open-time gates for a contract."""
    results = []
    
    # Gate 1: Scope validation
    results.append(check_scope_gate(contract))
    
    # Gate 2: Capability matrix
    results.append(check_capability_gate(contract))
    
    # Gate 3: Work declaration
    results.append(check_work_declaration_gate(contract))
    
    # Gate 4: Symbol intent
    results.append(check_symbol_intent_gate(contract))
    
    return results
```

### 2.2 Contract Close Gates

**Purpose:** Validate compliance evidence before allowing contract closure.

**Location:** `tools/ck3lens_mcp/ck3lens/policy/close_gates.py`

**Gates to implement:**

| Gate | Check | Outcome |
|------|-------|---------|
| `EVIDENCE_COMPLETE` | All required artifacts exist | AUTO_DENY if missing |
| `LINTER_CLEAN` | arch_lint reports no violations | REQUIRE_LXE if violations |
| `SYMBOLS_DECLARED` | New symbols have NST tokens | REQUIRE_NST if undeclared |
| `TARGETS_RESPECTED` | Edits stayed within declared targets | AUTO_DENY if out of scope |
| `TOKEN_VALID` | All exercised tokens are approved | AUTO_DENY if unapproved tokens |

**Evidence Requirements:**

```python
REQUIRED_EVIDENCE = {
    "arch_lint_report": "artifacts/lint/{contract_id}.arch_lint.json",
    "symbol_delta": "artifacts/symbols/{contract_id}.delta.json",
    "file_manifest": "artifacts/manifests/{contract_id}.files.json",
}
```

### 2.3 Pre-Commit Hook Integration

**Purpose:** Block commits that fail close gates.

**Location:** `scripts/hooks/pre-commit`

**Flow:**

```
git commit
    ↓
pre-commit hook
    ↓
Check for active contract
    ↓
If contract active → evaluate close gates
    ↓
If AUTO_DENY → block commit, print violations
    ↓
If REQUIRE_APPROVAL → check tokens exist
    ↓
If AUTO_APPROVE → allow commit
```

### 2.4 Branch-Based Workflow

**Purpose:** Isolate contract work on branches, merge only on success.

**Flow:**

```
Contract Open
    ↓
Create branch: contract/{contract_id}
    ↓
Work happens on branch
    ↓
Contract Close
    ↓
If close gates pass → merge to main
If close gates fail → branch remains, user resolves
```

---

## Implementation Order

### Sprint 1: Close Gates (Week 1)

1. Implement `close_gates.py` with evidence checking
2. Create `audit_contract_close.py` CLI tool
3. Update `ck3_contract(command="close")` to call gates
4. Test with manual contract close attempts

### Sprint 2: Open Gates (Week 2)

1. Implement `contract_gates.py` with scope validation
2. Update `ck3_contract(command="open")` to call gates
3. Add REQUIRE_APPROVAL handling with human notification
4. Test with various contract configurations

### Sprint 3: Pre-Commit Integration (Week 3)

1. Update `scripts/hooks/pre-commit` to check gates
2. Install hook automatically on mode initialization
3. Test commit blocking with failing gates
4. Document escape hatch (`--no-verify`)

### Sprint 4: Branch Workflow (Week 4)

1. Implement branch creation on contract open
2. Implement merge on successful close
3. Handle merge conflicts
4. Test full workflow end-to-end

---

## Migration from Phase 1.5

### No Breaking Changes

Phase 2 gates are **additive**. Phase 1.5 evidence infrastructure remains unchanged.

### Gradual Enforcement

Initially, gates may log warnings instead of blocking. Enforcement can be enabled gradually:

```python
ENFORCEMENT_MODE = "warn"  # "warn" | "block"
```

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| False positives blocking work | Start with `warn` mode, tune before `block` |
| Evidence format changes | Freeze evidence schema before implementing gates |
| Complex merge conflicts | Provide clear guidance on conflict resolution |
| Token approval bottleneck | Document self-approval workflow for low-risk tokens |

---

## Success Criteria

Phase 2 is complete when:

1. ✅ Contract open gates validate scope
2. ✅ Contract close gates validate evidence
3. ✅ Pre-commit hook blocks non-compliant commits
4. ✅ Branch workflow isolates contract work
5. ✅ All gates have `warn` → `block` toggle
6. ✅ Documentation complete for agent and human use

---

## Appendix: Capability Matrix Reference

From `CANONICAL CONTRACT SYSTEM.md` Section 12.2:

### ck3lens Mode

| Root | READ | WRITE | DELETE | RENAME | EXECUTE | DB_WRITE | GIT_WRITE |
|------|------|-------|--------|--------|---------|----------|-----------|
| ROOT_REPO | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| ROOT_USER_DOCS | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| ROOT_WIP | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| ROOT_STEAM | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| ROOT_GAME | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| ROOT_LAUNCHER | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |

### ck3raven-dev Mode

| Root | READ | WRITE | DELETE | RENAME | EXECUTE | DB_WRITE | GIT_WRITE |
|------|------|-------|--------|--------|---------|----------|-----------|
| ROOT_REPO | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| ROOT_USER_DOCS | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| ROOT_WIP | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| ROOT_STEAM | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| ROOT_GAME | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| ROOT_LAUNCHER | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
