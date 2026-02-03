# REVIEW: MCP-SYS-S-900 Occurrence Conversions

**Status:** Conversion COMPLETE - All occurrences converted and reviewed  
**Generated:** February 3, 2026  
**Review Date:** February 3, 2026 (corrections applied)

---

## Executive Summary

All legacy `MCP-SYS-S-900` codes have been converted to canonical `LAYER-AREA-TYPE-NNN` format.

**Critical corrections applied after review:**

| Item | Before | After | Reason |
|------|--------|-------|--------|
| `ck3_file` write/edit/delete | WA-WRITE-S-001 | **EN-WRITE-S-001** | Governed mutation → EN owns |
| `ck3_db_delete` | WA-DB-S-001 | **MCP-DB-S-001** | System-owned/ungoverned |
| `ck3_repair` | WA-SYS-S-001 | **MCP-SYS-S-001** | System-owned/ungoverned |
| `ck3_qbuilder` | WA-SYS-S-001 | **MCP-SYS-S-001** | System-owned/ungoverned |
| `ck3_ping` | WA-SYS-S-001 | **MCP-SYS-S-001** | System health probe |
| `ck3_get_instance_info` | WA-CFG-S-001 | **MCP-SYS-S-001** | Infrastructure metadata |

---

## Attribution Process Applied

For each code assignment, the following 5-step process was applied:

1. **Identify decision ownership** - Which subsystem made the decision?
2. **Determine governance status** - Did it pass through Enforcement/Contract checks?
   - If yes → success belongs to EN
   - If no → success belongs to MCP (for system ops) or WA (for world structure)
3. **Assign AREA independently** - What domain (WRITE, READ, DB, SYS, etc.)
4. **Assign TYPE** - S/I/D/E
5. **Validate constraints** - WA/CT cannot emit D, EN cannot emit I

---

## Final Code Assignments

### EN Layer (Governed Operations)

| Function | Code | Decision Owner |
|----------|------|----------------|
| `ck3_file` write/edit/delete/rename | EN-WRITE-S-001 | Enforcement approved mutation |
| `ck3_exec` executed | EN-EXEC-S-001 | Enforcement approved command |
| `ck3_exec` dry_run | EN-EXEC-S-002 | Enforcement would allow |
| `ck3_get_policy_status` healthy | EN-GATE-S-001 | Enforcement health check |

### MCP Layer (System-Owned / Ungoverned)

| Function | Code | Decision Owner |
|----------|------|----------------|
| `ck3_ping` | MCP-SYS-S-001 | Infrastructure health probe |
| `ck3_get_instance_info` | MCP-SYS-S-001 | Infrastructure metadata |
| `ck3_db_delete` confirmed | MCP-DB-S-001 | System-owned DB mutation |
| `ck3_db_delete` preview | MCP-DB-S-002 | System-owned preview |
| `ck3_repair` executed | MCP-SYS-S-001 | System maintenance |
| `ck3_repair` dry_run | MCP-SYS-S-002 | System preview |
| `ck3_qbuilder` status | MCP-SYS-S-001 | Daemon infrastructure |
| `ck3_qbuilder` build | MCP-SYS-S-001 | Daemon spawn |
| `ck3_qbuilder` discover | MCP-SYS-S-001 | Task enqueue |

### WA Layer (World Structure / Reads)

| Function | Code | Decision Owner |
|----------|------|----------------|
| `debug_get_logs` | WA-LOG-S-001 | Reading log files |
| `ck3_close_db` / `ck3_db` status | WA-DB-S-001 | DB connection state |
| `ck3_logs` | WA-LOG-S-001 | Log query |
| `ck3_conflicts` | WA-READ-S-001 | Conflict data read |
| `ck3_file` read/get/list | WA-READ-S-001 | File content read |
| `ck3_folder` | WA-READ-S-001 | Directory listing |
| `ck3_playset` | WA-VIS-S-001 | Playset visibility |
| `ck3_git` | WA-GIT-S-001 | Git status/diff |
| `ck3_validate` | WA-VAL-S-001 | Syntax validation |
| `ck3_vscode` | WA-IO-S-001 | External IPC |
| `ck3_search` | WA-READ-S-001 | Symbol search |
| `ck3_grep_raw` | WA-READ-S-001 | Text search |
| `ck3_file_search` | WA-READ-S-001 | Path search |
| `ck3_parse_content` | WA-PARSE-S-001 | Parse to AST |
| `ck3_report_validation_issue` | WA-LOG-S-001 | Journal write |
| `ck3_get_agent_briefing` | WA-CFG-S-001 | Config read |
| `ck3_search_mods` | WA-READ-S-001 | DB search |
| `ck3_get_mode_instructions` | WA-CFG-S-001 | Mode config |
| `ck3_get_detected_mode` | WA-CFG-S-001 | Mode state |
| `ck3_get_workspace_config` | WA-CFG-S-001 | Config read |
| `ck3_db_query` | WA-DB-S-001 | DB read |
| `ck3_journal` | WA-READ-S-001 | Journal read |

### CT Layer (Contract Lifecycle)

| Function | Code | Decision Owner |
|----------|------|----------------|
| `ck3_contract` status | CT-VAL-S-001 | Contract state |
| `ck3_contract` open | CT-OPEN-S-001 | Contract opened |
| `ck3_contract` close | CT-CLOSE-S-001 | Contract closed |
| `ck3_contract` cancel | CT-CLOSE-S-002 | Contract cancelled |

---

## Registry Updates Applied

New codes added to `reply_codes.py`:

```python
# MCP Success codes (for system-owned / ungoverned operations)
MCP_SYS_S_001 = ReplyCode("MCP-SYS-S-001", Layer.MCP, Area.SYS, ReplyType.S, 1,
    "SYS_OP_OK", "System-owned operation complete")
MCP_SYS_S_002 = ReplyCode("MCP-SYS-S-002", Layer.MCP, Area.SYS, ReplyType.S, 2,
    "SYS_PREVIEW_OK", "System-owned preview complete")

# MCP DB codes (for system-owned database operations)
MCP_DB_S_001 = ReplyCode("MCP-DB-S-001", Layer.MCP, Area.DB, ReplyType.S, 1,
    "DB_OP_OK", "System-owned DB operation complete")
MCP_DB_S_002 = ReplyCode("MCP-DB-S-002", Layer.MCP, Area.DB, ReplyType.S, 2,
    "DB_PREVIEW_OK", "System-owned DB preview complete")
```

---

## Validation

```
$ rg "WA-SYS-S" server.py
(0 matches)

$ rg "MCP-SYS-S-900" server.py
(0 matches)
```

All codes now follow canonical attribution rules.

