# Feature Request: QBuilder Status Enhancement

**Date**: 2026-02-10  
**Source**: Agent session — agent polled `ck3_qbuilder(command="status")` and got `idle, pending:0` which was indistinguishable from "never processed anything", when in fact the daemon had completed 132 items 5 minutes earlier.

## Problem

The `ck3_qbuilder(command="status")` response currently returns:

```json
{
  "daemon_state": "idle",
  "queue": {"pending": 0, "leased": 0, "failed": 102}
}
```

This tells you queue state at this instant, but nothing about what happened. An idle daemon with an empty queue looks the same whether it:
- Just started and never processed anything
- Finished 132 items 10 seconds ago
- Has been idle for 6 hours

For an agent (or human) checking whether work completed, this is useless. The agent in this session incorrectly concluded the daemon "went idle and did nothing" because the status gave no evidence of completed work.

## Proposed Enhancement

Add a `recent_activity` section to the status response, sourced from the JSONL build log:

```json
{
  "daemon_state": "idle",
  "queue": {"pending": 0, "leased": 0, "failed": 102},
  "recent_activity": {
    "run_id": "daemon-9ace15b9",
    "items_processed": 132,
    "first_item_at": "2026-02-10T16:24:51",
    "last_item_at": "2026-02-10T16:24:57",
    "duration_seconds": 10.6,
    "mods_discovered": [
      "Dev Debuff (4 files)",
      "Lands Beyond Legend (7 files)",
      "Better Candidate Law (20 files)",
      "Meritocratic Provincial Law (8 files)",
      "Better Soryo (15 files)",
      "Greater Sibling Relationships (7 files)",
      "Hearths, Hearts, Households (10 files)",
      "Eastern Roman Great Projects (62 files)",
      "East Asian Religions Expanded (37 files)"
    ],
    "idle_since": "2026-02-10T16:24:57",
    "errors_this_run": 0
  }
}
```

### Implementation Notes

- The daemon already writes structured JSONL to `qbuilder_YYYY-MM-DD.jsonl` with timestamps and event types
- The IPC status handler could parse the tail of this log to compute `recent_activity`
- Alternatively, the daemon worker loop could maintain in-memory counters (items processed, first/last timestamps, discovered mods) and expose them via IPC
- The in-memory approach is simpler and avoids log parsing on each status call

### Architecture Note

The daemon is single-threaded for queue processing. The 4 worker pool processes are a multiprocessing pool for CPU-bound parsing **within** each item — they're children of the daemon, not independent queue consumers. When `daemon_state: "idle"`, the pool workers are also idle. The status is accurate; it just lacks historical context.

## Priority

Medium — this is a developer experience / agent usability issue. The daemon works correctly; the reporting just doesn't convey what happened.
