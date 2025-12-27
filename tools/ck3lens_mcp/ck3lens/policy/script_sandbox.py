"""
Script Execution Sandbox

Sandboxed execution of Python scripts from the WIP workspace.
Enforces CK3Lens policy constraints on script execution.

Requirements for script execution:
1. Script must be in WIP workspace (~/.ck3raven/wip/)
2. Script must pass syntax validation
3. Script hash must match approved token
4. Declared reads/writes must be specified
5. Actual file access must match declarations (best-effort)

The sandbox:
- Validates script before execution
- Tracks declared vs actual file access
- Binds approval tokens to script hashes
- Provides safe subprocess execution with timeout
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .types import IntentType, CK3LensTokenType
from .wip_workspace import (
    is_wip_path,
    resolve_wip_path,
    validate_script_syntax,
    compute_script_hash,
    ScriptValidation,
)


@dataclass
class ScriptExecutionRequest:
    """Request to execute a WIP script."""
    script_rel_path: str  # Path relative to WIP
    script_hash: str  # Expected SHA256 hash
    declared_reads: list[str] = field(default_factory=list)
    declared_writes: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    timeout_seconds: int = 300  # 5 minute default
    working_dir: Optional[str] = None
    env_vars: dict[str, str] = field(default_factory=dict)
    
    # Contract/token binding
    contract_id: Optional[str] = None
    token_id: Optional[str] = None


@dataclass
class ScriptExecutionResult:
    """Result of script execution attempt."""
    executed: bool
    success: bool
    exit_code: Optional[int]
    stdout: str
    stderr: str
    error: Optional[str]
    duration_seconds: float
    
    # Validation results
    syntax_valid: bool
    hash_valid: bool
    token_valid: bool
    
    # File access tracking
    declared_writes: list[str]
    actual_writes: list[str]  # Best-effort detection
    undeclared_writes: list[str]
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "executed": self.executed,
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "syntax_valid": self.syntax_valid,
            "hash_valid": self.hash_valid,
            "token_valid": self.token_valid,
            "declared_writes": self.declared_writes,
            "actual_writes": self.actual_writes,
            "undeclared_writes": self.undeclared_writes,
        }


def _pre_execution_checks(
    request: ScriptExecutionRequest,
    local_mod_roots: set[str],
) -> tuple[bool, Optional[str], ScriptValidation | None]:
    """
    Pre-execution validation checks.
    
    Returns:
        (passed: bool, error: str | None, validation: ScriptValidation | None)
    """
    from .wip_workspace import get_wip_workspace_path
    
    wip_path = get_wip_workspace_path()
    
    # Check WIP workspace exists
    if not wip_path.exists():
        return False, "WIP workspace does not exist", None
    
    # Resolve script path
    try:
        script_path = resolve_wip_path(request.script_rel_path)
    except ValueError as e:
        return False, str(e), None
    
    if not script_path.exists():
        return False, f"Script not found: {request.script_rel_path}", None
    
    # Validate script is actually in WIP
    if not is_wip_path(script_path):
        return False, "Script must be in WIP workspace", None
    
    # Validate syntax
    validation = validate_script_syntax(request.script_rel_path)
    if not validation.is_valid:
        return False, f"Script syntax invalid: {validation.errors}", validation
    
    # Validate hash matches
    if validation.script_hash != request.script_hash:
        return False, f"Script hash mismatch: expected {request.script_hash}, got {validation.script_hash}", validation
    
    # Validate declared writes are within allowed scope
    for write_path in request.declared_writes:
        # WIP writes always allowed
        if write_path.startswith("wip:") or write_path.startswith("~/.ck3raven/wip/"):
            continue
        
        # Check if it's a local mod path
        write_normalized = write_path.replace("\\", "/").lower()
        allowed = False
        for mod_root in local_mod_roots:
            mod_root_normalized = mod_root.replace("\\", "/").lower()
            if write_normalized.startswith(mod_root_normalized):
                allowed = True
                break
        
        if not allowed:
            return False, f"Declared write outside allowed scope: {write_path}", validation
    
    return True, None, validation


def _validate_token(
    request: ScriptExecutionRequest,
    script_hash: str,
) -> tuple[bool, str]:
    """
    Validate execution token is valid and bound to correct hash.
    
    Returns:
        (valid: bool, error: str)
    """
    from .tokens import validate_token
    
    if not request.token_id:
        return False, "Script execution requires SCRIPT_EXECUTE token"
    
    valid, msg = validate_token(
        request.token_id,
        CK3LensTokenType.SCRIPT_EXECUTE.value,
        script_hash=script_hash,
    )
    
    if not valid:
        return False, f"Token validation failed: {msg}"
    
    return True, "Token valid"


def _snapshot_write_paths(paths: list[str]) -> dict[str, float]:
    """
    Snapshot modification times of paths for change detection.
    
    Returns:
        {path: mtime} for paths that exist
    """
    result = {}
    for path_str in paths:
        try:
            path = Path(path_str).resolve()
            if path.exists():
                result[str(path)] = path.stat().st_mtime
        except Exception:
            continue
    return result


def _detect_writes(
    before_snapshot: dict[str, float],
    declared_writes: list[str],
) -> list[str]:
    """
    Detect files that were modified after before_snapshot.
    
    This is best-effort - only checks declared paths.
    """
    actual_writes = []
    for path_str in declared_writes:
        try:
            path = Path(path_str).resolve()
            path_key = str(path)
            
            if not path.exists():
                continue
            
            current_mtime = path.stat().st_mtime
            
            if path_key not in before_snapshot:
                # New file created
                actual_writes.append(path_str)
            elif current_mtime > before_snapshot[path_key]:
                # File modified
                actual_writes.append(path_str)
        except Exception:
            continue
    
    return actual_writes


def execute_wip_script(
    request: ScriptExecutionRequest,
    local_mod_roots: set[str],
    validate_token: bool = True,
) -> ScriptExecutionResult:
    """
    Execute a Python script from the WIP workspace with sandbox enforcement.
    
    Args:
        request: Script execution request
        local_mod_roots: Set of allowed local mod root paths
        validate_token: Whether to require token validation (default True)
    
    Returns:
        ScriptExecutionResult with execution details
    """
    from .wip_workspace import get_wip_workspace_path
    
    start_time = time.time()
    
    # Pre-execution checks
    passed, error, validation = _pre_execution_checks(request, local_mod_roots)
    
    if not passed:
        return ScriptExecutionResult(
            executed=False,
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            error=error,
            duration_seconds=time.time() - start_time,
            syntax_valid=validation.is_valid if validation else False,
            hash_valid=False,
            token_valid=False,
            declared_writes=request.declared_writes,
            actual_writes=[],
            undeclared_writes=[],
        )
    
    script_hash = validation.script_hash if validation else ""
    
    # Token validation
    if validate_token:
        token_valid, token_error = _validate_token(request, script_hash)
        if not token_valid:
            return ScriptExecutionResult(
                executed=False,
                success=False,
                exit_code=None,
                stdout="",
                stderr="",
                error=token_error,
                duration_seconds=time.time() - start_time,
                syntax_valid=True,
                hash_valid=True,
                token_valid=False,
                declared_writes=request.declared_writes,
                actual_writes=[],
                undeclared_writes=[],
            )
    else:
        token_valid = True
    
    # Snapshot write paths before execution
    write_snapshot = _snapshot_write_paths(request.declared_writes)
    
    # Build command
    wip_path = get_wip_workspace_path()
    script_path = resolve_wip_path(request.script_rel_path)
    
    cmd = [sys.executable, str(script_path)] + request.args
    
    # Setup environment
    env = os.environ.copy()
    env.update(request.env_vars)
    
    # Add WIP path to help scripts find their own resources
    env["CK3LENS_WIP_PATH"] = str(wip_path)
    
    # Working directory defaults to WIP
    working_dir = request.working_dir or str(wip_path)
    
    # Execute with timeout
    try:
        proc = subprocess.run(
            cmd,
            cwd=working_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=request.timeout_seconds,
            stdin=subprocess.DEVNULL,
        )
        
        # Detect actual writes
        actual_writes = _detect_writes(write_snapshot, request.declared_writes)
        
        # Check for undeclared writes (would need filesystem monitoring for full coverage)
        undeclared_writes = []  # Best-effort - not fully implemented
        
        return ScriptExecutionResult(
            executed=True,
            success=proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            error=None if proc.returncode == 0 else f"Script exited with code {proc.returncode}",
            duration_seconds=time.time() - start_time,
            syntax_valid=True,
            hash_valid=True,
            token_valid=token_valid,
            declared_writes=request.declared_writes,
            actual_writes=actual_writes,
            undeclared_writes=undeclared_writes,
        )
        
    except subprocess.TimeoutExpired:
        return ScriptExecutionResult(
            executed=True,
            success=False,
            exit_code=-1,
            stdout="",
            stderr="",
            error=f"Script timed out after {request.timeout_seconds} seconds",
            duration_seconds=time.time() - start_time,
            syntax_valid=True,
            hash_valid=True,
            token_valid=token_valid,
            declared_writes=request.declared_writes,
            actual_writes=[],
            undeclared_writes=[],
        )
    except Exception as e:
        return ScriptExecutionResult(
            executed=False,
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            error=f"Execution error: {str(e)}",
            duration_seconds=time.time() - start_time,
            syntax_valid=True,
            hash_valid=True,
            token_valid=token_valid,
            declared_writes=request.declared_writes,
            actual_writes=[],
            undeclared_writes=[],
        )


def prepare_script_for_execution(
    script_content: str,
    script_name: str = "script.py",
) -> tuple[bool, dict[str, Any]]:
    """
    Prepare a script for execution by writing to WIP and validating.
    
    Args:
        script_content: Python script content
        script_name: Filename to use in WIP
    
    Returns:
        (success: bool, result: dict with hash, path, validation)
    """
    from .wip_workspace import write_wip_file, validate_script_syntax
    
    # Compute hash first
    script_hash = compute_script_hash(script_content)
    
    # Write to WIP
    try:
        write_result = write_wip_file(script_name, script_content)
    except Exception as e:
        return False, {"error": f"Failed to write script: {e}"}
    
    # Validate syntax
    validation = validate_script_syntax(script_name)
    
    if not validation.is_valid:
        return False, {
            "error": "Script has syntax errors",
            "syntax_errors": validation.errors,
            "script_hash": script_hash,
            "script_path": write_result["path"],
        }
    
    return True, {
        "script_hash": script_hash,
        "script_path": write_result["path"],
        "rel_path": script_name,
        "validation": {
            "is_valid": validation.is_valid,
            "line_count": validation.line_count,
        },
    }
