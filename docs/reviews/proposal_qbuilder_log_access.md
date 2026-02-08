# QBuilder Log Access via MCP Tools

**Date:** 2026-02-07  
**Status:** Proposal  
**Author:** ck3lens agent

---

## Problem Statement

`ck3_logs(log_type="qbuilder")` returns error summaries but not real-time processing logs. Agents need visibility into:
- What files are being processed
- How long each file takes
- Which files are timing out/failing
- Overall throughput rate

**Log files exist at:** `~/.ck3raven/logs/qbuilder_YYYY-MM-DD.jsonl`

---

## Proposed Enhancement

### New Tool: `ck3_qbuilder_logs`

```python
ck3_qbuilder_logs(
    command="tail",        # tail, head, stats, errors
    lines=50,              # number of lines for tail/head
    date="2026-02-07",     # optional date filter (defaults to today)
    filter="item_error"    # optional event type filter
)
```

### Output Modes

#### 1. `tail` / `head` - Raw Processing Log

Formatted as readable table:

| Time | Event | File | Duration | Status |
|------|-------|------|----------|--------|
| 22:46:23 | complete | bookmark_rags_to_riches_duke_robert.txt | 8.7s | OK |
| 22:46:14 | error | bookmark_persia_yaqub_alt_amr.txt | 30s | ParseTimeoutError |
| 22:45:29 | complete | bookmark_persia_suri_of_mandesh_alt_farhana.txt | 12.3s | OK |

#### 2. `stats` - Aggregated Processing Statistics

```json
{
  "run_id": "daemon-8d860621",
  "started": "2026-02-07 22:24:03",
  "total_processed": 329,
  "total_errors": 24,
  "error_rate": "7.3%",
  "avg_duration_ms": 3847,
  "p50_duration_ms": 340,
  "p95_duration_ms": 18700,
  "p99_duration_ms": 30000,
  "timeout_count": 24,
  "throughput_per_min": 2.1
}
```

#### 3. `errors` - Error-Only View

Filtered to `item_error` events with full details:

| Time | File | Duration | Error |
|------|------|----------|-------|
| 22:46:30 | bookmark_nomads_koncek_svoboda.txt | 30.0s | ParseTimeoutError |
| 22:45:16 | bookmark_nomads_togrul.txt | 30.0s | ParseTimeoutError |

---

## Implementation

**Location:** `tools/ck3lens_mcp/ck3lens/unified_tools.py`

**Log Format (JSONL):**
```json
{"ts": 1770475583.68, "event": "item_complete", "run_id": "daemon-8d860621", "file_id": 91210, "relpath": "common/bookmark_portraits/bookmark_rags_to_riches_duke_robert.txt", "duration_ms": 8687.22}
{"ts": 1770475620.28, "event": "item_error", "run_id": "daemon-8d860621", "file_id": 91212, "relpath": "common/bookmark_portraits/bookmark_rags_to_riches_duke_robert_alt_roger.txt", "duration_ms": 30031.63, "error": "ParseTimeoutError: Parse timeout after 30s: ..."}
```

**Event types to handle:**
- `run_start` - New daemon run started
- `worker_start` - Worker process spawned
- `item_claimed` - File claimed for processing
- `item_complete` - File processed successfully
- `item_error` - File processing failed
- `worker_progress` - Periodic progress update
- `worker_exit` - Worker finished
- `run_complete` - Run finished

---

## Benefits

1. **Real-time visibility** - See exactly what's processing without SQL queries
2. **Performance debugging** - Identify slow files and parser bottlenecks
3. **Error triage** - Quickly see which mods/files are failing
4. **Throughput monitoring** - Track items/minute to estimate completion time

---

## Priority

Medium - useful for debugging but existing `ck3_db_query` on build_queue provides basic visibility.
