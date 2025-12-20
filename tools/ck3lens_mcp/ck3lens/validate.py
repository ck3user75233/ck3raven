"""
Validation Tools

Parse and validate CK3 script content.
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Optional

# Add ck3raven to path if not installed
CK3RAVEN_PATH = Path(__file__).parent.parent.parent.parent / "src"
if CK3RAVEN_PATH.exists():
    sys.path.insert(0, str(CK3RAVEN_PATH))

from .contracts import PatchDraft, ValidationMessage, ValidationReport

ALLOWED_TOPLEVEL = {"common", "events", "gfx", "localization", "interface", "music", "sound", "history", "map_data"}


def parse_content(content: str, filename: str = "inline.txt", recover: bool = True) -> dict:
    """
    Parse CK3 script content.
    
    Args:
        content: CK3 script source code
        filename: For error messages
        recover: If True, use error-recovering parser to collect multiple errors.
                 If False, use standard parser (stops at first error).
    
    Returns:
        {
            "success": bool,
            "ast": dict or None,
            "errors": [{"line": int, "column": int, "message": str, "code": str}, ...]
        }
    """
    try:
        if recover:
            from ck3raven.parser import parse_source_recovering
            result = parse_source_recovering(content, filename)
            
            # Convert AST to dict
            ast_dict = result.ast.to_dict() if result.ast else None
            
            return {
                "success": result.success,
                "ast": ast_dict,
                "errors": [
                    {
                        "line": d.line,
                        "column": d.column,
                        "end_line": d.end_line,
                        "end_column": d.end_column,
                        "message": d.message,
                        "code": d.code,
                        "severity": d.severity
                    }
                    for d in result.diagnostics
                ]
            }
        else:
            # Original non-recovering parse
            from ck3raven.parser import parse_source
            from ck3raven.parser.parser import RootNode, BlockNode, AssignmentNode, ValueNode
            
            ast = parse_source(content, filename)
            
            # Simple AST serialization
            def node_to_dict(node):
                if isinstance(node, RootNode):
                    return {"type": "root", "children": [node_to_dict(c) for c in node.children]}
                elif isinstance(node, BlockNode):
                    return {
                        "type": "block",
                        "name": node.name,
                        "line": node.line,
                        "children": [node_to_dict(c) for c in node.children]
                    }
                elif isinstance(node, AssignmentNode):
                    return {
                        "type": "assignment",
                        "key": node.key,
                        "operator": getattr(node, 'operator', '='),
                        "value": node_to_dict(node.value),
                        "line": node.line
                    }
                elif isinstance(node, ValueNode):
                    return {"type": "value", "value": node.value}
                elif hasattr(node, 'children'):
                    return {"type": type(node).__name__, "children": [node_to_dict(c) for c in node.children]}
                else:
                    return {"type": type(node).__name__, "repr": str(node)}
            
            return {
                "success": True,
                "ast": node_to_dict(ast),
                "errors": []
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


def validate_patchdraft(draft: PatchDraft) -> ValidationReport:
    """
    Validate a PatchDraft.
    
    IMPORTANT: During early development, validation is ADVISORY, not blocking.
    The agent should present results to the user for review. If the validator
    produces false positives, report them via ck3_report_validation_issue.
    
    Checks:
    1. Path policy (relative, no traversal, valid top-level)
    2. Parse each patch content
    3. Reference validation (advisory - may have false positives)
    
    Trust levels:
    - PATH_* errors: High confidence, likely real issues
    - PARSE_ERROR: Medium confidence, parser may have edge case bugs  
    - REF_* errors: Low confidence, symbol database incomplete
    """
    errors: list[ValidationMessage] = []
    warnings: list[ValidationMessage] = []

    # 1) Path policy - HIGH CONFIDENCE
    for pf in draft.patches:
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

    # 2) Parse each patch - MEDIUM CONFIDENCE
    for pf in draft.patches:
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
        "patch_files": len(draft.patches),
        "errors": len(errors),
        "warnings": len(warnings),
        "validation_mode": "advisory",  # Not blocking during early development
        "note": "Review results with agent. Report false positives via ck3_report_validation_issue."
    }
    return ValidationReport(ok=ok, errors=errors, warnings=warnings, summary=summary)
