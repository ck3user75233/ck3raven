# Project Status - December 19, 2025 (Updated)

## Session Summary

This session focused on:
1. **Fixing symbol extraction bug** - Wrong column name in rebuild script
2. **Fixing MCP server configuration** - mcp.json pointed to non-existent venv
3. **Adding database integrity tests** - Comprehensive test suite
4. **Adding large file handling** - Skip files >2MB to prevent parser hangs

---

## Critical Bug Fixes

### 1. ✅ Symbol Extraction Bug (FIXED)
**Root Cause:** `rebuild_database.py` used column name `context_json` but schema has `metadata_json`.

**Fix:** Changed line 302 from:
```python
(name, symbol_type, defining_file_id, line_number, context_json)
```
To:
```python
(name, symbol_type, defining_file_id, line_number, metadata_json)
```

**Result:** Symbols now extract correctly (~130,000+ from 4,400+ files before hang).

### 2. ✅ MCP Server Config Bug (FIXED - Architecture Changed Jan 2026)
**Original Issue:** `.vscode/mcp.json` pointed to `.venv\\Scripts\\python.exe` but no venv existed.

**Resolution (Jan 2026):** Static `.vscode/mcp.json` is now **DEPRECATED**. The MCP server is provided dynamically by the CK3 Lens Explorer extension via `tools/ck3lens-explorer/src/mcp/mcpServerProvider.ts`. Each VS Code window gets a unique instance ID (e.g., `f9hf-719e4f`).

**If MCP disconnects:** Check `"chat.mcp.discovery.enabled": true` in User Settings. NEVER create mcp.json to "fix" it.

**Old Fix (deprecated):** Updated to use system Python with cwd:
```json
{
  "servers": {
    "ck3lens": {
      "type": "stdio",
      "command": "python",
      "args": ["tools/ck3lens_mcp/server.py"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

**Requirement:** Install MCP package: `pip install mcp[cli] pydantic fs structlog typer`

### 3. ✅ Large File Handling (ADDED)
**Problem:** Parser hangs on very large files (>2MB), blocking all extraction.

**Fix:** Added size check in `phase_symbol_extraction`:
```python
max_file_size = 2_000_000  # Skip files larger than 2MB
if len(content) > max_file_size:
    skipped_large += 1
    continue
```

---

## New Test Files Created

| File | Purpose |
|------|---------|
| `tests/test_db_content_integrity.py` | 8 tests: DB exists, tables, content, AST parsing, symbol extraction |
| `tests/test_rebuild_logic.py` | Replicates exact rebuild logic to identify schema mismatches |

---

## Known Issues

### Parser Hangs on Large Files
Some files cause the parser to hang indefinitely. Added 2MB skip threshold.
Files affected are typically large localization or GUI definition files.

### @lens/@raven Agent Modes Not Implemented
The extension's `package.json` has no `chatParticipants` section.
These agent modes would require VS Code's Chat Participants API.

### Workspace File Addition Opens New Window
When adding game files, VS Code opens a new window because files are outside current workspace.
Use "Add Folder to Workspace" instead of "Open Folder".

---

## Major Accomplishments

### 1. ✅ VS Code Tool Sets Configuration
**Files Created/Updated:**
- `.vscode/toolSets.json` - Two tool sets: `ck3lens`, `ck3raven-dev`
- ~~`.vscode/mcp.json`~~ - **DEPRECATED** - MCP is now provided dynamically by the CK3 Lens Explorer extension via `mcpServerProvider.ts`. Static mcp.json causes duplicate servers.

**Tool Sets:**
| Tool Set | Tools | Purpose |
|----------|-------|---------|
| `ck3lens` | `mcp_ck3lens_*` | CK3 modding with live editing |
| `ck3raven-dev` | `*` | Infrastructure development |

### 2. ✅ Culture Expanded Mod Added
- **Workshop ID:** 2829397295
- **mod_package_id:** 103
- **content_version_id:** 107
- **Files ingested:** 792 files (40.7 MB)
- **Symbols extracted:** 2,028 symbols
- **Load order position:** 74 (before True Romans at 75)

### 3. ✅ Unit-Level Conflict Analyzer Built
**New Files:**
| File | Purpose |
|------|---------|
| `src/ck3raven/resolver/contributions.py` | Data contracts (ContributionUnit, ConflictUnit, ResolutionChoice) |
| `src/ck3raven/resolver/conflict_analyzer.py` | Extraction, grouping, risk scoring, queries |

**New Database Tables:**
- `contribution_units` - What each source provides for a unit_key
- `conflict_units` - Grouped conflicts with risk scores
- `conflict_candidates` - Links conflicts to contributions
- `resolution_choices` - User decisions on conflict resolution

**New MCP Tools (6 tools):**
| Tool | Purpose |
|------|---------|
| `ck3_scan_unit_conflicts` | Full playset conflict scan |
| `ck3_get_conflict_summary` | Summary counts by risk/domain |
| `ck3_list_conflict_units` | List conflicts with filters |
| `ck3_get_conflict_detail` | Full detail for one conflict |
| `ck3_resolve_conflict` | Record resolution decision |
| `ck3_get_unit_content` | Compare all versions of a unit |

**Key Features:**
- **Unit Key Scheme:** Stable identifiers like `on_action:on_yearly_pulse`, `trait:brave`
- **Risk Scoring (0-100):** Based on domain, candidate count, merge semantics
- **Risk Levels:** Low (0-29), Medium (30-59), High (60-100)
- **Merge Capability:** winner_only, guided_merge, ai_merge
- **Database-only:** No file I/O, no regex - all from parsed ASTs

### 4. ✅ Conflicts Report Generator Built (NEW)
**New File:** `src/ck3raven/resolver/report.py`

**Schema:** `ck3raven.conflicts.v1`

**Report Levels:**
- **File-level conflicts:** Path collisions (who touches the same vpath)
- **ID-level conflicts:** Semantic collisions within parseable domains

**New MCP Tools (2 tools):**
| Tool | Purpose |
|------|---------|
| `ck3_generate_conflicts_report` | Full file + ID conflict report (JSON or CLI) |
| `ck3_get_high_risk_conflicts` | Get highest-risk conflicts for priority review |

**Output Formats:**
- JSON (machine-readable, canonical schema)
- CLI summary (human-readable text)

### 5. ✅ General Search Tools Added (NEW)
**New DBQueries methods + MCP tools:**
| Tool | Purpose |
|------|---------|
| `ck3_search_files` | Search files by path pattern (SQL LIKE) |
| `ck3_search_content` | Grep-style text search with snippets |

These complement `ck3_search_symbols` which only searches symbol names.

### 6. ✅ Playset Management MCP Tools Added (5 tools)
| Tool | Purpose |
|------|---------|
| `ck3_get_active_playset` | Get current playset with mod list |
| `ck3_list_playsets` | List all available playsets |
| `ck3_search_mods` | Fuzzy search by name/ID/abbreviation |
| `ck3_add_mod_to_playset` | Full workflow: find → ingest → extract → add |
| `ck3_remove_mod_from_playset` | Remove with load order adjustment |

### 7. ✅ Documentation Updated
| File | Changes |
|------|---------|
| `docs/ARCHITECTURE.md` | Comprehensive architecture guide |
| `README.md` | Updated architecture diagram, status table, roadmap |
| `.github/COPILOT_RAVEN_DEV.md` | Updated architecture, status, roadmap |
| `.github/COPILOT_LENS_COMPATCH.md` | Added conflict analysis tools table, database-only rules |
| `.github/copilot-instructions.md` | Updated tools table (28+ tools) |
| `tools/ck3lens_mcp/docs/TOOLS.md` | Added Section 2: Unit-Level Conflict Analysis Tools |

---

## Current Database Status

| Table | Count | Status |
|-------|-------|--------|
| vanilla_versions | 1 | ✅ |
| mod_packages | 105 | ✅ Including Culture Expanded |
| content_versions | 110 | ✅ |
| file_contents | ~77,000 | ✅ 30,781 with content_text |
| files | ~81,000 | ✅ 80,962 non-deleted |
| playsets | 1 | ✅ Active playset configured |
| playset_mods | 106 | ✅ Including Culture Expanded |
| symbols | ~132,000 | ⚠️ Partial - run `--refresh-symbols` after VS Code reset |
| asts | ~70,000 | ✅ Cached |
| contribution_units | 0 | ⏳ Run `ck3_scan_unit_conflicts` to populate |
| conflict_units | 0 | ⏳ Run `ck3_scan_unit_conflicts` to populate |

**After VS Code Reset:**
```bash
cd ck3raven
python scripts/rebuild_database.py --refresh-symbols
```

---

## MCP Server Status

**Total Tools:** 25+

| Category | Tools |
|----------|-------|
| Session | `ck3_init_session` |
| Search | `ck3_search_symbols`, `ck3_confirm_not_exists` |
| Files | `ck3_get_file`, `ck3_list_live_files`, `ck3_read_live_file` |
| Playset | `ck3_get_active_playset`, `ck3_list_playsets`, `ck3_search_mods`, `ck3_add_mod_to_playset`, `ck3_remove_mod_from_playset` |
| Conflicts | `ck3_scan_unit_conflicts`, `ck3_get_conflict_summary`, `ck3_list_conflict_units`, `ck3_get_conflict_detail`, `ck3_resolve_conflict`, `ck3_get_unit_content`, `ck3_get_conflicts` |
| Validation | `ck3_parse_content` |
| Live Ops | `ck3_write_file`, `ck3_edit_file`, `ck3_delete_file` |
| Git | `ck3_git_status`, `ck3_git_diff`, `ck3_git_add`, `ck3_git_commit`, `ck3_git_pull`, `ck3_git_push` |

---

## Roadmap Progress

### Phase 1: Foundation ✅ Complete
### Phase 1.5: MCP Integration ✅ Complete

### Phase 4: Compatch Helper (IN PROGRESS)
- [x] Conflict unit extraction and grouping
- [x] Risk scoring algorithm
- [x] Unit-level MCP tools
- [ ] Decision card UI
- [ ] Merge editor
- [ ] Patch file generation

### Phase 2: Game State Emulator (NEXT)
### Phase 3: Explorer UI (PLANNED)

---

## Next Steps

1. **Test the conflict analyzer** - Run `ck3_scan_unit_conflicts()` on the current playset
2. **Review high-risk conflicts** - Focus on on_actions and events first
3. **Design compatches** for Culture Expanded integration
4. **Build patch files** using resolution decisions

---

## Key Insight from This Session

The conflict analyzer operates **entirely on the database**:
- No file I/O - content comes from `file_contents` table
- No regex - uses SQL patterns and JSON AST traversal
- ASTs are pre-parsed and cached by (content_hash, parser_version)
- All searches use adjacency matching for fuzzy symbol lookup

This makes it fast and reliable for large playsets (26+ GB of content).
