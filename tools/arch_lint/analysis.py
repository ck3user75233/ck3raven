"""
arch_lint v2.35 — AST analysis and module indexing.

Handles:
- Python AST parsing
- Symbol definition extraction
- Call site extraction
- If-condition extraction
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .scanner import SourceFile


@dataclass(frozen=True)
class DefSymbol:
    """A defined symbol (function, class, variable)."""
    name: str
    kind: str  # "function", "class", "var"
    path: Path
    line: int
    col: int
    deprecated: bool = False


@dataclass
class ModuleIndex:
    """Index of a Python module's structure."""
    defs: list[DefSymbol]
    refs: set[str]
    calls: list[tuple[str, int, int]]         # (callee, line, col) for Name() calls
    dotted_calls: list[tuple[str, int, int]]  # (dotted, line, col) for Attribute() calls
    if_tests: list[tuple[str, int, int]]      # (test_src, line, col)


class _Collector(ast.NodeVisitor):
    """AST visitor to collect references, calls, and if-tests."""
    
    def __init__(self) -> None:
        self.refs: set[str] = set()
        self.calls: list[tuple[str, int, int]] = []
        self.dotted_calls: list[tuple[str, int, int]] = []
        self.if_tests: list[tuple[str, int, int]] = []
    
    def visit_Name(self, node: ast.Name) -> None:
        self.refs.add(node.id)
        self.generic_visit(node)
    
    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        if isinstance(fn, ast.Name):
            self.calls.append((fn.id, node.lineno, node.col_offset))
        elif isinstance(fn, ast.Attribute):
            parts = []
            cur = fn
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
                dotted = ".".join(reversed(parts))
                self.dotted_calls.append((dotted, node.lineno, node.col_offset))
        self.generic_visit(node)
    
    def visit_If(self, node: ast.If) -> None:
        try:
            test_src = ast.unparse(node.test)
        except Exception:
            test_src = ""
        self.if_tests.append((test_src, node.lineno, node.col_offset))
        self.generic_visit(node)


def _has_deprecated_comment_near(lines: list[str], line_no: int) -> bool:
    """Check if there's a #deprecated comment near the line."""
    for ln in range(max(1, line_no - 2), line_no + 1):
        if ln <= len(lines) and "#deprecated" in lines[ln - 1].lower():
            return True
    return False


def build_index(src: SourceFile) -> ModuleIndex:
    """Build a ModuleIndex from a Python source file."""
    lines = src.lines
    
    try:
        tree = ast.parse(src.text, filename=str(src.path))
    except SyntaxError:
        return ModuleIndex(defs=[], refs=set(), calls=[], dotted_calls=[], if_tests=[])
    
    # Collect top-level definitions
    defs: list[DefSymbol] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append(DefSymbol(
                name=node.name,
                kind="function",
                path=src.path,
                line=node.lineno,
                col=node.col_offset,
                deprecated=_has_deprecated_comment_near(lines, node.lineno),
            ))
        elif isinstance(node, ast.ClassDef):
            defs.append(DefSymbol(
                name=node.name,
                kind="class",
                path=src.path,
                line=node.lineno,
                col=node.col_offset,
                deprecated=_has_deprecated_comment_near(lines, node.lineno),
            ))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    defs.append(DefSymbol(
                        name=t.id,
                        kind="var",
                        path=src.path,
                        line=node.lineno,
                        col=node.col_offset,
                        deprecated=_has_deprecated_comment_near(lines, node.lineno),
                    ))
    
    # Collect references, calls, if-tests
    collector = _Collector()
    collector.visit(tree)
    
    return ModuleIndex(
        defs=defs,
        refs=collector.refs,
        calls=collector.calls,
        dotted_calls=collector.dotted_calls,
        if_tests=collector.if_tests,
    )


def collect_repo_refs(src: SourceFile) -> set[str]:
    """Collect all referenced names from a source file."""
    idx = build_index(src)
    return idx.refs
