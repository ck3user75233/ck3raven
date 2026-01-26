"""
Python Semantic Validator — Phase 1.5 Evidence Generator

Validates Python code for semantic errors like undefined names, unresolved imports,
and other issues that indicate hallucinated or incorrect code.

This is a SENSOR, not a JUDGE — it observes and reports evidence.

REQUIRES: VS Code with Pylance extension running and IPC server active.
The validator uses Pylance diagnostics via VS Code IPC for semantic analysis.

Produces evidence compatible with SemanticReport format from semantic_validator.py.

Usage:
    from ck3lens.validation import validate_python_files, validate_python_content
    
    # Validate files
    report = validate_python_files([Path("my_script.py")])
    
    # Validate content (for pre-write validation)
    report = validate_python_content(code_string, filename="test.py")
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..ipc_client import VSCodeIPCClient, VSCodeIPCError, is_vscode_available


# ============================================================================
# Exceptions
# ============================================================================

class PythonValidationError(Exception):
    """Raised when Python validation cannot proceed."""
    pass


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class PythonDiagnostic:
    """A single diagnostic from Python analysis."""
    
    file: str
    line: int
    column: int
    end_line: int
    end_column: int
    severity: str  # "error", "warning", "information", "hint"
    message: str
    source: str  # "Pylance"
    code: Optional[str] = None  # diagnostic code like "reportUndefinedVariable"
    
    # Categorization
    category: str = "other"  # "undefined_name", "unresolved_import", "syntax", "type_error", "other"
    symbol_name: Optional[str] = None  # extracted symbol name if applicable
    
    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
            "severity": self.severity,
            "message": self.message,
            "source": self.source,
            "code": self.code,
            "category": self.category,
            "symbol_name": self.symbol_name,
        }


@dataclass
class PythonValidationReport:
    """Complete Python validation report."""
    
    tool: str = "python_semantic_validator"
    version: str = "1.1.0"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Source info
    source: str = "vscode_ipc"  # Always Pylance via IPC
    files_analyzed: list[str] = field(default_factory=list)
    
    # Diagnostics by category
    undefined_names: list[PythonDiagnostic] = field(default_factory=list)
    unresolved_imports: list[PythonDiagnostic] = field(default_factory=list)
    syntax_errors: list[PythonDiagnostic] = field(default_factory=list)
    type_errors: list[PythonDiagnostic] = field(default_factory=list)
    other_errors: list[PythonDiagnostic] = field(default_factory=list)
    
    # Definitions found (for evidence)
    definitions: list[dict] = field(default_factory=list)
    
    # Metadata
    validation_errors: list[str] = field(default_factory=list)
    
    @property
    def all_diagnostics(self) -> list[PythonDiagnostic]:
        """All diagnostics combined."""
        return (
            self.undefined_names + 
            self.unresolved_imports + 
            self.syntax_errors + 
            self.type_errors + 
            self.other_errors
        )
    
    @property
    def has_errors(self) -> bool:
        """True if there are any error-level diagnostics."""
        return any(
            d.severity == "error" 
            for d in self.all_diagnostics
        )
    
    @property
    def has_undefined_symbols(self) -> bool:
        """True if there are undefined names or unresolved imports."""
        return bool(self.undefined_names or self.unresolved_imports)
    
    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "version": self.version,
            "timestamp": self.timestamp,
            "source": self.source,
            "files_analyzed": self.files_analyzed,
            "summary": {
                "undefined_names": len(self.undefined_names),
                "unresolved_imports": len(self.unresolved_imports),
                "syntax_errors": len(self.syntax_errors),
                "type_errors": len(self.type_errors),
                "other_errors": len(self.other_errors),
                "definitions_found": len(self.definitions),
                "has_errors": self.has_errors,
                "has_undefined_symbols": self.has_undefined_symbols,
            },
            "diagnostics": {
                "undefined_names": [d.to_dict() for d in self.undefined_names],
                "unresolved_imports": [d.to_dict() for d in self.unresolved_imports],
                "syntax_errors": [d.to_dict() for d in self.syntax_errors],
                "type_errors": [d.to_dict() for d in self.type_errors],
                "other_errors": [d.to_dict() for d in self.other_errors],
            },
            "definitions": self.definitions,
            "validation_errors": self.validation_errors,
        }


# ============================================================================
# Diagnostic Categorization
# ============================================================================

# Patterns to extract symbol names from error messages
UNDEFINED_NAME_PATTERNS = [
    # Pylance/pyright patterns
    (r'"(\w+)" is not defined', "undefined_name"),
    (r'Cannot find name "(\w+)"', "undefined_name"),
    (r'Name "(\w+)" is not defined', "undefined_name"),
    (r'"(\w+)" is not a known member', "undefined_name"),
    (r'has no attribute "(\w+)"', "undefined_name"),
    # Import patterns
    (r'Import "(\w+)" could not be resolved', "unresolved_import"),
    (r'No module named [\'"](\w+)[\'"]', "unresolved_import"),
    (r'"(\w+)" is not exported from module', "unresolved_import"),
    (r'Cannot find module "([^"]+)"', "unresolved_import"),
]

# Diagnostic codes that indicate undefined/unresolved issues
UNDEFINED_CODES = {
    "reportUndefinedVariable",
    "reportUnboundVariable", 
    "reportOptionalMemberAccess",
    "reportAttributeAccessIssue",
    "reportGeneralTypeIssues",
}

IMPORT_CODES = {
    "reportMissingImports",
    "reportMissingModuleSource",
    "reportMissingTypeStubs",
}


def categorize_diagnostic(message: str, code: Optional[str]) -> tuple[str, Optional[str]]:
    """
    Categorize a diagnostic message and extract symbol name if possible.
    
    Returns:
        (category, symbol_name)
    """
    # Check by diagnostic code first
    if code:
        if code in IMPORT_CODES:
            # Try to extract import name from message
            for pattern, _ in UNDEFINED_NAME_PATTERNS:
                match = re.search(pattern, message)
                if match:
                    return "unresolved_import", match.group(1)
            return "unresolved_import", None
        
        if code in UNDEFINED_CODES:
            for pattern, _ in UNDEFINED_NAME_PATTERNS:
                match = re.search(pattern, message)
                if match:
                    return "undefined_name", match.group(1)
            return "undefined_name", None
    
    # Fall back to message pattern matching
    for pattern, category in UNDEFINED_NAME_PATTERNS:
        match = re.search(pattern, message)
        if match:
            return category, match.group(1)
    
    # Check for type errors
    if any(x in message.lower() for x in ["type", "argument", "expected", "incompatible"]):
        return "type_error", None
    
    return "other", None


def severity_from_vscode(severity: str) -> str:
    """Convert VS Code severity to standard string."""
    mapping = {
        "error": "error",
        "warning": "warning",
        "information": "information",
        "info": "information",
        "hint": "hint",
    }
    return mapping.get(severity.lower(), "error")


# ============================================================================
# Python AST Analysis (for definitions extraction)
# ============================================================================

def extract_definitions_ast(content: str, file_path: str) -> tuple[list[dict], list[PythonDiagnostic]]:
    """
    Extract function/class definitions using Python AST.
    Also catches syntax errors.
    
    Returns:
        (definitions, syntax_errors)
    """
    definitions = []
    syntax_errors = []
    
    try:
        tree = ast.parse(content, filename=file_path)
    except SyntaxError as e:
        syntax_errors.append(PythonDiagnostic(
            file=file_path,
            line=e.lineno or 1,
            column=e.offset or 0,
            end_line=e.lineno or 1,
            end_column=(e.offset or 0) + 1,
            severity="error",
            message=str(e.msg),
            source="syntax",
            category="syntax",
        ))
        return definitions, syntax_errors
    
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            definitions.append({
                "name": node.name,
                "type": "function",
                "line": node.lineno,
                "column": node.col_offset,
            })
        elif isinstance(node, ast.AsyncFunctionDef):
            definitions.append({
                "name": node.name,
                "type": "async_function",
                "line": node.lineno,
                "column": node.col_offset,
            })
        elif isinstance(node, ast.ClassDef):
            definitions.append({
                "name": node.name,
                "type": "class",
                "line": node.lineno,
                "column": node.col_offset,
            })
    
    return definitions, syntax_errors


# ============================================================================
# VS Code IPC Validation (REQUIRED)
# ============================================================================

def validate_via_vscode_ipc(files: list[Path]) -> PythonValidationReport:
    """
    Validate files using VS Code IPC to get Pylance diagnostics.
    
    Raises:
        PythonValidationError: If VS Code IPC is unavailable
    """
    if not is_vscode_available():
        raise PythonValidationError(
            "VS Code IPC is not available. "
            "Ensure VS Code is running with the CK3 Lens extension active."
        )
    
    report = PythonValidationReport(source="vscode_ipc")
    
    try:
        with VSCodeIPCClient() as client:
            for file_path in files:
                abs_path = str(file_path.resolve())
                report.files_analyzed.append(abs_path)
                
                # Request validation for this file
                try:
                    result = client.validate_file(abs_path)
                except VSCodeIPCError:
                    # File might not be openable, try get_diagnostics directly
                    try:
                        result = client.get_diagnostics(abs_path)
                    except VSCodeIPCError as e:
                        report.validation_errors.append(f"IPC error for {abs_path}: {e}")
                        continue
                
                diagnostics = result.get("diagnostics", [])
                
                for diag in diagnostics:
                    # Only process Pylance diagnostics for Python semantic analysis
                    source = diag.get("source", "")
                    if source not in ("Pylance", "Python"):
                        continue
                    
                    severity = severity_from_vscode(diag.get("severity", "error"))
                    message = diag.get("message", "")
                    code = str(diag.get("code", "")) if diag.get("code") else None
                    
                    range_info = diag.get("range", {})
                    start = range_info.get("start", {})
                    end = range_info.get("end", {})
                    
                    # Categorize
                    category, symbol_name = categorize_diagnostic(message, code)
                    
                    diagnostic = PythonDiagnostic(
                        file=abs_path,
                        line=start.get("line", 0) + 1,  # VS Code uses 0-indexed
                        column=start.get("character", 0),
                        end_line=end.get("line", 0) + 1,
                        end_column=end.get("character", 0),
                        severity=severity,
                        message=message,
                        source="Pylance",
                        code=code,
                        category=category,
                        symbol_name=symbol_name,
                    )
                    
                    # Route to appropriate list
                    if category == "undefined_name":
                        report.undefined_names.append(diagnostic)
                    elif category == "unresolved_import":
                        report.unresolved_imports.append(diagnostic)
                    elif category == "syntax":
                        report.syntax_errors.append(diagnostic)
                    elif category == "type_error":
                        report.type_errors.append(diagnostic)
                    else:
                        report.other_errors.append(diagnostic)
                
                # Also extract definitions via AST
                try:
                    content = file_path.read_text(encoding="utf-8")
                    definitions, syntax_errors = extract_definitions_ast(content, abs_path)
                    report.definitions.extend([{**d, "file": abs_path} for d in definitions])
                    report.syntax_errors.extend(syntax_errors)
                except Exception as e:
                    report.validation_errors.append(f"AST parse error for {abs_path}: {e}")
    
    except VSCodeIPCError as e:
        raise PythonValidationError(f"VS Code IPC error: {e}")
    
    return report


# ============================================================================
# Main Validator Class
# ============================================================================

class PythonSemanticValidator:
    """
    Python semantic validator using Pylance via VS Code IPC.
    
    REQUIRES: VS Code with Pylance extension and CK3 Lens IPC server running.
    
    Usage:
        validator = PythonSemanticValidator()
        report = validator.validate_files([Path("script.py")])
        
        if report.has_undefined_symbols:
            print("Found undefined symbols!")
            for diag in report.undefined_names:
                print(f"  {diag.file}:{diag.line}: {diag.symbol_name}")
    """
    
    def validate_files(self, files: list[Path]) -> PythonValidationReport:
        """
        Validate Python files for semantic errors.
        
        Uses Pylance diagnostics via VS Code IPC.
        
        Raises:
            PythonValidationError: If VS Code IPC is unavailable
        """
        return validate_via_vscode_ipc(files)
    
    def validate_content(
        self, 
        content: str, 
        filename: str = "untitled.py"
    ) -> PythonValidationReport:
        """
        Validate Python content string (for pre-write validation).
        
        This checks syntax locally via AST. For full semantic analysis,
        the content would need to be written to a file and analyzed.
        
        NOTE: This only catches syntax errors since we can't open
        arbitrary content in VS Code for Pylance analysis.
        """
        report = PythonValidationReport(source="ast_syntax_only")
        report.files_analyzed.append(filename)
        
        definitions, syntax_errors = extract_definitions_ast(content, filename)
        report.definitions.extend([{**d, "file": filename} for d in definitions])
        report.syntax_errors.extend(syntax_errors)
        
        if syntax_errors:
            report.validation_errors.append(
                "Syntax errors found - semantic validation skipped. "
                "Write the file to disk for full Pylance analysis."
            )
        
        return report


# ============================================================================
# Convenience Functions
# ============================================================================

def validate_python_files(files: list[Path]) -> PythonValidationReport:
    """
    Validate Python files for semantic errors.
    
    Requires VS Code IPC to be available.
    
    Raises:
        PythonValidationError: If VS Code IPC is unavailable
    """
    validator = PythonSemanticValidator()
    return validator.validate_files(files)


def validate_python_content(content: str, filename: str = "untitled.py") -> PythonValidationReport:
    """
    Validate Python content for syntax errors.
    
    NOTE: Only catches syntax errors. For full semantic analysis,
    write the file and use validate_python_files().
    """
    validator = PythonSemanticValidator()
    return validator.validate_content(content, filename)


# ============================================================================
# CLI for Testing
# ============================================================================

if __name__ == "__main__":
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="Python Semantic Validator")
    parser.add_argument("files", nargs="*", type=Path, help="Python files to validate")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()
    
    if not args.files:
        print("Usage: python -m ck3lens.validation.python_validator file.py ...")
        sys.exit(1)
    
    try:
        report = validate_python_files(args.files)
    except PythonValidationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"Python Semantic Validation Report")
        print(f"  Source: {report.source}")
        print(f"  Files: {len(report.files_analyzed)}")
        print(f"  Undefined names: {len(report.undefined_names)}")
        print(f"  Unresolved imports: {len(report.unresolved_imports)}")
        print(f"  Syntax errors: {len(report.syntax_errors)}")
        print(f"  Type errors: {len(report.type_errors)}")
        
        if report.undefined_names:
            print("\nUndefined Names:")
            for d in report.undefined_names[:10]:
                print(f"  {d.file}:{d.line}: {d.symbol_name or d.message}")
        
        if report.unresolved_imports:
            print("\nUnresolved Imports:")
            for d in report.unresolved_imports[:10]:
                print(f"  {d.file}:{d.line}: {d.symbol_name or d.message}")
    
    sys.exit(1 if report.has_errors else 0)
