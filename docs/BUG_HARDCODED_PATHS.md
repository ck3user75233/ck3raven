# Bug Report: Hardcoded Paths Prevent Multi-Machine Development

## Summary
The ck3raven codebase contains numerous hardcoded user-specific paths that cause failures when the repository is used on different machines or by different users.

## Observed Symptom
During agent initialization, two different `local_mods_folder` paths were observed:
- **nateb**: `C:\Users\nateb\Documents\Paradox Interactive\Crusader Kings III\mod`
- **Nathan**: `C:\Users\Nathan\Documents\Paradox Interactive\Crusader Kings III\mod`

### Source of Each Path

| Path | Source |
|------|--------|
| `nateb` path | Stored in old playset JSON file: `playsets/MSC Religion Expanded Dec20-updated_playset.json` (line 1132) |
| `Nathan` path | Dynamic fallback `DEFAULT_CK3_MOD_DIR` in `workspace.py` using `Path.home()` |

The `nateb` path appears because:
1. The playset JSON was created on one machine (user: nateb)
2. Committed to git and pulled to another machine (user: Nathan)
3. The `local_mods_folder` field in the JSON contains the absolute path from the original machine

---

## Comprehensive Audit of Hardcoded Paths

### Category 1: Hardcoded in Playset JSON Files (Committed to Git)

| File | Line | Hardcoded Value |
|------|------|-----------------|
| `playsets/MSC Religion Expanded Dec20-updated_playset.json` | 1064-1100, 1132 | `C:\Users\nateb\Documents\...\mod\*` |

**Problem**: Playset files contain machine-specific absolute paths for local mods.

---

### Category 2: Hardcoded Default Paths in Python Code

| File | Line | Hardcoded Value |
|------|------|-----------------|
| `ck3lens/workspace.py` | 163 | `DEFAULT_VANILLA_PATH = Path("C:/Program Files (x86)/Steam/...")` |
| `ck3lens/world_router.py` | 252-253 | Steam paths for vanilla discovery |
| `server.py` | 296 | Fallback vanilla path in `_load_playset_from_json()` |
| `server.py` | 3978 | `search_base` in `ck3_launcher()` |
| `bridge/server.py` | 224 | `vanilla_root=Path("C:/Program Files (x86)/Steam/...")` |
| `scripts/launcher_to_playset.py` | 21, 46 | Steam workshop and vanilla paths |
| `scripts/ck3_syntax_learner.py` | 1038 | Game path |

---

### Category 3: Archived but Still Present

| File | Line | Hardcoded Value |
|------|------|-----------------|
| `archive/old_builder/config.py` | 23-31 | vanilla_path, workshop_path, steam paths |
| `archive/deprecated_scripts/convert_launcher_playset.py` | 14-16 | AI_WORKSPACE, LOCAL_MOD_BASE, STEAM_BASE |

---

## Recommended Fixes

### 1. `local_mods_folder` Should Auto-Detect with Confirmation

**Current behavior**: Falls back to `Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"`

**Recommended approach**:
```python
def detect_local_mods_folder() -> Path:
    # Auto-detect local_mods_folder with cross-platform support.
    # Returns None if detection fails (user must configure manually).
    
    # Standard locations by platform
    if sys.platform == "win32":
        candidates = [
            Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod",
            Path(os.environ.get("USERPROFILE", "")) / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod",
        ]
    else:  # Linux/Mac
        candidates = [
            Path.home() / ".local/share/Paradox Interactive/Crusader Kings III/mod",
            Path.home() / "Documents/Paradox Interactive/Crusader Kings III/mod",  # Proton
        ]
    
    for path in candidates:
        if path.exists():
            return path
    
    return None  # User must configure
```

**On first run**, if `local_mods_folder` is not in config and auto-detection succeeds, prompt user:
```
Detected local mods folder: C:\Users\Nathan\Documents\Paradox Interactive\Crusader Kings III\mod
Save this to configuration? [Y/n]
```

---

### 2. Playset JSON Should Use Relative/Canonical Paths

**Current playset format** (problematic):
```json
{
  "local_mods_folder": "C:\\Users\\nateb\\Documents\\Paradox Interactive\\Crusader Kings III\\mod"
}
```

**Recommended format** (portable):
```json
{
  "local_mods_folder": "~/.ck3mods"
}
```

For mod paths in `mods[]`, use:
- **Workshop mods**: Steam ID only (path is derived from Steam install location)
- **Local mods**: Relative to `local_mods_folder` (e.g., `"path": "Mini Super Compatch"`)

---

### 3. Path Migration on Load

The existing `path_migration.py` module is good but needs to be **automatically invoked** when loading playsets:

```python
# In _apply_playset():
from .path_migration import migrate_playset_paths

def _apply_playset(session: Session, data: dict) -> None:
    # Auto-migrate paths before applying
    migrated_data, was_modified, message = migrate_playset_paths(data)
    if was_modified:
        _logger.info(f"Path migration: {message}")
        data = migrated_data
    # ... rest of function
```

---

### 4. Centralized Path Configuration

Create a single source of truth for configurable paths:

**File**: `~/.ck3raven/paths.json`
```json
{
  "local_mods_folder": "C:/Users/Nathan/Documents/Paradox Interactive/Crusader Kings III/mod",
  "vanilla_game": "C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game",
  "steam_workshop": "C:/Program Files (x86)/Steam/steamapps/workshop/content/1158310",
  "auto_detected": true,
  "last_verified": "2026-01-13T12:00:00Z"
}
```

**Benefits**:
- Single file to edit when moving machines
- Auto-detection can populate on first run
- Playset JSONs can omit these paths entirely

---

### 5. Remove Hardcoded Fallbacks from Code

Replace all hardcoded paths with calls to a central path resolver:

```python
# Before (scattered throughout codebase):
DEFAULT_VANILLA_PATH = Path("C:/Program Files (x86)/Steam/...")

# After:
from ck3lens.paths import get_vanilla_path
vanilla_path = get_vanilla_path()  # Reads from config or auto-detects
```

---

## Files Requiring Changes

### Priority 1 (Active Code):
1. `tools/ck3lens_mcp/ck3lens/workspace.py` - Line 163: Remove hardcoded DEFAULT_VANILLA_PATH
2. `tools/ck3lens_mcp/server.py` - Lines 296, 3978: Replace hardcoded fallbacks
3. `tools/ck3lens_mcp/ck3lens/world_router.py` - Lines 252-253: Use path resolver
4. `tools/ck3lens-explorer/bridge/server.py` - Line 224: Use path resolver

### Priority 2 (Scripts):
5. `scripts/launcher_to_playset.py` - Lines 21, 46: Add CLI args or config
6. `scripts/ck3_syntax_learner.py` - Line 1038: Add CLI args

### Priority 3 (Cleanup):
7. `playsets/MSC Religion Expanded Dec20-updated_playset.json` - Migrate or delete
8. Archive files - No action needed (already deprecated)

---

## Implementation Plan

1. **Phase 1**: Create `ck3lens/paths.py` with auto-detection and config loading
2. **Phase 2**: Update `workspace.py` to use path resolver
3. **Phase 3**: Update remaining files to use path resolver
4. **Phase 4**: Add path validation on startup (warn if paths don't exist)
5. **Phase 5**: Auto-invoke path migration when loading playsets

---

## Environment Context

- **Development machines**: At least 2 (nateb, Nathan)
- **Current workaround**: `path_migration.py` exists but is not auto-invoked
- **Risk**: Users pulling repo get broken playsets and confusing errors
