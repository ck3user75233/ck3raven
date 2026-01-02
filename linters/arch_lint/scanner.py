from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class SourceFile:
    path: Path
    text: str
    lines: list[str]

def load_source(path: Path) -> SourceFile:
    text = path.read_text(encoding="utf-8", errors="replace")
    return SourceFile(path=path, text=text, lines=text.splitlines())

def get_line(lines: list[str], line_no: int) -> str:
    if line_no <= 0 or line_no > len(lines):
        return ""
    return lines[line_no-1]

def in_banned_context(line_text: str, keywords: tuple[str, ...]) -> bool:
    lc = line_text.lower()
    return any(k in lc for k in keywords)
