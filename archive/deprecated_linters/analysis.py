from __future__ import annotations
import ast
from dataclasses import dataclass
from pathlib import Path
from .scanner import SourceFile

@dataclass(frozen=True)
class DefSymbol:
    name: str
    kind: str  # function|class|var
    path: Path
    line: int
    col: int
    deprecated: bool = False

@dataclass
class ModuleIndex:
    defs: list[DefSymbol]
    refs: set[str]
    calls: list[tuple[str,int,int]]         # (callee, line, col) for Name() calls only
    dotted_calls: list[tuple[str,int,int]]  # (dotted, line, col) for Attribute() calls
    if_tests: list[tuple[str,int,int]]      # (test_src, line, col)

class Collector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.refs: set[str] = set()
        self.calls: list[tuple[str,int,int]] = []
        self.dotted_calls: list[tuple[str,int,int]] = []
        self.if_tests: list[tuple[str,int,int]] = []

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
    for ln in range(max(1, line_no-2), line_no+1):
        if ln <= len(lines) and "#deprecated" in lines[ln-1].lower():
            return True
    return False

def index_module(path: Path, text: str) -> ModuleIndex:
    lines = text.splitlines()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return ModuleIndex(defs=[], refs=set(), calls=[], dotted_calls=[], if_tests=[])

    defs: list[DefSymbol] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append(DefSymbol(node.name, "function", path, node.lineno, node.col_offset, _has_deprecated_comment_near(lines, node.lineno)))
        elif isinstance(node, ast.ClassDef):
            defs.append(DefSymbol(node.name, "class", path, node.lineno, node.col_offset, _has_deprecated_comment_near(lines, node.lineno)))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    defs.append(DefSymbol(t.id, "var", path, node.lineno, node.col_offset, _has_deprecated_comment_near(lines, node.lineno)))

    col = Collector()
    col.visit(tree)
    return ModuleIndex(defs=defs, refs=col.refs, calls=col.calls, dotted_calls=col.dotted_calls, if_tests=col.if_tests)

# === Wrappers for runner.py ===
def build_index(src: SourceFile) -> ModuleIndex:
    """Build ModuleIndex from SourceFile."""
    return index_module(src.path, src.text)

def collect_repo_refs(src: SourceFile) -> set[str]:
    """Collect all referenced names from a source file."""
    idx = build_index(src)
    return idx.refs