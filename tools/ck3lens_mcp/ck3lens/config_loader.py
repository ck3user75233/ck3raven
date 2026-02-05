"""
Configuration loader for workspace.toml.

Loads user-editable configuration for ALL machine-specific paths.
OS-defaults are fallbacks only - paths_doctor warns when defaults are used.

CRITICAL: No path is "baked into code as authority." All flow through config.
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
    """Parsed paths configuration with source tracking."""

    game_path: Path | None = None
    workshop_path: Path | None = None
    user_docs_path: Path | None = None
    utilities_path: Path | None = None
    launcher_path: Path | None = None
    vscode_path: Path | None = None
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
    """
    home = Path.home()

    if platform.system() == "Windows":
        return {
            "user_docs_path": home
            / "Documents"
            / "Paradox Interactive"
            / "Crusader Kings III",
            "utilities_path": home / "AppData" / "Local",
            "launcher_path": home
            / "AppData"
            / "Local"
            / "Paradox Interactive"
            / "launcher-v2",
            "vscode_path": home / "AppData" / "Roaming" / "Code" / "User",
        }
    else:
        # macOS/Linux
        return {
            "user_docs_path": home
            / ".local"
            / "share"
            / "Paradox Interactive"
            / "Crusader Kings III",
            "utilities_path": home / ".local" / "share",
            "launcher_path": home
            / ".local"
            / "share"
            / "Paradox Interactive"
            / "launcher-v2",
            "vscode_path": home / ".config" / "Code" / "User",
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

    # Load all paths
    config.paths.game_path = load_path("game_path", required=False)
    config.paths.workshop_path = load_path("workshop_path", required=False)
    config.paths.user_docs_path = load_path("user_docs_path")
    config.paths.utilities_path = load_path("utilities_path")
    config.paths.launcher_path = load_path("launcher_path")
    config.paths.vscode_path = load_path("vscode_path")

    # Local mods folder defaults to user_docs/mod
    if local_mods := paths_section.get("local_mods_folder"):
        config.paths.local_mods_folder = Path(local_mods)
    elif config.paths.user_docs_path:
        config.paths.local_mods_folder = config.paths.user_docs_path / "mod"
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
    config.paths.user_docs_path = os_defaults.get("user_docs_path")
    config.paths.utilities_path = os_defaults.get("utilities_path")
    config.paths.launcher_path = os_defaults.get("launcher_path")
    config.paths.vscode_path = os_defaults.get("vscode_path")

    if config.paths.user_docs_path:
        config.paths.local_mods_folder = config.paths.user_docs_path / "mod"

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
# Required - path to CK3 game installation
game_path = ""

# Required - path to Steam Workshop mods
workshop_path = ""

# Optional - CK3 user documents folder
# Current OS default: {defaults.get("user_docs_path", "N/A")}
# user_docs_path = ""

# Optional - Local utilities folder (launcher DB, caches)
# Current OS default: {defaults.get("utilities_path", "N/A")}
# utilities_path = ""

# Optional - CK3 launcher folder
# Current OS default: {defaults.get("launcher_path", "N/A")}
# launcher_path = ""

# Optional - VS Code user settings folder
# Current OS default: {defaults.get("vscode_path", "N/A")}
# vscode_path = ""

# Optional - override local mods folder
# local_mods_folder = ""

[options]
validate_paths_on_startup = true
create_missing_directories = true
warn_on_default_paths = true
'''

    config_path.write_text(default_content)
    return config_path
