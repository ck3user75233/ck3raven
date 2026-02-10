"""
Protected Files Module - HAT-gated file protection.

This module manages the protected files manifest and provides
functions for checking whether files require HAT authorization.

Architecture:
    Manifest: policy/protected_files.json (self-protected by hardcoded rule)
    HAT approval: Ephemeral — extension signs, MCP consumes (see tokens.py)
    Gate check: contract_v1.py open_contract() calls check_edits_against_manifest()
    Defense-in-depth: Pre-commit hook (check_staged) warns about protected files

Authority: docs/PROTECTED_FILES_AND_HAT.md
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# =============================================================================
# CONSTANTS
# =============================================================================

# Relative path to the manifest within the repo
MANIFEST_REL_PATH = "policy/protected_files.json"

# The manifest itself is ALWAYS protected (hardcoded, cannot be removed)
_HARDCODED_PROTECTED = frozenset({MANIFEST_REL_PATH})

# Current manifest schema version
MANIFEST_SCHEMA_VERSION = "1"


# =============================================================================
# MANIFEST ENTRY
# =============================================================================

@dataclass
class ProtectedEntry:
    """A single entry in the protected files manifest."""
    path: str           # Relative path from repo root
    entry_type: str     # "file" or "folder"
    sha256: str         # SHA-256 hash of current content (empty for folders)
    added_at: str       # ISO-8601 timestamp
    reason: str         # Why this file is protected

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "type": self.entry_type,
            "sha256": self.sha256,
            "added_at": self.added_at,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProtectedEntry":
        return cls(
            path=data["path"],
            entry_type=data.get("type", "file"),
            sha256=data.get("sha256", ""),
            added_at=data.get("added_at", ""),
            reason=data.get("reason", ""),
        )


# =============================================================================
# MANIFEST I/O
# =============================================================================

def _get_repo_root() -> Path:
    """Get ck3raven repo root. Works from any file in the repo."""
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").exists():
            return parent
    # Fallback: assume tools/compliance/ is 2 levels deep
    return Path(__file__).resolve().parent.parent.parent


def get_manifest_path() -> Path:
    """Get absolute path to the protected files manifest."""
    return _get_repo_root() / MANIFEST_REL_PATH


def load_manifest() -> list[ProtectedEntry]:
    """
    Load the protected files manifest.

    Returns:
        List of ProtectedEntry objects. Empty list if manifest doesn't exist.
    """
    manifest_path = get_manifest_path()
    if not manifest_path.exists():
        return []

    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Validate schema version
    version = data.get("schema_version", "0")
    if version != MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"Manifest schema version {version} != expected {MANIFEST_SCHEMA_VERSION}"
        )

    return [ProtectedEntry.from_dict(e) for e in data.get("entries", [])]


def save_manifest(entries: list[ProtectedEntry]) -> Path:
    """
    Save the protected files manifest.

    Args:
        entries: List of ProtectedEntry objects to save.

    Returns:
        Path to the saved manifest file.
    """
    manifest_path = get_manifest_path()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "entries": [e.to_dict() for e in entries],
    }
    manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return manifest_path


# =============================================================================
# PROTECTION CHECKS
# =============================================================================

def is_protected(rel_path: str) -> bool:
    """
    Check if a relative path is protected.

    Checks:
    1. Hardcoded paths (manifest itself)
    2. Manifest file entries (exact match)
    3. Manifest folder entries (prefix match)

    Args:
        rel_path: Path relative to repo root (forward slashes)

    Returns:
        True if the path is protected
    """
    # Normalize path separators
    normalized = rel_path.replace("\\", "/")

    # Check hardcoded
    if normalized in _HARDCODED_PROTECTED:
        return True

    # Check manifest entries
    entries = load_manifest()
    for entry in entries:
        entry_path = entry.path.replace("\\", "/")
        if entry.entry_type == "file":
            if normalized == entry_path:
                return True
        elif entry.entry_type == "folder":
            # Folder protection: any path under this folder
            folder = entry_path.rstrip("/") + "/"
            if normalized.startswith(folder) or normalized == entry_path.rstrip("/"):
                return True

    return False


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_all_hashes() -> list[tuple[str, str, str]]:
    """
    Verify SHA-256 hashes of all protected files.

    Returns:
        List of (path, expected_hash, actual_hash) for mismatches.
        Empty list means all hashes match.
    """
    entries = load_manifest()
    repo_root = _get_repo_root()
    mismatches = []

    for entry in entries:
        if entry.entry_type != "file" or not entry.sha256:
            continue
        file_path = repo_root / entry.path
        if not file_path.exists():
            mismatches.append((entry.path, entry.sha256, "FILE_NOT_FOUND"))
            continue
        actual = compute_file_hash(file_path)
        if actual != entry.sha256:
            mismatches.append((entry.path, entry.sha256, actual))

    return mismatches


def check_edits_against_manifest(
    edit_paths: list[str],
) -> list[str]:
    """
    Check if any edit paths touch protected files.

    This is called by open_contract() to determine if HAT is required.

    Args:
        edit_paths: List of relative paths from work_declaration edits

    Returns:
        List of protected paths that would be touched.
        Empty list means no HAT required.
    """
    protected_paths = []
    for path in edit_paths:
        if is_protected(path):
            protected_paths.append(path)
    return protected_paths


# ============================================================================
# Git Pre-Commit Check (CLI entry point)
# ============================================================================

def check_staged() -> int:
    """
    Check git staged files against the protected files manifest.

    Called by the git pre-commit hook. Returns 0 if commit is allowed,
    1 if protected files are staged without authorization.

    Defense-in-depth: the real enforcement happens at contract-open time
    (ephemeral HAT approval). This hook is a safety net for direct
    git commits that bypass the contract system.

    The commit is allowed if CK3RAVEN_PROTECTED_OK=1 is set in the
    environment (set automatically by ck3_git when committing under
    an active contract that consumed a HAT approval).

    Returns:
        0 = commit allowed, 1 = blocked
    """
    repo_root = _get_repo_root()

    # Get list of staged files
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True, text=True, cwd=str(repo_root),
    )
    if result.returncode != 0:
        print(f"[ck3raven] ERROR: git diff failed: {result.stderr.strip()}")
        return 1

    staged_files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    if not staged_files:
        return 0  # Nothing staged

    # Check each staged file against manifest
    protected_staged = []
    for f in staged_files:
        normalized = f.replace("\\", "/")
        if is_protected(normalized):
            protected_staged.append(normalized)

    if not protected_staged:
        return 0  # No protected files staged

    # Check for authorization via environment variable
    # Set by ck3_git tool when committing under a HAT-authorized contract
    if os.environ.get("CK3RAVEN_PROTECTED_OK") == "1":
        print(f"[ck3raven] OK: {len(protected_staged)} protected file(s) staged under authorized contract.")
        return 0

    # Blocked — print warning
    print("[ck3raven] BLOCKED: Protected files are staged for commit:")
    for p in protected_staged:
        print(f"  - {p}")
    print()
    print("Protected files require HAT approval via the contract system.")
    print("If this is intentional, use: git commit --no-verify")
    print("Or set CK3RAVEN_PROTECTED_OK=1 in your environment.")
    return 1


# ============================================================================
# CLI Entry Point
# ============================================================================

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] == "help":
        print("Usage: python -m tools.compliance.protected_files <command>")
        print()
        print("Commands:")
        print("  check-staged  Check git staged files against protected manifest")
        print("  list          List all protected entries")
        print("  verify        Verify SHA256 hashes of all protected files")
        sys.exit(0)

    cmd = args[0]

    if cmd == "check-staged":
        sys.exit(check_staged())

    elif cmd == "list":
        entries = load_manifest()
        if not entries:
            print("No protected entries.")
        else:
            print(f"{len(entries)} protected entries:")
            for e in entries:
                hash_display = e.sha256[:16] + "..." if e.sha256 else "(no hash)"
                print(f"  [{e.entry_type}] {e.path}  {hash_display}  ({e.reason})")

    elif cmd == "verify":
        mismatches = verify_all_hashes()
        entries = load_manifest()
        if not mismatches:
            print(f"All {len(entries)} entries verified OK.")
        else:
            print(f"{len(mismatches)} mismatch(es):")
            for fpath, expected, actual in mismatches:
                print(f"  {fpath}: expected={expected[:16]}... actual={actual[:16]}...")
            sys.exit(1)

    else:
        print(f"Unknown command: {cmd}")
        print("Use 'help' for usage information.")
        sys.exit(1)