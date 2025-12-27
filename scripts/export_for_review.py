#!/usr/bin/env python3
"""
Export ck3raven codebase to a single markdown file for code review.

Creates a comprehensive document with:
- Full directory tree at the top
- Each file's content with relative path header
- Excludes binary files, __pycache__, .git, etc.

Usage:
    python scripts/export_for_review.py [--output path/to/output.md]
"""

import argparse
import os
from datetime import datetime
from pathlib import Path

# Files/directories to exclude
EXCLUDE_DIRS = {
    ".git",
    ".githooks", 
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    ".mypy_cache",
    "node_modules",
    ".vscode",
    "*.egg-info",
}

EXCLUDE_FILES = {
    ".DS_Store",
    "Thumbs.db",
    "*.pyc",
    "*.pyo",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.log",
    "*.jsonl",
}

# File extensions to include (code files)
INCLUDE_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".sql",
    ".sh",
    ".ps1",
    ".bat",
    ".cfg",
    ".ini",
    ".gitignore",
}

# Files to include regardless of extension
INCLUDE_FILES = {
    "LICENSE",
    "Makefile",
    "Dockerfile",
    ".gitignore",
    ".pre-commit-config.yaml",
}


def should_exclude_dir(dir_name: str) -> bool:
    """Check if directory should be excluded."""
    for pattern in EXCLUDE_DIRS:
        if pattern.startswith("*"):
            if dir_name.endswith(pattern[1:]):
                return True
        elif dir_name == pattern:
            return True
    return False


def should_include_file(file_path: Path) -> bool:
    """Check if file should be included."""
    name = file_path.name
    
    # Check exclude patterns
    for pattern in EXCLUDE_FILES:
        if pattern.startswith("*"):
            if name.endswith(pattern[1:]):
                return False
        elif name == pattern:
            return False
    
    # Check include by name
    if name in INCLUDE_FILES:
        return True
    
    # Check include by extension
    suffix = file_path.suffix.lower()
    if suffix in INCLUDE_EXTENSIONS:
        return True
    
    # Special case: files without extension that look like scripts
    if not suffix and file_path.is_file():
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline()
                if first_line.startswith("#!"):
                    return True
        except Exception:
            pass
    
    return False


def build_tree(root: Path, prefix: str = "") -> list[str]:
    """Build directory tree as list of strings."""
    lines = []
    
    entries = sorted(root.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    
    # Filter out excluded directories
    entries = [e for e in entries if not (e.is_dir() and should_exclude_dir(e.name))]
    
    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        
        if entry.is_dir():
            lines.append(f"{prefix}{connector}{entry.name}/")
            extension = "    " if is_last else "│   "
            lines.extend(build_tree(entry, prefix + extension))
        else:
            if should_include_file(entry):
                lines.append(f"{prefix}{connector}{entry.name}")
    
    return lines


def collect_files(root: Path) -> list[Path]:
    """Collect all files to include, sorted by path."""
    files = []
    
    for dirpath, dirnames, filenames in os.walk(root):
        # Modify dirnames in-place to skip excluded directories
        dirnames[:] = [d for d in dirnames if not should_exclude_dir(d)]
        
        for filename in filenames:
            file_path = Path(dirpath) / filename
            if should_include_file(file_path):
                files.append(file_path)
    
    return sorted(files, key=lambda p: str(p).lower())


def read_file_content(file_path: Path) -> str | None:
    """Read file content, return None if binary or unreadable."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, "r", encoding="latin-1") as f:
                return f.read()
        except Exception:
            return None
    except Exception:
        return None


def get_language_hint(file_path: Path) -> str:
    """Get markdown code fence language hint."""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
        ".sql": "sql",
        ".sh": "bash",
        ".ps1": "powershell",
        ".bat": "batch",
        ".toml": "toml",
        ".txt": "text",
        ".ini": "ini",
        ".cfg": "ini",
    }
    return ext_map.get(file_path.suffix.lower(), "")


def export_to_markdown(root: Path, output_path: Path) -> None:
    """Export entire codebase to markdown."""
    
    # Build directory tree
    tree_lines = build_tree(root)
    
    # Collect files
    files = collect_files(root)
    
    # Generate markdown
    lines = [
        f"# ck3raven Codebase Export",
        f"",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"**Root:** `{root}`",
        f"",
        f"**Files included:** {len(files)}",
        f"",
        f"---",
        f"",
        f"## Directory Structure",
        f"",
        f"```",
        f"{root.name}/",
    ]
    
    lines.extend(tree_lines)
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## File Contents")
    lines.append("")
    
    for file_path in files:
        rel_path = file_path.relative_to(root)
        content = read_file_content(file_path)
        
        if content is None:
            lines.append(f"### `{rel_path}`")
            lines.append("")
            lines.append("*[Binary or unreadable file]*")
            lines.append("")
            lines.append("---")
            lines.append("")
            continue
        
        lang = get_language_hint(file_path)
        
        lines.append(f"### `{rel_path}`")
        lines.append("")
        lines.append(f"```{lang}")
        lines.append(content.rstrip())
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    print(f"[OK] Exported {len(files)} files to: {output_path}")
    print(f"     File size: {output_path.stat().st_size / 1024:.1f} KB")


def main():
    parser = argparse.ArgumentParser(description="Export ck3raven codebase to markdown")
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output file path (default: ck3raven_export_YYYYMMDD.md in AI Workspace)"
    )
    parser.add_argument(
        "--root", "-r",
        type=Path,
        default=None,
        help="Root directory (default: ck3raven project root)"
    )
    
    args = parser.parse_args()
    
    # Determine root
    if args.root:
        root = args.root.resolve()
    else:
        # Find ck3raven root from script location
        script_dir = Path(__file__).resolve().parent
        root = script_dir.parent  # scripts/ -> ck3raven/
    
    if not root.exists():
        print(f"[ERROR] Root directory not found: {root}")
        return 1
    
    # Determine output path
    if args.output:
        output_path = args.output.resolve()
    else:
        date_str = datetime.now().strftime("%Y%m%d")
        output_path = root.parent / f"ck3raven_export_{date_str}.md"
    
    export_to_markdown(root, output_path)
    return 0


if __name__ == "__main__":
    exit(main())
