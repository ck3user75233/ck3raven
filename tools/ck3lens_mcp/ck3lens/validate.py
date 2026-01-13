"""
Validation Tools

Parse and validate CK3 script content.

IMPORTANT: All parsing uses the canonical runtime (subprocess + timeout).
Direct calls to Parser().parse() are PROHIBITED.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Optional

# Add ck3raven to path if not installed
CK3RAVEN_PATH = Path(__file__).parent.parent.parent.parent / "src"
if CK3RAVEN_PATH.exists():
    sys.path.insert(0, str(CK3RAVEN_PATH))

from .contracts import ArtifactBundle, ValidationMessage, ValidationReport

ALLOWED_TOPLEVEL = {"common", "events", "gfx", "localization", "interface", "music", "sound", "history", "map_data"}


def parse_content(content: str, filename: str = "inline.txt", recover: bool = True, timeout: int = 30) -> dict:
    """
    Parse CK3 script content using canonical runtime (subprocess + timeout).
    
    Args:
        content: CK3 script source code
        filename: For error messages
        recover: If True, use error-recovering parser to collect multiple errors.
                 If False, use standard parser (stops at first error).
        timeout: Parse timeout in seconds (default 30, max 120)
    
    Returns:
        {
            "success": bool,
            "ast": dict or None,
            "errors": [{"line": int, "column": int, "message": str, "code": str}, ...]
        }
    """
    try:
        from ck3raven.parser.runtime import parse_text, ParseTimeoutError, ParseSubprocessError
        
        result = parse_text(content, filename=filename, timeout=timeout, recovering=recover)
        
        # Parse AST JSON to dict
        ast_dict = None
        if result.ast_json:
            try:
                ast_dict = json.loads(result.ast_json)
            except json.JSONDecodeError:
                pass
        
        # Convert diagnostics to error format
        errors = []
        if result.diagnostics:
            for d in result.diagnostics:
                errors.append({
                    "line": d.line,
                    "column": d.column,
                    "end_line": d.end_line,
                    "end_column": d.end_column,
                    "message": d.message,
                    "code": d.code,
                    "severity": d.severity,
                })
        elif not result.success and result.error:
            # Non-recovering parse returned an error
            errors.append({
                "line": 1,
                "column": 0,
                "end_line": 1,
                "end_column": 0,
                "message": result.error,
                "code": result.error_type or "PARSE_ERROR",
                "severity": "error",
            })
        
        return {
            "success": result.success,
            "ast": ast_dict,
            "errors": errors,
        }
    
    except Exception as e:
        # Try to extract line info from error message
        error_msg = str(e)
        line = 0
        column = 0
        
        # Common patterns: "line 5", "Line 5, column 3"
        import re
        line_match = re.search(r'line\s+(\d+)', error_msg, re.IGNORECASE)
        if line_match:
            line = int(line_match.group(1))
        col_match = re.search(r'column\s+(\d+)', error_msg, re.IGNORECASE)
        if col_match:
            column = int(col_match.group(1))
        
        return {
            "success": False,
            "ast": None,
            "errors": [{"line": line, "column": column, "message": error_msg, "code": "PARSE_ERROR", "severity": "error"}]
        }


def validate_artifact_bundle(bundle: ArtifactBundle) -> ValidationReport:
    """
    Validate an ArtifactBundle.
    
    IMPORTANT: During early development, validation is ADVISORY, not blocking.
    The agent should present results to the user for review. If the validator
    produces false positives, report them via ck3_report_validation_issue.
    
    Checks:
    1. Path policy (relative, no traversal, valid top-level)
    2. Parse each artifact content
    3. Reference validation (advisory - may have false positives)
    
    Trust levels:
    - PATH_* errors: High confidence, likely real issues
    - PARSE_ERROR: Medium confidence, parser may have edge case bugs  
    - REF_* errors: Low confidence, symbol database incomplete
    """
    errors: list[ValidationMessage] = []
    warnings: list[ValidationMessage] = []

    # 1) Path policy - HIGH CONFIDENCE
    for pf in bundle.artifacts:
        p = Path(pf.path)

        if p.is_absolute():
            errors.append(ValidationMessage(code="PATH_ABSOLUTE", message="Patch path must be relative", details={"path": pf.path, "confidence": "high"}))
            continue
        if ".." in p.parts:
            errors.append(ValidationMessage(code="PATH_TRAVERSAL", message="Patch path must not contain '..'", details={"path": pf.path, "confidence": "high"}))
            continue
        if not p.parts or p.parts[0] not in ALLOWED_TOPLEVEL:
            errors.append(ValidationMessage(
                code="PATH_TOPLEVEL",
                message=f"Top-level directory must be one of {sorted(ALLOWED_TOPLEVEL)}",
                details={"path": pf.path, "confidence": "high"},
            ))
            continue

        # Naming convention warning
        if p.name.endswith("_patched.txt"):
            warnings.append(ValidationMessage(code="NAME_STYLE", message="Avoid '_patched' suffix; use zz_ naming", details={"path": pf.path}))

    # 2) Parse each artifact - MEDIUM CONFIDENCE
    for pf in bundle.artifacts:
        if not pf.content.strip():
            errors.append(ValidationMessage(code="EMPTY_CONTENT", message="Patch file content is empty", details={"path": pf.path, "confidence": "high"}))
            continue
        
        if pf.format == "ck3_script":
            parse_result = parse_content(pf.content, pf.path)
            if not parse_result["success"]:
                for err in parse_result["errors"]:
                    errors.append(ValidationMessage(
                        code="PARSE_ERROR",
                        message=err["message"],
                        details={
                            "path": pf.path, 
                            "line": err["line"], 
                            "column": err["column"],
                            "confidence": "medium",
                            "note": "Parser may have edge cases - verify manually if suspicious"
                        }
                    ))

    # 3) Reference checks - LOW CONFIDENCE (placeholder)
    # Symbol database is still being built out, expect false positives
    # Would extract all references from parsed AST and check against symbol table

    ok = len(errors) == 0
    summary = {
        "parsed": ok,
        "artifact_files": len(bundle.artifacts),
        "errors": len(errors),
        "warnings": len(warnings),
        "validation_mode": "advisory",  # Not blocking during early development
        "note": "Review results with agent. Report false positives via ck3_report_validation_issue."
    }
    return ValidationReport(ok=ok, errors=errors, warnings=warnings, summary=summary)


# Backwards compatibility alias
validate_patchdraft = validate_artifact_bundle
