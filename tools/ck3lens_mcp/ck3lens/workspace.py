"""
Workspace and Session Configuration

Manages session state for the MCP server.

CANONICAL MODEL (December 2025):
- Session contains: playset info, db_path, local_mods_folder, mods[]
- mods[] is loaded from active playset at runtime
- local_mods_folder is a path - mods under it are potentially editable
- NO permission oracles here - enforcement.py decides writability
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
class ModEntry:
    """A mod entry from the active playset.
    
    This is pure data - no permission methods.
    """
    mod_id: str
    name: str
    path: Path
    load_order: int = 0
    
    def exists(self) -> bool:
        return self.path.exists()


@dataclass
class Session:
    """Current agent session state.
    
    CANONICAL MODEL:
    - mods[]: List of mods from active playset (ephemeral, loaded at runtime)
    - local_mods_folder: Path to folder where editable mods live
    - NO permission methods - enforcement.py handles that
    """
    playset_id: Optional[int] = None
    playset_name: Optional[str] = None
    db_path: Optional[Path] = None
    mods: list[ModEntry] = field(default_factory=list)
    local_mods_folder: Path = field(default_factory=lambda: DEFAULT_CK3_MOD_DIR)
    
    def get_mod(self, mod_id: str) -> Optional[ModEntry]:
        """Get mod by ID from mods[]."""
        for mod in self.mods:
            if mod.mod_id == mod_id or mod.name == mod_id:
                return mod
        return None
    
    # DEPRECATED - use get_mod instead
    def get_local_mod(self, mod_id: str) -> Optional[ModEntry]:
        """DEPRECATED: Use get_mod() instead."""
        return self.get_mod(mod_id)


# Default CK3 mod directory (this is local_mods_folder)
DEFAULT_CK3_MOD_DIR = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"

# Default ck3raven database
DEFAULT_DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"

# Playsets directory - in ck3raven repo
REPO_PLAYSETS_DIR = Path(__file__).parent.parent.parent.parent / "playsets"

# Legacy location (deprecated)
LEGACY_PLAYSETS_DIR = Path.home() / ".ck3raven" / "playsets"

# Default config file location (portable - uses standard user data location)
DEFAULT_CONFIG_PATH = Path.home() / ".ck3raven" / "ck3lens_config.yaml"


def _expand_path(path_str: str) -> Path:
    """Expand ~ and return Path."""
    return Path(path_str).expanduser()


def load_config(config_path: Optional[Path] = None) -> Session:
    """
    Load configuration from playset or config file.
    
    Searches for config in this order:
    1. Active playset (from ck3raven/playsets/playset_manifest.json)
    2. Explicit config_path if provided
    3. ck3lens_config.yaml in ~/.ck3raven/
    4. Empty defaults (read-only mode)
    """
    session = Session(
        db_path=DEFAULT_DB_PATH,
        mods=[]
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
    """Load the active playset configuration if one exists."""
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
    
    if "local_mods_folder" in data:
        session.local_mods_folder = _expand_path(data["local_mods_folder"])
    
    # Load mods from playset mods[] array
    session.mods = []
    for i, m in enumerate(data.get("mods", [])):
        path_str = m.get("path")
        if path_str:
            path = _expand_path(path_str)
        else:
            # Fallback: construct from local_mods_folder + folder name
            folder = m.get("folder", m.get("mod_id", ""))
            path = session.local_mods_folder / folder
        
        mod = ModEntry(
            mod_id=m.get("mod_id", m.get("name", "")),
            name=m.get("name", m.get("mod_id", "")),
            path=path,
            load_order=m.get("load_order", i),
        )
        session.mods.append(mod)


def _apply_config(session: Session, data: dict[str, Any]) -> None:
    """Apply config data to session."""
    if "db_path" in data and data["db_path"]:
        session.db_path = _expand_path(data["db_path"])
    
    if "local_mods_folder" in data and data["local_mods_folder"]:
        session.local_mods_folder = _expand_path(data["local_mods_folder"])
    
    # Load mods from config
    mods_data = data.get("mods", [])
    
    if mods_data:
        session.mods = []
        for i, m in enumerate(mods_data):
            path = _expand_path(m["path"]) if "path" in m else session.local_mods_folder / m["mod_id"]
            mod = ModEntry(
                mod_id=m["mod_id"],
                name=m.get("name", m["mod_id"]),
                path=path,
                load_order=m.get("load_order", i),
            )
            session.mods.append(mod)


def get_validation_rules_config(config_path: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    """Load validation rules configuration from config file."""
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


def is_under_local_mods_folder(file_path: Path, local_mods_folder: Path) -> bool:
    """
    Check if a path is under the local mods folder.
    
    This is a STRUCTURAL FACT, not a permission oracle.
    Used by enforcement.py at the write boundary.
    """
    try:
        file_path.resolve().relative_to(local_mods_folder.resolve())
        return True
    except ValueError:
        return False


# =============================================================================
# DEPRECATED ALIASES - kept for backwards compatibility
# =============================================================================

# LocalMod is now ModEntry
LocalMod = ModEntry


