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
