# CK3 Raven Policy Evolution - Review & Implementation Guide

## Executive Summary

The current `ck3_file` tool has hardcoded path restrictions that conflate **capability** (what the tool can do) with **policy** (what it should do in context). This prevents `ck3raven-dev` mode from editing infrastructure files, even though that's its primary purpose. This document captures all observations from our review and provides a detailed implementation roadmap.

---

## Part 1: Observations & Current State Analysis

### 1.1 Terminology (Finalized)

| Term | Definition |
|------|------------|
| **Active playset** | The enabled set of mods (local + workshop) currently configured for the game session. This is a fundamental project concept - the configuration determining what content is being analyzed/patched. |
| **Active local mods** | The editable subset: local mods that are enabled in the active playset. This is the ONLY scope ck3lens should write/delete. |
| **Local mods** | All mods in `Documents/Paradox Interactive/Crusader Kings III/mod/`. Editable in theory, but only active local mods are in-scope for normal operations. |
| **Workshop mods** | Mods in `steamapps/workshop/content/1158310/`. Always read-only. Never editable. |
| **ck3raven source** | The Python infrastructure in the `ck3raven/` directory. Editable only by `ck3raven-dev` mode. |

**Action required:** Update all documentation and code comments to use these terms consistently. The term "live mods" should be deprecated.

### 1.2 Current Architecture Flaw

```
CURRENT (broken):
┌─────────────┐
│  ck3_file   │──► Hardcoded path checks ──► Execute or Reject
└─────────────┘
     │
     └── Tool decides what's allowed based on "live_mods" whitelist
         No consultation of agent mode, contracts, or tokens
```

```
REQUIRED (correct):
┌─────────────┐     ┌───────────────┐
│  ck3_file   │────►│  file_policy  │────► Execute or Reject
└─────────────┘     └───────────────┘
                           │
                    Consults:
                    ├── Current agent mode
                    ├── Active contract (if any)
                    ├── Approval tokens
                    └── Path validation rules
```

### 1.3 Mode Boundaries (Strict Separation)

There is **no conceivable overlapping need** between the two modes:

| Operation | ck3lens mode | ck3raven-dev mode |
|-----------|--------------|-------------------|
| **Read** active playset content | ✅ Always | ✅ Always |
| **Read** outside playset (workshop/other local) | 🔶 Token (scoped to specific path) | ✅ Always (read-only is safe for dev) |
| **Read** ck3raven source | ❌ Never (not its domain) | ✅ Always |
| **Write/Edit** active local mods | ✅ With contract | ❌ Never (not its job) |
| **Delete** in active local mods | 🔶 Token required (scoped) | ❌ Never (not its job) |
| **Write/Edit** ck3raven source | ❌ Never | ✅ With contract |
| **Delete** ck3raven source files | ❌ Never | 🔶 Token required |
| **Launcher cache / mod registry repair** | 🔶 Special token | ❌ Never |
| **Write** to workshop mods | ❌ Never | ❌ Never |
| **Write** to vanilla game files | ❌ Never | ❌ Never |

**Key insight:** Mode separation is the PRIMARY enforcement layer. Even if an agent opens a contract or has a token, mode boundaries are inviolable.

### 1.4 Token System: Current vs Required

**Current state (problematic):**
- Agent calls `ck3_token(command="request", token_type="...", reason="...")`
- Token is **auto-granted** with TTL
- No human-in-the-loop
- No logic gates evaluate the request
- Tokens provide audit trail but not actual control

**Required state:**

| Token Tier | Examples | Granting Mechanism |
|------------|----------|-------------------|
| **Tier A: Capability tokens** (auto-grant with audit) | `READ_EXTERNAL` | Auto-grant if path is specific (no broad globs). Rate limited. Logged. |
| **Tier B: Approval tokens** (user confirmation required) | `DELETE_LOCALMOD`, `DELETE_INFRA`, `REGISTRY_REPAIR`, `FORCE_PUSH` | Must show branded approval UI with impact summary. Cannot be batched with "approve all". |

**VS Code approval concern:** User noted that VS Code's generic approval prompts lead to "approve all" behavior. Solution: ck3lens approval prompts must be:
1. Visually distinct (branded)
2. Show concrete impact (diff snippets, file list)
3. Non-batchable (not affected by "approve all commands")

### 1.5 Contract System: Current vs Required

**Current state (problematic):**
- Agent self-declares `intent` and `allowed_paths`
- No validation of paths against intent
- No rejection of overly broad patterns
- Contract provides audit trail but agent can still violate it
- **Critical gap:** Nothing prevents agent from declaring `allowed_paths=["ck3raven/**"]`

**Correction to earlier statement:** The policy layer DOES enforce `allowed_paths` at operation time. The gap is that the contract OPENING has no gates - any `allowed_paths` list is accepted. So the bypass is at contract creation, not contract enforcement.

**Required state:**

Contracts must pass **logic gates** at opening time:

| Gate | Rule | Auto-Deny Triggers |
|------|------|-------------------|
| **Mode gate** | Contract domain must match current mode | ck3raven-dev contract targeting mods; ck3lens contract targeting ck3raven source |
| **Path-shape gate** | Reject overly broad globs | `**` at root level; `**/*.py`; paths without directory anchor |
| **Cardinality gate** | Limit scope size | `MAX_PATHS_PER_CONTRACT = 20`; `MAX_FILES_MATCHED = 50` |
| **Domain exclusivity gate** | Single domain per contract | Contract requesting both `infra/` and `mods/` domains |
| **Intent-path plausibility** | Keywords in intent should relate to paths | Intent mentions "Windows shell" but paths include `rendering/` |

**Contracts cannot expand capability; they can only narrow it.**

### 1.6 File Addressing: `mod_name` + `rel_path`

**Why this scheme:**
- `mod_name` identifies which mod from the playset (maps to `content_version_id` in DB)
- `rel_path` is the relative path within that mod (e.g., `common/traits/my_trait.txt`)
- Avoids fragile absolute paths that vary per user

**What `mod_name` should be:**
- The mod's **descriptor name** (from `.mod` file)
- Example inputs: `"MiniSuperCompatch"`, `"Lowborn Rise Expanded"`, `"EPE"`

**Ambiguity handling:**
If `mod_name` matches multiple mods (broken registry state):
1. Error with: `"Multiple mods match 'X': [path1, path2]. Mod registry may need repair."`
2. Suggest `ck3_repair` tool

**Configuration concern:** Local mods path should be in config, not hardcoded. Verify and fix.

### 1.7 `ck3_repair` Tool (New)

Proposed specialized tool for ck3lens mode only:

| Command | Description | Token Required |
|---------|-------------|----------------|
| `query` | Analyze mod registry for issues | ❌ (read-only) |
| `repair_registry` | Fix mod registry issues | ✅ `REGISTRY_REPAIR` |
| `delete_launcher_cache` | Clear launcher cache | ✅ `CACHE_DELETE` |
| `diagnose_launcher` | Check launcher settings/state | ❌ (read-only) |

**Launcher-related paths to manage:**
- `Documents/Paradox Interactive/Crusader Kings III/launcher-v2.sqlite`
- `Documents/Paradox Interactive/Crusader Kings III/launcher/` directory
- Possibly: `AppData/Local/Programs/Paradox Interactive/launcher-v2/` (check)

### 1.8 Sub-Agent Considerations

**Two potential uses:**

1. **Contract approval sub-agent (real-time):**
   - Reviews contract open requests
   - Can approve, deny, or escalate to user
   - Generates human-readable impact summary
   - **Constraint:** Cannot approve what hard gates would deny

2. **Audit review sub-agent (async):**
   - Reads all logs periodically
   - Identifies patterns of concern
   - Suggests policy improvements
   - Flags anomalies for user review

**Key principle:** Sub-agents provide intelligence but not authority. The policy gates are the root of authority.

### 1.9 Agent Behavior Model

**Important insight from user:** Agents are not trying to be deceptive. They simply have difficulty maintaining many constraints while focused on an outcome. Shortcuts are always appealing.

**Implication:** Logic gates at contract/token time are valuable precisely because they add friction at decision points. The agent won't try to game the gates - it will accept the guardrails.

---

## Part 2: Implementation Roadmap

### Phase 1: Extract Policy Layer from `ck3_file`

**Goal:** Create `file_policy.py` as the single source of truth for file operation permissions.

#### Step 1.1: Define Policy Data Structures

```python
# tools/ck3lens_mcp/ck3lens/policy/file_policy.py

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from pathlib import Path

class FileOperation(Enum):
    READ = "read"
    WRITE = "write"
    EDIT = "edit"
    DELETE = "delete"
    RENAME = "rename"
    LIST = "list"

class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_TOKEN = "require_token"

class PathDomain(Enum):
    ACTIVE_LOCAL_MOD = "active_local_mod"      # Editable mod in playset
    LOCAL_MOD = "local_mod"                      # Local mod not in playset
    WORKSHOP_MOD = "workshop_mod"                # Steam workshop (read-only)
    CK3RAVEN_SOURCE = "ck3raven_source"          # Infrastructure code
    VANILLA = "vanilla"                          # Game files (read-only)
    OTHER = "other"                              # Anything else

@dataclass
class FileRequest:
    operation: FileOperation
    path: Path                          # Absolute path being accessed
    agent_mode: str                     # "ck3lens" or "ck3raven-dev"
    contract_id: Optional[str] = None
    token_id: Optional[str] = None
    
@dataclass  
class FileDecision:
    decision: Decision
    reason: str
    required_token_type: Optional[str] = None
    domain: Optional[PathDomain] = None
```

#### Step 1.2: Implement Path Domain Classification

```python
def classify_path(path: Path, config: Config) -> PathDomain:
    """Determine which domain a path belongs to."""
    path_str = str(path.resolve()).lower()
    
    # Check ck3raven source
    ck3raven_root = config.ck3raven_root.lower()
    if path_str.startswith(ck3raven_root):
        return PathDomain.CK3RAVEN_SOURCE
    
    # Check active local mods (from active playset)
    for mod_path in config.get_active_local_mod_paths():
        if path_str.startswith(mod_path.lower()):
            return PathDomain.ACTIVE_LOCAL_MOD
    
    # Check all local mods
    local_mods_root = config.local_mods_path.lower()
    if path_str.startswith(local_mods_root):
        return PathDomain.LOCAL_MOD
    
    # Check workshop
    workshop_root = config.workshop_path.lower()
    if path_str.startswith(workshop_root):
        return PathDomain.WORKSHOP_MOD
    
    # Check vanilla
    vanilla_root = config.vanilla_path.lower()
    if path_str.startswith(vanilla_root):
        return PathDomain.VANILLA
    
    return PathDomain.OTHER
```

#### Step 1.3: Implement Policy Evaluation Matrix

```python
# Policy matrix: (mode, operation, domain) -> Decision
POLICY_MATRIX = {
    # ck3lens mode
    ("ck3lens", FileOperation.READ, PathDomain.ACTIVE_LOCAL_MOD): Decision.ALLOW,
    ("ck3lens", FileOperation.READ, PathDomain.LOCAL_MOD): Decision.REQUIRE_TOKEN,  # READ_EXTERNAL
    ("ck3lens", FileOperation.READ, PathDomain.WORKSHOP_MOD): Decision.REQUIRE_TOKEN,  # READ_EXTERNAL
    ("ck3lens", FileOperation.READ, PathDomain.CK3RAVEN_SOURCE): Decision.DENY,
    ("ck3lens", FileOperation.READ, PathDomain.VANILLA): Decision.ALLOW,  # Needed for reference
    
    ("ck3lens", FileOperation.WRITE, PathDomain.ACTIVE_LOCAL_MOD): Decision.ALLOW,  # Contract required
    ("ck3lens", FileOperation.WRITE, PathDomain.LOCAL_MOD): Decision.DENY,
    ("ck3lens", FileOperation.WRITE, PathDomain.WORKSHOP_MOD): Decision.DENY,
    ("ck3lens", FileOperation.WRITE, PathDomain.CK3RAVEN_SOURCE): Decision.DENY,
    ("ck3lens", FileOperation.WRITE, PathDomain.VANILLA): Decision.DENY,
    
    ("ck3lens", FileOperation.DELETE, PathDomain.ACTIVE_LOCAL_MOD): Decision.REQUIRE_TOKEN,  # DELETE_LOCALMOD
    ("ck3lens", FileOperation.DELETE, PathDomain.LOCAL_MOD): Decision.DENY,
    ("ck3lens", FileOperation.DELETE, PathDomain.WORKSHOP_MOD): Decision.DENY,
    ("ck3lens", FileOperation.DELETE, PathDomain.CK3RAVEN_SOURCE): Decision.DENY,
    
    # ck3raven-dev mode
    ("ck3raven-dev", FileOperation.READ, PathDomain.ACTIVE_LOCAL_MOD): Decision.ALLOW,
    ("ck3raven-dev", FileOperation.READ, PathDomain.LOCAL_MOD): Decision.ALLOW,
    ("ck3raven-dev", FileOperation.READ, PathDomain.WORKSHOP_MOD): Decision.ALLOW,
    ("ck3raven-dev", FileOperation.READ, PathDomain.CK3RAVEN_SOURCE): Decision.ALLOW,
    ("ck3raven-dev", FileOperation.READ, PathDomain.VANILLA): Decision.ALLOW,
    
    ("ck3raven-dev", FileOperation.WRITE, PathDomain.ACTIVE_LOCAL_MOD): Decision.DENY,  # Not its job
    ("ck3raven-dev", FileOperation.WRITE, PathDomain.LOCAL_MOD): Decision.DENY,
    ("ck3raven-dev", FileOperation.WRITE, PathDomain.WORKSHOP_MOD): Decision.DENY,
    ("ck3raven-dev", FileOperation.WRITE, PathDomain.CK3RAVEN_SOURCE): Decision.ALLOW,  # Contract required
    ("ck3raven-dev", FileOperation.WRITE, PathDomain.VANILLA): Decision.DENY,
    
    ("ck3raven-dev", FileOperation.DELETE, PathDomain.ACTIVE_LOCAL_MOD): Decision.DENY,
    ("ck3raven-dev", FileOperation.DELETE, PathDomain.CK3RAVEN_SOURCE): Decision.REQUIRE_TOKEN,  # DELETE_INFRA
}

def evaluate_file_policy(request: FileRequest, config: Config) -> FileDecision:
    """Main policy evaluation entry point."""
    domain = classify_path(request.path, config)
    
    # Look up base decision from matrix
    key = (request.agent_mode, request.operation, domain)
    base_decision = POLICY_MATRIX.get(key, Decision.DENY)
    
    # Mode boundary is inviolable - even with token
    if base_decision == Decision.DENY:
        return FileDecision(
            decision=Decision.DENY,
            reason=f"Mode {request.agent_mode} cannot {request.operation.value} in {domain.value}",
            domain=domain
        )
    
    # Check if token satisfies REQUIRE_TOKEN
    if base_decision == Decision.REQUIRE_TOKEN:
        if request.token_id and validate_token_for_path(request.token_id, request.path):
            return FileDecision(decision=Decision.ALLOW, reason="Token approved", domain=domain)
        else:
            return FileDecision(
                decision=Decision.REQUIRE_TOKEN,
                reason=f"Token required for {request.operation.value} in {domain.value}",
                required_token_type=get_required_token_type(request.operation, domain),
                domain=domain
            )
    
    # ALLOW - but check contract for write operations
    if request.operation in (FileOperation.WRITE, FileOperation.EDIT, FileOperation.DELETE):
        contract = get_active_contract()
        if not contract:
            return FileDecision(
                decision=Decision.DENY,
                reason=f"No active contract for {request.operation.value} operation",
                domain=domain
            )
        if not path_matches_contract(request.path, contract):
            return FileDecision(
                decision=Decision.DENY,
                reason=f"Path not in contract allowed_paths",
                domain=domain
            )
    
    return FileDecision(decision=Decision.ALLOW, reason="Policy check passed", domain=domain)
```

#### Step 1.4: Refactor `ck3_file` to Use Policy Layer

```python
# In server.py, modify ck3_file function

@mcp.tool()
def ck3_file(
    command: Literal["get", "read", "write", "edit", "delete", "rename", "refresh", "list"],
    path: str | None = None,
    mod_name: str | None = None,
    rel_path: str | None = None,
    # ... other params
) -> dict:
    """Unified file operations tool."""
    from ck3lens.policy.file_policy import evaluate_file_policy, FileRequest, FileOperation
    
    # Resolve path
    if mod_name and rel_path:
        resolved_path = resolve_mod_path(mod_name, rel_path)
        if resolved_path.get("error"):
            return resolved_path
        target_path = Path(resolved_path["full_path"])
    elif path:
        target_path = Path(path)
    else:
        return {"error": "Must provide either path or (mod_name + rel_path)"}
    
    # Get current mode
    current_mode = get_current_agent_mode()  # From trace or session
    
    # Map command to operation
    operation_map = {
        "read": FileOperation.READ,
        "get": FileOperation.READ,
        "write": FileOperation.WRITE,
        "edit": FileOperation.EDIT,
        "delete": FileOperation.DELETE,
        "rename": FileOperation.RENAME,
        "list": FileOperation.READ,
        "refresh": FileOperation.WRITE,
    }
    operation = operation_map.get(command, FileOperation.READ)
    
    # Build request and evaluate policy
    request = FileRequest(
        operation=operation,
        path=target_path,
        agent_mode=current_mode,
        contract_id=get_active_contract_id(),
        token_id=token_id,  # passed as parameter
    )
    
    decision = evaluate_file_policy(request, get_config())
    
    # Handle decision
    if decision.decision == Decision.DENY:
        return {"success": False, "error": decision.reason, "domain": decision.domain.value}
    
    if decision.decision == Decision.REQUIRE_TOKEN:
        return {
            "success": False,
            "error": decision.reason,
            "required_token_type": decision.required_token_type,
            "hint": f"Use ck3_token to request a {decision.required_token_type} token"
        }
    
    # Proceed with actual operation (existing implementation)
    # ... rest of existing ck3_file logic
```

---

### Phase 2: Implement Contract Logic Gates

**Goal:** Validate contracts at creation time, not just at operation time.

#### Step 2.1: Define Gate Functions

```python
# tools/ck3lens_mcp/ck3lens/policy/contract_gates.py

from dataclasses import dataclass
from typing import List, Optional
import re
from fnmatch import fnmatch

@dataclass
class GateResult:
    passed: bool
    gate_name: str
    reason: str

def check_mode_gate(mode: str, allowed_paths: List[str], config: Config) -> GateResult:
    """Ensure contract paths match mode's allowed domains."""
    for path_pattern in allowed_paths:
        # Normalize pattern for checking
        if mode == "ck3lens":
            # ck3lens cannot touch ck3raven source
            if "ck3raven" in path_pattern.lower():
                return GateResult(
                    passed=False,
                    gate_name="mode_gate",
                    reason=f"ck3lens mode cannot include ck3raven paths: {path_pattern}"
                )
        elif mode == "ck3raven-dev":
            # ck3raven-dev cannot touch mods
            local_mods = config.local_mods_path.lower()
            if local_mods in path_pattern.lower() or "mod/" in path_pattern.lower():
                return GateResult(
                    passed=False,
                    gate_name="mode_gate",
                    reason=f"ck3raven-dev mode cannot include mod paths: {path_pattern}"
                )
    return GateResult(passed=True, gate_name="mode_gate", reason="Mode boundaries respected")

def check_path_shape_gate(allowed_paths: List[str]) -> GateResult:
    """Reject overly broad glob patterns."""
    forbidden_patterns = [
        r"^\*\*/",           # Starts with **/ (matches everything)
        r"^\*\*$",           # Just ** 
        r"^\*/",             # Starts with */ 
        r"\*\*/\*\.py$",     # **/*.py - too broad
        r"\*\*/\*\.txt$",    # **/*.txt - too broad
    ]
    
    for path_pattern in allowed_paths:
        for forbidden in forbidden_patterns:
            if re.match(forbidden, path_pattern):
                return GateResult(
                    passed=False,
                    gate_name="path_shape_gate",
                    reason=f"Pattern too broad: {path_pattern}. Must anchor to specific directory."
                )
        
        # Must have at least one concrete directory component
        if not re.search(r"[a-zA-Z_][a-zA-Z0-9_]*[/\\]", path_pattern):
            return GateResult(
                passed=False,
                gate_name="path_shape_gate",
                reason=f"Pattern lacks directory anchor: {path_pattern}"
            )
    
    return GateResult(passed=True, gate_name="path_shape_gate", reason="Path shapes acceptable")

def check_cardinality_gate(allowed_paths: List[str], config: Config) -> GateResult:
    """Limit contract scope size."""
    MAX_PATTERNS = 20
    MAX_MATCHED_FILES = 50
    
    if len(allowed_paths) > MAX_PATTERNS:
        return GateResult(
            passed=False,
            gate_name="cardinality_gate",
            reason=f"Too many path patterns: {len(allowed_paths)} > {MAX_PATTERNS}"
        )
    
    # Count matching files (simplified - actual implementation would scan)
    matched_count = estimate_matched_files(allowed_paths, config)
    if matched_count > MAX_MATCHED_FILES:
        return GateResult(
            passed=False,
            gate_name="cardinality_gate",
            reason=f"Patterns match too many files: ~{matched_count} > {MAX_MATCHED_FILES}"
        )
    
    return GateResult(passed=True, gate_name="cardinality_gate", reason="Scope size acceptable")

def check_domain_exclusivity_gate(allowed_paths: List[str], config: Config) -> GateResult:
    """Ensure contract doesn't span multiple domains."""
    domains_touched = set()
    
    for path_pattern in allowed_paths:
        if "ck3raven" in path_pattern.lower():
            domains_touched.add("infra")
        if config.local_mods_path.lower() in path_pattern.lower():
            domains_touched.add("mods")
    
    if len(domains_touched) > 1:
        return GateResult(
            passed=False,
            gate_name="domain_exclusivity_gate",
            reason=f"Contract spans multiple domains: {domains_touched}. Use separate contracts."
        )
    
    return GateResult(passed=True, gate_name="domain_exclusivity_gate", reason="Single domain")

def check_intent_path_plausibility(intent: str, allowed_paths: List[str]) -> GateResult:
    """Basic heuristic: do paths seem related to intent?"""
    # Keyword to path-component mapping
    intent_keywords = {
        "shell": ["exec", "subprocess", "command", "terminal"],
        "windows": ["exec", "subprocess", "platform"],
        "policy": ["policy", "clw", "token", "contract"],
        "parser": ["parser", "lexer", "ast"],
        "database": ["db", "schema", "sqlite", "query"],
        "mcp": ["mcp", "server", "tool"],
        "trait": ["trait", "common/traits"],
        "event": ["event", "events/"],
        "decision": ["decision", "common/decisions"],
    }
    
    intent_lower = intent.lower()
    relevant_components = []
    
    for keyword, components in intent_keywords.items():
        if keyword in intent_lower:
            relevant_components.extend(components)
    
    if not relevant_components:
        # No keywords matched - can't validate, allow
        return GateResult(passed=True, gate_name="intent_plausibility", reason="No keyword match (allowed)")
    
    # Check if at least one path contains a relevant component
    paths_str = " ".join(allowed_paths).lower()
    for component in relevant_components:
        if component in paths_str:
            return GateResult(passed=True, gate_name="intent_plausibility", reason=f"Path matches intent keyword: {component}")
    
    return GateResult(
        passed=False,
        gate_name="intent_plausibility",
        reason=f"Intent mentions {[k for k in intent_keywords if k in intent_lower]} but paths don't include related files"
    )

def validate_contract_open(
    mode: str,
    intent: str,
    allowed_paths: List[str],
    config: Config
) -> tuple[bool, List[GateResult]]:
    """Run all gates on contract open request."""
    gates = [
        check_mode_gate(mode, allowed_paths, config),
        check_path_shape_gate(allowed_paths),
        check_cardinality_gate(allowed_paths, config),
        check_domain_exclusivity_gate(allowed_paths, config),
        check_intent_path_plausibility(intent, allowed_paths),
    ]
    
    all_passed = all(g.passed for g in gates)
    return all_passed, gates
```

#### Step 2.2: Integrate Gates into Contract Opening

```python
# In work_contracts.py or wherever ck3_contract is implemented

def open_contract(intent: str, allowed_paths: List[str], ...) -> dict:
    """Open a new work contract with gate validation."""
    from ck3lens.policy.contract_gates import validate_contract_open
    
    mode = get_current_agent_mode()
    config = get_config()
    
    # Run all gates
    passed, gate_results = validate_contract_open(mode, intent, allowed_paths, config)
    
    # Log all gate evaluations (even successful ones)
    for gate in gate_results:
        audit_log("contract_gate", {
            "gate": gate.gate_name,
            "passed": gate.passed,
            "reason": gate.reason,
            "intent": intent,
            "paths": allowed_paths,
        })
    
    if not passed:
        failed_gates = [g for g in gate_results if not g.passed]
        return {
            "success": False,
            "error": "Contract rejected by policy gates",
            "failed_gates": [{"gate": g.gate_name, "reason": g.reason} for g in failed_gates],
        }
    
    # Proceed with contract creation
    # ... existing logic
```

---

### Phase 3: Token System Overhaul

**Goal:** Add user confirmation for high-risk tokens.

#### Step 3.1: Define Token Tiers

```python
# tools/ck3lens_mcp/ck3lens/policy/tokens.py

from enum import Enum

class TokenTier(Enum):
    AUTO_GRANT = "auto_grant"       # Low risk, auto-approve with audit
    USER_APPROVAL = "user_approval"  # High risk, requires user confirmation

TOKEN_TIERS = {
    "READ_EXTERNAL": TokenTier.AUTO_GRANT,
    "DELETE_LOCALMOD": TokenTier.USER_APPROVAL,
    "DELETE_INFRA": TokenTier.USER_APPROVAL,
    "REGISTRY_REPAIR": TokenTier.USER_APPROVAL,
    "CACHE_DELETE": TokenTier.USER_APPROVAL,
    "FORCE_PUSH": TokenTier.USER_APPROVAL,
    "GIT_REWRITE_HISTORY": TokenTier.USER_APPROVAL,
}
```

#### Step 3.2: User Approval Flow (VS Code Integration)

```python
# For USER_APPROVAL tier tokens, we need to:
# 1. Generate an approval request ID
# 2. Send request to VS Code extension via IPC
# 3. Extension shows branded, non-batchable dialog
# 4. Wait for user response
# 5. Complete or reject token creation

@dataclass
class ApprovalRequest:
    request_id: str
    token_type: str
    reason: str
    paths: List[str]
    impact_summary: str  # Human-readable impact
    diff_snippets: Optional[List[dict]] = None  # For edits: from/to previews

def request_token_with_approval(token_type: str, reason: str, paths: List[str]) -> dict:
    """Request a token that requires user approval."""
    tier = TOKEN_TIERS.get(token_type, TokenTier.USER_APPROVAL)
    
    if tier == TokenTier.AUTO_GRANT:
        # Validate scope, then auto-grant
        if not validate_path_specificity(paths):
            return {"success": False, "error": "Paths too broad for auto-grant"}
        return create_token(token_type, paths)
    
    # USER_APPROVAL tier
    approval_request = ApprovalRequest(
        request_id=generate_id(),
        token_type=token_type,
        reason=reason,
        paths=paths,
        impact_summary=generate_impact_summary(token_type, paths),
    )
    
    # Send to VS Code extension
    response = send_approval_request_to_vscode(approval_request)
    
    if response.approved:
        return create_token(token_type, paths)
    else:
        return {"success": False, "error": "User denied token request", "reason": response.denial_reason}
```

#### Step 3.3: VS Code Extension Approval UI

The extension needs a new approval dialog component:

```typescript
// In ck3lens-explorer extension

interface ApprovalRequest {
    requestId: string;
    tokenType: string;
    reason: string;
    paths: string[];
    impactSummary: string;
    diffSnippets?: Array<{file: string; from: string; to: string}>;
}

async function showApprovalDialog(request: ApprovalRequest): Promise<{approved: boolean; reason?: string}> {
    // Create branded, detailed dialog
    const detail = [
        `**Token Type:** ${request.tokenType}`,
        `**Reason:** ${request.reason}`,
        `**Affected Paths:**`,
        ...request.paths.map(p => `  - ${p}`),
        ``,
        `**Impact:** ${request.impactSummary}`,
    ].join('\n');
    
    // Show as modal - cannot be dismissed by "approve all"
    const result = await vscode.window.showWarningMessage(
        `CK3 Lens: Approval Required`,
        { modal: true, detail },
        'Approve',
        'Deny',
        'Show Details'
    );
    
    if (result === 'Approve') {
        return { approved: true };
    } else if (result === 'Show Details') {
        // Open detailed view in webview
        await showDetailedApprovalPanel(request);
        return await waitForPanelDecision(request.requestId);
    } else {
        return { approved: false, reason: 'User denied' };
    }
}
```

---

### Phase 4: Configuration Cleanup

**Goal:** Remove hardcoded paths, use config file.

#### Step 4.1: Config Schema

```python
# tools/ck3lens_mcp/ck3lens/config.py

from dataclasses import dataclass
from pathlib import Path
import json

@dataclass
class CK3LensConfig:
    # Paths (should not be hardcoded)
    ck3raven_root: Path
    local_mods_path: Path
    workshop_path: Path
    vanilla_path: Path
    database_path: Path
    
    # Policy settings
    max_paths_per_contract: int = 20
    max_files_per_contract: int = 50
    
    @classmethod
    def load(cls, config_path: Path | None = None) -> "CK3LensConfig":
        """Load from config file or environment."""
        if config_path is None:
            config_path = Path.home() / ".ck3raven" / "config.json"
        
        if config_path.exists():
            with open(config_path) as f:
                data = json.load(f)
            return cls(**data)
        
        # Fall back to environment detection
        return cls.detect_from_environment()
    
    def get_active_local_mod_paths(self) -> List[Path]:
        """Get paths of local mods in active playset."""
        # Query database for active playset mods
        # Return only those in local_mods_path
        ...
```

#### Step 4.2: Audit and Remove Hardcoded Paths

Search for hardcoded paths in:
- `server.py`
- `workspace.py`
- Any files in `ck3lens/` directory

Replace all with `config.X` references.

---

### Phase 5: Create `ck3_repair` Tool

```python
@mcp.tool()
def ck3_repair(
    command: Literal["query", "repair_registry", "delete_launcher_cache", "diagnose_launcher"],
    target: str | None = None,
) -> dict:
    """
    Repair launcher and mod registry issues.
    
    ck3lens mode only. Requires approval token for destructive operations.
    
    Commands:
    
    command=query            → Analyze mod registry for issues (no token)
    command=repair_registry  → Fix mod registry issues (REGISTRY_REPAIR token)
    command=delete_launcher_cache → Clear launcher cache (CACHE_DELETE token)
    command=diagnose_launcher → Check launcher state (no token)
    """
    from ck3lens.policy.file_policy import require_mode
    
    # Mode check - ck3lens only
    require_mode("ck3lens")
    
    if command == "query":
        return analyze_mod_registry()
    
    elif command == "diagnose_launcher":
        return diagnose_launcher_state()
    
    elif command == "repair_registry":
        # Requires token
        if not has_valid_token("REGISTRY_REPAIR"):
            return {
                "success": False,
                "error": "REGISTRY_REPAIR token required",
                "hint": "Use ck3_token to request approval"
            }
        return perform_registry_repair(target)
    
    elif command == "delete_launcher_cache":
        if not has_valid_token("CACHE_DELETE"):
            return {
                "success": False, 
                "error": "CACHE_DELETE token required"
            }
        return delete_launcher_cache()
```

---

### Phase 6: Fix `ck3_exec` Windows Shell Issue

This was the original task that exposed these gaps.

```python
# In server.py, around line 1943

# Actually execute
try:
    import platform
    
    # On Windows, use PowerShell to support & and other PS syntax
    if platform.system() == "Windows":
        ps_command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        proc = subprocess.run(
            ps_command,
            shell=False,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
    else:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
```

---

## Part 3: Implementation Priority

| Priority | Task | Complexity | Blocks |
|----------|------|------------|--------|
| **P0** | Fix `ck3_exec` Windows shell bug | Low | All terminal operations |
| **P1** | Create `file_policy.py` with mode/domain checks | Medium | ck3_file refactor |
| **P2** | Refactor `ck3_file` to use policy layer | Medium | ck3raven-dev file editing |
| **P3** | Implement contract logic gates | Medium | Preventing scope bypass |
| **P4** | Token tier system + user approval | High | Secure destructive ops |
| **P5** | Config cleanup (remove hardcoded paths) | Low | Clean architecture |
| **P6** | Create `ck3_repair` tool | Medium | User convenience |
| **P7** | VS Code approval UI | High | User confirmation UX |

---

## Part 4: Testing Checklist

After implementation, verify:

- [ ] `ck3raven-dev` can read/write/edit files in `ck3raven/` with contract
- [ ] `ck3raven-dev` CANNOT write to local mods (hard deny)
- [ ] `ck3lens` can read/write active local mods
- [ ] `ck3lens` CANNOT write to ck3raven source (hard deny)
- [ ] Contract with `allowed_paths=["**"]` is rejected
- [ ] Contract with paths not matching mode is rejected
- [ ] DELETE operations require token
- [ ] Token request for high-risk ops triggers user approval
- [ ] `ck3_exec` works with PowerShell syntax on Windows
- [ ] Audit log captures all gate decisions

---

## Part 5: Future Enhancements (Documented)

1. **Sub-agent contract reviewer** - Spin up a lightweight agent to review contract requests, provide impact summaries, and recommend approve/deny before escalating to user.

2. **Audit analysis sub-agent** - Periodic review of logs to identify policy gaps, suspicious patterns, and improvement opportunities.

3. **Mod registry repair** - Full implementation of `ck3_repair` with comprehensive launcher diagnostics.

4. **Path specificity learning** - Track which path patterns are commonly approved/denied and suggest improvements to agents.

5. **Contract templates** - Pre-defined contract shapes for common tasks (e.g., "add trait", "fix on_action conflict") with pre-validated paths.
