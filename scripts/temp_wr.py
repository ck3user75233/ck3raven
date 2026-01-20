"""Write the arch_lint wrapper with watermarking."""

from pathlib import Path

CONTENT = '''"""
Locked arch_lint Runner - Phase 1.5 Component A5

Wrapper that:
1. Verifies the linter lock first
2. Runs arch_lint
3. Stamps the output with lock_hash watermark

Usage:
    python -m tools.compliance.run_arch_lint_locked <contract_id> [arch_lint args...]
    
Output:
    artifacts/lint/<contract_id>.arch_lint.json  (structured)
    artifacts/lint/<contract_id>.arch_lint.txt   (human-readable, optional)

Authority: docs/PHASE_1_5_AGENT_INSTRUCTION.md
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, asdict
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


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class LintReport:
    """Structured lint report with watermark."""
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
    from tools.compliance.linter_lock import verify_lock, _get_lock_path
    
    result = verify_lock()
    return result.valid, result.lock_hash if result.valid else result.expected_hash, result.message


def get_arch_lint_version() -> str:
    """Extract arch_lint version from its config."""
    try:
        config_path = _get_repo_root() / "tools" / "arch_lint" / "config.py"
        content = config_path.read_text()
        # Look for version in docstring like "arch_lint v2.35"
        for line in content.split("\\n"):
            if "arch_lint v" in line:
                import re
                match = re.search(r"arch_lint (v[0-9.]+)", line)
                if match:
                    return match.group(1)
        return "unknown"
    except Exception:
        return "unknown"


def run_arch_lint_locked(
    contract_id: str,
    arch_lint_args: Optional[list[str]] = None,
    output_dir: Optional[Path] = None,
) -> LintReport:
    """
    Run arch_lint with lock verification and watermarking.
    
    Args:
        contract_id: Contract ID to associate with this lint run
        arch_lint_args: Additional arguments for arch_lint
        output_dir: Where to write artifacts (default: artifacts/lint/)
    
    Returns:
        LintReport with results
    
    Raises:
        RuntimeError: If lock verification fails
    """
    repo_root = _get_repo_root()
    
    if output_dir is None:
        output_dir = repo_root / "artifacts" / "lint"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if arch_lint_args is None:
        arch_lint_args = []
    
    # Step 1: Verify lock FIRST
    verified, lock_hash, message = verify_lock_first()
    
    if not verified:
        raise RuntimeError(f"Lock verification failed: {message}")
    
    # Step 2: Run arch_lint
    tool_path = "tools/arch_lint"
    tool_version = get_arch_lint_version()
    
    cmd = [sys.executable, "-m", "tools.arch_lint"] + arch_lint_args
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )
        exit_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        exit_code = -1
        stdout = ""
        stderr = "arch_lint timed out after 300 seconds"
    except Exception as e:
        exit_code = -2
        stdout = ""
        stderr = str(e)
    
    # Step 3: Count errors/warnings from output
    error_count = stdout.count("[ERROR]") + stdout.count("error:")
    warning_count = stdout.count("[WARNING]") + stdout.count("warning:")
    
    # Step 4: Create report with watermark
    timestamp = datetime.now(timezone.utc).isoformat()
    
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
    )
    
    # Step 5: Write artifacts
    json_path = output_dir / f"{contract_id}.arch_lint.json"
    txt_path = output_dir / f"{contract_id}.arch_lint.txt"
    
    # JSON (structured)
    json_path.write_text(json.dumps(report.to_dict(), indent=2))
    
    # TXT (human-readable)
    txt_content = [
        "=" * 60,
        "arch_lint Report",
        "=" * 60,
        f"Contract: {contract_id}",
        f"Timestamp: {timestamp}",
        f"Lock Hash: {lock_hash}",
        f"Lock Verified: {verified}",
        f"Tool: {tool_path} {tool_version}",
        f"Exit Code: {exit_code}",
        f"Errors: {error_count}",
        f"Warnings: {warning_count}",
        "",
        report.watermark(),
        "",
        "=" * 60,
        "STDOUT",
        "=" * 60,
        stdout,
        "",
        "=" * 60,
        "STDERR",
        "=" * 60,
        stderr,
    ]
    txt_path.write_text("\\n".join(txt_content))
    
    return report


# =============================================================================
# CLI Interface
# =============================================================================

def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m tools.compliance.run_arch_lint_locked <contract_id> [arch_lint args...]")
        print()
        print("Runs arch_lint with lock verification and watermarking.")
        print()
        print("Output:")
        print("  artifacts/lint/<contract_id>.arch_lint.json  (structured)")
        print("  artifacts/lint/<contract_id>.arch_lint.txt   (human-readable)")
        sys.exit(1)
    
    contract_id = sys.argv[1]
    arch_lint_args = sys.argv[2:]
    
    print(f"Running locked arch_lint for contract: {contract_id}")
    print()
    
    try:
        report = run_arch_lint_locked(contract_id, arch_lint_args)
        
        print(f"Lock verified: {report.lock_hash[:16]}...")
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
'''

target = Path(r"C:\Users\nateb\Documents\CK3 Mod Project 1.18\ck3raven\tools\compliance\run_arch_lint_locked.py")
target.write_text(CONTENT, encoding="utf-8")
print(f"Written {len(CONTENT)} bytes")
