"""
Builder Configuration

Loads configuration from YAML file or environment variables.
Supports multiple installations and custom paths.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any
import yaml


# Default configuration file locations (checked in order)
CONFIG_SEARCH_PATHS = [
    Path.home() / ".ck3raven" / "builder_config.yaml",
    Path(__file__).parent / "builder_config.yaml",
]


# Default paths for Windows Steam installation
DEFAULT_CONFIG = {
    "vanilla_path": r"C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\game",
    "workshop_path": r"C:\Program Files (x86)\Steam\steamapps\workshop\content\1158310",
    "local_mods_path": str(Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"),
    "database_path": str(Path.home() / ".ck3raven" / "ck3raven.db"),
    
    # Alternative Steam library paths to check
    "steam_library_paths": [
        r"C:\Program Files (x86)\Steam",
        r"C:\Program Files\Steam",
        r"D:\Steam",
        r"D:\SteamLibrary",
        r"E:\Steam",
        r"E:\SteamLibrary",
    ],
    
    # Build settings
    "max_file_size_bytes": 2_000_000,  # Skip files larger than this for parsing
    "parse_timeout_seconds": 30,        # Timeout for parsing individual files
    "batch_size": 500,                  # Files per batch for chunked processing
}


class BuilderConfig:
    """Configuration for the database builder."""
    
    def __init__(self, config_path: Optional[Path] = None):
        self._config: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self._config_path: Optional[Path] = None
        
        # Load from file if found
        self._load_config(config_path)
        
        # Override with environment variables
        self._apply_env_overrides()
    
    def _load_config(self, explicit_path: Optional[Path] = None) -> None:
        """Load configuration from YAML file."""
        search_paths = [explicit_path] if explicit_path else CONFIG_SEARCH_PATHS
        
        for config_path in search_paths:
            if config_path and config_path.exists():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        user_config = yaml.safe_load(f) or {}
                    self._config.update(user_config)
                    self._config_path = config_path
                    return
                except Exception as e:
                    print(f"Warning: Failed to load config from {config_path}: {e}")
    
    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides."""
        env_mappings = {
            "CK3_VANILLA_PATH": "vanilla_path",
            "CK3_WORKSHOP_PATH": "workshop_path",
            "CK3_LOCAL_MODS_PATH": "local_mods_path",
            "CK3RAVEN_DB_PATH": "database_path",
        }
        
        for env_var, config_key in env_mappings.items():
            if env_var in os.environ:
                self._config[config_key] = os.environ[env_var]
    
    @property
    def config_path(self) -> Optional[Path]:
        """Path to loaded config file, or None if using defaults."""
        return self._config_path
    
    @property
    def vanilla_path(self) -> Path:
        """Path to CK3 vanilla game folder."""
        path = Path(self._config["vanilla_path"])
        if path.exists():
            return path
        
        # Try to auto-detect from Steam library paths
        for steam_lib in self._config.get("steam_library_paths", []):
            candidate = Path(steam_lib) / "steamapps" / "common" / "Crusader Kings III" / "game"
            if candidate.exists():
                return candidate
        
        return path  # Return configured path even if not found
    
    @property
    def workshop_path(self) -> Path:
        """Path to Steam Workshop mods folder."""
        path = Path(self._config["workshop_path"])
        if path.exists():
            return path
        
        # Try to auto-detect from Steam library paths
        for steam_lib in self._config.get("steam_library_paths", []):
            candidate = Path(steam_lib) / "steamapps" / "workshop" / "content" / "1158310"
            if candidate.exists():
                return candidate
        
        return path
    
    @property
    def local_mods_path(self) -> Path:
        """Path to local mods folder."""
        return Path(self._config["local_mods_path"])
    
    @property
    def database_path(self) -> Path:
        """Path to the database file."""
        return Path(self._config["database_path"])
    
    @property
    def max_file_size(self) -> int:
        """Maximum file size to parse (bytes)."""
        return self._config.get("max_file_size_bytes", 2_000_000)
    
    @property
    def parse_timeout(self) -> int:
        """Timeout for parsing individual files (seconds)."""
        return self._config.get("parse_timeout_seconds", 30)
    
    @property
    def batch_size(self) -> int:
        """Number of files per processing batch."""
        return self._config.get("batch_size", 500)
    
    def to_dict(self) -> Dict[str, Any]:
        """Export current configuration as dict."""
        return {
            "vanilla_path": str(self.vanilla_path),
            "workshop_path": str(self.workshop_path),
            "local_mods_path": str(self.local_mods_path),
            "database_path": str(self.database_path),
            "max_file_size_bytes": self.max_file_size,
            "parse_timeout_seconds": self.parse_timeout,
            "batch_size": self.batch_size,
            "config_file": str(self._config_path) if self._config_path else None,
        }


# Global config instance (lazy-loaded)
_config: Optional[BuilderConfig] = None


def get_config(config_path: Optional[Path] = None) -> BuilderConfig:
    """Get the global config instance, loading if needed."""
    global _config
    if _config is None or config_path is not None:
        _config = BuilderConfig(config_path)
    return _config


def write_default_config(path: Optional[Path] = None) -> Path:
    """
    Write a default configuration file.
    
    Returns the path where config was written.
    """
    if path is None:
        path = Path.home() / ".ck3raven" / "builder_config.yaml"
    
    path.parent.mkdir(parents=True, exist_ok=True)
    
    config_content = """# CK3 Raven Builder Configuration
# 
# This file configures paths for the database builder.
# You can override any setting here or via environment variables.

# CK3 game installation
vanilla_path: "C:\\\\Program Files (x86)\\\\Steam\\\\steamapps\\\\common\\\\Crusader Kings III\\\\game"

# Steam Workshop mods
workshop_path: "C:\\\\Program Files (x86)\\\\Steam\\\\steamapps\\\\workshop\\\\content\\\\1158310"

# Local mods folder
# local_mods_path: "~/Documents/Paradox Interactive/Crusader Kings III/mod"

# Database location
# database_path: "~/.ck3raven/ck3raven.db"

# Alternative Steam library paths (auto-detection)
steam_library_paths:
  - "C:\\\\Program Files (x86)\\\\Steam"
  - "C:\\\\Program Files\\\\Steam"
  - "D:\\\\Steam"
  - "D:\\\\SteamLibrary"

# Build settings
max_file_size_bytes: 2000000    # Skip files larger than 2MB
parse_timeout_seconds: 30        # Timeout for parsing large files
batch_size: 500                  # Files per batch
"""
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(config_content)
    
    return path
