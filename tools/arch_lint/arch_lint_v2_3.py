#!/usr/bin/env python3
"""
arch_lint v2.3 — Token-based banned concept detector.

Key upgrades vs v2.2:
- Tokenization catches snake_case, kebab-case, whitespace, punctuation, and camelCase.
- Composite pattern matching: 'active%local%mods' means tokens appear in order with gaps.
- Mix-and-match suspicious combo rules (without enumerating every exact phrase).
- Case-insensitive everywhere.
- Allowlist exceptions at token and raw-text level (e.g., 'local_mods_folder').

Outputs:
- ERROR: definite architectural violations (banned concepts, raw mutation surfaces, etc.)
- WARN: suspicious combos / legacy remnants / unused symbols (heuristic)
"""

from __future__ import annotations

import ast
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

# -----------------------------
# Configuration
# -----------------------------

PY_FILE_EXCLUDES = {
    ".venv", "venv", "__pycache__", ".git", ".mypy_cache", ".pytest_cache",
    "node_modules", "dist", "build",
}

DEFAULT_ROOT = Path(".").resolve()

# Context suppression hints to avoid flagging banned-term lists/docs/examples
BANNED_CONTEXT_HINTS = [
    "banned", "banlist", "banned_terms", "banned term", "banned pattern",
    "forbid", "forbidden", "do not use", "deprecated", "arch_lint",
    "example", "docs", "documentation", "readme",
]

DEPRECATED_HINTS = ["deprecated", "deprecate", "legacy", "remove soon", "todo: remove"]

# Canonical allowlist exceptions (raw text substrings) — do NOT flag if hit is within these.
# Add canonical phrases here deliberately.
RAW_ALLOWLIST_SUBSTRINGS = [
    "local_mods_folder",  # canonical allowed
]

# Canonical allowlist token sequences — if the matched token window equals one of these, suppress.
# Example: local_mods_folder tokenizes to ['local','mods','folder'].
ALLOWLIST_TOKEN_SEQUENCES = [
    ("local", "mods", "folder"),
]

# -----------------------------
# Banned direct terms (definite)
# These are *concept roots* that should not appear as identifiers/phrases in executable code.
# NOTE: v2.3 also catches variants via tokenization; you don't need to list every underscore/case form.
# -----------------------------
BANNED_DIRECT_TERMS = [
    # Lens / drift terms (keep aligned with your bans)
    "playsetlens", "lensworld", "getlens", "get.lens", "lens_cache",

    # Old parallel truths
    "live_mods", "live_mods_config", "default_live_mods",
    "active_mods", "enabled_mods", "mod_groups",

    # Oracles / path registries
    "mod_root", "local_mod_root", "mod_paths", "active_mod_paths",

    # Known bad helpers
    "_derive_search_cvids", "_build_cv_filter", "_validate_visibility",
]

# -----------------------------
# Composite banned patterns (mix-and-match, "worthy of investigation")
# Pattern language:
#   - tokens separated by '%' must appear IN ORDER with any gaps
#   - example: 'active%local%mods' matches tokens ... active ... local ... mods ...
#
# Severity:
#   - Put truly banned combos as ERROR
#   - Put "investigate" combos as WARN
# -----------------------------
COMPOSITE_RULES = [
    # DEFINITE BAD (ERROR)
    ("ERROR", "BANNED_COMPOSITE", "live%mods", "Parallel truth: live mods"),
    ("ERROR", "BANNED_COMPOSITE", "active%mods", "Parallel truth: active mods"),
    ("ERROR", "BANNED_COMPOSITE", "enabled%mods", "Parallel truth: enabled mods"),
    ("ERROR", "BANNED_COMPOSITE", "mod%root", "Path oracle: mod root"),
    ("ERROR", "BANNED_COMPOSITE", "mod%paths", "Path oracle: mod paths"),
    ("ERROR", "BANNED_COMPOSITE", "local%mod%root", "Path oracle: local mod root"),

    # HIGH-SIGNAL INVESTIGATE (WARN) — these often indicate drift
    ("WARN", "SUSPECT_COMPOSITE", "active%local%mods", "Likely drift: active local mods"),
    ("WARN", "SUSPECT_COMPOSITE", "live%local%mods", "Likely drift: live local mods"),
    ("WARN", "SUSPECT_COMPOSITE", "local%mods", "Suspicious: local mods (ensure not a parallel truth)"),
    ("WARN", "SUSPECT_COMPOSITE", "workspace%mods", "Suspicious: workspace mods registry"),
]

# Token-level "must-not" combos regardless of separators/case:
# if these tokens occur near each other (within a window), flag.
# Example: tokens {'active','mods'} within window=6 => warn/error.
NEAR_WINDOW_RULES = [
    ("ERROR", "BANNED_NEAR", {"live", "mods"}, 6, "Parallel truth: live mods (near-match)"),
    ("ERROR", "BANNED_NEAR", {"active", "mods"}, 6, "Parallel truth: active mods (near-match)"),
    ("ERROR", "BANNED_NEAR", {"mod", "root"}, 6, "Path oracle: mod root (near-match)"),
    ("ERROR", "BANNED_NEAR", {"mod", "paths"}, 8, "Path oracle: mod paths (near-match)"),
    ("WARN", "SUSPECT_NEAR", {"local", "mods"}, 6, "Suspicious: local mods (near-match)"),
]

# Semantic path operations — if you still want these enforced (optional)
SEMANTIC_PATH_TOKENS = [
    ".resolve(",
    ".relative_to(",
]
OS_PATH_ALLOWLIST_FILES = [
    "world_adapter.py",
    "paths.py",
    "path_utils.py",
    "arch_lint_v2_3.py",
]
OS_PATH_WAIVER_TAG = "CK3RAVEN_OS_PATH_OK"

# -----------------------------
# Findings
# -----------------------------

@dataclass(frozen=True)
class Finding:
    kind: str          # "ERROR" or "WARN"
    code: str
    path: str
    line: int
    col: int
    message: str
    excerpt: str


# -----------------------------
# File walking
# -----------------------------

def iter_python_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        parts = set(Path(dirpath).parts)
        if parts & PY_FILE_EXCLUDES:
            dirnames[:] = []
            continue
        for fn in filenames:
            if fn.endswith(".py"):
                yield Path(dirpath) / fn


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# -----------------------------
# Tokenization (core upgrade)
# -----------------------------

_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")

def normalize_for_scan(s: str) -> str:
    # Lowercase for case-insensitive match
    return s.lower()

def tokenize_line(line: str) -> list[str]:
    """
    Tokenize robustly across snake_case, kebab-case, whitespace, punctuation, and camelCase.
    """
    # Split camelCase boundaries first by inserting spaces
    # e.g., ActiveLocalMods -> Active Local Mods
    line2 = _CAMEL_SPLIT.sub(" ", line)
    # Normalize separators to spaces
    line2 = _NON_ALNUM.sub(" ", line2)
    # Lowercase
    line2 = line2.lower()
    tokens = [t for t in line2.split() if t]
    return tokens

def tokenize_text_window(lines: list[str]) -> list[str]:
    toks: list[str] = []
    for ln in lines:
        toks.extend(tokenize_line(ln))
    return toks

def contains_allowlisted_raw(line: str) -> bool:
    l = line.lower()
    return any(x in l for x in RAW_ALLOWLIST_SUBSTRINGS)

def is_context_suppressed(line_text: str, window_text: str) -> bool:
    lt = line_text.lower()
    wt = window_text.lower()
    return any(h in lt for h in BANNED_CONTEXT_HINTS) or any(h in wt for h in BANNED_CONTEXT_HINTS)

def is_deprecated_line(line_text: str) -> bool:
    lt = line_text.lower()
    return any(h in lt for h in DEPRECATED_HINTS)


# -----------------------------
# Matching utilities
# -----------------------------

def match_composite_tokens(tokens: list[str], pattern: str) -> Optional[Tuple[int, int]]:
    """
    Returns (start_index, end_index_exclusive) of the matched span in tokens, or None.
    pattern format: 'a%b%c' => tokens a then b then c in order, with gaps allowed.
    """
    parts = [p.strip().lower() for p in pattern.split("%") if p.strip()]
    if not parts:
        return None
    start = 0
    first_pos = None
    last_pos = None
    for p in parts:
        try:
            idx = tokens.index(p, start)
        except ValueError:
            return None
        if first_pos is None:
            first_pos = idx
        last_pos = idx
        start = idx + 1
    return (first_pos or 0, (last_pos or 0) + 1)

def window_equals_allowlisted(tokens: list[str], span: Tuple[int, int]) -> bool:
    s, e = span
    window = tuple(tokens[s:e])
    return window in ALLOWLIST_TOKEN_SEQUENCES

def match_near_window(tokens: list[str], required: set[str], window: int) -> Optional[Tuple[int, int]]:
    """
    Returns span of the smallest window where all required tokens occur within `window` length.
    """
    req = set(t.lower() for t in required)
    n = len(tokens)
    for i in range(n):
        if tokens[i] not in req:
            continue
        seen = set()
        for j in range(i, min(n, i + window)):
            if tokens[j] in req:
                seen.add(tokens[j])
            if seen == req:
                return (i, j + 1)
    return None


# -----------------------------
# Rule scanners
# -----------------------------

def scan_direct_terms(path: Path, lines: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for i, line in enumerate(lines, start=1):
        if contains_allowlisted_raw(line):
            continue
        l = line.lower()
        # small context window
        lo = max(0, i - 1 - 4)
        hi = min(len(lines), i - 1 + 5)
        window_text = "\n".join(lines[lo:hi])
        if is_context_suppressed(line, window_text):
            continue
        for term in BANNED_DIRECT_TERMS:
            t = term.lower()
            if t in l:
                kind = "ERROR"
                code = "BANNED_TERM"
                msg = f"Use of banned term '{term}'. Remove/rename to canonical architecture."
                if is_deprecated_line(line):
                    kind = "WARN"
                    code = "DEPRECATED_BANNED_TERM"
                    msg = f"Deprecated banned term '{term}' still present. Remove fully."
                findings.append(Finding(
                    kind=kind,
                    code=code,
                    path=str(path),
                    line=i,
                    col=max(1, l.find(t) + 1),
                    message=msg,
                    excerpt=line.strip()[:240],
                ))
    return findings

def scan_composites(path: Path, lines: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for i, line in enumerate(lines, start=1):
        if contains_allowlisted_raw(line):
            continue
        lo = max(0, i - 1 - 4)
        hi = min(len(lines), i - 1 + 5)
        window_lines = lines[lo:hi]
        window_text = "\n".join(window_lines)

        if is_context_suppressed(line, window_text):
            continue

        tokens = tokenize_text_window(window_lines)

        for kind, code, pattern, reason in COMPOSITE_RULES:
            span = match_composite_tokens(tokens, pattern)
            if span is None:
                continue
            if window_equals_allowlisted(tokens, span):
                continue
            findings.append(Finding(
                kind=kind,
                code=code,
                path=str(path),
                line=i,
                col=1,
                message=f"{reason} — matched composite pattern '{pattern}' (token-based).",
                excerpt=line.strip()[:240],
            ))

        for kind, code, required, win, reason in NEAR_WINDOW_RULES:
            span = match_near_window(tokens, required, win)
            if span is None:
                continue
            if window_equals_allowlisted(tokens, span):
                continue
            findings.append(Finding(
                kind=kind,
                code=code,
                path=str(path),
                line=i,
                col=1,
                message=f"{reason} — near-window match {sorted(required)} within {win} tokens.",
                excerpt=line.strip()[:240],
            ))

    return findings

def scan_semantic_path_ops(path: Path, lines: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    allowlisted = path.name in OS_PATH_ALLOWLIST_FILES
    for i, line in enumerate(lines, start=1):
        l = line.strip()
        if any(tok in l for tok in SEMANTIC_PATH_TOKENS):
            if allowlisted:
                continue
            if OS_PATH_WAIVER_TAG in l:
                continue
            findings.append(Finding(
                kind="ERROR",
                code="SEMANTIC_PATH_OP",
                path=str(path),
                line=i,
                col=1,
                message=(
                    "Semantic path op detected outside canonical modules. "
                    "Route through WorldAdapter normalization/resolution. "
                    f"If truly OS-only, add waiver: #{OS_PATH_WAIVER_TAG}: <reason>"
                ),
                excerpt=line.strip()[:240],
            ))
    return findings


# -----------------------------
# Unused symbol heuristic (unchanged, WARN tier)
# -----------------------------

class _DefCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.defs: dict[str, tuple[int, int, str]] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if isinstance(getattr(node, "parent", None), ast.Module):
            self.defs[node.name] = (node.lineno, node.col_offset + 1, "function")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if isinstance(getattr(node, "parent", None), ast.Module):
            self.defs[node.name] = (node.lineno, node.col_offset + 1, "class")
        self.generic_visit(node)

def _attach_parents(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            setattr(child, "parent", node)

def collect_defs(path: Path, text: str) -> dict[str, tuple[int, int, str]]:
    try:
        tree = ast.parse(text, filename=str(path))
        _attach_parents(tree)
        c = _DefCollector()
        c.visit(tree)
        return c.defs
    except SyntaxError:
        return {}

def collect_name_uses(text: str) -> set[str]:
    return set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", text))

def scan_unused_symbols(all_files: dict[Path, str]) -> list[Finding]:
    defs: dict[Path, dict[str, tuple[int, int, str]]] = {}
    for p, t in all_files.items():
        defs[p] = collect_defs(p, t)

    global_uses: set[str] = set()
    for t in all_files.values():
        global_uses |= collect_name_uses(t)

    findings: list[Finding] = []
    for p, d in defs.items():
        for name, (line, col, kind) in d.items():
            if name.startswith("_") or name.startswith("__"):
                continue
            if name not in global_uses:
                findings.append(Finding(
                    kind="WARN",
                    code="UNUSED_SYMBOL",
                    path=str(p),
                    line=line,
                    col=col,
                    message=f"Top-level {kind} '{name}' appears unused across repo (heuristic).",
                    excerpt=f"{kind} {name}",
                ))
    return findings


# -----------------------------
# Output
# -----------------------------

def format_findings(findings: list[Finding]) -> str:
    out: list[str] = []
    # Sort errors first, then stable
    for f in sorted(findings, key=lambda x: (x.kind != "ERROR", x.path, x.line, x.col, x.code)):
        out.append(f"{f.kind} {f.code} {f.path}:{f.line}:{f.col} — {f.message}\n    {f.excerpt}")
    return "\n".join(out)

def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_ROOT
    py_files = list(iter_python_files(root))

    all_text: dict[Path, str] = {}
    findings: list[Finding] = []

    for p in py_files:
        t = read_text(p)
        all_text[p] = t
        lines = t.splitlines()
        findings.extend(scan_direct_terms(p, lines))
        findings.extend(scan_composites(p, lines))
        findings.extend(scan_semantic_path_ops(p, lines))

    findings.extend(scan_unused_symbols(all_text))

    errors = [f for f in findings if f.kind == "ERROR"]
    warns = [f for f in findings if f.kind == "WARN"]

    print("arch_lint v2.3 (token-based)")
    print(f"Scanned: {len(py_files)} python files under {root}")
    print(f"Errors: {len(errors)}  Warnings: {len(warns)}")
    print("")
    if findings:
        print(format_findings(findings))

    return 1 if errors else 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
