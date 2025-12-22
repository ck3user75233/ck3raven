# Policy Enforcement Architecture

**Version 1.3** — December 2025

This document describes the enforcement architecture for the CK3 Lens agent policy system, covering both `ck3lens` (CK3 modding) and `ck3raven-dev` (infrastructure development) agent modes.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         AGENT (Claude/etc)                         │
│  - Receives mode instructions (ck3lens or ck3raven-dev)            │
│  - Makes MCP tool calls                                             │
│  - Builds ArtifactBundle for delivery                               │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      MCP SERVER (FastMCP)                          │
│                                                                     │
│  ┌─────────────────┐    ┌─────────────────┐    ┌────────────────┐  │
│  │  Pre-Call       │    │  Tool           │    │  Tool Trace    │  │
│  │  Wrapper        │───▶│  Execution      │───▶│  Logger        │  │
│  │  (scope inject) │    │                 │    │  (JSONL)       │  │
│  └─────────────────┘    └─────────────────┘    └────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼ (on delivery attempt)
┌─────────────────────────────────────────────────────────────────────┐
│                     POLICY VALIDATOR                                │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                  Enforcement Pipeline                        │   │
│  │                                                              │   │
│  │  1. trace_required        ─── Verify tool trace exists      │   │
│  │  2. claims_validation     ─── Check claims[] evidence       │   │
│  │  3. artifact_bundle_schema ── Validate structure            │   │
│  │  4. artifact_bundle_validator ── CK3 content semantics      │   │
│  │  5. symbol_manifest_check ─── Verify declared symbols       │   │
│  │  6. post_trace            ─── Analyze session trace         │   │
│  │  7. server_only           ─── Issue completion state        │   │
│  │                                                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  Output: PolicyOutcome { deliverable, violations[], summary }       │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     DELIVERY GATE                                   │
│  - If deliverable=true: Accept artifacts, issue completion          │
│  - If deliverable=false: Return violations, block delivery          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Enforcement Stages (Server-Internal)

These are **NOT MCP tools**. They are internal validation stages in the policy validator pipeline.

| Stage | Description | Blocking? |
|-------|-------------|-----------|
| `trace_required` | Verify non-empty tool trace exists for session | Yes |
| `claims_validation` | Check `claims[]` list against evidence contracts | Yes |
| `pre_call_wrapper` | Inject/validate scope fields before tool execution | Yes |
| `post_trace` | Analyze completed trace for rule violations | Configurable |
| `artifact_bundle_schema` | Validate ArtifactBundle Pydantic structure | Yes |
| `artifact_bundle_validator` | Validate CK3 content semantics (paths, domains) | Yes |
| `symbol_manifest_check` | Verify declared new symbols exist in artifacts | Yes |
| `ck3_validator` | Run CK3 parse + reference validation | Yes |
| `python_validator` | Run Python syntax/import validation | Yes |
| `server_only` | Server-controlled state transitions | Yes |
| `advisory` | Log warning, don't block delivery | No |
| `manual_review` | Requires human review (not automated) | No |

---

## 3. Claims Evidence Contract

The `no_silent_assumptions` rule requires agents to attach structured claims to delivery attempts.

### 3.1 Claims Schema

```python
@dataclass
class Claim:
    claim_type: Literal["existence", "non_existence", "behavior", "value"]
    subject: str  # What is being claimed (e.g., "trait:brave exists")
    evidence_tool_calls: list[str]  # Trace IDs providing evidence
    
@dataclass
class ClaimsManifest:
    claims: list[Claim]
    negative_claims: list[Claim]  # Subset where claim_type == "non_existence"
```

### 3.2 Validation Rules

1. **Every claim must have ≥1 evidence_tool_call**
   - Trace ID must exist in session trace
   - Tool result must support the claim

2. **Evidence must match scope rules**
   - For `ck3lens`: playset_id and vanilla_version_id must match session
   - For `ck3raven-dev`: No scope restrictions

3. **Non-existence claims require `ck3_confirm_not_exists`**
   - The `ck3_confirm_not_exists` tool performs exhaustive fuzzy search
   - Returns `can_claim_not_exists: true` only after thorough check

### 3.3 Example

```json
{
  "claims": [
    {
      "claim_type": "existence",
      "subject": "trait:brave defined in vanilla",
      "evidence_tool_calls": ["trace_001_search_symbols"]
    },
    {
      "claim_type": "non_existence",
      "subject": "trait:my_custom_trait does not exist",
      "evidence_tool_calls": ["trace_002_confirm_not_exists"]
    }
  ]
}
```

---

## 4. Scope Enforcement (ck3lens mode)

### 4.1 Required Scope Fields

Every scoped tool call in `ck3lens` mode must include:

| Field | Required | Description |
|-------|----------|-------------|
| `playset_id` | Yes | Active playset ID from session |
| `vanilla_version_id` | Yes | Selected vanilla version |
| `roots` | Optional | List of mod/vanilla roots being searched |
| `mod_ids` | Optional | Specific mod IDs being queried |

### 4.2 Pre-Call Wrapper Behavior

```python
def pre_call_wrapper(tool_name: str, args: dict) -> dict:
    """Inject scope fields before tool execution."""
    if is_scoped_tool(tool_name):
        session = get_session()
        args["playset_id"] = session.playset_id
        args["vanilla_version_id"] = session.vanilla_version_id
    return args
```

### 4.3 Post-Trace Verification

After session completion, verify:
- All scoped calls have `playset_id` matching session
- All scoped calls have `vanilla_version_id` matching session (if set)
- No calls query mods outside `active_mod_ids`
- No calls access roots outside allowed set

---

## 5. Mode-Specific Rules

### 5.1 CK3LENS Mode

| Rule | Severity | Status | Notes |
|------|----------|--------|-------|
| `active_playset_enforcement` | error | active | Scope injection + verification |
| `database_first_search` | **warning** | enhancement | Downgraded until FS traces complete |
| `ck3_file_model_required` | error | active | A/B/C/D model required |
| `file_path_domain_validation` | error | active | Path matches CK3 domain |
| `new_symbol_declaration` | error | active | New symbols must be declared |
| `symbol_resolution` | error | active | All refs must resolve |
| `conflict_alignment` | **warning** | enhancement | Downgraded until touched_units complete |
| `negative_claims` | error | active | Requires ck3_confirm_not_exists |

### 5.2 CK3RAVEN-DEV Mode

| Rule | Severity | Status | Notes |
|------|----------|--------|-------|
| `python_validation_required` | error | active | Syntax + import validation |
| `schema_change_declaration` | warning | enhancement | Breaking vs non-breaking |
| `preserve_uncertainty` | warning | tbc | Requires manual review |

---

## 6. Database-First Search Exception

The `database_first_search` rule has explicit exceptions:

```yaml
filesystem_allowed_if:
  - database_rebuilding   # DB status shows incomplete/rebuilding
  - database_incomplete   # DB build_state missing or failed
  - domain_not_indexed    # Specific domain not yet in DB
```

### 6.1 How It Works

1. Agent calls `ck3_get_db_status` to check database state
2. If `is_complete: false` or status is `rebuilding/partial`:
   - Filesystem access is permitted
   - No `database_first_search` violation raised
3. If database is complete:
   - Agent must use DB search tools first
   - Filesystem access without prior DB search raises warning

### 6.2 Current Status

- **Severity: warning** (not error) during enhancement phase
- Will upgrade to error when:
  - FS tool calls include full trace metadata
  - Justification field supported in FS tool args

---

## 7. Testing the Policy

### 7.1 Unit Tests

Located in `tests/test_policy_validator.py`:

```python
# Test trace required
def test_empty_trace_error()

# Test scope enforcement
def test_scope_playset_missing_error()
def test_active_playset_not_fetched_error()

# Test file model
def test_ck3_file_model_missing_error()
def test_ck3_file_model_present_passes()

# Test Python validation
def test_python_validation_required()
def test_python_validation_passes_with_call()
```

### 7.2 Integration Testing

To verify rules work end-to-end:

1. **Trace Recording Test**
   ```python
   # Make tool calls, verify trace logged
   result = ck3_search_symbols(query="test")
   trace = get_session_trace()
   assert len(trace) > 0
   ```

2. **Delivery Gate Test**
   ```python
   # Attempt delivery without required validation
   result = ck3_validate_policy(mode="ck3lens", artifact_bundle={...})
   assert result["deliverable"] == False
   assert "CK3_VALIDATION_REQUIRED" in [v["code"] for v in result["violations"]]
   ```

3. **Scope Injection Test**
   ```python
   # Verify scope fields auto-injected
   result = ck3_search_symbols(query="test")
   trace_entry = get_last_trace()
   assert trace_entry["args"]["playset_id"] == session.playset_id
   ```

### 7.3 Manual Testing Checklist

- [ ] Create artifact bundle without ck3_file_model → expect error
- [ ] Attempt delivery with empty trace → expect TRACE_REQUIRED error
- [ ] Search outside active playset → expect OUT_OF_SCOPE_SEARCH error
- [ ] Claim symbol doesn't exist without ck3_confirm_not_exists → expect error
- [ ] Submit Python code without ck3_validate_python → expect error

---

## 8. Upgrade Path

### 8.1 Enhancement Rules → Error

Rules currently at `severity: warning` with `status: enhancement`:

| Rule | Upgrade Condition | Target |
|------|-------------------|--------|
| `database_first_search` | FS trace metadata complete | error |
| `conflict_alignment` | touched_units extraction complete | error |

### 8.2 Adding Claims Validation

1. Add `claims: list[Claim]` field to ArtifactBundle
2. Implement `claims_validation` enforcement stage
3. Update agent mode instructions to require claims
4. Enable enforcement in policy

---

## 9. File Locations

| File | Purpose |
|------|---------|
| `policy/agent_policy.yaml` | Policy specification |
| `policy/types.py` | Core types (Violation, PolicyOutcome, etc.) |
| `policy/loader.py` | YAML loading with caching |
| `policy/validator.py` | Core validation orchestrator |
| `policy/ck3lens_rules.py` | CK3-specific rule implementations |
| `policy/ck3raven_dev_rules.py` | Python dev rule implementations |
| `policy/trace_helpers.py` | Trace analysis utilities |
| `contracts.py` | ArtifactBundle, ArtifactFile models |
| `trace.py` | Tool trace logging |

---

## 10. Summary

The policy enforcement architecture provides:

1. **Clear separation** between MCP tools and enforcement stages
2. **Evidence contracts** requiring claims with tool-call proof
3. **Scope enforcement** with auto-injection and verification
4. **Graceful degradation** for enhancement-status rules (warning not error)
5. **Explicit upgrade paths** from warning → error as tooling matures
6. **Testable rules** with unit and integration test coverage
