# Comprehensive Policy Enforcement Implementation Plan

> **Status:** IMPLEMENTATION PLAN  
> **Created:** December 28, 2025  
> **Purpose:** Define centralized policy enforcement for ALL write-capable MCP tools

---

## 1. Problem Statement

Policy enforcement is currently:
- **Fragmented**: Each tool implements (or doesn't implement) its own enforcement
- **Incomplete**: Only `ck3_file` has contract validation; 8+ other tools have none
- **Inconsistent**: Different validation logic in different places

### Current State Audit

| Tool | Can Modify | Has Contract Check | Has Mode Check | Status |
|------|------------|-------------------|----------------|--------|
| `ck3_file(write/edit)` | Files | ✅ | ✅ | Fixed |
| `ck3_file(delete/rename)` | Files | ❌ | ❌ | **Missing** |
| `ck3_exec` | Shell commands | ❌ (has CLW policy) | ✅ | **Partial** |
| `ck3_git(add/commit/push)` | Git state | ❌ | ❌ | **Missing** |
| `ck3_db_delete` | Database rows | ❌ | ❌ | **Missing** |
| `ck3_repair` | Launcher/cache | ❌ | ❌ | **Missing** |
| `ck3_create_override_patch` | Creates files | ❌ | ❌ | **Missing** |
| `ck3_conflicts(resolve)` | DB state | ❌ | ❌ | **Missing** |
| `ck3_playset(add/remove/create)` | Playset config | ❌ | ❌ | **Missing** |
| `refresh_file_in_db` | DB state | ❌ | ❌ | **Missing** |

---

## 2. Target Architecture

### 2.1 Centralized Gate Function

Create a single `enforce_policy()` function that ALL write-capable tools must call:

```python
# tools/ck3lens_mcp/ck3lens/policy/enforcement.py

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List

class OperationType(Enum):
    """Categories of operations requiring enforcement."""
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    FILE_RENAME = "file_rename"
    GIT_MODIFY = "git_modify"        # add, commit
    GIT_PUSH = "git_push"            # push, pull
    GIT_REWRITE = "git_rewrite"      # amend, rebase, force push
    DB_MODIFY = "db_modify"          # resolve conflicts, update playset
    DB_DELETE = "db_delete"          # delete rows
    SHELL_SAFE = "shell_safe"        # read-only commands
    SHELL_WRITE = "shell_write"      # commands that write
    SHELL_DESTRUCTIVE = "shell_destructive"  # rm, drop, etc.
    LAUNCHER_REPAIR = "launcher_repair"
    CACHE_DELETE = "cache_delete"

@dataclass
class EnforcementRequest:
    """Request to validate an operation."""
    operation: OperationType
    mode: str  # "ck3lens" or "ck3raven-dev"
    
    # Context (varies by operation type)
    target_path: Optional[str] = None  # For file ops
    mod_name: Optional[str] = None     # For ck3lens mod ops
    rel_path: Optional[str] = None     # For ck3lens mod ops
    command: Optional[str] = None      # For shell ops
    
    # Existing auth
    contract_id: Optional[str] = None
    token_id: Optional[str] = None

@dataclass  
class EnforcementResult:
    """Result of policy enforcement."""
    allowed: bool
    reason: str
    required_contract: bool = False
    required_token: Optional[str] = None  # Token type if needed
    contract_id: Optional[str] = None
    token_id: Optional[str] = None

def enforce_policy(request: EnforcementRequest) -> EnforcementResult:
    """
    Central policy enforcement gate.
    
    ALL write-capable tools MUST call this before performing their operation.
    This is the SINGLE source of truth for policy decisions.
    """
    ...
```

### 2.2 Mode-Specific Rules

#### ck3raven-dev Mode

| Operation | Requirement |
|-----------|-------------|
| FILE_WRITE | Contract with matching `allowed_paths` |
| FILE_DELETE | Contract + `DELETE_SOURCE` token |
| FILE_RENAME | Contract with matching `allowed_paths` |
| GIT_MODIFY | Contract (git add, commit) |
| GIT_PUSH | Contract |
| GIT_REWRITE | `GIT_REWRITE_HISTORY` token |
| DB_MODIFY | Contract |
| DB_DELETE | Contract + `DB_DELETE_DATA` token |
| SHELL_SAFE | No restriction |
| SHELL_WRITE | Contract |
| SHELL_DESTRUCTIVE | Contract + token |
| LAUNCHER_REPAIR | **PROHIBITED** (ck3lens only) |
| CACHE_DELETE | **PROHIBITED** (ck3lens only) |

#### ck3lens Mode

| Operation | Requirement |
|-----------|-------------|
| FILE_WRITE | Contract with `targets` including mod_id+rel_path |
| FILE_DELETE | Contract + `DELETE_LOCALMOD` token |
| FILE_RENAME | Contract with matching targets |
| GIT_MODIFY | Contract (on local mod) |
| GIT_PUSH | Contract |
| GIT_REWRITE | `GIT_REWRITE_HISTORY` token |
| DB_MODIFY | Contract (playset changes) |
| DB_DELETE | **PROHIBITED** (user's mod data) |
| SHELL_SAFE | No restriction |
| SHELL_WRITE | Contract + WIP only |
| SHELL_DESTRUCTIVE | Contract + token + WIP only |
| LAUNCHER_REPAIR | `REGISTRY_REPAIR` token |
| CACHE_DELETE | `CACHE_DELETE` token |

### 2.3 Integration Pattern

Every write-capable tool follows this pattern:

```python
@mcp.tool()
def ck3_some_tool(...):
    from ck3lens.policy.enforcement import enforce_policy, EnforcementRequest, OperationType
    from ck3lens.agent_mode import get_agent_mode
    from ck3lens.work_contracts import get_active_contract
    
    mode = get_agent_mode()
    contract = get_active_contract()
    
    # Build enforcement request
    request = EnforcementRequest(
        operation=OperationType.FILE_WRITE,
        mode=mode,
        target_path=...,
        contract_id=contract.contract_id if contract else None,
        token_id=token_id,
    )
    
    # Enforce policy
    result = enforce_policy(request)
    
    if not result.allowed:
        return {
            "success": False,
            "error": result.reason,
            "required_contract": result.required_contract,
            "required_token": result.required_token,
        }
    
    # Proceed with operation...
```

---

## 3. Implementation Phases

### Phase 1: Core Enforcement Module

**Files to create:**
- `tools/ck3lens_mcp/ck3lens/policy/enforcement.py` - Central gate
- `tools/ck3lens_mcp/ck3lens/policy/operation_types.py` - Operation enum

**Tasks:**
1. Create `OperationType` enum with all operation categories
2. Create `EnforcementRequest` and `EnforcementResult` dataclasses
3. Implement `enforce_policy()` with mode-specific rules
4. Add contract scope validation (reuse existing `validate_path_against_contract`)
5. Add token validation integration
6. Add comprehensive logging to trace

### Phase 2: Integrate with ck3_file

**Files to modify:**
- `tools/ck3lens_mcp/ck3lens/unified_tools.py`

**Tasks:**
1. Refactor `_file_write`, `_file_write_raw` to use `enforce_policy()`
2. Refactor `_file_edit`, `_file_edit_raw` to use `enforce_policy()`
3. Add enforcement to `_file_delete`
4. Add enforcement to `_file_rename`
5. Remove inline policy checks (now in central module)

### Phase 3: Integrate with ck3_exec

**Files to modify:**
- `tools/ck3lens_mcp/server.py` (ck3_exec function)

**Tasks:**
1. Classify commands by operation type (safe/write/destructive)
2. Call `enforce_policy()` with appropriate operation type
3. Add contract scope check for write commands
4. Integrate with existing CLW policy layer

### Phase 4: Integrate with ck3_git

**Files to modify:**
- `tools/ck3lens_mcp/server.py` (ck3_git function)

**Tasks:**
1. Map git commands to operation types:
   - status/diff/log → READ (no enforcement)
   - add/commit → GIT_MODIFY
   - push/pull → GIT_PUSH
   - amend/rebase → GIT_REWRITE
2. Call `enforce_policy()` for each category
3. Add mode-aware enforcement (ck3lens: local mods only)

### Phase 5: Integrate with Database Tools

**Files to modify:**
- `tools/ck3lens_mcp/server.py` (ck3_db_delete, ck3_conflicts, ck3_playset)

**Tasks:**
1. Add enforcement to `ck3_db_delete`
2. Add enforcement to `ck3_conflicts(command="resolve")`
3. Add enforcement to `ck3_playset(command="add_mod/remove_mod/reorder/create")`
4. Add enforcement to `refresh_file_in_db`

### Phase 6: Integrate with Specialized Tools

**Files to modify:**
- `tools/ck3lens_mcp/server.py`

**Tasks:**
1. Add enforcement to `ck3_repair(command="repair_registry/delete_cache")`
2. Add enforcement to `ck3_create_override_patch`
3. Verify all deprecated tools are actually deprecated (not callable)

### Phase 7: Testing and Validation

**Files to create:**
- `tests/test_policy_enforcement.py`

**Tasks:**
1. Test each operation type with valid contract → allowed
2. Test each operation type without contract → denied
3. Test each operation type with wrong scope → denied
4. Test token requirements for destructive ops
5. Test mode-specific rules (ck3lens vs ck3raven-dev)
6. Test trace logging captures all decisions

---

## 4. Contract Schema Updates

### Current Contract Fields
```python
@dataclass
class WorkContract:
    contract_id: str
    intent: str
    canonical_domains: list[str]
    allowed_paths: list[str]  # For ck3raven-dev
    capabilities: list[str]
    status: str
    
    # CK3Lens specific
    intent_type: str
    targets: list[dict]  # [{mod_id, rel_path}] for ck3lens
```

### Required Additions
```python
    # Operations this contract authorizes
    authorized_operations: list[str]  # OperationType values
    
    # For git operations
    git_scope: str  # "local_mods" | "ck3raven" | "none"
    
    # For shell operations
    shell_scope: str  # "wip_only" | "repo" | "none"
```

---

## 5. Hard Gates (Immutable Rules)

These rules are enforced regardless of contract or token:

| Rule | Enforcement |
|------|-------------|
| ck3raven-dev cannot write to mods | `mode == "ck3raven-dev" && target in mods → DENY` |
| ck3lens cannot write to ck3raven source | `mode == "ck3lens" && target in ck3raven → DENY` |
| ck3lens cannot write to workshop/vanilla | Always DENY |
| Git history rewrite requires token | No contract can bypass |
| Delete operations require token | No contract can bypass |
| No writes without mode initialized | `mode is None → DENY` |

---

## 6. Trace Logging Requirements

Every `enforce_policy()` call MUST log:

```json
{
    "ts": 1735412345.123,
    "tool": "policy.enforce",
    "operation": "FILE_WRITE",
    "mode": "ck3raven-dev",
    "target": "tools/ck3lens_mcp/server.py",
    "contract_id": "wcp-2025-12-28-abc123",
    "decision": "ALLOW",
    "reason": "Contract scope valid"
}
```

---

## 7. Migration Strategy

### Step 1: Create Module (Non-Breaking)
- Create `enforcement.py` with all logic
- No changes to existing tools yet
- Write comprehensive tests

### Step 2: Integrate One Tool at a Time
- Start with `ck3_file` (already partially done)
- Verify behavior matches existing
- Run tests after each integration

### Step 3: Deprecate Inline Checks
- Remove inline policy checks from `file_policy.py`
- Route everything through `enforce_policy()`

### Step 4: Full Rollout
- Integrate remaining tools
- Final test pass
- Update documentation

---

## 8. Success Criteria

1. **Single Source of Truth**: All policy decisions flow through `enforce_policy()`
2. **100% Coverage**: Every write-capable tool calls enforcement
3. **Consistent Behavior**: Same rules apply regardless of tool
4. **Full Trace**: Every decision is logged
5. **Test Coverage**: Each operation type has test cases
6. **Documentation**: Updated policy docs reflect implementation

---

## 9. Estimated Effort

| Phase | Files | Estimated Time |
|-------|-------|----------------|
| Phase 1: Core Module | 2 new | 2 hours |
| Phase 2: ck3_file | 2 modified | 1 hour |
| Phase 3: ck3_exec | 1 modified | 1 hour |
| Phase 4: ck3_git | 1 modified | 1 hour |
| Phase 5: DB Tools | 1 modified | 1 hour |
| Phase 6: Specialized | 1 modified | 1 hour |
| Phase 7: Testing | 1 new | 2 hours |
| **Total** | **9 files** | **9 hours** |

---

## 10. Open Questions

1. Should `ck3_search` and other read-only tools also go through enforcement (for trace logging)?
2. Should contract scope be validated at tool entry or at enforcement time?
3. How should "emergency bypass" tokens work (if at all)?
4. Should enforcement be sync or could it be async for performance?
