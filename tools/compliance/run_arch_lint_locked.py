"""
Locked arch_lint Runner - Phase 1.5 Component A5

Wrapper that:
1. Verifies the linter lock first
2. Runs arch_lint on scoped files (from --files or git diff)
3. Stamps the output with lock_hash watermark and files manifest

Usage:
    python -m tools.compliance.run_arch_lint_locked <contract_id> [options]
    
Options:
    --files FILE [FILE ...]    Lint only these specific files
    --files-from MANIFEST      Read file list from JSON manifest
    --base-commit SHA          Derive changed files from git diff HEAD..SHA
    
Output:
    artifacts/lint/<contract_id>.arch_lint.json  (structured with manifest)
    artifacts/lint/<contract_id>.arch_lint.txt   (human-readable)

Authority: docs/PHASE_1_5_AGENT_INSTRUCTION.md
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _get_repo_root() -> Path:
    """Get the ck3raven repository root."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Could not find repository root")


# Lint-eligible extensions (Python only for arch_lint)
LINT_ELIGIBLE_EXTENSIONS = frozenset({".py"})


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class LintReport:
    """Structured lint report with watermark and manifest."""
    contract_id: str
    lock_hash: str
    lock_verified: bool
    timestamp: str
    hash_algorithm: str
    tool_path: str
    tool_version: str
    exit_code: int
    stdout: str
    stderr: str
    error_count: int
    warning_count: int
    
    # Scoped lint manifest
    files_linted: list[str] = field(default_factory=list)
    base_commit: Optional[str] = None
    head_commit: Optional[str] = None
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    def watermark(self) -> str:
        """Return the cryptographic watermark line."""
        return f"WATERMARK: lock={self.lock_hash} alg={self.hash_algorithm} ts={self.timestamp}"


# =============================================================================
# Core Functions
# =============================================================================

def verify_lock_first() -> tuple[bool, str, str]:
    """
    Verify the linter lock before running arch_lint.
    
    Returns:
        Tuple of (verified, lock_hash, message)
    """
    from tools.compliance.linter_lock import verify_lock
    
    result = verify_lock()
    return result.valid, result.lock_hash if result.valid else result.expected_hash, result.message


def get_arch_lint_version() -> str:
    """Extract arch_lint version from its config."""
    try:
        from tools.arch_lint import __version__
        return f"v{__version__}"
    except Exception:
        return "unknown"


def get_changed_files_from_git(base_commit: str, repo_root: Path) -> list[Path]:
    """
    Get list of files changed between base_commit and HEAD.
    
    Uses git diff --name-only to get the list.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_commit, "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git diff failed: {result.stderr}")
        
        files = []
        for line in result.stdout.strip().split("\n"):
            if line:
                path = repo_root / line
                if path.exists() and path.is_file():
                    files.append(path)
        return files
    except Exception as e:
        raise RuntimeError(f"Failed to get changed files from git: {e}")


def filter_lint_eligible(files: list[Path]) -> list[Path]:
    """Filter to only lint-eligible files (Python)."""
    return [f for f in files if f.suffix in LINT_ELIGIBLE_EXTENSIONS]


def get_head_commit(repo_root: Path) -> Optional[str]:
    """Get current HEAD commit."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def run_arch_lint_locked(
    contract_id: str,
    files: Optional[list[Path]] = None,
    files_from: Optional[Path] = None,
    base_commit: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> LintReport:
    """
    Run arch_lint with lock verification and watermarking on scoped files.
    
    Args:
        contract_id: Contract ID to associate with this lint run
        files: Explicit file list to lint
        files_from: JSON manifest path with file list
        base_commit: Git commit SHA to diff against HEAD for file list
        output_dir: Where to write artifacts (default: artifacts/lint/)
    
    Returns:
        LintReport with results
    
    Raises:
        RuntimeError: If lock verification fails or no files to lint
    """
    repo_root = _get_repo_root()
    
    if output_dir is None:
        output_dir = repo_root / "artifacts" / "lint"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Step 1: Verify lock FIRST
    verified, lock_hash, message = verify_lock_first()
    
    if not verified:
        raise RuntimeError(f"Lock verification failed: {message}")
    
    # Step 2: Determine files to lint
    files_to_lint: list[Path] = []
    
    if files:
        files_to_lint = [Path(f).resolve() for f in files]
    elif files_from:
        manifest_path = Path(files_from)
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text())
            if isinstance(data, list):
                files_to_lint = [Path(f).resolve() for f in data]
            elif isinstance(data, dict) and "files" in data:
                files_to_lint = [Path(f).resolve() for f in data["files"]]
    elif base_commit:
        all_changed = get_changed_files_from_git(base_commit, repo_root)
        files_to_lint = filter_lint_eligible(all_changed)
    
    # Filter to lint-eligible only
    files_to_lint = filter_lint_eligible(files_to_lint)
    
    # Get HEAD commit for tracking
    head_commit = get_head_commit(repo_root)
    
    # Step 3: Run arch_lint
    tool_path = "tools/arch_lint"
    tool_version = get_arch_lint_version()
    
    # Build command
    if files_to_lint:
        cmd = [sys.executable, "-m", "tools.arch_lint", "--files"] + [str(f) for f in files_to_lint]
    else:
        # No files to lint - this is OK, report 0 errors
        timestamp = datetime.now(timezone.utc).isoformat()
        report = LintReport(
            contract_id=contract_id,
            lock_hash=lock_hash,
            lock_verified=verified,
            timestamp=timestamp,
            hash_algorithm="sha256",
            tool_path=tool_path,
            tool_version=tool_version,
            exit_code=0,
            stdout="No lint-eligible files to check",
            stderr="",
            error_count=0,
            warning_count=0,
            files_linted=[],
            base_commit=base_commit,
            head_commit=head_commit,
        )
        _write_artifacts(report, output_dir, contract_id)
        return report
    
    # Set UTF-8 encoding for subprocess
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            timeout=300,  # 5 minute timeout
            env=env,
        )
        exit_code = result.returncode
        stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
    except subprocess.TimeoutExpired:
        exit_code = -1
        stdout = ""
        stderr = "arch_lint timed out after 300 seconds"
    except Exception as e:
        exit_code = -2
        stdout = ""
        stderr = str(e)
    
    # Step 4: Count errors/warnings from output
    error_count = stdout.count("[ERROR]") + stdout.count("error:")
    warning_count = stdout.count("[WARNING]") + stdout.count("warning:")
    
    # Step 5: Create report with watermark and manifest
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Convert to relative paths for manifest
    files_manifest = []
    for f in files_to_lint:
        try:
            rel = f.relative_to(repo_root)
            files_manifest.append(str(rel).replace("\\", "/"))
        except ValueError:
            files_manifest.append(str(f))
    
    report = LintReport(
        contract_id=contract_id,
        lock_hash=lock_hash,
        lock_verified=verified,
        timestamp=timestamp,
        hash_algorithm="sha256",
        tool_path=tool_path,
        tool_version=tool_version,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        error_count=error_count,
        warning_count=warning_count,
        files_linted=files_manifest,
        base_commit=base_commit,
        head_commit=head_commit,
    )
    
    _write_artifacts(report, output_dir, contract_id)
    return report


def _write_artifacts(report: LintReport, output_dir: Path, contract_id: str) -> None:
    """Write lint report artifacts."""
    json_path = output_dir / f"{contract_id}.arch_lint.json"
    txt_path = output_dir / f"{contract_id}.arch_lint.txt"
    
    # JSON (structured)
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    
    # TXT (human-readable)
    txt_content = [
        "=" * 60,
        "arch_lint Report (Scoped)",
        "=" * 60,
        f"Contract: {contract_id}",
        f"Timestamp: {report.timestamp}",
        f"Lock Hash: {report.lock_hash}",
        f"Lock Verified: {report.lock_verified}",
        f"Tool: {report.tool_path} {report.tool_version}",
        f"Exit Code: {report.exit_code}",
        f"Errors: {report.error_count}",
        f"Warnings: {report.warning_count}",
        "",
        f"Base Commit: {report.base_commit or 'N/A'}",
        f"Head Commit: {report.head_commit or 'N/A'}",
        f"Files Linted: {len(report.files_linted)}",
        "",
        report.watermark(),
        "",
        "=" * 60,
        "FILES MANIFEST",
        "=" * 60,
    ]
    for f in report.files_linted:
        txt_content.append(f"  {f}")
    txt_content.extend([
        "",
        "=" * 60,
        "STDOUT",
        "=" * 60,
        report.stdout,
        "",
        "=" * 60,
        "STDERR",
        "=" * 60,
        report.stderr,
    ])
    txt_path.write_text("\n".join(txt_content), encoding="utf-8")


# =============================================================================
# CLI Interface
# =============================================================================

def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Run scoped arch_lint with lock verification and watermarking."
    )
    parser.add_argument("contract_id", help="Contract ID for this lint run")
    parser.add_argument(
        "--files",
        nargs="*",
        metavar="FILE",
        help="Lint only these specific files",
    )
    parser.add_argument(
        "--files-from",
        metavar="MANIFEST",
        help="Read file list from JSON manifest",
    )
    parser.add_argument(
        "--base-commit",
        metavar="SHA",
        help="Derive changed files from git diff HEAD..SHA",
    )
    
    args = parser.parse_args()
    
    print(f"Running scoped arch_lint for contract: {args.contract_id}")
    print()
    
    try:
        files = [Path(f) for f in args.files] if args.files else None
        files_from = Path(args.files_from) if args.files_from else None
        
        report = run_arch_lint_locked(
            contract_id=args.contract_id,
            files=files,
            files_from=files_from,
            base_commit=args.base_commit,
        )
        
        print(f"Lock verified: {report.lock_hash[:16]}...")
        print(f"Files linted: {len(report.files_linted)}")
        print(f"Exit code: {report.exit_code}")
        print(f"Errors: {report.error_count}")
        print(f"Warnings: {report.warning_count}")
        print()
        print(report.watermark())
        print()
        print(f"Artifacts written to artifacts/lint/")
        
        sys.exit(report.exit_code)
        
    except RuntimeError as e:
        print(f"FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()