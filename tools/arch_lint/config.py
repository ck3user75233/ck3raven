"""
arch_lint v2.35 — Configuration.

Runtime configuration and CLI-derived settings.
For pattern definitions, see patterns.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class LintConfig:
    """Runtime configuration for arch_lint."""
    
    root: Path
    
    # File extensions
    python_exts: tuple[str, ...] = (".py",)
    docs_exts: tuple[str, ...] = (".md", ".rst", ".txt", ".adoc")
    
    # Directory exclusions
    exclude_dirs: tuple[str, ...] = (
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        "node_modules",
        "dist",
        "build",
        "archive",
        ".wip",
    )
    
    # Feature toggles
    warn_unused: bool = True
    warn_deprecated_symbols: bool = True
    check_comments: bool = True
    check_enforcement_sites: bool = True
    check_forbidden_filenames: bool = True
    check_path_apis: bool = True
    check_io: bool = True
    check_mutators: bool = True
    
    # Severity settings
    unused_severity: str = "WARN"
    concept_explosion_is_error: bool = True
    
    # Context suppression
    suppress_in_banned_context: bool = True
    
    # Output settings
    json_output: bool = False
    errors_only: bool = False
    
    # Unused symbol allowlists
    unused_name_allowlist_prefixes: tuple[str, ...] = ("_", "test_")
    unused_name_allowlist_exact: tuple[str, ...] = ()


def should_exclude_path(cfg: LintConfig, path: Path) -> bool:
    """Check if path should be excluded from scanning."""
    return any(d in path.parts for d in cfg.exclude_dirs)


def in_allowlist(path_str: str, allow: tuple[str, ...] | list[str]) -> bool:
    """Check if path matches any allowlist pattern."""
    # Normalize to forward slashes for cross-platform matching
    path_norm = path_str.replace("\\", "/")
    return any(s in path_norm for s in allow)
