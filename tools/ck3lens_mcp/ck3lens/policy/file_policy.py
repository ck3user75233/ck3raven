"""
File Policy Engine

Policy-based access control for file operations.
Integrates with CLW for mode-based permissions.

Policy Matrix:
| Mode          | Operation | Target           | Decision        |
|---------------|-----------|------------------|-----------------|
| ck3lens       | READ      | anywhere         | ALLOW (trace)   |
| ck3lens       | WRITE     | local_mod        | ALLOW           |
| ck3lens       | WRITE     | elsewhere        | DENY            |
| ck3raven-dev  | READ      | anywhere         | ALLOW (trace)   |
| ck3raven-dev  | WRITE     | ck3raven src     | ALLOW (contract)|
| ck3raven-dev  | WRITE     | ck3raven, no ctr | REQUIRE_TOKEN   |
| ck3raven-dev  | WRITE     | outside ck3raven | REQUIRE_TOKEN   |
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from .clw import Decision, PolicyResult
from .tokens import validate_token
from ..work_contracts import WorkContract, validate_path_against_contract


class FileOperation(Enum):
    """File operation types."""
    READ = auto()
    WRITE = auto()
    EDIT = auto()
    DELETE = auto()


@dataclass
class FileRequest:
    """Request for a file operation."""
    operation: FileOperation
    path: Path
    mode: str  # "ck3lens" or "ck3raven-dev"
    ck3raven_root: Optional[Path] = None
    contract_id: Optional[str] = None
    token_id: Optional[str] = None


# Paths that are NEVER writable
BLOCKED_PATHS = [
    "**/.git/**",
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/venv/**",
    "**/.venv/**",
]


def _is_within_ck3raven(path: Path, ck3raven_root: Path) -> bool:
    """Check if path is within ck3raven project."""
    try:
        path.resolve().relative_to(ck3raven_root.resolve())
        return True
    except ValueError:
        return False


def _is_blocked_path(path: Path) -> bool:
    """Check if path matches any blocked pattern."""
    import fnmatch
    path_str = str(path).replace("\\", "/")
    for pattern in BLOCKED_PATHS:
        if fnmatch.fnmatch(path_str, pattern):
            return True
    return False


def evaluate_file_operation(request: FileRequest) -> PolicyResult:
    """
    Evaluate a file operation request against mode-based policy.
    
    Args:
        request: FileRequest with operation details
    
    Returns:
        PolicyResult with decision
    """
    path = request.path.resolve()
    op = request.operation
    mode = request.mode
    
    # READ is always allowed (with tracing)
    if op == FileOperation.READ:
        return PolicyResult(
            decision=Decision.ALLOW,
            reason="Read operations are allowed",
            command=f"file:{op.name}:{path}",
        )
    
    # Blocked paths are never writable
    if _is_blocked_path(path):
        return PolicyResult(
            decision=Decision.DENY,
            reason=f"Path matches blocked pattern: {path}",
            command=f"file:{op.name}:{path}",
        )
    
    # ck3lens mode: Only local mods (handled by caller before reaching here)
    if mode == "ck3lens":
        return PolicyResult(
            decision=Decision.DENY,
            reason="ck3lens mode: Use mod_name+rel_path for writes, not raw paths",
            command=f"file:{op.name}:{path}",
        )
    
    # ck3raven-dev mode
    if mode == "ck3raven-dev":
        ck3raven_root = request.ck3raven_root
        
        if ck3raven_root and _is_within_ck3raven(path, ck3raven_root):
            # Within ck3raven project
            if request.contract_id:
                # Load and validate contract scope
                contract = WorkContract.load(request.contract_id)
                if contract is None:
                    return PolicyResult(
                        decision=Decision.DENY,
                        reason=f"Contract not found: {request.contract_id}",
                        command=f"file:{op.name}:{path}",
                    )
                
                if not contract.is_active():
                    return PolicyResult(
                        decision=Decision.REQUIRE_TOKEN,
                        reason=f"Contract is not active (status: {contract.status})",
                        required_token_type="FS_WRITE_OUTSIDE_CONTRACT",
                        command=f"file:{op.name}:{path}",
                    )
                
                # Validate path is within contract's allowed_paths
                try:
                    rel_path = str(path.relative_to(ck3raven_root))
                except ValueError:
                    rel_path = str(path)
                
                if contract.allowed_paths and not validate_path_against_contract(rel_path, contract):
                    return PolicyResult(
                        decision=Decision.DENY,
                        reason=f"Path '{rel_path}' not in contract allowed_paths: {contract.allowed_paths}",
                        command=f"file:{op.name}:{path}",
                        contract_id=request.contract_id,
                    )
                
                # Contract is valid and path is in scope
                return PolicyResult(
                    decision=Decision.ALLOW,
                    reason=f"Within ck3raven with valid contract scope",
                    command=f"file:{op.name}:{path}",
                    contract_id=request.contract_id,
                )
            else:
                # No contract - require token
                if request.token_id:
                    valid, msg = validate_token(
                        request.token_id,
                        "FS_WRITE_OUTSIDE_CONTRACT",
                        path=str(path),
                    )
                    if valid:
                        return PolicyResult(
                            decision=Decision.ALLOW,
                            reason=f"Token validated: {msg}",
                            command=f"file:{op.name}:{path}",
                            token_id=request.token_id,
                        )
                    else:
                        return PolicyResult(
                            decision=Decision.DENY,
                            reason=f"Token invalid: {msg}",
                            required_token_type="FS_WRITE_OUTSIDE_CONTRACT",
                            command=f"file:{op.name}:{path}",
                        )
                return PolicyResult(
                    decision=Decision.REQUIRE_TOKEN,
                    reason="Write to ck3raven without active contract requires token",
                    required_token_type="FS_WRITE_OUTSIDE_CONTRACT",
                    command=f"file:{op.name}:{path}",
                )
        else:
            # Outside ck3raven - always require token
            if request.token_id:
                valid, msg = validate_token(
                    request.token_id,
                    "FS_WRITE_OUTSIDE_CONTRACT",
                    path=str(path),
                )
                if valid:
                    return PolicyResult(
                        decision=Decision.ALLOW,
                        reason=f"Token validated for external write: {msg}",
                        command=f"file:{op.name}:{path}",
                        token_id=request.token_id,
                    )
                else:
                    return PolicyResult(
                        decision=Decision.DENY,
                        reason=f"Token invalid: {msg}",
                        required_token_type="FS_WRITE_OUTSIDE_CONTRACT",
                        command=f"file:{op.name}:{path}",
                    )
            return PolicyResult(
                decision=Decision.REQUIRE_TOKEN,
                reason="Write outside ck3raven requires FS_WRITE_OUTSIDE_CONTRACT token",
                required_token_type="FS_WRITE_OUTSIDE_CONTRACT",
                command=f"file:{op.name}:{path}",
            )
    
    # Unknown mode - deny
    return PolicyResult(
        decision=Decision.DENY,
        reason=f"Unknown mode: {mode}",
        command=f"file:{op.name}:{path}",
    )