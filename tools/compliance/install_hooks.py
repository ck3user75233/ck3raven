"""
Git Hook Installer for Protected Files.

Installs a pre-commit hook that checks staged files against the
protected files manifest. Protected files require HAT authorization
to modify.

Usage:
    python -m tools.compliance.install_hooks
    python tools/compliance/install_hooks.py

See docs/PROTECTED_FILES_AND_HAT.md for architecture details.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

# The pre-commit hook script content
HOOK_SCRIPT = """#!/bin/sh
# ck3raven Protected Files Pre-Commit Hook
# Installed by: python -m tools.compliance.install_hooks
#
# This hook checks if any staged files are in the protected files manifest.
# Protected files require HAT (Human Authorization Token) to modify.
# See docs/PROTECTED_FILES_AND_HAT.md

# Run the check-staged command
python -m tools.compliance.protected_files check-staged
exit_code=$?

if [ $exit_code -ne 0 ]; then
    echo ""
    echo "[ck3raven] Commit blocked by protected files check."
    echo "[ck3raven] See docs/PROTECTED_FILES_AND_HAT.md for details."
    exit 1
fi

exit 0
"""

HOOK_MARKER = "# ck3raven Protected Files Pre-Commit Hook"


def get_repo_root() -> Path:
    """Find the repo root by looking for .git directory."""
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").is_dir():
            return parent
    raise RuntimeError("Could not find .git directory")


def install_pre_commit_hook(force: bool = False) -> bool:
    """
    Install the pre-commit hook for protected files checking.

    Args:
        force: If True, overwrite existing hook even if not ck3raven's

    Returns:
        True if hook was installed, False if skipped
    """
    repo_root = get_repo_root()
    hooks_dir = repo_root / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    hook_path = hooks_dir / "pre-commit"

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8", errors="replace")

        # Already installed
        if HOOK_MARKER in existing:
            print(f"[ck3raven] Pre-commit hook already installed at {hook_path}")
            return False

        # Different hook exists
        if not force:
            print(f"[ck3raven] WARNING: Existing pre-commit hook found at {hook_path}")
            print("[ck3raven] Use --force to overwrite, or manually add the check.")
            print("[ck3raven] To add manually, put this in your pre-commit hook:")
            print()
            print("    python -m tools.compliance.protected_files check-staged")
            print()
            return False

        print(f"[ck3raven] Overwriting existing pre-commit hook (--force)")

    # Write hook
    hook_path.write_text(HOOK_SCRIPT, encoding="utf-8")

    # Make executable (Unix/Mac)
    if os.name != "nt":
        current_mode = hook_path.stat().st_mode
        hook_path.chmod(current_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    print(f"[ck3raven] Pre-commit hook installed at {hook_path}")
    return True


def uninstall_pre_commit_hook() -> bool:
    """
    Remove the ck3raven pre-commit hook.

    Only removes if the hook was installed by ck3raven (contains marker).

    Returns:
        True if removed, False if not found or not ck3raven's hook
    """
    repo_root = get_repo_root()
    hook_path = repo_root / ".git" / "hooks" / "pre-commit"

    if not hook_path.exists():
        print("[ck3raven] No pre-commit hook found.")
        return False

    existing = hook_path.read_text(encoding="utf-8", errors="replace")
    if HOOK_MARKER not in existing:
        print("[ck3raven] Pre-commit hook exists but was not installed by ck3raven.")
        print("[ck3raven] Not removing. Manually edit if needed.")
        return False

    hook_path.unlink()
    print(f"[ck3raven] Pre-commit hook removed from {hook_path}")
    return True


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] == "install":
        force = "--force" in args
        install_pre_commit_hook(force=force)

    elif args[0] == "uninstall":
        uninstall_pre_commit_hook()

    elif args[0] == "help":
        print("Usage: python -m tools.compliance.install_hooks <command>")
        print()
        print("Commands:")
        print("  install [--force]  Install git pre-commit hook")
        print("  uninstall          Remove git pre-commit hook")
        print("  help               Show this help")

    else:
        print(f"Unknown command: {args[0]}")
        print("Use 'help' for usage information.")
        sys.exit(1)
