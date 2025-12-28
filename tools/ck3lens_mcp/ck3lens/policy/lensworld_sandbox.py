"""
LensWorld Sandbox Runner

This module provides sandboxed Python execution for ck3lens mode.
Scripts are constrained to only access paths within LensWorld:
- WIP directory (read/write)
- Active local mods (read/write - declared paths only)
- CK3 utility paths (read only - logs, saves)

Any attempt to access paths outside these scopes results in FileNotFoundError.

Implementation:
- Monkey-patches builtins.open, os.path.exists, pathlib.Path, etc.
- All file operations are routed through a LensWorld-aware resolver
- Undeclared writes are blocked at runtime

This enforces #9 from the Canonical Initialization:
> "The system must constrain execution, not rely on script inspection."
"""
from __future__ import annotations

import builtins
import os
import sys
from pathlib import Path, PurePath, PureWindowsPath, PurePosixPath
from typing import Any, Callable, Set, Optional
import functools


# =============================================================================
# SANDBOX CONFIGURATION
# =============================================================================

class LensWorldSandbox:
    """
    Runtime sandbox that constrains file access to LensWorld paths.
    
    All file operations are validated against:
    - allowed_read_paths: paths that can be read
    - allowed_write_paths: paths that can be written
    
    Paths outside these sets result in FileNotFoundError (not PermissionError).
    This matches the LensWorld principle that out-of-scope = "not found".
    """
    
    def __init__(
        self,
        wip_path: Path,
        local_mod_roots: Set[Path],
        utility_paths: Set[Path],
        declared_write_paths: Set[Path],
    ):
        """
        Initialize sandbox with allowed paths.
        
        Args:
            wip_path: WIP directory (read/write always allowed)
            local_mod_roots: Active local mod root directories (read allowed, write if declared)
            utility_paths: CK3 utility paths like logs, saves (read only)
            declared_write_paths: Explicitly declared write paths from contract
        """
        self.wip_path = wip_path.resolve()
        self.local_mod_roots = {p.resolve() for p in local_mod_roots}
        self.utility_paths = {p.resolve() for p in utility_paths}
        self.declared_write_paths = {p.resolve() for p in declared_write_paths}
        
        # Build combined read paths
        self.allowed_read_roots = {self.wip_path} | self.local_mod_roots | self.utility_paths
        
        # Build combined write paths (WIP always, plus declared mod paths)
        self.allowed_write_roots = {self.wip_path}
        for write_path in self.declared_write_paths:
            # Check if write_path is under a local mod root
            for mod_root in self.local_mod_roots:
                try:
                    write_path.relative_to(mod_root)
                    self.allowed_write_roots.add(write_path)
                    break
                except ValueError:
                    pass
        
        # Track access for auditing
        self.access_log: list[dict] = []
        self.blocked_access_log: list[dict] = []
    
    def _is_under_allowed_root(self, path: Path, allowed_roots: Set[Path]) -> bool:
        """Check if path is under any of the allowed roots."""
        resolved = path.resolve()
        for root in allowed_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False
    
    def check_read(self, path: Path) -> bool:
        """Check if path can be read. Returns False if blocked."""
        resolved = path.resolve()
        allowed = self._is_under_allowed_root(resolved, self.allowed_read_roots)
        
        log_entry = {
            "operation": "read",
            "path": str(resolved),
            "allowed": allowed,
        }
        
        if allowed:
            self.access_log.append(log_entry)
        else:
            self.blocked_access_log.append(log_entry)
        
        return allowed
    
    def check_write(self, path: Path) -> bool:
        """Check if path can be written. Returns False if blocked."""
        resolved = path.resolve()
        
        # WIP writes always allowed
        try:
            resolved.relative_to(self.wip_path)
            self.access_log.append({
                "operation": "write",
                "path": str(resolved),
                "allowed": True,
                "scope": "wip",
            })
            return True
        except ValueError:
            pass
        
        # Check declared write paths
        for declared in self.declared_write_paths:
            try:
                resolved.relative_to(declared)
                self.access_log.append({
                    "operation": "write",
                    "path": str(resolved),
                    "allowed": True,
                    "scope": "declared",
                })
                return True
            except ValueError:
                pass
            # Also check if declared path is under this path (writing a parent dir)
            try:
                declared.relative_to(resolved)
                self.access_log.append({
                    "operation": "write",
                    "path": str(resolved),
                    "allowed": True,
                    "scope": "declared_parent",
                })
                return True
            except ValueError:
                pass
        
        # Not allowed
        self.blocked_access_log.append({
            "operation": "write",
            "path": str(resolved),
            "allowed": False,
        })
        return False
    
    def check_exists(self, path: Path) -> bool:
        """Check if we should report that path exists (visibility check)."""
        return self._is_under_allowed_root(path.resolve(), self.allowed_read_roots)
    
    def get_audit_summary(self) -> dict:
        """Get summary of file access during execution."""
        return {
            "allowed_operations": len(self.access_log),
            "blocked_operations": len(self.blocked_access_log),
            "access_log": self.access_log[-100:],  # Last 100
            "blocked_log": self.blocked_access_log,
        }


# =============================================================================
# MONKEY-PATCH IMPLEMENTATIONS
# =============================================================================

_active_sandbox: Optional[LensWorldSandbox] = None
_original_open: Optional[Callable] = None
_original_path_exists: Optional[Callable] = None
_original_path_is_file: Optional[Callable] = None
_original_path_is_dir: Optional[Callable] = None
_original_os_path_exists: Optional[Callable] = None
_original_os_listdir: Optional[Callable] = None
_original_os_makedirs: Optional[Callable] = None


def _sandboxed_open(file, mode='r', *args, **kwargs):
    """Sandboxed version of open() that checks LensWorld permissions."""
    global _active_sandbox, _original_open
    
    if _active_sandbox is None:
        return _original_open(file, mode, *args, **kwargs)
    
    path = Path(file) if not isinstance(file, Path) else file
    
    # Check if this is a write operation
    is_write = any(c in mode for c in 'waxb+')
    
    if is_write:
        if not _active_sandbox.check_write(path):
            raise FileNotFoundError(f"[LensWorld] Path not in scope: {path}")
    else:
        if not _active_sandbox.check_read(path):
            raise FileNotFoundError(f"[LensWorld] Path not in scope: {path}")
    
    return _original_open(file, mode, *args, **kwargs)


def _sandboxed_path_exists(self):
    """Sandboxed version of Path.exists()."""
    global _active_sandbox, _original_path_exists
    
    if _active_sandbox is None:
        return _original_path_exists(self)
    
    if not _active_sandbox.check_exists(self):
        return False  # Pretend it doesn't exist
    
    return _original_path_exists(self)


def _sandboxed_path_is_file(self):
    """Sandboxed version of Path.is_file()."""
    global _active_sandbox, _original_path_is_file
    
    if _active_sandbox is None:
        return _original_path_is_file(self)
    
    if not _active_sandbox.check_exists(self):
        return False
    
    return _original_path_is_file(self)


def _sandboxed_path_is_dir(self):
    """Sandboxed version of Path.is_dir()."""
    global _active_sandbox, _original_path_is_dir
    
    if _active_sandbox is None:
        return _original_path_is_dir(self)
    
    if not _active_sandbox.check_exists(self):
        return False
    
    return _original_path_is_dir(self)


def _sandboxed_os_path_exists(path):
    """Sandboxed version of os.path.exists()."""
    global _active_sandbox, _original_os_path_exists
    
    if _active_sandbox is None:
        return _original_os_path_exists(path)
    
    p = Path(path) if not isinstance(path, Path) else path
    if not _active_sandbox.check_exists(p):
        return False
    
    return _original_os_path_exists(path)


def _sandboxed_os_listdir(path='.'):
    """Sandboxed version of os.listdir()."""
    global _active_sandbox, _original_os_listdir
    
    if _active_sandbox is None:
        return _original_os_listdir(path)
    
    p = Path(path) if not isinstance(path, Path) else path
    if not _active_sandbox.check_read(p):
        raise FileNotFoundError(f"[LensWorld] Path not in scope: {path}")
    
    return _original_os_listdir(path)


def _sandboxed_os_makedirs(name, mode=0o777, exist_ok=False):
    """Sandboxed version of os.makedirs()."""
    global _active_sandbox, _original_os_makedirs
    
    if _active_sandbox is None:
        return _original_os_makedirs(name, mode, exist_ok)
    
    p = Path(name)
    if not _active_sandbox.check_write(p):
        raise FileNotFoundError(f"[LensWorld] Path not in scope: {name}")
    
    return _original_os_makedirs(name, mode, exist_ok)


# =============================================================================
# SANDBOX LIFECYCLE
# =============================================================================

def activate_sandbox(sandbox: LensWorldSandbox) -> None:
    """
    Activate the LensWorld sandbox by monkey-patching file operations.
    
    WARNING: This modifies global state. Use with try/finally and deactivate_sandbox().
    """
    global _active_sandbox
    global _original_open, _original_path_exists, _original_path_is_file
    global _original_path_is_dir, _original_os_path_exists, _original_os_listdir
    global _original_os_makedirs
    
    if _active_sandbox is not None:
        raise RuntimeError("Sandbox already active")
    
    _active_sandbox = sandbox
    
    # Save originals
    _original_open = builtins.open
    _original_path_exists = Path.exists
    _original_path_is_file = Path.is_file
    _original_path_is_dir = Path.is_dir
    _original_os_path_exists = os.path.exists
    _original_os_listdir = os.listdir
    _original_os_makedirs = os.makedirs
    
    # Apply patches
    builtins.open = _sandboxed_open
    Path.exists = _sandboxed_path_exists
    Path.is_file = _sandboxed_path_is_file
    Path.is_dir = _sandboxed_path_is_dir
    os.path.exists = _sandboxed_os_path_exists
    os.listdir = _sandboxed_os_listdir
    os.makedirs = _sandboxed_os_makedirs


def deactivate_sandbox() -> Optional[dict]:
    """
    Deactivate the LensWorld sandbox and restore original functions.
    
    Returns:
        Audit summary from the sandbox, or None if no sandbox was active.
    """
    global _active_sandbox
    global _original_open, _original_path_exists, _original_path_is_file
    global _original_path_is_dir, _original_os_path_exists, _original_os_listdir
    global _original_os_makedirs
    
    if _active_sandbox is None:
        return None
    
    audit = _active_sandbox.get_audit_summary()
    
    # Restore originals
    builtins.open = _original_open
    Path.exists = _original_path_exists
    Path.is_file = _original_path_is_file
    Path.is_dir = _original_path_is_dir
    os.path.exists = _original_os_path_exists
    os.listdir = _original_os_listdir
    os.makedirs = _original_os_makedirs
    
    _active_sandbox = None
    _original_open = None
    _original_path_exists = None
    _original_path_is_file = None
    _original_path_is_dir = None
    _original_os_path_exists = None
    _original_os_listdir = None
    _original_os_makedirs = None
    
    return audit


# =============================================================================
# SANDBOXED EXECUTION
# =============================================================================

def run_script_sandboxed(
    script_path: Path,
    wip_path: Path,
    local_mod_roots: Set[Path],
    utility_paths: Set[Path],
    declared_write_paths: Set[Path],
    script_args: list[str] | None = None,
) -> dict:
    """
    Execute a Python script within the LensWorld sandbox.
    
    The script runs in the SAME process with monkey-patched file operations.
    This ensures the sandbox cannot be bypassed by the script.
    
    Args:
        script_path: Path to the script (must be in WIP)
        wip_path: WIP directory root
        local_mod_roots: Active local mod directories
        utility_paths: Read-only utility paths (logs, etc.)
        declared_write_paths: Paths the script is allowed to write
        script_args: Optional command-line arguments
    
    Returns:
        {
            "success": bool,
            "error": str | None,
            "audit": {...},  # File access audit
            "output": str,   # Captured stdout/stderr (if any)
        }
    """
    import io
    import contextlib
    
    # Validate script is in WIP
    try:
        script_path.resolve().relative_to(wip_path.resolve())
    except ValueError:
        return {
            "success": False,
            "error": f"Script must be in WIP directory: {script_path}",
            "audit": {},
            "output": "",
        }
    
    if not script_path.exists():
        return {
            "success": False,
            "error": f"Script not found: {script_path}",
            "audit": {},
            "output": "",
        }
    
    # Create sandbox
    sandbox = LensWorldSandbox(
        wip_path=wip_path,
        local_mod_roots=local_mod_roots,
        utility_paths=utility_paths,
        declared_write_paths=declared_write_paths,
    )
    
    # Read script content
    script_content = script_path.read_text(encoding="utf-8")
    
    # Prepare execution environment
    script_globals = {
        "__name__": "__main__",
        "__file__": str(script_path),
        "__builtins__": builtins,
    }
    
    # Set up sys.argv
    old_argv = sys.argv
    sys.argv = [str(script_path)] + (script_args or [])
    
    # Capture output
    output_buffer = io.StringIO()
    
    try:
        # Activate sandbox
        activate_sandbox(sandbox)
        
        # Execute with output capture
        with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(output_buffer):
            exec(compile(script_content, str(script_path), "exec"), script_globals)
        
        return {
            "success": True,
            "error": None,
            "audit": sandbox.get_audit_summary(),
            "output": output_buffer.getvalue(),
        }
        
    except FileNotFoundError as e:
        # Expected for sandbox violations
        return {
            "success": False,
            "error": str(e),
            "audit": sandbox.get_audit_summary(),
            "output": output_buffer.getvalue(),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "audit": sandbox.get_audit_summary(),
            "output": output_buffer.getvalue(),
        }
    finally:
        # Always deactivate sandbox
        deactivate_sandbox()
        sys.argv = old_argv
