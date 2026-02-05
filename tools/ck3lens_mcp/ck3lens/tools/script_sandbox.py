"""
Script Sandbox - Tool Layer

TODO: IMPLEMENTATION INCOMPLETE - Structural placeholder only.

This module provides sandboxed Python execution for ck3lens mode.
It acts as a tool consumer, delegating to:
- Path boundary checks for read visibility
- enforcement.py for write permission decisions

Architecture:
    sandbox_execute() intercepts script I/O via monkey-patching:
    
    Script calls open("some/path", "r")
        └─> Sandbox intercepts
            └─> Is path under allowed read domains?
                - WIP (always)
                - local_mods_folder (active playset mods)
                - vanilla_path (CK3 game files)
                - utility_paths (logs, saves)
                └─> Yes → allow, No → FileNotFoundError
    
    Script calls open("some/path", "w")
        └─> Sandbox intercepts
            └─> enforcement.gate_write(path, contract_id)
                └─> ALLOW or PermissionError

IMPLEMENTATION NOTES:
    The sandbox does NOT need database access (PlaysetLens/DBQueries).
    It only needs path boundaries from Session:
    
    Required from Session:
    - wip_path: Path to ~/.ck3raven/wip/ (always readable/writable)
    - local_mods_folder: Path to Paradox mod folder (readable, writable with contract)
    - vanilla_path: Path to CK3 game/ folder (read-only)
    - utility_paths: Set of paths to logs, saves, etc. (read-only)
    
    The WorldAdapter abstraction is OVERKILL for sandbox I/O gating.
    Simple path containment checks (path.is_relative_to(boundary)) suffice.
    
    For writes, delegate to enforcement._enforce_ck3lens_write() which
    already knows the write policy (WIP always, local mods with contract).

INTEGRATION WITH ck3_exec:
    When ck3_exec detects a WIP Python script:
    1. Validate token (user approved execution)
    2. Create SandboxContext with path boundaries from Session
    3. Run script with sandboxed_execution() context manager
    4. Return audit of reads/writes attempted

CURRENT STATE:
    - Monkey-patching structure: DONE
    - Path boundary injection: PLACEHOLDER (uses WorldAdapter incorrectly)
    - enforcement.gate_write integration: DONE
    - Needs: Refactor to accept simple path boundaries instead of Session/WorldAdapter
"""
from __future__ import annotations

import builtins
import os
import sys
import io
import contextlib
from pathlib import Path
from typing import Any, Callable, Optional, Set
from dataclasses import dataclass, field


@dataclass
class SandboxContext:
    """
    Runtime context for sandbox execution.
    
    Captures path boundaries and tracks actual I/O for audit.
    
    TODO: Refactor to use simple path boundaries instead of session:
        wip_path: Path
        local_mods_folder: Optional[Path]
        vanilla_path: Optional[Path]  
        utility_paths: Set[Path]
    """
    # Session info for LensWorld resolution
    session: Any  # workspace.Session - TODO: replace with explicit paths
    
    # WIP workspace path (always allowed for read/write)
    wip_path: Path
    
    # Contract info for enforcement
    contract_id: Optional[str] = None
    
    # Token info if pre-approved
    token_id: Optional[str] = None
    
    # Audit trail
    reads_attempted: list[str] = field(default_factory=list)
    reads_allowed: list[str] = field(default_factory=list)
    reads_denied: list[str] = field(default_factory=list)
    writes_attempted: list[str] = field(default_factory=list)
    writes_allowed: list[str] = field(default_factory=list)
    writes_denied: list[str] = field(default_factory=list)


class SandboxedIO:
    """
    Sandboxed I/O interceptor that delegates to LensWorld + enforcement.
    
    All file operations are routed through:
    - LensWorld for visibility (can I see this path?)
    - enforcement.gate_write() for write permission
    """
    
    def __init__(self, ctx: SandboxContext):
        self.ctx = ctx
        self._original_open = builtins.open
        self._original_exists = os.path.exists
        self._original_isfile = os.path.isfile
        self._original_isdir = os.path.isdir
    
    def _resolve_and_check_read(self, path: Path) -> Path:
        """
        Check if path is readable via paths.resolve() + capability check.
        
        Returns resolved path if allowed, raises FileNotFoundError if not.
        """
        from .. import paths as paths_module
        from ..capability_matrix import get_capability, RootCategory
        
        path_str = str(path)
        self.ctx.reads_attempted.append(path_str)
        
        # Use new paths.resolve() for path classification
        resolved = paths_module.resolve(path_str)
        
        if resolved is None:
            self.ctx.reads_denied.append(path_str)
            raise FileNotFoundError(f"[Sandbox] Path not in any known root: {path}")
        
        # Check read capability for this root
        cap = get_capability("ck3lens", resolved.root, resolved.subdirectory)
        
        if cap and cap.read:
            self.ctx.reads_allowed.append(path_str)
            return path
        
        self.ctx.reads_denied.append(path_str)
        raise FileNotFoundError(f"[Sandbox] Path not readable in ck3lens mode: {path}")
    
    def _check_write(self, path: Path) -> bool:
        """
        Check if write is allowed via enforcement.enforce().
        
        Returns True if allowed, raises PermissionError if not.
        Enforcement handles WIP, local mods, etc. - no shortcuts here.
        """
        from .. import paths as paths_module
        from ..policy.enforcement import enforce, OperationType, Decision
        
        path_str = str(path)
        self.ctx.writes_attempted.append(path_str)
        
        # Resolve path first
        resolved = paths_module.resolve(path_str)
        
        if resolved is None:
            self.ctx.writes_denied.append(path_str)
            raise PermissionError(f"[Sandbox] Path not in any known root: {path}")
        
        # Check if contract is active
        has_contract = self.ctx.contract_id is not None
        
        # Delegate to new enforcement.enforce()
        result = enforce(
            mode="ck3lens",
            operation=OperationType.WRITE,
            resolved=resolved,
            has_contract=has_contract,
        )
        
        if result.decision == Decision.ALLOW:
            self.ctx.writes_allowed.append(path_str)
            return True
        
        self.ctx.writes_denied.append(path_str)
        raise PermissionError(
            f"[Sandbox] Write denied by enforcement: {result.reason}\n"
            f"Path: {path}"
        )
    
    def sandboxed_open(self, file, mode='r', *args, **kwargs):
        """Intercepted open() that checks LensWorld + enforcement."""
        path = Path(file) if not isinstance(file, Path) else file
        
        # Check read permission for read modes
        if 'r' in mode or '+' in mode:
            path = self._resolve_and_check_read(path)
        
        # Check write permission for write modes
        if 'w' in mode or 'a' in mode or 'x' in mode or '+' in mode:
            self._check_write(path)
        
        return self._original_open(file, mode, *args, **kwargs)
    
    def sandboxed_exists(self, path) -> bool:
        """Intercepted os.path.exists() - only visible paths exist."""
        from .. import paths as paths_module
        from ..capability_matrix import get_capability
        
        path_str = str(path)
        
        # Use paths.resolve() to check if path is in a known root
        resolved = paths_module.resolve(path_str)
        
        if resolved is None:
            return False  # Not in any known root = doesn't exist
        
        # Check read capability for this root
        cap = get_capability("ck3lens", resolved.root, resolved.subdirectory)
        
        if not cap or not cap.read:
            return False  # Not readable = doesn't exist for sandbox
        
        return self._original_exists(path)
    
    def install(self):
        """Install sandbox interceptors."""
        builtins.open = self.sandboxed_open
        os.path.exists = self.sandboxed_exists
        os.path.isfile = lambda p: self.sandboxed_exists(p) and self._original_isfile(p)
        os.path.isdir = lambda p: self.sandboxed_exists(p) and self._original_isdir(p)
    
    def uninstall(self):
        """Restore original I/O functions."""
        builtins.open = self._original_open
        os.path.exists = self._original_exists
        os.path.isfile = self._original_isfile
        os.path.isdir = self._original_isdir


@contextlib.contextmanager
def sandboxed_execution(ctx: SandboxContext):
    """
    Context manager for sandboxed script execution.
    
    Usage:
        ctx = SandboxContext(session=session, wip_path=wip_path)
        with sandboxed_execution(ctx):
            exec(script_code)
        print(ctx.writes_allowed)  # Audit what was written
    """
    sandbox = SandboxedIO(ctx)
    sandbox.install()
    try:
        yield ctx
    finally:
        sandbox.uninstall()


def run_script_sandboxed(
    script_path: Path,
    session: Any,  # workspace.Session
    wip_path: Path,
    contract_id: Optional[str] = None,
    token_id: Optional[str] = None,
    script_args: list[str] | None = None,
) -> dict:
    """
    Execute a Python script within the sandbox.
    
    The script runs in the SAME process with monkey-patched I/O.
    All file operations are routed through LensWorld + enforcement.
    
    Args:
        script_path: Path to script (must be in WIP)
        session: Active Session for LensWorld resolution
        wip_path: WIP workspace root
        contract_id: Optional contract for enforcement
        token_id: Optional pre-approved token
        script_args: Command-line args for script
    
    Returns:
        {
            "success": bool,
            "error": str | None,
            "output": str,  # Captured stdout/stderr
            "audit": {
                "reads_attempted": [...],
                "reads_allowed": [...],
                "reads_denied": [...],
                "writes_attempted": [...],
                "writes_allowed": [...],
                "writes_denied": [...],
            }
        }
    """
    # Validate script is in WIP via WorldAdapter
    from ..world_router import get_world
    from ..world_adapter import PathDomain
    
    adapter = get_world(session=session)
    if not adapter:
        return {
            "success": False,
            "error": "WorldAdapter not available",
            "output": "",
            "audit": {},
        }
    
    resolution = adapter.resolve(str(script_path))
    if not resolution.found or resolution.domain != PathDomain.WIP:
        return {
            "success": False,
            "error": f"Script must be in WIP directory: {script_path}",
            "output": "",
            "audit": {},
        }
    
    if not script_path.exists():
        return {
            "success": False,
            "error": f"Script not found: {script_path}",
            "output": "",
            "audit": {},
        }
    
    # Create sandbox context
    # Note: wip_path is kept for context but not used for permission checks
    # (WorldAdapter handles that now)
    ctx = SandboxContext(
        session=session,
        wip_path=wip_path,  # Already a Path, no .resolve() needed
        contract_id=contract_id,
        token_id=token_id,
    )
    
    # Read script content
    script_content = script_path.read_text(encoding="utf-8")
    
    # Prepare execution environment
    script_globals = {
        "__name__": "__main__",
        "__file__": str(script_path),
        "__builtins__": builtins,
    }
    
    # Set up sys.argv if args provided
    old_argv = sys.argv
    if script_args:
        sys.argv = [str(script_path)] + list(script_args)
    else:
        sys.argv = [str(script_path)]
    
    # Capture output
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    
    error_msg = None
    success = False
    
    try:
        with sandboxed_execution(ctx):
            with contextlib.redirect_stdout(stdout_capture):
                with contextlib.redirect_stderr(stderr_capture):
                    exec(compile(script_content, str(script_path), 'exec'), script_globals)
        success = True
    except FileNotFoundError as e:
        error_msg = f"Read denied: {e}"
    except PermissionError as e:
        error_msg = f"Write denied: {e}"
    except Exception as e:
        error_msg = f"Script error: {type(e).__name__}: {e}"
    finally:
        sys.argv = old_argv
    
    return {
        "success": success,
        "error": error_msg,
        "output": stdout_capture.getvalue() + stderr_capture.getvalue(),
        "audit": {
            "reads_attempted": ctx.reads_attempted,
            "reads_allowed": ctx.reads_allowed,
            "reads_denied": ctx.reads_denied,
            "writes_attempted": ctx.writes_attempted,
            "writes_allowed": ctx.writes_allowed,
            "writes_denied": ctx.writes_denied,
        },
    }
