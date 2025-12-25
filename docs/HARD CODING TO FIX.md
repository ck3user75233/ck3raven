# Hardcoded Mod Names To Fix

This document tracks all instances of hardcoded mod names/paths in the ck3raven codebase that should be moved to a centralized config file.

## Target: Single Source of Truth

All hardcoded mod references should read from:
```
C:\Users\Nathan\Documents\AI Workspace\ck3lens_config.yaml
```

---

## 1. `tools/ck3lens-explorer/bridge/server.py`

### Location 1: `list_live_mods()` function (Lines ~893-899)

```python
live_mods_config = {
    "MSC": ("Mini Super Compatch", "Mini Super Compatch"),
    "MSCRE": ("MSC Religion Expanded", "MSCRE"),
    "LRE": ("Lowborn Rise Expanded", "Lowborn Rise Expanded"),
}
```

**Purpose**: Python MCP bridge server that provides live mod file operations to VS Code extension.

**Why Hardcoded**: Legacy development - has TODO comment to move to config.

**Fix**: Import from `ck3lens_config.yaml` or share with `workspace.py`.

---

### Location 2: `create_override_patch()` function (Lines ~1143-1150)

```python
mod_paths = {
    "MSC": mod_root / "Mini Super Compatch",
    "MSCRE": mod_root / "MSCRE",
    "LRE": mod_root / "Lowborn Rise Expanded",
    "MRP": mod_root / "More Raid and Prisoners",
}
```

**Purpose**: Quick ID-to-folder mapping for creating patch files in live mods.

**Why Hardcoded**: Convenience for short IDs; has fallback to try direct folder name.

**Fix**: Should use same config as `list_live_mods()`.

---

## 2. `tools/ck3lens_mcp/ck3lens/workspace.py`

### Location: `DEFAULT_LIVE_MODS` constant (Lines ~70-94)

```python
DEFAULT_LIVE_MODS = [
    LiveMod(mod_id="MSC", name="Mini Super Compatch", path=DEFAULT_CK3_MOD_DIR / "Mini Super Compatch"),
    LiveMod(mod_id="MSCRE", name="MSC Religion Expanded", path=DEFAULT_CK3_MOD_DIR / "MSCRE"),
    LiveMod(mod_id="LRE", name="Lowborn Rise Expanded", path=DEFAULT_CK3_MOD_DIR / "Lowborn Rise Expanded"),
    LiveMod(mod_id="MRP", name="More Raid and Prisoners", path=DEFAULT_CK3_MOD_DIR / "More Raid and Prisoners"),
]
```

**Purpose**: Fallback defaults when `ck3lens_config.yaml` is missing.

**Why Hardcoded**: Library needs to work standalone without config file.

**Status**: ✅ Already reads from config via `load_config()` - these are just fallback defaults.

**Fix**: Consider removing defaults entirely and requiring config file, OR make defaults empty.

---

## 3. `scripts/convert_launcher_playset.py`

### Location: `LOCAL_MODS` list (Lines ~20-26)

```python
LOCAL_MODS = [
    ("Lowborn Rise Expanded", "Lowborn Rise Expanded"),
    ("More Raid and Prisoners", "More Raid and Prisoners"),
    ("Mini Super Compatch", "Mini Super Compatch"),
    ("MSC Religion Expanded", "MSCRE"),
    ("VanillaPatch", "VanillaPatch"),
]
```

**Purpose**: One-time utility script to convert CK3 Launcher JSON to active_mod_paths.json. Appends local mods after Steam mods.

**Why Hardcoded**: User-specific script, not meant to be general-purpose.

**Fix**: Could read from `ck3lens_config.yaml` live_mods section.

---

## 4. `tools/ck3lens-explorer/README.md`

### Location: Example configuration (Line ~131)

```json
"ck3lens.liveMods": ["Mini Super Compatch", "MSC Religion Expanded", "Lowborn Rise Expanded"]
```

**Purpose**: Documentation example showing users what config looks like.

**Why Hardcoded**: It's documentation, not code.

**Fix**: None needed - this is just an example.

---

## Summary Table

| File | Location | Status | Priority |
|------|----------|--------|----------|
| `bridge/server.py` | `list_live_mods()` | ⚠️ Hardcoded | HIGH |
| `bridge/server.py` | `create_override_patch()` | ⚠️ Hardcoded | HIGH |
| `workspace.py` | `DEFAULT_LIVE_MODS` | ✅ Has config loading | LOW |
| `convert_launcher_playset.py` | `LOCAL_MODS` | ⚠️ Hardcoded | MEDIUM |
| `README.md` | Example | ✅ Documentation only | NONE |

---

## Proposed Solution

1. **`server.py`** should import the `load_config()` function from `workspace.py` or directly read `ck3lens_config.yaml`

2. **Single config file** at `~/Documents/AI Workspace/ck3lens_config.yaml` should be the only place mod names are defined

3. **Fallback behavior**: If config missing, show error asking user to create it rather than using hardcoded defaults

---

## Config File Format Reference

```yaml
# ck3lens_config.yaml
db_path: "~/.ck3raven/ck3raven.db"
local_mods_path: "~/Documents/Paradox Interactive/Crusader Kings III/mod"

live_mods:
  - mod_id: MSC
    name: Mini Super Compatch
    path: ~/Documents/Paradox Interactive/Crusader Kings III/mod/Mini Super Compatch
  - mod_id: MSCRE
    name: MSC Religion Expanded
    path: ~/Documents/Paradox Interactive/Crusader Kings III/mod/MSCRE
  - mod_id: LRE
    name: Lowborn Rise Expanded
    path: ~/Documents/Paradox Interactive/Crusader Kings III/mod/Lowborn Rise Expanded
```
