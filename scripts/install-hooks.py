#!/usr/bin/env python3
"""
Install git hooks for ck3raven.

Run this after cloning the repository:
    python scripts/install-hooks.py

This installs:
- pre-commit: Blocks commits that fail policy validation
"""
from pathlib import Path
import shutil
import stat

REPO_ROOT = Path(__file__).parent.parent
HOOKS_DIR = REPO_ROOT / ".git" / "hooks"
HOOKS_SRC = REPO_ROOT / "scripts" / "hooks"


def install_hook(name: str) -> bool:
    """Install a hook from scripts/hooks/ to .git/hooks/."""
    src = HOOKS_SRC / name
    dst = HOOKS_DIR / name
    
    if not src.exists():
        print(f"❌ Hook source not found: {src}")
        return False
    
    # Copy the hook
    shutil.copy2(src, dst)
    
    # Make executable (Unix)
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    
    print(f"✅ Installed {name}")
    return True


def main():
    print("Installing git hooks for ck3raven...")
    print()
    
    if not HOOKS_DIR.exists():
        print(f"❌ Git hooks directory not found: {HOOKS_DIR}")
        print("   Are you running this from inside the ck3raven repository?")
        return 1
    
    # Create hooks source directory if needed
    HOOKS_SRC.mkdir(parents=True, exist_ok=True)
    
    # Install hooks
    success = True
    success &= install_hook("pre-commit")
    
    print()
    if success:
        print("✅ All hooks installed successfully")
        print()
        print("Policy enforcement is now ACTIVE.")
        print("Commits that fail validation will be blocked.")
        print()
        print("To bypass in emergencies: git commit --no-verify")
    else:
        print("⚠️  Some hooks failed to install")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
