# CK3Raven Paths Design Guidelines

> **Status:** CANONICAL  
> **Created:** January 27, 2026  
> **Updated:** February 1, 2026  
> **Purpose:** Single source of truth for ALL path resolution in ck3raven

---

## Core Principle

**Paths ARE constants, not computed values.**

There is no indirection. No getters. No aliases. Path constants are `Path` objects, resolved once at module load.

```python
from ck3lens.paths import ROOT_GAME, VENV_PATH, DB_PATH

# These ARE paths. Not keys. Not enums. Path objects.
abs_path = ROOT_GAME / "common/traits/00_traits.txt"
```

---

## Path Categories

ck3raven has three categories of paths:

### 1. Canonical Domain Roots (Capability Matrix)
Top-level paths that define authorization boundaries. These map directly to `RootCategory` in the capability matrix.

### 2. Infrastructure Paths (Derived)
Paths the tool needs to function. Most are derived from domain roots or `CONFIG_DIR`.

### 3. User-Configurable Paths
Paths that users may need to override via `roots.json`.

---

## Complete Path Inventory

### Canonical Domain Roots (Capability Matrix)

These are THE domains for authorization. Each maps to a `RootCategory` enum value.

| Constant | RootCategory | Description | Typical Value |
|----------|--------------|-------------|---------------|
| `ROOT_GAME` | `ROOT_GAME` | Vanilla CK3 installation | `.../steamapps/common/Crusader Kings III/game` |
| `ROOT_STEAM` | `ROOT_STEAM` | Steam Workshop mods | `.../steamapps/workshop/content/1158310` |
| `ROOT_USER_DOCS` | `ROOT_USER_DOCS` | User-authored mods | `~/Documents/Paradox Interactive/Crusader Kings III/mod` |
| `ROOT_UTILITIES` | `ROOT_UTILITIES` | CK3 logs, saves, crashes | `~/Documents/Paradox Interactive/Crusader Kings III` |
| `ROOT_LAUNCHER` | `ROOT_LAUNCHER` | Paradox launcher registry | `~/AppData/Roaming/Paradox Interactive/launcher-v2` |
| `ROOT_REPO` | `ROOT_REPO` | ck3raven repository root | `C:/Users/.../ck3raven` |
| `ROOT_WIP` | `ROOT_WIP` | Scratch/experimental workspace | `~/.ck3raven/wip` |
| `ROOT_VSCODE` | `ROOT_VSCODE` | VS Code settings/extensions | Platform-specific |
| `ROOT_OTHER` | `ROOT_OTHER` | Catch-all for unclassified paths | N/A (fallback) |

**Note:** `ROOT_OTHER` is a fallback domain for paths that don't match any other root. Operations targeting `ROOT_OTHER` require explicit token approval.

### Infrastructure Paths (Derived from Roots)

These are computed from canonical roots. They do NOT require user configuration.

| Constant | Derivation | Description |
|----------|------------|-------------|
| `CONFIG_DIR` | Fixed: `~/.ck3raven` | Configuration directory |
| `DB_PATH` | `CONFIG_DIR / "ck3raven.db"` | SQLite database |
| `ROOTS_CONFIG` | `CONFIG_DIR / "roots.json"` | Path overrides file |
| `SESSION_CONFIG` | `CONFIG_DIR / "session.json"` | Session state |
| `VENV_PATH` | `ROOT_REPO / ".venv"` | Python virtual environment |
| `PYTHON_EXE` | `VENV_PATH / "Scripts/python.exe"` | Python executable |
| `PLAYSETS_DIR` | `ROOT_REPO / "playsets"` | Playset definitions |
| `MCP_SERVER_DIR` | `ROOT_REPO / "tools/ck3lens_mcp"` | MCP server |
| `EXTENSION_DIR` | `ROOT_REPO / "tools/ck3lens-explorer"` | VS Code extension |
| `BRIDGE_DIR` | `MCP_SERVER_DIR / "bridge"` | Python bridge |
| `LOGS_DIR` | `ROOT_UTILITIES / "logs"` | CK3 logs |
| `SAVES_DIR` | `ROOT_UTILITIES / "save games"` | CK3 saves |
| `CRASHES_DIR` | `ROOT_UTILITIES / "crashes"` | CK3 crash reports |

### User-Configurable Paths

Only these paths should be in `roots.json`. Everything else is derived.

| Constant | Why Configurable |
|----------|------------------|
| `ROOT_GAME` | Steam library location varies |
| `ROOT_STEAM` | Usually derived from ROOT_GAME, but can be separate |
| `ROOT_REPO` | Workspace location varies |
| `ROOT_USER_DOCS` | Paradox folder location can vary |

---

## Banned Terms

These create parallel authority and are **permanently banned**:

| ❌ Banned | ✅ Use Instead | Notes |
|-----------|----------------|-------|
| `vanilla_root` | `ROOT_GAME` | |
| `vanilla_path` | `ROOT_GAME` | |
| `workshop_root` | `ROOT_STEAM` | |
| `local_mods_folder` | `ROOT_USER_DOCS` | *See note below* |
| `wip_root` | `ROOT_WIP` | |
| `ck3raven_root` | `ROOT_REPO` | |
| `ck3ravenPath` | `ROOT_REPO` | |
| `utility_roots` | `ROOT_UTILITIES` | |
| `launcher_path` | `ROOT_LAUNCHER` | |
| `DEFAULT_VANILLA_PATH` | `ROOT_GAME` | |
| `DEFAULT_CK3_MOD_DIR` | `ROOT_USER_DOCS` | |
| `DEFAULT_DB_PATH` | `DB_PATH` | |
| `DEFAULT_CONFIG_PATH` | `CONFIG_DIR` | |
| `get_vanilla_root()` | `ROOT_GAME` | |
| `_detect_ck3raven_root()` | `ROOT_REPO` | |
| `pythonPath` (as detection) | `PYTHON_EXE` | |
| `possiblePaths` | Use `ROOT_REPO` directly | |

**Note on `local_mods_folder`:** This term IS canonical in the playset/mod context (it identifies which mods are editable). However, it should NOT be used as a domain/path constant. For domain purposes, use `ROOT_USER_DOCS`.

---

## Design Rules

### Rule 1: No Path Parameters

Components do NOT accept path parameters for canonical paths.

```python
# ❌ BANNED - path as parameter creates alias
def __init__(self, vanilla_root: Path, db_path: Path):
    self._vanilla_root = vanilla_root

# ✅ CORRECT - import and use directly
from ck3lens.paths import ROOT_GAME, DB_PATH

class WorldAdapter:
    def _resolve_vanilla(self, address):
        return ROOT_GAME / address.relative_path
```

### Rule 2: No Path Detection Methods

Detection logic lives in ONE place (`ck3lens/paths.py`), executed once at module load.

```python
# ❌ BANNED - detection scattered across codebase
class WorldRouter:
    def _get_vanilla_root(self): ...
    def _detect_ck3raven_root(self): ...

class PythonBridge:
    def _findCk3ravenPath(): ...
    def _detectPythonPath(): ...

# ✅ CORRECT - paths.py handles all detection at import time
from ck3lens.paths import ROOT_REPO, PYTHON_EXE
```

### Rule 3: No Path Caching

The paths are module-level constants. They don't change during runtime.

```python
# ❌ BANNED - caching implies mutability
self._cached_vanilla_path = ...
this.cachedCk3ravenPath = ...

# ✅ CORRECT - constants are constants
from ck3lens.paths import ROOT_GAME
```

### Rule 4: Single Config Source

Machine-specific configuration is loaded once from `~/.ck3raven/roots.json`, not sprinkled throughout the codebase.

```python
# ❌ BANNED - config loading in multiple places
if config.get("vanilla_path"):
    self.vanilla_path = config["vanilla_path"]

# ✅ CORRECT - paths.py loads config and exports final paths
from ck3lens.paths import ROOT_GAME
```

### Rule 5: TypeScript Delegates to Python

The VS Code extension does NOT duplicate path detection. It calls the Python bridge to get paths.

```typescript
// ❌ BANNED - duplicating detection in TypeScript
const possiblePaths = [
    path.join(os.homedir(), 'Documents', 'AI Workspace', 'ck3raven'),
    ...
];

// ✅ CORRECT - ask Python for the authoritative path
const paths = await bridge.call('get_paths');
const repoPath = paths.ROOT_REPO;
```

**Bootstrap Exception:** The extension needs `ROOT_REPO` to FIND the Python bridge. This ONE case allows TypeScript detection (see Bootstrap Problem section).

---

## Configuration

### File: `~/.ck3raven/roots.json`

Machine-specific path overrides. Only non-derived paths belong here:

```json
{
    "version": "1.0",
    "roots": {
        "ROOT_GAME": "D:/SteamLibrary/steamapps/common/Crusader Kings III/game",
        "ROOT_REPO": "C:/Users/Nathan/Documents/AI Workspace/ck3raven"
    },
    "_auto_detected": false,
    "_verified_at": "2026-01-27T12:00:00Z"
}
```

**What belongs in roots.json:**
- `ROOT_GAME` - if Steam is not in default location
- `ROOT_STEAM` - only if different from derived value
- `ROOT_REPO` - if not auto-detected from workspace
- `ROOT_USER_DOCS` - only if non-standard location

**What does NOT belong in roots.json:**
- `DB_PATH` - always derived from `CONFIG_DIR`
- `VENV_PATH` - always derived from `ROOT_REPO`
- `PLAYSETS_DIR` - always derived from `ROOT_REPO`
- Any `*_DIR` path - all derived

### Auto-Detection Order

For each configurable path, `paths.py` checks:

1. **Config file** (`~/.ck3raven/roots.json`) - explicit override wins
2. **Environment variable** (e.g., `CK3RAVEN_ROOT_GAME`) - for CI/testing
3. **Auto-detection** - platform-specific heuristics

---

## Implementation

### New Module: `ck3lens/paths.py`

This is THE authoritative source for all paths:

```python
# ck3lens/paths.py
"""
Canonical path constants for ck3raven.

This module is THE source of truth for all filesystem paths.
Import paths directly - do not create aliases or pass as parameters.

Usage:
    from ck3lens.paths import ROOT_GAME, DB_PATH, PYTHON_EXE
    
    game_file = ROOT_GAME / "common/traits/00_traits.txt"
"""

from pathlib import Path
from typing import Optional
import json
import os
import sys

# =============================================================================
# FIXED PATHS (Never change, never configurable)
# =============================================================================

CONFIG_DIR: Path = Path.home() / ".ck3raven"
_ROOTS_CONFIG: Path = CONFIG_DIR / "roots.json"


# =============================================================================
# CONFIG LOADING
# =============================================================================

def _load_config() -> dict:
    """Load roots.json if it exists."""
    if _ROOTS_CONFIG.exists():
        try:
            return json.loads(_ROOTS_CONFIG.read_text())
        except Exception:
            pass
    return {}


def _get_root(name: str, auto_detect_fn) -> Optional[Path]:
    """Get a root path from config, env, or auto-detection."""
    config = _load_config()
    
    # 1. Config override
    if name in config.get("roots", {}):
        return Path(config["roots"][name])
    
    # 2. Environment variable
    env_key = f"CK3RAVEN_{name}"
    if env_key in os.environ:
        return Path(os.environ[env_key])
    
    # 3. Auto-detect
    return auto_detect_fn()


# =============================================================================
# AUTO-DETECTION FUNCTIONS
# =============================================================================

def _detect_root_repo() -> Optional[Path]:
    """Find ck3raven repo by walking up from this file."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "tools" / "ck3lens_mcp").exists():
            return parent
    return None


def _detect_root_game() -> Optional[Path]:
    """Find CK3 game installation."""
    candidates = (
        [
            Path("C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game"),
            Path("C:/Program Files/Steam/steamapps/common/Crusader Kings III/game"),
            Path("D:/Steam/steamapps/common/Crusader Kings III/game"),
            Path("D:/SteamLibrary/steamapps/common/Crusader Kings III/game"),
            Path("E:/Steam/steamapps/common/Crusader Kings III/game"),
            Path("E:/SteamLibrary/steamapps/common/Crusader Kings III/game"),
        ] if sys.platform == "win32" else [
            Path.home() / ".steam/steam/steamapps/common/Crusader Kings III/game",
            Path.home() / ".local/share/Steam/steamapps/common/Crusader Kings III/game",
        ]
    )
    for c in candidates:
        if c.exists():
            return c
    return None


def _detect_root_steam() -> Optional[Path]:
    """Find Steam Workshop folder (derived from ROOT_GAME)."""
    if ROOT_GAME:
        steamapps = ROOT_GAME.parent.parent
        workshop = steamapps / "workshop" / "content" / "1158310"
        if workshop.exists():
            return workshop
    return None


def _detect_root_user_docs() -> Optional[Path]:
    """Find user mods folder."""
    p = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
    return p if p.exists() else None


def _detect_root_utilities() -> Optional[Path]:
    """Find CK3 utilities folder (logs, saves, etc.)."""
    p = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III"
    return p if p.exists() else None


def _detect_root_launcher() -> Optional[Path]:
    """Find Paradox launcher folder."""
    if sys.platform == "win32":
        p = Path.home() / "AppData" / "Roaming" / "Paradox Interactive" / "launcher-v2"
    else:
        p = Path.home() / ".local" / "share" / "Paradox Interactive" / "launcher-v2"
    return p if p.exists() else None


def _detect_root_vscode() -> Optional[Path]:
    """Find VS Code user data folder."""
    if sys.platform == "win32":
        p = Path.home() / "AppData" / "Roaming" / "Code" / "User"
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "Code" / "User"
    else:
        p = Path.home() / ".config" / "Code" / "User"
    return p if p.exists() else None


# =============================================================================
# CANONICAL DOMAIN ROOTS (Capability Matrix)
# =============================================================================

ROOT_GAME: Optional[Path] = _get_root("ROOT_GAME", _detect_root_game)
ROOT_STEAM: Optional[Path] = _get_root("ROOT_STEAM", _detect_root_steam)
ROOT_USER_DOCS: Optional[Path] = _get_root("ROOT_USER_DOCS", _detect_root_user_docs)
ROOT_UTILITIES: Optional[Path] = _get_root("ROOT_UTILITIES", _detect_root_utilities)
ROOT_LAUNCHER: Optional[Path] = _get_root("ROOT_LAUNCHER", _detect_root_launcher)
ROOT_REPO: Optional[Path] = _get_root("ROOT_REPO", _detect_root_repo)
ROOT_WIP: Path = CONFIG_DIR / "wip"  # Always derived, always exists conceptually
ROOT_VSCODE: Optional[Path] = _get_root("ROOT_VSCODE", _detect_root_vscode)
ROOT_OTHER: Optional[Path] = None  # Catch-all, never has a concrete path

# =============================================================================
# DERIVED INFRASTRUCTURE PATHS
# =============================================================================

# Database & Config (derived from CONFIG_DIR)
DB_PATH: Path = CONFIG_DIR / "ck3raven.db"
ROOTS_CONFIG: Path = _ROOTS_CONFIG
SESSION_CONFIG: Path = CONFIG_DIR / "session.json"

# Python environment (derived from ROOT_REPO)
VENV_PATH: Optional[Path] = ROOT_REPO / ".venv" if ROOT_REPO else None
PYTHON_EXE: Optional[Path] = (
    VENV_PATH / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if VENV_PATH else None
)

# Tool paths (derived from ROOT_REPO)
PLAYSETS_DIR: Optional[Path] = ROOT_REPO / "playsets" if ROOT_REPO else None
MCP_SERVER_DIR: Optional[Path] = ROOT_REPO / "tools" / "ck3lens_mcp" if ROOT_REPO else None
EXTENSION_DIR: Optional[Path] = ROOT_REPO / "tools" / "ck3lens-explorer" if ROOT_REPO else None
BRIDGE_DIR: Optional[Path] = MCP_SERVER_DIR / "bridge" if MCP_SERVER_DIR else None
ACTIVE_PLAYSET_MANIFEST: Optional[Path] = PLAYSETS_DIR / "playset_manifest.json" if PLAYSETS_DIR else None

# CK3 utilities (derived from ROOT_UTILITIES)
LOGS_DIR: Optional[Path] = ROOT_UTILITIES / "logs" if ROOT_UTILITIES else None
SAVES_DIR: Optional[Path] = ROOT_UTILITIES / "save games" if ROOT_UTILITIES else None
CRASHES_DIR: Optional[Path] = ROOT_UTILITIES / "crashes" if ROOT_UTILITIES else None


# =============================================================================
# UTILITIES
# =============================================================================

def get_all_paths() -> dict[str, Optional[str]]:
    """Get all paths for diagnostics/configuration UI."""
    return {
        # Canonical Domain Roots
        "ROOT_GAME": str(ROOT_GAME) if ROOT_GAME else None,
        "ROOT_STEAM": str(ROOT_STEAM) if ROOT_STEAM else None,
        "ROOT_USER_DOCS": str(ROOT_USER_DOCS) if ROOT_USER_DOCS else None,
        "ROOT_UTILITIES": str(ROOT_UTILITIES) if ROOT_UTILITIES else None,
        "ROOT_LAUNCHER": str(ROOT_LAUNCHER) if ROOT_LAUNCHER else None,
        "ROOT_REPO": str(ROOT_REPO) if ROOT_REPO else None,
        "ROOT_WIP": str(ROOT_WIP),
        "ROOT_VSCODE": str(ROOT_VSCODE) if ROOT_VSCODE else None,
        "ROOT_OTHER": None,  # Catch-all has no path
        # Derived Infrastructure
        "CONFIG_DIR": str(CONFIG_DIR),
        "DB_PATH": str(DB_PATH),
        "VENV_PATH": str(VENV_PATH) if VENV_PATH else None,
        "PYTHON_EXE": str(PYTHON_EXE) if PYTHON_EXE else None,
        "PLAYSETS_DIR": str(PLAYSETS_DIR) if PLAYSETS_DIR else None,
        "MCP_SERVER_DIR": str(MCP_SERVER_DIR) if MCP_SERVER_DIR else None,
        "EXTENSION_DIR": str(EXTENSION_DIR) if EXTENSION_DIR else None,
    }


def verify_paths() -> dict[str, dict]:
    """Verify all paths exist for diagnostics."""
    all_paths = get_all_paths()
    return {
        name: {
            "path": path_str,
            "exists": Path(path_str).exists() if path_str else False,
        }
        for name, path_str in all_paths.items()
    }


def save_roots_config(roots: dict[str, str]) -> None:
    """Save roots configuration."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "version": "1.0",
        "roots": roots,
        "_auto_detected": False,
    }
    ROOTS_CONFIG.write_text(json.dumps(data, indent=2))
```

---

## TypeScript Integration

The VS Code extension must NOT duplicate path detection. It delegates to Python:

### Bridge Method

```python
# bridge/server.py

from ck3lens.paths import get_all_paths, ROOT_REPO, PYTHON_EXE

def handle_get_paths(params: dict) -> dict:
    """Return all canonical paths to TypeScript."""
    return get_all_paths()
```

### TypeScript Usage

```typescript
// pythonBridge.ts

export class PythonBridge {
    private paths: Record<string, string | null> | null = null;
    
    async getPaths(): Promise<Record<string, string | null>> {
        if (!this.paths) {
            this.paths = await this.call('get_paths', {});
        }
        return this.paths;
    }
    
    async getRootRepo(): Promise<string | null> {
        const paths = await this.getPaths();
        return paths.ROOT_REPO;
    }
}
```

### Bootstrap Problem

The extension needs `ROOT_REPO` to FIND the Python bridge. This is the ONE case where TypeScript must detect a path:

```typescript
// pythonBridge.ts - ONLY exception to the "no detection in TypeScript" rule

function bootstrapRootRepo(): string | null {
    // Check VS Code workspace folders first
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (workspaceFolders) {
        for (const folder of workspaceFolders) {
            const candidate = folder.uri.fsPath;
            if (fs.existsSync(path.join(candidate, 'pyproject.toml')) &&
                fs.existsSync(path.join(candidate, 'tools', 'ck3lens_mcp'))) {
                return candidate;
            }
        }
    }
    
    // Check config file
    const configPath = path.join(os.homedir(), '.ck3raven', 'roots.json');
    if (fs.existsSync(configPath)) {
        try {
            const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
            if (config.roots?.ROOT_REPO) {
                return config.roots.ROOT_REPO;
            }
        } catch {}
    }
    
    return null;
}
```

After bootstrap, ALL other path queries go through the Python bridge.

---

## Migration Plan

### Phase 1: Create ck3lens/paths.py

1. Create new module `ck3lens/paths.py` with all constants
2. Add `get_all_paths()`, `get_domain_roots()`, and `verify_paths()` utilities
3. Test: `from ck3lens.paths import ROOT_GAME, DB_PATH`

### Phase 2: Migrate capability_matrix.py

1. Import paths from `ck3lens.paths`
2. `RootCategory` enum values map to path constants
3. Remove any path detection from capability_matrix.py
4. Domain classification stays in WorldAdapter (the canonical resolver)

### Phase 3: Migrate WorldRouter

1. Delete `_get_vanilla_root()` method
2. Delete `_detect_ck3raven_root()` method  
3. Delete `_get_utility_roots()` method
4. Import from `ck3lens.paths` directly

### Phase 4: Migrate WorldAdapter

1. Remove all path parameters from `__init__`
2. Import from `ck3lens.paths` directly
3. Use constants in resolution methods

### Phase 5: Migrate workspace.py

1. Delete `DEFAULT_VANILLA_PATH` constant
2. Delete `DEFAULT_CK3_MOD_DIR` constant
3. Delete `DEFAULT_DB_PATH` constant
4. Delete `DEFAULT_CONFIG_PATH` constant
5. Import from `ck3lens.paths`

### Phase 6: Migrate server.py

1. Replace all hardcoded Steam paths
2. Import from `ck3lens.paths`
3. Add `ck3_paths()` MCP tool for diagnostics

### Phase 7: Migrate bridge/server.py

1. Add `get_paths` handler
2. Replace hardcoded paths with imports
3. Delete any detection logic

### Phase 8: Migrate pythonBridge.ts

1. Reduce to bootstrap-only detection
2. Add `getPaths()` method that calls bridge
3. Delete `possiblePaths` arrays
4. Delete `findCk3ravenPath()` complex logic

### Phase 9: Cleanup

1. Delete `scripts/temp_*.py` (legacy scripts)
2. Update `launcher_to_playset.py` to use imports
3. Run arch_lint
4. Update all documentation

---

## Files to Modify

| File | Changes |
|------|---------|
| `ck3lens/paths.py` | **NEW** - all path constants and detection |
| `ck3lens/policy/capability_matrix.py` | Remove detection, import from paths.py |
| `ck3lens/world_router.py` | Delete detection methods, import constants |
| `ck3lens/world_adapter.py` | Remove path params, import constants |
| `ck3lens/workspace.py` | Delete DEFAULT_* constants, import from paths.py |
| `server.py` | Replace hardcoded paths, add ck3_paths tool |
| `bridge/server.py` | Add get_paths handler, remove detection |
| `pythonBridge.ts` | Reduce to bootstrap, delegate to bridge |
| `scripts/launcher_to_playset.py` | Import from paths.py |
| `scripts/temp_*.py` | **DELETE** |

---

## MCP Tool: ck3_paths

```python
@mcp_tool
def ck3_paths(command: str = "status") -> dict:
    """
    Manage canonical paths.
    
    Commands:
        status  - Show all configured paths
        verify  - Check which paths exist
        detect  - Auto-detect and save roots.json
    """
    from ck3lens.paths import get_all_paths, verify_paths, save_roots_config
    
    if command == "status":
        return {"paths": get_all_paths()}
    
    elif command == "verify":
        return {"verification": verify_paths()}
    
    elif command == "detect":
        detected = {...}
        save_roots_config({k: v for k, v in detected.items() if v})
        return {"success": True, "detected": detected}
```

---

## arch_lint Updates (REQUIRED)

The arch_lint tool MUST be updated to enforce path hygiene. Add these rules:

### New Rule: PATH-01 (Parallel Path Aliases)

**Severity:** ERROR

Detects banned path variable names that create parallel authority:

```python
# scripts/arch_lint/rules/path_rules.py

PATH_ALIAS_BANNED = [
    r"\bvanilla_root\b",
    r"\bvanilla_path\b",
    r"\bworkshop_root\b",
    r"\bwip_root\b",
    r"\bck3raven_root\b",
    r"\bck3ravenPath\b",
    r"\butility_roots\b",
    r"\blauncher_path\b",
    r"\b_vanilla_root\b",
    r"\bself\._vanilla_root\b",
    r"\bself\.vanilla_root\b",
]
```

**Error message:** `PATH-01: Banned path alias '{match}'. Use canonical import from ck3lens.paths instead.`

### New Rule: PATH-02 (Hardcoded Default Constants)

**Severity:** ERROR

Detects DEFAULT_* path constants outside paths.py:

```python
PATH_DEFAULT_BANNED = [
    r"\bDEFAULT_VANILLA_PATH\b",
    r"\bDEFAULT_CK3_MOD_DIR\b",
    r"\bDEFAULT_DB_PATH\b",
    r"\bDEFAULT_CONFIG_PATH\b",
]
```

**Error message:** `PATH-02: Banned default constant '{match}'. Import from ck3lens.paths instead.`

### New Rule: PATH-03 (Path Detection Methods)

**Severity:** ERROR

Detects path detection methods outside paths.py:

```python
PATH_DETECTION_BANNED = [
    r"\bdef _get_vanilla_root\b",
    r"\bdef _detect_ck3raven_root\b",
    r"\bdef _detect_vanilla\b",
    r"\bdef _get_utility_roots\b",
    r"\bdef findCk3ravenPath\b",
    r"\bfunction bootstrapRootRepo\b",  # Allowed ONLY in pythonBridge.ts
]
```

**Error message:** `PATH-03: Path detection method '{match}' must be in ck3lens/paths.py only.`

### New Rule: PATH-04 (Hardcoded Steam Paths)

**Severity:** ERROR

Detects hardcoded Steam paths outside paths.py:

```python
PATH_HARDCODED_BANNED = [
    r"Program Files.*Steam.*steamapps",
    r"\.steam/steam/steamapps",
    r"SteamLibrary.*steamapps",
]
```

**Error message:** `PATH-04: Hardcoded Steam path. Use ROOT_GAME or ROOT_STEAM from ck3lens.paths.`

### Allowlist

These files are ALLOWED to contain path detection (the source of truth):

```python
PATH_RULES_ALLOWLIST = [
    "ck3lens/paths.py",           # THE source of truth
    "pythonBridge.ts",            # Bootstrap exception only
    "docs/PATHS_DESIGN_GUIDELINES.md",  # Documentation
]
```

---

## Verification

After implementation:

```bash
# Run arch_lint - should catch any violations
python -m scripts.arch_lint --errors-only

# Specifically test path rules
python -m scripts.arch_lint --rules PATH-01,PATH-02,PATH-03,PATH-04

# Manual verification (should return empty outside paths.py)
grep -rn "vanilla_root\|workshop_root\|wip_root\|ck3raven_root\|ck3ravenPath" tools/
grep -rn "DEFAULT_VANILLA\|DEFAULT_CK3_MOD\|DEFAULT_DB_PATH" tools/
grep -rn "_detect_\|_get_vanilla\|findCk3raven" tools/
```

All arch_lint PATH-* rules should pass with zero errors after migration is complete.

---

## Appendix: Hardcoded Paths Audit (February 1, 2026)

This section documents all hardcoded paths found in the codebase that need to be migrated to `ck3lens/paths.py`.

### Python Files - VIOLATIONS

| File | Line(s) | Problem | Fix |
|------|---------|---------|-----|
| [`tools/ck3lens_mcp/ck3lens/workspace.py`](../tools/ck3lens_mcp/ck3lens/workspace.py#L163) | 163 | `DEFAULT_VANILLA_PATH` constant | Import `ROOT_GAME` |
| [`tools/ck3lens_mcp/ck3lens/world_router.py`](../tools/ck3lens_mcp/ck3lens/world_router.py#L252-L254) | 252-254 | `_get_vanilla_root()` detection method | Delete, use `ROOT_GAME` |
| [`tools/ck3lens_mcp/server.py`](../tools/ck3lens_mcp/server.py#L374) | 374 | Hardcoded fallback vanilla path | Import `ROOT_GAME` |
| [`tools/ck3lens-explorer/bridge/server.py`](../tools/ck3lens-explorer/bridge/server.py#L231) | 231 | `vanilla_root=Path(...)` parameter | Import `ROOT_GAME` |
| [`scripts/launcher_to_playset.py`](../scripts/launcher_to_playset.py#L21) | 21, 46 | `STEAM_WORKSHOP` constant | Import `ROOT_STEAM`, `ROOT_GAME` |

### TypeScript Files - OK (Bootstrap Exception)

| File | Line(s) | Status |
|------|---------|--------|
| [`tools/ck3lens-explorer/src/setup/setupWizard.ts`](../tools/ck3lens-explorer/src/setup/setupWizard.ts#L532-L557) | 532-557 | ✅ **ALLOWED** - Bootstrap detection |

### Temporary Scripts - DELETE

| File | Action |
|------|--------|
| [`scripts/temp_sym.py`](../scripts/temp_sym.py) | **DELETE** |
| [`scripts/temp_w.py`](../scripts/temp_w.py) | **DELETE** |
| [`scripts/temp_w2.py`](../scripts/temp_w2.py) | **DELETE** |
| [`scripts/temp_wr.py`](../scripts/temp_wr.py) | **DELETE** |
| [`scripts/temp_write.py`](../scripts/temp_write.py) | **DELETE** |

### Migration Status

- [ ] Create `ck3lens/paths.py`
- [ ] Migrate `workspace.py`
- [ ] Migrate `world_router.py`
- [ ] Migrate `server.py`
- [ ] Migrate `bridge/server.py`
- [ ] Migrate `launcher_to_playset.py`
- [ ] Delete temp scripts (5 files)
- [ ] Run arch_lint PATH-* rules
