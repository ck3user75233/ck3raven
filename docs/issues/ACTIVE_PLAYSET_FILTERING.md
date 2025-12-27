# Active Playset Filtering - Requirements & Task

**Created:** December 26, 2025  
**Status:** PENDING (blocked by ck3_exec hang)  
**Priority:** HIGH - Core to ck3lens agent safety

---

## Background

The active playset represents the scope of:
- Error log analysis
- Conflict analysis  
- Compatching
- Any mod editing

**Critical Safety Issue:** ck3lens agent previously could see ALL mods in `/mod/` folder and nearly damaged mods that weren't in the active playset by trying to "fix" errors that appeared in logs.

---

## Requirements

### Core Principle
> At NO point in time should ck3lens ever see, touch, or query mods that are NOT IN THE ACTIVE PLAYSET.

### Scope
- All MCP tools used by ck3lens must filter to active playset
- Like a virtual file system - only playset mods are visible
- When playset changes, all queries/tools automatically filter to new scope
- Only LOCAL mods IN THE ACTIVE PLAYSET can be edited (not all local mods)

### Mod Categories
1. **Steam Workshop Mods** - Read-only, in playset = visible
2. **Local Mods** - In playset = visible AND editable
3. **Mods NOT in playset** - INVISIBLE to agent

---

## Task: Audit MCP Tools

Create a table with columns:
1. Tool name
2. Current playset filtering status:
   - `none` - No filtering available
   - `optional` - Has filter param but not default
   - `default` - Filters by default
   - `required` - Cannot be disabled
3. Required filtering level:
   - `none` - Doesn't need filtering (e.g., ping, config)
   - `optional` - Useful but not critical
   - `default` - Should filter by default
   - `required` - Must always filter, no bypass

### Tools to Audit (ck3lens mode)
From MCP server, the tools prefixed with `ck3_`:
- ck3_search
- ck3_file (get/read/write/edit/delete)
- ck3_folder
- ck3_logs
- ck3_conflicts
- ck3_get_symbol_conflicts
- ck3_qr_conflicts
- ck3_db_query
- ck3_validate
- ck3_parse_content
- ck3_get_completions
- ck3_get_hover
- ck3_get_definition
- ck3_playset
- ck3_git
- ck3_list_local_mods
- ck3_create_override_patch
- ck3_get_scope_info
- ck3_get_db_status
- ck3_get_agent_briefing
- etc.

---

## Architecture Considerations

Design should:
1. **Be modular** - Filter logic in one place, not scattered
2. **Survive upstream changes** - Playset loading/storage could change
3. **Survive downstream changes** - Tool implementations could change
4. **Single source of truth** - One place defines "what's in scope"

### Possible Approaches

1. **Query-level filtering** - All DB queries auto-filter by content_version_id
2. **Lens context object** - Pass lens scope to all tool functions
3. **Database view** - Create filtered views based on active playset
4. **Middleware pattern** - Intercept tool calls and inject filter

---

## Deliverables

1. Complete tool audit table
2. Architecture recommendation
3. Implementation plan with phases

---

## Architecture Analysis (December 27, 2025)

### Current State: Two Conflicting Implementations

**1. File-Based (Intended Design):**
- `PLAYSETS_DIR = Path(...) / "playsets"` - expects a `playsets/` folder ✅ EXISTS
- `playset.schema.json` - full schema with mods, load_order, agent_briefing ✅ EXISTS
- `example_playset.json` - template playset ✅ EXISTS
- `playset_manifest.json` - pointer to active playset ✅ EXISTS

**2. Database-Based (Deprecated - Should Be Expunged):**
- `playsets` table in database schema
- `playset_mods` table linking to `content_version_id`s
- `db.get_active_lens()` queries `WHERE is_active = 1` - returns None because table is empty
- `src/ck3raven/db/playsets.py` - 464 lines of database-based playset management

### The PlaysetLens Class

```python
@dataclass
class PlaysetLens:
    playset_id: int
    playset_name: str
    vanilla_cv_id: int           # content_version_id for vanilla
    mod_cv_ids: list[int]        # content_version_ids for mods in load order
    
    @property
    def all_cv_ids(self) -> Set[int]:
        """All content_version_ids visible through this lens."""
        return {self.vanilla_cv_id} | set(self.mod_cv_ids)
    
    def get_file_ids_sql(self, conn) -> str:
        """Return SQL subquery for valid file_ids."""
        cv_list = ",".join(str(cv) for cv in self.all_cv_ids)
        return f"SELECT file_id FROM files WHERE content_version_id IN ({cv_list})"
```

**The lens is just an array of `content_version_id`s.** It's used to filter all queries.

### How It's Used in db_queries.py

Every query method takes an optional `lens: PlaysetLens` parameter. When a lens is provided, queries are filtered:

```python
def search_symbols(self, lens: Optional[PlaysetLens], query: str, ...):
    # ...
    if lens:
        # Filter to only files in the playset
        cv_ids = ",".join(str(cv) for cv in lens.all_cv_ids)
        base_sql += f" AND f.content_version_id IN ({cv_ids})"
```

### How It's Called from server.py

```python
def _get_lens(no_lens: bool = False):
    """Get the active playset lens for filtering queries."""
    if no_lens:
        return None
    
    db = _get_db()
    return db.get_active_lens()  # <-- THIS IS THE PROBLEM
```

The `_get_lens()` function is called by many MCP tools:
- `ck3_search` → calls `_get_lens()` → passes to `db.search_symbols(lens, ...)`
- `ck3_file(command="get")` → calls `_get_lens()` → passes to `db.get_file(lens, ...)`
- etc.

### The Problem

Currently `db.get_active_lens()` queries the **database** for a playset marked `is_active = 1`:

```python
def get_active_lens(self) -> Optional[PlaysetLens]:
    """Get the lens for the currently active playset."""
    row = self.conn.execute("""
        SELECT playset_id FROM playsets WHERE is_active = 1 LIMIT 1
    """).fetchone()
    
    if row:
        return self.get_lens(row["playset_id"])
    return None
```

But:
1. The database `playsets` table is empty
2. The design intent is file-based playsets in `/playsets/` folder
3. No one is loading the playset JSON files and creating a lens from them

---

## Next Steps

### Step 1: Implement File-Based Lens Loader

**Replace `db.get_active_lens()`** with a function that:

1. Reads the active playset pointer (e.g., `playset_manifest.json` or `~/.ck3raven/active_playset.json`)
2. Loads the playset JSON file from `/playsets/`
3. Resolves mod paths to `content_version_id`s using the database
4. Returns a `PlaysetLens` with those `content_version_id`s

The rest of the architecture is already correct - all query methods accept a `lens` parameter and filter appropriately.

### Step 2: Deprecate Database Playset Tables

- Mark `src/ck3raven/db/playsets.py` as deprecated
- If possible without breaking the database, remove `playsets` and `playset_mods` tables from schema
- If removal would require rebuild, leave tables but ensure nothing writes to them

### Step 3: Tool Audit

Complete the tool audit table to verify all MCP tools correctly use the lens.
