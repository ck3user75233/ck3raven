"""
Contract Close Audit Tool - Phase 1.5 Compliance Gate

This tool runs all Phase 1.5 compliance checks before allowing contract closure.

Authority: docs/PHASE_1_5_AGENT_INSTRUCTION.md

Checks run in order:
1. Linter lock eligibility (active lock verifies, proposed lock fails unless promoted)
2. Derive changed files from git diff (base_commit..HEAD)
3. Run watermarked arch_lint via scoped wrapper
4. Verify lint coverage for all lint-eligible changed files
5. Playset drift check (baseline vs current playset_hash)
6. Symbols identity diff (baseline vs current)
7. Token validation (NST for new symbols, LXE for lint violations)

Usage:
    python -m tools.compliance.audit_contract_close <contract_id> [--base-commit SHA]
    
Exit codes:
    0 = All checks pass
    1 = Check failure (see audit artifact for details)
    2 = System error
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any


def _get_repo_root() -> Path:
    """Get the ck3raven repository root."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Could not find repository root")


def _get_artifacts_dir() -> Path:
    """Get the artifacts directory."""
    return _get_repo_root() / "artifacts"


def _get_audit_dir() -> Path:
    """Get the audit artifacts directory."""
    return _get_artifacts_dir() / "audit"


# Lint-eligible extensions for coverage check
LINT_ELIGIBLE_EXTENSIONS = frozenset({".py"})


# =============================================================================
# Check Results
# =============================================================================

@dataclass
class CheckResult:
    """Result of a single compliance check."""
    check_name: str
    passed: bool
    message: str
    details: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "check_name": self.check_name,
            "passed": self.passed,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class AuditResult:
    """Complete audit result for contract closure."""
    contract_id: str
    audit_timestamp: str
    all_passed: bool
    checks: list[CheckResult]
    can_close: bool
    failure_reason: Optional[str]
    
    # Metadata
    baseline_snapshot_id: Optional[str] = None
    current_snapshot_id: Optional[str] = None
    playset_hash_baseline: Optional[str] = None
    playset_hash_current: Optional[str] = None
    base_commit: Optional[str] = None
    head_commit: Optional[str] = None
    changed_files: Optional[list[str]] = None
    
    def to_dict(self) -> dict:
        return {
            "contract_id": self.contract_id,
            "audit_timestamp": self.audit_timestamp,
            "all_passed": self.all_passed,
            "can_close": self.can_close,
            "failure_reason": self.failure_reason,
            "baseline_snapshot_id": self.baseline_snapshot_id,
            "current_snapshot_id": self.current_snapshot_id,
            "playset_hash_baseline": self.playset_hash_baseline,
            "playset_hash_current": self.playset_hash_current,
            "base_commit": self.base_commit,
            "head_commit": self.head_commit,
            "changed_files": self.changed_files,
            "checks": [c.to_dict() for c in self.checks],
        }
    
    def save(self, path: Optional[Path] = None) -> Path:
        """Save audit result to disk."""
        if path is None:
            audit_dir = _get_audit_dir()
            audit_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            path = audit_dir / f"{self.contract_id}_{timestamp}.audit.json"
        
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path
    
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"=== Contract Close Audit: {self.contract_id} ===",
            f"Timestamp: {self.audit_timestamp}",
            f"Result: {'PASS' if self.all_passed else 'FAIL'}",
            "",
        ]
        
        for check in self.checks:
            status = "[PASS]" if check.passed else "[FAIL]"
            lines.append(f"  {status} {check.check_name}: {check.message}")
        
        if not self.can_close:
            lines.append("")
            lines.append(f"CLOSURE BLOCKED: {self.failure_reason}")
        
        return "\n".join(lines)


# =============================================================================
# Git Helpers
# =============================================================================

def get_changed_files(base_commit: str, repo_root: Path) -> list[str]:
    """Get list of changed files between base_commit and HEAD."""
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
                files.append(line.replace("\\", "/"))
        return files
    except Exception as e:
        raise RuntimeError(f"Failed to get changed files: {e}")


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


def filter_lint_eligible(files: list[str]) -> list[str]:
    """Filter to only lint-eligible files."""
    return [f for f in files if Path(f).suffix in LINT_ELIGIBLE_EXTENSIONS]


# =============================================================================
# Check 1: Linter Lock Eligibility
# =============================================================================

def check_linter_lock() -> CheckResult:
    """
    Verify linter lock is valid and no unapproved proposed lock exists.
    """
    repo_root = _get_repo_root()
    active_lock_path = repo_root / "policy" / "locks" / "linter.lock.json"
    proposed_lock_path = repo_root / "artifacts" / "locks" / "proposed" / "linter.lock.json"
    
    # Check active lock exists
    if not active_lock_path.exists():
        return CheckResult(
            check_name="linter_lock",
            passed=False,
            message="No active linter lock found",
            details={"path": str(active_lock_path)},
        )
    
    # Check for unapproved proposed lock
    if proposed_lock_path.exists():
        return CheckResult(
            check_name="linter_lock",
            passed=False,
            message="Proposed linter lock exists - must be promoted or deleted before closure",
            details={
                "proposed_path": str(proposed_lock_path),
                "action_required": "User must promote proposed lock to policy/locks/ or delete it",
            },
        )
    
    # Verify active lock (check file hashes match)
    try:
        with open(active_lock_path) as f:
            lock_data = json.load(f)
        
        files = lock_data.get("files", [])
        mismatches = []
        
        for file_entry in files:
            file_path = repo_root / file_entry["path"]
            expected_hash = file_entry["sha256"]
            
            if not file_path.exists():
                mismatches.append({"path": file_entry["path"], "error": "file missing"})
                continue
            
            content = file_path.read_bytes()
            actual_hash = hashlib.sha256(content).hexdigest()
            
            if actual_hash != expected_hash:
                mismatches.append({
                    "path": file_entry["path"],
                    "expected": expected_hash[:16] + "...",
                    "actual": actual_hash[:16] + "...",
                })
        
        if mismatches:
            return CheckResult(
                check_name="linter_lock",
                passed=False,
                message=f"Linter lock verification failed: {len(mismatches)} file(s) changed",
                details={"mismatches": mismatches},
            )
        
        return CheckResult(
            check_name="linter_lock",
            passed=True,
            message=f"Linter lock verified ({len(files)} files)",
            details={"lock_hash": lock_data.get("lock_hash", "unknown")[:32]},
        )
        
    except Exception as e:
        return CheckResult(
            check_name="linter_lock",
            passed=False,
            message=f"Error verifying linter lock: {e}",
            details={"error": str(e)},
        )


# =============================================================================
# Check 2: Scoped arch_lint with Coverage Verification
# =============================================================================

def check_arch_lint(
    contract_id: str,
    base_commit: Optional[str],
    changed_files: Optional[list[str]],
) -> tuple[CheckResult, Optional[int]]:
    """
    Run scoped arch_lint and verify coverage.
    
    Returns:
        (CheckResult, error_count or None)
    """
    repo_root = _get_repo_root()
    
    # Must have base_commit to determine scope
    if not base_commit:
        return CheckResult(
            check_name="arch_lint",
            passed=False,
            message="No base_commit - cannot determine lint scope",
            details={"action_required": "Contract must capture base_commit at open"},
        ), None
    
    # Get lint-eligible changed files
    lint_eligible = filter_lint_eligible(changed_files or [])
    
    # If no lint-eligible files changed, pass trivially
    if not lint_eligible:
        return CheckResult(
            check_name="arch_lint",
            passed=True,
            message="No lint-eligible files changed",
            details={"changed_files_count": len(changed_files or [])},
        ), 0
    
    try:
        # Run the locked wrapper with base_commit
        from tools.compliance.run_arch_lint_locked import run_arch_lint_locked
        
        report = run_arch_lint_locked(
            contract_id=contract_id,
            base_commit=base_commit,
        )
        
        # Verify coverage: every lint-eligible changed file must be in manifest
        linted_set = set(report.files_linted)
        missing_coverage = [f for f in lint_eligible if f not in linted_set]
        
        if missing_coverage:
            return CheckResult(
                check_name="arch_lint",
                passed=False,
                message=f"Lint coverage incomplete: {len(missing_coverage)} file(s) not linted",
                details={
                    "missing_files": missing_coverage,
                    "linted_count": len(report.files_linted),
                    "required_count": len(lint_eligible),
                    "action_required": "All lint-eligible changed files must be linted",
                },
            ), None
        
        # Check error_count (canonical field)
        error_count = report.error_count
        
        if error_count > 0:
            return CheckResult(
                check_name="arch_lint",
                passed=False,
                message=f"arch_lint found {error_count} error(s)",
                details={
                    "error_count": error_count,
                    "warning_count": report.warning_count,
                    "files_linted": len(report.files_linted),
                    "watermark": report.lock_hash[:32],
                    "requires_lxe": True,
                },
            ), error_count
        
        return CheckResult(
            check_name="arch_lint",
            passed=True,
            message=f"arch_lint passed ({len(report.files_linted)} files, {report.warning_count} warnings)",
            details={
                "files_linted": len(report.files_linted),
                "warning_count": report.warning_count,
                "watermark": report.lock_hash[:32],
            },
        ), 0
        
    except RuntimeError as e:
        return CheckResult(
            check_name="arch_lint",
            passed=False,
            message=f"Lint wrapper failed: {e}",
            details={"error": str(e)},
        ), None
    except Exception as e:
        return CheckResult(
            check_name="arch_lint",
            passed=False,
            message=f"Error running arch_lint: {e}",
            details={"error": str(e)},
        ), None


# =============================================================================
# Check 3: Playset Drift
# =============================================================================

def check_playset_drift(baseline_playset_hash: Optional[str]) -> CheckResult:
    """
    Verify playset hasn't changed since contract open.
    """
    if baseline_playset_hash is None:
        return CheckResult(
            check_name="playset_drift",
            passed=False,
            message="No baseline playset_hash - contract missing Phase 1.5 metadata",
            details={"action_required": "Contract must capture playset_hash at open"},
        )
    
    try:
        from tools.compliance.symbols_lock import get_active_playset_identity
        
        current_playset = get_active_playset_identity()
        current_hash = current_playset.playset_hash
        
        if current_hash != baseline_playset_hash:
            return CheckResult(
                check_name="playset_drift",
                passed=False,
                message="Playset has changed since contract open",
                details={
                    "baseline_hash": baseline_playset_hash[:32] + "...",
                    "current_hash": current_hash[:32] + "...",
                    "action_required": "Cancel contract and reopen with current playset",
                },
            )
        
        return CheckResult(
            check_name="playset_drift",
            passed=True,
            message="Playset unchanged",
            details={"playset_hash": current_hash[:32] + "..."},
        )
        
    except Exception as e:
        return CheckResult(
            check_name="playset_drift",
            passed=False,
            message=f"Error checking playset: {e}",
            details={"error": str(e)},
        )


# =============================================================================
# Check 4: Symbols Identity Diff
# =============================================================================

def check_symbols_diff(
    baseline_snapshot_path: Optional[str],
    contract_id: str,
) -> tuple[CheckResult, Optional[list[dict]]]:
    """
    Compare baseline symbol snapshot to current state.
    """
    if baseline_snapshot_path is None:
        return CheckResult(
            check_name="symbols_diff",
            passed=False,
            message="No baseline snapshot - contract missing Phase 1.5 metadata",
            details={"action_required": "Contract must capture baseline snapshot at open"},
        ), None
    
    try:
        from tools.compliance.symbols_lock import (
            SymbolsSnapshot,
            check_new_symbols,
            _resolve_snapshot_path,
        )
        
        baseline_path = _resolve_snapshot_path(baseline_snapshot_path)
        has_new, diff = check_new_symbols(baseline_path)
        
        if not diff.playset_match:
            return CheckResult(
                check_name="symbols_diff",
                passed=False,
                message=f"Playset drift detected during symbols diff",
                details={"drift_message": diff.playset_drift_message},
            ), None
        
        if diff.added_count > 0:
            new_identities = [
                {"symbol_type": i.symbol_type, "scope": i.scope, "name": i.name}
                for i in diff.added_identities
            ]
            
            return CheckResult(
                check_name="symbols_diff",
                passed=False,
                message=f"New symbol identities detected: {diff.added_count}",
                details={
                    "added_count": diff.added_count,
                    "added_by_type": diff.added_by_type,
                    "samples": [i.key() for i in diff.added_identities[:10]],
                    "requires_nst": True,
                },
            ), new_identities
        
        return CheckResult(
            check_name="symbols_diff",
            passed=True,
            message="No new symbol identities",
            details={
                "baseline_id": diff.baseline_id,
                "current_hash": diff.current_hash[:32] + "...",
            },
        ), None
        
    except FileNotFoundError as e:
        return CheckResult(
            check_name="symbols_diff",
            passed=False,
            message=f"Baseline snapshot not found: {baseline_snapshot_path}",
            details={"error": str(e)},
        ), None
    except Exception as e:
        return CheckResult(
            check_name="symbols_diff",
            passed=False,
            message=f"Error checking symbols diff: {e}",
            details={"error": str(e)},
        ), None


# =============================================================================
# Check 5: Token Validation
# =============================================================================

def validate_nst_tokens(
    contract_id: str,
    new_identities: Optional[list[dict]],
) -> CheckResult:
    """Validate NST coverage for new identities.
    
    An NST (New Symbol Token) authorizes the introduction of new symbol
    identities. Required when the symbol diff shows additions.
    
    Uses the tokens.py module for proper lifecycle validation:
    - Checks token exists in policy/tokens/ (approved)
    - Validates signature integrity
    - Verifies expiration
    - Confirms coverage of actual new symbols
    """
    from tools.compliance.tokens import (
        TokenType,
        load_tokens_for_contract,
        validate_token,
        check_nst_coverage,
    )
    
    if new_identities is None or len(new_identities) == 0:
        return CheckResult(
            check_name="nst_validation",
            passed=True,
            message="No NST required (no new symbols)",
            details={},
        )
    
    # Load approved NST tokens for this contract
    nst_tokens = load_tokens_for_contract(contract_id, TokenType.NST)
    
    if not nst_tokens:
        # Check if there's a proposal pending approval
        proposed_tokens = load_tokens_for_contract(
            contract_id, TokenType.NST, include_proposed=True
        )
        
        proposal_hint = ""
        if proposed_tokens:
            proposal_hint = f" ({len(proposed_tokens)} pending approval in artifacts/tokens_proposed/)"
        
        return CheckResult(
            check_name="nst_validation",
            passed=False,
            message=f"NST required for {len(new_identities)} new symbol(s){proposal_hint}",
            details={
                "new_identities": [
                    f"{i['symbol_type']}:{i.get('scope', '')}:{i['name']}"
                    for i in new_identities[:20]
                ],
                "action_required": "Create NST proposal and get user approval",
                "propose_command": f"python -m tools.compliance.tokens propose-nst --contract-id {contract_id} --symbols <symbol_list>",
                "pending_proposals": len(proposed_tokens) if proposed_tokens else 0,
            },
        )
    
    # Validate each token's integrity and expiration
    validation_errors = []
    valid_tokens = []
    
    for token in nst_tokens:
        is_valid, error = validate_token(token)
        if not is_valid:
            validation_errors.append(f"{token.token_id}: {error}")
        else:
            valid_tokens.append(token)
    
    if not valid_tokens:
        return CheckResult(
            check_name="nst_validation",
            passed=False,
            message=f"All {len(nst_tokens)} NST token(s) failed validation",
            details={
                "validation_errors": validation_errors,
                "action_required": "Fix or recreate NST tokens",
            },
        )
    
    # Check coverage - do the approved symbols cover the actual new symbols?
    coverage_result = check_nst_coverage(valid_tokens, new_identities)
    
    if not coverage_result["fully_covered"]:
        uncovered = coverage_result.get("uncovered_symbols", [])
        return CheckResult(
            check_name="nst_validation",
            passed=False,
            message=f"NST coverage incomplete: {len(uncovered)} symbol(s) not covered",
            details={
                "uncovered_symbols": uncovered[:20],
                "covered_count": coverage_result.get("covered_count", 0),
                "total_new": len(new_identities),
                "action_required": "Expand NST scope or create additional NST",
            },
        )
    
    return CheckResult(
        check_name="nst_validation",
        passed=True,
        message=f"NST validation passed ({len(valid_tokens)} token(s), {len(new_identities)} symbol(s) covered)",
        details={
            "token_count": len(valid_tokens),
            "symbols_covered": len(new_identities),
            "validation_errors": validation_errors if validation_errors else None,
        },
    )


def validate_lxe_tokens(
    contract_id: str,
    error_count: Optional[int],
    lint_violations: Optional[list[dict]] = None,
) -> CheckResult:
    """Validate LXE coverage for lint errors.
    
    An LXE (Lint Exception Token) authorizes known lint violations to
    remain in the codebase. Required when arch_lint produces errors.
    
    Uses the tokens.py module for proper lifecycle validation:
    - Checks token exists in policy/tokens/ (approved)
    - Validates signature integrity
    - Verifies expiration
    - Confirms coverage of actual lint violations
    """
    from tools.compliance.tokens import (
        TokenType,
        load_tokens_for_contract,
        validate_token,
        check_lxe_coverage,
    )
    
    if error_count is None or error_count == 0:
        return CheckResult(
            check_name="lxe_validation",
            passed=True,
            message="No LXE required (no lint errors)",
            details={},
        )
    
    # Load approved LXE tokens for this contract
    lxe_tokens = load_tokens_for_contract(contract_id, TokenType.LXE)
    
    if not lxe_tokens:
        # Check if there's a proposal pending approval
        proposed_tokens = load_tokens_for_contract(
            contract_id, TokenType.LXE, include_proposed=True
        )
        
        proposal_hint = ""
        if proposed_tokens:
            proposal_hint = f" ({len(proposed_tokens)} pending approval in artifacts/tokens_proposed/)"
        
        return CheckResult(
            check_name="lxe_validation",
            passed=False,
            message=f"LXE required for {error_count} lint error(s){proposal_hint}",
            details={
                "error_count": error_count,
                "action_required": "Create LXE proposal and get user approval",
                "propose_command": f"python -m tools.compliance.tokens propose-lxe --contract-id {contract_id} --violations <violation_list>",
                "pending_proposals": len(proposed_tokens) if proposed_tokens else 0,
            },
        )
    
    # Validate each token's integrity and expiration
    validation_errors = []
    valid_tokens = []
    
    for token in lxe_tokens:
        is_valid, error = validate_token(token)
        if not is_valid:
            validation_errors.append(f"{token.token_id}: {error}")
        else:
            valid_tokens.append(token)
    
    if not valid_tokens:
        return CheckResult(
            check_name="lxe_validation",
            passed=False,
            message=f"All {len(lxe_tokens)} LXE token(s) failed validation",
            details={
                "validation_errors": validation_errors,
                "action_required": "Fix or recreate LXE tokens",
            },
        )
    
    # Check coverage - do the approved violations cover the actual lint errors?
    if lint_violations:
        coverage_result = check_lxe_coverage(valid_tokens, lint_violations)
        
        if not coverage_result["fully_covered"]:
            uncovered = coverage_result.get("uncovered_violations", [])
            return CheckResult(
                check_name="lxe_validation",
                passed=False,
                message=f"LXE coverage incomplete: {len(uncovered)} violation(s) not covered",
                details={
                    "uncovered_violations": uncovered[:20],
                    "covered_count": coverage_result.get("covered_count", 0),
                    "total_violations": error_count,
                    "action_required": "Expand LXE scope or create additional LXE",
                },
            )
    
    return CheckResult(
        check_name="lxe_validation",
        passed=True,
        message=f"LXE validation passed ({len(valid_tokens)} token(s) covering {error_count} error(s))",
        details={
            "token_count": len(valid_tokens),
            "errors_covered": error_count,
            "validation_errors": validation_errors if validation_errors else None,
        },
    )


# =============================================================================
# Main Audit Function
# =============================================================================

def run_contract_close_audit(
    contract_id: str,
    baseline_snapshot_path: Optional[str] = None,
    baseline_playset_hash: Optional[str] = None,
    base_commit: Optional[str] = None,
) -> AuditResult:
    """
    Run complete Phase 1.5 audit for contract closure.
    
    Checks run in order:
    1. Linter lock eligibility
    2. Derive changed files from git diff (base_commit..HEAD)
    3. Scoped arch_lint with coverage verification
    4. Playset drift
    5. Symbols identity diff
    6. Token validation (NST/LXE)
    """
    repo_root = _get_repo_root()
    timestamp = datetime.now(timezone.utc).isoformat()
    checks: list[CheckResult] = []
    lint_error_count: Optional[int] = None
    new_identities: Optional[list[dict]] = None
    changed_files: Optional[list[str]] = None
    head_commit = get_head_commit(repo_root)
    
    # Check 1: Linter lock
    lock_result = check_linter_lock()
    checks.append(lock_result)
    
    # Derive changed files from git (requires base_commit)
    if base_commit:
        try:
            changed_files = get_changed_files(base_commit, repo_root)
        except Exception as e:
            checks.append(CheckResult(
                check_name="git_diff",
                passed=False,
                message=f"Failed to get changed files: {e}",
                details={"error": str(e)},
            ))
    
    # Check 2: arch_lint (only if lock passes)
    if lock_result.passed:
        lint_result, lint_error_count = check_arch_lint(contract_id, base_commit, changed_files)
        checks.append(lint_result)
    else:
        checks.append(CheckResult(
            check_name="arch_lint",
            passed=False,
            message="Skipped - linter lock failed",
            details={"skipped": True},
        ))
    
    # Check 3: Playset drift
    drift_result = check_playset_drift(baseline_playset_hash)
    checks.append(drift_result)
    
    # Check 4: Symbols diff (only if playset matches)
    if drift_result.passed:
        symbols_result, new_identities = check_symbols_diff(baseline_snapshot_path, contract_id)
        checks.append(symbols_result)
    else:
        checks.append(CheckResult(
            check_name="symbols_diff",
            passed=False,
            message="Skipped - playset drift detected",
            details={"skipped": True},
        ))
    
    # Check 5a: NST validation
    nst_result = validate_nst_tokens(contract_id, new_identities)
    checks.append(nst_result)
    
    # Check 5b: LXE validation
    lxe_result = validate_lxe_tokens(contract_id, lint_error_count)
    checks.append(lxe_result)
    
    # Determine overall result
    all_passed = all(c.passed for c in checks)
    
    failure_reason = None
    if not all_passed:
        for check in checks:
            if not check.passed:
                failure_reason = f"{check.check_name}: {check.message}"
                break
    
    # Get current playset hash
    current_playset_hash = None
    try:
        from tools.compliance.symbols_lock import get_active_playset_identity
        current_playset_hash = get_active_playset_identity().playset_hash
    except Exception:
        pass
    
    return AuditResult(
        contract_id=contract_id,
        audit_timestamp=timestamp,
        all_passed=all_passed,
        checks=checks,
        can_close=all_passed,
        failure_reason=failure_reason,
        baseline_snapshot_id=baseline_snapshot_path,
        playset_hash_baseline=baseline_playset_hash,
        playset_hash_current=current_playset_hash,
        base_commit=base_commit,
        head_commit=head_commit,
        changed_files=changed_files,
    )


# =============================================================================
# CLI
# =============================================================================

def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Run Phase 1.5 compliance audit for contract closure"
    )
    parser.add_argument("contract_id", help="Contract ID to audit")
    parser.add_argument(
        "--baseline-snapshot",
        help="Path or ID of baseline symbol snapshot",
    )
    parser.add_argument(
        "--baseline-playset-hash",
        help="Playset hash captured at contract open",
    )
    parser.add_argument(
        "--base-commit",
        help="Git commit SHA captured at contract open",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Output JSON only, no summary",
    )
    
    args = parser.parse_args()
    
    result = run_contract_close_audit(
        contract_id=args.contract_id,
        baseline_snapshot_path=args.baseline_snapshot,
        baseline_playset_hash=args.baseline_playset_hash,
        base_commit=args.base_commit,
    )
    
    artifact_path = result.save()
    
    if args.json_only:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.summary())
        print()
        print(f"Audit artifact: {artifact_path}")
    
    sys.exit(0 if result.can_close else 1)


if __name__ == "__main__":
    main()