"""
Linter Lock System - Phase 1.5 Component A

Hash-locks the arch_lint ruleset to ensure deterministic lint behavior.
The lock must be verified before any lint run; outputs include lock_hash watermark.

Scope: arch_lint ONLY (Ruff is out of scope for Phase 1.5)

Usage:
    # Generate initial lock (to policy/locks/)
    python -m tools.compliance.linter_lock create
    
    # Verify current state against lock
    python -m tools.compliance.linter_lock verify
    
    # Show lock status
    python -m tools.compliance.linter_lock status
    
    # Create proposed lock (to artifacts/locks/proposed/)
    python -m tools.compliance.linter_lock propose
    
    # Diff active vs proposed lock
    python -m tools.compliance.linter_lock diff

Authority: docs/PHASE_1_5_AGENT_INSTRUCTION.md
"""

from __future__ import annotations

import glob
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# =============================================================================
# Configuration
# =============================================================================

LOCK_SCHEMA_VERSION = "v1"

# Canonical lock locations
# Active lock (human-approved only)
ACTIVE_LOCK_RELPATH = "policy/locks/linter.lock.json"
# Proposed lock (agent-writable, pending human approval)
PROPOSED_LOCK_RELPATH = "artifacts/locks/proposed/linter.lock.json"

# Default manifests for arch_lint (Ruff explicitly excluded)
DEFAULT_MANIFESTS = [
    {
        "glob": "tools/arch_lint/*.py",
        "description": "arch_lint Python source files"
    },
    {
        "glob": "tools/arch_lint/requirements.txt",
        "description": "arch_lint dependencies"
    },
]

# Files to explicitly exclude (even if matched by glob)
EXCLUDE_PATTERNS = [
    "__pycache__",
    "*.pyc",
    ".git",
]


def _get_repo_root() -> Path:
    """Get the ck3raven repository root."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Could not find repository root")


def _get_lock_path() -> Path:
    """Get the canonical active lock file path."""
    return _get_repo_root() / ACTIVE_LOCK_RELPATH


def _get_proposed_lock_path() -> Path:
    """Get the proposed lock file path."""
    return _get_repo_root() / PROPOSED_LOCK_RELPATH


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class LockedFile:
    """A single file entry in the lock."""
    path: str           # Relative path (POSIX-style)
    sha256: str         # SHA256 hash of file content
    size_bytes: int     # File size in bytes
    
    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "LockedFile":
        return cls(
            path=data["path"],
            sha256=data["sha256"],
            size_bytes=data["size_bytes"],
        )


@dataclass
class LockManifest:
    """A glob pattern defining files to include in the lock."""
    glob: str           # Glob pattern relative to repo root
    description: str    # Human-readable description
    
    def to_dict(self) -> dict:
        return {
            "glob": self.glob,
            "description": self.description,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "LockManifest":
        return cls(
            glob=data["glob"],
            description=data["description"],
        )


@dataclass
class LinterLock:
    """
    The complete linter lock file.
    
    Hash-locks the arch_lint ruleset for deterministic verification.
    """
    schema_version: str
    lock_hash: str
    created_at: str
    created_by: str
    description: str
    manifests: list[LockManifest]
    files: list[LockedFile]
    file_count: int
    total_bytes: int
    
    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "lock_hash": self.lock_hash,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "description": self.description,
            "manifests": [m.to_dict() for m in self.manifests],
            "files": [f.to_dict() for f in self.files],
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "LinterLock":
        return cls(
            schema_version=data["schema_version"],
            lock_hash=data["lock_hash"],
            created_at=data["created_at"],
            created_by=data["created_by"],
            description=data["description"],
            manifests=[LockManifest.from_dict(m) for m in data["manifests"]],
            files=[LockedFile.from_dict(f) for f in data["files"]],
            file_count=data["file_count"],
            total_bytes=data["total_bytes"],
        )
    
    def save(self, path: Optional[Path] = None) -> Path:
        """Save lock to disk."""
        if path is None:
            path = _get_lock_path()
        
        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write with consistent formatting
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path
    
    @classmethod
    def load(cls, path: Optional[Path] = None) -> Optional["LinterLock"]:
        """Load lock from disk."""
        if path is None:
            path = _get_lock_path()
        
        if not path.exists():
            return None
        
        data = json.loads(path.read_text())
        return cls.from_dict(data)


# =============================================================================
# Hashing Functions
# =============================================================================

def hash_file(file_path: Path) -> str:
    """
    Compute SHA256 hash of file content.
    
    Args:
        file_path: Absolute path to file
    
    Returns:
        Hexadecimal SHA256 hash
    """
    content = file_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def compute_lock_hash(files: list[LockedFile]) -> str:
    """
    Compute deterministic lock hash from file list.
    
    Algorithm:
        1. Sort files by path
        2. Build canonical JSON array of {path, sha256} pairs
        3. Compute SHA256 of canonical JSON
    
    Args:
        files: List of locked files
    
    Returns:
        Lock hash (hexadecimal SHA256)
    """
    # Sort by path for deterministic ordering
    sorted_files = sorted(files, key=lambda f: f.path)
    
    # Build canonical JSON (no whitespace, sorted keys)
    canonical_data = [
        {"path": f.path, "sha256": f.sha256}
        for f in sorted_files
    ]
    canonical_json = json.dumps(
        canonical_data,
        sort_keys=True,
        separators=(',', ':')
    )
    
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# =============================================================================
# Glob Expansion
# =============================================================================

def expand_globs(
    manifests: list[LockManifest],
    root: Optional[Path] = None,
) -> list[Path]:
    """
    Expand manifest globs to concrete file list.
    
    Args:
        manifests: List of glob patterns
        root: Repository root (auto-detected if None)
    
    Returns:
        Sorted list of absolute file paths
    """
    if root is None:
        root = _get_repo_root()
    
    files: set[Path] = set()
    
    for manifest in manifests:
        pattern = str(root / manifest.glob)
        matched = glob.glob(pattern, recursive=True)
        
        for match in matched:
            path = Path(match)
            
            # Skip excluded patterns
            skip = False
            for exclude in EXCLUDE_PATTERNS:
                if exclude in str(path):
                    skip = True
                    break
            
            if not skip and path.is_file():
                files.add(path)
    
    return sorted(files)


def _to_posix_relpath(path: Path, root: Path) -> str:
    """Convert path to POSIX-style relative path."""
    return path.relative_to(root).as_posix()


# =============================================================================
# Lock Creation
# =============================================================================

def create_lock(
    manifests: Optional[list[dict]] = None,
    created_by: str = "system",
    description: str = "arch_lint ruleset lock for ck3raven",
) -> LinterLock:
    """
    Create a new linter lock from current file state.
    
    Args:
        manifests: List of glob patterns (uses defaults if None)
        created_by: Attribution for lock creation
        description: Human-readable description
    
    Returns:
        New LinterLock object
    """
    root = _get_repo_root()
    
    # Use default manifests if not specified
    if manifests is None:
        manifest_objs = [LockManifest.from_dict(m) for m in DEFAULT_MANIFESTS]
    else:
        manifest_objs = [LockManifest.from_dict(m) for m in manifests]
    
    # Expand globs to file list
    file_paths = expand_globs(manifest_objs, root)
    
    # Hash each file
    locked_files: list[LockedFile] = []
    total_bytes = 0
    
    for file_path in file_paths:
        rel_path = _to_posix_relpath(file_path, root)
        file_hash = hash_file(file_path)
        size = file_path.stat().st_size
        
        locked_files.append(LockedFile(
            path=rel_path,
            sha256=file_hash,
            size_bytes=size,
        ))
        total_bytes += size
    
    # Compute lock hash
    lock_hash = compute_lock_hash(locked_files)
    
    return LinterLock(
        schema_version=LOCK_SCHEMA_VERSION,
        lock_hash=lock_hash,
        created_at=datetime.now().isoformat(),
        created_by=created_by,
        description=description,
        manifests=manifest_objs,
        files=locked_files,
        file_count=len(locked_files),
        total_bytes=total_bytes,
    )


def create_proposed_lock(
    output_path: Optional[Path] = None,
    created_by: str = "agent",
    description: str = "Proposed arch_lint lock (pending human approval)",
) -> tuple[LinterLock, Path]:
    """
    Create a proposed lock file for human review.
    
    Proposed locks are written to artifacts/locks/proposed/, NOT to policy/locks/.
    Promotion from proposed to active is a manual human action only.
    
    Args:
        output_path: Where to write (defaults to PROPOSED_LOCK_RELPATH)
        created_by: Attribution
        description: Human-readable description
    
    Returns:
        Tuple of (LinterLock, output_path)
    """
    if output_path is None:
        output_path = _get_proposed_lock_path()
    
    lock = create_lock(created_by=created_by, description=description)
    lock.save(output_path)
    
    return lock, output_path


# =============================================================================
# Lock Verification
# =============================================================================

@dataclass
class VerificationResult:
    """Result of lock verification."""
    valid: bool
    lock_hash: str              # Current computed hash
    expected_hash: str          # Hash from lock file
    mismatches: list[dict]      # Files that don't match
    missing: list[str]          # Files in lock but not on disk
    extra: list[str]            # Files on disk but not in lock
    message: str                # Human-readable summary
    
    def to_dict(self) -> dict:
        return asdict(self)


def verify_lock(lock_path: Optional[Path] = None) -> VerificationResult:
    """
    Verify current file state against stored lock.
    
    Args:
        lock_path: Path to lock file (uses default if None)
    
    Returns:
        VerificationResult with details
    """
    # Load existing lock
    lock = LinterLock.load(lock_path)
    
    if lock is None:
        return VerificationResult(
            valid=False,
            lock_hash="",
            expected_hash="",
            mismatches=[],
            missing=[],
            extra=[],
            message="Lock file not found",
        )
    
    root = _get_repo_root()
    
    # Track findings
    mismatches: list[dict] = []
    missing: list[str] = []
    
    # Check each file in lock
    lock_paths = {f.path for f in lock.files}
    current_files: list[LockedFile] = []
    
    for locked_file in lock.files:
        file_path = root / locked_file.path
        
        if not file_path.exists():
            missing.append(locked_file.path)
            continue
        
        # Compute current hash
        current_hash = hash_file(file_path)
        current_size = file_path.stat().st_size
        
        current_files.append(LockedFile(
            path=locked_file.path,
            sha256=current_hash,
            size_bytes=current_size,
        ))
        
        if current_hash != locked_file.sha256:
            mismatches.append({
                "path": locked_file.path,
                "expected": locked_file.sha256[:16] + "...",
                "actual": current_hash[:16] + "...",
            })
    
    # Check for extra files (new files matching globs)
    current_paths = expand_globs(lock.manifests, root)
    current_relpaths = {_to_posix_relpath(p, root) for p in current_paths}
    extra = sorted(current_relpaths - lock_paths)
    
    # Compute current lock hash
    current_lock_hash = compute_lock_hash(current_files) if current_files else ""
    
    # Determine validity
    valid = (
        len(mismatches) == 0 and
        len(missing) == 0 and
        len(extra) == 0 and
        current_lock_hash == lock.lock_hash
    )
    
    # Build message
    if valid:
        message = f"Lock verified: {lock.lock_hash[:16]}..."
    else:
        issues = []
        if mismatches:
            issues.append(f"{len(mismatches)} file(s) modified")
        if missing:
            issues.append(f"{len(missing)} file(s) missing")
        if extra:
            issues.append(f"{len(extra)} new file(s)")
        if current_lock_hash != lock.lock_hash:
            issues.append("hash mismatch")
        message = "Lock verification FAILED: " + ", ".join(issues)
    
    return VerificationResult(
        valid=valid,
        lock_hash=current_lock_hash,
        expected_hash=lock.lock_hash,
        mismatches=mismatches,
        missing=missing,
        extra=extra,
        message=message,
    )


# =============================================================================
# Lock Diffing
# =============================================================================

@dataclass
class LockDiff:
    """Deterministic diff between two locks."""
    active_hash: str
    proposed_hash: str
    hashes_match: bool
    added_files: list[str]      # In proposed but not in active
    removed_files: list[str]    # In active but not in proposed
    changed_files: list[dict]   # In both but different hash
    unchanged_count: int        # Files that match exactly
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    def summary(self) -> str:
        """Generate deterministic human-readable summary."""
        lines = [
            "=== Lock Diff Summary ===",
            f"Active lock hash:   {self.active_hash[:16]}...",
            f"Proposed lock hash: {self.proposed_hash[:16]}...",
            f"Hashes match: {self.hashes_match}",
            "",
        ]
        
        if self.hashes_match:
            lines.append("No changes detected.")
            return "\n".join(lines)
        
        lines.append(f"Unchanged files: {self.unchanged_count}")
        
        if self.added_files:
            lines.append(f"\nAdded files ({len(self.added_files)}):")
            for f in sorted(self.added_files):
                lines.append(f"  + {f}")
        
        if self.removed_files:
            lines.append(f"\nRemoved files ({len(self.removed_files)}):")
            for f in sorted(self.removed_files):
                lines.append(f"  - {f}")
        
        if self.changed_files:
            lines.append(f"\nChanged files ({len(self.changed_files)}):")
            for entry in sorted(self.changed_files, key=lambda x: x["path"]):
                lines.append(f"  ~ {entry['path']}")
                lines.append(f"      active:   {entry['active_hash'][:16]}...")
                lines.append(f"      proposed: {entry['proposed_hash'][:16]}...")
        
        return "\n".join(lines)


def diff_lock(
    active_lock: Optional[LinterLock] = None,
    proposed_lock: Optional[LinterLock] = None,
) -> LockDiff:
    """
    Compute deterministic diff between active and proposed locks.
    
    Args:
        active_lock: Active lock (loads from default if None)
        proposed_lock: Proposed lock (loads from default if None)
    
    Returns:
        LockDiff with added/removed/changed files and hash deltas
    
    Raises:
        FileNotFoundError: If either lock file doesn't exist
    """
    if active_lock is None:
        active_lock = LinterLock.load(_get_lock_path())
        if active_lock is None:
            raise FileNotFoundError(f"Active lock not found: {_get_lock_path()}")
    
    if proposed_lock is None:
        proposed_lock = LinterLock.load(_get_proposed_lock_path())
        if proposed_lock is None:
            raise FileNotFoundError(f"Proposed lock not found: {_get_proposed_lock_path()}")
    
    # Build file maps
    active_files = {f.path: f.sha256 for f in active_lock.files}
    proposed_files = {f.path: f.sha256 for f in proposed_lock.files}
    
    active_paths = set(active_files.keys())
    proposed_paths = set(proposed_files.keys())
    
    # Compute sets
    added_files = sorted(proposed_paths - active_paths)
    removed_files = sorted(active_paths - proposed_paths)
    
    # Check for changed files
    common_paths = active_paths & proposed_paths
    changed_files = []
    unchanged_count = 0
    
    for path in sorted(common_paths):
        if active_files[path] != proposed_files[path]:
            changed_files.append({
                "path": path,
                "active_hash": active_files[path],
                "proposed_hash": proposed_files[path],
            })
        else:
            unchanged_count += 1
    
    return LockDiff(
        active_hash=active_lock.lock_hash,
        proposed_hash=proposed_lock.lock_hash,
        hashes_match=active_lock.lock_hash == proposed_lock.lock_hash,
        added_files=added_files,
        removed_files=removed_files,
        changed_files=changed_files,
        unchanged_count=unchanged_count,
    )


def proposed_lock_exists() -> bool:
    """Check if a proposed lock file exists."""
    return _get_proposed_lock_path().exists()


def check_closure_eligibility() -> tuple[bool, str]:
    """
    Check if contract closure is allowed with current lock state.
    
    Rules:
        1. Active lock must exist
        2. If proposed lock exists, active lock must match working tree
           (i.e., proposed has been promoted or is stale)
        3. Working tree must match active lock
    
    Returns:
        Tuple of (eligible, reason)
    """
    # Check active lock exists
    active_lock = LinterLock.load(_get_lock_path())
    if active_lock is None:
        return False, "No active lock file found"
    
    # Verify working tree matches active lock
    verification = verify_lock(_get_lock_path())
    if not verification.valid:
        return False, f"Working tree does not match active lock: {verification.message}"
    
    # Check for unpromoted proposed lock
    if proposed_lock_exists():
        proposed_lock = LinterLock.load(_get_proposed_lock_path())
        if proposed_lock and proposed_lock.lock_hash != active_lock.lock_hash:
            return False, (
                "Proposed lock exists with different hash. "
                "Human must promote (copy to policy/locks/) or delete it before closure."
            )
    
    return True, f"Eligible for closure with lock {active_lock.lock_hash[:16]}..."


# =============================================================================
# CLI Interface
# =============================================================================

def main():
    """CLI entry point."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python -m tools.compliance.linter_lock <command>")
        print("Commands: create, verify, status, propose, diff, check-closure")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "create":
        print("Creating linter lock...")
        lock = create_lock()
        path = lock.save()
        print(f"Lock created: {path}")
        print(f"  Files: {lock.file_count}")
        print(f"  Total bytes: {lock.total_bytes}")
        print(f"  Lock hash: {lock.lock_hash[:16]}...")
    
    elif command == "verify":
        print("Verifying linter lock...")
        result = verify_lock()
        print(result.message)
        
        if result.mismatches:
            print("\nModified files:")
            for m in result.mismatches:
                print(f"  {m['path']}")
        
        if result.missing:
            print("\nMissing files:")
            for m in result.missing:
                print(f"  {m}")
        
        if result.extra:
            print("\nNew files (not in lock):")
            for e in result.extra:
                print(f"  {e}")
        
        sys.exit(0 if result.valid else 1)
    
    elif command == "status":
        lock = LinterLock.load()
        if lock is None:
            print("No lock file found")
            sys.exit(1)
        
        print(f"Lock file: {_get_lock_path()}")
        print(f"  Schema version: {lock.schema_version}")
        print(f"  Created at: {lock.created_at}")
        print(f"  Created by: {lock.created_by}")
        print(f"  Files: {lock.file_count}")
        print(f"  Total bytes: {lock.total_bytes}")
        print(f"  Lock hash: {lock.lock_hash[:16]}...")
        
        # Also run verification
        result = verify_lock()
        print(f"\nVerification: {'PASS' if result.valid else 'FAIL'}")
        
        # Check for proposed lock
        if proposed_lock_exists():
            proposed = LinterLock.load(_get_proposed_lock_path())
            if proposed:
                print(f"\nProposed lock exists: {_get_proposed_lock_path()}")
                print(f"  Proposed hash: {proposed.lock_hash[:16]}...")
    
    elif command == "propose":
        print("Creating proposed lock...")
        lock, path = create_proposed_lock()
        print(f"Proposed lock created: {path}")
        print(f"  Files: {lock.file_count}")
        print(f"  Lock hash: {lock.lock_hash[:16]}...")
        print()
        print("NOTE: This lock must be manually promoted to policy/locks/")
        print("      by a human reviewer before it becomes active.")
    
    elif command == "diff":
        try:
            diff = diff_lock()
            print(diff.summary())
        except FileNotFoundError as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    elif command == "check-closure":
        eligible, reason = check_closure_eligibility()
        print(f"Closure eligible: {eligible}")
        print(f"Reason: {reason}")
        sys.exit(0 if eligible else 1)
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
