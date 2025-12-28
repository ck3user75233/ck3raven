"""
Workspace and Local Mod Configuration

Manages local mod paths (whitelisted for agent writes) and session state.
NO file copying - all reads come from ck3raven DB or filesystem wrappers.

Local mods are loaded from:
1. Active playset configuration (playsets/*.json)
2. VS Code settings (ck3lens.localMods)
3. ck3lens_config.yaml in AI Workspace

If no local mods are configured, the agent operates in read-only mode.
This is perfectly valid - not everyone needs write access.
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
class LocalMod:
    """A mod the agent is allowed to write to (user-configured)."""
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
    local_mods: list[LocalMod] = field(default_factory=list)
    mod_root: Path = field(default_factory=lambda: DEFAULT_CK3_MOD_DIR)
    
    def get_local_mod(self, mod_id: str) -> Optional[LocalMod]:
        """Get local mod by ID."""
        for mod in self.local_mods:
            if mod.mod_id == mod_id:
                return mod
        return None
    
    def is_path_allowed(self, path: Path) -> bool:
        """Check if path is within a local mod directory."""
        resolved = path.resolve()
        for mod in self.local_mods:
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

# Playsets directory - in ck3raven repo, not ~/.ck3raven/
# This is the design of record - same location as MCP tools use
REPO_PLAYSETS_DIR = Path(__file__).parent.parent.parent.parent / "playsets"

# Legacy location (deprecated)
LEGACY_PLAYSETS_DIR = Path.home() / ".ck3raven" / "playsets"

# Default config file location
DEFAULT_CONFIG_PATH = Path.home() / "Documents" / "AI Workspace" / "ck3lens_config.yaml"


def _expand_path(path_str: str) -> Path:
    """Expand ~ and return Path."""
    return Path(path_str).expanduser()


def load_config(config_path: Optional[Path] = None) -> Session:
    """
    Load configuration from playset or config file.
    
    Searches for config in this order:
    1. Active playset (from ck3raven/playsets/playset_manifest.json)
    2. Explicit config_path if provided
    3. ck3lens_config.yaml in AI Workspace
    4. Empty defaults (read-only mode)
    
    Config file format (YAML):
        db_path: "~/.ck3raven/ck3raven.db"
        mod_root: "~/Documents/Paradox Interactive/Crusader Kings III/mod"
        local_mods:
          - mod_id: MyMod
            name: My Custom Mod
            path: "~/Documents/.../MyMod"
    
    If no local_mods configured, agent operates in read-only mode.
    """
    session = Session(
        db_path=DEFAULT_DB_PATH,
        local_mods=[]  # Start empty - user must configure
    )
    
    # Try to load active playset first
    active_playset = _load_active_playset()
    if active_playset:
        _apply_playset(session, active_playset)
        return session
    
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


def _load_active_playset() -> Optional[dict]:
    """Load the active playset configuration if one exists.
    
    Uses the playset_manifest.json in ck3raven/playsets/ directory
    (same source as MCP tools like ck3_playset).
    """
    manifest_file = REPO_PLAYSETS_DIR / "playset_manifest.json"
    
    if not manifest_file.exists():
        return None
    
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        active_filename = manifest.get("active")
        
        if not active_filename:
            return None
        
        playset_file = REPO_PLAYSETS_DIR / active_filename
        
        if playset_file.exists():
            return json.loads(playset_file.read_text(encoding="utf-8"))
    except Exception:
        pass
    
    return None


def _apply_playset(session: Session, data: dict) -> None:
    """Apply playset configuration to session."""
    session.playset_name = data.get("name")
    
    if "mod_root" in data:
        session.mod_root = _expand_path(data["mod_root"])
    
    # Load local mods from playset
    session.local_mods = []
    for m in data.get("local_mods", []):
        path = _expand_path(m["path"]) if "path" in m else session.mod_root / m.get("folder", m["mod_id"])
        mod = LocalMod(
            mod_id=m.get("mod_id", m.get("name", "")),
            name=m.get("name", m.get("mod_id", "")),
            path=path
        )
        if mod.exists():
            session.local_mods.append(mod)


def _apply_config(session: Session, data: dict[str, Any]) -> None:
    """Apply config data to session."""
    if "db_path" in data and data["db_path"]:
        session.db_path = _expand_path(data["db_path"])
    
    if "mod_root" in data and data["mod_root"]:
        session.mod_root = _expand_path(data["mod_root"])
    # Legacy support
    elif "local_mods_path" in data and data["local_mods_path"]:
        session.mod_root = _expand_path(data["local_mods_path"])
    
    # Load local_mods from config
    local_mods_data = data.get("local_mods", [])
    # Legacy support for live_mods key
    if not local_mods_data:
        local_mods_data = data.get("live_mods", [])
    
    if local_mods_data:
        session.local_mods = []
        for m in local_mods_data:
            path = _expand_path(m["path"]) if "path" in m else session.mod_root / m["mod_id"]
            mod = LocalMod(
                mod_id=m["mod_id"],
                name=m.get("name", m["mod_id"]),
                path=path
            )
            if mod.exists():
                session.local_mods.append(mod)


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


