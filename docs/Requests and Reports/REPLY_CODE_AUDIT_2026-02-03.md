# Reply Code Audit — February 3, 2026

**Status:** PENDING REVIEW  
**Purpose:** Complete audit of all reply codes in `server.py` against the canonical Reply System architecture.

---

## Executive Summary

### The Problem

The current implementation uses **ad-hoc tool-based code prefixes** (e.g., `FILE-OP-S-001`, `PLAYSET-OP-E-001`) instead of the canonical **LAYER-AREA-TYPE-NNN** format that encodes semantic ownership.

### Key Violations Found

| Issue | Count | Severity |
|-------|-------|----------|
| Tool-named codes (not layer-based) | 28 | High |
| CT layer emitting D (forbidden) | 1 | **Critical** |
| Wrong TYPE for semantics | 5 | Medium |
| Legacy wrap code (`MCP-SYS-S-900`) | 14 | High (silent error hiding) |

---

## Canonical Format Specification

### Format: `LAYER-AREA-TYPE-NNN`

| Element | Values | Description |
|---------|--------|-------------|
| **LAYER** | WA, EN, CT, MCP | Semantic owner of the decision |
| **AREA** | SYS, RES, VIS, READ, WRITE, EXEC, OPEN, CLOSE, VAL, DB, PARSE, GIT | Functional domain |
| **TYPE** | S, I, D, E | Reply type |
| **NNN** | 001-999 | Unique identifier |

### Layer Ownership Rules (Decision-Locked)

| Layer | May Emit | Must NOT Emit | Semantics |
|-------|----------|---------------|-----------|
| **WA** (World Adapter) | S, I, E | **D** | Resolution, visibility, world-mapping |
| **EN** (Enforcement) | S, D, E | **I** | Governance, authorization, policy |
| **CT** (Contract System) | S, I, E | **D** | Contract lifecycle only |
| **MCP** (Infrastructure) | E (and I for tool inputs) | D | Transport, system failures |

---

## Complete Code Inventory

### 1. MCP-SYS-S-900 — Legacy Wrap (DELETE CANDIDATE)

> ⚠️ **This code silently wraps non-Reply returns as success. Should be removed.**

| Line | Tool | Context | Proposed Action |
|------|------|---------|-----------------|
| [L932](../tools/ck3lens_mcp/server.py#L932) | `ck3_db` | status retrieved | Replace with `WA-DB-S-001` |
| [L958](../tools/ck3lens_mcp/server.py#L958) | `ck3_db` | enabled | Replace with `WA-DB-S-001` |
| [L1052](../tools/ck3lens_mcp/server.py#L1052) | `ck3_db_delete` | success | Replace with `WA-DB-S-001` |
| [L1058](../tools/ck3lens_mcp/server.py#L1058) | `ck3_db_delete` | complete | Replace with `WA-DB-S-001` |
| [L1437](../tools/ck3lens_mcp/server.py#L1437) | `ck3_get_policy_status` | healthy | Replace with `EN-VAL-S-001` |
| [L1560](../tools/ck3lens_mcp/server.py#L1560) | `ck3_logs` | query complete | Replace with `WA-READ-S-001` |
| [L1682](../tools/ck3lens_mcp/server.py#L1682) | `ck3_conflicts` | symbols | Replace with `WA-RES-S-001` |
| [L1732](../tools/ck3lens_mcp/server.py#L1732) | `ck3_conflicts` | files | Replace with `WA-RES-S-001` |
| [L1784](../tools/ck3lens_mcp/server.py#L1784) | `ck3_conflicts` | summary | Replace with `WA-RES-S-001` |
| [L2762](../tools/ck3lens_mcp/server.py#L2762) | `ck3_validate` | complete | Replace with `WA-VAL-S-001` |
| [L2833](../tools/ck3lens_mcp/server.py#L2833) | `ck3_vscode` | complete | Replace with `WA-READ-S-001` |
| [L3801](../tools/ck3lens_mcp/server.py#L3801) | `ck3_exec` | executed | Replace with `EN-EXEC-S-001` |
| [L3806](../tools/ck3lens_mcp/server.py#L3806) | `ck3_exec` | complete | Replace with `EN-EXEC-S-001` |
| [L4215](../tools/ck3lens_mcp/server.py#L4215) | `ck3_search` | complete | Replace with `WA-RES-S-001` |

---

### 2. MCP-SYS-I-901 — Invalid Input

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L961](../tools/ck3lens_mcp/server.py#L961) | `ck3_db` | unknown command | `MCP-SYS-I-901` | `MCP-SYS-I-001` | ✅ Correct layer, renumber |
| [L1056](../tools/ck3lens_mcp/server.py#L1056) | `ck3_db_delete` | preview | `MCP-SYS-I-901` | `WA-DB-I-001` | DB validation = World |
| [L3804](../tools/ck3lens_mcp/server.py#L3804) | `ck3_exec` | dry run | `MCP-SYS-I-901` | `EN-EXEC-S-002` | **Problem:** EN cannot emit I. Dry run is success (preview) |
| [L4076](../tools/ck3lens_mcp/server.py#L4076) | `ck3_token` | deprecated | `MCP-SYS-I-901` | `MCP-SYS-I-001` | ✅ Correct layer |

---

### 3. MCP-SYS-D-903 — Policy Denied

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L1047](../tools/ck3lens_mcp/server.py#L1047) | `ck3_db_delete` | policy denied | `MCP-SYS-D-903` | `EN-DB-D-001` | Move to EN layer |
| [L3795](../tools/ck3lens_mcp/server.py#L3795) | `ck3_exec` | command denied | `MCP-SYS-D-903` | `EN-EXEC-D-001` | Move to EN layer |

---

### 4. MCP-SYS-E-001 — System Error

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L1048](../tools/ck3lens_mcp/server.py#L1048) | `ck3_db_delete` | internal error | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L1444](../tools/ck3lens_mcp/server.py#L1444) | `ck3_get_policy_status` | policy DOWN | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L1554](../tools/ck3lens_mcp/server.py#L1554) | `ck3_logs` | error | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L1657](../tools/ck3lens_mcp/server.py#L1657) | `ck3_conflicts` | no mods in session | `MCP-SYS-E-001` | `WA-VIS-I-001` | **Wrong type:** Missing prerequisite = Invalid |
| [L2756](../tools/ck3lens_mcp/server.py#L2756) | `ck3_validate` | error | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L2827](../tools/ck3lens_mcp/server.py#L2827) | `ck3_vscode` | error | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L3796](../tools/ck3lens_mcp/server.py#L3796) | `ck3_exec` | command failed | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L4354](../tools/ck3lens_mcp/server.py#L4354) | `ck3_grep_raw` | exception | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L4455](../tools/ck3lens_mcp/server.py#L4455) | `ck3_file_search` | exception | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L4827](../tools/ck3lens_mcp/server.py#L4827) | `ck3_get_mode_instructions` | error | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L5440](../tools/ck3lens_mcp/server.py#L5440) | `ck3_db_query` | SQL exception | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L5495](../tools/ck3lens_mcp/server.py#L5495) | `ck3_db_query` | exception | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L5656](../tools/ck3lens_mcp/server.py#L5656) | `ck3_qbuilder` | exception | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L5707](../tools/ck3lens_mcp/server.py#L5707) | `ck3_qbuilder` | lock held | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L5747](../tools/ck3lens_mcp/server.py#L5747) | `ck3_qbuilder` | exception | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |
| [L5753](../tools/ck3lens_mcp/server.py#L5753) | `ck3_qbuilder` | daemon not running | `MCP-SYS-E-001` | `WA-SYS-I-001` | **Wrong type:** Service unavailable = Invalid |
| [L5768](../tools/ck3lens_mcp/server.py#L5768) | `ck3_qbuilder` | daemon not available | `MCP-SYS-E-001` | `WA-SYS-I-001` | **Wrong type:** Same |
| [L5778](../tools/ck3lens_mcp/server.py#L5778) | `ck3_qbuilder` | exception | `MCP-SYS-E-001` | `MCP-SYS-E-001` | ✅ Correct |

---

### 5. DB-CONN-* Codes (Non-Canonical)

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L882](../tools/ck3lens_mcp/server.py#L882) | `ck3_close_db` | success | `DB-CONN-S-001` | `WA-DB-S-001` | DB ops = World |
| [L888](../tools/ck3lens_mcp/server.py#L888) | `ck3_close_db` | exception | `DB-CONN-E-001` | `MCP-SYS-E-001` | Exception = MCP |
| [L953](../tools/ck3lens_mcp/server.py#L953) | `ck3_db` | disabled | `DB-CONN-S-001` | `WA-DB-S-001` | DB ops = World |

---

### 6. FILE-OP-* Codes (Non-Canonical)

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L1930](../tools/ck3lens_mcp/server.py#L1930) | `ck3_file` | write denied (REQUIRE_TOKEN) | `FILE-OP-D-001` | `EN-WRITE-D-001` | Denied = EN |
| [L1932](../tools/ck3lens_mcp/server.py#L1932) | `ck3_file` | write denied (permission) | `FILE-OP-D-001` | `EN-WRITE-D-001` | Denied = EN |
| [L1936](../tools/ck3lens_mcp/server.py#L1936) | `ck3_file` | file not found | `FILE-OP-I-001` | `WA-RES-I-001` | Invalid path = WA |
| [L1939](../tools/ck3lens_mcp/server.py#L1939) | `ck3_file` | error fallback | `FILE-OP-E-001` | `MCP-SYS-E-001` | Error = MCP |
| [L1941](../tools/ck3lens_mcp/server.py#L1941) | `ck3_file` | complete | `FILE-OP-S-001` | `WA-WRITE-S-001` or `WA-READ-S-001` | File ops = WA |

---

### 7. FOLDER-OP-* Codes (Non-Canonical)

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L2022](../tools/ck3lens_mcp/server.py#L2022) | `ck3_folder` | error | `FOLDER-OP-E-001` | `MCP-SYS-E-001` | Error = MCP |
| [L2024](../tools/ck3lens_mcp/server.py#L2024) | `ck3_folder` | complete | `FOLDER-OP-S-001` | `WA-READ-S-001` | Read = WA |

---

### 8. PLAYSET-OP-* Codes (Non-Canonical)

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L2093](../tools/ck3lens_mcp/server.py#L2093) | `ck3_playset` | error | `PLAYSET-OP-E-001` | `MCP-SYS-E-001` | Error = MCP |
| [L2096](../tools/ck3lens_mcp/server.py#L2096) | `ck3_playset` | switched | `PLAYSET-OP-S-002` | `WA-VIS-S-001` | Visibility = WA |
| [L2100](../tools/ck3lens_mcp/server.py#L2100) | `ck3_playset` | active | `PLAYSET-OP-S-001` | `WA-VIS-S-001` | Visibility = WA |
| [L2102](../tools/ck3lens_mcp/server.py#L2102) | `ck3_playset` | complete | `PLAYSET-OP-S-001` | `WA-VIS-S-001` | Visibility = WA |

---

### 9. GIT-CMD-* Codes (Non-Canonical)

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L2685](../tools/ck3lens_mcp/server.py#L2685) | `ck3_git` | error | `GIT-CMD-E-001` | `MCP-SYS-E-001` | Error = MCP |
| [L2687](../tools/ck3lens_mcp/server.py#L2687) | `ck3_git` | complete | `GIT-CMD-S-001` | `WA-GIT-S-001` | Git = WA |

---

### 10. REPAIR-OP-* Codes (Non-Canonical)

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L2894](../tools/ck3lens_mcp/server.py#L2894) | `ck3_repair` | error | `REPAIR-OP-E-001` | `MCP-SYS-E-001` | Error = MCP |
| [L2897](../tools/ck3lens_mcp/server.py#L2897) | `ck3_repair` | dry run | `REPAIR-OP-I-001` | `WA-SYS-S-002` | Preview = Success (not Invalid) |
| [L2899](../tools/ck3lens_mcp/server.py#L2899) | `ck3_repair` | complete | `REPAIR-OP-S-001` | `WA-SYS-S-001` | Repair = WA |

---

### 11. CONTRACT-OP-* Codes — **CRITICAL VIOLATIONS**

> ⚠️ **CT layer emitting D is forbidden. These must be remapped.**

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L3357](../tools/ck3lens_mcp/server.py#L3357) | `ck3_contract` | not authorized | `CONTRACT-OP-D-001` | `EN-OPEN-D-001` | **⛔ CT cannot emit D** → Move to EN |
| [L3358](../tools/ck3lens_mcp/server.py#L3358) | `ck3_contract` | error | `CONTRACT-OP-E-001` | `MCP-SYS-E-001` | Error = MCP |
| [L3362](../tools/ck3lens_mcp/server.py#L3362) | `ck3_contract` | active | `CONTRACT-OP-S-003` | `CT-OPEN-S-001` | ✅ Contract success |
| [L3363](../tools/ck3lens_mcp/server.py#L3363) | `ck3_contract` | no active contract | `CONTRACT-OP-I-001` | **Semantic split needed** (see below) |
| [L3366](../tools/ck3lens_mcp/server.py#L3366) | `ck3_contract` | opened | `CONTRACT-OP-S-001` | `CT-OPEN-S-001` | ✅ |
| [L3369](../tools/ck3lens_mcp/server.py#L3369) | `ck3_contract` | closed | `CONTRACT-OP-S-002` | `CT-CLOSE-S-001` | ✅ |
| [L3372](../tools/ck3lens_mcp/server.py#L3372) | `ck3_contract` | cancelled | `CONTRACT-OP-S-004` | `CT-CLOSE-S-002` | ✅ |
| [L3374](../tools/ck3lens_mcp/server.py#L3374) | `ck3_contract` | complete | `CONTRACT-OP-S-003` | `CT-VAL-S-001` | ✅ |

**Semantic Split for L3363:**
- If this is a **query response** ("status: no contract") → `CT-VAL-I-001` (informational)
- If this is **blocking execution** ("you need a contract") → `EN-OPEN-D-001` (governance)

---

### 12. SEARCH-OP-* Codes (Non-Canonical)

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L4280](../tools/ck3lens_mcp/server.py#L4280) | `ck3_grep_raw` | not visible | `SEARCH-OP-I-001` | `WA-RES-I-001` | Resolution = WA |
| [L4286](../tools/ck3lens_mcp/server.py#L4286) | `ck3_grep_raw` | no path | `SEARCH-OP-I-001` | `WA-RES-I-001` | Resolution = WA |
| [L4298](../tools/ck3lens_mcp/server.py#L4298) | `ck3_grep_raw` | not found | `SEARCH-OP-I-001` | `WA-RES-I-001` | Resolution = WA |
| [L4414](../tools/ck3lens_mcp/server.py#L4414) | `ck3_file_search` | not visible | `SEARCH-OP-I-001` | `WA-RES-I-001` | Resolution = WA |
| [L4420](../tools/ck3lens_mcp/server.py#L4420) | `ck3_file_search` | no path | `SEARCH-OP-I-001` | `WA-RES-I-001` | Resolution = WA |
| [L4430](../tools/ck3lens_mcp/server.py#L4430) | `ck3_file_search` | not found | `SEARCH-OP-I-001` | `WA-RES-I-001` | Resolution = WA |

---

### 13. PARSE-AST-* Codes (Non-Canonical)

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L4504](../tools/ck3lens_mcp/server.py#L4504) | `ck3_parse_content` | exception | `PARSE-AST-E-001` | `MCP-SYS-E-001` | Error = MCP |
| [L4533](../tools/ck3lens_mcp/server.py#L4533) | `ck3_parse_content` | success | `PARSE-AST-S-001` | `WA-PARSE-S-001` | Parse = WA |
| [L4546](../tools/ck3lens_mcp/server.py#L4546) | `ck3_parse_content` | syntax errors | `PARSE-AST-I-001` | `WA-PARSE-I-001` | Syntax = WA |

---

### 14. JRN-* Codes (Non-Canonical)

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L5579](../tools/ck3lens_mcp/server.py#L5579) | `ck3_journal` | success | `JRN-S-001` | `WA-READ-S-001` | Journal = WA |
| [L5581](../tools/ck3lens_mcp/server.py#L5581) | `ck3_journal` | error | `JRN-E-001` | `MCP-SYS-E-001` | Error = MCP |

---

### 15. DB-QUERY-* Codes (Non-Canonical)

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L5444](../tools/ck3lens_mcp/server.py#L5444) | `ck3_db_query` | no table/SQL | `DB-QUERY-I-001` | `WA-DB-I-001` | Input = WA |
| [L5447](../tools/ck3lens_mcp/server.py#L5447) | `ck3_db_query` | unknown table | `DB-QUERY-I-002` | `WA-DB-I-002` | Input = WA |

---

### 16. Non-Canonical Codes Introduced Today (February 3, 2026)

> ⚠️ **These were incorrectly created during the rb.error → rb.invalid refactor.**

| Line | Tool | Context | Current | Canonical | Notes |
|------|------|---------|---------|-----------|-------|
| [L1796](../tools/ck3lens_mcp/server.py#L1796) | `ck3_conflicts` | unknown command | `CONFLICTS-I-001` | `MCP-SYS-I-001` | Tool input = MCP |
| [L4668](../tools/ck3lens_mcp/server.py#L4668) | `ck3_get_agent_briefing` | no playset | `BRIEFING-I-001` | `WA-VIS-I-001` | Visibility = WA |
| [L5417](../tools/ck3lens_mcp/server.py#L5417) | `ck3_db_query` | no SQL | `DBQUERY-I-001` | `WA-DB-I-001` | Input = WA |
| [L5794](../tools/ck3lens_mcp/server.py#L5794) | `ck3_qbuilder` | unknown command | `QBUILDER-I-001` | `MCP-SYS-I-001` | Tool input = MCP |

---

## Proposed Canonical Code Registry

### WA (World Adapter) — May emit: S, I, E

| Code | Message Key | Meaning |
|------|-------------|---------|
| `WA-RES-S-001` | `RESOLUTION_OK` | Path/symbol resolved successfully |
| `WA-RES-I-001` | `PATH_NOT_FOUND` | Path does not exist in lens |
| `WA-RES-I-002` | `SYMBOL_NOT_FOUND` | Symbol not found |
| `WA-VIS-S-001` | `VISIBILITY_OK` | Visibility/playset operation complete |
| `WA-VIS-I-001` | `NO_PLAYSET` | No active playset configured |
| `WA-READ-S-001` | `READ_OK` | Read operation complete |
| `WA-WRITE-S-001` | `WRITE_OK` | Write operation complete |
| `WA-DB-S-001` | `DB_OP_OK` | Database operation complete |
| `WA-DB-I-001` | `DB_INPUT_MISSING` | Required DB input missing |
| `WA-DB-I-002` | `DB_TABLE_UNKNOWN` | Unknown table name |
| `WA-GIT-S-001` | `GIT_OP_OK` | Git operation complete |
| `WA-VAL-S-001` | `VALIDATION_OK` | Validation passed |
| `WA-PARSE-S-001` | `PARSE_OK` | Parse successful |
| `WA-PARSE-I-001` | `PARSE_SYNTAX_ERROR` | Syntax errors found |
| `WA-SYS-S-001` | `SYS_OP_OK` | System operation complete |
| `WA-SYS-S-002` | `SYS_PREVIEW_OK` | Preview/dry-run complete |
| `WA-SYS-I-001` | `SERVICE_UNAVAILABLE` | Required service not available |

### EN (Enforcement) — May emit: S, D, E

| Code | Message Key | Meaning |
|------|-------------|---------|
| `EN-WRITE-D-001` | `WRITE_DENIED` | Write denied by policy |
| `EN-EXEC-D-001` | `EXEC_DENIED` | Command execution denied |
| `EN-EXEC-S-001` | `EXEC_OK` | Command executed |
| `EN-EXEC-S-002` | `EXEC_DRY_RUN` | Dry run - would be allowed |
| `EN-DB-D-001` | `DB_OP_DENIED` | Database operation denied |
| `EN-OPEN-D-001` | `CONTRACT_REQUIRED` | Active contract required |
| `EN-VAL-S-001` | `POLICY_HEALTHY` | Policy system healthy |

### CT (Contract System) — May emit: S, I, E

| Code | Message Key | Meaning |
|------|-------------|---------|
| `CT-OPEN-S-001` | `CONTRACT_OPENED` | Contract opened |
| `CT-CLOSE-S-001` | `CONTRACT_CLOSED` | Contract closed |
| `CT-CLOSE-S-002` | `CONTRACT_CANCELLED` | Contract cancelled |
| `CT-VAL-S-001` | `CONTRACT_VALID` | Contract validation passed |
| `CT-VAL-I-001` | `CONTRACT_MALFORMED` | Contract request malformed |

### MCP (Infrastructure) — May emit: E, I (for tool input)

| Code | Message Key | Meaning |
|------|-------------|---------|
| `MCP-SYS-E-001` | `SYS_CRASH` | Unexpected exception |
| `MCP-SYS-I-001` | `INPUT_INVALID` | Tool input validation failed |

---

## Summary Statistics

| Category | Count |
|----------|-------|
| **Total codes audited** | 68 |
| **Correctly formatted** | 12 |
| **Need remapping (tool-based → layer-based)** | 51 |
| **Wrong TYPE for semantics** | 5 |
| **Critical CT→D violation** | 1 |

---

## Recommended Actions

1. **Create `tools/ck3lens_mcp/ck3lens/reply_codes.py`** — Central registry
2. **Update Canonical Reply System doc** — Replace lines 75-86 with expanded specification
3. **Refactor all codes in server.py** — Apply canonical mappings from this audit
4. **Remove `MCP-SYS-S-900`** — No legacy wrapping
5. **Split L3363 semantics** — Query response vs governance block
6. **Fix my February 3 mistakes** — Replace `CONFLICTS-I-001`, `BRIEFING-I-001`, `DBQUERY-I-001`, `QBUILDER-I-001`

---

*Generated: February 3, 2026*  
*Auditor: GitHub Copilot (Claude Opus 4.5)*  
*Status: Awaiting Review*
