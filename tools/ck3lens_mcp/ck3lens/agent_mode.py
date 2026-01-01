"""
Agent Mode Persistence (Per-Instance)

Mode is stored in ~/.ck3raven/agent_mode_{instance_id}.json
Each VS Code window has its own instance file to prevent cross-window issues.

Extension blanks its own instance file on startup.
Agent initializes via ck3_get_mode_instructions()

This provides per-instance mode state that:
1. Persists across MCP tool calls within a session
2. Is explicitly cleared by the extension on startup (per instance)
3. Requires agent to declare mode before any policy-gated operations
4. Does NOT interfere with other VS Code windows
"""
from pathlib import Path
import json
import os
from typing import Optional, Literal

MODE_DIR = Path.home() / ".ck3raven"
VALID_MODES = frozenset({"ck3lens", "ck3raven-dev"})

AgentMode = Optional[Literal["ck3lens", "ck3raven-dev"]]


def _get_mode_file(instance_id: Optional[str] = None) -> Path:
    """
    Get the mode file path for a specific instance.
    
    Args:
        instance_id: The instance ID (from CK3LENS_INSTANCE_ID env var).
                     If None, reads from environment or uses "default".
    
    Returns:
        Path to the instance-specific mode file.
    """
    if instance_id is None:
        instance_id = os.environ.get("CK3LENS_INSTANCE_ID", "default")
    
    # Sanitize instance_id for filesystem
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in instance_id)
    
    return MODE_DIR / f"agent_mode_{safe_id}.json"


def get_agent_mode(instance_id: Optional[str] = None) -> AgentMode:
    """
    Read current agent mode from instance-specific file.
    
    Args:
        instance_id: The instance ID. If None, reads from CK3LENS_INSTANCE_ID env var.
    
    Returns:
        The current mode ("ck3lens" or "ck3raven-dev"), or None if not initialized.
    """
    mode_file = _get_mode_file(instance_id)
    
    if not mode_file.exists():
        return None
    try:
        data = json.loads(mode_file.read_text())
        mode = data.get("mode")
        if mode in VALID_MODES:
            return mode
        return None
    except (json.JSONDecodeError, IOError):
        return None


def set_agent_mode(mode: AgentMode, instance_id: Optional[str] = None) -> None:
    """
    Set agent mode for this instance. Pass None to blank/reset.
    
    Args:
        mode: "ck3lens", "ck3raven-dev", or None to clear
        instance_id: The instance ID. If None, reads from CK3LENS_INSTANCE_ID env var.
    """
    mode_file = _get_mode_file(instance_id)
    mode_file.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "mode": mode,
        "instance_id": instance_id or os.environ.get("CK3LENS_INSTANCE_ID", "default"),
        "set_at": None,
    }
    # Add timestamp if setting a mode
    if mode is not None:
        from datetime import datetime
        data["set_at"] = datetime.now().isoformat()
    
    mode_file.write_text(json.dumps(data, indent=2))


def clear_agent_mode(instance_id: Optional[str] = None) -> None:
    """
    Clear agent mode for this instance (called by extension on startup).
    
    This ensures each VS Code session starts fresh and the agent
    must explicitly initialize its mode.
    
    Args:
        instance_id: The instance ID. If None, reads from CK3LENS_INSTANCE_ID env var.
    """
    set_agent_mode(None, instance_id)


def get_mode_file_path(instance_id: Optional[str] = None) -> str:
    """
    Return the path to the mode file for this instance.
    
    Args:
        instance_id: The instance ID. If None, reads from CK3LENS_INSTANCE_ID env var.
    """
    return str(_get_mode_file(instance_id))


def cleanup_stale_mode_files(max_age_hours: int = 24) -> dict:
    """
    Clean up old instance mode files.
    
    Called by extension on startup to remove mode files from instances
    that are no longer running.
    
    Args:
        max_age_hours: Delete mode files older than this many hours.
    
    Returns:
        Dict with cleanup stats: {"deleted": [...], "kept": [...], "errors": [...]}
    """
    from datetime import datetime, timedelta
    
    result = {"deleted": [], "kept": [], "errors": []}
    
    if not MODE_DIR.exists():
        return result
    
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    
    for mode_file in MODE_DIR.glob("agent_mode_*.json"):
        try:
            # Check file modification time
            mtime = datetime.fromtimestamp(mode_file.stat().st_mtime)
            if mtime < cutoff:
                mode_file.unlink()
                result["deleted"].append(mode_file.name)
            else:
                result["kept"].append(mode_file.name)
        except Exception as e:
            result["errors"].append({"file": mode_file.name, "error": str(e)})
    
    return result
