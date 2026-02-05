"""
Canonical path CONSTANTS for CK3 Lens.

ALL paths are CONSTANTS loaded at module import time.
Import directly: `from ck3lens.paths import ROOT_REPO, ROOT_GAME`

9 Root Categories:
- ROOT_REPO: from config (required for ck3raven-dev, optional for ck3lens)
- ROOT_CK3RAVEN_DATA: always ~/.ck3raven
- ROOT_GAME: from config (required)
- ROOT_STEAM: from config (required)
- ROOT_USER_DOCS: from config or OS-default
- ROOT_UTILITIES: from config or OS-default
- ROOT_LAUNCHER: from config or OS-default
- ROOT_VSCODE: from config or OS-default
- ROOT_EXTERNAL: not a path (catch-all classifier)

CRITICAL: ROOT_REPO is CONFIG-BASED, not computed from __file__.
This is required because __file__ computation breaks when the package
is pip-installed into a venv at a different location.
"""

from pathlib import Path
from enum import Enum
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# LOAD CONFIG AT MODULE IMPORT
# =============================================================================

def _load_paths_from_config():
    """Load paths from workspace.toml. Creates default if missing."""
    from ck3lens.config_loader import load_config
    return load_config()

_config = _load_paths_from_config()


# =============================================================================
# ROOT CATEGORY ENUM (for classify_path return type)
# =============================================================================

class RootCategory(Enum):
    """Canonical root categories for path classification."""
    ROOT_REPO = "ROOT_REPO"
    ROOT_CK3RAVEN_DATA = "ROOT_CK3RAVEN_DATA"
    ROOT_GAME = "ROOT_GAME"
    ROOT_STEAM = "ROOT_STEAM"
    ROOT_USER_DOCS = "ROOT_USER_DOCS"
    ROOT_UTILITIES = "ROOT_UTILITIES"
    ROOT_LAUNCHER = "ROOT_LAUNCHER"
    ROOT_VSCODE = "ROOT_VSCODE"
    ROOT_EXTERNAL = "ROOT_EXTERNAL"


# =============================================================================
# PATH CONSTANTS
# =============================================================================

# From config (NO __file__ computation - that breaks in venvs)
# ROOT_REPO is None if not configured - paths_doctor will warn
ROOT_REPO: Path | None = _config.paths.root_repo

# Always computed (not from config)
ROOT_CK3RAVEN_DATA: Path = Path.home() / ".ck3raven"

# From config (required)
ROOT_GAME: Path | None = _config.paths.game_path
ROOT_STEAM: Path | None = _config.paths.workshop_path

# From config (with OS-default fallback)
ROOT_USER_DOCS: Path | None = _config.paths.user_docs_path
ROOT_UTILITIES: Path | None = _config.paths.utilities_path
ROOT_LAUNCHER: Path | None = _config.paths.launcher_path
ROOT_VSCODE: Path | None = _config.paths.vscode_path


# =============================================================================
# DERIVED PATHS (subdirectories of ROOT_CK3RAVEN_DATA)
# =============================================================================

WIP_DIR: Path = ROOT_CK3RAVEN_DATA / "wip"
DB_PATH: Path = ROOT_CK3RAVEN_DATA / "ck3raven.db"
PLAYSET_DIR: Path = ROOT_CK3RAVEN_DATA / "playsets"
LOGS_DIR: Path = ROOT_CK3RAVEN_DATA / "logs"
CONFIG_DIR: Path = ROOT_CK3RAVEN_DATA / "config"

# Local mods folder - from config or derived from ROOT_USER_DOCS
LOCAL_MODS_FOLDER: Path | None = (
    _config.paths.local_mods_folder 
    or (ROOT_USER_DOCS / "mod" if ROOT_USER_DOCS else None)
)


# =============================================================================
# LOG WARNINGS FOR MISSING CONFIG
# =============================================================================

if _config.options.warn_on_default_paths and _config.paths.using_defaults:
    for path_name in _config.paths.using_defaults:
        logger.warning(f"Using OS-default for {path_name} - configure in ~/.ck3raven/config/workspace.toml")

if _config.errors:
    for error in _config.errors:
        logger.warning(f"Config error: {error}")
