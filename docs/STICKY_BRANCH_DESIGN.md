# Sticky Contextual Branching - Design Brief

> **Status:** Design Phase  
> **Author:** Agent  
> **Date:** February 6, 2026  
> **Canonical Ref:** CANONICAL_ARCHITECTURE.md Rules #1-2

---

## 1. Goal

Ensure agent safety and traceability without creating "branch spam" (fragmented history) or forcing the user to manually manage git state.

**Key Principle:** Work that spans multiple contracts stays on a single branch, preserving contiguous git history while maintaining full auditability via commit-level contract references.

---

## 2. Architectural Constraints (Non-Negotiable)

### 2.1 Single Enforcement Boundary

Per CANONICAL_ARCHITECTURE.md:

| Rule | Requirement |
|------|-------------|
| **Rule #1** | Only `enforcement.py` may deny operations |
| **Rule #2** | No permission oracles - never ask "am I allowed?" outside enforcement |

**Implications:**

- `git_tools.py` must NOT contain any deny logic (no "safety guard" deny)
- No separate `is_branch_safe()` or `BranchPolicy` class queried by tools
- `WorldAdapter` and startup code must NOT contain branch policy
- All branch policy lives INSIDE enforcement

### 2.2 All Logic as Enforcement Subroutine

Branch policy must be implemented as a private subroutine inside enforcement (e.g., `enforcement_git.py` or private helpers within `enforcement.py`).

It must be called ONLY via the enforcement entrypoint - not directly by tools or other modules.

---

## 3. Protected Branch Policy Data

Protected patterns belong in ONE place (inside enforcement):

```python
# enforcement.py (or enforcement_git.py)
PROTECTED_BRANCH_PATTERNS = [
    "main",
    "master", 
    "release/*",
    "tags/*"
]
```

- Enforcement matches against this list
- Tools do NOT access or check this list directly
- Pattern matching uses fnmatch-style globbing

---

## 4. Command Classification

### 4.1 Read-Only Commands (No Branch Restriction)

```python
READ_COMMANDS = {"status", "diff", "log", "show", "branch"}
```

- Never trigger auto-switch
- Pass through enforcement without branch checks
- No contract requirement

### 4.2 Mutating Commands (Branch Restriction Applies)

```python
MUTATING_COMMANDS = {"add", "commit", "push", "checkout", "merge", "rebase"}
```

- Trigger branch policy evaluation
- May result in deny, auto-switch, or allow
- Contract required for execution

---

## 5. Sticky Branch Logic (Inside Enforcement)

The sticky rule executes when enforcement evaluates a mutating git command:

```python
def _resolve_working_branch(current_branch: str, contract_id: str) -> BranchDecision:
    """
    Private enforcement helper - NEVER called by tools directly.
    
    Returns:
        BranchDecision with:
            - action: "stay" | "switch" | "deny"
            - target_branch: str (if switch)
            - reason: str
    """
```

### 5.1 Decision Matrix

| Current Branch | Command Type | Capability Present | Decision |
|----------------|--------------|-------------------|----------|
| Protected (main, master, etc.) | Mutating | No | **DENY** |
| Protected (main, master, etc.) | Mutating | Yes (`ensure_working_branch`) | **AUTO-SWITCH** to `agent/{contract_id}` |
| `agent/*` (any) | Mutating | Any | **STAY** (sticky) |
| Non-protected feature branch | Mutating | Any | **STAY** (collaborative) |
| Any | Read-only | Any | **ALLOW** (no branch check) |

### 5.2 Sticky Behavior Detail

When already on an `agent/*` branch:

- New contracts do NOT create new branches
- Stay on current `agent/*` branch regardless of new contract_id
- Commit messages include footer with current contract_id for traceability

Example:
```
Branch: agent/v1-2026-02-06-abc123

Commit 1: "Fix trait definition\n\n[Contract: v1-2026-02-06-abc123]"
Commit 2: "Add localization\n\n[Contract: v1-2026-02-06-def456]"  <- Different contract, same branch
```

---

## 6. Auto-Switch as Explicit Mutation

Auto-switching is a mutation and must be explicitly modeled:

### 6.1 Structured Action Result

If enforcement decides to auto-switch, it must return a structured "required actions" result:

```python
@dataclass
class EnforcementResult:
    allowed: bool
    actions: list[dict]  # e.g., [{"type": "git_checkout_new_branch", "branch": "agent/v1-..."}]
    denial_code: str | None  # e.g., "EN-GIT-D-001"
    denial_reason: str | None
```

### 6.2 Action Execution

The tool wrapper (or enforcement module if that's the convention) executes required actions with these constraints:

- **Capability gate:** Requires `ensure_working_branch` capability
- **Contract gate:** Requires active contract for mutating operations
- **Logging:** Must be logged as a policy action

### 6.3 Action Types

```python
BRANCH_ACTIONS = {
    "git_checkout_new_branch": {
        "required_capability": "ensure_working_branch",
        "requires_contract": True,
        "log_as": "policy_branch_switch"
    }
}
```

---

## 7. Reply + Logging Compliance

### 7.1 Reply Status Codes

| Status | Meaning |
|--------|---------|
| `Reply(S)` | Command executed successfully |
| `Reply(D)` | Denied by enforcement |
| `Reply(I)` | Invalid arguments |
| `Reply(E)` | Crash/error |

### 7.2 Denial Codes (Enforcement Only)

Denials must come from enforcement with stable codes:

| Code | Meaning |
|------|---------|
| `EN-GIT-D-001` | Protected branch mutation denied |
| `EN-GIT-D-002` | Missing required capability for auto-switch |
| `EN-GIT-D-003` | No active contract for mutating operation |

### 7.3 Required Log Fields

Every git operation must log:

```python
{
    "trace_id": str,
    "contract_id": str | None,
    "operation": str,
    "decision": "allow" | "deny" | "autoswitch",
    "branch_before": str,
    "branch_after": str | None,
    "actions_taken": list[str],
    "denial_code": str | None,
    "timestamp": datetime
}
```

---

## 8. Implementation Checklist

### 8.1 Files to Modify

| File | Changes |
|------|---------|
| `enforcement.py` | Add `PROTECTED_BRANCH_PATTERNS`, `_resolve_working_branch()`, branch enforcement logic |
| `git_tools.py` | Remove any deny logic, defer all decisions to enforcement |
| `capability_matrix.py` | Add `ensure_working_branch` capability (if not present) |
| `reply.py` | Ensure denial codes follow `EN-GIT-D-XXX` pattern |

### 8.2 Files that Must NOT Be Modified for Branch Logic

- `WorldAdapter`
- `startup.py` / initialization code
- Any tool file other than calling enforcement

---

## 9. Test Requirements

### 9.1 Boundary Tests

**Test:** Only enforcement can deny
- Mock git_tools to ensure no `Reply.failure()` or deny logic exists in tool code
- All denials must come from enforcement module

### 9.2 Protected Branch Tests

**Test:** Protected branch + mutating command without capability/contract
- On `main`, call `ck3_git(command="commit", ...)`
- Without `ensure_working_branch` capability → `Reply(D)` with `EN-GIT-D-001`

**Test:** Protected branch + mutating command with capability/contract
- On `main`, call `ck3_git(command="commit", ...)` with capability
- Expect auto-switch to `agent/{contract_id}` + proceed

### 9.3 Read-Only Tests

**Test:** Read-only commands never trigger auto-switch
- On `main`, call `ck3_git(command="status")`
- No branch change, `Reply(S)`

### 9.4 Sticky Behavior Tests

**Test:** Already on `agent/*`, new contract does not create new branch
- On `agent/v1-abc123`, open new contract `v1-def456`
- Call `ck3_git(command="commit", ...)`
- Stay on `agent/v1-abc123`
- Commit message includes `[Contract: v1-def456]` footer

### 9.5 Collaborative Mode Tests

**Test:** On feature branch, agent stays
- On `feat/my-feature`, call `ck3_git(command="commit", ...)`
- No branch change, `Reply(S)`

---

## 10. Optional Refinement: Explicit Branch Ensure

For stricter determinism, consider making auto-switch explicit:

1. Enforcement denies with: "Protected branch; run `ck3_git(command='ensure_branch')` first"
2. Agent must explicitly call `ck3_git(command="ensure_branch", contract_id="...")` to create/switch
3. Then proceed with original command

**Pros:**
- More deterministic flow
- Agent explicitly acknowledges branch switch

**Cons:**
- Extra round-trip
- May feel verbose

**Decision:** TBD during implementation - start with auto-switch, can tighten later if needed.

---

## 11. Summary

| Component | Responsibility |
|-----------|----------------|
| `enforcement.py` | ALL branch decisions, denials, auto-switch actions |
| `git_tools.py` | Execute commands, pass requests to enforcement, execute returned actions |
| `WorldAdapter` | Visibility only (what exists), NO policy |
| `capability_matrix.py` | Define `ensure_working_branch` capability |
| Commit messages | Include `[Contract: {id}]` footer for traceability |

**Key Invariant:** Tools never deny. Enforcement always decides. Sticky branches preserve contiguous history.
