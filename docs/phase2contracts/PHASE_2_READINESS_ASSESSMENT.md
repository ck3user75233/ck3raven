# Phase 2 Deterministic Gates - Readiness Assessment

> **Assessed:** February 8, 2026  
> **Context:** ck3raven-dev mode  
> **Assessor:** Agent research of codebase infrastructure

---

## Executive Summary

**TL;DR:** Most foundational infrastructure exists but there's a critical architectural mismatch: the Phase 2 plan references `symbols_lock.py` which has been **deprecated** in favor of `semantic_validator.py`. The gate wrapper files (`contract_gates.py`, `close_gates.py`) don't exist yet. Pre-commit hooks are configured but not installed. The check functions exist in `audit_contract_close.py` but need to be wrapped as gates with the warn/block toggle.

---

## ✅ READY TO USE (Working Infrastructure)

| Component | Location | State |
|-----------|----------|-------|
| Token System (NST/LXE) | `tools/compliance/tokens.py` | 771 lines, HMAC signing, TTL expiration |
| Linter Lock | `tools/compliance/linter_lock.py` | 776 lines, active lock at `policy/locks/` |
| Locked Lint Runner | `tools/compliance/run_arch_lint_locked.py` | Scoped lint with watermarking |
| Capability Matrix | `tools/ck3lens_mcp/ck3lens/capability_matrix.py` | 204 lines, complete for both modes |
| Enforcement Module | `tools/ck3lens_mcp/ck3lens/policy/enforcement.py` | Single enforcement entry point |
| Contract V1 Schema | `tools/ck3lens_mcp/ck3lens/policy/contract_v1.py` | `open/close/cancel_contract()` implemented |
| Pre-commit Hook Script | `scripts/hooks/pre-commit` | Calls policy-check.py |
| Pre-commit Policy Check | `scripts/pre-commit-policy-check.py` | Reads trace, validates session |

---

## ⚠️ EXISTS BUT NOT READY (Needs Integration Work)

| Component | Issue | Action Required |
|-----------|-------|-----------------|
| **`symbols_lock.py`** | **DEPRECATED** - all functions return stubs | Migrate `check_symbols_diff()` in audit_contract_close.py to use `semantic_validator.py` |
| **`semantic_validator.py`** | 769 lines, produces evidence but header says "Phase 1.5 only, no enforcement" | Wire into `audit_contract_close.py` symbol diff checks |
| **`audit_contract_close.py`** | 910 lines with 6 check functions, BUT `check_symbols_diff()` imports deprecated `symbols_lock` | Fix import to use `semantic_validator.py` output format |
| **Pre-commit Installation** | `scripts/install-hooks.py` exists but NOT executed | Run `python scripts/install-hooks.py` to install |
| **`hard_gates.py`** | 1216 lines of gate implementations moved to `archive/deprecated_policy/` | Extract useful patterns for new gate files |

---

## ❌ NOT STARTED (Must Be Built)

| Component | Expected Location | Per Phase 2 Plan |
|-----------|-------------------|------------------|
| **Contract Open Gates** | `tools/ck3lens_mcp/ck3lens/policy/contract_gates.py` | SCOPE_VALIDATION, CAPABILITY_CHECK, WORK_DECLARATION_COMPLETE, SYMBOL_INTENT_REVIEW |
| **Close Gates** | `tools/ck3lens_mcp/ck3lens/policy/close_gates.py` | EVIDENCE_COMPLETE, LINTER_CLEAN, SYMBOLS_DECLARED, TARGETS_RESPECTED, TOKEN_VALID |
| **Branch Workflow** | TBD | Auto-create `contract/{id}` branch on open, merge on close |
| **Warn/Block Toggle** | TBD | `ENFORCEMENT_MODE = "warn" | "block"` setting |
| **Symbol Artifacts** | `artifacts/symbols/` | Currently EMPTY - no snapshots being produced |
| **Approved Tokens** | `policy/tokens/` | Contains only `.gitkeep` - no NST/LXE tokens in use |

---

## Critical Architecture Issue

**The Phase 2 plan (dated Jan 26, 2026) references `symbols_lock.py` but the code was deprecated.** Evidence:

```python
# From symbols_lock.py line 13:
# "Migration path: Use semantic_validator.py with git-diff file list instead."

# From audit_contract_close.py line 445:
def check_symbols_diff(...):
    from tools.compliance.symbols_lock import (  # <-- BROKEN IMPORT
        SymbolsSnapshot,
        check_new_symbols,
        ...
    )
```

This must be resolved before Phase 2 gates can work.

---

## Detailed Component Analysis

### Token System (`tools/compliance/tokens.py`)

**Status:** ✅ Complete and functional

**Key Features:**
- `TokenType` enum: `NST` (New Symbol Token), `LXE` (Lint Exception)
- `Token` dataclass with HMAC signing
- `TokenScope` for defining coverage
- Functions: `sign_token()`, `verify_token_signature()`, `load_tokens_for_contract()`, `validate_token()`, `check_nst_coverage()`, `check_lxe_coverage()`
- TTL: NST = 24 hours, LXE = 8 hours

**Current State:**
- `policy/tokens/` directory exists but contains only `.gitkeep`
- No approved tokens currently in use
- Token proposal workflow exists but not exercised

---

### Linter Lock System (`tools/compliance/linter_lock.py`)

**Status:** ✅ Complete and functional

**Key Features:**
- SHA256 hash-based file locking
- Active lock at `policy/locks/linter.lock.json`
- Verification before lint runs
- Proposed lock handling at `artifacts/locks/proposed/`

**Current State:**
- Active lock exists and validates
- Hash verification working
- Integration with `run_arch_lint_locked.py` complete

---

### Locked Lint Runner (`tools/compliance/run_arch_lint_locked.py`)

**Status:** ✅ Complete and functional

**Key Features:**
- Verifies linter lock before running
- Scoped linting via `--files` or `--base-commit` 
- Outputs watermarked reports to `artifacts/lint/`
- `LintReport` dataclass with manifest

**Current State:**
- 422 lines, fully implemented
- Integrates with `audit_contract_close.py`

---

### Semantic Validator (`tools/compliance/semantic_validator.py`)

**Status:** ⚠️ Exists but not wired into audit

**Key Features:**
- 769 lines of evidence generation code
- Extracts CK3 and Python symbol definitions
- Tracks undefined references
- Outputs `SemanticReport` JSON

**Docstring Warning:**
> "Phase Boundary: This is Phase 1.5 — evidence construction only. No enforcement logic, no token validation, no contract close integration."

**Integration Gap:**
- `audit_contract_close.py` `check_symbols_diff()` still imports `symbols_lock.py`
- Needs migration to use `semantic_validator.py` output

---

### Audit Contract Close (`tools/compliance/audit_contract_close.py`)

**Status:** ⚠️ Partially broken

**Check Functions (6 total):**

| Function | Status | Notes |
|----------|--------|-------|
| `check_linter_lock()` | ✅ Working | Verifies active lock, checks for proposed |
| `check_arch_lint()` | ✅ Working | Runs locked wrapper, verifies coverage |
| `check_playset_drift()` | ⚠️ Calls deprecated | Uses `symbols_lock.get_active_playset_identity()` |
| `check_symbols_diff()` | ❌ Broken | Imports from deprecated `symbols_lock` |
| `validate_nst_tokens()` | ✅ Working | Uses `tokens.py` correctly |
| `validate_lxe_tokens()` | ✅ Working | Uses `tokens.py` correctly |

---

### Capability Matrix (`tools/ck3lens_mcp/ck3lens/capability_matrix.py`)

**Status:** ✅ Complete and functional

**Structure:**
- `Capability` dataclass with `read`, `write`, `delete`, `subfolders_writable`
- Matrix keyed by `(mode, RootCategory, subdirectory)`
- Both `ck3lens` and `ck3raven-dev` modes fully defined

**Key Rules:**
- `ROOT_EXTERNAL` always denied
- `db/` and `daemon/` subdirs never writable
- Contract required for write/delete (enforced in `enforcement.py`)

---

### Enforcement Module (`tools/ck3lens_mcp/ck3lens/policy/enforcement.py`)

**Status:** ✅ Complete and functional

**Key Features:**
- 256 lines, single entry point
- `enforce()` function is THE canonical enforcement gate
- `Decision` enum: `ALLOW`, `DENY`, `REQUIRE_TOKEN`, `REQUIRE_CONTRACT`
- `EnforcementResult` with diagnostic failure support

---

### Pre-commit Infrastructure

**Status:** ⚠️ Exists but not installed

**Components:**
1. `scripts/hooks/pre-commit` - Shell script calling guards
2. `scripts/pre-commit-policy-check.py` - Python validation logic
3. `scripts/guards/code_diff_guard.py` - Duplicate implementation checker
4. `scripts/install-hooks.py` - Installation script
5. `.pre-commit-config.yaml` - Standard pre-commit framework config

**Current State:**
- `.git/hooks/` contains only `.sample` files
- Hook script exists in `scripts/hooks/` but not symlinked
- `install-hooks.py` never executed

**To Activate:**
```bash
python scripts/install-hooks.py
```

---

### Contract V1 (`tools/ck3lens_mcp/ck3lens/policy/contract_v1.py`)

**Status:** ✅ Complete for Phase 1.5

**Key Features:**
- `AgentMode` enum: `CK3LENS`, `CK3RAVEN_DEV`
- `Operation` enum: `READ`, `WRITE`, `DELETE`, etc.
- `RootCategory` enum for geographic scope
- `ContractV1` schema with `open_contract()`, `close_contract()`, `cancel_contract()`
- `validate_operations()` for capability matrix lookup

**Phase 2 Gap:**
- No gate evaluation on open/close
- No branch workflow integration

---

## Recommended Implementation Order

### Sprint 0: Prerequisite Fix (1-2 days)

**Goal:** Fix the broken `symbols_lock.py` dependency

1. Update `check_symbols_diff()` in `audit_contract_close.py` to use `semantic_validator.py` output format
2. Update `check_playset_drift()` to not depend on deprecated module
3. Remove or clearly mark `symbols_lock.py` as non-functional

### Sprint 1: Close Gates (Week 1)

**Goal:** Wrap existing audit checks as gates with outcomes

1. Create `tools/ck3lens_mcp/ck3lens/policy/close_gates.py`
2. Define `GateResult` with `AUTO_APPROVE`, `REQUIRE_APPROVAL`, `AUTO_DENY`
3. Wrap each audit check as a gate function
4. Add `ENFORCEMENT_MODE = "warn" | "block"` toggle
5. Update `ck3_contract(command="close")` to call gates

### Sprint 2: Open Gates (Week 2)

**Goal:** Validate contracts before work begins

1. Create `tools/ck3lens_mcp/ck3lens/policy/contract_gates.py`
2. Implement gates:
   - `SCOPE_VALIDATION` - targets exist and within root
   - `CAPABILITY_CHECK` - (mode, root, operation) allowed
   - `WORK_DECLARATION_COMPLETE` - required fields present
   - `SYMBOL_INTENT_REVIEW` - new symbols declared
3. Update `ck3_contract(command="open")` to call gates

### Sprint 3: Pre-Commit Integration (Week 3)

**Goal:** Block non-compliant commits

1. Run `python scripts/install-hooks.py`
2. Update `pre-commit-policy-check.py` to call close gates
3. Test commit blocking with failing gates
4. Document `--no-verify` escape hatch

### Sprint 4: Branch Workflow (Week 4)

**Goal:** Isolate contract work on branches

1. Implement branch creation on contract open: `contract/{contract_id}`
2. Implement merge on successful close
3. Handle merge conflicts with guidance
4. End-to-end testing

---

## Verification Commands

```bash
# Verify locked lint runner
python -m tools.compliance.run_arch_lint_locked --help

# Verify semantic evidence generator
python -m tools.compliance.semantic_validator --help

# Check linter lock exists
cat policy/locks/linter.lock.json | head -20

# Check token directory
ls -la policy/tokens/

# Check symbol artifacts (should be empty)
ls -la artifacts/symbols/

# Install pre-commit hooks
python scripts/install-hooks.py
```

---

## Decisions Captured

1. **`symbols_lock.py` deprecation happened after Phase 2 plan was drafted** → Plan document needs update to reflect `semantic_validator.py` as the source of symbol evidence

2. **Pre-commit hooks exist but are not installed** → Explicit installation step required, not automatic

3. **The check functions in `audit_contract_close.py` are reusable** → Wrap in gate format rather than rewrite from scratch

4. **Branch workflow is entirely new** → No existing code to leverage, build from scratch

5. **Token workflow is complete but unused** → Need test cases exercising NST/LXE approval flow

---

## File Reference Index

| Category | File | Lines | Purpose |
|----------|------|-------|---------|
| **Tokens** | `tools/compliance/tokens.py` | 771 | Token types, signing, validation |
| **Linting** | `tools/compliance/linter_lock.py` | 776 | Lock management |
| **Linting** | `tools/compliance/run_arch_lint_locked.py` | 422 | Scoped lint runner |
| **Symbols** | `tools/compliance/semantic_validator.py` | 769 | Evidence generation |
| **Symbols** | `tools/compliance/symbols_lock.py` | 130 | **DEPRECATED** |
| **Audit** | `tools/compliance/audit_contract_close.py` | 910 | Close-time checks |
| **Policy** | `tools/ck3lens_mcp/ck3lens/capability_matrix.py` | 204 | Permission matrix |
| **Policy** | `tools/ck3lens_mcp/ck3lens/policy/enforcement.py` | 256 | Single gate |
| **Policy** | `tools/ck3lens_mcp/ck3lens/policy/contract_v1.py` | 754 | Contract schema |
| **Hooks** | `scripts/hooks/pre-commit` | 45 | Shell hook script |
| **Hooks** | `scripts/pre-commit-policy-check.py` | 151 | Validation logic |
| **Hooks** | `scripts/install-hooks.py` | 67 | Hook installer |
| **Archive** | `archive/deprecated_policy/hard_gates.py` | 1216 | Old gate patterns |

---

## Appendix: Original Phase 2 Plan Summary

From `docs/PHASE_2_IMPLEMENTATION_PLAN.md` (dated January 26, 2026):

**Phase 2 Goal:** Implement deterministic gates that:
1. Evaluate declared scope at contract open time
2. Validate compliance evidence at contract close time  
3. Block non-compliant commits at git hook time

**Gate Outcomes:**
- `AUTO_APPROVE` - Contract is valid, work may proceed
- `REQUIRE_APPROVAL` - Human approval required
- `AUTO_DENY` - Contract is invalid, cannot proceed

**Originally Planned Sprint Timeline:**
- Sprint 1: Close Gates (Week 1)
- Sprint 2: Open Gates (Week 2)
- Sprint 3: Pre-Commit Integration (Week 3)
- Sprint 4: Branch Workflow (Week 4)

**Risk Identified in Original Plan:**
> "Evidence format changes → Freeze evidence schema before implementing gates"

This risk materialized with the `symbols_lock.py` deprecation.
