"""
Workspace and Live Mod Configuration

Manages live mod paths (whitelisted for agent writes) and session state.
NO file copying - all reads come from ck3raven DB.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


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
        mod_id="PVP2",
        name="PVP2",
        path=DEFAULT_CK3_MOD_DIR / "PVP2"
    ),
    LiveMod(
        mod_id="MSC",
        name="Mini Super Compatch",
        path=DEFAULT_CK3_MOD_DIR / "Mini Super Compatch"
    ),
    LiveMod(
        mod_id="MSCRE",
        name="MSCRE",
        path=DEFAULT_CK3_MOD_DIR / "MSCRE"
    ),
    LiveMod(
        mod_id="LRE",
        name="Lowborn Rise Expanded",
        path=DEFAULT_CK3_MOD_DIR / "Lowborn Rise Expanded"
    ),
    LiveMod(
        mod_id="MRP",
        name="More Raiding and Prisoners",
        path=DEFAULT_CK3_MOD_DIR / "More Raiding and Prisoners"
    ),
]


def load_config(config_path: Optional[Path] = None) -> Session:
    """
    Load configuration from JSON file or use defaults.
    
    Config file format:
    {
        "db_path": "~/.ck3raven/ck3raven.db",
        "live_mods": [
            {"mod_id": "MSC", "name": "Mini Super Compatch", "path": "..."}
        ]
    }
    """
    session = Session(
        db_path=DEFAULT_DB_PATH,
        live_mods=[m for m in DEFAULT_LIVE_MODS if m.exists()]
    )
    
    if config_path and config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            
            if "db_path" in data:
                session.db_path = Path(data["db_path"]).expanduser()
            
            if "live_mods" in data:
                session.live_mods = []
                for m in data["live_mods"]:
                    mod = LiveMod(
                        mod_id=m["mod_id"],
                        name=m.get("name", m["mod_id"]),
                        path=Path(m["path"]).expanduser()
                    )
                    if mod.exists():
                        session.live_mods.append(mod)
        except Exception as e:
            print(f"Warning: Failed to load config from {config_path}: {e}")
    
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

