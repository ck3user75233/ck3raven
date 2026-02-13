"""
Workspace and Session Configuration

Manages session state for the MCP server.

CANONICAL MODEL (January 2026):
- Session contains: playset info, db_path, local_mods_folder, mods[]
- mods[0] is ALWAYS vanilla (injected automatically, load_order=0)
- mods[1:] are user mods from playset
- mods[] is NEVER empty - vanilla is always present even if playset fails to load
- Each mod has .cvid resolved from database
- DB filtering = {m.cvid for m in mods if m.cvid}
- local_mods_folder is a path - mods under it are potentially editable
- NO permission oracles here - enforcement.py decides writability

BANNED CONCEPTS (do not recreate):
- vanilla_cvid (vanilla is mods[0])
- PlaysetLens (just use mods[].cvid)
- local_mods[] / editable_mods[] (derive from mods[] + local_mods_folder)
- ui_hint_potentially_editable (no UI consumes this - deleted)
- is_writable / can_write / can_edit (permission oracles)

CONFLICT ANALYSIS MODEL:
- File-level: Same relpath in multiple mods = file conflict
  - Exact match filename = full override (later wins)
  - Prefixed filename (zzz_traits.txt) = partial override/append intent
- Block-level (Symbol-level): Same block ID within a relpath = ID conflict
  - on_action blocks: CONTAINER_MERGE - blocks with SAME ID override, different IDs append
  - traits/events/decisions: OVERRIDE - last definition wins
  - Only blocks/symbols with IDENTICAL names conflict
- Use mods[] load order to determine winners (higher index = later load = wins)
- Agent can derive all conflict info from mods[].cvid + relpath + block names

"""
from __future__ import annotations
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any, TYPE_CHECKING, Set

from ck3lens.paths import ROOT_USER_DOCS, ROOT_GAME, ROOT_CK3RAVEN_DATA

if TYPE_CHECKING:
    from .db_queries import DBQueries

# Try to import yaml, fall back to json-only if not available
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# Module logger
_logger = logging.getLogger(__name__)


@dataclass
class ModEntry:
    """A mod entry from the active playset.
    
    mods[0] is always vanilla (name="vanilla", load_order=0).
    mods[1:] are user mods in load order.
    
    cvid is resolved from database when playset is loaded.
    """
    mod_id: str
    name: str
    path: Path
    load_order: int = 0
    cvid: Optional[int] = None  # resolved from DB at load time
    workshop_id: Optional[str] = None  # Steam Workshop ID if available
    
    def exists(self) -> bool:
        return self.path.exists()
    
    @property
    def is_indexed(self) -> bool:
        """True if this mod has been indexed in the database."""
        return self.cvid is not None
    
    @property
    def is_vanilla(self) -> bool:
        """True if this is the vanilla game (always mods[0])."""
        return self.mod_id == "vanilla"


@dataclass
class Session:
    """Current agent session state.
    
    CANONICAL MODEL:
    - mods[0] = vanilla (always present, injected automatically)
    - mods[1:] = user mods from playset in load order
    - mods[] is NEVER empty - vanilla is always present
    - DB filtering = {m.cvid for m in mods if m.cvid}
    - local_mods_folder: Path to folder where editable mods live
    - NO permission methods - enforcement.py handles that
    """
    playset_name: Optional[str] = None
    db_path: Optional[Path] = None
    mods: list[ModEntry] = field(default_factory=list)
    local_mods_folder: Path = field(default_factory=lambda: ROOT_USER_DOCS / "mod")
    
    def get_mod(self, mod_id: str) -> Optional[ModEntry]:
        """Get mod by ID or name from mods[]."""
        for mod in self.mods:
            if mod.mod_id == mod_id or mod.name == mod_id:
                return mod
        return None
    
    @property
    def vanilla(self) -> Optional[ModEntry]:
        """Get vanilla (mods[0]). Always returns a value since vanilla is always present."""
        return self.mods[0] if self.mods else None
    
    def get_unresolved_mods(self) -> list[ModEntry]:
        """Get mods that haven't been indexed yet (no cvid)."""
        return [m for m in self.mods if m.cvid is None]
    
    def is_fully_indexed(self) -> bool:
        """True if all mods (including vanilla) have cvids resolved."""
        return all(m.cvid is not None for m in self.mods)
    
    def resolve_cvids(self, db: "DBQueries") -> dict:
        """Resolve cvids from database for all mods (including vanilla at mods[0]).
        
        Call this when playset is activated.
        
        Args:
            db: DBQueries instance with active connection
            
        Returns:
            Dict with resolution stats:
            - mods_resolved: int
            - mods_missing: list of mod names not found in DB
        """
        # Delegate to db_queries - it handles vanilla as mods[0]
        return db.get_cvids(self.mods)
    
    # DEPRECATED - use get_mod instead
    def get_local_mod(self, mod_id: str) -> Optional[ModEntry]:
        """DEPRECATED: Use get_mod() instead."""
        return self.get_mod(mod_id)


# Playsets directory - canonical location from paths.py
# NOTE: Import PLAYSET_DIR at function scope to avoid circular imports
# The canonical path is: ~/.ck3raven/playsets/

# Legacy location (deprecated)
LEGACY_PLAYSETS_DIR = Path.home() / ".ck3raven" / "playsets"

# Default config file location (portable - uses standard user data location)
DEFAULT_CONFIG_PATH = Path.home() / ".ck3raven" / "ck3lens_config.yaml"


def _expand_path(path_str: str) -> Path:
    """Expand ~ and return Path."""
    return Path(path_str).expanduser()


def _load_json_robust(path: Path) -> Optional[dict]:
    """Load JSON file, handling UTF-8 BOM if present.
    
    Windows tools (especially PowerShell) often write UTF-8 with BOM.
    This function strips the BOM if present and continues.
    """
    try:
        content = path.read_text(encoding="utf-8")
        # Strip BOM if present (common from Windows/PowerShell)
        if content.startswith('\ufeff'):
            content = content[1:]
        return json.loads(content)
    except json.JSONDecodeError as e:
        _logger.warning(f"Failed to parse JSON from {path}: {e}")
        return None
    except Exception as e:
        _logger.warning(f"Failed to load {path}: {e}")
        return None


def _create_vanilla_entry(vanilla_path: Optional[Path] = None) -> ModEntry:
    """Create the vanilla ModEntry (always mods[0])."""
    if vanilla_path is None:
        vanilla_path = ROOT_GAME
    
    return ModEntry(
        mod_id="vanilla",
        name="vanilla",
        path=vanilla_path,
        load_order=0,
    )


def load_config(config_path: Optional[Path] = None) -> Session:
    """
    Load configuration from playset or config file.
    
    IMPORTANT: mods[] is NEVER empty. Vanilla is always mods[0].
    If playset loading fails, session still has vanilla as mods[0].
    
    Searches for config in this order:
    1. Active playset (from ck3raven/playsets/playset_manifest.json)
    2. Explicit config_path if provided
    3. ck3lens_config.yaml in ~/.ck3raven/
    4. Defaults with vanilla as mods[0]
    """
    # Start with vanilla as mods[0] - ALWAYS present
    session = Session(
        db_path=ROOT_CK3RAVEN_DATA / "ck3raven.db",
        mods=[_create_vanilla_entry()]
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
            # Strip BOM if present
            if content.startswith('\ufeff'):
                content = content[1:]
            
            # Parse YAML or JSON
            if config_path.suffix in ('.yaml', '.yml') and HAS_YAML:
                data = yaml.safe_load(content)
            else:
                data = json.loads(content)
            
            if data:
                _apply_config(session, data)
                
        except Exception as e:
            _logger.warning(f"Failed to load config from {config_path}: {e}")
            # Session still has vanilla as mods[0]
    
    return session


def _load_active_playset() -> Optional[dict]:
    """Load the active playset configuration if one exists.
    
    Handles UTF-8 BOM gracefully (common from Windows/PowerShell tools).
    Returns None if no active playset or if loading fails.
    """
    from .paths import PLAYSET_DIR  # Import here to avoid circular imports
    
    manifest_file = PLAYSET_DIR / "playset_manifest.json"
    
    if not manifest_file.exists():
        return None
    
    manifest = _load_json_robust(manifest_file)
    if manifest is None:
        return None
    
    active_filename = manifest.get("active")
    if not active_filename:
        return None
    
    playset_file = PLAYSET_DIR / active_filename
    
    if not playset_file.exists():
        _logger.warning(f"Active playset file not found: {playset_file}")
        return None
    
    return _load_json_robust(playset_file)


def _apply_playset(session: Session, data: dict) -> None:
    """Apply playset configuration to session.
    
    Injects vanilla as mods[0] automatically.
    cvids are NOT resolved here - call session.resolve_cvids(db) after DB connection.
    """
    session.playset_name = data.get("playset_name", data.get("name"))
    
    if "local_mods_folder" in data:
        session.local_mods_folder = _expand_path(data["local_mods_folder"])
    
    # Get vanilla path from playset or data
    vanilla_data = data.get("vanilla", {})
    vanilla_path_str = vanilla_data.get("path") if isinstance(vanilla_data, dict) else data.get("vanilla_path")
    if vanilla_path_str:
        vanilla_path = _expand_path(vanilla_path_str)
    else:
        vanilla_path = ROOT_GAME
    session.mods = [_create_vanilla_entry(vanilla_path)]
    
    # Add user mods from playset mods[] array
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
            load_order=m.get("load_order", i + 1),  # Use explicit load_order if present, else i+1
            workshop_id=m.get("steam_id", m.get("workshop_id")),
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
        # Get vanilla path
        vanilla_path = data.get("vanilla_path")
        if vanilla_path:
            vanilla_path = _expand_path(vanilla_path)
        else:
            vanilla_path = ROOT_GAME
        
        # Start with vanilla as mods[0]
        session.mods = [_create_vanilla_entry(vanilla_path)]
        
        for i, m in enumerate(mods_data):
            path = _expand_path(m["path"]) if "path" in m else session.local_mods_folder / m["mod_id"]
            mod = ModEntry(
                mod_id=m["mod_id"],
                name=m.get("name", m["mod_id"]),
                path=path,
                load_order=i + 1,
                workshop_id=m.get("workshop_id"),
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
        # Strip BOM if present
        if content.startswith('\ufeff'):
            content = content[1:]
            
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


# =============================================================================
# DEPRECATED ALIASES - kept for backwards compatibility
# =============================================================================

# LocalMod is now ModEntry
LocalMod = ModEntry

