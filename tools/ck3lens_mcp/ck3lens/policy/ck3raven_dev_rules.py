"""
CK3 Raven Dev Rules

Policy validation rules specific to the ck3raven-dev agent mode.
These rules enforce Python code quality and infrastructure development best practices.
"""
from __future__ import annotations
from typing import Any, TYPE_CHECKING
import re

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

# =============================================================================
# FILE LOCATION POLICY
# =============================================================================

# Allowed paths for new Python files (Rule 1)
ALLOWED_PYTHON_PATHS = (
    "src/",           # Production code
    "tests/",         # Test files
    "scripts/",       # Documented maintenance scripts
    "examples/",      # Example code
    "tools/",         # Tool implementations
    "builder/",       # Build system
)

# Ephemeral script patterns that must go to temp/artifacts (Rule 3)
EPHEMERAL_PATTERNS = (
    r"scratch_",
    r"tmp_",
    r"oneoff_",
    r"workaround_",
    r"temp_",
    r"hack_",
    r"quick_",
)

# Intent types for structured declarations (Rule 5)
VALID_INTENTS = frozenset({"bugfix", "feature", "refactor", "investigation"})
VALID_OUTPUT_KINDS = frozenset({
    "core_change",
    "new_core_module",
    "maintenance_script",
    "experiment",
})

# Core paths that must be touched for bugfixes
CORE_SRC_PATHS = (
    "src/ck3raven/",
    "tools/ck3lens_mcp/ck3lens/",
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


# =============================================================================
# RULE 1: No ad-hoc scripts in production tree (HARD GATE)
# =============================================================================

def enforce_allowed_python_paths(
    ctx: ValidationContext,
    bundle: "ArtifactBundle | None",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: New Python files must be in allowed directories only.
    
    Rule: allowed_python_paths
    Severity: ERROR (hard gate)
    
    Allowed paths:
    - src/** (production code)
    - tests/** (test files)
    - scripts/** (maintenance scripts - must be documented)
    - examples/** (example code)
    - tools/** (tool implementations)
    - builder/** (build system)
    """
    if bundle is None:
        return
    
    disallowed_files = []
    
    for artifact in bundle.artifacts:
        path = getattr(artifact, "path", "")
        if not path.endswith(".py"):
            continue
        
        path_normalized = path.replace("\\", "/")
        
        # Check if file path matches allowed location patterns
        in_allowed_location = any(
            path_normalized.startswith(allowed) or f"/{allowed}" in path_normalized
            for allowed in ALLOWED_PYTHON_PATHS
        )
        
        if not in_allowed_location:
            disallowed_files.append(path)
    
    summary["disallowed_python_files"] = disallowed_files
    
    if disallowed_files:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="PYTHON_FILE_WRONG_LOCATION",
            message=f"Python file(s) in disallowed location: {disallowed_files}",
            details={
                "disallowed_files": disallowed_files,
                "allowed_paths": list(ALLOWED_PYTHON_PATHS),
                "suggestion": "Move to src/, tests/, scripts/, examples/, tools/, or builder/",
            },
        ))


def enforce_scripts_documented(
    ctx: ValidationContext,
    bundle: "ArtifactBundle | None",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: Scripts in scripts/ must be documented in scripts/README.md.
    
    Rule: scripts_must_be_documented
    Severity: ERROR (hard gate)
    
    Any new script in scripts/ must have an entry in scripts/README.md with:
    - Purpose
    - When to use
    - Why it isn't core code
    """
    if bundle is None:
        return
    
    script_files = []
    readme_updated = False
    
    for artifact in bundle.artifacts:
        path = getattr(artifact, "path", "")
        path_normalized = path.replace("\\", "/")
        
        if "scripts/" in path_normalized and path.endswith(".py"):
            script_files.append(path)
        
        if "scripts/README.md" in path_normalized or "docs/scripts.md" in path_normalized:
            readme_updated = True
    
    summary["new_script_files"] = script_files
    summary["scripts_readme_updated"] = readme_updated
    
    if script_files and not readme_updated:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="SCRIPT_NOT_DOCUMENTED",
            message=f"New script(s) in scripts/ without README.md update: {script_files}",
            details={
                "script_files": script_files,
                "required_docs": ["scripts/README.md", "docs/scripts.md"],
                "suggestion": (
                    "Add entry to scripts/README.md with: purpose, when to use, "
                    "why it isn't core code"
                ),
            },
        ))


# =============================================================================
# RULE 3: Ephemeral scripts must be in temp/artifacts (HARD GATE)
# =============================================================================

def enforce_ephemeral_scripts_location(
    ctx: ValidationContext,
    bundle: "ArtifactBundle | None",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: Ephemeral/workaround scripts must go to temp or .artifacts/.
    
    Rule: ephemeral_scripts_location
    Severity: ERROR (hard gate)
    
    Files matching patterns like scratch_*, tmp_*, workaround_*, etc.
    must NOT be in the committed repository tree.
    """
    if bundle is None:
        return
    
    ephemeral_in_repo = []
    
    for artifact in bundle.artifacts:
        path = getattr(artifact, "path", "")
        filename = path.replace("\\", "/").split("/")[-1].lower()
        
        # Check if filename matches ephemeral patterns
        is_ephemeral = any(
            re.match(pattern, filename) for pattern in EPHEMERAL_PATTERNS
        )
        
        # Check if it's in a safe location
        path_normalized = path.replace("\\", "/").lower()
        is_safe_location = (
            ".artifacts/" in path_normalized or
            "/temp/" in path_normalized or
            "/tmp/" in path_normalized or
            path_normalized.startswith("temp/") or
            path_normalized.startswith("tmp/")
        )
        
        if is_ephemeral and not is_safe_location:
            ephemeral_in_repo.append(path)
    
    summary["ephemeral_scripts_in_repo"] = ephemeral_in_repo
    
    if ephemeral_in_repo:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="EPHEMERAL_SCRIPT_IN_REPO",
            message=f"Ephemeral/workaround script(s) must not be in repo: {ephemeral_in_repo}",
            details={
                "ephemeral_files": ephemeral_in_repo,
                "ephemeral_patterns": list(EPHEMERAL_PATTERNS),
                "allowed_locations": [".artifacts/", "temp/", "OS temp dir"],
                "suggestion": "Move to .artifacts/ or delete after use - never commit",
            },
        ))


# =============================================================================
# RULE 2 & 4: Bugfix must touch core + add test (HARD GATE)
# =============================================================================

def enforce_bugfix_requirements(
    ctx: ValidationContext,
    bundle: "ArtifactBundle | None",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: Bugfixes must modify core code AND add regression tests.
    
    Rule: bugfix_requirements
    Severity: ERROR (hard gate for intent:bugfix)
    
    When intent is 'bugfix', the bundle must:
    1. Touch at least one existing file under src/
    2. Include at least one file under tests/
    """
    if bundle is None:
        return
    
    # Get architecture intent from bundle metadata or context
    intent = _get_architecture_intent(ctx, bundle)
    summary["detected_intent"] = intent
    
    if intent != "bugfix":
        summary["bugfix_requirements"] = "not_applicable"
        return
    
    # Check for core file modifications
    core_files_touched = []
    test_files_added = []
    script_only = True
    
    for artifact in bundle.artifacts:
        path = getattr(artifact, "path", "")
        path_normalized = path.replace("\\", "/")
        
        # Check for core src modifications
        if any(cp in path_normalized for cp in CORE_SRC_PATHS):
            core_files_touched.append(path)
            script_only = False
        
        # Check for test files
        if "tests/" in path_normalized and path.endswith(".py"):
            test_files_added.append(path)
    
    summary["core_files_touched"] = core_files_touched
    summary["test_files_added"] = test_files_added
    summary["script_only_delivery"] = script_only
    
    # Violation 1: No core files touched
    if not core_files_touched:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="BUGFIX_NO_CORE_CHANGE",
            message="Bugfix must modify core code, not just create scripts.",
            details={
                "intent": "bugfix",
                "core_paths_expected": list(CORE_SRC_PATHS),
                "suggestion": (
                    "Fix the bug in the actual source code under src/ck3raven/ "
                    "or tools/ck3lens_mcp/ck3lens/. Scripts are workarounds, not fixes."
                ),
            },
        ))
    
    # Violation 2: No test file added
    if not test_files_added:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="BUGFIX_NO_REGRESSION_TEST",
            message="Bugfix must include a regression test.",
            details={
                "intent": "bugfix",
                "suggestion": (
                    "Add a minimal failing test under tests/ that reproduces the bug, "
                    "then verify the fix makes it pass."
                ),
            },
        ))


# =============================================================================
# RULE 5: Architecture intent declaration (STRUCTURED VALIDATION)
# =============================================================================

def enforce_architecture_intent(
    ctx: ValidationContext,
    bundle: "ArtifactBundle | None",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Enforce: Deliverables should declare architecture intent.
    
    Rule: architecture_intent_required
    Severity: WARNING (advisory, but enables other rules)
    
    Structured declaration:
    - intent: bugfix | feature | refactor | investigation
    - output_kind: core_change | new_core_module | maintenance_script | experiment
    - justification: why this approach
    - docs_updated: true/false
    """
    if bundle is None:
        return
    
    intent = _get_architecture_intent(ctx, bundle)
    output_kind = _get_output_kind(ctx, bundle)
    
    summary["architecture_intent"] = intent
    summary["output_kind"] = output_kind
    
    # Check for valid intent
    if intent and intent not in VALID_INTENTS:
        violations.append(Violation(
            severity=Severity.WARNING,
            code="INVALID_INTENT",
            message=f"Unknown intent '{intent}'. Valid: {VALID_INTENTS}",
            details={"provided": intent, "valid_intents": list(VALID_INTENTS)},
        ))
    
    # Check output_kind alignment
    if output_kind:
        if output_kind == "maintenance_script":
            # Must be in scripts/ and documented
            # (already enforced by other rules)
            pass
        elif output_kind == "experiment":
            # Must be in .artifacts/ (not committed)
            # (already enforced by ephemeral rule)
            pass
        elif output_kind == "new_core_module":
            # Must be in src/ with tests and docs
            _validate_new_core_module(ctx, bundle, violations, summary)


def _validate_new_core_module(
    ctx: ValidationContext,
    bundle: "ArtifactBundle",
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """Validate that new core module has tests and documentation."""
    has_tests = False
    has_docs = False
    
    for artifact in bundle.artifacts:
        path = getattr(artifact, "path", "")
        path_normalized = path.replace("\\", "/")
        
        if "tests/" in path_normalized:
            has_tests = True
        if any(doc in path_normalized for doc in ["README", "DESIGN", "docs/", ".md"]):
            has_docs = True
    
    if not has_tests:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="NEW_MODULE_NO_TESTS",
            message="New core module requires tests.",
            details={"output_kind": "new_core_module"},
        ))
    
    if not has_docs:
        violations.append(Violation(
            severity=Severity.WARNING,
            code="NEW_MODULE_NO_DOCS",
            message="New core module should have documentation.",
            details={"output_kind": "new_core_module"},
        ))


def _get_architecture_intent(ctx: ValidationContext, bundle: "ArtifactBundle") -> str | None:
    """Extract architecture intent from bundle metadata or context."""
    # Check bundle metadata
    if hasattr(bundle, "intent"):
        return bundle.intent
    if hasattr(bundle, "metadata") and isinstance(bundle.metadata, dict):
        return bundle.metadata.get("intent")
    
    # Infer from user intent
    if ctx.user_intent:
        intent_lower = ctx.user_intent.lower()
        if any(word in intent_lower for word in ["fix", "bug", "broken", "error", "crash"]):
            return "bugfix"
        if any(word in intent_lower for word in ["add", "new feature", "implement"]):
            return "feature"
        if any(word in intent_lower for word in ["refactor", "clean", "reorganize"]):
            return "refactor"
        if any(word in intent_lower for word in ["investigate", "debug", "understand", "why"]):
            return "investigation"
    
    return None


def _get_output_kind(ctx: ValidationContext, bundle: "ArtifactBundle") -> str | None:
    """Extract output kind from bundle metadata."""
    if hasattr(bundle, "output_kind"):
        return bundle.output_kind
    if hasattr(bundle, "metadata") and isinstance(bundle.metadata, dict):
        return bundle.metadata.get("output_kind")
    return None


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
    
    Rules enforced:
    1. allowed_python_paths - New .py files must be in allowed directories
    2. scripts_must_be_documented - Scripts in scripts/ need README entry
    3. ephemeral_scripts_location - Workaround scripts go to .artifacts/
    4. bugfix_requirements - Bugfixes must touch core + add tests
    5. architecture_intent_required - Declare intent/output_kind
    6. python_validation_required - Python must pass syntax check
    7. schema_change_declaration - Schema changes need breaking/non-breaking
    8. preserve_uncertainty - Advisory for core logic neutrality
    """
    if violations is None:
        violations = []
    if summary is None:
        summary = {}
    
    # File location policies (if bundle provided)
    if bundle is not None:
        # Rule 1: No ad-hoc scripts in production tree
        enforce_allowed_python_paths(ctx, bundle, violations, summary)
        
        # Rule 1b: Scripts must be documented
        enforce_scripts_documented(ctx, bundle, violations, summary)
        
        # Rule 3: Ephemeral scripts must be in temp/artifacts
        enforce_ephemeral_scripts_location(ctx, bundle, violations, summary)
        
        # Rule 2 & 4: Bugfix must touch core + add test
        enforce_bugfix_requirements(ctx, bundle, violations, summary)
        
        # Rule 5: Architecture intent declaration
        enforce_architecture_intent(ctx, bundle, violations, summary)
        
        # Python validation
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
