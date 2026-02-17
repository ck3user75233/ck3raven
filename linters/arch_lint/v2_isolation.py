"""V2 Isolation Purity Gate — Sprint 0.

Scans ``tools/ck3lens_mcp/`` to enforce that **only** authorized files
import from ``world_adapter_v2`` or ``leak_detector``.

Authorized importers (allowlist):
    • world_adapter_v2.py itself
    • leak_detector.py itself
    • impl/dir_ops.py
    • server.py  (lazy import inside _get_world_v2 / ck3_dir)
    • Any file whose stem ends with ``_v2`` (future Sprint expansions)
    • Any file under ``tests/`` (test code)

Runs standalone::

    python -m linters.arch_lint.v2_isolation [--json]

Or can be called programmatically::

    from linters.arch_lint.v2_isolation import check_v2_isolation
    findings = check_v2_isolation(repo_root)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

from .reporting import Finding, Reporter

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Modules whose imports we protect (bare module names, no package prefix).
PROTECTED_MODULES = frozenset({"world_adapter_v2", "leak_detector"})

# Stems (or path-substring matches) allowed to import the protected modules.
# Paths are checked as POSIX-normalised relative paths from the MCP root.
_ALLOWED_STEMS: frozenset[str] = frozenset({
    "world_adapter_v2",
    "leak_detector",
})

_ALLOWED_REL_PATHS: frozenset[str] = frozenset({
    "ck3lens/impl/dir_ops.py",
    "server.py",
})


def _is_allowed(rel_posix: str, stem: str) -> bool:
    """Return True if *rel_posix* (from MCP root) is permitted to import V2."""
    # Exact stem match (e.g. world_adapter_v2.py, leak_detector.py)
    if stem in _ALLOWED_STEMS:
        return True
    # Exact relative-path match
    if rel_posix in _ALLOWED_REL_PATHS:
        return True
    # Future-proof: any *_v2.py file
    if stem.endswith("_v2"):
        return True
    # Test files are always allowed
    if "tests/" in rel_posix or "test_" in stem:
        return True
    return False


# ---------------------------------------------------------------------------
# Import detection regex
# ---------------------------------------------------------------------------

# Matches:
#   from world_adapter_v2 import ...
#   from ck3lens.world_adapter_v2 import ...
#   from .world_adapter_v2 import ...
#   from ..world_adapter_v2 import ...
#   import world_adapter_v2
#   import ck3lens.world_adapter_v2
_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+[\w.]*\.?(?P<from_mod>"
    + "|".join(re.escape(m) for m in PROTECTED_MODULES)
    + r")\s+import"
    + r"|import\s+[\w.]*\.?(?P<imp_mod>"
    + "|".join(re.escape(m) for m in PROTECTED_MODULES)
    + r"))"
)


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def check_v2_isolation(
    repo_root: Path,
    *,
    mcp_subdir: str = "tools/ck3lens_mcp",
) -> list[Finding]:
    """Scan *mcp_subdir* for unauthorised V2 imports.

    Returns a (possibly empty) list of :class:`Finding` objects.
    """
    mcp_root = repo_root / mcp_subdir
    if not mcp_root.is_dir():
        return []

    findings: list[Finding] = []

    for py_file in mcp_root.rglob("*.py"):
        rel = py_file.relative_to(mcp_root)
        rel_posix = rel.as_posix()
        stem = py_file.stem

        if _is_allowed(rel_posix, stem):
            continue

        try:
            lines = py_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        for line_no, line_text in enumerate(lines, start=1):
            m = _IMPORT_RE.match(line_text)
            if m:
                imported = m.group("from_mod") or m.group("imp_mod") or ""
                findings.append(Finding(
                    rule_id="V2-ISOLATION",
                    severity="ERROR",
                    path=str(py_file),
                    line=line_no,
                    col=0,
                    message=(
                        f"Unauthorised import of '{imported}' in {rel_posix}. "
                        f"Only allowlisted files may import V2 modules."
                    ),
                    evidence=line_text.strip()[:220],
                    suggested_fix=(
                        "Move V2 usage to an allowlisted module (dir_ops, server, "
                        "or a *_v2.py file), or add this file to the allowlist in "
                        "linters/arch_lint/v2_isolation.py."
                    ),
                ))

    return findings


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    """Run the purity gate from the command line."""
    import argparse

    parser = argparse.ArgumentParser(
        description="V2 isolation purity gate for Sprint 0",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detect from CWD)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output findings as JSONL",
    )
    args = parser.parse_args(argv)

    root = args.root
    if root is None:
        # Walk up from this file to find repo root (contains pyproject.toml)
        candidate = Path(__file__).resolve().parent
        for _ in range(10):
            if (candidate / "pyproject.toml").exists():
                root = candidate
                break
            candidate = candidate.parent
        if root is None:
            print("ERROR: Could not locate repo root. Pass --root.", file=sys.stderr)
            return 2

    findings = check_v2_isolation(root)

    if not findings:
        print("v2_isolation: PASS — no unauthorised imports found.")
        return 0

    rpt = Reporter()
    for f in findings:
        rpt.add(f)

    if args.json_output:
        print(rpt.to_jsonl())
    else:
        print(rpt.render_human())

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
