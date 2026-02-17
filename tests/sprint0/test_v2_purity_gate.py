"""
GATE-* — Purity gate tests (AST-based import scanning).

Tests: GATE-01 (v2 imports isolated), GATE-02 (v1 unchanged),
       GATE-03 (no v2 imports in v1 tools).

Adjustment 4: Uses AST-based import scanning — detects direct imports,
alias imports, nested imports, and relative imports. AST > grep.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterator

import pytest

# Repository and MCP package roots
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MCP_ROOT = _REPO_ROOT / "tools" / "ck3lens_mcp"

# Ensure ck3lens is importable
if str(_MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MCP_ROOT))


# =========================================================================
# AST-based import scanner
# =========================================================================

_V2_MODULES = frozenset({"world_adapter_v2", "leak_detector"})

_ALLOWED_STEMS = frozenset({
    "world_adapter_v2",
    "leak_detector",
})

_ALLOWED_REL_PATHS = frozenset({
    "ck3lens/impl/dir_ops.py",
    "server.py",
})


def _is_allowed(rel_posix: str, stem: str) -> bool:
    """Return True if file is allowed to import V2 modules."""
    if stem in _ALLOWED_STEMS:
        return True
    if rel_posix in _ALLOWED_REL_PATHS:
        return True
    if stem.endswith("_v2"):
        return True
    if "tests/" in rel_posix or "test_" in stem:
        return True
    return False


def _find_v2_imports_ast(source: str) -> list[tuple[int, str]]:
    """Parse source with AST and return list of (line, imported_module) for V2 imports.
    
    Detects:
    - `import world_adapter_v2`
    - `import ck3lens.world_adapter_v2`
    - `from world_adapter_v2 import ...`
    - `from ck3lens.world_adapter_v2 import ...`
    - `from .world_adapter_v2 import ...`
    - `from ..world_adapter_v2 import ...`
    - Alias imports (`import world_adapter_v2 as wa2`)
    - Nested function-level imports
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # alias.name could be "world_adapter_v2" or "ck3lens.world_adapter_v2"
                parts = alias.name.split(".")
                for part in parts:
                    if part in _V2_MODULES:
                        violations.append((node.lineno, part))
                        break

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            parts = module.split(".")
            for part in parts:
                if part in _V2_MODULES:
                    violations.append((node.lineno, part))
                    break

    return violations


def _iter_py_files(root: Path) -> Iterator[Path]:
    """Iterate all .py files under root, excluding __pycache__ and node_modules."""
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts or "node_modules" in p.parts:
            continue
        yield p


# =========================================================================
# GATE-01: v2 Module Imports Are Isolated (AST-based)
# =========================================================================

class TestGATE01V2ImportsIsolated:
    """No file outside the allowed set imports from world_adapter_v2 or leak_detector."""

    def test_no_unauthorized_imports(self) -> None:
        violations: list[str] = []

        for py_file in _iter_py_files(_MCP_ROOT):
            rel = py_file.relative_to(_MCP_ROOT)
            rel_posix = rel.as_posix()
            stem = py_file.stem

            if _is_allowed(rel_posix, stem):
                continue

            source = py_file.read_text(encoding="utf-8", errors="replace")
            imports = _find_v2_imports_ast(source)

            for line, mod in imports:
                violations.append(f"{rel_posix}:{line} imports {mod}")

        assert violations == [], (
            f"Unauthorized V2 imports found:\n" + "\n".join(f"  - {v}" for v in violations)
        )


# =========================================================================
# GATE-02: v1 WorldAdapter Unchanged
# =========================================================================

class TestGATE02V1Unchanged:
    """world_adapter.py has zero diff from the Sprint 0 baseline.
    
    We verify this by checking that world_adapter.py does NOT import from
    or reference world_adapter_v2 at all — the strongest invariant we can
    check without git diff in a unit test.
    """

    def test_v1_no_v2_references(self) -> None:
        v1_path = _MCP_ROOT / "ck3lens" / "world_adapter.py"
        assert v1_path.exists(), "world_adapter.py (v1) not found"

        source = v1_path.read_text(encoding="utf-8")
        imports = _find_v2_imports_ast(source)
        assert imports == [], (
            f"world_adapter.py (v1) imports V2 modules: {imports}"
        )
        # Also check no string reference to world_adapter_v2
        assert "world_adapter_v2" not in source, (
            "world_adapter.py (v1) references 'world_adapter_v2' in source text"
        )


# =========================================================================
# GATE-03: No v2 Imports in v1 Tools (AST-based)
# =========================================================================

class TestGATE03NoV2InV1Tools:
    """Specific v1 files must NOT import anything from world_adapter_v2.
    
    Uses AST-based scanning, not grep.
    """

    _V1_FILES = [
        "ck3lens/unified_tools.py",
        "ck3lens/workspace.py",
        "ck3lens/contracts.py",
        "ck3lens/impl/file_ops.py",
        "ck3lens/impl/search_ops.py",
        "ck3lens/impl/conflict_ops.py",
        "ck3lens/impl/playset_ops.py",
    ]

    @pytest.mark.parametrize("rel_path", _V1_FILES)
    def test_no_v2_import(self, rel_path: str) -> None:
        full_path = _MCP_ROOT / rel_path
        if not full_path.exists():
            pytest.skip(f"{rel_path} does not exist")

        source = full_path.read_text(encoding="utf-8", errors="replace")
        imports = _find_v2_imports_ast(source)

        assert imports == [], (
            f"{rel_path} has unauthorized V2 imports: "
            + ", ".join(f"line {ln}: {mod}" for ln, mod in imports)
        )
