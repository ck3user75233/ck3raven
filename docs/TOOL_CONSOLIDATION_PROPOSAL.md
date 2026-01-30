# MCP Tool Consolidation Proposal

> **Status:** DRAFT - Pending approval  
> **Created:** January 28, 2026  
> **Author:** Agent (via user request)

---

## Executive Summary

This proposal outlines a consolidation of the current 30 MCP tools into a more manageable and intuitive set. The goals are:

1. **Reduce cognitive load** - Fewer tools to remember
2. **Consistent API patterns** - All tools use `command` parameter for operations
3. **Remove deprecated tools** - Clean up legacy code
4. **Better naming** - Names that clearly describe purpose

---

## Current Tool Inventory (30 tools)

| # | Tool Name | Line | Category | Proposal |
|---|-----------|------|----------|----------|
| 1 | `ck3_get_instance_info` | 495 | Status | Merge → `ck3_status` |
| 2 | `ck3_ping` | 522 | Status | Merge → `ck3_status` |
| 3 | `ck3_close_db` | 721 | Database | Merge → `ck3_db` |
| 4 | `ck3_db` | 782 | Database | Keep (expand) |
| 5 | `ck3_db_delete` | 855 | Database | Merge → `ck3_db` |
| 6 | `ck3_get_policy_status` | 1260 | Status | Merge → `ck3_status` |
| 7 | `ck3_logs` | 1304 | Logs | Keep |
| 8 | `ck3_conflicts` | 1399 | Resolver | Rename → `ck3_resolver` |
| 9 | `ck3_file` | 1630 | Files | Keep |
| 10 | `ck3_folder` | 1744 | Files | Keep |
| 11 | `ck3_playset` | 1818 | Playset | Keep |
| 12 | `ck3_git` | 2354 | Git | Keep |
| 13 | `ck3_validate` | 2425 | Validation | Rename → `ck3_script` |
| 14 | `ck3_vscode` | 2487 | IDE | Keep |
| 15 | `ck3_repair` | 2543 | Repair | Keep |
| 16 | `ck3_contract` | 2938 | Contracts | Keep |
| 17 | `ck3_exec` | 3364 | Shell | Keep |
| 18 | `ck3_token` | 3640 | Tokens | **REMOVE** (deprecated) |
| 19 | `ck3_search` | 3687 | Search | Keep (expand) |
| 20 | `ck3_grep_raw` | 3840 | Search | Keep (specialized) |
| 21 | `ck3_file_search` | 3953 | Search | Merge → `ck3_search` |
| 22 | `ck3_parse_content` | 4062 | Parsing | Keep |
| 23 | `ck3_report_validation_issue` | 4133 | Issues | Keep |
| 24 | `ck3_get_agent_briefing` | 4216 | Status | Merge → `ck3_status` |
| 25 | `ck3_search_mods` | 4268 | Search | Merge → `ck3_search` |
| 26 | `ck3_get_mode_instructions` | 4360 | Init | Keep (critical) |
| 27 | `ck3_get_detected_mode` | 4621 | Status | Merge → `ck3_status` |
| 28 | `ck3_get_workspace_config` | 4699 | Status | Merge → `ck3_status` |
| 29 | `ck3_db_query` | 4870 | Database | Merge → `ck3_db` |
| 30 | `ck3_qbuilder` | 5027 | Builder | Keep |

---

## Proposed Consolidations

### 1. `ck3_status` - Unified Status Tool

**Consolidates:** `ck3_get_instance_info`, `ck3_ping`, `ck3_get_policy_status`, `ck3_get_agent_briefing`, `ck3_get_detected_mode`, `ck3_get_workspace_config`

**Rationale:** All these tools return read-only status information about the MCP server, session, or configuration. Consolidating them reduces the tool count by 5.

```python
def ck3_status(
    command: Literal["ping", "instance", "policy", "briefing", "mode", "config", "all"] = "all"
) -> Reply:
    """
    Get system status and configuration information.
    
    Commands:
        ping     → Simple health check (was ck3_ping)
        instance → Server instance info (was ck3_get_instance_info)
        policy   → Policy enforcement status (was ck3_get_policy_status)
        briefing → Agent briefing notes (was ck3_get_agent_briefing)
        mode     → Detected agent mode (was ck3_get_detected_mode)
        config   → Workspace configuration (was ck3_get_workspace_config)
        all      → Combined status summary
    """
```

---

### 2. `ck3_db` - Unified Database Tool

**Consolidates:** `ck3_db` (existing), `ck3_close_db`, `ck3_db_delete`, `ck3_db_query`

**Rationale:** All database operations belong in one tool. The existing `ck3_db` already has a `command` parameter; we just add more commands.

```python
def ck3_db(
    command: Literal["status", "enable", "disable", "close", "delete", "query"] = "status",
    # ... existing params ...
    # For query:
    table: str | None = None,
    sql: str | None = None,
    filters: dict | None = None,
    # For delete:
    target: str | None = None,
    scope: str | None = None,
    confirm: bool = False,
) -> Reply:
    """
    Database operations.
    
    Commands:
        status  → Check database connection status
        enable  → Enable database access
        disable → Disable database access  
        close   → Close database connection (was ck3_close_db)
        delete  → Delete indexed data (was ck3_db_delete)
        query   → Run database queries (was ck3_db_query)
    """
```

---

### 3. `ck3_resolver` - Rename from `ck3_conflicts`

**Rationale:** User requested rename. The tool will eventually house game state emulation, not just conflict detection. "Resolver" better captures the broader purpose.

```python
def ck3_resolver(
    command: Literal["symbols", "files", "summary", "emulate"] = "symbols",
    # ... existing params ...
) -> dict:
    """
    Conflict resolution and game state emulation.
    
    Commands:
        symbols  → Find symbols defined by multiple mods (was default)
        files    → Find files that multiple mods override
        summary  → Get conflict statistics
        emulate  → (Future) Emulate resolved game state
    """
```

---

### 4. `ck3_script` - Rename from `ck3_validate`

**Rationale:** User noted confusion with contract validation. "Script" or "syntax" better describes validating CK3 script files.

Alternative names considered:
- `ck3_syntax_check` - More explicit but verbose
- `ck3_script` - Short, indicates it's about CK3 scripts

```python
def ck3_script(
    target: Literal["syntax", "python", "references", "bundle", "policy"] = "syntax",
    # ... existing params ...
) -> dict:
    """
    Validate CK3 scripts and code.
    
    Targets:
        syntax     → Validate CK3 script syntax
        python     → Check Python syntax
        references → Validate symbol references exist
        bundle     → Validate artifact bundle
        policy     → Validate against policy rules
    """
```

---

### 5. `ck3_search` - Expanded to Include File Search

**Consolidates:** `ck3_search` (existing), `ck3_file_search`, `ck3_search_mods`

**Rationale:** All search operations belong in one tool. The tool can be mode-aware:
- In `ck3lens` mode: Default to `mod_name` + `rel_path` addressing
- In `ck3raven-dev` mode: Default to raw `path` addressing

```python
def ck3_search(
    query: str,
    # Existing params:
    file_pattern: str | None = None,
    game_folder: str | None = None,
    symbol_type: str | None = None,
    # New command for different search types:
    search_type: Literal["unified", "files", "mods"] = "unified",
    # For file search (was ck3_file_search):
    pattern: str | None = None,
    base_path: str | None = None,
    # For mod search (was ck3_search_mods):
    search_by: Literal["name", "workshop_id", "any"] = "any",
    fuzzy: bool = True,
    # ...
) -> dict:
    """
    Unified search across symbols, content, files, and mods.
    
    Search types:
        unified → Full search across symbols, content, and files (default)
        files   → Search for files by glob pattern (was ck3_file_search)
        mods    → Search for mods by name or workshop ID (was ck3_search_mods)
    """
```

---

### 6. REMOVE `ck3_token` (Deprecated)

**Rationale:** The token system has been deprecated. Only NST (New Symbol Token) and LXE (Lint Exception) remain, and these are managed internally by `ck3_contract` operations. No MCP tool currently interacts with NST/LXE directly.

**Migration path:**
1. Remove the tool entirely
2. Any agent needing tokens uses `ck3_contract` with appropriate work_declaration
3. Document in Reply System that tokens are deprecated

---

## Proposed Tool List After Consolidation

**From 30 tools to 22 tools (8 removed/merged):**

| # | Tool Name | Purpose |
|---|-----------|---------|
| 1 | `ck3_status` | **NEW** - Unified status/info (was 6 tools) |
| 2 | `ck3_db` | **EXPANDED** - Database operations (absorbed 3 tools) |
| 3 | `ck3_resolver` | **RENAMED** - Conflict resolution (was ck3_conflicts) |
| 4 | `ck3_script` | **RENAMED** - Script validation (was ck3_validate) |
| 5 | `ck3_search` | **EXPANDED** - Unified search (absorbed 2 tools) |
| 6 | `ck3_get_mode_instructions` | Initialization - KEEP AS-IS |
| 7 | `ck3_logs` | Log analysis - KEEP AS-IS |
| 8 | `ck3_file` | File operations - KEEP AS-IS |
| 9 | `ck3_folder` | Folder operations - KEEP AS-IS |
| 10 | `ck3_playset` | Playset management - KEEP AS-IS |
| 11 | `ck3_git` | Git operations - KEEP AS-IS |
| 12 | `ck3_vscode` | VS Code IPC - KEEP AS-IS |
| 13 | `ck3_repair` | Launcher repair - KEEP AS-IS |
| 14 | `ck3_contract` | Contract management - KEEP AS-IS |
| 15 | `ck3_exec` | Shell execution - KEEP AS-IS |
| 16 | `ck3_grep_raw` | Raw grep search - KEEP AS-IS |
| 17 | `ck3_parse_content` | AST parsing - KEEP AS-IS |
| 18 | `ck3_report_validation_issue` | Issue reporting - KEEP AS-IS |
| 19 | `ck3_qbuilder` | Build system - KEEP AS-IS |

**Removed:**
- `ck3_token` (deprecated)

**Merged into `ck3_status`:**
- `ck3_get_instance_info`
- `ck3_ping`
- `ck3_get_policy_status`
- `ck3_get_agent_briefing`
- `ck3_get_detected_mode`
- `ck3_get_workspace_config`

**Merged into `ck3_db`:**
- `ck3_close_db`
- `ck3_db_delete`
- `ck3_db_query`

**Merged into `ck3_search`:**
- `ck3_file_search`
- `ck3_search_mods`

---

## Implementation Notes

### Breaking Changes

This is a **breaking change** to the MCP tool API. Existing agent conversations will have stale tool references.

**Mitigation:**
1. Implement as part of the Reply System Phase C migration
2. Update copilot-instructions.md with new tool names
3. Old tool names can be kept as deprecated aliases for one release cycle (optional)

### Reply System Integration

All consolidated tools should return `Reply` objects per the Reply System specification.

### Mode-Aware Behavior

The new `ck3_search` should be mode-aware:
- `ck3lens` mode: Uses mod-name addressing by default
- `ck3raven-dev` mode: Uses path addressing by default

---

## Open Questions

1. **Should we keep deprecated aliases?** For backward compatibility during transition?
2. **Should `ck3_grep_raw` merge into `ck3_search`?** It's specialized for raw filesystem grep, which is different from database search.
3. **What about `ck3_parse_content`?** Should it merge into `ck3_script(target="parse")`?
4. **Should `ck3_report_validation_issue` have a shorter name?** Like `ck3_report_issue` or merge into a broader feedback tool?

---

## Approval Checklist

- [ ] User approves overall consolidation strategy
- [ ] User confirms new tool names
- [ ] User confirms removal of `ck3_token`
- [ ] User confirms breaking change is acceptable
- [ ] Implementation can proceed after Reply System Phase C migration

---

## Timeline

| Phase | Work | Depends On |
|-------|------|------------|
| 1 | Complete Reply System Phase C migration | Current |
| 2 | Implement `ck3_status` consolidation | Phase 1 |
| 3 | Expand `ck3_db` with merged commands | Phase 1 |
| 4 | Rename `ck3_conflicts` → `ck3_resolver` | Phase 1 |
| 5 | Rename `ck3_validate` → `ck3_script` | Phase 1 |
| 6 | Expand `ck3_search` with merged commands | Phase 1 |
| 7 | Remove `ck3_token` | Phase 1 |
| 8 | Update documentation | All phases |
