"""
CK3 Lens Rules

Policy validation rules specific to the ck3lens agent mode.
Implements the CK3LENS_POLICY_ARCHITECTURE.md specification.

Core Invariants:
1. Mods must be ingested into the database to be visible
2. Only mods in the active playset are visible by default
3. Only active local mods are mutable
4. Vanilla and workshop mods are always immutable
5. Filesystem access never expands mod discovery
6. ck3lens cannot write Python except to the WIP workspace
7. ck3raven source is read-only (no writes even with contract)

CRITICAL: ck3lens agents can ONLY edit CK3 mod files in configured local_mods.
They CANNOT edit Python code, core ck3raven code, or any infrastructure files
(except Python in the WIP workspace for temporary scripts).
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .types import (
    Severity, Violation, ValidationContext,
    ScopeDomain,  # IntentType and AcceptanceTest REMOVED - BANNED
)
# REMOVED: hard_gates imports - this module was archived Dec 2025
# All enforcement decisions should go through enforcement.py
from .wip_workspace import is_wip_path, get_wip_workspace_path
from .trace_helpers import (
    trace_has_call,
    trace_calls,
    trace_last_call,
    trace_any_filesystem_search,
    get_scoped_calls,
    get_resolved_unit_keys,
    is_db_search_tool,
    extract_search_scope_from_call,
)

if TYPE_CHECKING:
    from ..contracts import ArtifactBundle


# =============================================================================
# FILE PATH RESTRICTIONS FOR CK3LENS
# =============================================================================

# Extensions that ck3lens is ALLOWED to edit in MOD directories (CK3 mod files only)
CK3_ALLOWED_EXTENSIONS = frozenset({
    ".txt",      # CK3 script files
    ".yml",      # Localization
    ".gui",      # GUI definitions
    ".gfx",      # Graphics definitions
    ".dds",      # Texture files
    ".asset",    # 3D asset definitions
    ".mesh",     # 3D meshes
    ".shader",   # Shaders
    ".settings", # Settings files
    ".info",     # Mod info files
    ".mod",      # Mod descriptor
})

# Paths that ck3lens is FORBIDDEN from editing (infrastructure/Python)
# EXCEPTION: WIP workspace (~/.ck3raven/wip/) allows Python
CK3LENS_FORBIDDEN_PATHS = (
    "src/",           # Core ck3raven code
    "builder/",       # Database builder
    "tests/",         # Test files
    "scripts/",       # Maintenance scripts
    "tools/",         # Tool implementations
    ".vscode/",       # VS Code config
    ".github/",       # GitHub workflows
    ".git/",          # Git internals
    "docs/",          # Documentation
)

# File extensions ck3lens is FORBIDDEN from editing in MOD directories
# NOTE: .py IS allowed in WIP workspace only
CK3LENS_FORBIDDEN_EXTENSIONS = frozenset({
    ".py",            # Python code (EXCEPT in WIP workspace)
    ".pyc",           # Compiled Python
    ".json",          # Config files
    ".yaml",          # Config files
    ".toml",          # Config files
    ".md",            # Documentation
    ".rst",           # Documentation
    ".sh",            # Shell scripts
    ".ps1",           # PowerShell scripts
    ".bat",           # Batch scripts
    ".cmd",           # Command scripts
})

# Extensions allowed ONLY in WIP workspace (nowhere else)
WIP_ONLY_EXTENSIONS = frozenset({
    ".py",            # Python scripts for batch transformations
})


# =============================================================================
# HELPER: CLASSIFY PATH DOMAIN
# =============================================================================

def classify_path_domain(
    path: str | Path,
    *,
    local_mods_folder: Path | None = None,
    vanilla_root: str | None = None,
    ck3raven_root: Path | None = None,
) -> ScopeDomain | None:
    """
    Classify a path into its scope domain.
    
    Returns the ScopeDomain for structural classification only (NOT permissions).
    
    For mod paths, returns None - enforcement.py decides based on local_mods_folder.
    """
    if isinstance(path, str):
        path = Path(path)
    
    path_resolved = path.resolve()
    path_str = str(path_resolved).replace("\\", "/").lower()
    
    # WIP workspace
    if is_wip_path(path):
        return ScopeDomain.WIP_WORKSPACE
    
    # CK3Raven source
    if ck3raven_root:
        ck3raven_str = str(ck3raven_root.resolve()).replace("\\", "/").lower()
        if path_str.startswith(ck3raven_str):
            return ScopeDomain.CK3RAVEN_SOURCE
    
    # Vanilla game
    if vanilla_root:
        vanilla_str = vanilla_root.replace("\\", "/").lower()
        if path_str.startswith(vanilla_str):
            return ScopeDomain.VANILLA_GAME
    
    # Local mods - path under local_mods_folder
    if local_mods_folder:
        local_str = str(local_mods_folder.resolve()).replace("\\", "/").lower()
        if path_str.startswith(local_str):
            # Mod paths handled by enforcement.py
            return None
    
    # If it looks like a mod path but not under local_mods_folder, it's workshop
    # Workshop mods are in Steam workshop folder or other locations
    if _looks_like_mod_path(path_str):
        return None
    
    # Unknown - treat as potentially inactive
    return None


def _looks_like_mod_path(path_str: str) -> bool:
    """Check if path looks like a CK3 mod path (has common mod structure)."""
    mod_indicators = [
        "/common/",
        "/events/",
        "/localization/",
        "/gfx/",
        "/gui/",
        "/music/",
        "/sound/",
        "workshop/content/1158310/",  # CK3 Steam workshop ID
    ]
    return any(indicator in path_str for indicator in mod_indicators)


# =============================================================================
# CK3LENS PATH ENFORCEMENT (CRITICAL SECURITY RULE)
# =============================================================================

def enforce_ck3lens_file_restrictions(
    ctx: ValidationContext,
    bundle: "ArtifactBundle",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: ck3lens agents can ONLY edit CK3 mod files (plus Python in WIP).
    
    Rule: no_python_editing (except WIP), local_mods_only
    Severity: ERROR (HARD GATE)
    
    ck3lens is for CK3 modding ONLY. It cannot:
    - Edit Python files (.py) EXCEPT in WIP workspace
    - Edit infrastructure code (src/, builder/, tools/, etc.)
    - Edit configuration files (.json, .yaml, .toml)
    - Edit documentation (.md, .rst)
    - Write to ck3raven source (NEVER, even with contract)
    
    This prevents ck3lens agents from modifying the ck3raven codebase itself.
    Infrastructure changes require ck3raven-dev mode.
    """
    forbidden_files = []
    forbidden_extensions = []
    forbidden_paths = []
    wip_python_files = []  # Python files in WIP (allowed)
    ck3raven_writes = []   # Attempted writes to ck3raven source (NEVER allowed)
    
    for artifact in bundle.artifacts:
        path = getattr(artifact, "path", "")
        if not path:
            continue
        
        path_obj = Path(path)
        path_normalized = str(path_obj).replace("\\", "/").lower()
        filename = path_normalized.split("/")[-1]
        
        # Get extension
        if "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1]
        else:
            ext = ""
        
        # Classify the domain using local_mods_folder boundary
        domain = classify_path_domain(
            path,
            local_mods_folder=ctx.local_mods_folder,
            vanilla_root=ctx.vanilla_root,
            ck3raven_root=ctx.ck3raven_root,
        )
        
        # HARD GATE: ck3raven source is NEVER writable
        if domain == ScopeDomain.CK3RAVEN_SOURCE:
            ck3raven_writes.append({
                "path": path,
                "reason": "ck3lens cannot write to ck3raven source - NEVER allowed"
            })
            continue
        
        # WIP workspace special handling
        if domain == ScopeDomain.WIP_WORKSPACE:
            if ext in WIP_ONLY_EXTENSIONS:
                wip_python_files.append(path)
                continue  # Python in WIP is allowed
            # Other files in WIP are also allowed
            continue
        
        # For non-WIP paths, check forbidden extensions
        if ext in CK3LENS_FORBIDDEN_EXTENSIONS:
            forbidden_extensions.append({
                "path": path,
                "extension": ext,
                "reason": f"ck3lens cannot edit {ext} files outside WIP workspace - use ck3raven-dev mode"
            })
            continue
        
        # Check forbidden paths (ck3raven infrastructure)
        for forbidden in CK3LENS_FORBIDDEN_PATHS:
            if path_normalized.startswith(forbidden) or f"/{forbidden}" in path_normalized:
                forbidden_paths.append({
                    "path": path,
                    "forbidden_prefix": forbidden,
                    "reason": f"ck3lens cannot edit files in {forbidden} - use ck3raven-dev mode"
                })
                break
        
        # Check if extension is allowed (for non-forbidden paths)
        if ext and ext not in CK3_ALLOWED_EXTENSIONS:
            # Not in forbidden list but also not in allowed list
            if ext not in CK3LENS_FORBIDDEN_EXTENSIONS:
                forbidden_files.append({
                    "path": path,
                    "extension": ext,
                    "reason": f"Extension {ext} not in allowed CK3 file types"
                })
    
    # Collect all violations
    all_forbidden = forbidden_extensions + forbidden_paths + forbidden_files + ck3raven_writes
    summary["ck3lens_forbidden_files"] = all_forbidden
    summary["ck3lens_wip_python_files"] = wip_python_files
    
    # ck3raven writes are the most critical - always DENY
    if ck3raven_writes:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="CK3LENS_CK3RAVEN_WRITE_FORBIDDEN",
            message="ck3lens CANNOT write to ck3raven source code - NEVER allowed.",
            details={
                "files": ck3raven_writes,
                "suggestion": "Use ck3raven-dev mode for infrastructure changes",
                "hard_gate": True,
            },
        ))
    
    if forbidden_extensions:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="CK3LENS_FORBIDDEN_EXTENSION",
            message="ck3lens agents CANNOT edit Python or infrastructure files outside WIP workspace.",
            details={
                "files": forbidden_extensions,
                "suggestion": "Use ck3raven-dev mode for Python/infrastructure changes, or write Python to ~/.ck3raven/wip/",
                "wip_workspace": str(get_wip_workspace_path()),
            },
        ))
    
    if forbidden_paths:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="CK3LENS_FORBIDDEN_PATH",
            message="ck3lens agents CANNOT edit core ck3raven code.",
            details={
                "files": forbidden_paths,
                "forbidden_prefixes": list(CK3LENS_FORBIDDEN_PATHS),
                "suggestion": "Use ck3raven-dev mode for infrastructure changes",
            },
        ))


def enforce_active_playset_scope(
    ctx: ValidationContext,
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: all DB-search tools must be scoped to active playset + vanilla version.
    
    Rule: active_playset_enforcement
    Severity: ERROR
    """
    # Require playset_id in context
    if ctx.playset_id is None:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="SCOPE_PLAYSET_MISSING",
            message="ck3lens requires playset_id in context.",
            details={},
        ))
        return
    
    # Ensure agent fetched active playset at least once
    if not trace_has_call(ctx.trace, "ck3_get_active_playset") and not trace_has_call(ctx.trace, "ck3_init_session"):
        violations.append(Violation(
            severity=Severity.ERROR,
            code="ACTIVE_PLAYSET_NOT_FETCHED",
            message="Active playset must be fetched before scoped operations.",
            details={"required_tools": ["ck3_get_active_playset", "ck3_init_session"]},
        ))
    
    # Validate every scoped call is within bounds
    out_of_scope_calls = []
    scoped_calls = get_scoped_calls(ctx.trace)
    
    for call in scoped_calls:
        scope = extract_search_scope_from_call(call)
        
        # playset_id must match if specified
        if scope["playset_id"] is not None and scope["playset_id"] != ctx.playset_id:
            out_of_scope_calls.append({
                "tool": call.name,
                "reason": "playset_id_mismatch",
                "expected": ctx.playset_id,
                "actual": scope["playset_id"],
            })
        
        # vanilla_version_id must match if both specified
        if ctx.vanilla_version_id and scope["vanilla_version_id"]:
            if scope["vanilla_version_id"] != ctx.vanilla_version_id:
                out_of_scope_calls.append({
                    "tool": call.name,
                    "reason": "vanilla_version_mismatch",
                    "expected": ctx.vanilla_version_id,
                    "actual": scope["vanilla_version_id"],
                })
        
        # mod_ids must be subset of active_mod_ids if provided
        if ctx.active_mod_ids is not None and scope["mod_ids"]:
            if not scope["mod_ids"].issubset(ctx.active_mod_ids):
                extra = scope["mod_ids"] - ctx.active_mod_ids
                out_of_scope_calls.append({
                    "tool": call.name,
                    "reason": "mod_ids_outside_active_playset",
                    "extra_mods": list(extra),
                })
        
        # roots must be subset of allowed roots
        if ctx.active_roots is not None and scope["roots"]:
            allowed_roots = ctx.active_roots.copy()
            if ctx.vanilla_root:
                allowed_roots.add(ctx.vanilla_root)
            if not scope["roots"].issubset(allowed_roots):
                extra = scope["roots"] - allowed_roots
                out_of_scope_calls.append({
                    "tool": call.name,
                    "reason": "roots_outside_active_scope",
                    "extra_roots": list(extra),
                })
    
    if out_of_scope_calls:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="OUT_OF_SCOPE_SEARCH",
            message="Search/read operations outside active playset/vanilla scope are disallowed in ck3lens.",
            details={"violations": out_of_scope_calls},
        ))
    
    summary["ck3lens_scope_checked_calls"] = len(scoped_calls)


def enforce_database_first(
    ctx: ValidationContext,
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: DB search must be attempted before filesystem inspection.
    
    Rule: database_first_search
    Severity: ERROR (enhancement status)
    """
    used_fs = trace_any_filesystem_search(ctx.trace)
    summary["used_filesystem_search"] = used_fs
    
    if not used_fs:
        return
    
    # Check DB status for exceptions
    db_status_calls = trace_calls(ctx.trace, "ck3_get_db_status")
    db_rebuilding = any(
        c.result_meta.get("status") in ("rebuilding", "partial", "incomplete")
        or c.result_meta.get("is_complete") is False
        for c in db_status_calls
    )
    
    if db_rebuilding:
        # Filesystem allowed when DB is rebuilding
        summary["db_first_exemption"] = "database_rebuilding"
        return
    
    # Find first DB search and first FS search timestamps
    db_search_ts = None
    fs_search_ts = None
    
    for call in ctx.trace:
        if is_db_search_tool(call.name):
            if db_search_ts is None or call.timestamp_ms < db_search_ts:
                db_search_ts = call.timestamp_ms
        elif trace_any_filesystem_search([call]):
            if fs_search_ts is None or call.timestamp_ms < fs_search_ts:
                fs_search_ts = call.timestamp_ms
    
    if db_search_ts is None:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="DB_FIRST_REQUIRED",
            message="Filesystem search used without prior database search attempt.",
            details={"db_rebuilding": db_rebuilding, "status": "enhancement"},
        ))
    elif fs_search_ts is not None and db_search_ts > fs_search_ts:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="DB_FIRST_ORDERING",
            message="Database search must precede filesystem search.",
            details={"db_search_ts": db_search_ts, "fs_search_ts": fs_search_ts},
        ))
    
    # Check for justification (enhancement)
    fs_calls_with_justification = sum(
        1 for c in ctx.trace 
        if trace_any_filesystem_search([c]) and "justification" in c.args
    )
    fs_calls_total = sum(1 for c in ctx.trace if trace_any_filesystem_search([c]))
    
    if fs_calls_total > 0 and fs_calls_with_justification == 0:
        violations.append(Violation(
            severity=Severity.WARNING,
            code="FS_JUSTIFICATION_MISSING",
            message="Filesystem search used without explicit justification (recommended).",
            details={"status": "enhancement"},
        ))


def enforce_ck3_file_model_required(
    ctx: ValidationContext,
    bundle: "ArtifactBundle",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: every artifact file must declare a CK3 file model (A/B/C/D).
    
    Rule: ck3_file_model_required
    Severity: ERROR
    """
    agent_policy = ctx.policy.get("agents", {}).get("ck3lens", {})
    rules = agent_policy.get("rules", {})
    ck3_file_model_rule = rules.get("ck3_file_model_required", {})
    allowed_models = set(ck3_file_model_rule.get("allowed_models", ["A", "B", "C", "D"]))
    
    missing_model = []
    invalid_model = []
    
    for pf in bundle.artifacts:
        ck3_file_model = getattr(pf, "ck3_file_model", None)
        if not ck3_file_model:
            missing_model.append(pf.path)
        elif ck3_file_model not in allowed_models:
            invalid_model.append({"path": pf.path, "model": ck3_file_model})
    
    if missing_model:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="CK3_FILE_MODEL_MISSING",
            message="Each artifact file must declare ck3_file_model (A/B/C/D).",
            details={"paths": missing_model, "allowed_models": list(allowed_models)},
        ))
    
    if invalid_model:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="CK3_FILE_MODEL_INVALID",
            message="Invalid ck3_file_model declared.",
            details={"invalid": invalid_model, "allowed_models": list(allowed_models)},
        ))
    
    summary["artifact_files_count"] = len(bundle.artifacts)


def enforce_ck3_validation_called(
    ctx: ValidationContext,
    bundle: "ArtifactBundle",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: ck3_validate_artifact_bundle must be called for CK3 script content.
    
    Rule: file_path_domain_validation / symbol_resolution
    Severity: ERROR
    """
    has_ck3_script = any(
        getattr(p, "format", "ck3_script") == "ck3_script" 
        for p in bundle.artifacts
    )
    
    if not has_ck3_script:
        return
    
    if not trace_has_call(ctx.trace, "ck3_validate_artifact_bundle"):
        violations.append(Violation(
            severity=Severity.ERROR,
            code="CK3_VALIDATION_REQUIRED",
            message="ck3_validate_artifact_bundle must be run before delivery.",
            details={},
        ))
        return
    
    # Check last validation result
    last_validation = trace_last_call(ctx.trace, "ck3_validate_artifact_bundle")
    if last_validation:
        ok = last_validation.result_meta.get("ok")
        if ok is False:
            violations.append(Violation(
                severity=Severity.ERROR,
                code="CK3_VALIDATION_FAILED",
                message="ck3_validate_artifact_bundle indicates errors.",
                details={"report": last_validation.result_meta},
            ))


def enforce_symbol_manifest(
    ctx: ValidationContext,
    bundle: "ArtifactBundle",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: new symbols must be declared with reason and defined in artifact files.
    
    Rule: new_symbol_declaration
    Severity: ERROR
    """
    declared = getattr(bundle, "declared_new_symbols", []) or []
    artifact_paths = {p.path for p in bundle.artifacts}
    
    bad = []
    for s in declared:
        # Handle both DeclaredSymbol objects and dicts
        if hasattr(s, "type"):
            st = s.type
            name = s.name
            reason = getattr(s, "reason", None)
            defined_in = getattr(s, "defined_in_path", None)
        else:
            st = s.get("type")
            name = s.get("name")
            reason = s.get("reason")
            defined_in = s.get("defined_in_path")
        
        # Check required fields
        if not st or not name:
            bad.append({"symbol": str(s), "problem": "missing_type_or_name"})
            continue
        
        # Reason and defined_in are required for full manifest validation
        if not reason:
            bad.append({"symbol": name, "problem": "missing_reason"})
        
        if defined_in and defined_in not in artifact_paths:
            bad.append({
                "symbol": name,
                "problem": "defined_in_path_not_in_artifact",
                "defined_in": defined_in,
            })
    
    if bad:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="NEW_SYMBOL_MANIFEST_INVALID",
            message="Declared new symbols must include type/name/reason/defined_in_path and be defined in submitted artifact files.",
            details={"violations": bad},
        ))
    
    summary["declared_new_symbols_count"] = len(declared)


def enforce_negative_claims(
    ctx: ValidationContext,
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: non-existence claims require ck3_confirm_not_exists.
    
    Rule: negative_claims
    Severity: ERROR
    
    NOTE: Full enforcement requires intent tagging in the deliverable request.
    Currently we just check if ck3_confirm_not_exists was ever called.
    """
    # Check if any negative claim tools were used
    confirm_not_exists_called = trace_has_call(ctx.trace, "ck3_confirm_not_exists")
    
    summary["confirm_not_exists_called"] = confirm_not_exists_called
    summary["negative_claims_enforcement"] = "requires_intent_tag (enhancement)"
    
    # Future: check deliverable request for negative_claim intent tags
    # and require ck3_confirm_not_exists for each claimed non-existent symbol


def enforce_conflict_alignment(
    ctx: ValidationContext,
    bundle: "ArtifactBundle",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: modified unit_keys must correspond to resolved conflict units.
    
    Rule: conflict_alignment
    Severity: ERROR (enhancement status)
    """
    touched = set(getattr(bundle, "touched_units", []) or [])
    
    if not touched:
        violations.append(Violation(
            severity=Severity.WARNING,
            code="TOUCHED_UNITS_MISSING",
            message="ArtifactBundle should include touched_units for conflict alignment checks.",
            details={"status": "enhancement"},
        ))
        summary["conflict_alignment_checked"] = False
        return
    
    resolved_unit_keys = get_resolved_unit_keys(ctx.trace)
    
    # If we have resolved units, check alignment
    if resolved_unit_keys:
        extra = touched - resolved_unit_keys
        if extra:
            violations.append(Violation(
                severity=Severity.ERROR,
                code="CONFLICT_ALIGNMENT_FAILED",
                message="Patch modifies unit_keys that were not explicitly resolved.",
                details={
                    "touched_units": sorted(list(touched)),
                    "resolved_unit_keys": sorted(list(resolved_unit_keys)),
                    "unresolved": sorted(list(extra)),
                },
            ))
    
    summary["conflict_alignment_checked"] = True
    summary["touched_units_count"] = len(touched)
    summary["resolved_units_count"] = len(resolved_unit_keys)


# =============================================================================
# NEW: INTENT TYPE AND CONTRACT ENFORCEMENT
# =============================================================================

def enforce_contract_completeness(
    ctx: ValidationContext,
    bundle: "ArtifactBundle",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: Write contracts must have targets, snippets, and DIFF_SANITY.
    
    Rules:
    - Write contract without targets → AUTO_DENY
    - Write contract without snippets (if >0 files) → AUTO_DENY
    - Write contract without DIFF_SANITY acceptance test → AUTO_DENY
    
    Severity: ERROR (HARD GATE)
    """
    # Only applies to write intents
    # intent_type checks REMOVED - BANNED per canonical spec
    # Write detection now based on operations[] in contract
    return  # Skip this rule - needs rewrite for V1 contracts
    
    # Check targets
    targets = getattr(bundle, "targets", None)
    if not targets and len(bundle.artifacts) > 0:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="CONTRACT_MISSING_TARGETS",
            message="Write contract must specify targets [{mod_id, rel_path}].",
            details={
                "hard_gate": True,
                "artifact_count": len(bundle.artifacts),
            },
        ))
    
    # Check snippets
    snippets = getattr(bundle, "before_after_snippets", None) or getattr(bundle, "snippets", None)
    if not snippets and len(bundle.artifacts) > 0:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="CONTRACT_MISSING_SNIPPETS",
            message="Write contract must include before/after snippets.",
            details={
                "hard_gate": True,
                "artifact_count": len(bundle.artifacts),
                "hint": "Provide up to 3 before_after_snippets blocks showing changes",
            },
        ))
    
    # Check acceptance tests
    acceptance_tests = getattr(bundle, "acceptance_tests", None)
    tests_set = set(acceptance_tests or [])
    
    if AcceptanceTest.DIFF_SANITY.value not in tests_set and "DIFF_SANITY" not in tests_set:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="CONTRACT_MISSING_DIFF_SANITY",
            message="Write contract must include DIFF_SANITY acceptance test.",
            details={
                "hard_gate": True,
                "declared_tests": list(tests_set),
                "required": AcceptanceTest.DIFF_SANITY.value,
            },
        ))
    
    summary["contract_targets_count"] = len(targets) if targets else 0
    summary["contract_snippets_count"] = len(snippets) if snippets else 0
    summary["contract_acceptance_tests"] = list(tests_set)


def enforce_delete_requirements(
    ctx: ValidationContext,
    bundle: "ArtifactBundle",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: Delete operations require explicit file list and approval token.
    
    Rules:
    - Delete without explicit file list → AUTO_DENY
    - Delete with glob patterns → AUTO_DENY
    - Delete without Tier B approval token → AUTO_DENY
    
    Severity: ERROR (HARD GATE)
    """
    # Check if any artifacts are marked for deletion
    delete_artifacts = [a for a in bundle.artifacts if getattr(a, "operation", None) == "delete"]
    
    if not delete_artifacts:
        summary["delete_operations"] = 0
        return
    
    summary["delete_operations"] = len(delete_artifacts)
    
    # Check for glob patterns
    for artifact in delete_artifacts:
        path = getattr(artifact, "path", "") or getattr(artifact, "rel_path", "")
        if "*" in path or "?" in path:
            violations.append(Violation(
                severity=Severity.ERROR,
                code="DELETE_GLOB_FORBIDDEN",
                message="Delete operations cannot use glob patterns.",
                details={
                    "hard_gate": True,
                    "path": path,
                    "hint": "List each file to delete explicitly",
                },
            ))
    
    # Check for delete token
    delete_token = getattr(bundle, "delete_token", None)
    if not delete_token:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="DELETE_TOKEN_REQUIRED",
            message="Delete operations require DELETE_LOCALMOD approval token.",
            details={
                "hard_gate": True,
                "files_to_delete": len(delete_artifacts),
                "required_token": "DELETE_LOCALMOD",
            },
        ))


def validate_ck3lens_rules(
    ctx: ValidationContext,
    bundle: "ArtifactBundle | None" = None,
    violations: list[Violation] | None = None,
    summary: dict[str, Any] | None = None,
) -> tuple[list[Violation], dict[str, Any]]:
    """
    Run all ck3lens-specific validation rules.
    
    Args:
        ctx: Validation context
        bundle: Optional ArtifactBundle being validated
        violations: Existing violations list to append to
        summary: Existing summary dict to update
    
    Returns:
        Tuple of (violations list, summary dict)
    """
    if violations is None:
        violations = []
    if summary is None:
        summary = {}
    
    # Record validation metadata
    summary["mode"] = ctx.mode.value
    # intent_type removed from summary - BANNED per canonical spec
    summary["contract_id"] = ctx.contract_id
    
    # Scope enforcement (always)
    enforce_active_playset_scope(ctx, violations, summary)
    
    # Database-first rule (always)
    enforce_database_first(ctx, violations, summary)
    
    # ArtifactBundle-specific rules
    if bundle is not None:        
        # HARD GATE: Contract completeness (targets, snippets, DIFF_SANITY)
        enforce_contract_completeness(ctx, bundle, violations, summary)
        
        # HARD GATE: Delete requirements (explicit list, token)
        enforce_delete_requirements(ctx, bundle, violations, summary)
        
        # HARD GATE: ck3lens cannot edit Python/infrastructure files (except WIP)
        enforce_ck3lens_file_restrictions(ctx, bundle, violations, summary)
        
        # Standard validation rules
        enforce_ck3_file_model_required(ctx, bundle, violations, summary)
        enforce_ck3_validation_called(ctx, bundle, violations, summary)
        enforce_symbol_manifest(ctx, bundle, violations, summary)
        enforce_conflict_alignment(ctx, bundle, violations, summary)
    
    # Negative claims (always, but currently advisory)
    enforce_negative_claims(ctx, violations, summary)
    
    # Compute summary statistics
    error_count = sum(1 for v in violations if v.severity == Severity.ERROR)
    warning_count = sum(1 for v in violations if v.severity == Severity.WARNING)
    hard_gate_failures = sum(
        1 for v in violations 
        if v.severity == Severity.ERROR and v.details.get("hard_gate")
    )
    
    summary["error_count"] = error_count
    summary["warning_count"] = warning_count
    summary["hard_gate_failures"] = hard_gate_failures
    summary["deliverable"] = error_count == 0
    
    return violations, summary
