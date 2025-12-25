"""
CK3 Lens Rules

Policy validation rules specific to the ck3lens agent mode.
These rules enforce CK3 modding constraints and best practices.

CRITICAL: ck3lens agents can ONLY edit CK3 mod files in configured local_mods.
They CANNOT edit Python code, core ck3raven code, or any infrastructure files.
"""
from __future__ import annotations
from typing import Any, TYPE_CHECKING

from .types import Severity, Violation, ValidationContext
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

# Extensions that ck3lens is ALLOWED to edit (CK3 mod files only)
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

# File extensions ck3lens is FORBIDDEN from editing
CK3LENS_FORBIDDEN_EXTENSIONS = frozenset({
    ".py",            # Python code
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
    Enforce: ck3lens agents can ONLY edit CK3 mod files.
    
    Rule: no_python_editing, local_mods_only
    Severity: ERROR (HARD GATE)
    
    ck3lens is for CK3 modding ONLY. It cannot:
    - Edit Python files (.py)
    - Edit infrastructure code (src/, builder/, tools/, etc.)
    - Edit configuration files (.json, .yaml, .toml)
    - Edit documentation (.md, .rst)
    
    This prevents ck3lens agents from modifying the ck3raven codebase itself.
    Infrastructure changes require ck3raven-dev mode.
    """
    forbidden_files = []
    forbidden_extensions = []
    forbidden_paths = []
    
    for artifact in bundle.artifacts:
        path = getattr(artifact, "path", "")
        if not path:
            continue
        
        path_normalized = path.replace("\\", "/").lower()
        filename = path_normalized.split("/")[-1]
        
        # Get extension
        if "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1]
        else:
            ext = ""
        
        # Check forbidden extensions
        if ext in CK3LENS_FORBIDDEN_EXTENSIONS:
            forbidden_extensions.append({
                "path": path,
                "extension": ext,
                "reason": f"ck3lens cannot edit {ext} files - use ck3raven-dev mode"
            })
        
        # Check forbidden paths
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
    all_forbidden = forbidden_extensions + forbidden_paths + forbidden_files
    summary["ck3lens_forbidden_files"] = all_forbidden
    
    if forbidden_extensions:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="CK3LENS_FORBIDDEN_EXTENSION",
            message="ck3lens agents CANNOT edit Python or infrastructure files.",
            details={
                "files": forbidden_extensions,
                "suggestion": "Use ck3raven-dev mode for Python/infrastructure changes",
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
    
    # Scope enforcement (always)
    enforce_active_playset_scope(ctx, violations, summary)
    
    # Database-first rule (always)
    enforce_database_first(ctx, violations, summary)
    
    # ArtifactBundle-specific rules
    if bundle is not None:
        # CRITICAL: ck3lens cannot edit Python/infrastructure files
        enforce_ck3lens_file_restrictions(ctx, bundle, violations, summary)
        
        enforce_ck3_file_model_required(ctx, bundle, violations, summary)
        enforce_ck3_validation_called(ctx, bundle, violations, summary)
        enforce_symbol_manifest(ctx, bundle, violations, summary)
        enforce_conflict_alignment(ctx, bundle, violations, summary)
    
    # Negative claims (always, but currently advisory)
    enforce_negative_claims(ctx, violations, summary)
    
    return violations, summary
