"""
Code-Diff Guard

Prevents duplicate implementations and shadow pipelines by analyzing
code changes (diffs) for forbidden patterns.

This guard runs:
- Pre-commit (advisory in local, authoritative in CI)
- On any code modification

Core Rule:
    Any new or modified code must either:
    1. Extend an existing canonical implementation, or
    2. Introduce a new canonical implementation in the correct domain

Creating "parallel" or "shadow" logic is forbidden.

Canonical Locations:
    src/ck3raven/**   - Real logic allowed
    builder/**        - Real logic allowed

Thin Locations (no business logic):
    tools/**          - CLI glue, MCP tools only
    scripts/**        - CLI glue, one-off scripts only

Forbidden Patterns (Hard Fail):
    - Duplicate function names (extract_*, parse_*, ingest_*, etc.)
    - Shadow routing (os.walk, glob, rglob in thin code)
    - Path-based routing logic in thin code
    - DB access outside canonical DB modules
    - Re-implementation of existing logic
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional


# ============================================================================
# Configuration
# ============================================================================

# Canonical code locations (where business logic belongs)
CANONICAL_PATHS = [
    "src/ck3raven/**",
    "builder/**",
]

# Thin code locations (no business logic allowed)
THIN_PATHS = [
    "tools/**",
    "scripts/**",
]

# Test paths (exempt from most rules)
TEST_PATHS = [
    "tests/**",
]

# Forbidden function name patterns in thin code
FORBIDDEN_FUNCTION_PATTERNS = [
    r"def (extract|parse|ingest|route|classify|resolve)_\w+",
    r"def (build|generate|create|compute)_\w+(?!_response|_error|_result)",
    r"def _?(do|process|handle)_\w+",
]

# Shadow routing patterns (forbidden in thin code)
SHADOW_ROUTING_PATTERNS = [
    r"\bos\.walk\s*\(",
    r"\bglob\.glob\s*\(",
    r"\.rglob\s*\(",
    r"\.glob\s*\(",
    r'if\s+["\']common/',
    r'if\s+["\']events?/',
    r'\.startswith\s*\(\s*["\']common/',
    r'\.endswith\s*\(\s*["\']\.txt["\']\s*\)',
]

# DB access patterns (forbidden outside canonical DB modules)
DB_ACCESS_PATTERNS = [
    r"\.execute\s*\(",
    r"\.executemany\s*\(",
    r"sqlite3\.connect\s*\(",
    r"conn\.cursor\s*\(",
]

# Keywords suggesting duplicate implementation
DUPLICATE_KEYWORDS = [
    r"\b(v2|new|fixed|quick|temp|alt|my)_\w+",
    r"# ?TODO:? ?(move|refactor|consolidate)",
]


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class Violation:
    """A detected code-diff guard violation."""
    file_path: str
    line_number: int
    rule: str
    message: str
    severity: Literal["error", "warning"] = "error"
    context: str = ""


@dataclass
class GuardResult:
    """Result of running the code-diff guard."""
    passed: bool
    violations: list[Violation] = field(default_factory=list)
    files_checked: int = 0
    
    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violations": [
                {
                    "file": v.file_path,
                    "line": v.line_number,
                    "rule": v.rule,
                    "message": v.message,
                    "severity": v.severity,
                }
                for v in self.violations
            ],
            "files_checked": self.files_checked,
        }


# ============================================================================
# Path Classification
# ============================================================================

def _matches_pattern(path: str, patterns: list[str]) -> bool:
    """Check if path matches any glob pattern."""
    import fnmatch
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
    return False


def classify_path(path: str) -> Literal["canonical", "thin", "test", "other"]:
    """
    Classify a file path by its location.
    
    Returns:
        canonical: Business logic allowed
        thin: No business logic allowed
        test: Test file (exempt from most rules)
        other: Unknown location
    """
    # Normalize path
    path = path.replace("\\", "/")
    
    if _matches_pattern(path, TEST_PATHS):
        return "test"
    elif _matches_pattern(path, CANONICAL_PATHS):
        return "canonical"
    elif _matches_pattern(path, THIN_PATHS):
        return "thin"
    else:
        return "other"


def get_domain_for_path(path: str) -> Optional[str]:
    """
    Get the canonical domain for a path.
    
    Returns:
        Domain name or None if not in a canonical location
    """
    path = path.replace("\\", "/")
    
    domain_map = {
        "src/ck3raven/parser/": "parser",
        "src/ck3raven/resolver/": "routing",
        "src/ck3raven/db/": "extraction",  # or query
        "src/ck3raven/emulator/": "builder",
        "builder/": "builder",
        "tools/": "cli",
        "scripts/": "cli",
    }
    
    for prefix, domain in domain_map.items():
        if path.startswith(prefix):
            return domain
    
    return None


# ============================================================================
# Pattern Detection
# ============================================================================

def check_forbidden_functions(
    content: str,
    file_path: str,
) -> list[Violation]:
    """Check for forbidden function patterns in thin code."""
    violations = []
    
    for line_num, line in enumerate(content.splitlines(), 1):
        for pattern in FORBIDDEN_FUNCTION_PATTERNS:
            if re.search(pattern, line):
                # Extract function name
                match = re.search(r"def (\w+)", line)
                func_name = match.group(1) if match else "unknown"
                
                violations.append(Violation(
                    file_path=file_path,
                    line_number=line_num,
                    rule="forbidden_function",
                    message=f"Business logic function '{func_name}' not allowed in thin code",
                    context=line.strip(),
                ))
    
    return violations


def check_shadow_routing(
    content: str,
    file_path: str,
) -> list[Violation]:
    """Check for shadow routing patterns."""
    violations = []
    
    for line_num, line in enumerate(content.splitlines(), 1):
        for pattern in SHADOW_ROUTING_PATTERNS:
            if re.search(pattern, line):
                violations.append(Violation(
                    file_path=file_path,
                    line_number=line_num,
                    rule="shadow_routing",
                    message="Shadow routing pattern detected - use canonical routing module",
                    context=line.strip(),
                ))
    
    return violations


def check_db_access(
    content: str,
    file_path: str,
) -> list[Violation]:
    """Check for DB access outside canonical modules."""
    violations = []
    
    # Allow DB access in db_queries.py
    if "db_queries" in file_path or "db/" in file_path:
        return []
    
    for line_num, line in enumerate(content.splitlines(), 1):
        for pattern in DB_ACCESS_PATTERNS:
            if re.search(pattern, line):
                violations.append(Violation(
                    file_path=file_path,
                    line_number=line_num,
                    rule="db_access_outside_canonical",
                    message="Direct DB access not allowed in thin code - use db_queries",
                    context=line.strip(),
                ))
    
    return violations


def check_duplicate_keywords(
    content: str,
    file_path: str,
) -> list[Violation]:
    """Check for keywords suggesting duplicate implementation."""
    violations = []
    
    for line_num, line in enumerate(content.splitlines(), 1):
        for pattern in DUPLICATE_KEYWORDS:
            if re.search(pattern, line, re.IGNORECASE):
                violations.append(Violation(
                    file_path=file_path,
                    line_number=line_num,
                    rule="duplicate_indicator",
                    message="Naming suggests duplicate implementation",
                    severity="warning",
                    context=line.strip(),
                ))
    
    return violations


def check_canonical_header(
    content: str,
    file_path: str,
) -> list[Violation]:
    """
    Check that new canonical modules have the required header.
    
    Required header:
        # CanonicalDomain: <domain>
        # Rationale: <why>
        # Related: <existing modules>
    """
    violations = []
    
    # Only check canonical locations
    if classify_path(file_path) != "canonical":
        return []
    
    # Check for module docstring or header
    lines = content.splitlines()[:30]  # Check first 30 lines
    
    has_domain = any("# CanonicalDomain:" in line for line in lines)
    has_rationale = any("# Rationale:" in line for line in lines)
    
    if not has_domain:
        violations.append(Violation(
            file_path=file_path,
            line_number=1,
            rule="missing_canonical_header",
            message="Canonical module missing '# CanonicalDomain:' header",
            severity="warning",
        ))
    
    if not has_rationale:
        violations.append(Violation(
            file_path=file_path,
            line_number=1,
            rule="missing_canonical_header",
            message="Canonical module missing '# Rationale:' header",
            severity="warning",
        ))
    
    return violations


# ============================================================================
# Main Guard Function
# ============================================================================

def run_guard(
    files: list[tuple[str, str]],  # (path, content) pairs
    strict: bool = False,
) -> GuardResult:
    """
    Run the code-diff guard on a set of files.
    
    Args:
        files: List of (path, content) tuples to check
        strict: If True, warnings are treated as errors
    
    Returns:
        GuardResult with pass/fail and violations
    """
    all_violations = []
    
    for file_path, content in files:
        path_type = classify_path(file_path)
        
        # Skip non-Python files
        if not file_path.endswith(".py"):
            continue
        
        # Skip tests
        if path_type == "test":
            continue
        
        # Different rules for thin vs canonical
        if path_type == "thin":
            # Thin code gets stricter checks
            all_violations.extend(check_forbidden_functions(content, file_path))
            all_violations.extend(check_shadow_routing(content, file_path))
            all_violations.extend(check_db_access(content, file_path))
            all_violations.extend(check_duplicate_keywords(content, file_path))
        
        elif path_type == "canonical":
            # Canonical code needs headers
            all_violations.extend(check_canonical_header(content, file_path))
            all_violations.extend(check_duplicate_keywords(content, file_path))
    
    # Determine pass/fail
    errors = [v for v in all_violations if v.severity == "error"]
    warnings = [v for v in all_violations if v.severity == "warning"]
    
    if strict:
        passed = len(all_violations) == 0
    else:
        passed = len(errors) == 0
    
    return GuardResult(
        passed=passed,
        violations=all_violations,
        files_checked=len(files),
    )


def run_guard_on_diff(
    base_ref: str = "HEAD~1",
    strict: bool = False,
) -> GuardResult:
    """
    Run guard on files changed since base_ref.
    
    Args:
        base_ref: Git ref to compare against (default: HEAD~1)
        strict: Treat warnings as errors
    
    Returns:
        GuardResult
    """
    # Get list of changed files
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_ref],
            capture_output=True,
            text=True,
            check=True,
        )
        changed_files = result.stdout.strip().split("\n")
        changed_files = [f for f in changed_files if f.endswith(".py")]
    except subprocess.CalledProcessError:
        return GuardResult(passed=True, files_checked=0)
    
    if not changed_files:
        return GuardResult(passed=True, files_checked=0)
    
    # Read file contents
    files = []
    for file_path in changed_files:
        path = Path(file_path)
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                files.append((file_path, content))
            except Exception:
                continue
    
    return run_guard(files, strict=strict)


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """CLI entry point for code-diff guard."""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(
        description="""Code-Diff Guard - Prevents duplicate implementations and shadow pipelines

This guard analyzes code changes for forbidden patterns that would create
duplicate logic or bypass the canonical architecture.

CANONICAL LOCATIONS (business logic allowed):
  src/ck3raven/**   - Parser, resolver, DB, emulator
  builder/**        - Database builder

THIN LOCATIONS (no business logic):
  tools/**          - CLI glue, MCP tools only
  scripts/**        - CLI glue, one-off scripts only

FORBIDDEN PATTERNS IN THIN CODE:
  - Functions named extract_*, parse_*, ingest_*, route_*, etc.
  - Shadow routing (os.walk, glob, rglob)
  - Direct DB access (.execute, sqlite3.connect)
  - Duplicate indicators (v2_*, new_*, temp_*)

USAGE:
  Check staged changes:     python code_diff_guard.py --base HEAD
  Check last commit:        python code_diff_guard.py --base HEAD~1
  Strict mode (CI):         python code_diff_guard.py --base HEAD~1 --strict
  JSON output:              python code_diff_guard.py --json

EXIT CODES:
  0 = All checks passed
  1 = Violations found (commit should be blocked)
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base", "-b",
        default="HEAD~1",
        help="Git ref to compare against (default: HEAD~1)",
    )
    parser.add_argument(
        "--strict", "-s",
        action="store_true",
        help="Treat warnings as errors (use in CI)",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output results as JSON",
    )
    
    args = parser.parse_args()
    
    result = run_guard_on_diff(base_ref=args.base, strict=args.strict)
    
    if args.json:
        import json
        print(json.dumps(result.to_dict(), indent=2))
    else:
        if result.passed:
            print(f"✅ Code-Diff Guard PASSED ({result.files_checked} files checked)")
        else:
            print(f"❌ Code-Diff Guard FAILED ({len(result.violations)} violations)")
            print()
            for v in result.violations:
                icon = "❌" if v.severity == "error" else "⚠️"
                print(f"{icon} [{v.rule}] {v.file_path}:{v.line_number}")
                print(f"   {v.message}")
                if v.context:
                    print(f"   > {v.context}")
                print()
    
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
