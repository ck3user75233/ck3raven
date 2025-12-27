"""
CK3Lens Hard Gates

Pure functions implementing hard gate checks from CK3LENS_POLICY_ARCHITECTURE.md
and CK3RAVEN_DEV_POLICY_ARCHITECTURE.md.

Each gate returns a decision tuple: (allowed: bool, reason: str)

CK3LENS Hard Gates (AUTO_DENY on failure):
- Missing intent_type → AUTO_DENY
- Write outside active local mods → AUTO_DENY
- Write to workshop/vanilla → AUTO_DENY
- Write to ck3raven source (any mode) → AUTO_DENY
- Read inactive mod without user prompt evidence → AUTO_DENY
- Utility file write → AUTO_DENY
- Python write outside WIP workspace → AUTO_DENY
- Script execution without syntax validation → AUTO_DENY
- Script execution with declared/actual mismatch → AUTO_DENY
- Write contract without targets → AUTO_DENY
- Write contract without snippets (if >0 files) → AUTO_DENY
- Write contract without DIFF_SANITY acceptance test → AUTO_DENY
- Delete without explicit file list → AUTO_DENY
- Delete without Tier B approval token → AUTO_DENY
- Contract attempting to expand visibility beyond mode allows → AUTO_DENY

CK3RAVEN-DEV Hard Gates (AUTO_DENY on failure):
- Mod write prohibition (absolute) → AUTO_DENY
- run_in_terminal prohibition → AUTO_DENY
- Git history rewrite without token → AUTO_DENY
- DB destructive operation without migration context → AUTO_DENY
- WIP script as substitute for code fix → AUTO_DENY
- Repeated script execution without core changes → AUTO_DENY
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .types import (
    IntentType, ScopeDomain, AcceptanceTest, CK3LensTokenType,
    AgentMode, Ck3RavenDevIntentType, Ck3RavenDevWipIntent, Ck3RavenDevTokenType,
    GIT_COMMANDS_SAFE, GIT_COMMANDS_RISKY, GIT_COMMANDS_DANGEROUS,
    get_ck3raven_dev_wip_path,
)
from .wip_workspace import is_wip_path


# =============================================================================
# GATE RESULT TYPE
# =============================================================================

@dataclass
class GateResult:
    """Result of a hard gate check."""
    allowed: bool
    gate_name: str
    reason: str
    details: dict[str, Any] | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "gate_name": self.gate_name,
            "reason": self.reason,
            "details": self.details or {},
        }


def deny(gate_name: str, reason: str, **details) -> GateResult:
    """Shorthand for denied gate result."""
    return GateResult(
        allowed=False,
        gate_name=gate_name,
        reason=reason,
        details=details if details else None,
    )


def allow(gate_name: str, reason: str = "Gate passed", **details) -> GateResult:
    """Shorthand for allowed gate result."""
    return GateResult(
        allowed=True,
        gate_name=gate_name,
        reason=reason,
        details=details if details else None,
    )


# =============================================================================
# INTENT TYPE GATES
# =============================================================================

def gate_intent_type_required(intent_type: IntentType | str | None) -> GateResult:
    """
    HARD GATE: Contract must have valid intent_type.
    
    Missing intent_type → AUTO_DENY
    """
    if intent_type is None:
        return deny(
            "INTENT_TYPE_REQUIRED",
            "Contract missing required intent_type field"
        )
    
    # Validate it's a known type
    if isinstance(intent_type, str):
        try:
            IntentType(intent_type)
        except ValueError:
            return deny(
                "INTENT_TYPE_INVALID",
                f"Unknown intent_type: {intent_type}",
                valid_types=[t.value for t in IntentType],
            )
    
    return allow("INTENT_TYPE_REQUIRED", f"Valid intent_type: {intent_type}")


def gate_write_requires_write_intent(
    intent_type: IntentType | None,
    has_write_operations: bool,
) -> GateResult:
    """
    HARD GATE: Write operations require COMPATCH or BUGPATCH intent.
    """
    if not has_write_operations:
        return allow("WRITE_REQUIRES_WRITE_INTENT", "No write operations")
    
    write_intents = {IntentType.COMPATCH, IntentType.BUGPATCH}
    
    if intent_type not in write_intents:
        return deny(
            "WRITE_REQUIRES_WRITE_INTENT",
            f"Write operations require COMPATCH or BUGPATCH intent, not {intent_type}",
            actual_intent=intent_type.value if intent_type else None,
            allowed_intents=[i.value for i in write_intents],
        )
    
    return allow("WRITE_REQUIRES_WRITE_INTENT", f"Write allowed with {intent_type}")


# =============================================================================
# SCOPE DOMAIN GATES
# =============================================================================

def gate_write_active_local_mods_only(
    target_path: str | Path,
    local_mod_roots: set[str],
    ck3raven_root: Path | None = None,
) -> GateResult:
    """
    HARD GATE: Writes only allowed to active local mods or WIP workspace.
    
    Write outside active local mods → AUTO_DENY
    Write to ck3raven source → AUTO_DENY (even with contract)
    """
    if isinstance(target_path, str):
        target_path = Path(target_path)
    
    target_resolved = target_path.resolve()
    target_str = str(target_resolved).replace("\\", "/").lower()
    
    # WIP workspace is always allowed
    if is_wip_path(target_path):
        return allow(
            "WRITE_ACTIVE_LOCAL_MODS_ONLY",
            "WIP workspace write allowed",
            domain=ScopeDomain.WIP_WORKSPACE.value,
        )
    
    # CK3Raven source is NEVER writable (even with contract)
    if ck3raven_root:
        ck3raven_str = str(ck3raven_root.resolve()).replace("\\", "/").lower()
        if target_str.startswith(ck3raven_str):
            return deny(
                "WRITE_CK3RAVEN_SOURCE_FORBIDDEN",
                "ck3lens cannot write to ck3raven source code",
                target=str(target_path),
                ck3raven_root=str(ck3raven_root),
            )
    
    # Check if it's within any local mod root
    for mod_root in local_mod_roots:
        mod_root_lower = mod_root.replace("\\", "/").lower()
        if target_str.startswith(mod_root_lower):
            return allow(
                "WRITE_ACTIVE_LOCAL_MODS_ONLY",
                "Write to active local mod allowed",
                domain=ScopeDomain.ACTIVE_LOCAL_MODS.value,
                mod_root=mod_root,
            )
    
    return deny(
        "WRITE_ACTIVE_LOCAL_MODS_ONLY",
        "Write outside active local mods not allowed",
        target=str(target_path),
        allowed_roots=list(local_mod_roots),
    )


def gate_no_workshop_vanilla_writes(
    target_path: str | Path,
    workshop_roots: set[str],
    vanilla_root: str | None,
) -> GateResult:
    """
    HARD GATE: Workshop and vanilla mods are immutable.
    
    Write to workshop/vanilla → AUTO_DENY
    """
    if isinstance(target_path, str):
        target_path = Path(target_path)
    
    target_resolved = target_path.resolve()
    target_str = str(target_resolved).replace("\\", "/").lower()
    
    # Check vanilla
    if vanilla_root:
        vanilla_lower = vanilla_root.replace("\\", "/").lower()
        if target_str.startswith(vanilla_lower):
            return deny(
                "NO_WORKSHOP_VANILLA_WRITES",
                "Vanilla game files are immutable",
                target=str(target_path),
                domain=ScopeDomain.VANILLA_GAME.value,
            )
    
    # Check workshop mods
    for workshop_root in workshop_roots:
        workshop_lower = workshop_root.replace("\\", "/").lower()
        if target_str.startswith(workshop_lower):
            return deny(
                "NO_WORKSHOP_VANILLA_WRITES",
                "Workshop mods are immutable",
                target=str(target_path),
                domain=ScopeDomain.ACTIVE_WORKSHOP_MODS.value,
            )
    
    return allow("NO_WORKSHOP_VANILLA_WRITES", "Not a workshop/vanilla path")


# =============================================================================
# PYTHON FILE GATES
# =============================================================================

def gate_python_wip_only(
    target_path: str | Path,
    operation: str,  # "read", "write", "execute"
) -> GateResult:
    """
    HARD GATE: Python files can only be written to WIP workspace.
    
    Python write outside WIP workspace → AUTO_DENY
    """
    if isinstance(target_path, str):
        target_path = Path(target_path)
    
    # Check if it's a Python file
    if not target_path.suffix.lower() == ".py":
        return allow("PYTHON_WIP_ONLY", "Not a Python file")
    
    # Read is allowed anywhere (with logging)
    if operation == "read":
        return allow("PYTHON_WIP_ONLY", "Python read allowed")
    
    # Write/execute must be in WIP
    if not is_wip_path(target_path):
        return deny(
            "PYTHON_WIP_ONLY",
            f"Python {operation} only allowed in WIP workspace",
            target=str(target_path),
            expected_location="~/.ck3raven/wip/",
        )
    
    return allow("PYTHON_WIP_ONLY", f"Python {operation} in WIP allowed")


# =============================================================================
# INACTIVE MOD GATES
# =============================================================================

def gate_inactive_mod_requires_user_prompt(
    target_path: str | Path,
    is_inactive_mod: bool,
    has_user_prompt_evidence: bool,
    has_read_token: bool,
) -> GateResult:
    """
    HARD GATE: Reading inactive mods requires explicit user prompt + token.
    
    Read inactive mod without user prompt evidence → AUTO_DENY
    """
    if not is_inactive_mod:
        return allow("INACTIVE_MOD_REQUIRES_USER_PROMPT", "Not an inactive mod")
    
    if not has_user_prompt_evidence:
        return deny(
            "INACTIVE_MOD_REQUIRES_USER_PROMPT",
            "Reading inactive mod requires explicit user request",
            target=str(target_path),
            hint="User must explicitly ask to read this mod",
        )
    
    if not has_read_token:
        return deny(
            "INACTIVE_MOD_REQUIRES_TOKEN",
            "Reading inactive mod requires READ_INACTIVE_MOD token",
            target=str(target_path),
            required_token=CK3LensTokenType.READ_INACTIVE_MOD.value,
        )
    
    return allow("INACTIVE_MOD_REQUIRES_USER_PROMPT", "User prompted + token valid")


# =============================================================================
# SCRIPT EXECUTION GATES
# =============================================================================

def gate_script_syntax_validated(
    script_path: str,
    syntax_validated: bool,
    validation_passed: bool,
) -> GateResult:
    """
    HARD GATE: Script must pass syntax validation before execution.
    
    Script execution without syntax validation → AUTO_DENY
    """
    if not syntax_validated:
        return deny(
            "SCRIPT_SYNTAX_VALIDATED",
            "Script must be syntax-validated before execution",
            script_path=script_path,
            hint="Call validate_script_syntax first",
        )
    
    if not validation_passed:
        return deny(
            "SCRIPT_SYNTAX_INVALID",
            "Script has syntax errors - execution denied",
            script_path=script_path,
        )
    
    return allow("SCRIPT_SYNTAX_VALIDATED", "Script syntax valid")


def gate_script_declarations_match(
    script_hash: str,
    declared_writes: list[str],
    actual_writes: list[str],
) -> GateResult:
    """
    HARD GATE: Script's actual file access must match declarations.
    
    Script execution with declared/actual mismatch → AUTO_DENY
    """
    declared_set = set(declared_writes)
    actual_set = set(actual_writes)
    
    undeclared = actual_set - declared_set
    
    if undeclared:
        return deny(
            "SCRIPT_DECLARATIONS_MATCH",
            "Script wrote to undeclared files",
            script_hash=script_hash,
            undeclared_writes=list(undeclared),
            declared_writes=declared_writes,
        )
    
    return allow(
        "SCRIPT_DECLARATIONS_MATCH",
        "Script writes match declarations",
        script_hash=script_hash,
    )


def gate_script_has_execution_token(
    script_hash: str,
    has_token: bool,
    token_hash: str | None = None,
) -> GateResult:
    """
    HARD GATE: Script execution requires approval token.
    
    Token is bound to script hash - if hash changes, approval invalidated.
    """
    if not has_token:
        return deny(
            "SCRIPT_HAS_EXECUTION_TOKEN",
            "Script execution requires SCRIPT_EXECUTE token",
            script_hash=script_hash,
            required_token=CK3LensTokenType.SCRIPT_EXECUTE.value,
        )
    
    if token_hash and token_hash != script_hash:
        return deny(
            "SCRIPT_TOKEN_HASH_MISMATCH",
            "Script content changed - approval invalidated",
            current_hash=script_hash,
            token_bound_hash=token_hash,
            hint="Re-validate and re-approve the script",
        )
    
    return allow(
        "SCRIPT_HAS_EXECUTION_TOKEN",
        "Script execution approved",
        script_hash=script_hash,
    )


# =============================================================================
# CONTRACT COMPLETENESS GATES
# =============================================================================

def gate_write_contract_has_targets(
    intent_type: IntentType | None,
    targets: list[dict[str, str]] | None,
) -> GateResult:
    """
    HARD GATE: Write contracts must specify targets.
    
    Write contract without targets → AUTO_DENY
    """
    write_intents = {IntentType.COMPATCH, IntentType.BUGPATCH}
    
    if intent_type not in write_intents:
        return allow("WRITE_CONTRACT_HAS_TARGETS", "Not a write contract")
    
    if not targets:
        return deny(
            "WRITE_CONTRACT_HAS_TARGETS",
            "Write contract must specify targets [{mod_id, rel_path}]",
            intent_type=intent_type.value if intent_type else None,
        )
    
    return allow(
        "WRITE_CONTRACT_HAS_TARGETS",
        f"Write contract has {len(targets)} targets",
        target_count=len(targets),
    )


def gate_write_contract_has_snippets(
    intent_type: IntentType | None,
    file_count: int,
    snippet_count: int,
) -> GateResult:
    """
    HARD GATE: Write contracts must include before/after snippets.
    
    Write contract without snippets (if >0 files) → AUTO_DENY
    """
    write_intents = {IntentType.COMPATCH, IntentType.BUGPATCH}
    
    if intent_type not in write_intents:
        return allow("WRITE_CONTRACT_HAS_SNIPPETS", "Not a write contract")
    
    if file_count == 0:
        return allow("WRITE_CONTRACT_HAS_SNIPPETS", "No files to write")
    
    if snippet_count == 0:
        return deny(
            "WRITE_CONTRACT_HAS_SNIPPETS",
            "Write contract must include before/after snippets",
            file_count=file_count,
            hint="Provide up to 3 before_after_snippets blocks",
        )
    
    return allow(
        "WRITE_CONTRACT_HAS_SNIPPETS",
        f"Write contract has {snippet_count} snippets for {file_count} files",
    )


def gate_write_contract_has_diff_sanity(
    intent_type: IntentType | None,
    acceptance_tests: list[str] | None,
) -> GateResult:
    """
    HARD GATE: Write contracts must include DIFF_SANITY acceptance test.
    
    Write contract without DIFF_SANITY → AUTO_DENY
    """
    write_intents = {IntentType.COMPATCH, IntentType.BUGPATCH}
    
    if intent_type not in write_intents:
        return allow("WRITE_CONTRACT_HAS_DIFF_SANITY", "Not a write contract")
    
    tests = set(acceptance_tests or [])
    
    if AcceptanceTest.DIFF_SANITY.value not in tests and "DIFF_SANITY" not in tests:
        return deny(
            "WRITE_CONTRACT_HAS_DIFF_SANITY",
            "Write contract must include DIFF_SANITY acceptance test",
            acceptance_tests=list(tests),
            hint="DIFF_SANITY ensures proposed scope matches actual touched files",
        )
    
    return allow("WRITE_CONTRACT_HAS_DIFF_SANITY", "DIFF_SANITY acceptance test present")


# =============================================================================
# DELETE OPERATION GATES
# =============================================================================

def gate_delete_explicit_file_list(
    is_delete_operation: bool,
    has_explicit_list: bool,
    uses_globs: bool,
) -> GateResult:
    """
    HARD GATE: Delete operations require explicit file list, no globs.
    
    Delete without explicit file list → AUTO_DENY
    """
    if not is_delete_operation:
        return allow("DELETE_EXPLICIT_FILE_LIST", "Not a delete operation")
    
    if not has_explicit_list:
        return deny(
            "DELETE_EXPLICIT_FILE_LIST",
            "Delete operations require explicit file list",
            hint="Provide complete list of files to delete",
        )
    
    if uses_globs:
        return deny(
            "DELETE_NO_GLOBS",
            "Delete operations cannot use glob patterns",
            hint="List each file explicitly",
        )
    
    return allow("DELETE_EXPLICIT_FILE_LIST", "Explicit file list provided")


def gate_delete_has_token(
    is_delete_operation: bool,
    has_token: bool,
) -> GateResult:
    """
    HARD GATE: Delete operations require Tier B approval token.
    
    Delete without Tier B approval token → AUTO_DENY
    """
    if not is_delete_operation:
        return allow("DELETE_HAS_TOKEN", "Not a delete operation")
    
    if not has_token:
        return deny(
            "DELETE_HAS_TOKEN",
            "Delete operations require DELETE_LOCALMOD approval token",
            required_token=CK3LensTokenType.DELETE_LOCALMOD.value,
        )
    
    return allow("DELETE_HAS_TOKEN", "Delete token provided")


# =============================================================================
# COMPOSITE GATE RUNNER
# =============================================================================

def run_all_gates(
    *,
    # Operation context
    operation: str,  # "read", "write", "edit", "delete", "execute"
    target_path: str | Path | None = None,
    
    # Intent/contract context
    intent_type: IntentType | str | None = None,
    targets: list[dict[str, str]] | None = None,
    snippets: list[dict[str, Any]] | None = None,
    acceptance_tests: list[str] | None = None,
    
    # Scope context
    local_mod_roots: set[str] | None = None,
    workshop_roots: set[str] | None = None,
    vanilla_root: str | None = None,
    ck3raven_root: Path | None = None,
    
    # Token context
    has_delete_token: bool = False,
    has_read_inactive_token: bool = False,
    has_script_execute_token: bool = False,
    script_token_hash: str | None = None,
    
    # Script context
    is_script_execution: bool = False,
    script_hash: str | None = None,
    syntax_validated: bool = False,
    syntax_passed: bool = False,
    declared_writes: list[str] | None = None,
    actual_writes: list[str] | None = None,
    
    # Inactive mod context
    is_inactive_mod: bool = False,
    has_user_prompt_evidence: bool = False,
) -> tuple[bool, list[GateResult]]:
    """
    Run all applicable hard gates and return results.
    
    Returns:
        Tuple of (all_passed: bool, gate_results: list)
    """
    results: list[GateResult] = []
    
    # Normalize intent_type
    if isinstance(intent_type, str):
        try:
            intent_type = IntentType(intent_type)
        except ValueError:
            intent_type = None
    
    # Gate: Intent type required for write operations
    if operation in ("write", "edit", "delete"):
        results.append(gate_intent_type_required(intent_type))
        results.append(gate_write_requires_write_intent(intent_type, True))
    
    # Gate: Target path restrictions
    if target_path and operation in ("write", "edit", "delete"):
        if local_mod_roots is not None:
            results.append(gate_write_active_local_mods_only(
                target_path, local_mod_roots, ck3raven_root
            ))
        
        if workshop_roots or vanilla_root:
            results.append(gate_no_workshop_vanilla_writes(
                target_path, workshop_roots or set(), vanilla_root
            ))
        
        results.append(gate_python_wip_only(target_path, operation))
    
    # Gate: Inactive mod access
    if target_path and is_inactive_mod:
        results.append(gate_inactive_mod_requires_user_prompt(
            target_path, is_inactive_mod, has_user_prompt_evidence, has_read_inactive_token
        ))
    
    # Gate: Script execution
    if is_script_execution and script_hash:
        results.append(gate_script_syntax_validated(
            str(target_path) if target_path else "unknown",
            syntax_validated, syntax_passed
        ))
        
        results.append(gate_script_has_execution_token(
            script_hash, has_script_execute_token, script_token_hash
        ))
        
        if actual_writes is not None:
            results.append(gate_script_declarations_match(
                script_hash, declared_writes or [], actual_writes
            ))
    
    # Gate: Write contract completeness
    if operation in ("write", "edit"):
        results.append(gate_write_contract_has_targets(intent_type, targets))
        
        file_count = len(targets) if targets else 0
        snippet_count = len(snippets) if snippets else 0
        results.append(gate_write_contract_has_snippets(intent_type, file_count, snippet_count))
        
        results.append(gate_write_contract_has_diff_sanity(intent_type, acceptance_tests))
    
    # Gate: Delete operations
    if operation == "delete":
        has_explicit = targets is not None and len(targets) > 0
        uses_globs = any("*" in t.get("rel_path", "") for t in (targets or []))
        results.append(gate_delete_explicit_file_list(True, has_explicit, uses_globs))
        results.append(gate_delete_has_token(True, has_delete_token))
    
    # Check if all gates passed
    all_passed = all(r.allowed for r in results)
    
    return all_passed, results


# =============================================================================
# CK3RAVEN-DEV HARD GATES
# =============================================================================

def gate_ck3raven_dev_mod_write_prohibition(
    target_path: str | Path,
    mod_roots: set[str],
    vanilla_root: str | None,
    workshop_pattern: str = "steamapps/workshop",
) -> GateResult:
    """
    HARD GATE (ck3raven-dev): Absolute prohibition on mod file writes.
    
    ck3raven-dev mode CANNOT write to ANY mod files - local, workshop, or vanilla.
    This is an absolute prohibition, not bypassable by any token.
    
    Mod write in ck3raven-dev → AUTO_DENY
    """
    if isinstance(target_path, str):
        target_path = Path(target_path)
    
    target_resolved = target_path.resolve()
    target_str = str(target_resolved).replace("\\", "/").lower()
    
    # Check vanilla
    if vanilla_root:
        vanilla_lower = vanilla_root.replace("\\", "/").lower()
        if target_str.startswith(vanilla_lower):
            return deny(
                "CK3RAVEN_DEV_MOD_WRITE_PROHIBITION",
                "ck3raven-dev cannot write to vanilla game files (absolute prohibition)",
                target=str(target_path),
            )
    
    # Check workshop mods (via pattern)
    if workshop_pattern.lower() in target_str:
        return deny(
            "CK3RAVEN_DEV_MOD_WRITE_PROHIBITION",
            "ck3raven-dev cannot write to workshop mods (absolute prohibition)",
            target=str(target_path),
        )
    
    # Check any local mod roots
    for mod_root in mod_roots:
        mod_root_lower = mod_root.replace("\\", "/").lower()
        if target_str.startswith(mod_root_lower):
            return deny(
                "CK3RAVEN_DEV_MOD_WRITE_PROHIBITION",
                "ck3raven-dev cannot write to local mods (absolute prohibition)",
                target=str(target_path),
                mod_root=mod_root,
            )
    
    return allow("CK3RAVEN_DEV_MOD_WRITE_PROHIBITION", "Not a mod path")


def gate_ck3raven_dev_run_in_terminal_prohibition(
    tool_name: str,
    command: str | None = None,
) -> GateResult:
    """
    HARD GATE (ck3raven-dev): run_in_terminal is prohibited.
    
    ck3raven-dev must use ck3_exec for all command execution.
    run_in_terminal → AUTO_DENY
    """
    if tool_name == "run_in_terminal":
        return deny(
            "CK3RAVEN_DEV_RUN_IN_TERMINAL_PROHIBITION",
            "ck3raven-dev must use ck3_exec, not run_in_terminal",
            command=command,
            hint="Use ck3_exec tool instead",
        )
    
    return allow("CK3RAVEN_DEV_RUN_IN_TERMINAL_PROHIBITION", "Not run_in_terminal")


def gate_ck3raven_dev_git_command_classification(
    git_command: str,
    has_git_push_token: bool = False,
    has_force_push_token: bool = False,
    has_history_rewrite_token: bool = False,
) -> GateResult:
    """
    HARD GATE (ck3raven-dev): Git commands must be classified and authorized.
    
    - Safe commands (status, diff, log, fetch, pull): Always allowed
    - Risky commands (add, commit): Allowed with contract
    - Dangerous commands (push, force push, rebase, amend): Require explicit token
    
    Unclassified/blocked git commands → AUTO_DENY
    """
    # Normalize command
    cmd_parts = git_command.strip().split()
    if not cmd_parts or cmd_parts[0] != "git":
        return allow("CK3RAVEN_DEV_GIT_CLASSIFICATION", "Not a git command")
    
    # Get git subcommand
    if len(cmd_parts) < 2:
        return deny(
            "CK3RAVEN_DEV_GIT_CLASSIFICATION",
            "Invalid git command (no subcommand)",
            command=git_command,
        )
    
    git_subcommand = cmd_parts[1].lower()
    
    # Check for force push
    is_force_push = "--force" in git_command or "-f" in cmd_parts
    
    # Check for amend
    is_amend = "--amend" in git_command
    
    # Safe commands - always allowed
    if git_subcommand in GIT_COMMANDS_SAFE:
        return allow(
            "CK3RAVEN_DEV_GIT_CLASSIFICATION",
            f"Safe git command: {git_subcommand}",
            category="safe",
        )
    
    # Risky but allowed with contract
    if git_subcommand in GIT_COMMANDS_RISKY and not is_amend:
        return allow(
            "CK3RAVEN_DEV_GIT_CLASSIFICATION",
            f"Risky git command allowed: {git_subcommand}",
            category="risky",
        )
    
    # Dangerous commands - require tokens
    if git_subcommand == "push":
        if is_force_push:
            if not has_force_push_token:
                return deny(
                    "CK3RAVEN_DEV_GIT_FORCE_PUSH_REQUIRES_TOKEN",
                    "git push --force requires GIT_FORCE_PUSH token",
                    command=git_command,
                    required_token=Ck3RavenDevTokenType.GIT_FORCE_PUSH.value,
                )
        else:
            if not has_git_push_token:
                return deny(
                    "CK3RAVEN_DEV_GIT_PUSH_REQUIRES_TOKEN",
                    "git push requires GIT_PUSH token",
                    command=git_command,
                    required_token=Ck3RavenDevTokenType.GIT_PUSH.value,
                )
        return allow(
            "CK3RAVEN_DEV_GIT_CLASSIFICATION",
            "git push authorized with token",
            category="dangerous",
        )
    
    if git_subcommand in ("rebase", "reset") or is_amend:
        if not has_history_rewrite_token:
            return deny(
                "CK3RAVEN_DEV_GIT_HISTORY_REWRITE_REQUIRES_TOKEN",
                f"git {git_subcommand} requires GIT_HISTORY_REWRITE token",
                command=git_command,
                required_token=Ck3RavenDevTokenType.GIT_HISTORY_REWRITE.value,
            )
        return allow(
            "CK3RAVEN_DEV_GIT_CLASSIFICATION",
            f"git {git_subcommand} authorized with token",
            category="dangerous",
        )
    
    # Unknown git command - block by default
    return deny(
        "CK3RAVEN_DEV_GIT_UNCLASSIFIED",
        f"Unknown git command not allowed: {git_subcommand}",
        command=git_command,
        hint="Add to safe/risky/dangerous classification if valid",
    )


def gate_ck3raven_dev_db_destructive_requires_migration(
    operation: str,
    table_names: list[str] | None,
    has_migration_context: bool,
    has_rollback_plan: bool,
    has_db_migration_token: bool = False,
) -> GateResult:
    """
    HARD GATE (ck3raven-dev): Destructive DB ops require migration context.
    
    DB destructive operation without migration context → AUTO_DENY
    Destructive = DROP, DELETE, TRUNCATE, ALTER (column drop)
    """
    destructive_ops = {"drop", "delete", "truncate", "alter"}
    
    if operation.lower() not in destructive_ops:
        return allow("CK3RAVEN_DEV_DB_MIGRATION", "Non-destructive operation")
    
    if not has_migration_context:
        return deny(
            "CK3RAVEN_DEV_DB_MIGRATION_CONTEXT_REQUIRED",
            f"Destructive DB operation '{operation}' requires migration context",
            tables=table_names,
            hint="Create migration script with rollback plan first",
        )
    
    if not has_rollback_plan:
        return deny(
            "CK3RAVEN_DEV_DB_ROLLBACK_REQUIRED",
            f"Destructive DB operation '{operation}' requires rollback plan",
            tables=table_names,
        )
    
    if not has_db_migration_token:
        return deny(
            "CK3RAVEN_DEV_DB_MIGRATION_TOKEN_REQUIRED",
            f"Destructive DB operation '{operation}' requires DB_MIGRATION_DESTRUCTIVE token",
            required_token=Ck3RavenDevTokenType.DB_MIGRATION_DESTRUCTIVE.value,
        )
    
    return allow(
        "CK3RAVEN_DEV_DB_MIGRATION",
        f"DB operation '{operation}' authorized with migration context + token",
    )


def gate_ck3raven_dev_wip_intent_valid(
    wip_intent: Ck3RavenDevWipIntent | str | None,
    has_core_change_plan: bool,
) -> GateResult:
    """
    HARD GATE (ck3raven-dev): WIP scripts must have valid intent.
    
    WIP scripts in ck3raven-dev are strictly constrained:
    - ANALYSIS_ONLY: Read-only analysis, no writes (no core_change_plan needed)
    - REFACTOR_ASSIST: Generate patches (REQUIRES core_change_plan)
    - MIGRATION_HELPER: Generate migrations (REQUIRES core_change_plan)
    """
    if wip_intent is None:
        return deny(
            "CK3RAVEN_DEV_WIP_INTENT_REQUIRED",
            "WIP script must declare intent type",
            valid_intents=[i.value for i in Ck3RavenDevWipIntent],
        )
    
    # Normalize to enum
    if isinstance(wip_intent, str):
        try:
            wip_intent = Ck3RavenDevWipIntent(wip_intent)
        except ValueError:
            return deny(
                "CK3RAVEN_DEV_WIP_INTENT_INVALID",
                f"Unknown WIP intent: {wip_intent}",
                valid_intents=[i.value for i in Ck3RavenDevWipIntent],
            )
    
    # ANALYSIS_ONLY doesn't need core_change_plan
    if wip_intent == Ck3RavenDevWipIntent.ANALYSIS_ONLY:
        return allow(
            "CK3RAVEN_DEV_WIP_INTENT_VALID",
            "ANALYSIS_ONLY intent valid",
        )
    
    # REFACTOR_ASSIST and MIGRATION_HELPER require core_change_plan
    if wip_intent in (Ck3RavenDevWipIntent.REFACTOR_ASSIST, Ck3RavenDevWipIntent.MIGRATION_HELPER):
        if not has_core_change_plan:
            return deny(
                "CK3RAVEN_DEV_WIP_REQUIRES_CORE_CHANGE_PLAN",
                f"{wip_intent.value} requires core_change_plan",
                hint="Document what source files will be modified after script output",
            )
        return allow(
            "CK3RAVEN_DEV_WIP_INTENT_VALID",
            f"{wip_intent.value} intent valid with core_change_plan",
        )
    
    return allow("CK3RAVEN_DEV_WIP_INTENT_VALID", "WIP intent valid")


def gate_ck3raven_dev_wip_not_workaround(
    script_hash: str,
    previous_executions: list[tuple[str, str, bool]],  # [(hash, timestamp, core_changes_made)]
    determinism_threshold: int = 3,
) -> GateResult:
    """
    HARD GATE (ck3raven-dev): WIP scripts cannot substitute for code fixes.
    
    Detects workaround pattern:
    - Same script executed N+ times consecutively
    - No core source changes between executions
    
    Repeated script execution without core changes → AUTO_DENY
    
    Args:
        script_hash: Current script's hash
        previous_executions: List of (hash, timestamp, core_changes_made) tuples
        determinism_threshold: How many consecutive same-hash runs trigger detection
    """
    if not previous_executions:
        return allow("CK3RAVEN_DEV_WIP_NOT_WORKAROUND", "First execution")
    
    # Count consecutive same-hash runs without core changes
    consecutive_same_hash = 0
    for prev_hash, _, core_changes_made in reversed(previous_executions):
        if prev_hash == script_hash and not core_changes_made:
            consecutive_same_hash += 1
        else:
            break
    
    if consecutive_same_hash >= determinism_threshold:
        return deny(
            "CK3RAVEN_DEV_WIP_WORKAROUND_DETECTED",
            f"Script executed {consecutive_same_hash + 1} times without core changes",
            script_hash=script_hash,
            threshold=determinism_threshold,
            hint="WIP scripts cannot substitute for proper code fixes",
        )
    
    return allow(
        "CK3RAVEN_DEV_WIP_NOT_WORKAROUND",
        f"Script execution allowed (consecutive: {consecutive_same_hash + 1})",
    )


def gate_ck3raven_dev_wip_path_valid(
    script_path: str | Path,
    repo_root: Path,
) -> GateResult:
    """
    HARD GATE (ck3raven-dev): WIP scripts must be in <repo>/.wip/ directory.
    
    WIP script outside .wip/ directory → AUTO_DENY
    """
    if isinstance(script_path, str):
        script_path = Path(script_path)
    
    expected_wip = get_ck3raven_dev_wip_path(repo_root)
    script_resolved = script_path.resolve()
    expected_resolved = expected_wip.resolve()
    
    try:
        script_resolved.relative_to(expected_resolved)
        return allow(
            "CK3RAVEN_DEV_WIP_PATH_VALID",
            "Script in valid WIP location",
            wip_path=str(expected_wip),
        )
    except ValueError:
        return deny(
            "CK3RAVEN_DEV_WIP_PATH_INVALID",
            f"WIP script must be in {expected_wip}, not {script_path}",
            expected_location=str(expected_wip),
            actual_location=str(script_path),
        )


# =============================================================================
# CK3RAVEN-DEV COMPOSITE GATE RUNNER
# =============================================================================

def run_ck3raven_dev_gates(
    *,
    # Operation context
    operation: str,  # "read", "write", "edit", "delete", "execute", "git", "db"
    target_path: str | Path | None = None,
    command: str | None = None,
    tool_name: str | None = None,
    
    # Scope context
    repo_root: Path | None = None,
    mod_roots: set[str] | None = None,
    vanilla_root: str | None = None,
    
    # Token context
    has_git_push_token: bool = False,
    has_force_push_token: bool = False,
    has_history_rewrite_token: bool = False,
    has_db_migration_token: bool = False,
    has_script_run_token: bool = False,
    
    # DB context
    db_operation: str | None = None,
    table_names: list[str] | None = None,
    has_migration_context: bool = False,
    has_rollback_plan: bool = False,
    
    # WIP context
    wip_intent: Ck3RavenDevWipIntent | str | None = None,
    has_core_change_plan: bool = False,
    script_hash: str | None = None,
    previous_executions: list[tuple[str, str, bool]] | None = None,
) -> tuple[bool, list[GateResult]]:
    """
    Run all applicable ck3raven-dev hard gates.
    
    Returns:
        Tuple of (all_passed: bool, gate_results: list)
    """
    results: list[GateResult] = []
    
    # Gate: run_in_terminal prohibition
    if tool_name:
        results.append(gate_ck3raven_dev_run_in_terminal_prohibition(tool_name, command))
    
    # Gate: Mod write prohibition (for write operations)
    if target_path and operation in ("write", "edit", "delete"):
        results.append(gate_ck3raven_dev_mod_write_prohibition(
            target_path, mod_roots or set(), vanilla_root
        ))
    
    # Gate: Git command classification
    if operation == "git" and command:
        results.append(gate_ck3raven_dev_git_command_classification(
            command,
            has_git_push_token,
            has_force_push_token,
            has_history_rewrite_token,
        ))
    
    # Gate: DB destructive operations
    if operation == "db" and db_operation:
        results.append(gate_ck3raven_dev_db_destructive_requires_migration(
            db_operation,
            table_names,
            has_migration_context,
            has_rollback_plan,
            has_db_migration_token,
        ))
    
    # Gate: WIP script execution
    if operation == "execute" and target_path and repo_root:
        results.append(gate_ck3raven_dev_wip_path_valid(target_path, repo_root))
        results.append(gate_ck3raven_dev_wip_intent_valid(wip_intent, has_core_change_plan))
        
        if script_hash:
            results.append(gate_ck3raven_dev_wip_not_workaround(
                script_hash,
                previous_executions or [],
            ))
    
    all_passed = all(r.allowed for r in results)
    return all_passed, results
