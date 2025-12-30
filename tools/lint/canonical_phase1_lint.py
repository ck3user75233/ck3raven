#!/usr/bin/env python3
"""
Phase 1 Canonical Architecture Linter

Goal: enforce high-signal architectural invariants early:
- No banned "oracle" terms or parallel authority lists (canonical banned terms list)
- No path normalization outside canonical modules
- No duplicate policy engines / gates / approvals modules
- No enforcement calls outside canonical boundary/enforcement modules (heuristic)

This is intentionally phase-1: token-based + text pattern checks.

Usage:
    python tools/lint/canonical_phase1_lint.py --root .
    python tools/lint/canonical_phase1_lint.py --root . --json
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
import tokenize
from typing import Iterable, Iterator, List, Optional, Tuple


# -----------------------------
# Rule IDs (Phase 1)
# -----------------------------
RULE_BANNED_TERMS = "P1-A1"
RULE_BANNED_FILENAMES = "P1-A2"
RULE_FORBIDDEN_PATH_APIS = "P1-A3"
RULE_ENFORCEMENT_CALL_SITES = "P1-A4"

# -----------------------------
# Canonical banned terms list (direct mapping from CANONICAL_ARCHITECTURE.md)
# Source: docs/CANONICAL_ARCHITECTURE.md §6 Banned Terms
# -----------------------------
BANNED_PERMISSION_ORACLES = {
    "can_write",
    "can_edit",
    "can_delete",
    "is_writable",
    "is_editable",
    "is_allowed",
    "is_path_allowed",
    "is_path_writable",
    "writable_mod",
    "editable_mod",
    "mod_write",
    "mod_read",
    "mod_delete",
}

BANNED_PARALLEL_AUTHORITY = {
    "editable_mods",
    "writable_mods",
    # "local_mods" - NOTE: This is a valid concept in Session, only banned as a *derived/filtered* list
    # We'll flag it but with lower severity or in a separate check
    "live_mods",
    "mod_whitelist",
    "whitelist",
    "blacklist",
    "mod_roots",
}

BANNED_TERMS = BANNED_PERMISSION_ORACLES | BANNED_PARALLEL_AUTHORITY

# Terms that are warnings (used legitimately in some contexts but should be reviewed)
WARN_TERMS = {
    "local_mods",  # Valid in Session.local_mods_folder context, banned as derived list
}

# -----------------------------
# Forbidden filename patterns (Phase 1)
# These indicate duplicate policy engines or gate modules
# -----------------------------
FORBIDDEN_FILENAME_GLOBS = [
    "*gates*.py",
    "*approval*.py",
    "file_policy.py",     # specifically called out historically
    "*policy_engine*.py",
    "hard_gates.py",      # known deprecated module
]

# Allowed exceptions (archived files are OK)
FILENAME_ALLOWED_PATHS = [
    "archive/",
    "deprecated/",
    "test_",
    "_test.py",
]

# -----------------------------
# Forbidden path-derivation APIs outside canonical modules
# These indicate path normalization leaking out of WorldAdapter
# -----------------------------

# ALWAYS forbidden - no exceptions by variable name
FORBIDDEN_PATH_PATTERNS_ALWAYS = [
    ".relative_to(",       # Any .relative_to() call - use WorldAdapter
    "os.path.relpath(",    # os.path.relpath - should use WorldAdapter
    "posixpath.relpath(",
    "ntpath.relpath(",
]

# Allowed base names for .resolve() calls
# These are WorldAdapter/LensWorld instances where resolve() is the correct API
ALLOWED_RESOLVE_BASE_NAMES = {
    "world",
    "adapter",
    "world_adapter",
    "lens_world",
    "lensworld",
}

# Regex to match attr.resolve( calls and capture the base name
# Matches: world.resolve(, adapter.resolve(, etc.
RE_ATTR_CALL = re.compile(r"(?P<base>[A-Za-z_][A-Za-z0-9_]*)\s*\.\s*resolve\s*\(")

# Regex to match Path(...).resolve( pattern - always forbidden
# Matches: Path(p).resolve(, Path("foo").resolve(, Path(some_var).resolve(
RE_PATH_RESOLVE = re.compile(r"Path\s*\([^)]*\)\s*\.\s*resolve\s*\(")

# Files (or directories) allowed to contain path derivation logic.
# These are the canonical path normalization modules.
ALLOWED_PATH_LOGIC_SUBSTRINGS = [
    "tools/ck3lens_mcp/ck3lens/world_adapter.py",
    "tools/ck3lens_mcp/ck3lens/paths/",
    # Policy layer modules need path resolution for enforcement
    "tools/ck3lens_mcp/ck3lens/policy/",
    # World router delegates to WorldAdapter
    "tools/ck3lens_mcp/ck3lens/world_router.py",
    # Workspace needs path resolution for session setup
    "tools/ck3lens_mcp/ck3lens/workspace.py",
    # Local mods needs path resolution for mod discovery
    "tools/ck3lens_mcp/ck3lens/local_mods.py",
    # Playset scope needs path resolution
    "tools/ck3lens_mcp/ck3lens/playset_scope.py",
    # Core ck3raven modules (not MCP tools, infrastructure)
    "src/ck3raven/",
    # Builder/daemon infrastructure
    "builder/",
    # Scripts are tools, not MCP enforcement boundary
    "scripts/",
    # Tests are allowed to use path APIs
    "tests/",
    "test_",
    # Linter itself needs to use paths
    "tools/lint/",
]

# -----------------------------
# Enforcement call-site heuristic
# These functions should ONLY be called from boundary/dispatcher modules
# -----------------------------
ENFORCEMENT_CALL_TOKENS = [
    "enforce_policy(",
    "enforce_and_log(",
]

# Only these modules should call enforcement functions.
# This is the canonical enforcement boundary.
ALLOWED_ENFORCEMENT_CALLERS_SUBSTRINGS = [
    # The enforcement module itself
    "tools/ck3lens_mcp/ck3lens/policy/enforcement.py",
    # The unified tools boundary dispatcher
    "tools/ck3lens_mcp/ck3lens/unified_tools.py",
    # Server.py is the MCP boundary
    "tools/ck3lens_mcp/server.py",
    # Script sandbox is an enforcement boundary for sandboxed execution
    "tools/ck3lens_mcp/ck3lens/tools/script_sandbox.py",
    # Tests
    "tests/",
    "test_",
    # Linter documents enforcement patterns (as strings)
    "tools/lint/",
]

# -----------------------------
# Repo walk exclusions
# -----------------------------
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
    "archive",  # Archived/deprecated code is excluded
}

EXCLUDED_FILE_GLOBS = [
    "*.pyc",
    "*.pyo",
]


@dataclass(frozen=True)
class LintError:
    rule_id: str
    path: str
    line: int
    col: int
    message: str
    severity: str = "ERROR"  # ERROR, WARN, INFO


def _is_excluded_path(p: Path) -> bool:
    """Check if path should be excluded from linting."""
    parts = set(p.parts)
    if parts & EXCLUDED_DIRS:
        return True
    for g in EXCLUDED_FILE_GLOBS:
        if fnmatch.fnmatch(p.name, g):
            return True
    return False


def iter_python_files(root: Path) -> Iterator[Path]:
    """Iterate over all Python files in the repo."""
    for p in root.rglob("*.py"):
        if _is_excluded_path(p):
            continue
        yield p


def _relpath_str(root: Path, p: Path) -> str:
    """Get relative path as posix string."""
    try:
        return p.relative_to(root).as_posix()
    except Exception:
        return p.as_posix()


def _allowed_by_substring(rel: str, allowed_substrings: List[str]) -> bool:
    """Check if relative path is allowed by any substring match."""
    rel_norm = rel.replace("\\", "/")
    return any(s in rel_norm for s in allowed_substrings)


def check_forbidden_filenames(root: Path, files: Iterable[Path]) -> List[LintError]:
    """Check for forbidden filename patterns (duplicate policy engines)."""
    errs: List[LintError] = []
    for p in files:
        rel = _relpath_str(root, p)
        
        # Skip if in allowed exception paths
        if _allowed_by_substring(rel, FILENAME_ALLOWED_PATHS):
            continue
        
        for g in FORBIDDEN_FILENAME_GLOBS:
            if fnmatch.fnmatch(p.name, g):
                errs.append(
                    LintError(
                        rule_id=RULE_BANNED_FILENAMES,
                        path=rel,
                        line=1,
                        col=0,
                        message=f"Forbidden filename pattern '{g}' matched by '{p.name}'. "
                                f"Canonical architecture forbids duplicate gates/approval/policy-engine modules.",
                    )
                )
                break
    return errs


def _tokenize_names(p: Path) -> Iterator[Tuple[str, int, int]]:
    """
    Yield (NAME token string, line, col) for a Python file.
    Ignores strings/comments automatically via tokenize.
    """
    try:
        with p.open("rb") as f:
            for tok in tokenize.tokenize(f.readline):
                if tok.type == tokenize.NAME:
                    yield tok.string, tok.start[0], tok.start[1]
    except (tokenize.TokenizeError, SyntaxError, UnicodeDecodeError):
        # Skip files that can't be tokenized
        pass


def check_banned_terms(root: Path, files: Iterable[Path]) -> List[LintError]:
    """Check for banned permission oracle and parallel authority terms."""
    errs: List[LintError] = []
    for p in files:
        rel = _relpath_str(root, p)
        
        # Skip lint files themselves (they document the banned terms)
        if "lint" in rel.lower() and "canonical" in rel.lower():
            continue
        
        # Skip docs
        if "/docs/" in rel or rel.startswith("docs/"):
            continue
            
        for name, line, col in _tokenize_names(p):
            if name in BANNED_TERMS:
                errs.append(
                    LintError(
                        rule_id=RULE_BANNED_TERMS,
                        path=rel,
                        line=line,
                        col=col,
                        message=f"Banned term '{name}' used. "
                                f"These are forbidden permission/capability oracles or parallel authority structures.",
                    )
                )
            elif name in WARN_TERMS:
                errs.append(
                    LintError(
                        rule_id=RULE_BANNED_TERMS,
                        path=rel,
                        line=line,
                        col=col,
                        message=f"Term '{name}' should be reviewed - valid in some contexts, banned as derived list.",
                        severity="WARN",
                    )
                )
    return errs


def check_forbidden_path_apis(root: Path, files: Iterable[Path]) -> List[LintError]:
    """Check for path derivation APIs outside canonical modules."""
    errs: List[LintError] = []
    for p in files:
        rel = _relpath_str(root, p)
        if _allowed_by_substring(rel, ALLOWED_PATH_LOGIC_SUBSTRINGS):
            continue

        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        
        # Check ALWAYS-forbidden patterns (relative_to, os.path.relpath, etc.)
        for pat in FORBIDDEN_PATH_PATTERNS_ALWAYS:
            idx = 0
            while True:
                idx = text.find(pat, idx)
                if idx == -1:
                    break

                # Compute line/col
                prefix = text[:idx]
                line = prefix.count("\n") + 1
                col = len(prefix.split("\n")[-1]) if "\n" in prefix else len(prefix)

                errs.append(
                    LintError(
                        rule_id=RULE_FORBIDDEN_PATH_APIS,
                        path=rel,
                        line=line,
                        col=col,
                        message=f"Forbidden path derivation API '{pat}' used outside canonical path modules. "
                                f"All normalization must flow through WorldAdapter/normalize utility.",
                    )
                )
                idx += 1
        
        # Check for Path(...).resolve( pattern - ALWAYS forbidden
        for m in RE_PATH_RESOLVE.finditer(text):
            prefix = text[:m.start()]
            line = prefix.count("\n") + 1
            col = len(prefix.split("\n")[-1]) if "\n" in prefix else len(prefix)
            
            errs.append(
                LintError(
                    rule_id=RULE_FORBIDDEN_PATH_APIS,
                    path=rel,
                    line=line,
                    col=col,
                    message=f"Forbidden Path(...).resolve() used outside canonical path modules. "
                            f"Use WorldAdapter.resolve() instead.",
                )
            )
        
        # Check for base.resolve( patterns, allow if base is in ALLOWED_RESOLVE_BASE_NAMES
        for m in RE_ATTR_CALL.finditer(text):
            base_name = m.group("base")
            if base_name.lower() in ALLOWED_RESOLVE_BASE_NAMES:
                # This is an allowed WorldAdapter.resolve() call
                continue
            
            # Check if this is a Path(...).resolve( which we already caught above
            # The Path pattern is more specific, so skip if it matches
            match_text = text[max(0, m.start() - 20):m.end()]
            if RE_PATH_RESOLVE.search(match_text):
                continue
            
            prefix = text[:m.start()]
            line = prefix.count("\n") + 1
            col = len(prefix.split("\n")[-1]) if "\n" in prefix else len(prefix)
            
            errs.append(
                LintError(
                    rule_id=RULE_FORBIDDEN_PATH_APIS,
                    path=rel,
                    line=line,
                    col=col,
                    message=f"Suspicious .resolve() call on '{base_name}' outside canonical path modules. "
                            f"Only WorldAdapter (world.resolve()) is allowed. "
                            f"If this is a Path, use WorldAdapter.resolve() instead.",
                )
            )
                
    return errs


def check_enforcement_call_sites(root: Path, files: Iterable[Path]) -> List[LintError]:
    """Check that enforcement calls only occur in allowed boundary modules."""
    errs: List[LintError] = []
    for p in files:
        rel = _relpath_str(root, p)
        if _allowed_by_substring(rel, ALLOWED_ENFORCEMENT_CALLERS_SUBSTRINGS):
            continue

        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
            
        for func in ENFORCEMENT_CALL_TOKENS:
            idx = text.find(func)
            if idx == -1:
                continue

            prefix = text[:idx]
            line = prefix.count("\n") + 1
            col = len(prefix.split("\n")[-1]) if "\n" in prefix else len(prefix)

            errs.append(
                LintError(
                    rule_id=RULE_ENFORCEMENT_CALL_SITES,
                    path=rel,
                    line=line,
                    col=col,
                    message=f"Enforcement call '{func}' found outside allowed boundary/enforcement modules. "
                            f"Phase 1 rule: enforcement is only invoked at tool boundary/dispatcher or enforcement module.",
                )
            )
    return errs


def run_lint(root: Path) -> List[LintError]:
    """Run all Phase 1 lint checks."""
    files = list(iter_python_files(root))

    errors: List[LintError] = []
    errors.extend(check_forbidden_filenames(root, files))
    errors.extend(check_banned_terms(root, files))
    errors.extend(check_forbidden_path_apis(root, files))
    errors.extend(check_enforcement_call_sites(root, files))

    # De-dup exact duplicates
    unique = {(e.rule_id, e.path, e.line, e.col, e.message): e for e in errors}
    return list(unique.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 1 canonical architecture linter")
    parser.add_argument("--root", type=str, default=".", help="Repo root (default: current directory)")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument("--errors-only", action="store_true", help="Only show ERROR severity, hide WARN")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    errors = run_lint(root)
    
    if args.errors_only:
        errors = [e for e in errors if e.severity == "ERROR"]
    
    errors.sort(key=lambda e: (e.severity != "ERROR", e.path, e.line, e.col, e.rule_id))

    if not errors:
        print("OK: canonical phase-1 lint passed")
        return 0

    if args.json:
        print(json.dumps([asdict(e) for e in errors], indent=2))
    else:
        # Group by severity for readability
        error_count = sum(1 for e in errors if e.severity == "ERROR")
        warn_count = sum(1 for e in errors if e.severity == "WARN")
        
        for e in errors:
            severity_marker = "ERROR" if e.severity == "ERROR" else "WARN "
            print(f"{e.path}:{e.line}:{e.col} [{e.rule_id}] {severity_marker} {e.message}")

        print(f"\n{error_count} error(s), {warn_count} warning(s)")
        
        if error_count > 0:
            print("FAIL: canonical phase-1 lint failed")
            return 1
        else:
            print("PASS with warnings")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
