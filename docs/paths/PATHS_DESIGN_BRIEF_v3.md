# Paths Architecture Design Brief v3

> **Status:** CURRENT IMPLEMENTATION  
> **Date:** February 5, 2026  
> **Supersedes:** PATHS_DESIGN_BRIEF_v2.md  
> **Purpose:** Documents the actual implemented paths architecture

---

## Executive Summary

This document describes the **implemented** paths architecture. Key design choices:

1. **Direct constants** - No ROOTS registry, no get_root() function. Import constants directly.
2. **9 root categories** - Enum for classification, constants for actual paths
3. **Resolution in WorldAdapter** - paths.py has constants only, WorldAdapter.resolve() does classification
4. **Capability matrix with subfolders_writable** - Protects root-level files (like `.mod`) automatically
5. **Config-driven** - Configurable paths loaded from workspace.toml at module import

---

## 1. Root Categories

### 1.1 Complete Root Enumeration

| Root | Source | Description |
|------|--------|-------------|
| `ROOT_REPO` | `Path(__file__).parent...` | ck3raven source repository |
| `ROOT_CK3RAVEN_DATA` | `Path.home() / ".ck3raven"` | ck3raven runtime data |
| `ROOT_GAME` | config (required) | Vanilla game files |
| `ROOT_STEAM` | config (required) | Workshop mods location |
| `ROOT_USER_DOCS` | config or OS-default | CK3 user documents |
| `ROOT_UTILITIES` | config or OS-default | AppData/Local |
| `ROOT_LAUNCHER` | config or OS-default | Launcher registry |
| `ROOT_VSCODE` | config or OS-default | VS Code user settings |
| `ROOT_EXTERNAL` | N/A | Catch-all (always denied) |

### 1.2 ROOT_CK3RAVEN_DATA Structure

```
~/.ck3raven/
├── config/              # User configuration (workspace.toml)
├── playsets/            # Playset definitions (*.json)
├── wip/                 # Agent scratch workspace
├── logs/                # Application logs
├── db/                  # Database (daemon-only writes)
├── daemon/              # Daemon runtime files
└── ck3raven.db          # SQLite database
```

---

## 2. Implementation: ck3lens/paths.py

### 2.1 Design Principle: Constants Only

paths.py exports **constants**, not functions. No registry, no lookups.

```python
# Import directly - no intermediaries
from ck3lens.paths import ROOT_REPO, ROOT_GAME, WIP_DIR, LOCAL_MODS_FOLDER
```

### 2.2 Actual Implementation

```python
from pathlib import Path
from enum import Enum

# Config loaded once at module import
_config = _load_paths_from_config()

class RootCategory(Enum):
    """For classify_path return type."""
    ROOT_REPO = "ROOT_REPO"
    ROOT_CK3RAVEN_DATA = "ROOT_CK3RAVEN_DATA"
    # ... etc

# PATH CONSTANTS - computed once at module load
ROOT_REPO: Path = Path(__file__).resolve().parent.parent.parent.parent
ROOT_CK3RAVEN_DATA: Path = Path.home() / ".ck3raven"
ROOT_GAME: Path | None = _config.paths.game_path
ROOT_STEAM: Path | None = _config.paths.workshop_path
# ... etc

# DERIVED PATHS - subdirectories of ROOT_CK3RAVEN_DATA
WIP_DIR: Path = ROOT_CK3RAVEN_DATA / "wip"
DB_PATH: Path = ROOT_CK3RAVEN_DATA / "ck3raven.db"
PLAYSET_DIR: Path = ROOT_CK3RAVEN_DATA / "playsets"
LOGS_DIR: Path = ROOT_CK3RAVEN_DATA / "logs"
CONFIG_DIR: Path = ROOT_CK3RAVEN_DATA / "config"

# Local mods folder - from config or derived
LOCAL_MODS_FOLDER: Path | None = (
    _config.paths.local_mods_folder 
    or (ROOT_USER_DOCS / "mod" if ROOT_USER_DOCS else None)
)
```

### 2.3 What paths.py Does NOT Have

- ❌ `ROOTS` dict/registry
- ❌ `get_root(category)` function
- ❌ `resolve(path)` function (this is WorldAdapter's job)
- ❌ `get_wip_dir()`, `get_db_path()` functions (use constants directly)

---

## 3. Path Resolution (WorldAdapter)

### 3.1 Resolution is WorldAdapter's Job

paths.py has constants. WorldAdapter.resolve() classifies paths:

```python
class WorldAdapter:
    def resolve(self, path: str) -> ResolutionResult:
        """
        Classify path to root category.
        Returns ResolutionResult with:
        - root_category: RootCategory enum
        - absolute_path: Path
        - subdirectory: str | None (first component under root)
        - relative_path: str | None (full relative path)
        """
```

### 3.2 Resolution Order (Most Specific First)

1. ROOT_CK3RAVEN_DATA (contains WIP, db, etc.)
2. ROOT_REPO
3. ROOT_USER_DOCS
4. ROOT_GAME
5. ROOT_STEAM
6. ROOT_UTILITIES
7. ROOT_LAUNCHER
8. ROOT_VSCODE
9. ROOT_EXTERNAL (catch-all)

---

## 4. Capability Matrix

### 4.1 subfolders_writable Pattern

The `subfolders_writable` flag enables writes **only** to nested paths (3+ components).

This automatically protects:
- `.mod` registry files in `mod/` folder
- Top-level files in any root

```python
@dataclass(frozen=True)
class Capability:
    read: bool = False
    write: bool = False
    delete: bool = False
    subfolders_writable: bool = False  # Only nested paths writable

def get_capability(mode, root, relative_path=None) -> Capability:
    cap = CAPABILITY_MATRIX.get((mode, root), Capability())
    
    if cap.subfolders_writable and relative_path:
        parts = Path(relative_path).parts
        if len(parts) >= 3:  # e.g., "mod/MyMod/file.txt"
            return Capability(read=cap.read, write=True, delete=True)
    
    return cap
```

### 4.2 Matrix Entries

```python
CAPABILITY_MATRIX = {
    # ck3lens mode
    ("ck3lens", RootCategory.ROOT_USER_DOCS): Capability(
        read=True, 
        subfolders_writable=True  # mod/MyMod/file.txt writable, mod/*.mod protected
    ),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA): Capability(read=True, write=True, delete=True),
    ("ck3lens", RootCategory.ROOT_GAME): Capability(read=True),
    ("ck3lens", RootCategory.ROOT_STEAM): Capability(read=True),
    
    # ck3raven-dev mode
    ("ck3raven-dev", RootCategory.ROOT_REPO): Capability(read=True, write=True, delete=True),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA): Capability(read=True, write=True, delete=True),
    # ... etc
}
```

### 4.3 Global Invariants (Override Matrix)

1. **ROOT_EXTERNAL** - Always denied (catch-all for unknown paths)
2. **db/ and daemon/ subdirs** - Never writable (Single-Writer Architecture)
3. **Contract required** - All write/delete operations require active contract

### 4.4 Subdirectory-Based Authority (CRITICAL)

The capability matrix uses a **three-key lookup**: `(mode, root_category, subdirectory)`. This enables fine-grained permissions where a root category has mixed-authority subdirectories.

#### 4.4.1 The Three-Way Contract

Subdirectory-based authority requires cooperation between three components:

| Component | Responsibility | Must Provide |
|-----------|----------------|--------------|
| **WorldAdapter.resolve()** | Classify paths | `subdirectory` and `relative_path` fields in ResolutionResult |
| **capability_matrix.py** | Permissions lookup | Entries keyed by `(mode, root, subdirectory)` tuple |
| **enforcement.py** | Final decision | Logic that checks `resolved.subdirectory` for special handling |

**If ANY component fails its responsibility, permissions break silently.**

#### 4.4.2 Required ResolutionResult Fields

When resolving paths that need subdirectory-based permissions:

```python
@dataclass
class ResolutionResult:
    root_category: RootCategory      # Always required
    absolute_path: Path              # Always required
    subdirectory: str | None = None  # REQUIRED for subdirectory authority
    relative_path: str | None = None # REQUIRED for subfolders_writable
```

**Example resolutions:**

| Input | root_category | subdirectory | relative_path |
|-------|---------------|--------------|---------------|
| `mod://MyMod/common/traits/foo.txt` | ROOT_USER_DOCS | `"mod"` | `"mod/MyMod/common/traits/foo.txt"` |
| `wip://analysis/report.md` | ROOT_CK3RAVEN_DATA | `"wip"` | `"wip/analysis/report.md"` |
| `data://config/workspace.toml` | ROOT_CK3RAVEN_DATA | `"config"` | `"config/workspace.toml"` |

#### 4.4.3 Capability Matrix Entry Patterns

**Pattern 1: subfolders_writable (ROOT_USER_DOCS/mod)**

Protects root-level files (`.mod` registry) while allowing nested writes:

```python
# Matrix entry
("ck3lens", ROOT_USER_DOCS, "mod"): Capability(read=True, subfolders_writable=True)

# Lookup logic in get_capability():
if cap.subfolders_writable and relative_path:
    parts = Path(relative_path).parts  # ["mod", "MyMod", "file.txt"]
    if len(parts) >= 3:  # 3+ components = nested = writable
        return Capability(read=True, write=True, delete=True)
```

**Pattern 2: Direct subdirectory grants (ROOT_CK3RAVEN_DATA/wip)**

Certain subdirectories have explicit permissions:

```python
# Matrix entries
("ck3lens", ROOT_CK3RAVEN_DATA, "wip"): Capability(read=True, write=True, delete=True)
("ck3lens", ROOT_CK3RAVEN_DATA, "playsets"): Capability(read=True)  # Read-only
("ck3lens", ROOT_CK3RAVEN_DATA, "db"): Capability(read=True)  # Daemon-only writes
```

**Pattern 3: enforcement.py special handling**

Some logic lives in enforcement.py, not the matrix:

```python
# In enforcement.py validate_write():
if resolved.subdirectory == "wip":
    # WIP has explicit write permission via capability lookup
    pass  # Let matrix decide
elif resolved.subdirectory == "db":
    return deny("Database writes require daemon")
```

#### 4.4.4 Common Failure Mode: Missing Subdirectory

**Symptom:** Writes denied with `EN-WRITE-D-001: Write not permitted for (mode, ROOT_X)`

**Root cause:** `resolve()` returned ResolutionResult without setting `subdirectory` field

**The capability lookup then:**
1. Looks for `(mode, ROOT_X, None)` - finds base entry (often read-only)
2. Never sees the subdirectory-specific entry that grants write access
3. Denies the operation

**Prevention checklist:**
- [ ] `_resolve_to_absolute()` extracts subdirectory from path
- [ ] Subdirectory is first path component under root (e.g., `"mod"`, `"wip"`, `"config"`)
- [ ] `relative_path` computed relative to the ROOT constant (not subdirectory)
- [ ] Capability matrix has entry for `(mode, root, subdirectory)` tuple

#### 4.4.5 Adding New Subdirectory Authority

When adding permissions for a new subdirectory:

1. **capability_matrix.py**: Add entry with 3-tuple key
   ```python
   ("ck3lens", ROOT_CK3RAVEN_DATA, "new_subdir"): Capability(read=True, write=True)
   ```

2. **world_adapter.py**: Ensure `_resolve_to_absolute()` sets subdirectory
   ```python
   # In address resolution logic:
   subdirectory = parts[0] if parts else None
   relative_path = str(Path(*parts)) if parts else None
   ```

3. **Test**: Verify the full round-trip works
   ```python
   result = world.resolve("data://new_subdir/test.txt")
   assert result.subdirectory == "new_subdir"
   assert result.relative_path == "new_subdir/test.txt"
   
   cap = get_capability(mode, result.root_category, result.subdirectory, result.relative_path)
   assert cap.write == True
   ```

---

## 5. Banned Patterns

### 5.1 Banned in paths.py

```python
# ❌ BANNED - Registry/dict of roots
ROOTS: dict[RootCategory, Path] = {...}

# ❌ BANNED - Getter functions
def get_root(category: RootCategory) -> Path: ...
def get_wip_dir() -> Path: ...

# ❌ BANNED - Resolution (WorldAdapter's job)
def resolve(path: str) -> ResolvedPath: ...
```

### 5.2 Banned Elsewhere

```python
# ❌ BANNED - Special .mod file checks (subfolders_writable handles this)
if path.endswith(".mod"):
    return DENY

# ❌ BANNED - Conditional WIP paths
if mode == "ck3raven-dev":
    wip = repo / ".wip"
else:
    wip = home / ".ck3raven" / "wip"

# ❌ BANNED - Alias parameters
def create(wip_root=None, ck3raven_root=None, vanilla_root=None): ...
```

### 5.3 Required Pattern

```python
# ✅ REQUIRED - Import constants directly
from ck3lens.paths import ROOT_REPO, WIP_DIR, LOCAL_MODS_FOLDER

# ✅ REQUIRED - Use WorldAdapter for resolution
result = world.resolve(path)

# ✅ REQUIRED - Use capability matrix for enforcement
cap = get_capability(mode, result.root_category, result.relative_path)
```

---

## 6. Files

| File | Responsibility |
|------|----------------|
| `ck3lens/paths.py` | Constants only (ROOT_*, WIP_DIR, etc.) |
| `ck3lens/world_adapter.py` | Resolution (classify_path, resolve) |
| `ck3lens/capability_matrix.py` | Permissions (subfolders_writable) |
| `ck3lens/policy/enforcement.py` | Enforcement (matrix + invariants) |
| `ck3lens/paths_doctor.py` | **NEW** - Read-only diagnostics |

---

## 7. Migration Notes

### 7.1 Deleted Code

| What | Why |
|------|-----|
| `ROOTS` dict | Unnecessary indirection |
| `get_root()` function | Import constants directly |
| `get_wip_dir()` etc. | Use WIP_DIR constant |
| `resolve()` in paths.py | Moved to WorldAdapter |
| world_router.py | Detection logic moved to constants |
| INVARIANT 4 (.mod check) | subfolders_writable handles this |

### 7.2 Config File

`~/.ck3raven/config/workspace.toml` - auto-created, user fills in:
- `game_path` - CK3 install
- `workshop_path` - Steam workshop

---

## 8. Paths Doctor (Diagnostics)

### 8.1 Purpose

The Paths Doctor is a **read-only diagnostic utility** whose sole purpose is to:
- Validate configured and derived paths
- Detect misconfiguration early
- Provide actionable remediation guidance

It exists to surface configuration and environment problems, **not** to enforce policy, grant access, or modify system state.

### 8.2 Non-Negotiable Constraints

| Constraint | Requirement |
|------------|-------------|
| **Read-only** | MUST NOT create directories, write files, modify config, or mutate any path constants |
| **No enforcement** | MUST NOT perform allow/deny decisions, MUST NOT consult capability matrix for authorization |
| **Canonical sources only** | MUST read paths exclusively from: paths.py constants, loaded config, WorldAdapter resolution (cross-check only) |
| **No re-implementation** | MUST NOT re-implement path resolution. Classification checks MUST delegate to `WorldAdapter.resolve()` |
| **Deterministic output** | Given same config and filesystem state, report MUST be stable in content and ordering |

### 8.3 Module Placement and API

**File:** `ck3lens/paths_doctor.py`

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class DoctorFinding:
    id: str                 # stable identifier, e.g. PD-ROOT-GAME-MISSING
    severity: Literal["OK", "WARN", "ERROR"]
    subject: str            # e.g. ROOT_GAME, WIP_DIR, config
    message: str            # human-readable description
    remediation: str | None # concrete next step for the user

@dataclass(frozen=True)
class PathsDoctorReport:
    ok: bool                      # true iff no ERROR findings
    findings: tuple[DoctorFinding, ...]
    summary: dict[str, int]       # counts by severity
    config_path: str | None       # path to loaded config, if known

def run_paths_doctor(*, include_resolution_checks: bool = True) -> PathsDoctorReport:
    """Run all diagnostic checks and return report."""
    ...
```

**CLI Entry:**
```bash
python -m ck3lens.paths_doctor
```

### 8.4 What Paths Doctor Checks

#### 8.4.1 Root Presence and Validity

For each canonical root category:
- `ROOT_GAME` (required)
- `ROOT_STEAM` (required)
- `ROOT_USER_DOCS`
- `ROOT_UTILITIES`
- `ROOT_LAUNCHER`
- `ROOT_VSCODE`
- `ROOT_CK3RAVEN_DATA`
- `ROOT_REPO` (derived)

**Checks performed:**
| Condition | Severity |
|-----------|----------|
| Required root missing | ERROR |
| Configured root path does not exist | WARN (or ERROR if required) |
| Root exists but is wrong type (file vs directory) | ERROR |
| Obvious root overlap or nesting (e.g. GAME under REPO) | WARN or ERROR |

#### 8.4.2 CK3RAVEN_DATA Structure Sanity

Validate derived paths under `ROOT_CK3RAVEN_DATA`:
- `WIP_DIR`
- `PLAYSET_DIR`
- `LOGS_DIR`
- `CONFIG_DIR`
- `DB_PATH` (file)

| Condition | Severity |
|-----------|----------|
| Missing expected directories | WARN |
| `DB_PATH` exists but is a directory | ERROR |
| `DB_PATH` missing | WARN (daemon may not have created yet) |

#### 8.4.3 Local Mods Folder Validity

Validate `LOCAL_MODS_FOLDER`:

| Condition | Severity |
|-----------|----------|
| Not configured | WARN |
| Configured but missing | WARN |
| Exists but not a directory | ERROR |

#### 8.4.4 Config Provenance and Health

Report:
- Config source path (e.g. `~/.ck3raven/config/workspace.toml`)
- Parse errors → ERROR
- Missing required keys → ERROR
- Use of OS-default fallback values → WARN

#### 8.4.5 Optional Resolution Cross-Checks

When `include_resolution_checks=True`, run non-mutating classification checks via `WorldAdapter.resolve()` on representative paths:

| Path | Expected Classification |
|------|------------------------|
| `WIP_DIR / "doctor_probe.txt"` | ROOT_CK3RAVEN_DATA, subdir wip |
| `ROOT_REPO / <known file>` | ROOT_REPO |
| `LOCAL_MODS_FOLDER / <example>` | ROOT_USER_DOCS |
| An unrelated temp path | ROOT_EXTERNAL |

These checks detect regressions in resolution order or root constants.

### 8.5 Severity Semantics

| Severity | Meaning |
|----------|---------|
| **ERROR** | Misconfiguration that prevents correct operation; requires user action |
| **WARN** | Non-fatal issue or degraded capability; operation may continue |
| **OK** | Informational confirmation |

`report.ok` MUST be `False` if any ERROR findings are present.

### 8.6 Integration Expectations

**Paths Doctor MAY be run:**
- Manually via CLI
- Automatically at MCP server startup (logging summary only)
- Via an optional MCP tool (read-only reply)

**Paths Doctor MUST NOT:**
- Block startup automatically
- Write to logs or config beyond standard logging output
- Influence enforcement decisions

### 8.7 Explicitly Banned Behaviors

Paths Doctor MUST NOT:
- Create `~/.ck3raven/*` directories
- Write or modify config files
- Alter path constants or derived paths
- Consult the capability matrix to infer permissions
- Implement its own path resolution logic

---

## 9. References

- [CANONICAL_ARCHITECTURE.md](../CANONICAL_ARCHITECTURE.md)
- [SINGLE_WRITER_ARCHITECTURE.md](../SINGLE_WRITER_ARCHITECTURE.md)
