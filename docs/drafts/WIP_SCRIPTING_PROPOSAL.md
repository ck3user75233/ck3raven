# WIP Scripting Architecture - Draft Proposal

> **Status:** DRAFT - For evaluation and possible implementation
> **Date:** December 28, 2025
> **Source:** User concern about scripts bypassing LensWorld

---

## Problem Statement

Helper scripts are sometimes necessary for:
- batch edits across multiple files
- large refactors
- repetitive fixes

**However, unrestricted scripts can bypass LensWorld by accessing the filesystem directly.**

If a script runs with full filesystem access:
- It could read mods outside the active playset
- It could write to paths the agent shouldn't touch
- LensWorld's cognitive simplification is undermined

---

## Proposed Solution: Execute Scripts via ck3_exec

### Core Principle

**The system must constrain execution, not rely on script inspection.**

Scripts cannot be trusted to stay within bounds. The execution environment must enforce bounds.

### Proposed Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Agent Creates Script                      │
│                    (writes to WIP scope)                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  SCRIPT_RUN Contract                          │
│  - Declares intent                                            │
│  - Declares expected outputs                                  │
│  - Declares allowed input paths                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      ck3_exec                                 │
│  - Validates contract                                         │
│  - Sets working_dir to WIP                                    │
│  - Passes allowed_paths from contract                         │
│  - Runs with restricted environment                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Execution Sandbox                           │
│  - Working directory: WIP only                                │
│  - Allowed reads: active local mods + WIP                     │
│  - Allowed writes: WIP only (or declared output paths)        │
│  - Filesystem access outside → NOT_FOUND                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Rules for Writing Scripts

1. **Scripts may be written only inside WIP**
   - Path: `~/.ck3raven/wip/` (ck3lens) or `<repo>/.wip/` (ck3raven-dev)
   - Agent uses `ck3_file(command="write")` to WIP path

2. **Scripts must not be treated as runtime output**
   - They are temporary assistance tools
   - Not part of any mod or project

3. **Scripts must declare their purpose via a SCRIPT_RUN contract**
   - Intent: SCRIPT_RUN
   - Allowed paths: explicitly declared
   - Expected behavior: documented

---

## Rules for Executing Scripts

1. **Scripts may only be executed via ck3_exec**
   - Never via direct Python import or subprocess
   - ck3_exec applies LensWorld constraints

2. **Execution must enforce restrictions:**

   | Access Type | Allowed Paths | Behavior Outside |
   |-------------|---------------|------------------|
   | Read | Active local mods, WIP, CK3 utility | NOT_FOUND |
   | Write | WIP only (unless contract specifies) | NOT_FOUND |
   | Working dir | WIP | Enforced |

3. **Scripts must not:**
   - Walk the full filesystem
   - Access mods outside the active playset
   - Write outside declared output paths

---

## Implementation Considerations

### Current State Analysis

**What we have now:**
- WIP workspace exists (`policy/wip_workspace.py`)
- `ck3_exec` exists with CLW policy enforcement
- CLW checks `target_paths` for scope validation
- WorldAdapter provides visibility filtering

**Gap analysis:**
- ck3_exec doesn't currently sandbox Python interpreter
- No automatic working_dir restriction for scripts
- SCRIPT_RUN intent exists but may not be fully enforced

### Possible Implementation Approaches

#### Option A: Environment Variable Sandbox

Set environment variables before script execution:
- `CK3_ALLOWED_READ_PATHS` = comma-separated list
- `CK3_ALLOWED_WRITE_PATHS` = comma-separated list
- Script must respect these (honor system)

**Weakness:** Relies on script cooperation.

#### Option B: chroot-like Working Directory

Run script with:
- `cwd` set to WIP
- Relative paths only work within WIP
- Absolute paths outside WIP → permission denied

**Strength:** OS-level enforcement.
**Weakness:** Complex on Windows.

#### Option C: Python Subprocess with Path Interception

Inject a custom `open()` function that:
- Checks paths against allowed list
- Returns NOT_FOUND for violations

**Strength:** Works at Python level.
**Weakness:** Can be bypassed by determined code.

#### Option D: Read-Only Bind Mounts (Linux/WSL only)

Mount active mod paths as read-only in a temp directory.
Run script with that as root.

**Strength:** True isolation.
**Weakness:** Platform-specific, complex.

### Recommended Approach

**Start with Option B (working directory restriction) + Option A (declared paths):**

1. Script declares allowed paths in contract
2. ck3_exec runs with `cwd=WIP`
3. Paths outside declared scope get NOT_FOUND from WorldAdapter
4. Audit log captures all file access attempts

This provides:
- Defense in depth
- Clear contract requirements
- Audit trail for violations
- Graceful failure (NOT_FOUND not exception)

---

## Contract Schema Extension

```python
@dataclass
class ScriptRunContract:
    """Contract for script execution."""
    
    contract_id: str
    intent: Literal["SCRIPT_RUN"]
    
    # Script location (must be in WIP)
    script_path: str  # Relative to WIP
    
    # Allowed input paths (read access)
    allowed_read_paths: list[str]  # Glob patterns
    
    # Allowed output paths (write access)
    allowed_write_paths: list[str]  # Glob patterns, default WIP only
    
    # Expected behavior
    description: str
    
    # Timeout
    max_runtime_seconds: int = 300
```

---

## Enforcement Model Summary

| Layer | Responsibility |
|-------|---------------|
| Contract | Declare intent and allowed paths |
| ck3_exec | Validate contract, set working_dir, pass scope |
| WorldAdapter | Return NOT_FOUND for out-of-scope paths |
| CLW | Block dangerous commands |
| Audit Logger | Record all access attempts |

**Key guarantee:** If a script attempts out-of-scope access, execution must fail safely with no filesystem leakage.

---

## Questions for Review

1. Is the current WIP isolation sufficient, or do we need stronger sandboxing?
2. Should SCRIPT_RUN contracts require explicit user approval?
3. How do we handle scripts that legitimately need to write to mod paths?
4. Should script output be automatically captured for review?

---

## Next Steps

1. Audit current WIP and ck3_exec implementation
2. Determine minimum viable sandbox requirements
3. Prototype path restriction for ck3_exec
4. Update contract schema if needed
5. Test with sample batch-edit scripts

