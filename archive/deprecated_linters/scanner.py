from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

@dataclass(frozen=True)
class SourceFile:
    path: Path
    text: str
    lines: list[str]

# Skip patterns for directory/file exclusion
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".wip", "archive"}
SKIP_FILES = {"__pycache__"}

def is_doc_file(path: Path) -> bool:
    """Check if file is documentation (markdown, txt, rst)."""
    return path.suffix.lower() in {".md", ".txt", ".rst"}

def load_source(path: Path) -> SourceFile:
    """Load a single source file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return SourceFile(path=path, text=text, lines=text.splitlines())

def load_sources(root: Path) -> list[SourceFile]:
    """Recursively load all Python and doc files under root."""
    sources: list[SourceFile] = []
    for item in _walk_files(root):
        if item.suffix == ".py" or is_doc_file(item):
            try:
                sources.append(load_source(item))
            except Exception:
                pass  # Skip unreadable files
    return sources

def _walk_files(root: Path) -> Iterator[Path]:
    """Walk directory tree, skipping excluded dirs."""
    for item in root.iterdir():
        if item.is_dir():
            if item.name in SKIP_DIRS:
                continue
            yield from _walk_files(item)
        elif item.is_file():
            yield item

def get_line(lines: list[str], line_no: int) -> str:
    """Get line by 1-based line number."""
    if line_no <= 0 or line_no > len(lines):
        return ""
    return lines[line_no-1]

def in_banned_context(line_text: str, keywords: tuple[str, ...]) -> bool:
    """Check if line contains any banned-context keywords (for suppression)."""
    lc = line_text.lower()
    return any(k in lc for k in keywords)