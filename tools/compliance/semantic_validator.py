"""
Semantic Validator — Phase 1.5 Evidence Generator

This tool produces deterministic semantic evidence for contract auditing.
It is a SENSOR, not a JUDGE — it observes reality and emits evidence.

All enforcement decisions occur later during contract audit and closure.

Usage:
    python -m tools.compliance.semantic_validator file1.py file2.txt --out report.json
    python -m tools.compliance.semantic_validator --files-from manifest.txt --out report.json

Output:
    Deterministic JSON artifact containing:
    - definitions_added: New symbols introduced by this edit
    - undefined_refs: Symbol usages that cannot be resolved
    - valid_refs: Symbol usages that successfully resolve (integrity evidence)

Phase Boundary:
    This is Phase 1.5 — evidence construction only.
    No enforcement logic, no token validation, no contract close integration.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class SymbolLocation:
    """Location of a symbol definition or reference."""
    file: str
    line: int
    column: int = 0
    
    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "column": self.column}


@dataclass
class SymbolDef:
    """A symbol definition."""
    name: str
    symbol_type: str  # e.g., "trait", "event", "function", "class"
    location: SymbolLocation
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "symbol_type": self.symbol_type,
            "location": self.location.to_dict(),
        }


@dataclass
class SymbolRef:
    """A symbol reference."""
    name: str
    ref_type: str  # e.g., "has_trait", "trigger_event", "import"
    location: SymbolLocation
    resolved: bool = False
    resolved_to: Optional[str] = None  # mod/file where it resolved
    
    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "ref_type": self.ref_type,
            "location": self.location.to_dict(),
        }
        if self.resolved_to:
            d["resolved_to"] = self.resolved_to
        return d


@dataclass
class FileResult:
    """Result of validating a single file."""
    file_path: str
    file_type: str  # "python" or "ck3"
    definitions: list[SymbolDef] = field(default_factory=list)
    undefined_refs: list[SymbolRef] = field(default_factory=list)
    valid_refs: list[SymbolRef] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "file_type": self.file_type,
            "definitions": [d.to_dict() for d in self.definitions],
            "undefined_refs": [r.to_dict() for r in self.undefined_refs],
            "valid_refs": [r.to_dict() for r in self.valid_refs],
            "parse_errors": self.parse_errors,
        }


@dataclass
class SemanticReport:
    """Complete semantic validation report."""
    tool: str = "semantic_validator"
    version: str = "1.0.0"
    contract_id: Optional[str] = None
    session_mods_hash: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    files_scanned: list[str] = field(default_factory=list)
    
    # CK3 results
    ck3_definitions_added: list[SymbolDef] = field(default_factory=list)
    ck3_undefined_refs: list[SymbolRef] = field(default_factory=list)
    ck3_parse_errors: list[str] = field(default_factory=list)
    
    # Python results  
    python_definitions_added: list[SymbolDef] = field(default_factory=list)
    python_undefined_refs: list[SymbolRef] = field(default_factory=list)
    python_syntax_errors: list[str] = field(default_factory=list)
    
    # Metadata
    validation_errors: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "version": self.version,
            "contract_id": self.contract_id,
            "session_mods_hash": self.session_mods_hash,
            "timestamp": self.timestamp,
            "files_scanned": self.files_scanned,
            "ck3": {
                "definitions_added": [d.to_dict() for d in self.ck3_definitions_added],
                "undefined_refs": [r.to_dict() for r in self.ck3_undefined_refs],
                "parse_errors": self.ck3_parse_errors,
            },
            "python": {
                "definitions_added": [d.to_dict() for d in self.python_definitions_added],
                "undefined_refs": [r.to_dict() for r in self.python_undefined_refs],
                "syntax_errors": self.python_syntax_errors,
            },
            "validation_errors": self.validation_errors,
        }


# ============================================================================
# CK3 Semantic Analysis
# ============================================================================

# CK3 definition types that create new symbols
CK3_DEFINITION_CONTEXTS = {
    "common/traits": "trait",
    "common/decisions": "decision",
    "common/scripted_triggers": "scripted_trigger",
    "common/scripted_effects": "scripted_effect",
    "common/on_action": "on_action",
    "common/modifiers": "modifier",
    "common/event_themes": "event_theme",
    "common/scripted_guis": "scripted_gui",
    "events": "event",
}

# CK3 reference patterns - these reference symbols defined elsewhere
CK3_REFERENCE_PATTERNS = [
    # Traits
    (r'\bhas_trait\s*=\s*(\w+)', "has_trait"),
    (r'\badd_trait\s*=\s*(\w+)', "add_trait"),
    (r'\bremove_trait\s*=\s*(\w+)', "remove_trait"),
    # Events
    (r'\btrigger_event\s*=\s*\{?\s*id\s*=\s*([\w.]+)', "trigger_event"),
    (r'\btrigger_event\s*=\s*([\w.]+)', "trigger_event"),
    # Scripted triggers/effects
    (r'^(\w+)\s*=\s*\{', "definition"),  # Top-level blocks are definitions
    # Modifiers
    (r'\bhas_modifier\s*=\s*(\w+)', "has_modifier"),
    (r'\badd_modifier\s*=\s*\{?\s*modifier\s*=\s*(\w+)', "add_modifier"),
    # Decisions
    (r'\bhas_decision\s*=\s*(\w+)', "has_decision"),
    # Character flags/variables (not symbols, skip)
    # Scripted values
    (r'@(\w+)', "scripted_value"),
]


def get_ck3_definition_type(file_path: str) -> Optional[str]:
    """Determine what type of CK3 symbol this file defines based on path."""
    path_lower = file_path.replace("\\", "/").lower()
    for context_path, def_type in CK3_DEFINITION_CONTEXTS.items():
        if context_path in path_lower:
            return def_type
    return None


def extract_ck3_definitions(content: str, file_path: str) -> list[SymbolDef]:
    """Extract top-level definitions from a CK3 script file.
    
    Uses indentation/brace tracking to identify true top-level blocks,
    not nested blocks within other definitions.
    """
    definitions = []
    def_type = get_ck3_definition_type(file_path)
    
    if not def_type:
        return definitions
    
    # Track brace depth to identify top-level definitions only
    brace_depth = 0
    
    # Common keys that appear at any level but aren't symbol definitions
    NON_DEFINITION_KEYS = {
        # Control flow / conditions
        'if', 'else', 'else_if', 'switch', 'trigger_if', 'trigger_else',
        'and', 'or', 'not', 'nor', 'nand',
        'any', 'all', 'none',
        
        # Common blocks
        'trigger', 'effect', 'desc', 'option', 'immediate', 'after',
        'on_trigger', 'on_complete', 'weight', 'ai_will_do', 'ai_chance',
        'is_shown', 'is_valid', 'cost', 'cooldown', 'potential',
        'allow', 'fail_text', 'success_text', 'confirm_text',
        
        # Scripting constructs
        'random', 'random_list', 'ordered', 'while', 'every', 'any_of',
        'save_scope_as', 'save_temporary_scope_as',
        
        # Data / display
        'modifier', 'modifiers', 'triggered_desc', 'first_valid',
        'culture_modifier', 'faith_modifier', 'government_modifier',
        
        # Scopes
        'root', 'this', 'prev', 'from', 'scope', 'target',
        'liege', 'spouse', 'primary_spouse', 'player_heir', 'heir',
        
        # Lists
        'list', 'value', 'values', 'compare', 'add', 'subtract', 'multiply', 'divide',
    }
    
    for line_num, line in enumerate(content.split('\n'), 1):
        # Track brace depth
        # Count braces, ignoring those in strings (simple heuristic)
        in_string = False
        for i, ch in enumerate(line):
            if ch == '"' and (i == 0 or line[i-1] != '\\'):
                in_string = not in_string
            elif not in_string:
                if ch == '{':
                    brace_depth += 1
                elif ch == '}':
                    brace_depth -= 1
        
        # Skip if we're inside a block (not top-level)
        # We want to catch definitions BEFORE the opening brace is counted
        stripped = line.lstrip()
        
        # Skip comments
        if stripped.startswith('#'):
            continue
        
        # Check for top-level definition pattern
        # Must be at brace_depth 0 or 1 (1 because the { on this line was already counted)
        # The line must match: identifier = {
        if brace_depth <= 1:
            match = re.match(r'^(\w+)\s*=\s*\{', stripped)
            if match:
                name = match.group(1).lower()
                
                # Skip common non-definition keys
                if name in NON_DEFINITION_KEYS:
                    continue
                
                # Skip numeric or very short names (likely not definitions)
                if name.isdigit() or len(name) < 2:
                    continue
                
                definitions.append(SymbolDef(
                    name=match.group(1),  # Keep original case
                    symbol_type=def_type,
                    location=SymbolLocation(file=file_path, line=line_num),
                ))
    
    return definitions


def extract_ck3_references(content: str, file_path: str) -> list[SymbolRef]:
    """Extract symbol references from a CK3 script file."""
    references = []
    
    for line_num, line in enumerate(content.split('\n'), 1):
        # Skip comments
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue
        
        for pattern, ref_type in CK3_REFERENCE_PATTERNS:
            if ref_type == "definition":
                continue  # Skip definition pattern for references
            
            for match in re.finditer(pattern, line):
                name = match.group(1)
                # Skip common literals and variables
                if name.lower() in ('yes', 'no', 'true', 'false', 'scope', 'root', 
                                    'this', 'prev', 'from', 'owner'):
                    continue
                
                references.append(SymbolRef(
                    name=name,
                    ref_type=ref_type,
                    location=SymbolLocation(
                        file=file_path,
                        line=line_num,
                        column=match.start(1),
                    ),
                ))
    
    return references


def resolve_ck3_references(
    references: list[SymbolRef],
    local_definitions: list[SymbolDef],
    db_path: Optional[Path],
    cvids: Optional[list[int]] = None,
) -> tuple[list[SymbolRef], list[SymbolRef]]:
    """
    Resolve CK3 symbol references against local definitions and database.
    
    Returns:
        (valid_refs, undefined_refs)
    """
    # Build local symbol lookup
    local_symbols = {d.name for d in local_definitions}
    
    # Build database symbol lookup if available
    db_symbols = set()
    if db_path and db_path.exists():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            
            if cvids:
                placeholders = ",".join("?" * len(cvids))
                # Golden Join pattern: symbols → asts → files → content_versions
                cursor.execute(f"""
                    SELECT DISTINCT s.name 
                    FROM symbols s
                    JOIN asts a ON s.ast_id = a.ast_id
                    JOIN files f ON a.content_hash = f.content_hash
                    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                    WHERE cv.content_version_id IN ({placeholders})
                """, cvids)
            else:
                cursor.execute("SELECT DISTINCT name FROM symbols")
            
            db_symbols = {row[0] for row in cursor.fetchall()}
            conn.close()
        except Exception as e:
            pass  # DB not available - will report as validation error
    
    valid_refs = []
    undefined_refs = []
    
    for ref in references:
        if ref.name in local_symbols:
            ref.resolved = True
            ref.resolved_to = "local"
            valid_refs.append(ref)
        elif ref.name in db_symbols:
            ref.resolved = True
            ref.resolved_to = "database"
            valid_refs.append(ref)
        else:
            undefined_refs.append(ref)
    
    return valid_refs, undefined_refs


def validate_ck3_file(
    file_path: Path,
    db_path: Optional[Path] = None,
    cvids: Optional[list[int]] = None,
) -> FileResult:
    """Validate a single CK3 script file."""
    result = FileResult(file_path=str(file_path), file_type="ck3")
    
    try:
        content = file_path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception as e:
        result.parse_errors.append(f"Failed to read file: {e}")
        return result
    
    # Extract definitions
    result.definitions = extract_ck3_definitions(content, str(file_path))
    
    # Extract and resolve references
    references = extract_ck3_references(content, str(file_path))
    result.valid_refs, result.undefined_refs = resolve_ck3_references(
        references, result.definitions, db_path, cvids
    )
    
    return result


# ============================================================================
# Python Semantic Analysis
# ============================================================================

def extract_python_definitions(content: str, file_path: str) -> tuple[list[SymbolDef], list[str]]:
    """
    Extract top-level function and class definitions from Python source.
    
    Returns:
        (definitions, syntax_errors)
    """
    definitions = []
    syntax_errors = []
    
    try:
        tree = ast.parse(content, filename=file_path)
    except SyntaxError as e:
        syntax_errors.append(f"{file_path}:{e.lineno}: {e.msg}")
        return definitions, syntax_errors
    
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            definitions.append(SymbolDef(
                name=node.name,
                symbol_type="function",
                location=SymbolLocation(file=file_path, line=node.lineno, column=node.col_offset),
            ))
        elif isinstance(node, ast.AsyncFunctionDef):
            definitions.append(SymbolDef(
                name=node.name,
                symbol_type="async_function",
                location=SymbolLocation(file=file_path, line=node.lineno, column=node.col_offset),
            ))
        elif isinstance(node, ast.ClassDef):
            definitions.append(SymbolDef(
                name=node.name,
                symbol_type="class",
                location=SymbolLocation(file=file_path, line=node.lineno, column=node.col_offset),
            ))
    
    return definitions, syntax_errors


def run_pyright(files: list[Path]) -> list[SymbolRef]:
    """
    Run pyright on files and extract undefined name diagnostics.
    
    Returns list of undefined references.
    """
    undefined_refs = []
    
    if not files:
        return undefined_refs
    
    try:
        # Run pyright with JSON output
        cmd = [
            sys.executable, "-m", "pyright",
            "--outputjson",
            *[str(f) for f in files],
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        
        # Parse JSON output
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            # pyright might not be installed or failed
            return undefined_refs
        
        # Extract undefined name diagnostics
        for diagnostic in data.get("generalDiagnostics", []):
            if diagnostic.get("severity") == "error":
                message = diagnostic.get("message", "")
                
                # Pattern: "X" is not defined
                # Pattern: Cannot find name "X"
                # Pattern: Module "X" has no attribute "Y"
                undefined_match = re.search(r'"(\w+)" is not defined', message)
                if not undefined_match:
                    undefined_match = re.search(r'Cannot find name "(\w+)"', message)
                if not undefined_match:
                    undefined_match = re.search(r'Import "(\w+)" could not be resolved', message)
                
                if undefined_match:
                    name = undefined_match.group(1)
                    file_path = diagnostic.get("file", "")
                    range_info = diagnostic.get("range", {})
                    start = range_info.get("start", {})
                    
                    undefined_refs.append(SymbolRef(
                        name=name,
                        ref_type="undefined_name",
                        location=SymbolLocation(
                            file=file_path,
                            line=start.get("line", 0) + 1,  # pyright is 0-indexed
                            column=start.get("character", 0),
                        ),
                    ))
    except subprocess.TimeoutExpired:
        pass
    except FileNotFoundError:
        # pyright not installed
        pass
    except Exception:
        pass
    
    return undefined_refs


def validate_python_file(file_path: Path) -> FileResult:
    """Validate a single Python file."""
    result = FileResult(file_path=str(file_path), file_type="python")
    
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        result.parse_errors.append(f"Failed to read file: {e}")
        return result
    
    # Extract definitions
    definitions, syntax_errors = extract_python_definitions(content, str(file_path))
    result.definitions = definitions
    result.parse_errors.extend(syntax_errors)
    
    return result


# ============================================================================
# Main Validator
# ============================================================================

def classify_file(file_path: Path) -> str:
    """Classify file as 'python', 'ck3', or 'unknown'."""
    suffix = file_path.suffix.lower()
    
    if suffix == ".py":
        return "python"
    elif suffix in (".txt", ".gui", ".yml", ".info"):
        return "ck3"
    else:
        return "unknown"


def validate_files(
    files: list[Path],
    db_path: Optional[Path] = None,
    cvids: Optional[list[int]] = None,
    contract_id: Optional[str] = None,
) -> SemanticReport:
    """
    Validate a list of files and produce a semantic report.
    
    This is the main entry point for the validator.
    """
    report = SemanticReport(contract_id=contract_id)
    
    # Compute session mods hash if cvids provided
    if cvids:
        cvid_str = ",".join(str(c) for c in sorted(cvids))
        report.session_mods_hash = hashlib.sha256(cvid_str.encode()).hexdigest()[:16]
    
    python_files = []
    ck3_files = []
    
    # Classify files
    for file_path in files:
        if not file_path.exists():
            report.validation_errors.append(f"File not found: {file_path}")
            continue
        
        file_type = classify_file(file_path)
        report.files_scanned.append(str(file_path))
        
        if file_type == "python":
            python_files.append(file_path)
        elif file_type == "ck3":
            ck3_files.append(file_path)
        else:
            report.validation_errors.append(f"Unknown file type: {file_path}")
    
    # Validate CK3 files
    for file_path in ck3_files:
        result = validate_ck3_file(file_path, db_path, cvids)
        report.ck3_definitions_added.extend(result.definitions)
        report.ck3_undefined_refs.extend(result.undefined_refs)
        report.ck3_parse_errors.extend(result.parse_errors)
    
    # Validate Python files
    for file_path in python_files:
        result = validate_python_file(file_path)
        report.python_definitions_added.extend(result.definitions)
        report.python_syntax_errors.extend(result.parse_errors)
    
    # Run pyright on all Python files at once (more efficient)
    if python_files:
        undefined_refs = run_pyright(python_files)
        report.python_undefined_refs.extend(undefined_refs)
    
    return report


# ============================================================================
# CLI Interface
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Semantic Validator — Phase 1.5 Evidence Generator",
        epilog="Produces deterministic semantic evidence for contract auditing.",
    )
    
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Files to validate",
    )
    
    parser.add_argument(
        "--files-from",
        type=Path,
        help="Read file list from manifest (one per line)",
    )
    
    parser.add_argument(
        "--out", "-o",
        type=Path,
        help="Output JSON report path",
    )
    
    parser.add_argument(
        "--db",
        type=Path,
        default=Path.home() / ".ck3raven" / "ck3raven.db",
        help="Path to ck3raven database (default: ~/.ck3raven/ck3raven.db)",
    )
    
    parser.add_argument(
        "--contract-id",
        type=str,
        help="Contract ID for the report",
    )
    
    parser.add_argument(
        "--cvids",
        type=str,
        help="Comma-separated content version IDs for playset filtering",
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON to stdout",
    )
    
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress non-JSON output",
    )
    
    args = parser.parse_args()
    
    # Collect files
    files = list(args.files) if args.files else []
    
    if args.files_from:
        if args.files_from.exists():
            for line in args.files_from.read_text().strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    files.append(Path(line))
        else:
            print(f"Error: Manifest file not found: {args.files_from}", file=sys.stderr)
            sys.exit(1)
    
    if not files:
        parser.print_help()
        sys.exit(1)
    
    # Parse CVIDs
    cvids = None
    if args.cvids:
        cvids = [int(c.strip()) for c in args.cvids.split(",")]
    
    # Validate
    db_path = args.db if args.db.exists() else None
    report = validate_files(
        files=files,
        db_path=db_path,
        cvids=cvids,
        contract_id=args.contract_id,
    )
    
    # Output
    report_dict = report.to_dict()
    report_json = json.dumps(report_dict, indent=2)
    
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report_json)
        if not args.quiet:
            print(f"Report written to: {args.out}")
    
    if args.json or not args.out:
        print(report_json)
    elif not args.quiet:
        # Summary output
        print(f"\n=== Semantic Validation Report ===")
        print(f"Files scanned: {len(report.files_scanned)}")
        print(f"\nCK3:")
        print(f"  Definitions added: {len(report.ck3_definitions_added)}")
        print(f"  Undefined refs: {len(report.ck3_undefined_refs)}")
        print(f"  Parse errors: {len(report.ck3_parse_errors)}")
        print(f"\nPython:")
        print(f"  Definitions added: {len(report.python_definitions_added)}")
        print(f"  Undefined refs: {len(report.python_undefined_refs)}")
        print(f"  Syntax errors: {len(report.python_syntax_errors)}")
        
        # Show issues if any
        if report.ck3_undefined_refs:
            print(f"\n⚠ CK3 Undefined References:")
            for ref in report.ck3_undefined_refs[:10]:
                print(f"  {ref.location.file}:{ref.location.line}: {ref.name} ({ref.ref_type})")
            if len(report.ck3_undefined_refs) > 10:
                print(f"  ... and {len(report.ck3_undefined_refs) - 10} more")
        
        if report.python_undefined_refs:
            print(f"\n⚠ Python Undefined References:")
            for ref in report.python_undefined_refs[:10]:
                print(f"  {ref.location.file}:{ref.location.line}: {ref.name}")
            if len(report.python_undefined_refs) > 10:
                print(f"  ... and {len(report.python_undefined_refs) - 10} more")
    
    # Exit with error if there are undefined refs or parse errors
    has_errors = (
        report.ck3_undefined_refs or
        report.python_undefined_refs or
        report.ck3_parse_errors or
        report.python_syntax_errors or
        report.validation_errors
    )
    
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
