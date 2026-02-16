"""
arch_lint v2.35 â€” File scanning and source loading.

Handles:
- Directory walking with exclusions
- Source file loading
- Python tokenization (for precise token extraction)
"""

from __future__ import annotations

import re
import tokenize
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Iterator

from .config import LintConfig, should_exclude_path


@dataclass(frozen=True)
class SourceFile:
    """A loaded source file with content."""
    path: Path
    text: str
    lines: list[str]
    
    @property
    def is_python(self) -> bool:
        return self.path.suffix == ".py"
    
    @property
    def is_doc(self) -> bool:
        return self.path.suffix.lower() in {".md", ".txt", ".rst", ".adoc"}


def load_source(path: Path) -> SourceFile:
    """Load a single source file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return SourceFile(path=path, text=text, lines=text.splitlines())


def iter_files(cfg: LintConfig) -> Iterator[Path]:
    """Iterate over all relevant files under root (or explicit list)."""
    # If explicit_files provided, use that instead of scanning
    if cfg.explicit_files is not None:
        for path in cfg.explicit_files:
            if path.is_file():
                yield path
        return
    
    all_exts = set(cfg.python_exts) | set(cfg.docs_exts)
    
    for path in cfg.root.rglob("*"):
        if not path.is_file():
            continue
        if should_exclude_path(cfg, path):
            continue
        if path.suffix in all_exts:
            yield path


def load_sources(cfg: LintConfig) -> list[SourceFile]:
    """Load all source files under root."""
    sources: list[SourceFile] = []
    for path in iter_files(cfg):
        try:
            sources.append(load_source(path))
        except Exception:
            pass  # Skip unreadable files
    return sources


def get_line(lines: list[str], line_no: int) -> str:
    """Get line by 1-based line number."""
    if line_no <= 0 or line_no > len(lines):
        return ""
    return lines[line_no - 1]


# =============================================================================
# Tokenization
# =============================================================================

# Regex for camelCase splitting
_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def tokenize_line(line: str, strip_comments: bool = False) -> list[str]:
    """
    Tokenize robustly across snake_case, kebab-case, camelCase.
    Returns lowercase tokens.
    
    If strip_comments=True, removes Python comment content before tokenizing.
    """
    if strip_comments and "#" in line:
        # Strip comment portion (but keep if # is inside a string - imperfect but good enough)
        line = line.split("#")[0]
    
    # Split camelCase: ActiveLocalMods -> Active Local Mods
    line2 = _CAMEL_SPLIT.sub(" ", line)
    # Normalize separators to spaces
    line2 = _NON_ALNUM.sub(" ", line2)
    # Lowercase and split
    return [t for t in line2.lower().split() if t]


def tokenize_window(lines: list[str], strip_comments: bool = False) -> list[str]:
    """Tokenize multiple lines into a single token list."""
    tokens: list[str] = []
    for line in lines:
        tokens.extend(tokenize_line(line, strip_comments=strip_comments))
    return tokens


def python_tokenize_names(path: Path) -> Iterator[tuple[str, int, int]]:
    """
    Use Python's tokenize module to extract NAME tokens.
    This skips strings and comments automatically.
    
    Yields: (token_string, line, col)
    """
    try:
        with path.open("rb") as f:
            for tok in tokenize.tokenize(f.readline):
                if tok.type == tokenize.NAME:
                    yield tok.string, tok.start[0], tok.start[1]
    except (tokenize.TokenError, SyntaxError, UnicodeDecodeError):
        pass  # Skip files that can't be tokenized


# =============================================================================
# Context Detection
# =============================================================================

def in_banned_context(line_text: str, keywords: list[str]) -> bool:
    """Check if line contains banned-context keywords (for suppression)."""
    lc = line_text.lower()
    return any(k in lc for k in keywords)


def contains_allowlisted_raw(line: str, substrings: list[str]) -> bool:
    """Check if line contains an allowlisted raw substring."""
    lc = line.lower()
    return any(s in lc for s in substrings)


def is_deprecated_line(line_text: str, hints: list[str]) -> bool:
    """Check if line contains deprecation hints."""
    lc = line_text.lower()
    return any(h in lc for h in hints)


# SQL keywords that indicate the line is SQL, not code logic
_SQL_CONTEXT_KEYWORDS = frozenset({
    "insert into", "select ", "update ", "delete from", "create table",
    "alter table", "values (", "values(", "from ", "where ", "join ",
    "content_root", "_root_hash", "content_version",
})

# Phrases that contain banned word patterns but are benign
_BENIGN_PHRASES = frozenset({
    "root cause",
    "root causes",
})


def is_sql_context(window_text: str) -> bool:
    """Check if the window looks like SQL (column names, queries).
    
    Used to suppress false positives like 'content_root_hash' triggering 'mod%root'.
    """
    lc = window_text.lower()
    return any(kw in lc for kw in _SQL_CONTEXT_KEYWORDS)


def has_benign_phrase(window_text: str) -> bool:
    """Check if window contains benign phrases that shouldn't trigger patterns.
    
    E.g., 'root causes' should not trigger 'mod%root'.
    """
    lc = window_text.lower()
    return any(phrase in lc for phrase in _BENIGN_PHRASES)
