"""
WIP Workspace Management

Manages the disposable workspace for agent temporary scripts and outputs.

Location: ~/.ck3raven/wip/ (ROOT_CK3RAVEN_DATA / "wip")

Both modes share the same WIP workspace. WIP is:
- A scratch area for analysis scripts and temporary outputs
- Auto-cleaned of stale files (>24h) on session start
- Writable without contract (enforcement.py handles this via capability matrix)

Rules:
1. Python scripts go in WIP (not in mod directories for ck3lens mode)
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

from .types import AgentMode
from ..paths import ROOT_CK3RAVEN_DATA

# WIP workspace: ROOT_CK3RAVEN_DATA / "wip" — no alias needed
_WIP = ROOT_CK3RAVEN_DATA / "wip"


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


def get_workspace_state(mode: AgentMode = AgentMode.CK3LENS) -> WipWorkspaceState:
    """Get the current WIP workspace state."""
    exists = _WIP.exists()
    files = []
    stale_files = []
    stale_threshold = time.time() - (24 * 60 * 60)  # 24 hours ago
    
    if exists:
        for f in _WIP.rglob("*"):
            if f.is_file():
                rel_path = str(f.relative_to(_WIP))
                files.append(rel_path)
                if f.stat().st_mtime < stale_threshold:
                    stale_files.append(rel_path)
    
    return WipWorkspaceState(
        path=_WIP,
        exists=exists,
        mode=mode,
        file_count=len(files),
        files=files,
        stale_files=stale_files,
    )


def initialize_workspace(
    mode: AgentMode = AgentMode.CK3LENS,
    wipe: bool = False,
) -> dict[str, Any]:
    """
    Initialize the WIP workspace.
    
    Called on session start (ck3_get_mode_instructions).
    
    Args:
        mode: Agent mode (for logging)
        wipe: If True, wipe existing contents (disabled by default to preserve work)
    
    Returns:
        Status dict with path, wiped_count, etc.
    """
    wiped_count = 0
    stale_cleaned = 0
    
    if wipe and _WIP.exists():
        # Count files before wiping
        wiped_count = sum(1 for _ in _WIP.rglob("*") if _.is_file())
        
        # Remove all contents but keep the directory
        for item in _WIP.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    elif _WIP.exists():
        # Just clean stale files (older than 24h)
        stale_threshold = time.time() - (24 * 60 * 60)
        for f in _WIP.rglob("*"):
            if f.is_file() and f.stat().st_mtime < stale_threshold:
                f.unlink()
                stale_cleaned += 1
    
    # Ensure directory exists
    _WIP.mkdir(parents=True, exist_ok=True)
    
    # Write marker file with wipe timestamp
    marker = _WIP / ".wip_session"
    marker.write_text(f"wiped_at: {time.time()}\nmode: {mode.value}\n")
    
    return {
        "path": str(_WIP),
        "mode": mode.value,
        "exists": True,
        "wiped": wipe,
        "wiped_count": wiped_count,
        "stale_cleaned": stale_cleaned,
        "initialized_at": time.time(),
    }


def cleanup_stale_files(mode: AgentMode = AgentMode.CK3LENS) -> dict[str, Any]:
    """
    Clean up files older than 24 hours (best-effort).
    
    Returns:
        Status dict with cleanup results
    """
    if not _WIP.exists():
        return {"path": str(_WIP), "exists": False, "cleaned": 0}
    
    stale_threshold = time.time() - (24 * 60 * 60)
    cleaned = []
    
    for f in _WIP.rglob("*"):
        if f.is_file() and f.name != ".wip_session":
            if f.stat().st_mtime < stale_threshold:
                rel_path = str(f.relative_to(_WIP))
                f.unlink()
                cleaned.append(rel_path)
    
    return {
        "path": str(_WIP),
        "mode": mode.value,
        "exists": True,
        "cleaned": len(cleaned),
        "cleaned_files": cleaned,
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


def validate_script_syntax(rel_path: str) -> ScriptValidation:
    """
    Validate Python script syntax in WIP workspace.
    
    Args:
        rel_path: Path to script relative to WIP root
    
    Returns:
        ScriptValidation with hash and validation result
    """
    file_path = resolve_wip_path(rel_path)
    
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
    allowed_write_mods: set[str],
) -> dict[str, Any]:
    """
    Validate that script declarations are within allowed scope.
    
    Args:
        script_hash: SHA256 of script content
        declarations: What the script claims to read/write
        allowed_write_mods: Set of mod names where writes are allowed
                            (mods whose paths are under local_mods_folder)
    
    Returns:
        Validation result with any errors
    """
    errors = []
    
    # Check writes - only WIP or editable mods allowed
    for write_path in declarations.declared_writes:
        # WIP writes are always allowed
        if write_path.startswith("wip:") or write_path.startswith("~/.ck3raven/wip/"):
            continue
        
        # Check if it's a write to an editable mod
        parts = write_path.split("/", 1)
        if len(parts) >= 1:
            mod_name = parts[0]
            if mod_name not in allowed_write_mods:
                errors.append(f"Write to non-editable mod not allowed: {write_path}")
    
    return {
        "script_hash": script_hash,
        "valid": len(errors) == 0,
        "errors": errors,
        "declared_reads_count": len(declarations.declared_reads),
        "declared_writes_count": len(declarations.declared_writes),
    }


# =============================================================================
# WORKAROUND DETECTION (ck3raven-dev only)
# =============================================================================

# In-memory tracking of script executions per contract
# Key: contract_id, Value: dict of {script_hash: first_execution_timestamp}
_script_execution_tracker: dict[str, dict[str, float]] = {}

# Track when core source files were last modified (for change detection)
_last_core_change_time: dict[str, float] = {}  # Key: contract_id


def track_script_execution(
    contract_id: str,
    script_hash: str,
) -> dict[str, Any]:
    """
    Track a WIP script execution for workaround detection.
    
    Per CK3RAVEN_DEV_POLICY_ARCHITECTURE.md Section 8.6:
    - Same script hash executed twice without core changes = AUTO_DENY
    
    Args:
        contract_id: Active contract ID
        script_hash: SHA256 of script content
    
    Returns:
        Dict with:
        - allowed: bool (False if workaround detected)
        - first_execution: bool (True if first time this script hash runs)
        - reason: str explaining decision
    """
    if contract_id not in _script_execution_tracker:
        _script_execution_tracker[contract_id] = {}
    
    tracker = _script_execution_tracker[contract_id]
    
    if script_hash not in tracker:
        # First execution of this script hash
        tracker[script_hash] = time.time()
        return {
            "allowed": True,
            "first_execution": True,
            "script_hash": script_hash[:16] + "...",
            "reason": "First execution of this script version",
        }
    
    # Script hash seen before - check for core changes
    first_exec_time = tracker[script_hash]
    last_core_change = _last_core_change_time.get(contract_id, 0)
    
    if last_core_change > first_exec_time:
        # Core changes happened after first execution - reset and allow
        tracker[script_hash] = time.time()
        return {
            "allowed": True,
            "first_execution": False,
            "script_hash": script_hash[:16] + "...",
            "reason": "Core source changes detected since last execution - script re-allowed",
        }
    
    # Workaround detected!
    return {
        "allowed": False,
        "first_execution": False,
        "script_hash": script_hash[:16] + "...",
        "reason": "WORKAROUND DETECTED: Same script hash executed twice without core source changes",
        "first_execution_time": first_exec_time,
        "hint": "Make core source changes to address the underlying issue, then the script will be re-allowed",
    }


def record_core_source_change(contract_id: str) -> None:
    """
    Record that core source files have been changed.
    
    Called when ck3_file write/edit modifies files in src/, tools/, etc.
    This resets the workaround detection for the next script execution.
    """
    _last_core_change_time[contract_id] = time.time()


def clear_execution_tracker(contract_id: str) -> dict[str, Any]:
    """
    Clear execution tracking for a contract (e.g., on contract close).
    
    Returns:
        Dict with count of cleared script hashes
    """
    cleared_count = 0
    if contract_id in _script_execution_tracker:
        cleared_count = len(_script_execution_tracker[contract_id])
        del _script_execution_tracker[contract_id]
    if contract_id in _last_core_change_time:
        del _last_core_change_time[contract_id]
    
    return {
        "contract_id": contract_id,
        "cleared_script_hashes": cleared_count,
    }


def get_execution_tracker_state(contract_id: str) -> dict[str, Any]:
    """Get current workaround detection state for debugging."""
    tracker = _script_execution_tracker.get(contract_id, {})
    last_change = _last_core_change_time.get(contract_id)
    
    return {
        "contract_id": contract_id,
        "tracked_script_count": len(tracker),
        "script_hashes": [h[:16] + "..." for h in tracker.keys()],
        "last_core_change": last_change,
    }
