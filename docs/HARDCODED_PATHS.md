# Hardcoded Paths and Values

**Purpose**: Bare factual list of hardcoded paths, filenames, and lists in the codebase.  
**Use with**: `tools/arch_lint/arch_lint_v2_3.py` for banned concept detection.

---

## Hardcoded Path Patterns

### `tools/ck3lens-explorer/bridge/server.py`

| Line | Pattern |
|------|---------|
| 178 | `Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"` |
| 902 | `Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"` |
| 935 | `Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"` |
| 953 | `Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"` |
| 1126 | `Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"` |

### `tools/ck3lens_mcp/ck3lens/workspace.py`

No hardcoded paths remaining as of January 2026.

### `scripts/fix_docstring.py`

| Line | Pattern |
|------|---------|
| 6 | String literal `"MSC"` in example code |

---

## Legacy JSON Key References

### `tools/ck3lens-explorer/bridge/server.py`

| Line | Key |
|------|-----|
| 1140 | `playset_data.get("local_mods", [])` — reads legacy playset JSON format |

---

## Run Arch Lint

```powershell
cd C:\Users\Nathan\Documents\AI Workspace\ck3raven
$env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python.exe tools\arch_lint\arch_lint_v2_3.py
```

Excluding archive folder (deprecated code):
```powershell
.venv\Scripts\python.exe tools\arch_lint\arch_lint_v2_3.py src tools builder scripts
```
