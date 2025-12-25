"""
Workspace and Live Mod Configuration

Manages live mod paths (whitelisted for agent writes) and session state.
NO file copying - all reads come from ck3raven DB or filesystem wrappers.

Configuration is loaded from ck3lens_config.yaml in the AI Workspace.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

# Try to import yaml, fall back to json-only if not available
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


@dataclass
class LiveMod:
    """A mod the agent is allowed to write to."""
    mod_id: str
    name: str
    path: Path
    
    def exists(self) -> bool:
        return self.path.exists()


@dataclass
class Session:
    """Current agent session state."""
    playset_id: Optional[int] = None
    playset_name: Optional[str] = None
    db_path: Optional[Path] = None
    live_mods: list[LiveMod] = field(default_factory=list)
    mod_root: Path = field(default_factory=lambda: DEFAULT_CK3_MOD_DIR)
    
    def get_live_mod(self, mod_id: str) -> Optional[LiveMod]:
        """Get live mod by ID."""
        for mod in self.live_mods:
            if mod.mod_id == mod_id:
                return mod
        return None
    
    def is_path_allowed(self, path: Path) -> bool:
        """Check if path is within a live mod directory."""
        resolved = path.resolve()
        for mod in self.live_mods:
            mod_resolved = mod.path.resolve()
            try:
                resolved.relative_to(mod_resolved)
                return True
            except ValueError:
                continue
        return False


# Default CK3 mod directory
DEFAULT_CK3_MOD_DIR = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"

# Default ck3raven database
DEFAULT_DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"

# Whitelisted live mods (agent can write to these)
DEFAULT_LIVE_MODS = [
    LiveMod(
        mod_id="MSC",
        name="Mini Super Compatch",
        path=DEFAULT_CK3_MOD_DIR / "Mini Super Compatch"
    ),
    LiveMod(
        mod_id="MSCRE",
        name="MSC Religion Expanded",
        path=DEFAULT_CK3_MOD_DIR / "MSCRE"
    ),
    LiveMod(
        mod_id="LRE",
        name="Lowborn Rise Expanded",
        path=DEFAULT_CK3_MOD_DIR / "Lowborn Rise Expanded"
    ),
    LiveMod(
        mod_id="MRP",
        name="More Raid and Prisoners",
        path=DEFAULT_CK3_MOD_DIR / "More Raid and Prisoners"
    ),
]

# Default config file location
DEFAULT_CONFIG_PATH = Path.home() / "Documents" / "AI Workspace" / "ck3lens_config.yaml"


def _expand_path(path_str: str) -> Path:
    """Expand ~ and return Path."""
    return Path(path_str).expanduser()


def load_config(config_path: Optional[Path] = None) -> Session:
    """
    Load configuration from YAML/JSON file or use defaults.
    
    Searches for config in this order:
    1. Explicit config_path if provided
    2. ck3lens_config.yaml in AI Workspace
    3. ck3lens_config.json in AI Workspace
    4. Hardcoded defaults
    
    Config file format (YAML):
        db_path: "~/.ck3raven/ck3raven.db"
        local_mods_path: "~/Documents/Paradox Interactive/Crusader Kings III/mod"
        live_mods:
          - mod_id: MSC
            name: Mini Super Compatch
            path: "~/Documents/.../Mini Super Compatch"
    """
    session = Session(
        db_path=DEFAULT_DB_PATH,
        live_mods=[m for m in DEFAULT_LIVE_MODS if m.exists()]
    )
    
    # Find config file
    if config_path is None:
        if DEFAULT_CONFIG_PATH.exists():
            config_path = DEFAULT_CONFIG_PATH
        else:
            json_path = DEFAULT_CONFIG_PATH.with_suffix('.json')
            if json_path.exists():
                config_path = json_path
    
    if config_path and config_path.exists():
        try:
            content = config_path.read_text(encoding="utf-8")
            
            # Parse YAML or JSON
            if config_path.suffix in ('.yaml', '.yml') and HAS_YAML:
                data = yaml.safe_load(content)
            else:
                data = json.loads(content)
            
            if data:
                _apply_config(session, data)
                
        except Exception as e:
            print(f"Warning: Failed to load config from {config_path}: {e}")
    
    return session


def _apply_config(session: Session, data: dict[str, Any]) -> None:
    """Apply config data to session."""
    if "db_path" in data and data["db_path"]:
        session.db_path = _expand_path(data["db_path"])
    
    if "local_mods_path" in data and data["local_mods_path"]:
        session.mod_root = _expand_path(data["local_mods_path"])
    
    if "live_mods" in data and data["live_mods"]:
        session.live_mods = []
        for m in data["live_mods"]:
            path = _expand_path(m["path"]) if "path" in m else session.mod_root / m["mod_id"]
            mod = LiveMod(
                mod_id=m["mod_id"],
                name=m.get("name", m["mod_id"]),
                path=path
            )
            if mod.exists():
                session.live_mods.append(mod)


def get_validation_rules_config(config_path: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    """
    Load validation rules configuration from config file.
    
    Returns dict mapping rule_name -> {enabled: bool, severity: str}
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH
    
    if not config_path.exists():
        return {}
    
    try:
        content = config_path.read_text(encoding="utf-8")
        if config_path.suffix in ('.yaml', '.yml') and HAS_YAML:
            data = yaml.safe_load(content)
        else:
            data = json.loads(content)
        
        return data.get("validation_rules", {})
    except Exception:
        return {}
    
    return session


def validate_relpath(relpath: str) -> tuple[bool, str]:
    """
    Validate a relative path for safety.
    
    Returns (is_valid, error_message).
    """
    p = Path(relpath)
    
    # No absolute paths
    if p.is_absolute():
        return False, "Path must be relative"
    
    # No parent traversal
    if ".." in p.parts:
        return False, "Path must not contain '..'"
    
    # Must have valid top-level
    allowed_toplevel = {"common", "events", "gfx", "localization", "interface", "music", "sound", "history", "map_data", "descriptor.mod"}
    if p.parts and p.parts[0] not in allowed_toplevel:
        # Allow descriptor.mod at root
        if relpath != "descriptor.mod":
            return False, f"Top-level must be one of {sorted(allowed_toplevel)}"
    
    return True, ""

