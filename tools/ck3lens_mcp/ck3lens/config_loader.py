"""
Configuration loader for workspace.toml.

Loads user-editable configuration for ALL machine-specific paths.
OS-defaults are fallbacks only - paths_doctor warns when defaults are used.

CRITICAL: No path is "baked into code as authority." All flow through config.

Path naming convention: All path fields use canonical ROOT_* names from RootCategory enum:
  - root_repo, root_game, root_steam, root_user_docs, root_vscode
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
import platform
import logging

logger = logging.getLogger(__name__)

# Use tomllib (Python 3.11+) or tomli as fallback
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore


@dataclass
class PathsConfig:
    """Parsed paths configuration with source tracking.
    
    Field names match canonical RootCategory enum values (lowercase).
    """

    # ck3raven repository root (REQUIRED for ck3raven-dev mode)
    root_repo: Path | None = None
    
    # CK3 game installation (vanilla files)
    root_game: Path | None = None
    
    # Steam Workshop mods folder
    root_steam: Path | None = None
    
    # CK3 user documents folder (contains launcher-v2.sqlite, dlc_load.json, saves, local mods)
    root_user_docs: Path | None = None
    
    # VS Code user settings folder
    root_vscode: Path | None = None
    
    # Local mods folder (derived from root_user_docs if not set)
    local_mods_folder: Path | None = None

    # Track which paths are using defaults (for doctor warnings)
    using_defaults: set[str] = field(default_factory=set)


@dataclass
class OptionsConfig:
    """Parsed options configuration."""

    validate_paths_on_startup: bool = True
    create_missing_directories: bool = True
    warn_on_default_paths: bool = True


@dataclass
class WorkspaceConfig:
    """Complete workspace configuration."""

    paths: PathsConfig = field(default_factory=PathsConfig)
    options: OptionsConfig = field(default_factory=OptionsConfig)
    config_path: Path | None = None
    errors: list[str] = field(default_factory=list)


def get_config_path() -> Path:
    """Get path to workspace.toml."""
    return Path.home() / ".ck3raven" / "config" / "workspace.toml"


# ─────────────────────────────────────────────────────────────────────
# OS-DEFAULT FALLBACKS (used only when config value is missing)
# ─────────────────────────────────────────────────────────────────────


def _get_os_defaults() -> dict[str, Path]:
    """
    Get OS-specific default paths.

    These are FALLBACKS only. When used, paths_doctor warns.
    They are NOT "baked into code as authority."
    
    NOTE: root_repo, root_game, root_steam have NO defaults - must be configured.
    """
    home = Path.home()

    if platform.system() == "Windows":
        return {
            "root_user_docs": home
            / "Documents"
            / "Paradox Interactive"
            / "Crusader Kings III",
            "root_vscode": home / "AppData" / "Roaming" / "Code" / "User",
        }
    else:
        # macOS/Linux
        return {
            "root_user_docs": home
            / ".local"
            / "share"
            / "Paradox Interactive"
            / "Crusader Kings III",
            "root_vscode": home / ".config" / "Code" / "User",
        }


def load_config() -> WorkspaceConfig:
    """
    Load configuration from workspace.toml.

    Returns WorkspaceConfig with parsed values or OS-defaults.
    Tracks which paths are using defaults in paths.using_defaults.
    Errors are collected in config.errors, not raised.
    
    If workspace.toml doesn't exist, creates it with default template.
    """
    config_path = get_config_path()
    config = WorkspaceConfig(config_path=config_path)
    os_defaults = _get_os_defaults()

    if tomllib is None:
        logger.debug("No TOML parser available, using OS-defaults")
        # Still provide OS-defaults
        _apply_all_defaults(config, os_defaults)
        return config

    data: dict[str, Any] = {}

    if not config_path.exists():
        # Create default config file
        logger.info(f"Creating default config at {config_path}")
        create_default_config()
    
    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            logger.debug(f"Could not parse config: {e}, using OS-defaults")

    # Parse [paths] section with OS-default fallbacks
    paths_section = data.get("paths", {})

    def load_path(key: str, required: bool = False) -> Path | None:
        """Load path from config, falling back to OS-default if available."""
        value = paths_section.get(key)
        if value:
            path = Path(value)
            # Note: we don't check existence here - that's for paths_doctor
            return path

        # Fall back to OS-default if available
        if key in os_defaults:
            config.paths.using_defaults.add(key)
            return os_defaults[key]

        # No default available
        if required:
            config.errors.append(
                f"{key} not configured and no OS-default available"
            )
        return None

    # Load root_repo - NO DEFAULT, must be configured for ck3raven-dev
    config.paths.root_repo = load_path("root_repo", required=False)
    
    # Load all other paths (canonical names)
    config.paths.root_game = load_path("root_game", required=False)
    config.paths.root_steam = load_path("root_steam", required=False)
    config.paths.root_user_docs = load_path("root_user_docs")
    config.paths.root_vscode = load_path("root_vscode")

    # Local mods folder defaults to root_user_docs/mod
    if local_mods := paths_section.get("local_mods_folder"):
        config.paths.local_mods_folder = Path(local_mods)
    elif config.paths.root_user_docs:
        config.paths.local_mods_folder = config.paths.root_user_docs / "mod"
        config.paths.using_defaults.add("local_mods_folder")

    # Parse [options] section
    options_section = data.get("options", {})
    config.options.validate_paths_on_startup = options_section.get(
        "validate_paths_on_startup", True
    )
    config.options.create_missing_directories = options_section.get(
        "create_missing_directories", True
    )
    config.options.warn_on_default_paths = options_section.get(
        "warn_on_default_paths", True
    )

    return config


def _apply_all_defaults(config: WorkspaceConfig, os_defaults: dict[str, Path]) -> None:
    """Apply all OS-defaults when config can't be loaded."""
    # root_repo, root_game, root_steam have NO defaults - they stay None
    config.paths.root_repo = None
    config.paths.root_game = None
    config.paths.root_steam = None
    
    config.paths.root_user_docs = os_defaults.get("root_user_docs")
    config.paths.root_vscode = os_defaults.get("root_vscode")

    if config.paths.root_user_docs:
        config.paths.local_mods_folder = config.paths.root_user_docs / "mod"

    config.paths.using_defaults = set(os_defaults.keys())
    config.paths.using_defaults.add("local_mods_folder")


def create_default_config() -> Path:
    """
    Create default workspace.toml if it doesn't exist.

    Returns path to config file.
    """
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        return config_path

    # Get OS-defaults for template
    defaults = _get_os_defaults()

    default_content = f'''# ~/.ck3raven/config/workspace.toml
# User configuration for machine-specific paths
# Edit this file to match your system, then restart VS Code
#
# ALL paths are configurable. If not set, OS-specific defaults are used
# and paths_doctor will warn about each default being used.

[paths]
# REQUIRED for ck3raven-dev mode - path to ck3raven repository
# This is auto-detected on first run if running from source.
# root_repo = ""

# Required - path to CK3 game installation
root_game = ""

# Required - path to Steam Workshop mods
root_steam = ""

# Optional - CK3 user documents folder
# Contains: launcher-v2.sqlite, dlc_load.json, save games, local mods
# Current OS default: {defaults.get("root_user_docs", "N/A")}
# root_user_docs = ""

# Optional - VS Code user settings folder
# Current OS default: {defaults.get("root_vscode", "N/A")}
# root_vscode = ""

# Optional - override local mods folder
# local_mods_folder = ""

[options]
validate_paths_on_startup = true
create_missing_directories = true
warn_on_default_paths = true
'''

    config_path.write_text(default_content)
    return config_path
