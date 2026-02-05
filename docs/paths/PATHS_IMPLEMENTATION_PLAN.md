# Paths Refactor Implementation Plan

> **Status:** DRAFT - Awaiting Review  
> **Date:** February 4, 2026  
> **Design Brief:** [PATHS_DESIGN_BRIEF_v2.md](PATHS_DESIGN_BRIEF_v2.md)  
> **Purpose:** Run-book quality implementation plan for paths architecture refactor

---

## Table of Contents

1. [Scope and Non-Goals](#1-scope-and-non-goals)
2. [Decisions Log](#2-decisions-log)
3. [Phase 0: Configuration Layer](#phase-0-configuration-layer)
4. [Phase A: ROOTS Data Model](#phase-a-roots-data-model)
5. [Phase B: Resolution Function](#phase-b-resolution-function)
6. [Phase C: Capability Matrix](#phase-c-capability-matrix)
7. [Phase D: Enforcement Consolidation](#phase-d-enforcement-consolidation)
8. [Phase E: Call Site Migration](#phase-e-call-site-migration)
9. [Phase F: Validation and CI Gates](#phase-f-validation-and-ci-gates)
10. [Risk Register](#10-risk-register)
11. [Acceptance Criteria](#11-acceptance-criteria)

---

## 1. Scope and Non-Goals

### 1.1 In Scope

| Area | Description |
|------|-------------|
| **ROOTS Registry** | Create single source of truth for all path constants |
| **Path Resolution** | Implement `paths.resolve()` for root classification |
| **Capability Matrix** | Consolidate to pure data structure keyed by `(mode, root, subdir)` |
| **Enforcement** | Single `enforce()` function replacing per-domain functions |
| **Banned Terms** | Remove all banned path aliases and getter functions |
| **CI Gates** | Add grep-based guards against banned patterns |
| **Config Layer** | Load ALL configurable roots from `workspace.toml` |

### 1.2 Non-Goals (Explicit Exclusions)

| Exclusion | Rationale |
|-----------|-----------|
| **WorldAdapter rewrite** | Beyond scope - only update path resolution calls |
| **MCP tool refactoring** | Only update to use new paths API - no logic changes |
| **Database schema changes** | Unrelated to paths architecture |
| **Contract system changes** | Use existing contract validation unchanged |
| **Token system changes** | Tokens remain as-is |
| **UI/extension changes** | Extension consumes MCP unchanged |
| **QBuilder daemon changes** | Daemon path handling out of scope |

### 1.3 Dependencies

| Dependency | Status | Risk if Missing |
|------------|--------|-----------------|
| `workspace.toml` config file | May not exist | Phase 0 creates it |
| arch_lint for banned terms | Exists | None |
| pytest infrastructure | Exists | None |
| Active contract for writes | Required | Standard workflow |

---

## 2. Decisions Log

### Must-Answer Questions (All Resolved)

| # | Question | Decision | Justification |
|---|----------|----------|---------------|
| D1 | Where does WIP live? | `~/.ck3raven/wip/` always | No mode-conditional paths |
| D2 | Is ROOT_TEMP needed? | **NO - Deleted** | Use `wip/` or `cache/` instead |
| D3 | How handle configurable roots? | Load from `workspace.toml` at startup | User edits config, restart to apply |
| D4 | Per-root getter functions? | **NO - Use registry directly** | Single `get_root()` for dynamic roots only |
| D5 | Per-domain enforcement? | **NO - Single `enforce()`** | Matrix + invariants is complete |
| D6 | How classify unknown paths? | `ROOT_EXTERNAL` catch-all | Always denied by matrix |
| D7 | Are ROOT_LAUNCHER and ROOT_UTILITIES separate? | **YES** | Launcher is subset but has distinct semantics |
| D8 | Contract required for all writes? | **YES** | Global invariant, no exceptions |
| D9 | db/ and daemon/ writable? | **NEVER** | Single-Writer Architecture invariant |
| D10 | What about in-memory paths? | Out of scope | Only filesystem paths covered |
| D11 | Are platform defaults hard-coded? | **NO** | All roots config-driven with OS-default fallback + doctor warning |
| D12 | ROOT_USER_DOCS write scope? | **mod/ subdir only** | User docs broadly readable, local mods writable |
| D13 | CK3RAVEN_DATA root-level access? | **Read-only** | Explicit matrix entry for subdirectory=None |

### Design Choices with Alternatives Rejected

| Choice | Selected | Rejected | Why |
|--------|----------|----------|-----|
| Resolution order | Specificity-first | Alphabetical | `ROOT_LAUNCHER` is subset of `ROOT_UTILITIES` |
| Matrix key format | `(mode, root, subdir)` | Nested dict | Flat structure is grep-friendly |
| Invariant handling | Check before matrix | Check after | Fail-fast on obvious violations |
| Config format | TOML | JSON/YAML | Matches `pyproject.toml` precedent |
| Path normalization | No-IO string normalization | Path.resolve() | Avoid filesystem dependency |
| Platform defaults | Config fallback + warning | Hard-coded | Truly eliminates hard-coded paths |

---

## Phase 0: Configuration Layer

**Objective:** Eliminate ALL hard-coded machine-specific paths via config file. ALL roots flow through config (OS-defaults are fallbacks, not authority).

### 0.1 Files Changed

| File | Action | Description |
|------|--------|-------------|
| `~/.ck3raven/config/workspace.toml` | **CREATE** | User-editable config for ALL machine-specific paths |
| `tools/ck3lens_mcp/ck3lens/config_loader.py` | **CREATE** | Config loading with validation |
| `tools/ck3lens_mcp/ck3lens/session.py` | **MODIFY** | Load config at session init |

### 0.2 workspace.toml Schema

```toml
# ~/.ck3raven/config/workspace.toml
# User configuration for machine-specific paths
# Edit this file to match your system, then restart VS Code
#
# ALL paths are configurable. If not set, OS-specific defaults are used
# and paths_doctor will warn about each default being used.

[paths]
# Required - path to CK3 game installation
game_path = "C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III"

# Required - path to Steam Workshop mods
workshop_path = "C:/Program Files (x86)/Steam/steamapps/workshop/content/1158310"

# Optional - CK3 user documents folder
# Default (Windows): ~/Documents/Paradox Interactive/Crusader Kings III
# Default (Linux): ~/.local/share/Paradox Interactive/Crusader Kings III
# user_docs_path = ""

# Optional - Local utilities folder (launcher DB, caches)
# Default (Windows): ~/AppData/Local
# Default (Linux): ~/.local/share
# utilities_path = ""

# Optional - CK3 launcher folder
# Default (Windows): ~/AppData/Local/Paradox Interactive/launcher-v2
# Default (Linux): ~/.local/share/Paradox Interactive/launcher-v2
# launcher_path = ""

# Optional - VS Code user settings folder
# Default (Windows): ~/AppData/Roaming/Code/User
# Default (Linux): ~/.config/Code/User
# vscode_path = ""

# Optional - override local mods folder (default: {user_docs_path}/mod)
# local_mods_folder = ""

[options]
# Validate paths on startup (default: true)
validate_paths_on_startup = true

# Create missing directories (default: true)
create_missing_directories = true

# Warn when using OS-default paths (default: true)
warn_on_default_paths = true
```

### 0.3 config_loader.py Implementation

```python
"""
Configuration loader for workspace.toml.

Loads user-editable configuration for ALL machine-specific paths.
OS-defaults are fallbacks only - paths_doctor warns when defaults are used.

CRITICAL: No path is "baked into code as authority." All flow through config.
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable
import platform
import logging

logger = logging.getLogger(__name__)

# Use tomllib (Python 3.11+) or tomli as fallback
try:
    import tomllib
except ImportError:
    import tomli as tomllib

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
            "user_docs_path": home / "Documents" / "Paradox Interactive" / "Crusader Kings III",
            "utilities_path": home / "AppData" / "Local",
            "launcher_path": home / "AppData" / "Local" / "Paradox Interactive" / "launcher-v2",
            "vscode_path": home / "AppData" / "Roaming" / "Code" / "User",
        }
    else:
        # macOS/Linux
        return {
            "user_docs_path": home / ".local" / "share" / "Paradox Interactive" / "Crusader Kings III",
            "utilities_path": home / ".local" / "share",
            "launcher_path": home / ".local" / "share" / "Paradox Interactive" / "launcher-v2",
            "vscode_path": home / ".config" / "Code" / "User",
        }

def load_config() -> WorkspaceConfig:
    """
    Load configuration from workspace.toml.
    
    Returns WorkspaceConfig with parsed values or OS-defaults.
    Tracks which paths are using defaults in paths.using_defaults.
    Errors are collected in config.errors, not raised.
    """
    config_path = get_config_path()
    config = WorkspaceConfig(config_path=config_path)
    os_defaults = _get_os_defaults()
    
    data: dict = {}
    
    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            config.errors.append(f"Invalid TOML: {e}")
    else:
        config.errors.append(f"Config file not found: {config_path}")
    
    # Parse [paths] section with OS-default fallbacks
    paths_section = data.get("paths", {})
    
    def load_path(key: str, required: bool = False) -> Path | None:
        """Load path from config, falling back to OS-default if available."""
        value = paths_section.get(key)
        if value:
            path = Path(value)
            if not path.exists():
                config.errors.append(f"{key} does not exist: {value}")
            return path
        
        # Fall back to OS-default if available
        if key in os_defaults:
            config.paths.using_defaults.add(key)
            return os_defaults[key]
        
        # No default available
        if required:
            config.errors.append(f"{key} not configured and no OS-default available")
        return None
    
    # Load all paths
    config.paths.game_path = load_path("game_path", required=True)
    config.paths.workshop_path = load_path("workshop_path", required=True)
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
```

### 0.4 Phase 0 Validation

| Command | Expected Result |
|---------|-----------------|
| `python -c "from ck3lens.config_loader import load_config; c = load_config(); print(c.paths.using_defaults)"` | Prints set of paths using OS-defaults |
| `python -c "from ck3lens.config_loader import create_default_config; print(create_default_config())"` | Creates file with OS-defaults shown |
| `grep -r "Program Files" tools/ck3lens_mcp/ck3lens/` | **Zero matches** (hard-coded paths eliminated) |
| `grep -r "steamapps" tools/ck3lens_mcp/ck3lens/` | **Zero matches** (hard-coded paths eliminated) |
| `grep -r "AppData" tools/ck3lens_mcp/ck3lens/` | **Zero matches** except in `_get_os_defaults()` |
| `grep -r "Documents/Paradox" tools/ck3lens_mcp/ck3lens/` | **Zero matches** except in `_get_os_defaults()` |

### 0.5 Phase 0 Success Criteria

- [ ] `workspace.toml` schema includes ALL platform-specific paths
- [ ] `config_loader.py` created with `load_config()` and `create_default_config()`
- [ ] `PathsConfig.using_defaults` tracks which paths use OS-defaults
- [ ] OS-defaults isolated in `_get_os_defaults()` only
- [ ] Session loads config at startup
- [ ] No hard-coded machine-specific paths in MCP code (except fallback function)
- [ ] Config validation errors collected, not raised

---

## Phase A: ROOTS Data Model

**Objective:** Create `ck3lens/paths.py` with ROOTS registry. Registry is built from config, NOT hard-coded.

### A.1 Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tools/ck3lens_mcp/ck3lens/paths.py` | **CREATE** | ROOTS registry, RootCategory enum |
| `tools/ck3lens_mcp/ck3lens/__init__.py` | **MODIFY** | Export paths module |

### A.2 paths.py Implementation (Data Model Only)

```python
"""
Canonical path resolution for CK3 Lens.

This module is THE authority for:
1. Root category definitions (RootCategory enum)
2. ROOTS registry (built from config, NOT hard-coded)
3. Convenience accessors for derived paths

NO OTHER MODULE may define path constants.
NO per-root getter functions (except get_root for dynamic roots).
NO hard-coded platform paths (all flow through config_loader).
"""

from enum import Enum, auto
from pathlib import Path
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# ROOT CATEGORIES
# ─────────────────────────────────────────────────────────────────────

class RootCategory(Enum):
    """Canonical root categories for path classification."""
    
    ROOT_REPO = auto()           # ck3raven source repository
    ROOT_USER_DOCS = auto()      # CK3 user documents (saves, local mods)
    ROOT_STEAM = auto()          # Steam library (workshop mods)
    ROOT_GAME = auto()           # CK3 game installation (vanilla)
    ROOT_UTILITIES = auto()      # AppData/Local (launcher DB, cache)
    ROOT_LAUNCHER = auto()       # Launcher registry (subset of UTILITIES)
    ROOT_CK3RAVEN_DATA = auto()  # ~/.ck3raven/ runtime data
    ROOT_VSCODE = auto()         # VS Code user settings
    ROOT_EXTERNAL = auto()       # Catch-all for unclassified (always denied)

# ─────────────────────────────────────────────────────────────────────
# ROOTS REGISTRY (built from config, not hard-coded)
# ─────────────────────────────────────────────────────────────────────

def _build_roots_registry() -> dict[RootCategory, Path | None]:
    """
    Build roots registry from config.
    
    ALL platform-specific paths come from config_loader.
    This function does NOT hard-code any platform paths.
    
    Called once at module load.
    """
    from ck3lens.config_loader import load_config
    
    config = load_config()
    home = Path.home()
    
    # Log warnings for defaults being used
    if config.options.warn_on_default_paths and config.paths.using_defaults:
        for path_name in config.paths.using_defaults:
            logger.warning(f"Using OS-default for {path_name} - consider configuring in workspace.toml")
    
    return {
        # Config-driven paths (required)
        RootCategory.ROOT_GAME: config.paths.game_path,
        RootCategory.ROOT_STEAM: config.paths.workshop_path,
        
        # Config-driven paths (with OS-default fallback)
        RootCategory.ROOT_USER_DOCS: config.paths.user_docs_path,
        RootCategory.ROOT_UTILITIES: config.paths.utilities_path,
        RootCategory.ROOT_LAUNCHER: config.paths.launcher_path,
        RootCategory.ROOT_VSCODE: config.paths.vscode_path,
        
        # Always ~/.ck3raven (not platform-dependent)
        RootCategory.ROOT_CK3RAVEN_DATA: home / ".ck3raven",
        
        # Note: ROOT_REPO is detected at runtime (not in registry)
        # Note: ROOT_EXTERNAL is not a real path
    }

# Registry built once at module load
ROOTS: dict[RootCategory, Path | None] = _build_roots_registry()

# ─────────────────────────────────────────────────────────────────────
# DYNAMIC ROOT DETECTION
# ─────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _detect_repo_root() -> Path | None:
    """Detect ck3raven repo root by walking up from this file."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return None

def get_root(root: RootCategory) -> Path | None:
    """
    Get absolute path for a root category.
    
    Returns None if:
    - ROOT_EXTERNAL (not a real path)
    - ROOT_REPO not detected
    - Path not configured and no OS-default available
    """
    if root == RootCategory.ROOT_EXTERNAL:
        return None
    if root == RootCategory.ROOT_REPO:
        return _detect_repo_root()
    return ROOTS.get(root)

# ─────────────────────────────────────────────────────────────────────
# CONVENIENCE ACCESSORS
# ─────────────────────────────────────────────────────────────────────

def get_wip_dir() -> Path:
    """Get WIP workspace directory. Always ROOT_CK3RAVEN_DATA/wip/."""
    data_root = ROOTS.get(RootCategory.ROOT_CK3RAVEN_DATA)
    if data_root is None:
        raise RuntimeError("ROOT_CK3RAVEN_DATA not available")
    return data_root / "wip"

def get_db_path() -> Path:
    """Get database path."""
    data_root = ROOTS.get(RootCategory.ROOT_CK3RAVEN_DATA)
    if data_root is None:
        raise RuntimeError("ROOT_CK3RAVEN_DATA not available")
    return data_root / "db" / "ck3raven.db"

def get_playset_dir() -> Path:
    """Get playsets directory."""
    data_root = ROOTS.get(RootCategory.ROOT_CK3RAVEN_DATA)
    if data_root is None:
        raise RuntimeError("ROOT_CK3RAVEN_DATA not available")
    return data_root / "playsets"

def get_logs_dir() -> Path:
    """Get logs directory."""
    data_root = ROOTS.get(RootCategory.ROOT_CK3RAVEN_DATA)
    if data_root is None:
        raise RuntimeError("ROOT_CK3RAVEN_DATA not available")
    return data_root / "logs"

def get_local_mods_folder() -> Path:
    """Get local mods folder (writable mods location)."""
    from ck3lens.config_loader import load_config
    
    config = load_config()
    if config.paths.local_mods_folder:
        return config.paths.local_mods_folder
    
    user_docs = ROOTS.get(RootCategory.ROOT_USER_DOCS)
    if user_docs:
        return user_docs / "mod"
    
    raise RuntimeError("Cannot determine local_mods_folder")
```

### A.3 Phase A Validation

| Command | Expected Result |
|---------|-----------------|
| `python -c "from ck3lens.paths import RootCategory; print(list(RootCategory))"` | Lists all 9 root categories |
| `python -c "from ck3lens.paths import ROOTS; print(ROOTS)"` | Prints registry dict (values from config) |
| `python -c "from ck3lens.paths import get_wip_dir; print(get_wip_dir())"` | Prints `~/.ck3raven/wip` |
| `python -c "from ck3lens.paths import get_root, RootCategory; print(get_root(RootCategory.ROOT_REPO))"` | Prints repo path or None |
| `grep -rn "Documents.*Paradox" tools/ck3lens_mcp/ck3lens/paths.py` | **Zero matches** |
| `grep -rn "AppData" tools/ck3lens_mcp/ck3lens/paths.py` | **Zero matches** |

### A.4 Phase A Success Criteria

- [ ] `RootCategory` enum with all 9 categories
- [ ] `ROOTS` registry built from config (not hard-coded)
- [ ] `get_root()` single function for dynamic roots
- [ ] Convenience accessors for common paths
- [ ] No per-root getter functions like `_get_wip_root()`
- [ ] **No platform-specific paths in paths.py** (all come from config_loader)
- [ ] Unit tests for registry and accessors

---

## Phase B: Resolution Function

**Objective:** Implement `paths.resolve()` for structural path classification using NO-IO normalization.

### B.1 Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tools/ck3lens_mcp/ck3lens/paths.py` | **MODIFY** | Add `resolve()` function and `ResolvedPath` dataclass |

### B.2 Resolution Implementation (No-IO Normalization)

```python
# Add to paths.py

from dataclasses import dataclass
import os

@dataclass(frozen=True)
class ResolvedPath:
    """
    Result of path resolution.
    
    This is STRUCTURAL information only - it identifies what root
    a path belongs to. It does NOT contain permission information.
    """
    root: RootCategory
    absolute: Path
    relative: str          # Relative to root (empty string if path IS root)
    subdirectory: str | None  # First path component under root

def _normalize_path_no_io(path: str | Path) -> Path:
    """
    Normalize path WITHOUT filesystem IO.
    
    This avoids Path.resolve() which:
    - Hits the filesystem (can fail for non-existent paths)
    - Resolves symlinks (can change path unexpectedly)
    - Behaves differently on Windows vs Unix
    
    Instead, we:
    1. Expand ~ to home directory
    2. Make path absolute (using cwd for relative paths)
    3. Normalize separators and remove .. components
    4. Case-fold on Windows for comparison
    """
    p = Path(path)
    
    # Expand ~ to home directory (no IO)
    if str(p).startswith("~"):
        p = Path(os.path.expanduser(str(p)))
    
    # Make absolute without IO
    if not p.is_absolute():
        p = Path.cwd() / p
    
    # Normalize path components (no IO)
    # os.path.normpath handles .., ., and separator normalization
    normalized = os.path.normpath(str(p))
    
    return Path(normalized)

def _is_under_no_io(path: Path, root: Path) -> bool:
    """
    Check if path is under root WITHOUT filesystem IO.
    
    Uses string comparison after normalization.
    Case-insensitive on Windows.
    """
    # Normalize both paths
    path_str = os.path.normpath(str(path))
    root_str = os.path.normpath(str(root))
    
    # Case-insensitive on Windows
    if os.name == "nt":
        path_str = path_str.lower()
        root_str = root_str.lower()
    
    # Check if path starts with root
    if not path_str.startswith(root_str):
        return False
    
    # Ensure it's a proper subdirectory (not just prefix match)
    # e.g., /foo/bar should not match /foo/barbaz
    if len(path_str) > len(root_str):
        next_char = path_str[len(root_str)]
        if next_char not in (os.sep, "/"):
            return False
    
    return True

def _compute_relative_no_io(path: Path, root: Path) -> str:
    """
    Compute relative path WITHOUT filesystem IO.
    
    Assumes _is_under_no_io(path, root) is True.
    """
    path_str = os.path.normpath(str(path))
    root_str = os.path.normpath(str(root))
    
    # Case handling for comparison
    if os.name == "nt":
        path_compare = path_str.lower()
        root_compare = root_str.lower()
    else:
        path_compare = path_str
        root_compare = root_str
    
    if path_compare == root_compare:
        return ""
    
    # Strip root prefix and leading separator
    relative = path_str[len(root_str):]
    if relative.startswith(os.sep) or relative.startswith("/"):
        relative = relative[1:]
    
    # Normalize to forward slashes for consistency
    return relative.replace(os.sep, "/")

def resolve(path: str | Path) -> ResolvedPath:
    """
    Resolve any path to its canonical root category.
    
    This is a STRUCTURAL operation only:
    - Identifies which root category contains the path
    - Computes absolute and relative paths
    - Extracts subdirectory for ROOT_CK3RAVEN_DATA and ROOT_USER_DOCS
    
    It does NOT:
    - Hit the filesystem (works for non-existent paths)
    - Check permissions
    - Decide if operations are allowed
    - Consult the capability matrix
    
    Classification order (most specific first):
    1. ROOT_REPO (if detected)
    2. ROOT_CK3RAVEN_DATA
    3. ROOT_VSCODE
    4. ROOT_LAUNCHER (subset of UTILITIES)
    5. ROOT_UTILITIES
    6. ROOT_USER_DOCS
    7. ROOT_STEAM (from config)
    8. ROOT_GAME (from config)
    9. ROOT_EXTERNAL (catch-all)
    """
    abs_path = _normalize_path_no_io(path)
    
    # Check each root in specificity order
    for root, root_path in _resolution_order():
        if root_path is None:
            continue
        if _is_under_no_io(abs_path, root_path):
            relative = _compute_relative_no_io(abs_path, root_path)
            
            # Extract subdirectory (first path component)
            parts = relative.split("/") if relative else []
            subdirectory = parts[0] if parts else None
            
            # Only track subdirectory for roots that use subdir-level matrix
            track_subdir = root in (RootCategory.ROOT_CK3RAVEN_DATA, RootCategory.ROOT_USER_DOCS)
            
            return ResolvedPath(
                root=root,
                absolute=abs_path,
                relative=relative,
                subdirectory=subdirectory if track_subdir else None,
            )
    
    # Anything else is ROOT_EXTERNAL
    return ResolvedPath(
        root=RootCategory.ROOT_EXTERNAL,
        absolute=abs_path,
        relative=str(abs_path),
        subdirectory=None,
    )

def _resolution_order() -> list[tuple[RootCategory, Path | None]]:
    """
    Return roots in classification order (most specific first).
    
    Order matters: ROOT_LAUNCHER must be checked before ROOT_UTILITIES
    because it's a more specific subset.
    """
    return [
        (RootCategory.ROOT_REPO, get_root(RootCategory.ROOT_REPO)),
        (RootCategory.ROOT_CK3RAVEN_DATA, ROOTS.get(RootCategory.ROOT_CK3RAVEN_DATA)),
        (RootCategory.ROOT_VSCODE, ROOTS.get(RootCategory.ROOT_VSCODE)),
        (RootCategory.ROOT_LAUNCHER, ROOTS.get(RootCategory.ROOT_LAUNCHER)),
        (RootCategory.ROOT_UTILITIES, ROOTS.get(RootCategory.ROOT_UTILITIES)),
        (RootCategory.ROOT_USER_DOCS, ROOTS.get(RootCategory.ROOT_USER_DOCS)),
        (RootCategory.ROOT_STEAM, get_root(RootCategory.ROOT_STEAM)),
        (RootCategory.ROOT_GAME, get_root(RootCategory.ROOT_GAME)),
    ]
```

### B.3 Phase B Validation

| Command | Expected Result |
|---------|-----------------|
| `python -c "from ck3lens.paths import resolve; print(resolve('~/.ck3raven/wip/test.py'))"` | Shows `ROOT_CK3RAVEN_DATA`, subdirectory=`wip` |
| `python -c "from ck3lens.paths import resolve; print(resolve('C:/random/path.txt'))"` | Shows `ROOT_EXTERNAL` |
| `python -c "from ck3lens.paths import resolve; print(resolve('/nonexistent/path/file.txt'))"` | Works (no IO error), shows `ROOT_EXTERNAL` |
| `python -c "from ck3lens.paths import resolve, RootCategory; assert resolve('~/.ck3raven/wip/x.py').subdirectory == 'wip'"` | No assertion error |
| Test: Resolve path inside repo | Returns `ROOT_REPO` with relative path |
| Test: Resolve path under launcher | Returns `ROOT_LAUNCHER` (not `ROOT_UTILITIES`) |
| Test: Resolve non-existent path | Works without error (no IO) |

### B.4 Phase B Success Criteria

- [ ] `ResolvedPath` dataclass with `root`, `absolute`, `relative`, `subdirectory`
- [ ] `resolve()` function classifies all paths
- [ ] **No filesystem IO** - uses `_normalize_path_no_io()` instead of `Path.resolve()`
- [ ] Works correctly for non-existent paths
- [ ] Resolution order prioritizes specific roots over general
- [ ] `subdirectory` populated for `ROOT_CK3RAVEN_DATA` and `ROOT_USER_DOCS`
- [ ] Unknown paths classified as `ROOT_EXTERNAL`
- [ ] No permission logic in resolution code
- [ ] Unit tests cover all root categories **including non-existent paths**

---

## Phase C: Capability Matrix

**Objective:** Create pure data structure as sole enforcement driver. ROOT_USER_DOCS uses subdir matrix for mod/ only. CK3RAVEN_DATA has explicit None entry.

### C.1 Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tools/ck3lens_mcp/ck3lens/capability_matrix.py` | **REWRITE** | Pure matrix data structure |

### C.2 capability_matrix.py Implementation

```python
"""
Capability matrix for path enforcement.

THE matrix is THE sole enforcement driver.
No per-domain enforcement functions.

Matrix key: (mode, root, subdirectory)
- For ROOT_CK3RAVEN_DATA, subdirectory is significant
- For ROOT_USER_DOCS, only mod/ subdirectory is writable
- For all other roots, subdirectory is None

Global invariants OVERRIDE the matrix:
1. Contract required for write/delete
2. db/ and daemon/ subdirs are NEVER writable
3. ROOT_EXTERNAL is always denied
"""

from dataclasses import dataclass
from ck3lens.paths import RootCategory

@dataclass(frozen=True)
class Capability:
    """Capability flags for a (mode, root, subdir) combination."""
    read: bool = False
    write: bool = False
    delete: bool = False

# Type alias for matrix key
MatrixKey = tuple[str, RootCategory, str | None]

# ─────────────────────────────────────────────────────────────────────
# THE CAPABILITY MATRIX
# ─────────────────────────────────────────────────────────────────────

CAPABILITY_MATRIX: dict[MatrixKey, Capability] = {
    # =================================================================
    # ck3lens mode
    # =================================================================
    
    # Game content (read-only)
    ("ck3lens", RootCategory.ROOT_GAME, None): Capability(read=True),
    ("ck3lens", RootCategory.ROOT_STEAM, None): Capability(read=True),
    
    # User docs - READ-ONLY by default, mod/ subdirectory is writable
    ("ck3lens", RootCategory.ROOT_USER_DOCS, None): Capability(read=True),  # Default: read-only
    ("ck3lens", RootCategory.ROOT_USER_DOCS, "mod"): Capability(read=True, write=True, delete=True),  # Local mods
    
    # CK3RAVEN_DATA - explicit root-level entry + per-subdirectory rules
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, None): Capability(read=True),  # Root level: read-only
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "config"): Capability(read=True, write=True),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "playsets"): Capability(read=True, write=True, delete=True),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "wip"): Capability(read=True, write=True, delete=True),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "logs"): Capability(read=True, write=True),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "journal"): Capability(read=True, write=True),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "cache"): Capability(read=True, write=True, delete=True),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "db"): Capability(read=True),  # Daemon only
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "daemon"): Capability(read=True),  # Daemon only
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "artifacts"): Capability(read=True, write=True),
    
    # Utilities (read-only)
    ("ck3lens", RootCategory.ROOT_LAUNCHER, None): Capability(read=True),
    ("ck3lens", RootCategory.ROOT_UTILITIES, None): Capability(read=True),
    ("ck3lens", RootCategory.ROOT_VSCODE, None): Capability(read=True),
    
    # Repo not visible in ck3lens mode
    ("ck3lens", RootCategory.ROOT_REPO, None): Capability(),
    
    # External always denied
    ("ck3lens", RootCategory.ROOT_EXTERNAL, None): Capability(),
    
    # =================================================================
    # ck3raven-dev mode
    # =================================================================
    
    # Repo - full access
    ("ck3raven-dev", RootCategory.ROOT_REPO, None): Capability(read=True, write=True, delete=True),
    
    # Game content (read-only for testing/reference)
    ("ck3raven-dev", RootCategory.ROOT_GAME, None): Capability(read=True),
    ("ck3raven-dev", RootCategory.ROOT_STEAM, None): Capability(read=True),
    
    # User docs - read-only (not modding in dev mode)
    ("ck3raven-dev", RootCategory.ROOT_USER_DOCS, None): Capability(read=True),
    ("ck3raven-dev", RootCategory.ROOT_USER_DOCS, "mod"): Capability(read=True),  # Read-only in dev mode
    
    # CK3RAVEN_DATA - explicit root-level entry + per-subdirectory rules
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, None): Capability(read=True),  # Root level: read-only
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "config"): Capability(read=True, write=True, delete=True),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "playsets"): Capability(read=True, write=True, delete=True),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "wip"): Capability(read=True, write=True, delete=True),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "logs"): Capability(read=True, write=True, delete=True),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "journal"): Capability(read=True, write=True, delete=True),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "cache"): Capability(read=True, write=True, delete=True),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "db"): Capability(read=True),  # Daemon only
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "daemon"): Capability(read=True),  # Daemon only
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "artifacts"): Capability(read=True, write=True, delete=True),
    
    # Utilities (read-only)
    ("ck3raven-dev", RootCategory.ROOT_LAUNCHER, None): Capability(read=True),
    ("ck3raven-dev", RootCategory.ROOT_UTILITIES, None): Capability(read=True),
    
    # VS Code - write settings (no delete)
    ("ck3raven-dev", RootCategory.ROOT_VSCODE, None): Capability(read=True, write=True),
    
    # External always denied
    ("ck3raven-dev", RootCategory.ROOT_EXTERNAL, None): Capability(),
}

def get_capability(mode: str, root: RootCategory, subdirectory: str | None = None) -> Capability:
    """
    Look up capability from matrix.
    
    For ROOT_CK3RAVEN_DATA and ROOT_USER_DOCS:
    - Checks (mode, root, subdirectory) first
    - Falls back to (mode, root, None) for root-level default
    
    For all other roots:
    - Uses (mode, root, None) directly
    
    Returns empty Capability() if no entry found (default deny).
    """
    # Roots that use subdirectory-level lookup
    subdir_roots = (RootCategory.ROOT_CK3RAVEN_DATA, RootCategory.ROOT_USER_DOCS)
    
    if root in subdir_roots and subdirectory:
        key = (mode, root, subdirectory)
        if key in CAPABILITY_MATRIX:
            return CAPABILITY_MATRIX[key]
    
    # Fall back to root-level lookup (also handles subdirectory=None)
    key = (mode, root, None)
    return CAPABILITY_MATRIX.get(key, Capability())
```

### C.3 Phase C Validation

| Command | Expected Result |
|---------|-----------------|
| `python -c "from ck3lens.capability_matrix import CAPABILITY_MATRIX; print(len(CAPABILITY_MATRIX))"` | Prints count (36+) |
| `python -c "from ck3lens.capability_matrix import get_capability; from ck3lens.paths import RootCategory; print(get_capability('ck3lens', RootCategory.ROOT_CK3RAVEN_DATA, 'wip'))"` | Shows `Capability(read=True, write=True, delete=True)` |
| `python -c "from ck3lens.capability_matrix import get_capability; from ck3lens.paths import RootCategory; print(get_capability('ck3lens', RootCategory.ROOT_CK3RAVEN_DATA, None))"` | Shows `Capability(read=True)` (root-level read-only) |
| `python -c "from ck3lens.capability_matrix import get_capability; from ck3lens.paths import RootCategory; print(get_capability('ck3lens', RootCategory.ROOT_CK3RAVEN_DATA, 'db'))"` | Shows `Capability(read=True)` (daemon-only) |
| `python -c "from ck3lens.capability_matrix import get_capability; from ck3lens.paths import RootCategory; print(get_capability('ck3lens', RootCategory.ROOT_USER_DOCS, None))"` | Shows `Capability(read=True)` (read-only default) |
| `python -c "from ck3lens.capability_matrix import get_capability; from ck3lens.paths import RootCategory; print(get_capability('ck3lens', RootCategory.ROOT_USER_DOCS, 'mod'))"` | Shows `Capability(read=True, write=True, delete=True)` |
| `python -c "from ck3lens.capability_matrix import get_capability; from ck3lens.paths import RootCategory; print(get_capability('ck3lens', RootCategory.ROOT_USER_DOCS, 'save games'))"` | Shows `Capability(read=True)` (falls back to None) |
| `grep -r "def _enforce_" tools/ck3lens_mcp/ck3lens/policy/` | **Zero matches** after Phase D |

### C.4 Phase C Success Criteria

- [ ] `CAPABILITY_MATRIX` dict with all entries
- [ ] `Capability` dataclass with read/write/delete
- [ ] `get_capability()` single lookup function
- [ ] Subdirectory lookup for `ROOT_CK3RAVEN_DATA` and `ROOT_USER_DOCS`
- [ ] **Explicit entry for `(mode, ROOT_CK3RAVEN_DATA, None)`** - read-only
- [ ] **Explicit entry for `(mode, ROOT_USER_DOCS, None)`** - read-only
- [ ] **Only `ROOT_USER_DOCS/mod/` is writable** - other user docs are read-only
- [ ] Matrix entries for both modes (ck3lens, ck3raven-dev)
- [ ] No enforcement logic in matrix module
- [ ] Unit tests for matrix lookups **including subdirectory=None cases**

---

## Phase D: Enforcement Consolidation

**Objective:** Single `enforce()` function replacing all per-domain functions.

### D.1 Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tools/ck3lens_mcp/ck3lens/policy/enforcement.py` | **REWRITE** | Single `enforce()` function |

### D.2 enforcement.py Implementation

```python
"""
Enforcement - pure function driven by capability matrix.

This is THE enforcement boundary.
NO per-domain enforcement functions.
Global invariants OVERRIDE matrix decisions.

Single entry point: enforce()
"""

from dataclasses import dataclass
from enum import Enum

from ck3lens.paths import RootCategory, ResolvedPath
from ck3lens.capability_matrix import get_capability

class Decision(Enum):
    """Enforcement decision."""
    ALLOW = "allow"
    DENY = "deny"

class OperationType(Enum):
    """Operation types for enforcement."""
    FILE_READ = "read"
    FILE_WRITE = "write"
    FILE_DELETE = "delete"

@dataclass(frozen=True)
class EnforcementResult:
    """Result of enforcement check."""
    decision: Decision
    reason: str

def enforce(
    mode: str,
    operation: OperationType,
    resolved: ResolvedPath,
    has_contract: bool,
) -> EnforcementResult:
    """
    THE enforcement function.
    
    Checks (in order):
    1. Global invariants (override matrix)
    2. Capability matrix lookup
    
    Args:
        mode: Agent mode ("ck3lens" or "ck3raven-dev")
        operation: The operation being attempted
        resolved: Result from paths.resolve()
        has_contract: Whether an active contract exists
        
    Returns:
        EnforcementResult with decision and reason
    """
    
    # ─────────────────────────────────────────────────────────────────
    # GLOBAL INVARIANT 1: ROOT_EXTERNAL is always denied
    # ─────────────────────────────────────────────────────────────────
    if resolved.root == RootCategory.ROOT_EXTERNAL:
        return EnforcementResult(
            decision=Decision.DENY,
            reason="Path is outside all known roots (ROOT_EXTERNAL)",
        )
    
    # ─────────────────────────────────────────────────────────────────
    # GLOBAL INVARIANT 2: Contract required for write/delete
    # ─────────────────────────────────────────────────────────────────
    if operation in (OperationType.FILE_WRITE, OperationType.FILE_DELETE):
        if not has_contract:
            return EnforcementResult(
                decision=Decision.DENY,
                reason="Contract required for write/delete operations",
            )
    
    # ─────────────────────────────────────────────────────────────────
    # GLOBAL INVARIANT 3: db/ and daemon/ are NEVER writable
    # ─────────────────────────────────────────────────────────────────
    if resolved.root == RootCategory.ROOT_CK3RAVEN_DATA:
        if resolved.subdirectory in ("db", "daemon"):
            if operation in (OperationType.FILE_WRITE, OperationType.FILE_DELETE):
                return EnforcementResult(
                    decision=Decision.DENY,
                    reason=f"/{resolved.subdirectory}/ is daemon-only (Single-Writer Architecture)",
                )
    
    # ─────────────────────────────────────────────────────────────────
    # MATRIX LOOKUP
    # ─────────────────────────────────────────────────────────────────
    cap = get_capability(mode, resolved.root, resolved.subdirectory)
    
    # Check capability for requested operation
    if operation == OperationType.FILE_READ and cap.read:
        return EnforcementResult(decision=Decision.ALLOW, reason="Matrix allows read")
    if operation == OperationType.FILE_WRITE and cap.write:
        return EnforcementResult(decision=Decision.ALLOW, reason="Matrix allows write")
    if operation == OperationType.FILE_DELETE and cap.delete:
        return EnforcementResult(decision=Decision.ALLOW, reason="Matrix allows delete")
    
    # Default deny with specific message
    op_name = operation.value
    root_name = resolved.root.name
    subdir_info = f"/{resolved.subdirectory}" if resolved.subdirectory else ""
    return EnforcementResult(
        decision=Decision.DENY,
        reason=f"Capability matrix denies {op_name} for {root_name}{subdir_info}",
    )
```

### D.3 Per-Domain Functions to Delete

These functions must be deleted from `enforcement.py`:

| Function | Status |
|----------|--------|
| `_enforce_ck3lens_write()` | DELETE |
| `_enforce_wip_access()` | DELETE |
| `_enforce_repo_access()` | DELETE |
| `_enforce_vanilla_access()` | DELETE |
| `_enforce_steam_access()` | DELETE |
| `_enforce_launcher_access()` | DELETE |
| `enforce_policy()` (old signature) | REPLACE with `enforce()` |

### D.4 Phase D Validation

| Command | Expected Result |
|---------|-----------------|
| `python -c "from ck3lens.policy.enforcement import enforce, OperationType; from ck3lens.paths import resolve; r = resolve('~/.ck3raven/wip/test.py'); print(enforce('ck3lens', OperationType.FILE_WRITE, r, True))"` | Shows `ALLOW` |
| `python -c "from ck3lens.policy.enforcement import enforce, OperationType; from ck3lens.paths import resolve; r = resolve('~/.ck3raven/wip/test.py'); print(enforce('ck3lens', OperationType.FILE_WRITE, r, False))"` | Shows `DENY` with "Contract required" |
| `python -c "from ck3lens.policy.enforcement import enforce, OperationType; from ck3lens.paths import resolve; r = resolve('~/.ck3raven/db/ck3raven.db'); print(enforce('ck3raven-dev', OperationType.FILE_WRITE, r, True))"` | Shows `DENY` with "daemon-only" |
| `python -c "from ck3lens.policy.enforcement import enforce, OperationType; from ck3lens.paths import resolve; r = resolve('~/.ck3raven'); print(enforce('ck3lens', OperationType.FILE_WRITE, r, True))"` | Shows `DENY` (root-level is read-only) |
| `grep -r "def _enforce_" tools/ck3lens_mcp/ck3lens/policy/` | **Zero matches** |

### D.5 Phase D Success Criteria

- [ ] Single `enforce()` function
- [ ] All per-domain enforcement functions deleted
- [ ] Global invariants checked before matrix
- [ ] Matrix is sole driver after invariants
- [ ] OperationType enum matches design
- [ ] Decision enum with ALLOW/DENY
- [ ] Unit tests for each invariant
- [ ] Unit tests for matrix-driven decisions
- [ ] **Unit test for CK3RAVEN_DATA subdirectory=None (read-only)**
- [ ] **Unit test for ROOT_USER_DOCS subdirectory=None (read-only)**
- [ ] **Unit test for ROOT_USER_DOCS/mod (writable)**
- [ ] **Unit test for ROOT_USER_DOCS/save games (read-only fallback)**

---

## Phase E: Call Site Migration

**Objective:** Update all call sites to use new paths API.

### E.1 Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tools/ck3lens_mcp/ck3lens/world_adapter.py` | **MODIFY** | Use `paths.resolve()` |
| `tools/ck3lens_mcp/ck3lens/world_router.py` | **DELETE** | No longer needed |
| `tools/ck3lens_mcp/server.py` | **MODIFY** | Import from paths, not world_router |
| `tools/ck3lens_mcp/ck3lens/session.py` | **MODIFY** | Remove path parameters |
| All MCP tool implementations | **MODIFY** | Update imports and calls |

### E.2 Migration Patterns

#### Before (world_router.py)
```python
from ck3lens.world_router import get_wip_root, get_ck3raven_root

wip = get_wip_root()
repo = get_ck3raven_root()
```

#### After (paths.py)
```python
from ck3lens.paths import get_wip_dir, get_root, RootCategory

wip = get_wip_dir()
repo = get_root(RootCategory.ROOT_REPO)
```

#### Before (enforcement)
```python
from ck3lens.policy.enforcement import enforce_policy, EnforcementRequest

result = enforce_policy(EnforcementRequest(
    operation=OperationType.FILE_WRITE,
    mode=session.mode,
    tool_name="ck3_file",
    mod_name="MSC",
    rel_path="common/traits/fix.txt",
))
```

#### After (enforcement)
```python
from ck3lens.policy.enforcement import enforce, OperationType
from ck3lens.paths import resolve

resolved = resolve(full_path)
result = enforce(session.mode, OperationType.FILE_WRITE, resolved, has_contract=True)
```

### E.3 world_router.py Deletion

The entire file is deleted. Its functions are replaced:

| world_router Function | Replacement |
|-----------------------|-------------|
| `get_wip_root()` | `paths.get_wip_dir()` |
| `get_ck3raven_root()` | `paths.get_root(RootCategory.ROOT_REPO)` |
| `get_vanilla_root()` | `paths.get_root(RootCategory.ROOT_GAME)` |
| `get_ck3raven_data_root()` | `paths.ROOTS[RootCategory.ROOT_CK3RAVEN_DATA]` |
| `normalize_path_input()` | `paths.resolve()` |
| `get_world()` | Direct `WorldAdapter` instantiation |

### E.4 Banned Terms CI Gate

Add to `scripts/arch_lint/config.py`:

```python
BANNED_PATH_TERMS = [
    "wip_root",
    "ck3raven_root", 
    "vanilla_root",
    "ck3raven_data_root",
    "_get_wip_root",
    "_get_ck3raven_root",
    "_get_vanilla_root",
    "_get_ck3raven_data_root",
    "world_router",  # Module should not exist
]
```

### E.5 Phase E Validation

| Command | Expected Result |
|---------|-----------------|
| `python -c "from ck3lens.world_router import get_world"` | **ImportError** (module deleted) |
| `grep -r "from ck3lens.world_router" tools/ck3lens_mcp/` | **Zero matches** |
| `grep -r "wip_root" tools/ck3lens_mcp/` | **Zero matches** |
| `grep -r "ck3raven_root" tools/ck3lens_mcp/` | **Zero matches** |
| `grep -r "vanilla_root" tools/ck3lens_mcp/` | **Zero matches** |
| `python -m pytest tests/test_paths.py -v` | All tests pass |

### E.6 Phase E Success Criteria

- [ ] `world_router.py` deleted
- [ ] All imports updated to use `paths`
- [ ] All enforcement calls use new `enforce()` signature
- [ ] Banned terms grep returns zero matches
- [ ] All MCP tools work with new API
- [ ] Integration tests pass

---

## Phase F: Validation and CI Gates

**Objective:** Comprehensive validation and CI protection on Windows AND Linux.

### F.1 Validation Commands

| Command | Expected Result | Evidence |
|---------|-----------------|----------|
| `python -m pytest tests/test_paths.py -v` | All tests pass | Test output log |
| `python -m pytest tests/test_capability_matrix.py -v` | All tests pass | Test output log |
| `python -m pytest tests/test_enforcement.py -v` | All tests pass | Test output log |
| `python -m scripts.arch_lint --errors-only` | Zero errors | Lint output |
| `grep -r "world_router" tools/ck3lens_mcp/` | Zero matches | grep output |
| `grep -r "wip_root" tools/ck3lens_mcp/` | Zero matches | grep output |
| `grep -r "_enforce_" tools/ck3lens_mcp/ck3lens/policy/` | Zero matches | grep output |
| `python -c "from ck3lens.paths import paths_doctor; print(paths_doctor())"` | No errors | Doctor output |

### F.2 Test Files to Create

| File | Purpose |
|------|---------|
| `tests/test_paths.py` | ROOTS registry, resolution, accessors, **non-existent paths** |
| `tests/test_capability_matrix.py` | Matrix lookups, edge cases, **subdirectory=None** |
| `tests/test_enforcement.py` | Invariants, matrix-driven decisions, **USER_DOCS subdirs** |
| `tests/test_config_loader.py` | Config loading, validation, **default tracking** |

### F.3 Test Coverage Requirements

| Component | Required Coverage |
|-----------|-------------------|
| `paths.py` | 95%+ |
| `capability_matrix.py` | 100% |
| `enforcement.py` | 95%+ |
| `config_loader.py` | 90%+ |

### F.4 CI Gate Configuration (Windows + Linux)

```yaml
# .github/workflows/paths-validation.yml
name: Paths Architecture Validation

on: [push, pull_request]

jobs:
  validate:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -e .[dev]
      
      - name: Check banned terms
        shell: bash
        run: |
          if grep -r "world_router" tools/ck3lens_mcp/; then
            echo "ERROR: world_router references found"
            exit 1
          fi
          if grep -r "wip_root" tools/ck3lens_mcp/; then
            echo "ERROR: wip_root references found"
            exit 1
          fi
          if grep -r "_enforce_" tools/ck3lens_mcp/ck3lens/policy/; then
            echo "ERROR: Per-domain enforcement functions found"
            exit 1
          fi
      
      - name: Run arch_lint
        run: python -m scripts.arch_lint --errors-only
      
      - name: Run path tests
        run: python -m pytest tests/test_paths.py tests/test_capability_matrix.py tests/test_enforcement.py tests/test_config_loader.py -v
      
      - name: Test non-existent paths (no IO errors)
        run: |
          python -c "from ck3lens.paths import resolve; r = resolve('/nonexistent/path/file.txt'); assert r.root.name == 'ROOT_EXTERNAL'"
```

### F.5 Phase F Success Criteria

- [ ] All validation commands pass
- [ ] Test files created and passing
- [ ] Coverage requirements met
- [ ] **CI gate runs on BOTH ubuntu-latest AND windows-latest**
- [ ] paths_doctor reports no errors (or only warnings for defaults)
- [ ] Documentation updated

---

## 10. Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **R1: Path resolution breaks existing tools** | Medium | High | Comprehensive test suite, staged rollout |
| **R2: Capability matrix misses edge case** | Low | Medium | Review all existing enforcement calls before migration |
| **R3: Config loading fails silently** | Low | High | Config errors collected in WorkspaceConfig.errors |
| **R4: ROOT_LAUNCHER/ROOT_UTILITIES overlap** | Low | Low | Resolution order puts LAUNCHER first |
| **R5: Platform differences (Windows/Linux)** | Medium | Medium | **CI runs on both platforms**, no-IO normalization |
| **R6: Contract check regression** | Low | High | Dedicated invariant test |
| **R7: db/daemon invariant bypassed** | Very Low | High | Dedicated invariant test, arch_lint check |
| **R8: No-IO resolution fails edge case** | Low | Medium | Extensive test suite including symlinks, UNC paths |

### Risk Responses

| Risk | Response |
|------|----------|
| R1 | Run full MCP test suite before each phase merge |
| R2 | Generate capability matrix report, manual review |
| R3 | paths_doctor checks config at startup |
| R4 | Already handled by specificity-first resolution |
| R5 | **CI workflow includes both ubuntu-latest and windows-latest** |
| R6 | Invariant tests are required for Phase D sign-off |
| R7 | arch_lint rule for write calls to db/ or daemon/ |
| R8 | Test suite includes non-existent paths, paths with .., UNC paths |

---

## 11. Acceptance Criteria

### 11.1 Definition of Done

| Phase | Acceptance Criteria |
|-------|---------------------|
| **Phase 0** | Config loading works, ALL platform paths flow through config, using_defaults tracked |
| **Phase A** | ROOTS registry exists **built from config (not hard-coded)**, accessors work |
| **Phase B** | resolve() classifies all test paths correctly **without filesystem IO** |
| **Phase C** | Matrix has all entries **including subdirectory=None**, USER_DOCS/mod only writable |
| **Phase D** | Single enforce() function, all per-domain functions deleted |
| **Phase E** | world_router deleted, all imports migrated, grep clean |
| **Phase F** | All tests pass **on Windows AND Linux**, CI gates configured |

### 11.2 Evidence Packet Checklist

For final sign-off, collect:

| Evidence | Source | Required |
|----------|--------|----------|
| Test results for paths.py | pytest output | ✓ |
| Test results for capability_matrix.py | pytest output | ✓ |
| Test results for enforcement.py | pytest output | ✓ |
| Test results for config_loader.py | pytest output | ✓ |
| arch_lint clean run | lint output | ✓ |
| Banned terms grep (zero matches) | grep output | ✓ |
| paths_doctor output (no errors) | doctor output | ✓ |
| Coverage report (meets thresholds) | coverage output | ✓ |
| Full MCP test suite | pytest output | ✓ |
| Manual smoke test (write to wip) | Screenshot/log | ✓ |
| Manual smoke test (write to mod) | Screenshot/log | ✓ |
| **CI passing on ubuntu-latest** | GitHub Actions | ✓ |
| **CI passing on windows-latest** | GitHub Actions | ✓ |
| **Test for non-existent paths (no IO error)** | pytest output | ✓ |
| **Test for CK3RAVEN_DATA subdirectory=None** | pytest output | ✓ |
| **Test for USER_DOCS subdirectory=None (read-only)** | pytest output | ✓ |
| **Test for USER_DOCS/mod (writable)** | pytest output | ✓ |

### 11.3 Rollback Plan

If issues discovered after merge:

1. **Phase-level rollback:** Each phase is a separate commit, can revert individually
2. **Full rollback:** Keep `archive/deprecated_paths/` with old implementations
3. **Feature flag:** If needed, add `USE_NEW_PATHS=false` environment variable

---

## Appendix A: Complete File List

| File | Phase | Action |
|------|-------|--------|
| `~/.ck3raven/config/workspace.toml` | 0 | CREATE |
| `ck3lens/config_loader.py` | 0 | CREATE |
| `ck3lens/paths.py` | A, B | CREATE |
| `ck3lens/capability_matrix.py` | C | REWRITE |
| `ck3lens/policy/enforcement.py` | D | REWRITE |
| `ck3lens/world_router.py` | E | DELETE |
| `ck3lens/world_adapter.py` | E | MODIFY |
| `ck3lens/session.py` | 0, E | MODIFY |
| `server.py` | E | MODIFY |
| `tests/test_paths.py` | A, B | CREATE |
| `tests/test_capability_matrix.py` | C | CREATE |
| `tests/test_enforcement.py` | D | CREATE |
| `tests/test_config_loader.py` | 0 | CREATE |
| `scripts/arch_lint/config.py` | E | MODIFY |
| `.github/workflows/paths-validation.yml` | F | CREATE |

---

## Appendix B: Quick Reference

### New Imports

```python
# Path resolution
from ck3lens.paths import (
    RootCategory,
    ROOTS,
    resolve,
    ResolvedPath,
    get_root,
    get_wip_dir,
    get_db_path,
    get_playset_dir,
    get_logs_dir,
    get_local_mods_folder,
)

# Capability matrix
from ck3lens.capability_matrix import (
    Capability,
    CAPABILITY_MATRIX,
    get_capability,
)

# Enforcement
from ck3lens.policy.enforcement import (
    Decision,
    OperationType,
    EnforcementResult,
    enforce,
)

# Configuration
from ck3lens.config_loader import (
    WorkspaceConfig,
    PathsConfig,
    load_config,
    create_default_config,
    get_config_path,
)
```

### Common Patterns

```python
# Resolve and enforce
resolved = resolve(user_path)
result = enforce(session.mode, OperationType.FILE_WRITE, resolved, has_contract=True)
if result.decision != Decision.ALLOW:
    return {"error": result.reason}

# Get paths
wip = get_wip_dir()
repo = get_root(RootCategory.ROOT_REPO)
db = get_db_path()

# Check config
config = load_config()
if config.errors:
    logger.warning(f"Config issues: {config.errors}")
if config.paths.using_defaults:
    logger.info(f"Using OS-defaults for: {config.paths.using_defaults}")
```

---

*End of Implementation Plan*
