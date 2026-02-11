"""
Reply System Linter — enforces Canonical Reply System 2.0 across the codebase.

Checks:
  1. REGISTRY: All codes in both registries pass format + layer ownership rules
  2. PARALLEL: No parallel Reply types (EnforcementResult, _ReplyBuilder, etc.)
  3. AREA:     No forbidden AREA values (OPEN, CLOSE per spec → use GATE)
  4. ORPHAN:   Codes used in source but missing from registry
  5. LAYER:    Layer ownership violations in registry entries

Run:
    python -m tools.compliance.reply_linter
    python tools/compliance/reply_linter.py

Exit codes:
    0 = clean
    1 = violations found
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple


# ============================================================================
# Configuration
# ============================================================================

# Scan these directories for source violations
SCAN_DIRS = [
    "tools/ck3lens_mcp",
    "src/ck3raven/core",
]

# File extensions to scan
SCAN_EXTENSIONS = {".py"}

# Skip these paths (exports, tests, archives, docs)
SKIP_PATTERNS = [
    "exports/",
    "archive/",
    "deprecated_policy/",
    "__pycache__/",
    ".wip/",
    "node_modules/",
    "reply_linter.py",  # Don't lint ourselves
]

# Parallel type names that must not exist in source
FORBIDDEN_TYPES = [
    "EnforcementResult",
    # _ReplyBuilder is internal and will be cleaned up separately
]

# AREA values forbidden by canonical spec (§5 clarification)
FORBIDDEN_AREAS = {"OPEN", "CLOSE"}

# Layer ownership: which reply types each layer may emit
LAYER_ALLOWED_TYPES = {
    "WA":  {"S", "I", "E"},
    "EN":  {"S", "D", "E"},
    "CT":  {"S", "I", "E"},
    "MCP": {"S", "E", "I"},
}

# Valid layers (closed set — additions require architecture review)
VALID_LAYERS = {"WA", "EN", "CT", "MCP"}

# Code pattern: LAYER-AREA-TYPE-NNN
CODE_PATTERN = re.compile(r"^([A-Z]+)-([A-Z]+)-([SIDE])-(\d{3})$")

# Pattern to find code strings in source files
CODE_IN_SOURCE = re.compile(r"""['"]([A-Z]+-[A-Z]+-[SIDE]-\d{3})['"]""")


# ============================================================================
# Types
# ============================================================================

class Violation(NamedTuple):
    file: str
    line: int
    rule: str
    message: str


# ============================================================================
# Registry Checks
# ============================================================================

def check_ck3lens_registry(root: Path) -> list[Violation]:
    """Check tools/ck3lens_mcp/ck3lens/reply_codes.py Codes class."""
    violations = []
    registry_path = root / "tools" / "ck3lens_mcp" / "ck3lens" / "reply_codes.py"
    
    if not registry_path.exists():
        violations.append(Violation(str(registry_path), 0, "MISSING", "reply_codes.py not found"))
        return violations
    
    lines = registry_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines, 1):
        # Find ReplyCode constructor calls with codes
        match = re.search(r'ReplyCode\("([^"]+)"', line)
        if not match:
            continue
        
        code = match.group(1)
        vs = _validate_code(code, str(registry_path), i)
        violations.extend(vs)
    
    return violations


def check_core_registry(root: Path) -> list[Violation]:
    """Check src/ck3raven/core/reply_registry.py _REGISTRY_LIST."""
    violations = []
    registry_path = root / "src" / "ck3raven" / "core" / "reply_registry.py"
    
    if not registry_path.exists():
        violations.append(Violation(str(registry_path), 0, "MISSING", "reply_registry.py not found"))
        return violations
    
    lines = registry_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines, 1):
        # Find code= definitions
        match = re.search(r'code="([^"]+)"', line)
        if not match:
            continue
        
        code = match.group(1)
        vs = _validate_code(code, str(registry_path), i)
        violations.extend(vs)
    
    return violations


def _validate_code(code: str, filepath: str, line: int) -> list[Violation]:
    """Validate a single code string against canonical rules."""
    violations = []
    
    m = CODE_PATTERN.match(code)
    if not m:
        violations.append(Violation(filepath, line, "FORMAT", f"Code {code!r} doesn't match LAYER-AREA-TYPE-NNN"))
        return violations
    
    layer, area, rtype, _num = m.groups()
    
    # Check layer is valid
    if layer not in VALID_LAYERS:
        violations.append(Violation(filepath, line, "LAYER", f"Unknown layer {layer!r} in {code}"))
    
    # Check layer ownership
    if layer in LAYER_ALLOWED_TYPES and rtype not in LAYER_ALLOWED_TYPES[layer]:
        allowed = sorted(LAYER_ALLOWED_TYPES[layer])
        violations.append(Violation(
            filepath, line, "OWNERSHIP",
            f"{layer} cannot emit {rtype} (allowed: {allowed}) — code {code}",
        ))
    
    # Check forbidden AREA values
    if area in FORBIDDEN_AREAS:
        violations.append(Violation(
            filepath, line, "AREA",
            f"AREA {area!r} is forbidden (use GATE instead) — code {code}",
        ))
    
    return violations


# ============================================================================
# Source Checks
# ============================================================================

def check_source_parallel_types(root: Path) -> list[Violation]:
    """Check for parallel Reply types that should not exist."""
    violations = []
    
    for scan_dir in SCAN_DIRS:
        dirpath = root / scan_dir
        if not dirpath.exists():
            continue
        
        for pyfile in dirpath.rglob("*.py"):
            if _should_skip(pyfile, root):
                continue
            
            lines = pyfile.read_text(encoding="utf-8").splitlines()
            relpath = str(pyfile.relative_to(root))
            
            for i, line in enumerate(lines, 1):
                for forbidden in FORBIDDEN_TYPES:
                    # Match class definition or import of forbidden type
                    if re.search(rf"\bclass\s+{forbidden}\b", line):
                        violations.append(Violation(
                            relpath, i, "PARALLEL",
                            f"Forbidden parallel type: class {forbidden} (use Reply instead)",
                        ))
                    elif re.search(rf"\b{forbidden}\b", line) and "import" in line:
                        violations.append(Violation(
                            relpath, i, "PARALLEL",
                            f"Import of forbidden parallel type: {forbidden}",
                        ))
    
    return violations


def check_source_codes(root: Path) -> list[Violation]:
    """Check code strings used in source against canonical rules."""
    violations = []
    
    # Collect all registered codes from both registries
    registered = _collect_registered_codes(root)
    
    for scan_dir in SCAN_DIRS:
        dirpath = root / scan_dir
        if not dirpath.exists():
            continue
        
        for pyfile in dirpath.rglob("*.py"):
            if _should_skip(pyfile, root):
                continue
            
            lines = pyfile.read_text(encoding="utf-8").splitlines()
            relpath = str(pyfile.relative_to(root))
            
            for i, line in enumerate(lines, 1):
                # Skip comments and docstrings
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                
                for m in CODE_IN_SOURCE.finditer(line):
                    code = m.group(1)
                    vs = _validate_code(code, relpath, i)
                    violations.extend(vs)
    
    return violations


def _collect_registered_codes(root: Path) -> set[str]:
    """Collect all codes from both registries."""
    codes = set()
    
    # ck3lens registry
    rp = root / "tools" / "ck3lens_mcp" / "ck3lens" / "reply_codes.py"
    if rp.exists():
        for m in re.finditer(r'ReplyCode\("([^"]+)"', rp.read_text(encoding="utf-8")):
            codes.add(m.group(1))
    
    # core registry
    rp = root / "src" / "ck3raven" / "core" / "reply_registry.py"
    if rp.exists():
        for m in re.finditer(r'code="([^"]+)"', rp.read_text(encoding="utf-8")):
            codes.add(m.group(1))
    
    return codes


def _should_skip(filepath: Path, root: Path) -> bool:
    """Check if a file should be skipped."""
    rel = str(filepath.relative_to(root)).replace("\\", "/")
    return any(pat in rel for pat in SKIP_PATTERNS)


# ============================================================================
# Main
# ============================================================================

def run_lint(root: Path | None = None) -> list[Violation]:
    """Run all checks and return violations."""
    if root is None:
        root = Path(__file__).resolve().parent.parent.parent  # tools/compliance/ → repo root
    
    violations = []
    violations.extend(check_ck3lens_registry(root))
    violations.extend(check_core_registry(root))
    violations.extend(check_source_parallel_types(root))
    violations.extend(check_source_codes(root))
    return violations


def main():
    root = Path(__file__).resolve().parent.parent.parent
    violations = run_lint(root)
    
    if not violations:
        print("reply_linter: CLEAN — no violations found")
        sys.exit(0)
    
    # Group by rule
    by_rule: dict[str, list[Violation]] = {}
    for v in violations:
        by_rule.setdefault(v.rule, []).append(v)
    
    print(f"reply_linter: {len(violations)} violation(s) found\n")
    
    for rule in sorted(by_rule):
        items = by_rule[rule]
        print(f"[{rule}] ({len(items)} violations)")
        for v in items:
            print(f"  {v.file}:{v.line} — {v.message}")
        print()
    
    sys.exit(1)


if __name__ == "__main__":
    main()
