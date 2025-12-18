# Project Status - December 18, 2025 (Updated)

## Session Summary

This session focused on:
1. Setting up ck3lens mode with VS Code Tool Sets
2. Adding Culture Expanded mod to the active playset
3. Building the unit-level conflict analyzer for compatching
4. Building the conflicts report generator (v1)
5. Adding general search tools (search_files, search_content)
6. Updating all architecture documentation

---

## Major Accomplishments

### 1. ✅ VS Code Tool Sets Configuration
**Files Created/Updated:**
- `.vscode/toolSets.json` - Three tool sets: `ck3lens`, `ck3lens-live`, `ck3raven-dev`
- `.vscode/mcp.json` - MCP server configuration

**Tool Sets:**
| Tool Set | Tools | Purpose |
|----------|-------|---------|
| `ck3lens` | 22 specific MCP tools | Database-only compatching |
| `ck3lens-live` | `mcp_ck3lens_*` | Full modding with file editing |
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
| file_contents | ~80,000 | ✅ 26 GB deduplicated |
| files | ~85,000 | ✅ |
| playsets | 1 | ✅ Active playset configured |
| playset_mods | 106 | ✅ Including Culture Expanded |
| symbols | ~1,200,000 | ✅ Extracted |
| asts | ~70,000 | ✅ Cached |
| contribution_units | 0 | ⏳ Run `ck3_scan_unit_conflicts` to populate |
| conflict_units | 0 | ⏳ Run `ck3_scan_unit_conflicts` to populate |
| conflict_candidates | 0 | ⏳ Run `ck3_scan_unit_conflicts` to populate |
| resolution_choices | 0 | ⏳ Populated when conflicts are resolved |

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
| Validation | `ck3_parse_content`, `ck3_validate_patchdraft` |
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
