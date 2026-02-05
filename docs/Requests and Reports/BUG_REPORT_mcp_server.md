# Bug Report: MCP Server Fails to Start

**Date**: 2026-02-04  
**Status**: BLOCKING  
**Component**: `tools/ck3lens_mcp/`

---

## Issue 1: TokenTier ImportError (BLOCKING)

### Error
```
ImportError: cannot import name 'TokenTier' from 'ck3lens.policy.enforcement'
```

### Stack Trace
```
python -m tools.ck3lens_mcp.server
  → tools/ck3lens_mcp/server.py (line 30)
    → from ck3lens.policy.contract_v1 import ...
      → ck3lens/policy/__init__.py (line 84)
        → from .enforcement import TokenTier, ...
          → ImportError: cannot import name 'TokenTier'
```

### Root Cause
Token system was deprecated (only 2 canonical tokens remain: NST, LXE per `ck3_token` docstring), but `ck3lens/policy/__init__.py` still imports the removed `TokenTier` class from `enforcement.py`.

### Fix
Edit `tools/ck3lens_mcp/ck3lens/policy/__init__.py` around line 84:

```python
# BEFORE (broken)
from .enforcement import (
    TokenTier,  # ← REMOVE THIS
    ...
)

# AFTER (fixed)
from .enforcement import (
    # TokenTier removed - deprecated
    ...
)
```

### Find All References
```powershell
Select-String -Path "c:\Users\nateb\Documents\CK3 Mod Project 1.18\ck3raven\tools\ck3lens_mcp\**\*.py" -Pattern "TokenTier" -Recurse
```

### Verification
```powershell
& "c:\Users\nateb\Documents\CK3 Mod Project 1.18\ck3raven\.venv\Scripts\python.exe" -c "from ck3lens.policy import *; print('OK')"
```

---

## Issue 2: Non-Canonical Path Resolution (Low Priority)

**File**: `tools/ck3lens-explorer/src/mcp/mcpServerProvider.ts`  
**Severity**: Low (architectural drift, not blocking)

### Problem
`findCk3RavenRoot()` (lines 79-137) uses ad-hoc heuristics instead of canonical domain pattern:

```typescript
// Current: 4 priority levels, 6+ path strategies
function findCk3RavenRoot(logger: Logger): string | undefined {
    // Priority 1: Extension configuration
    // Priority 2: Search workspace folders (3 sub-strategies)
    // Priority 3: Check relative to extension path
    // Priority 4: Check for development extension path
}
```

### Issues
1. `ck3ravenRoot` is not a canonical domain name (should be `ROOT_REPO`)
2. Parent traversal (`path.dirname(path.dirname(...))`) is fragile
3. String matching (`includes('ck3lens-explorer')`) is brittle
4. No alignment with Python-side `WorldAdapter` pattern

### Recommended Fix (When Refactoring)
Align with canonical domains from `PATHS_DESIGN_GUIDELINES.md`:

```typescript
// Simplified - use canonical domain resolver
const repoRoot = resolveDomain(DomainRoot.ROOT_REPO, this.logger);
const pythonExe = resolveDomain(DomainRoot.ROOT_VENV, this.logger);
```

---

## Issue 3: PYTHONPATH May Be Incomplete

### Current (line 229)
```typescript
PYTHONPATH: `${ck3ravenRoot}${path.delimiter}${path.join(ck3ravenRoot, 'src')}`,
```

### Problem
Module import uses `-m tools.ck3lens_mcp.server` which requires `tools` on path. Currently works because `ck3ravenRoot` contains `tools/`, but intent is unclear.

### Recommended Fix
Make explicit:
```typescript
PYTHONPATH: `${ck3ravenRoot}${path.delimiter}${path.join(ck3ravenRoot, 'src')}${path.delimiter}${path.join(ck3ravenRoot, 'tools', 'ck3lens_mcp')}`,
```

---

## Issue 4: Missing __init__.py Validation

### Current (lines 220-223)
```typescript
const serverPath = path.join(ck3ravenRoot, 'tools', 'ck3lens_mcp', 'server.py');
if (!fs.existsSync(serverPath)) { ... }
```

### Problem
Only checks `server.py`, not `__init__.py` files required for `-m` module imports.

### Verification
```powershell
Test-Path "c:\Users\nateb\Documents\CK3 Mod Project 1.18\ck3raven\tools\__init__.py"
Test-Path "c:\Users\nateb\Documents\CK3 Mod Project 1.18\ck3raven\tools\ck3lens_mcp\__init__.py"
```

If `tools/__init__.py` is missing, create it:
```powershell
New-Item "c:\Users\nateb\Documents\CK3 Mod Project 1.18\ck3raven\tools\__init__.py" -ItemType File
```

---

## Action Items

| Priority | Issue | Action |
|----------|-------|--------|
| **P0** | TokenTier ImportError | Remove `TokenTier` from `__init__.py` imports |
| P2 | Missing `__init__.py` | Verify `tools/__init__.py` exists |
| P3 | PYTHONPATH | Consider adding `tools/ck3lens_mcp` explicitly |
| P4 | Canonical domains | Align with `WorldAdapter` pattern when refactoring |

---

## Related Commits
- `c54456c` - "Clean up git enforcement: remove dead token patterns"
- `e7a8fd1` - "add canonical domain roots (ROOT_WIP, ROOT_VSCODE, ROOT_OTHER)"
- `198d4e8` - "add PATHS_DESIGN_GUIDELINES.md"

## Related Documentation
- `docs/PATHS_DESIGN_GUIDELINES.md`
- `docs/MCP_SERVER_ARCHITECTURE.md`
- `ck3_token` tool docstring (documents token deprecation)
