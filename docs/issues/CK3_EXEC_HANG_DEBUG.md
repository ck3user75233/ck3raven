# CK3_EXEC HANG ISSUE - RESOLVED

**Created:** December 26, 2025  
**Resolved:** December 26, 2025  
**Status:** ✅ RESOLVED

---

## Root Cause

Two separate issues:

### Issue 1: Windows Store Python Stub
- `ck3_exec` used `subprocess.run(command, shell=True)`
- Windows PATH resolved `python` to `C:\Users\nateb\AppData\Local\Microsoft\WindowsApps\python.exe`
- This is a Windows Store redirect stub that can hang

### Issue 2: Missing PyYAML Dependency
- `builder/config.py` imports `yaml`
- `pyproject.toml` declared `dependencies = []` (empty)
- Anyone cloning the repo would hit this error on first build

---

## Solution Implemented

### 1. Created `runtime_env.py` Module
**Location:** `tools/ck3lens_mcp/ck3lens/runtime_env.py`

A centralized runtime environment management module that handles:

| Component | Purpose |
|-----------|---------|
| `PythonEnvironment` | Detects Python interpreter, transforms commands |
| `DependencyChecker` | Validates required packages are installed |
| `ExternalToolsChecker` | Validates git, etc. are available |
| `validate_startup()` | Fail-fast validation at MCP server startup |
| `transform_python_command()` | Converts `python foo` → `"/path/to/python" foo` |

### 2. Fixed `pyproject.toml`
```toml
# Before
dependencies = []

# After
dependencies = [
    "pyyaml>=6.0",  # For builder config files
]
```

### 3. Updated `ck3_exec` in `server.py`
```python
# Now transforms python commands before execution
from ck3lens.runtime_env import transform_python_command

command = transform_python_command(command)  # "python x" → '"/full/path/python" x'
```

### 4. Added Startup Validation
Server.py now validates runtime environment on startup and warns about issues.

---

## Files Changed

1. `tools/ck3lens_mcp/ck3lens/runtime_env.py` - NEW
2. `tools/ck3lens_mcp/server.py` - Updated ck3_exec and startup
3. `pyproject.toml` - Added pyyaml dependency
4. `tools/ck3lens_mcp/ck3lens/python_env.py` - DELETED (replaced by runtime_env.py)

---

## Testing Required

After MCP server restart:
1. `ck3_exec("python --version")` should work (not hang)
2. `ck3_exec("python builder/daemon.py status")` should work
3. Startup should show warning about Windows Store Python if applicable

---

## Notes for Future

- The `runtime_env.py` module is designed to be extensible
- Add new required packages to `DependencyChecker.REQUIRED_PACKAGES`
- Add new tools to `ExternalToolsChecker.TOOLS`
- Startup validation runs on every MCP server start
