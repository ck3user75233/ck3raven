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

## ⚠️ Phase Boundary Rules (CRITICAL)

### BUILD NOW (Phase 1.5) — Evidence Construction

These components are SENSORS. They observe reality and emit evidence.
They do NOT make enforcement decisions.

| Component | Location | Purpose |
|-----------|----------|---------|
| `semantic_validator.py` | `tools/compliance/` | Extract definitions, resolve refs, emit evidence |
| `tokens.py` | `tools/compliance/` | NST/LXE lifecycle: propose → approve → validate |
| `arch_lint` / `code_diff_guard.py` | `scripts/guards/` | Detect architecture violations |
| Symbol extractors | `tools/compliance/` | Extract Python and CK3 symbol inventories |
| Evidence artifacts | `artifacts/` | Deterministic JSON outputs |

**Validator output schema:**
```json
{
  "definitions_added": ["symbol1", "symbol2"],
  "undefined_refs": [{"name": "bad_ref", "location": {...}}],
  "valid_refs": [{"name": "good_ref", "resolved_to": "mod/file.txt"}]
}
```

### DO NOT BUILD YET (Phase 2) — Deterministic Gates

These components are JUDGES. They use evidence to allow/deny.
They require stable sensors before implementation.

| Component | Location | Why Wait |
|-----------|----------|----------|
| Contract close enforcement | `audit_contract_close.py` caller | Needs stable evidence format |
| Target file validation | `enforcement.py` | Needs contract schema finalized |
| Branch-based commits | git integration | Needs close enforcement first |
| Commit blocking | pre-commit hook | Needs audit tool stable |

**Phase 2 will add:**
- `ck3_contract(command="close")` validates all evidence before allowing
- Writes outside declared target files are blocked proactively
- Failed validation keeps changes on contract branch (not main)

### Why This Separation?

```
Phase 1.5: Build the thermometer
Phase 2.0: Build the thermostat

The thermometer must be accurate before the thermostat can work.
```

If we build enforcement gates before validators are stable:
- Gates will have false positives/negatives
- Agents will be blocked by buggy evidence
- Trust in the system will degrade

If we build validators first and test them:
- Evidence format stabilizes
- Edge cases are discovered
- Gates can be confident in their inputs

---

## Hard Law

If compliance cannot be proven deterministically:

stop, block closure, escalate to user.

---

## Session Notes

### January 26, 2026 Session

**Focus:** Bug fixes, infrastructure improvements, documentation

**Commits:**
- `056176f` - fix: disable WIP auto-wipe on mode initialization
- `a3e3028` - feat: add Python semantic validator using VS Code IPC + pyright fallback
- `07c9fd6` - refactor: use golden_join.py for consistent symbol query patterns
- `4a423a0` - fix: remove fallbacks from Python validator, require VS Code IPC
- `fa2bcef` - feat(FEAT-001): add Instance ID button to AgentView for copy/chat

**Changes Made:**

1. **WIP Auto-Wipe Disabled**
   - Changed `wipe=True` to `wipe=False` in `server.py` and `wip_workspace.py`
   - WIP workspace now preserves files across mode initialization

2. **Python Semantic Validator (`tools/ck3lens_mcp/ck3lens/validation/python_validator.py`)**
   - Uses VS Code IPC to get Pylance diagnostics
   - No fallbacks - errors out if IPC unavailable
   - Raises `PythonValidationError` if validation cannot be performed
   - Version 1.1.0

3. **Golden Join Pattern (`tools/ck3lens_mcp/ck3lens/db/golden_join.py`)**
   - Canonical JOIN order: `symbols s → asts a → files f → content_versions cv`
   - `GOLDEN_JOIN` constant and `cvid_filter_clause()` helper
   - Refactored `search_ops.py`, `conflict_ops.py`, `unified_tools.py` to use it

4. **Instance ID Button (FEAT-001)**
   - Added `instance-id` item type to `AgentTreeItem`
   - Shows current MCP instance ID in Tools view
   - Click to copy ID, copy tool prefix, or send to chat
   - Helps agents identify correct MCP server instance

**Verified Working (No Changes Needed):**

1. **FEAT-002: Auto-detect file type**
   - Already implemented - code checks `path.endswith(".txt")` before CK3 syntax validation
   - Non-.txt files (.py, .md, .json) automatically skip CK3 validation

2. **BUG-002: Instance Sharing**
   - Working correctly via `agent_mode_{instanceId}.json` mechanism
   - Extension watches mode file for changes
   - Trace filtering by `instance_id` prevents cross-window contamination

**Phase 1.5 Status:** COMPLETE - Ready for Phase 2
