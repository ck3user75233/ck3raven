from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

@dataclass(frozen=True)
class LintConfig:
    root: Path
    python_exts: tuple[str, ...] = (".py",)
    docs_exts: tuple[str, ...] = (".md", ".rst", ".txt", ".adoc")
    exclude_dirs: tuple[str, ...] = (
        ".git",".venv","venv","__pycache__","node_modules","dist","build",
        ".mypy_cache",".pytest_cache",
    )

    # Allowlists (tighten these to your actual module locations)
    worldadapter_paths: tuple[str, ...] = ("world_adapter.py", "worldadapter.py", "world_adapter/")
    handle_paths: tuple[str, ...] = ("db_handle", "fs_handle", "handles/", "handle_")

    # 2.2: Path arithmetic is allowed ONLY in WorldAdapter + handle modules.
    allow_path_arithmetic_in: tuple[str, ...] = (
        "world_adapter.py",
        "world_adapter/",
        "handles/",
        "fs_handle",
    )

    # 2.2: Raw IO is allowed ONLY in handle modules + WorldAdapter internals.
    allow_raw_io_in: tuple[str, ...] = (
        "world_adapter.py",
        "world_adapter/",
        "handles/",
        "fs_handle",
        "db_handle",
    )

    # 2.2: Mutators (writes) are allowed ONLY in builder/write-handle modules.
    allow_mutators_in: tuple[str, ...] = (
        "builder",
        "build/",
        "write_handle",
        "mutator_handle",
        "builder_handle",
    )

    suppress_in_banned_context: bool = True
    banned_context_keywords: tuple[str, ...] = (
        "banned","ban list","banned words","forbidden","do not use","avoid this",
        "anti-pattern","bad example","deprecated","legacy","warning","must not","never do",
        "banned patterns","banned ideas","forbidden patterns","anti-patterns",
    )

    warn_deprecated_symbols: bool = True
    warn_unused: bool = True
    unused_severity: str = "WARN"
    unused_name_allowlist_prefixes: tuple[str, ...] = ("_", "test_")
    unused_name_allowlist_exact: tuple[str, ...] = ()

    # Concept explosion rules
    concept_explosion_is_error: bool = True

    report_doc_banned_term_mentions: bool = True

def should_exclude_path(cfg: LintConfig, path: Path) -> bool:
    return any(d in path.parts for d in cfg.exclude_dirs)

def iter_repo_files(cfg: LintConfig) -> Iterable[Path]:
    for p in cfg.root.rglob("*"):
        if not p.is_file():
            continue
        if should_exclude_path(cfg, p):
            continue
        if p.suffix in cfg.python_exts or p.suffix in cfg.docs_exts:
            yield p

def is_python(cfg: LintConfig, path: Path) -> bool:
    return path.suffix in cfg.python_exts

def is_doc(cfg: LintConfig, path: Path) -> bool:
    return path.suffix in cfg.docs_exts

def in_allowlist(path_str: str, allow: tuple[str, ...]) -> bool:
    return any(s in path_str for s in allow)
