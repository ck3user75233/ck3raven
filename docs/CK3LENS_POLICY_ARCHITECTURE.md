# CK3LENS Policy Architecture

> **Status:** CANONICAL  
> **Scope:** ck3lens agent mode ONLY  
> **Last Updated:** December 28, 2025  
> **Related:** [LENSWORLD.md](LENSWORLD.md) - Visibility layer architecture

---

## 0. Relationship to LensWorld

**This document defines POLICY.** For visibility (what exists), see [LENSWORLD.md](LENSWORLD.md).

| Layer | Question | This Document |
|-------|----------|---------------|
| **LensWorld** | What exists and can be referenced? | ❌ See LENSWORLD.md |
| **Policy** | What actions are permitted on references? | ✅ This document |

**Key principle:** LensWorld and Policy are orthogonal:
- LensWorld never returns ALLOW or DENY - only FOUND or NOT_FOUND
- Policy only evaluates actions on references that LensWorld resolved successfully
- Out-of-lens references result in NOT_FOUND (policy never runs)

---

## 1. Purpose of ck3lens Mode

ck3lens exists to:
- Analyze CK3 mods
- Debug mod conflicts
- Create and modify local mods in the active playset
- Support compatching workflows

It does NOT exist to:
- Explore the filesystem freely
- Modify infrastructure (ck3raven source)
- Discover mods outside user intent

---

## 2. Core Design Principles

### Database-Projected View

ck3lens operates on a **database-projected view** of the active playset.
Filesystem access is exceptional, explicit, and approval-gated.

### Core Invariants

1. Mods must be **ingested into the database** to be visible
2. Only mods in the **active playset** are visible by default
3. Only **active local mods** are mutable
4. Vanilla and workshop mods are **always immutable**
5. Filesystem access **never expands** mod discovery
6. ck3lens **cannot write Python** except to the WIP workspace
7. ck3raven source is **read-only** (no writes even with contract)

---

## 3. Scope Domains

| Scope Domain | Visibility | Read/Search | Write/Edit | Delete | Notes |
|--------------|------------|-------------|------------|--------|-------|
| **ACTIVE PLAYSET (DB VIEW)** | LensWorld | ✅ | ❌ | ❌ | Normal universe |
| **ACTIVE LOCAL MODS** | LensWorld | ✅ | ✅ (contract) | 🔶 (approval) | Only mutable scope |
| **ACTIVE WORKSHOP MODS** | LensWorld | ✅ | ❌ | ❌ | Immutable |
| **VANILLA GAME** | LensWorld | ✅ | ❌ | ❌ | Immutable |
| **INACTIVE MODS** | Outside Lens | 🔶 User-prompt | ❌ | ❌ | NOT_FOUND by default |
| **CK3 UTILITY FILES** | LensWorld | ✅ | ❌ | ❌ | Logs, saves, debug files |
| **CK3RAVEN SOURCE** | LensWorld | ✅ (logged) | ❌ (always) | ❌ (always) | Read-only, for bug context |
| **CK3LENS WIP WORKSPACE** | LensWorld | ✅ | ✅ | ✅ | Disposable Python scripts |
| **LAUNCHER / REGISTRY** | LensWorld | ✅ (diagnostic) | 🔶 (repair tool) | 🔶 (repair tool) | Via ck3_repair only |

### Key Clarifications

- **Inactive mods**: Outside the lens - result in NOT_FOUND, not DENY. User prompt required to expand lens.
- **CK3RAVEN SOURCE**: In lens (for bug reports), but policy prohibits writes unconditionally.
- **Python files**: Policy restricts Python writes to WIP workspace only.

---

## 4. CK3LENS WIP WORKSPACE

### Purpose
- Temporary helper scripts
- Batch transformations
- Intermediate outputs

### Location
```
~/.ck3raven/wip/
```
Address: `wip:/<relative_path>`

### Properties
- Added to `.gitignore` if inside repo
- Auto-wiped at session start (on `ck3_get_mode_instructions` call)
- Best-effort cleanup of files older than 24h

### Rules
1. Not a mod - not loadable by CK3
2. No user approval required for deletion
3. All script execution via `ck3_exec`
4. Script output can only go to:
   - WIP workspace itself
   - Active local mods (via normal write contract)
5. Scripts must declare what files they will read/write
6. Mismatch between declaration and actual behavior → execution denied

---

## 5. Intent Types (Required)

Every contract must declare exactly one `intent_type`. Missing → AUTO_DENY.

| Intent Type | Description | Operations | Special Requirements |
|-------------|-------------|------------|---------------------|
| **COMPATCH** | Modify active local mods for compatibility/integration/corrections | Write/Edit/Delete | targets, snippets, rollback, acceptance_tests |
| **BUGPATCH** | Patch a bug in another mod via local override | Write/Edit/Delete | targets, snippets, rollback, acceptance_tests |
| **RESEARCH_MOD_ISSUES** | Read-only research into mod conflicts, errors, behavior | Read only | findings evidence (DB/logs) |
| **RESEARCH_BUGREPORT** | Read-only research to file bug report about ck3raven tooling | Read only | findings, optional ck3raven source read |
| **SCRIPT_WIP** | Draft/run scripts in WIP for batch transformations | WIP write/execute | script hash, syntax validation, approval binding |

---

## 6. Contract Requirements by Intent

### 6.1 COMPATCH / BUGPATCH (Write/Edit/Delete)

**Required fields:**
- `targets`: List of `{mod_id, rel_path}` - must resolve to concrete files
- `operation`: edit | write | delete
- `before_after_snippets`: Up to 3 blocks
- `change_summary`: Required if more than 3 files
- `rollback_plan`: How to undo
- `acceptance_tests`: DIFF_SANITY + VALIDATION

**For deletes additionally:**
- `explicit_file_list`: No globs allowed
- `approval_token`: Tier B token required

### 6.2 RESEARCH_MOD_ISSUES (Read-Only)

**Required fields:**
- `findings_evidence`: DB excerpts and/or log excerpts
- No write operations permitted

### 6.3 RESEARCH_BUGREPORT (Read-Only)

**Required fields:**
- `findings_evidence`: Description of issue being reported
- `ck3raven_source_access`: Optional, limited read-only access by contract

### 6.4 SCRIPT_WIP

**Required fields:**
- `script_content`: The Python script
- `script_hash`: SHA256 of script content
- `syntax_validation`: Proof script passed syntax check
- `declared_reads`: Files script will read
- `declared_writes`: Files script will write (WIP or active local mods only)

---

## 7. Acceptance Tests

### Mandatory for Write/Edit

**DIFF_SANITY** (Hard requirement):
- Proposed scope must match actual touched files
- If mismatch → contract cannot complete

**VALIDATION** (Best-effort):
- Run whatever CK3Raven validation/parsing checks exist
- If full validator not available, fallback to:
  - Basic parse/syntax sanity where supported
  - No made-up IDs/symbols introduced (reviewed via snippets)

### Not Required
- Game launch/load check (too slow)

---

## 8. Script Execution (SCRIPT_WIP)

### Pre-Approval Requirements
1. Script must be in WIP workspace
2. Script must pass syntax validation (Python compile)
3. Script hash recorded in contract
4. Declared reads/writes must be specified

### Approval Semantics
- Approval is **reusable** within contract (not single-use)
- Bound to:
  - Script hash (content identity)
  - Contract scope
  - TTL
- If script changes (hash change) → approval invalidated, re-approval required

### Execution Constraints
- Script can only write to:
  - WIP workspace
  - Active local mods (if declared and approved)
- Mismatch between declared and actual file access → execution blocked

---

## 9. Token Tiers

### Tier A — Capability (None for ck3lens)
- No auto-grant tokens for mod discovery
- No auto-grant for inactive mods

### Tier B — Approval Required
| Token Type | Use Case | TTL |
|------------|----------|-----|
| `DELETE_LOCALMOD` | Delete files in active local mods | 15 min |
| `READ_INACTIVE_MOD` | Read inactive mod (after user prompt) | 30 min |
| `REGISTRY_REPAIR` | Repair mod registry | 15 min |
| `CACHE_DELETE` | Delete launcher cache | 15 min |
| `SCRIPT_EXECUTE` | Execute WIP script (reusable per hash) | 60 min |

---

## 10. User-Prompted Exception Flow

For accessing **inactive mods** (outside lens):

### Requirement
The agent must be able to demonstrate that the user explicitly requested access to a specific inactive mod.

### Enforcement
Policy engine checks for evidence of user prompt:
- User message must contain explicit reference to the mod path or identity
- Pattern: "read mod X" or "look at [path]" or "check [mod name] which is not in my playset"

### Flow
1. User explicitly asks agent to read an inactive mod
2. Agent cites the user's request in token request
3. Policy validates user prompt exists
4. Token granted (Tier B, with user confirmation)
5. **Lens is temporarily expanded** to include the requested mod

---

## 11. Hard Gates

| Condition | Result |
|-----------|--------|
| Missing `intent_type` | AUTO_DENY |
| Write outside active local mods | POLICY_VIOLATION |
| Write to workshop/vanilla | POLICY_VIOLATION |
| Write to ck3raven source (any mode) | POLICY_VIOLATION |
| Access inactive mod without lens expansion | NOT_FOUND |
| Utility file write | POLICY_VIOLATION |
| Python write outside WIP workspace | POLICY_VIOLATION |
| Script execution without syntax validation | AUTO_DENY |
| Script execution with declared/actual mismatch | AUTO_DENY |
| Write contract without targets | AUTO_DENY |
| Write contract without snippets (if >0 files) | AUTO_DENY |
| Write contract without DIFF_SANITY acceptance test | AUTO_DENY |
| Delete without explicit file list | AUTO_DENY |
| Delete without Tier B approval token | AUTO_DENY |

---

## 12. ck3_repair Tool (LAUNCHER Domain)

### Purpose
Specialized tool for launcher and registry repair operations.

### Commands
| Command | Description | Token Required |
|---------|-------------|----------------|
| `query` | Analyze mod registry for issues | ❌ (read-only) |
| `diagnose_launcher` | Check launcher state | ❌ (read-only) |
| `repair_registry` | Fix mod registry issues | ✅ REGISTRY_REPAIR |
| `delete_cache` | Clear launcher cache | ✅ CACHE_DELETE |

### Scope
Only available in ck3lens mode. Requires LAUNCHER domain in contract for repair operations.

---

## 13. Implementation Checklist

### Phase 1: Core Policy Infrastructure
- [x] Create WorldAdapter and WorldRouter (see LENSWORLD.md)
- [ ] Create `ck3lens_policy.py` with scope domain enum
- [ ] Implement hard gates as pure functions
- [ ] Add `intent_type` enum and validation
- [ ] Create WIP workspace lifecycle (init, wipe, path management)
- [ ] Update `ck3_file` to enforce ck3lens restrictions

### Phase 2: Contract System
- [ ] Update contract schema with new required fields
- [ ] Implement per-intent validation
- [ ] Add DIFF_SANITY acceptance test check
- [ ] Add change_preview/snippet validation

### Phase 3: Script Execution
- [ ] Implement script syntax validation gate
- [ ] Add script hash binding to approval tokens
- [ ] Implement declared vs actual file access check
- [ ] Create script execution sandbox

### Phase 4: Token System
- [ ] Remove any Tier A auto-grants for mod discovery
- [ ] Implement Tier B tokens for ck3lens
- [ ] Add user-prompt evidence check for inactive mod access

### Phase 5: ck3_repair Tool
- [ ] Create `ck3_repair` tool with query/diagnose/repair/delete commands
- [ ] Add LAUNCHER domain to scope domains
- [ ] Implement registry repair logic
- [ ] Implement cache deletion logic

### Phase 6: Documentation
- [x] Create LENSWORLD.md
- [ ] Update agent instructions with new rules
- [ ] Add examples to COPILOT_CK3LENS.md
- [ ] Document user-prompt patterns for inactive mods

---

## Appendix A: Quick Reference - What Can ck3lens Do?

| Action | LensWorld | Policy | Result |
|--------|-----------|--------|--------|
| Search active playset via database | Found | Allowed | ✅ |
| Read active local mods | Found | Allowed | ✅ |
| Read active workshop mods | Found | Allowed | ✅ |
| Read vanilla game files | Found | Allowed | ✅ |
| Read ck3raven source | Found | Allowed (logged) | ✅ |
| Read inactive mods | NOT_FOUND | N/A | ❌ (expand lens first) |
| Write active local mods | Found | Requires contract | 🔶 |
| Delete active local mod files | Found | Requires contract + token | 🔶 |
| Write Python scripts | Found (WIP only) | Allowed | 🔶 |
| Execute scripts | Found (WIP) | Requires approval | 🔶 |
| Write to ck3raven source | Found | NEVER | ❌ |
| Write to workshop/vanilla | Found | NEVER | ❌ |
| Enumerate arbitrary filesystem | NOT_FOUND | N/A | ❌ |

---

## Appendix B: Contract Examples

### Example: COMPATCH Contract
```yaml
intent_type: COMPATCH
targets:
  - mod_id: MSC
    rel_path: common/traits/zzz_msc_brave_fix.txt
operation: write
before_after_snippets:
  - file: common/traits/zzz_msc_brave_fix.txt
    before: null  # New file
    after: |
      brave_fix = {
        # Fixed definition
      }
change_summary: "Adding missing trait override"
rollback_plan: "Delete the file"
acceptance_tests:
  - DIFF_SANITY
  - VALIDATION
```

### Example: SCRIPT_WIP Contract
```yaml
intent_type: SCRIPT_WIP
script_content: |
  # Batch rename script
  import os
  for f in declared_inputs:
      # process...
script_hash: "sha256:abc123..."
syntax_validation: PASSED
declared_reads:
  - mod_id: MSC
    rel_path: common/traits/*.txt
declared_writes:
  - wip: batch_output.json
  - mod_id: MSC
    rel_path: common/traits/zzz_batch_result.txt
```
