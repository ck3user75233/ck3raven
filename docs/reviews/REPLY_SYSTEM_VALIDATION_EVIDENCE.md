# REPLY_SYSTEM_VALIDATION_EVIDENCE.md

Generated: 2026-02-03T10:24Z
Instance: 4fde-4b0dd3

---

## Test 1 — Successful Tool Execution

### Reply
```json
{"reply_type":"S","code":"MCP-SYS-S-001","message":"Ping successful.","data":{"status":"ok","instance_id":"4fde-4b0dd3","timestamp":"2026-02-03T18:23:16.562342"},"trace":{"trace_id":"707f8f0de4024b46","session_id":"1784c6fca764410d"},"meta":{"layer":"MCP","tool":"ck3_ping","contract_id":null}}
```

### Log
```json
{"ts": "2026-02-03T10:23:16.562Z", "level": "INFO", "cat": "mcp.tool", "inst": "4fde-4b0dd3", "trace_id": "707f8f0de4024b46", "msg": "tool_end", "data": {"tool": "ck3_ping", "reply_type": "S", "code": "MCP-SYS-S-001", "duration_ms": 0.04}}
```

---

## Test 2 — Invalid Input

### Reply
```json
{"reply_type":"S","code":"WA-READ-S-001","message":"Search completed: 0 symbols, 0 refs, 0 content matches.","data":{"query":"","playset":"ACTIVE PLAYSET",...},"trace":{"trace_id":"355fb2715d60466f","session_id":"1784c6fca764410d"},"meta":{"layer":"MCP","tool":"ck3_search","contract_id":null}}
```

### Log
```json
{"ts": "2026-02-03T10:23:27.247Z", "level": "INFO", "cat": "mcp.tool", "inst": "4fde-4b0dd3", "trace_id": "355fb2715d60466f", "msg": "tool_end", "data": {"tool": "ck3_search", "reply_type": "S", "code": "WA-READ-S-001", "duration_ms": 1001.52}}
```

### Observation
Empty query is tolerated by ck3_search. Returns success with empty results.

---

## Test 3 — Enforcement Denial (EN-Owned)

### Reply
```json
{"reply_type":"D","code":"EN-DB-D-001","message":"DB deletion requires explicit confirmation (provide token_id)","data":{"success":false,"target":"content_versions","scope":"all","error":"DB deletion requires explicit confirmation (provide token_id)","policy_decision":"REQUIRE_TOKEN","required_token_type":null,"hint":"Use ck3_token to request a None token"},"trace":{"trace_id":"1800f29962ac4f3f","session_id":"1784c6fca764410d"},"meta":{"layer":"MCP","tool":"ck3_db_delete","contract_id":null}}
```

### Log
```json
{"ts": "2026-02-03T10:24:12.526Z", "level": "WARN", "cat": "mcp.tool", "inst": "4fde-4b0dd3", "trace_id": "1800f29962ac4f3f", "msg": "tool_end", "data": {"tool": "ck3_db_delete", "reply_type": "D", "code": "EN-DB-D-001", "duration_ms": 21.68}}
```

---

## Test 4 — Ungoverned System Write (MCP-Owned)

### Reply
```json
{"reply_type":"S","code":"WA-LOG-S-001","message":"Validation issue recorded. ID: dc8ffe4973b9. Will be reviewed in ck3raven-dev mode.","data":{"issue_id":"dc8ffe4973b9","issues_file":"c:\\Users\\nateb\\Documents\\CK3 Mod Project 1.18\\ck3raven\\ck3lens_validation_issues.jsonl"},"trace":{"trace_id":"024d88fc8f544d39","session_id":"1784c6fca764410d"},"meta":{"layer":"MCP","tool":"ck3_report_validation_issue","contract_id":null}}
```

### Log
```json
{"ts": "2026-02-03T10:24:23.939Z", "level": "INFO", "cat": "mcp.tool", "inst": "4fde-4b0dd3", "trace_id": "024d88fc8f544d39", "msg": "tool_end", "data": {"tool": "ck3_report_validation_issue", "reply_type": "S", "code": "WA-LOG-S-001", "duration_ms": 2.02}}
```

### Observation
Code is WA-LOG-S-001, not MCP-SYS-S-*. This tool was attributed to WA layer.

---

## Test 5 — Exception Path (Infrastructure Failure)

### Reply
```json
{"reply_type":"E","code":"MCP-SYS-E-001","message":"no such table: nonexistent_table_xyz_force_error","data":{"error":"no such table: nonexistent_table_xyz_force_error"},"trace":{"trace_id":"901ac8ef0f5348dd","session_id":"1784c6fca764410d"},"meta":{"layer":"MCP","tool":"ck3_db_query","contract_id":null}}
```

### Log
```json
{"ts": "2026-02-03T10:24:35.865Z", "level": "ERROR", "cat": "mcp.tool", "inst": "4fde-4b0dd3", "trace_id": "901ac8ef0f5348dd", "msg": "tool_end", "data": {"tool": "ck3_db_query", "reply_type": "E", "code": "MCP-SYS-E-001", "duration_ms": 0.1}}
```

---

## Test 6 — Legacy Code Elimination (Audit)

### Command
```powershell
Select-String -Path "$env:USERPROFILE\.ck3raven\logs\ck3raven-mcp.log" -Pattern "MCP-SYS-S-900" | Measure-Object | Select-Object -ExpandProperty Count
```

### Output
```
0
```

---

## Test 7 — Trace ↔ Log Correlation

### Log Entry (trace_id: 707f8f0de4024b46)
```json
{"ts": "2026-02-03T10:23:16.562Z", "level": "INFO", "cat": "mcp.tool", "inst": "4fde-4b0dd3", "trace_id": "707f8f0de4024b46", "msg": "tool_end", "data": {"tool": "ck3_ping", "reply_type": "S", "code": "MCP-SYS-S-001", "duration_ms": 0.04}}
```

### Trace Entry (file: 4fde-4b0dd3.jsonl)
```json
{"event": "tool_call", "timestamp": 1770114196.5627282, "iso_time": "2026-02-03T10:23:16Z", "window_id": "4fde-4b0dd3", "trace_id": "707f8f0de4024b46", "tool": "ck3_ping", "params": {}, "result_summary": {"reply_type": "S", "code": "MCP-SYS-S-001", "message": "Ping successful.", "data_keys": ["status", "instance_id", "timestamp"]}, "error": null, "duration_ms": 0.04}
```

---

## Test 8 — Reply Code Format Validation

### Unique Codes Observed
```
EN-DB-D-001
EN-EXEC-S-001
MCP-SYS-E-001
MCP-SYS-S-001
WA-LOG-S-001
WA-READ-S-001
WA-RES-I-001
```

### Format Check
| Code | LAYER | AREA | TYPE | NNN | Valid |
|------|-------|------|------|-----|-------|
| EN-DB-D-001 | EN | DB | D | 001 | ✓ |
| EN-EXEC-S-001 | EN | EXEC | S | 001 | ✓ |
| MCP-SYS-E-001 | MCP | SYS | E | 001 | ✓ |
| MCP-SYS-S-001 | MCP | SYS | S | 001 | ✓ |
| WA-LOG-S-001 | WA | LOG | S | 001 | ✓ |
| WA-READ-S-001 | WA | READ | S | 001 | ✓ |
| WA-RES-I-001 | WA | RES | I | 001 | ✓ |

### Layer Type Enforcement
| Code | Layer | Type | Allowed Types | Valid |
|------|-------|------|---------------|-------|
| EN-DB-D-001 | EN | D | S, D, E | ✓ |
| EN-EXEC-S-001 | EN | S | S, D, E | ✓ |
| MCP-SYS-E-001 | MCP | E | S, I, E | ✓ |
| MCP-SYS-S-001 | MCP | S | S, I, E | ✓ |
| WA-LOG-S-001 | WA | S | S, I, E | ✓ |
| WA-READ-S-001 | WA | S | S, I, E | ✓ |
| WA-RES-I-001 | WA | I | S, I, E | ✓ |

---

## Test Results with Pass/Fail Rationale

| Test | Action | Expected | Observed | Pass/Fail | Rationale |
|------|--------|----------|----------|-----------|-----------|
| **1** | `ck3_ping` | S, code ≠ MCP-SYS-S-900 | `MCP-SYS-S-001`, `reply_type=S` | **PASS** | Correct layer (MCP), correct type (S), no legacy code |
| **2** | `ck3_search { query: "" }` | I (invalid input), WA layer | `WA-READ-S-001`, `reply_type=S` | **FAIL** | Empty query should be rejected as invalid input, not tolerated. Tool returns success with empty results. |
| **3** | `ck3_db_delete { target: "content_versions", scope: "all" }` | D, EN layer | `EN-DB-D-001`, `reply_type=D` | **PASS** | Correct layer (EN), correct type (D), enforcement denial |
| **4** | `ck3_report_validation_issue` | S, MCP layer (ungoverned) | `WA-LOG-S-001`, `reply_type=S` | **FAIL** | Test expected MCP-owned ungoverned write. Got WA-LOG-S-001. Either test expectation wrong or attribution wrong. |
| **5** | `ck3_db_query { sql: "SELECT * FROM nonexistent_table" }` | E, MCP layer (exception) | `MCP-SYS-E-001`, `reply_type=E` | **FAIL** | Bad SQL is **invalid input**, not infrastructure exception. Should be `WA-SQL-I-001` or similar. E reserved for unexpected failures only. |
| **6** | grep for `MCP-SYS-S-900` | 0 matches | 0 matches | **PASS** | No legacy codes in logs |
| **7** | Trace ↔ Log correlation | Same trace_id in both | `707f8f0de4024b46` in both | **PASS** | Correlation working correctly |
| **8** | Reply code format | All match `LAYER-AREA-TYPE-NNN` | All 7 codes valid format | **PASS** | Format constraint enforced |

---

## Summary

| Result | Count |
|--------|-------|
| **PASS** | 5 |
| **FAIL** | 3 |

### Failures Requiring Remediation

1. **Test 2**: `ck3_search` should reject empty query as `WA-SEARCH-I-001` (invalid input)
2. **Test 4**: Attribution unclear - is `ck3_report_validation_issue` WA-owned or MCP-owned?
3. **Test 5**: SQL errors from bad user input should be `I` (invalid input), not `E` (exception). `E` must require actual exception in call stack - predictable validation failures are not exceptions.
