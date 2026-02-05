# Paths Architecture Design Brief v2

> **Status:** DRAFT - Pending Approval  
> **Date:** February 4, 2026  
> **Supersedes:** PATHS_DESIGN_GUIDELINES.md (portions)  
> **Purpose:** Updated conceptual design for canonical path resolution

---

## Executive Summary

This design brief updates the paths architecture to reflect current implementation reality and planned improvements. Key changes from the original PATHS_DESIGN_GUIDELINES.md:

1. **ROOT_CK3RAVEN_DATA** - New root category for `~/.ck3raven/` (not in original spec)
2. **ROOT_VSCODE** - New root category for VS Code user settings
3. **Capability matrix as sole enforcement driver** - Single data structure keyed by `(mode, root, subdir)`
4. **Contract requirement** - All write operations require an active contract
5. **Single-module pattern** - All path logic consolidates to `ck3lens/paths.py`
6. **No aliases or intermediate variables** - ROOTS registry maps constants to paths directly
7. **No per-root getter functions** - Single `get_root(root)` function uses registry

---

## 1. Root Categories

### 1.1 Complete Root Enumeration

| Root | Path | Description |
|------|------|-------------|
| `ROOT_REPO` | Detected at runtime | ck3raven source repository |
| `ROOT_USER_DOCS` | `~/Documents/Paradox Interactive/Crusader Kings III/` | CK3 user documents (saves, local mods) |
| `ROOT_STEAM` | Steam library path (from config) | Workshop mods location |
| `ROOT_GAME` | CK3 install path (from config) | Vanilla game files |
| `ROOT_UTILITIES` | `~/AppData/Local/` | Launcher DB, cache locations |
| `ROOT_LAUNCHER` | `~/AppData/Local/Paradox Interactive/launcher-v2/` | Launcher registry |
| `ROOT_CK3RAVEN_DATA` | `~/.ck3raven/` | ck3raven runtime data directory |
| `ROOT_VSCODE` | `~/AppData/Roaming/Code/User/` | VS Code user settings |
| `ROOT_EXTERNAL` | Anything else | Catch-all for unclassified paths (always denied) |

**Notes:**
- `ROOT_EXTERNAL` is a classifier bucket for paths outside all other roots. It is NOT a valid write target.
- `ROOT_TEMP` is deleted - ephemeral scratch goes to `ROOT_CK3RAVEN_DATA/wip/` or `ROOT_CK3RAVEN_DATA/cache/`.
- WIP is NOT a separate root. It is always `ROOT_CK3RAVEN_DATA/wip/`.

### 1.2 ROOT_CK3RAVEN_DATA Structure

```
~/.ck3raven/
├── config/              # User configuration (workspace.toml, etc.)
├── playsets/            # Playset definitions (*.json)
├── wip/                 # Agent scratch workspace
├── logs/                # Application logs
├── journal/             # Chat session journals
├── cache/               # Derived caches (rebuild-safe)
├── db/                  # SQLite database (single-writer daemon only)
├── daemon/              # Daemon runtime files (pid, lock, socket)
└── artifacts/           # Compliance artifacts (tokens, proofs)
```

---

## 2. Implementation: ck3lens/paths.py

### 2.1 ROOTS Registry

A single registry maps root constants to paths. No per-root getter functions.

```python
"""
Canonical path resolution for CK3 Lens.

This module is THE authority for:
1. Root category definitions
2. Path-to-root classification
3. ROOTS registry (constants → paths)

NO OTHER MODULE may define path constants.
NO per-root getter functions (except repo detection).
"""

from enum import Enum, auto
from pathlib import Path
from dataclasses import dataclass
from functools import lru_cache
import platform

class RootCategory(Enum):
    """Canonical root categories."""
    ROOT_REPO = auto()
    ROOT_USER_DOCS = auto()
    ROOT_STEAM = auto()
    ROOT_GAME = auto()
    ROOT_UTILITIES = auto()
    ROOT_LAUNCHER = auto()
    ROOT_CK3RAVEN_DATA = auto()
    ROOT_VSCODE = auto()
    ROOT_EXTERNAL = auto()  # Catch-all for unclassified paths

# ---------------------------------------------------------------------
# ROOTS REGISTRY - THE source of truth for path constants
# ---------------------------------------------------------------------

def _build_roots_registry() -> dict[RootCategory, Path]:
    """
    Build the roots registry at module load.
    
    Most roots are constants. Exceptions:
    - ROOT_REPO: detected at runtime (walk up from __file__)
    - ROOT_STEAM, ROOT_GAME: from user config (workspace.toml)
    - ROOT_EXTERNAL: not a real path, used only as classifier
    """
    home = Path.home()
    
    # Platform-specific paths
    if platform.system() == "Windows":
        user_docs = home / "Documents" / "Paradox Interactive" / "Crusader Kings III"
        utilities = home / "AppData" / "Local"
        launcher = utilities / "Paradox Interactive" / "launcher-v2"
        vscode = home / "AppData" / "Roaming" / "Code" / "User"
    else:
        # macOS/Linux - adjust as needed
        user_docs = home / ".local" / "share" / "Paradox Interactive" / "Crusader Kings III"
        utilities = home / ".local" / "share"
        launcher = utilities / "Paradox Interactive" / "launcher-v2"
        vscode = home / ".config" / "Code" / "User"
    
    return {
        # Constants - always known
        RootCategory.ROOT_USER_DOCS: user_docs,
        RootCategory.ROOT_UTILITIES: utilities,
        RootCategory.ROOT_LAUNCHER: launcher,
        RootCategory.ROOT_CK3RAVEN_DATA: home / ".ck3raven",
        RootCategory.ROOT_VSCODE: vscode,
        # ROOT_EXTERNAL is not a path - it's a classifier
    }

# Immutable registry built once at module load
ROOTS: dict[RootCategory, Path] = _build_roots_registry()

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
    Get the absolute path for a root category.
    
    Returns None if root is not available (e.g., ROOT_REPO not detected,
    ROOT_STEAM/ROOT_GAME not configured, ROOT_EXTERNAL).
    """
    if root == RootCategory.ROOT_REPO:
        return _detect_repo_root()
    if root == RootCategory.ROOT_EXTERNAL:
        return None  # Not a real path
    if root in (RootCategory.ROOT_STEAM, RootCategory.ROOT_GAME):
        # These come from config - placeholder for now
        return _get_from_config(root)
    return ROOTS.get(root)

def _get_from_config(root: RootCategory) -> Path | None:
    """Get configurable roots from workspace.toml."""
    # TODO: Load from config
    return None

# ---------------------------------------------------------------------
# Derived paths - convenience accessors
# ---------------------------------------------------------------------

def get_wip_dir() -> Path:
    """Get the WIP workspace directory. Always ROOT_CK3RAVEN_DATA/wip/."""
    return ROOTS[RootCategory.ROOT_CK3RAVEN_DATA] / "wip"

def get_db_path() -> Path:
    """Get the database path."""
    return ROOTS[RootCategory.ROOT_CK3RAVEN_DATA] / "db" / "ck3raven.db"

def get_playset_dir() -> Path:
    """Get the playsets directory."""
    return ROOTS[RootCategory.ROOT_CK3RAVEN_DATA] / "playsets"

def get_logs_dir() -> Path:
    """Get the logs directory."""
    return ROOTS[RootCategory.ROOT_CK3RAVEN_DATA] / "logs"

def get_local_mods_folder() -> Path:
    """Get the local mods folder (writable mods location)."""
    return ROOTS[RootCategory.ROOT_USER_DOCS] / "mod"
```

### 2.2 Path Resolution

```python
@dataclass(frozen=True)
class ResolvedPath:
    """Result of path resolution."""
    root: RootCategory
    absolute: Path
    relative: str  # Relative to root
    subdirectory: str | None  # First path component under root (for CK3RAVEN_DATA)

def resolve(path: str | Path) -> ResolvedPath:
    """
    Resolve any path to its canonical root category.
    
    This is a STRUCTURAL operation only - it identifies what root
    a path belongs to. It does NOT check permissions.
    
    Classification order (most specific first):
    1. ROOT_REPO (if detected and path is under it)
    2. ROOT_CK3RAVEN_DATA
    3. ROOT_VSCODE
    4. ROOT_LAUNCHER (subset of ROOT_UTILITIES)
    5. ROOT_UTILITIES
    6. ROOT_USER_DOCS
    7. ROOT_STEAM (from config)
    8. ROOT_GAME (from config)
    9. ROOT_EXTERNAL (catch-all)
    """
    abs_path = Path(path).resolve()
    
    # Check each root in specificity order
    for root, root_path in _resolution_order():
        if root_path and _is_under(abs_path, root_path):
            relative = abs_path.relative_to(root_path)
            subdirectory = relative.parts[0] if relative.parts else None
            return ResolvedPath(
                root=root,
                absolute=abs_path,
                relative=str(relative),
                subdirectory=subdirectory if root == RootCategory.ROOT_CK3RAVEN_DATA else None,
            )
    
    # Anything else is ROOT_EXTERNAL
    return ResolvedPath(
        root=RootCategory.ROOT_EXTERNAL,
        absolute=abs_path,
        relative=str(abs_path),
        subdirectory=None,
    )

def _resolution_order() -> list[tuple[RootCategory, Path | None]]:
    """Return roots in classification order (most specific first)."""
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

def _is_under(path: Path, root: Path) -> bool:
    """Check if path is under root (case-insensitive on Windows)."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
```

---

## 3. Capability Matrix

### 3.1 The Matrix is THE Enforcement Driver

Enforcement is a **pure function** that consults the capability matrix. No per-domain enforcement functions.

```python
"""
Capability matrix for path enforcement.

The matrix is keyed by (mode, root, subdir) where subdir is optional.
Only ROOT_CK3RAVEN_DATA uses subdir lookup - all other roots use (mode, root) only.

Global invariants OVERRIDE the matrix:
1. Contract required for all write/delete operations
2. db/ and daemon/ subdirs are NEVER writable (Single-Writer Architecture)
3. ROOT_EXTERNAL is always denied
"""

from dataclasses import dataclass
from enum import Enum

@dataclass(frozen=True)
class Capability:
    read: bool = False
    write: bool = False
    delete: bool = False

# Type alias for matrix key
MatrixKey = tuple[str, RootCategory, str | None]  # (mode, root, subdir or None)

# ---------------------------------------------------------------------
# THE CAPABILITY MATRIX
# ---------------------------------------------------------------------

CAPABILITY_MATRIX: dict[MatrixKey, Capability] = {
    # =========================================================
    # ck3lens mode
    # =========================================================
    
    # Game content (read-only)
    ("ck3lens", RootCategory.ROOT_GAME, None): Capability(read=True),
    ("ck3lens", RootCategory.ROOT_STEAM, None): Capability(read=True),
    
    # User docs - mods are writable
    ("ck3lens", RootCategory.ROOT_USER_DOCS, None): Capability(read=True, write=True, delete=True),
    
    # CK3RAVEN_DATA - per-subdirectory rules
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "config"): Capability(read=True, write=True),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "playsets"): Capability(read=True, write=True, delete=True),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "wip"): Capability(read=True, write=True, delete=True),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "logs"): Capability(read=True, write=True),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "journal"): Capability(read=True, write=True),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "cache"): Capability(read=True, write=True, delete=True),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "db"): Capability(read=True),  # Daemon-only writes
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "daemon"): Capability(read=True),  # Daemon-only writes
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "artifacts"): Capability(read=True, write=True),
    
    # Utilities (read-only)
    ("ck3lens", RootCategory.ROOT_LAUNCHER, None): Capability(read=True),
    ("ck3lens", RootCategory.ROOT_UTILITIES, None): Capability(read=True),
    ("ck3lens", RootCategory.ROOT_VSCODE, None): Capability(read=True),
    
    # Repo not visible in ck3lens mode
    ("ck3lens", RootCategory.ROOT_REPO, None): Capability(),
    
    # External always denied
    ("ck3lens", RootCategory.ROOT_EXTERNAL, None): Capability(),
    
    # =========================================================
    # ck3raven-dev mode
    # =========================================================
    
    # Repo - full access
    ("ck3raven-dev", RootCategory.ROOT_REPO, None): Capability(read=True, write=True, delete=True),
    
    # Game content (read-only for testing)
    ("ck3raven-dev", RootCategory.ROOT_GAME, None): Capability(read=True),
    ("ck3raven-dev", RootCategory.ROOT_STEAM, None): Capability(read=True),
    ("ck3raven-dev", RootCategory.ROOT_USER_DOCS, None): Capability(read=True),
    
    # CK3RAVEN_DATA - per-subdirectory rules
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "config"): Capability(read=True, write=True, delete=True),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "playsets"): Capability(read=True, write=True, delete=True),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "wip"): Capability(read=True, write=True, delete=True),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "logs"): Capability(read=True, write=True, delete=True),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "journal"): Capability(read=True, write=True, delete=True),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "cache"): Capability(read=True, write=True, delete=True),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "db"): Capability(read=True),  # Daemon-only writes
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "daemon"): Capability(read=True),  # Daemon-only writes
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
    
    For ROOT_CK3RAVEN_DATA, uses (mode, root, subdirectory).
    For all other roots, uses (mode, root, None).
    """
    if root == RootCategory.ROOT_CK3RAVEN_DATA and subdirectory:
        key = (mode, root, subdirectory)
        if key in CAPABILITY_MATRIX:
            return CAPABILITY_MATRIX[key]
    
    # Fall back to root-level lookup
    key = (mode, root, None)
    return CAPABILITY_MATRIX.get(key, Capability())
```

### 3.2 Enforcement as Pure Function

```python
"""
Enforcement - pure function driven by capability matrix.

NO per-domain enforcement functions.
Global invariants OVERRIDE matrix decisions.
"""

from dataclasses import dataclass
from enum import Enum

class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"

class OperationType(Enum):
    FILE_READ = "read"
    FILE_WRITE = "write"
    FILE_DELETE = "delete"

@dataclass(frozen=True)
class EnforcementResult:
    decision: Decision
    reason: str

def enforce(
    mode: str,
    operation: OperationType,
    resolved: ResolvedPath,
    has_contract: bool,
) -> EnforcementResult:
    """
    Pure enforcement function.
    
    Checks:
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
    
    # ─────────────────────────────────────────────────────────────
    # GLOBAL INVARIANT 1: ROOT_EXTERNAL is always denied
    # ─────────────────────────────────────────────────────────────
    if resolved.root == RootCategory.ROOT_EXTERNAL:
        return EnforcementResult(
            decision=Decision.DENY,
            reason="Path is outside all known roots (ROOT_EXTERNAL)",
        )
    
    # ─────────────────────────────────────────────────────────────
    # GLOBAL INVARIANT 2: Contract required for write/delete
    # ─────────────────────────────────────────────────────────────
    if operation in (OperationType.FILE_WRITE, OperationType.FILE_DELETE):
        if not has_contract:
            return EnforcementResult(
                decision=Decision.DENY,
                reason="Contract required for write/delete operations",
            )
    
    # ─────────────────────────────────────────────────────────────
    # GLOBAL INVARIANT 3: db/ and daemon/ are NEVER writable
    # ─────────────────────────────────────────────────────────────
    if resolved.root == RootCategory.ROOT_CK3RAVEN_DATA:
        if resolved.subdirectory in ("db", "daemon"):
            if operation in (OperationType.FILE_WRITE, OperationType.FILE_DELETE):
                return EnforcementResult(
                    decision=Decision.DENY,
                    reason=f"/{resolved.subdirectory}/ is daemon-only (Single-Writer Architecture)",
                )
    
    # ─────────────────────────────────────────────────────────────
    # MATRIX LOOKUP
    # ─────────────────────────────────────────────────────────────
    cap = get_capability(mode, resolved.root, resolved.subdirectory)
    
    # Check capability for requested operation
    if operation == OperationType.FILE_READ and cap.read:
        return EnforcementResult(decision=Decision.ALLOW, reason="Matrix allows read")
    if operation == OperationType.FILE_WRITE and cap.write:
        return EnforcementResult(decision=Decision.ALLOW, reason="Matrix allows write")
    if operation == OperationType.FILE_DELETE and cap.delete:
        return EnforcementResult(decision=Decision.ALLOW, reason="Matrix allows delete")
    
    # Default deny
    return EnforcementResult(
        decision=Decision.DENY,
        reason=f"Capability matrix denies {operation.value} for {resolved.root.name}",
    )
```

---

## 4. Banned Terms and Patterns

### 4.1 Banned Parameter Names

| Banned Term | Why | Replacement |
|-------------|-----|-------------|
| `wip_root` | Alias adds no value | `get_wip_dir()` or `ROOTS[ROOT_CK3RAVEN_DATA] / "wip"` |
| `ck3raven_root` | Alias adds no value | `get_root(ROOT_REPO)` |
| `vanilla_root` | Alias adds no value | `get_root(ROOT_GAME)` |
| `ck3raven_data_root` | Alias adds no value | `ROOTS[ROOT_CK3RAVEN_DATA]` |

### 4.2 Banned Patterns

```python
# ❌ BANNED - Per-root getter functions
def _get_ck3raven_data_root() -> Path:
    return Path.home() / ".ck3raven"

def _get_wip_root() -> Path:
    return Path.home() / ".ck3raven" / "wip"

# ❌ BANNED - Per-domain enforcement functions
def _enforce_ck3raven_data_access(...):
    ...

def _enforce_repo_access(...):
    ...

# ❌ BANNED - Conditional WIP routing
if mode == "ck3raven-dev":
    wip = repo / ".wip"
else:
    wip = Path.home() / ".ck3raven" / "wip"
```

```python
# ✅ REQUIRED - Use ROOTS registry directly
wip_dir = ROOTS[RootCategory.ROOT_CK3RAVEN_DATA] / "wip"

# ✅ REQUIRED - Single get_root() for dynamic roots
repo = get_root(RootCategory.ROOT_REPO)

# ✅ REQUIRED - Pure enforcement via matrix
result = enforce(mode, operation, resolved, has_contract)
```

---

## 5. Tests

### 5.1 Matrix is Sole Driver

```python
def test_matrix_is_sole_driver():
    """Assert that enforcement decisions come ONLY from matrix + invariants."""
    
    # Test that adding a matrix entry changes enforcement
    # Test that removing a matrix entry changes enforcement
    # Test that no other code path affects decisions
    ...

def test_global_invariants_override_matrix():
    """Assert that invariants override even permissive matrix entries."""
    
    # Even if matrix says write=True for db/, enforcement denies
    resolved = paths.resolve("~/.ck3raven/db/test.db")
    result = enforce("ck3raven-dev", OperationType.FILE_WRITE, resolved, has_contract=True)
    assert result.decision == Decision.DENY
    assert "daemon-only" in result.reason

def test_contract_required_for_writes():
    """Assert contract is required even for permissive roots."""
    
    resolved = paths.resolve("~/.ck3raven/wip/test.py")
    result = enforce("ck3lens", OperationType.FILE_WRITE, resolved, has_contract=False)
    assert result.decision == Decision.DENY
    assert "Contract required" in result.reason

def test_external_always_denied():
    """Assert ROOT_EXTERNAL is always denied."""
    
    resolved = paths.resolve("C:/random/path.txt")
    assert resolved.root == RootCategory.ROOT_EXTERNAL
    
    for op in OperationType:
        result = enforce("ck3raven-dev", op, resolved, has_contract=True)
        assert result.decision == Decision.DENY
```

---

## 6. Paths Doctor

A diagnostic function to validate path configuration. Run this during startup or on-demand.

```python
def paths_doctor() -> list[DiagnosticResult]:
    """
    Validate all path constants and report issues.
    
    Checks:
    1. Each ROOTS entry exists on filesystem
    2. ROOT_REPO was detected (if in ck3raven-dev mode)
    3. ROOT_STEAM and ROOT_GAME are configured (warns if not)
    4. Subdirectories of ROOT_CK3RAVEN_DATA exist
    5. Permissions are correct (can write where expected)
    
    Returns list of diagnostics (info, warning, error).
    """
    results = []
    
    for root, path in ROOTS.items():
        if not path.exists():
            results.append(DiagnosticResult(
                level="warning",
                root=root,
                message=f"Path does not exist: {path}",
            ))
    
    # Check CK3RAVEN_DATA subdirectories
    data_root = ROOTS[RootCategory.ROOT_CK3RAVEN_DATA]
    for subdir in ("config", "playsets", "wip", "logs", "journal", "cache", "db", "daemon"):
        subdir_path = data_root / subdir
        if not subdir_path.exists():
            results.append(DiagnosticResult(
                level="info",
                root=RootCategory.ROOT_CK3RAVEN_DATA,
                message=f"Subdirectory does not exist (will be created): {subdir}/",
            ))
    
    # Check configurable roots
    if get_root(RootCategory.ROOT_STEAM) is None:
        results.append(DiagnosticResult(
            level="warning",
            root=RootCategory.ROOT_STEAM,
            message="ROOT_STEAM not configured - Workshop mods will not be available",
        ))
    
    if get_root(RootCategory.ROOT_GAME) is None:
        results.append(DiagnosticResult(
            level="warning",
            root=RootCategory.ROOT_GAME,
            message="ROOT_GAME not configured - Vanilla files will not be available",
        ))
    
    return results
```

---

## 7. Migration Scope

### 7.1 Files to Update

| File | Changes |
|------|---------|
| `ck3lens/paths.py` | **NEW** - Create with ROOTS registry, resolve(), get_root() |
| `ck3lens/capability_matrix.py` | **REFACTOR** - Replace with pure matrix data structure |
| `ck3lens/policy/enforcement.py` | **REFACTOR** - Single enforce() function, delete per-domain functions |
| `ck3lens/world_adapter.py` | Remove path parameters, use `paths.resolve()` |
| `ck3lens/world_router.py` | Delete - no longer needed |
| `server.py` | Use `paths.resolve()` and `enforce()` |

### 7.2 Banned Terms to Remove

| Term | Files Affected |
|------|----------------|
| `wip_root` | `world_router.py`, `world_adapter.py` |
| `ck3raven_root` | `world_router.py`, `world_adapter.py` |
| `vanilla_root` | `world_router.py`, `world_adapter.py` |
| `_get_ck3raven_data_root()` | Delete entirely |
| `_enforce_*_access()` | `enforcement.py` - replace with single enforce() |

---

## 8. Approval Checklist

Before implementation:

- [ ] ROOTS registry pattern confirmed
- [ ] Capability matrix as sole driver confirmed
- [ ] Global invariants list complete
- [ ] ROOT_EXTERNAL as catch-all confirmed
- [ ] ROOT_TEMP deleted
- [ ] No per-root getter functions
- [ ] No per-domain enforcement functions
- [ ] Tests cover matrix-driven decisions

---

## 9. References

- [CANONICAL_ARCHITECTURE.md](../CANONICAL_ARCHITECTURE.md) - Canonical architecture rules
- [PATHS_DESIGN_GUIDELINES.md](../PATHS_DESIGN_GUIDELINES.md) - Original paths spec
- [SINGLE_WRITER_ARCHITECTURE.md](../SINGLE_WRITER_ARCHITECTURE.md) - DB write authority
