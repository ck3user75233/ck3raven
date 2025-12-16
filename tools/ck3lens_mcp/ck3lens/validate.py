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


def parse_content(content: str, filename: str = "inline.txt") -> dict:
    """
    Parse CK3 script content.
    
    Returns AST or parse errors.
    """
    try:
        from ck3raven.parser import parse_source
        from ck3raven.parser.parser import RootNode, BlockNode, AssignmentNode, ValueNode
        
        ast = parse_source(content)
        
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
            "errors": [{"line": line, "column": column, "message": error_msg}]
        }


def validate_patchdraft(draft: PatchDraft) -> ValidationReport:
    """
    Validate a PatchDraft.
    
    Checks:
    1. Path policy (relative, no traversal, valid top-level)
    2. Parse each patch content
    3. (Future) Reference validation
    """
    errors: list[ValidationMessage] = []
    warnings: list[ValidationMessage] = []

    # 1) Path policy
    for pf in draft.patches:
        p = Path(pf.path)

        if p.is_absolute():
            errors.append(ValidationMessage(code="PATH_ABSOLUTE", message="Patch path must be relative", details={"path": pf.path}))
            continue
        if ".." in p.parts:
            errors.append(ValidationMessage(code="PATH_TRAVERSAL", message="Patch path must not contain '..'", details={"path": pf.path}))
            continue
        if not p.parts or p.parts[0] not in ALLOWED_TOPLEVEL:
            errors.append(ValidationMessage(
                code="PATH_TOPLEVEL",
                message=f"Top-level directory must be one of {sorted(ALLOWED_TOPLEVEL)}",
                details={"path": pf.path},
            ))
            continue

        # Naming convention warning
        if p.name.endswith("_patched.txt"):
            warnings.append(ValidationMessage(code="NAME_STYLE", message="Avoid '_patched' suffix; use zz_ naming", details={"path": pf.path}))

    # 2) Parse each patch
    for pf in draft.patches:
        if not pf.content.strip():
            errors.append(ValidationMessage(code="EMPTY_CONTENT", message="Patch file content is empty", details={"path": pf.path}))
            continue
        
        if pf.format == "ck3_script":
            parse_result = parse_content(pf.content, pf.path)
            if not parse_result["success"]:
                for err in parse_result["errors"]:
                    errors.append(ValidationMessage(
                        code="PARSE_ERROR",
                        message=err["message"],
                        details={"path": pf.path, "line": err["line"], "column": err["column"]}
                    ))

    # 3) Reference checks - placeholder for future
    # Would extract all references from parsed AST and check against symbol table

    ok = len(errors) == 0
    summary = {
        "parsed": ok,
        "patch_files": len(draft.patches),
        "errors": len(errors),
        "warnings": len(warnings)
    }
    return ValidationReport(ok=ok, errors=errors, warnings=warnings, summary=summary)
