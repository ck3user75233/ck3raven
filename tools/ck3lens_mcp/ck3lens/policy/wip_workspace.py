"""
WIP Workspace Management

Manages the disposable workspace for agent temporary scripts and outputs.

CK3LENS Mode:
  Location: ~/.ck3raven/wip/
  - Auto-wiped at session start
  - General purpose for analysis scripts
  - Script output can go to WIP or active local mods

CK3RAVEN-DEV Mode:
  Location: <repo>/.wip/
  - Git-ignored
  - Strictly constrained to analysis/staging only
  - Cannot substitute for proper code fixes
  - Requires WIP intent declaration

Common Rules:
1. Python is ONLY allowed in WIP (not in mod directories for ck3lens)
2. Script execution via ck3_exec only
3. Scripts must declare what files they read/write
4. Mismatch between declaration and actual behavior → execution denied
"""
from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .types import (
    AgentMode,
    get_wip_workspace_path,
    get_ck3lens_wip_path,
    get_ck3raven_dev_wip_path,
)


# =============================================================================
# WIP WORKSPACE LIFECYCLE
# =============================================================================

@dataclass
class WipWorkspaceState:
    """Current state of the WIP workspace."""
    path: Path
    exists: bool
    mode: AgentMode = AgentMode.CK3LENS
    file_count: int = 0
    files: list[str] = field(default_factory=list)
    last_wiped: Optional[float] = None
    stale_files: list[str] = field(default_factory=list)  # Files older than 24h


def get_workspace_state(
    mode: AgentMode = AgentMode.CK3LENS,
    repo_root: Path | None = None,
) -> WipWorkspaceState:
    """Get the current WIP workspace state for the specified mode."""
    wip_path = get_wip_workspace_path(mode, repo_root)
    exists = wip_path.exists()
    files = []
    stale_files = []
    stale_threshold = time.time() - (24 * 60 * 60)  # 24 hours ago
    
    if exists:
        for f in wip_path.rglob("*"):
            if f.is_file():
                rel_path = str(f.relative_to(wip_path))
                files.append(rel_path)
                if f.stat().st_mtime < stale_threshold:
                    stale_files.append(rel_path)
    
    return WipWorkspaceState(
        path=wip_path,
        exists=exists,
        mode=mode,
        file_count=len(files),
        files=files,
        stale_files=stale_files,
    )


def initialize_workspace(
    mode: AgentMode = AgentMode.CK3LENS,
    repo_root: Path | None = None,
    wipe: bool = True,
) -> dict[str, Any]:
    """
    Initialize the WIP workspace for the specified mode.
    
    Called on session start (ck3_get_mode_instructions).
    
    Args:
        mode: Agent mode (affects WIP location)
        repo_root: Repository root (required for ck3raven-dev mode)
        wipe: If True, wipe existing contents (default behavior on session start)
    
    Returns:
        Status dict with path, wiped_count, etc.
    """
    wip_path = get_wip_workspace_path(mode, repo_root)
    wiped_count = 0
    stale_cleaned = 0
    
    if wipe and wip_path.exists():
        # Count files before wiping
        wiped_count = sum(1 for _ in wip_path.rglob("*") if _.is_file())
        
        # Remove all contents but keep the directory
        for item in wip_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    elif wip_path.exists():
        # Just clean stale files (older than 24h)
        stale_threshold = time.time() - (24 * 60 * 60)
        for f in wip_path.rglob("*"):
            if f.is_file() and f.stat().st_mtime < stale_threshold:
                f.unlink()
                stale_cleaned += 1
    
    # Ensure directory exists
    wip_path.mkdir(parents=True, exist_ok=True)
    
    # Write marker file with wipe timestamp
    marker = wip_path / ".wip_session"
    marker.write_text(f"wiped_at: {time.time()}\nmode: {mode.value}\n")
    
    return {
        "path": str(wip_path),
        "mode": mode.value,
        "exists": True,
        "wiped": wipe,
        "wiped_count": wiped_count,
        "stale_cleaned": stale_cleaned,
        "initialized_at": time.time(),
    }


def cleanup_stale_files(
    mode: AgentMode = AgentMode.CK3LENS,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """
    Clean up files older than 24 hours (best-effort).
    
    Returns:
        Status dict with cleanup results
    """
    wip_path = get_wip_workspace_path(mode, repo_root)
    if not wip_path.exists():
        return {"path": str(wip_path), "exists": False, "cleaned": 0}
    
    stale_threshold = time.time() - (24 * 60 * 60)
    cleaned = []
    
    for f in wip_path.rglob("*"):
        if f.is_file() and f.name != ".wip_session":
            if f.stat().st_mtime < stale_threshold:
                rel_path = str(f.relative_to(wip_path))
                f.unlink()
                cleaned.append(rel_path)
    
    return {
        "path": str(wip_path),
        "mode": mode.value,
        "exists": True,
        "cleaned": len(cleaned),
        "cleaned_files": cleaned,
    }


# =============================================================================
# FILE OPERATIONS IN WIP
# =============================================================================

def is_wip_path(
    path: Path | str,
    mode: AgentMode = AgentMode.CK3LENS,
    repo_root: Path | None = None,
) -> bool:
    """Check if a path is within the WIP workspace for the specified mode."""
    wip_path = get_wip_workspace_path(mode, repo_root)
    if isinstance(path, str):
        path = Path(path)
    
    try:
        path.resolve().relative_to(wip_path.resolve())
        return True
    except ValueError:
        return False


def is_any_wip_path(path: Path | str, repo_root: Path | None = None) -> bool:
    """
    Check if a path is within ANY WIP workspace (either mode).
    
    Useful for general WIP detection without knowing the mode.
    """
    return (
        is_wip_path(path, AgentMode.CK3LENS) or
        is_wip_path(path, AgentMode.CK3RAVEN_DEV, repo_root)
    )


def resolve_wip_path(
    rel_path: str,
    mode: AgentMode = AgentMode.CK3LENS,
    repo_root: Path | None = None,
) -> Path:
    """
    Resolve a relative path within WIP workspace.
    
    Args:
        rel_path: Path relative to WIP root
        mode: Agent mode
        repo_root: Repository root (for ck3raven-dev)
    
    Returns:
        Absolute path within WIP
    """
    wip_path = get_wip_workspace_path(mode, repo_root)
    resolved = (wip_path / rel_path).resolve()
    
    # Ensure it's still within WIP (prevent path traversal)
    try:
        resolved.relative_to(wip_path.resolve())
    except ValueError:
        raise ValueError(f"Path traversal detected: {rel_path}")
    
    return resolved


def write_wip_file(
    rel_path: str,
    content: str | bytes,
    mode: AgentMode = AgentMode.CK3LENS,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """
    Write a file to WIP workspace.
    
    Args:
        rel_path: Path relative to WIP root
        content: File content
        mode: Agent mode
        repo_root: Repository root (for ck3raven-dev)
    
    Returns:
        Status dict with path, size, etc.
    """
    file_path = resolve_wip_path(rel_path, mode, repo_root)
    
    # Ensure parent directory exists
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write content
    if isinstance(content, bytes):
        file_path.write_bytes(content)
    else:
        file_path.write_text(content, encoding="utf-8")
    
    return {
        "path": str(file_path),
        "rel_path": rel_path,
        "mode": mode.value,
        "size": file_path.stat().st_size,
        "written_at": time.time(),
    }


def read_wip_file(
    rel_path: str,
    mode: AgentMode = AgentMode.CK3LENS,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """
    Read a file from WIP workspace.
    
    Args:
        rel_path: Path relative to WIP root
        mode: Agent mode
        repo_root: Repository root (for ck3raven-dev)
    
    Returns:
        Dict with content, path, etc.
    """
    file_path = resolve_wip_path(rel_path, mode, repo_root)
    
    if not file_path.exists():
        return {"error": f"File not found: {rel_path}", "exists": False}
    
    try:
        content = file_path.read_text(encoding="utf-8")
        is_binary = False
    except UnicodeDecodeError:
        content = None
        is_binary = True
    
    return {
        "path": str(file_path),
        "rel_path": rel_path,
        "mode": mode.value,
        "exists": True,
        "is_binary": is_binary,
        "content": content,
        "size": file_path.stat().st_size,
    }


def delete_wip_file(
    rel_path: str,
    mode: AgentMode = AgentMode.CK3LENS,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """
    Delete a file from WIP workspace.
    
    No approval required for WIP files.
    
    Args:
        rel_path: Path relative to WIP root
        mode: Agent mode
        repo_root: Repository root (for ck3raven-dev)
    
    Returns:
        Status dict
    """
    file_path = resolve_wip_path(rel_path, mode, repo_root)
    
    if not file_path.exists():
        return {"path": str(file_path), "existed": False, "deleted": False}
    
    file_path.unlink()
    return {
        "path": str(file_path),
        "rel_path": rel_path,
        "mode": mode.value,
        "existed": True,
        "deleted": True,
    }


# =============================================================================
# SCRIPT VALIDATION AND EXECUTION
# =============================================================================

@dataclass
class ScriptValidation:
    """Result of script syntax validation."""
    script_path: str
    script_hash: str
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    line_count: int = 0


def compute_script_hash(content: str) -> str:
    """Compute SHA256 hash of script content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def validate_script_syntax(
    rel_path: str,
    mode: AgentMode = AgentMode.CK3LENS,
    repo_root: Path | None = None,
) -> ScriptValidation:
    """
    Validate Python script syntax in WIP workspace.
    
    Args:
        rel_path: Path to script relative to WIP root
        mode: Agent mode
        repo_root: Repository root (for ck3raven-dev)
    
    Returns:
        ScriptValidation with hash and validation result
    """
    file_path = resolve_wip_path(rel_path, mode, repo_root)
    
    if not file_path.exists():
        return ScriptValidation(
            script_path=str(file_path),
            script_hash="",
            is_valid=False,
            errors=[f"Script not found: {rel_path}"],
        )
    
    content = file_path.read_text(encoding="utf-8")
    script_hash = compute_script_hash(content)
    errors = []
    
    try:
        compile(content, str(file_path), "exec")
    except SyntaxError as e:
        errors.append(f"Syntax error at line {e.lineno}: {e.msg}")
    except Exception as e:
        errors.append(f"Validation error: {str(e)}")
    
    return ScriptValidation(
        script_path=str(file_path),
        script_hash=script_hash,
        is_valid=len(errors) == 0,
        errors=errors,
        line_count=len(content.splitlines()),
    )


@dataclass
class ScriptDeclaration:
    """
    Declared file access for a script.
    
    Scripts must declare what files they will read/write.
    Mismatch between declaration and actual behavior → execution denied.
    """
    declared_reads: list[str] = field(default_factory=list)
    declared_writes: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "declared_reads": self.declared_reads,
            "declared_writes": self.declared_writes,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScriptDeclaration":
        return cls(
            declared_reads=data.get("declared_reads", []),
            declared_writes=data.get("declared_writes", []),
        )


def validate_script_declarations(
    script_hash: str,
    declarations: ScriptDeclaration,
    local_mods: set[str],
) -> dict[str, Any]:
    """
    Validate that script declarations are within allowed scope.
    
    Args:
        script_hash: SHA256 of script content
        declarations: What the script claims to read/write
        local_mods: Set of allowed local mod names for writes
    
    Returns:
        Validation result with any errors
    """
    errors = []
    
    # Check writes - only WIP or active local mods allowed
    for write_path in declarations.declared_writes:
        # WIP writes are always allowed
        if write_path.startswith("wip:") or write_path.startswith("~/.ck3raven/wip/"):
            continue
        
        # Check if it's a local mod write
        parts = write_path.split("/", 1)
        if len(parts) >= 1:
            mod_name = parts[0]
            if mod_name not in local_mods:
                errors.append(f"Write to non-local mod not allowed: {write_path}")
    
    return {
        "script_hash": script_hash,
        "valid": len(errors) == 0,
        "errors": errors,
        "declared_reads_count": len(declarations.declared_reads),
        "declared_writes_count": len(declarations.declared_writes),
    }
