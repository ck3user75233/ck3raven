"""
Agent Mode Persistence

Mode is stored in ~/.ck3raven/agent_mode.json
Extension blanks it on startup, agent initializes via ck3_get_mode_instructions()

This provides a single source of truth for agent mode that:
1. Persists across MCP tool calls within a session
2. Is explicitly cleared by the extension on startup
3. Requires agent to declare mode before any policy-gated operations
"""
from pathlib import Path
import json
from typing import Optional, Literal

MODE_FILE = Path.home() / ".ck3raven" / "agent_mode.json"
VALID_MODES = frozenset({"ck3lens", "ck3raven-dev"})

AgentMode = Optional[Literal["ck3lens", "ck3raven-dev"]]


def get_agent_mode() -> AgentMode:
    """
    Read current agent mode from file.
    
    Returns:
        The current mode ("ck3lens" or "ck3raven-dev"), or None if not initialized.
    """
    if not MODE_FILE.exists():
        return None
    try:
        data = json.loads(MODE_FILE.read_text())
        mode = data.get("mode")
        if mode in VALID_MODES:
            return mode
        return None
    except (json.JSONDecodeError, IOError):
        return None


def set_agent_mode(mode: AgentMode) -> None:
    """
    Set agent mode. Pass None to blank/reset.
    
    Args:
        mode: "ck3lens", "ck3raven-dev", or None to clear
    """
    MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "mode": mode,
        "set_at": None,
    }
    # Add timestamp if setting a mode
    if mode is not None:
        from datetime import datetime
        data["set_at"] = datetime.now().isoformat()
    
    MODE_FILE.write_text(json.dumps(data, indent=2))


def clear_agent_mode() -> None:
    """
    Clear agent mode (called by extension on startup).
    
    This ensures each VS Code session starts fresh and the agent
    must explicitly initialize its mode.
    """
    set_agent_mode(None)


def get_mode_file_path() -> str:
    """Return the path to the mode file for external tools."""
    return str(MODE_FILE)
