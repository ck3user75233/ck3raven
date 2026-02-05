# Paths Refactor - Outstanding TODOs

> **Date:** February 4, 2026  
> **Status:** In Progress

---

## Completed This Session

1. ✅ **paths.py rewritten** - Constants loaded at module import, no detection functions
2. ✅ **ROOT_REPO** - Now `Path(__file__).parent.parent.parent.parent` (not walking up looking for pyproject.toml)
3. ✅ **config_loader.py** - Already existed, now wired up to paths.py
4. ✅ **world_router.py** - Removed `_detect_ck3raven_root()`, `_get_vanilla_root()`, `_get_utility_roots()` - uses constants
5. ✅ **mcpServerProvider.ts** - Removed `findCk3RavenRoot()` - uses `path.resolve(__dirname, '..', '..', '..', '..')`
6. ✅ **9 root categories** verified in paths.py, capability_matrix.py, enforcement.py
7. ✅ **INVARIANT 4** added - `.mod` registry files in `mod/` folder are read-only

---

## Outstanding TODOs

### HIGH PRIORITY

#### 1. Config File Not Created Yet
- `~/.ck3raven/config/` directory doesn't exist
- `workspace.toml` will be auto-created on first import of paths.py
- User needs to fill in `game_path` and `workshop_path` for their Steam install

#### 2. Express .mod File Restriction in Capability Matrix
**Current:** Linear check in enforcement.py (INVARIANT 4):
```python
if path_str.endswith(".mod"):
    return DENY
```

**Better:** Express in capability matrix. Options to explore:
- Add file extension patterns to matrix keys: `(mode, root, subdir, pattern)`
- Add a `file_filter` field to Capability dataclass
- Use subdirectory depth (files directly in `mod/` vs files in `mod/*/`)

**Rationale:** Matrix should be THE sole enforcement driver. Linear checks are harder to audit.

### MEDIUM PRIORITY

#### 3. WorldAdapter Needs Resolve Function
- Removed `resolve()` from paths.py (WorldAdapter's job)
- WorldAdapter needs to implement resolution using `paths.ROOTS` registry
- Resolution = "is path X inside ROOT_Y?" → returns `ResolvedPath`

#### 4. Test MCP Server Startup
- Changes to paths.py, enforcement.py may have broken imports
- Need to test: `python -m tools.ck3lens_mcp.server`
- Error seen earlier: `OperationType has no attribute 'DB_WRITE'` (may be stale)

#### 5. doctor.ts Uses Config Setting for repoRoot
- Currently: `const repoRoot = ck3ravenPath || workspaceRoot`
- This is for diagnostics (showing what's configured) - may be fine
- Consider: Should doctor.ts also use the constant pattern?

### LOW PRIORITY

#### 6. Delete world_router.py Eventually
- Currently marked DEPRECATED
- Once all call sites use paths.py constants, delete it

#### 7. Cleanup Unused Code
- `_get_utility_roots()` deleted but may have been used elsewhere
- Search for orphaned imports

---

## Design Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| ROOT_REPO computation | `Path(__file__).parent...` | Extension knows where it is |
| ROOT_CK3RAVEN_DATA | Always `~/.ck3raven` | Not platform-dependent |
| Configurable roots | From `workspace.toml` | User fills in their paths |
| .mod files | Read-only via enforcement.py invariant | Launcher registry protection |
| local_mods_folder | Not a root, derived from ROOT_USER_DOCS/mod | Can be overridden in config |

---

## Files Changed This Session

| File | Change |
|------|--------|
| `tools/ck3lens_mcp/ck3lens/paths.py` | Rewritten - constants at module load |
| `tools/ck3lens_mcp/ck3lens/world_router.py` | Removed detection functions, uses constants |
| `tools/ck3lens_mcp/ck3lens/policy/enforcement.py` | Added INVARIANT 4 (.mod read-only) |
| `tools/ck3lens-explorer/src/mcp/mcpServerProvider.ts` | Removed findCk3RavenRoot(), uses constant |
