"""
CK3 Raven Dev Rules

Policy validation rules specific to the ck3raven-dev agent mode.
These rules enforce Python code quality and infrastructure development best practices.
"""
from __future__ import annotations
from typing import Any, TYPE_CHECKING

from .types import Severity, Violation, ValidationContext
from .trace_helpers import trace_has_call, trace_calls, trace_last_call

if TYPE_CHECKING:
    from ..contracts import ArtifactBundle


# Python source file indicators
PYTHON_CONTENT_TYPES = frozenset({"python", "py"})

# Paths that indicate schema/contract changes
SCHEMA_PATHS = (
    "schema",
    "contracts",
    "models",
    "db/schema",
    "ast",
)


def enforce_python_validation(
    ctx: ValidationContext,
    bundle: "ArtifactBundle",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: Python code must pass syntax and import validation.
    
    Rule: python_validation_required
    Severity: ERROR
    """
    # Check if any artifact contains Python content
    has_python = any(
        _is_python_content(p) for p in bundle.artifacts
    )
    summary["has_python_output"] = has_python
    
    if not has_python:
        return
    
    # Require ck3_validate_python call
    if not trace_has_call(ctx.trace, "ck3_validate_python"):
        violations.append(Violation(
            severity=Severity.ERROR,
            code="PY_VALIDATION_REQUIRED",
            message="Python output requires ck3_validate_python before delivery.",
            details={"python_files": [p.path for p in bundle.artifacts if _is_python_content(p)]},
        ))
        return
    
    # Check last validation result
    last_validation = trace_last_call(ctx.trace, "ck3_validate_python")
    if last_validation:
        # Check for explicit ok=False or valid=False
        ok = last_validation.result_meta.get("ok")
        valid = last_validation.result_meta.get("valid")
        
        if ok is False or valid is False:
            violations.append(Violation(
                severity=Severity.ERROR,
                code="PY_VALIDATION_FAILED",
                message="ck3_validate_python indicates errors.",
                details={"report": last_validation.result_meta},
            ))
        
        # Check for errors array
        errors = last_validation.result_meta.get("errors", [])
        if errors:
            violations.append(Violation(
                severity=Severity.ERROR,
                code="PY_VALIDATION_ERRORS",
                message=f"Python validation found {len(errors)} error(s).",
                details={"errors": errors},
            ))


def enforce_schema_change_declaration(
    ctx: ValidationContext,
    bundle: "ArtifactBundle | None",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: schema/contract changes should be declared as breaking or non-breaking.
    
    Rule: schema_change_declaration
    Severity: WARNING (enhancement status)
    """
    if bundle is None:
        summary["schema_change_declaration"] = "no_bundle"
        return
    
    # Detect schema-related files in the bundle
    schema_files = [
        p.path for p in bundle.artifacts
        if _is_schema_path(p.path)
    ]
    
    summary["schema_files_detected"] = schema_files
    
    if schema_files:
        # Check if notes or metadata contains breaking/non-breaking declaration
        notes = getattr(bundle, "notes", "") or ""
        has_declaration = (
            "breaking" in notes.lower() or
            "non-breaking" in notes.lower() or
            "backward compatible" in notes.lower()
        )
        
        if not has_declaration:
            violations.append(Violation(
                severity=Severity.WARNING,
                code="SCHEMA_CHANGE_UNDECLARED",
                message="Schema/contract changes should declare breaking vs non-breaking impact.",
                details={
                    "schema_files": schema_files,
                    "status": "enhancement",
                    "suggestion": "Add 'breaking: true/false' to notes or use a change_manifest",
                },
            ))
        
        summary["schema_change_declared"] = has_declaration
    else:
        summary["schema_change_declaration"] = "no_schema_changes"


def warn_uncertainty_preservation(
    ctx: ValidationContext,
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Add advisory warning about preserving uncertainty in core logic.
    
    Rule: preserve_uncertainty
    Severity: WARNING (TBC status - requires manual/heuristic review)
    """
    violations.append(Violation(
        severity=Severity.WARNING,
        code="PRESERVE_UNCERTAINTY_TBC",
        message="Preserve uncertainty in core logic is not fully automatable; requires manual/heuristic review.",
        details={
            "status": "tbc",
            "guidance": "Core ck3raven logic should not encode gameplay assumptions or collapse unknowns into safe defaults.",
        },
    ))
    summary["preserve_uncertainty"] = "tbc"


def enforce_get_errors_validation(
    ctx: ValidationContext,
    bundle: "ArtifactBundle | None",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: get_errors should be called on modified Python files.
    
    This aligns with the ck3raven-dev mode instructions that require
    validation via get_errors before reporting completion.
    
    Severity: WARNING (advisory)
    """
    if bundle is None:
        return
    
    python_files = [p.path for p in bundle.artifacts if _is_python_content(p)]
    if not python_files:
        return
    
    # Check if get_errors was called (it's a VS Code tool, not MCP)
    # We can only check the trace for MCP tools
    # This is advisory - the real enforcement is in the mode instructions
    
    summary["python_files_needing_validation"] = python_files
    summary["get_errors_note"] = "Run get_errors on modified Python files before delivery"


def validate_ck3raven_dev_rules(
    ctx: ValidationContext,
    bundle: "ArtifactBundle | None" = None,
    violations: list[Violation] | None = None,
    summary: dict[str, Any] | None = None,
) -> tuple[list[Violation], dict[str, Any]]:
    """
    Run all ck3raven-dev-specific validation rules.
    
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
    
    # Python validation (if bundle provided)
    if bundle is not None:
        enforce_python_validation(ctx, bundle, violations, summary)
        enforce_schema_change_declaration(ctx, bundle, violations, summary)
        enforce_get_errors_validation(ctx, bundle, violations, summary)
    
    # Preserve uncertainty warning (always)
    warn_uncertainty_preservation(ctx, violations, summary)
    
    return violations, summary


# -----------------------------
# Helper Functions
# -----------------------------

def _is_python_content(artifact_file: Any) -> bool:
    """Check if an artifact file contains Python content."""
    # Check format field
    fmt = getattr(artifact_file, "format", None) or getattr(artifact_file, "content_type", None)
    if fmt and fmt.lower() in PYTHON_CONTENT_TYPES:
        return True
    
    # Check file extension
    path = getattr(artifact_file, "path", "")
    if path.endswith(".py"):
        return True
    
    return False


def _is_schema_path(path: str) -> bool:
    """Check if a path indicates schema/contract content."""
    path_lower = path.lower().replace("\\", "/")
    return any(schema_path in path_lower for schema_path in SCHEMA_PATHS)
