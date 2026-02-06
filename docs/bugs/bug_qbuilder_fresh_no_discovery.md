# Bug Report: QBuilder --fresh Does Not Enqueue Discovery

**Severity:** Critical  
**Component:** qbuilder/cli.py  
**Date:** 2026-02-06

---

## Summary

When running `python -m qbuilder daemon --fresh`, the daemon resets all data but **never enqueues discovery tasks for the active playset**. This leaves the worker idle forever with 0 pending items.

## Symptoms

```
$ python -m qbuilder daemon --fresh

[OK] Data reset complete
[OK] IPC server listening on port 19876

=== Daemon Started ===
  run_id: daemon-50dec89f
  pending: 0                    # <-- Should be >0 after fresh reset
  
[Worker] Waiting for work... (0 processed, idle for 5s)
[Worker] Waiting for work... (0 processed, idle for 65s)  # Forever
```

## Root Cause

In `qbuilder/cli.py`, the `cmd_daemon` function with `--fresh` flag:

1. ✅ Resets all data tables (files, asts, symbols, etc.)
2. ✅ Resets qbuilder queue tables (discovery_queue, build_queue)
3. ❌ **Does NOT call `enqueue_playset_roots()` to queue discovery tasks**

The daemon then checks `discovery_pending > 0` (around line 226), and since it's 0, no discovery happens.

## Recommended Fix

After the fresh reset block (around line 190), add a call to enqueue discovery:

```python
# After reset_qbuilder_tables(conn) and print("[OK] Data reset complete"):
playset_path = get_active_playset_file()
if playset_path and playset_path.exists():
    print(f"Enqueuing discovery from {playset_path.name}...")
    discovery_count = enqueue_playset_roots(conn, playset_path)
    print(f"[OK] Enqueued {discovery_count} discovery tasks")
else:
    print("[WARN] No active playset found - daemon will wait for work")
```

## Expected Behavior After Fix

```
$ python -m qbuilder daemon --fresh

Resetting all data for fresh build...
[OK] Data reset complete
Enqueuing discovery from playset_MSC_Religion.json...
[OK] Enqueued 45 discovery tasks
[OK] IPC server listening on port 19876

=== Daemon Started ===
  pending: 45
  
Processing 45 discovery tasks...
```

## Related Code

- `qbuilder/discovery.py`: Contains `enqueue_playset_roots()` function
- `qbuilder/ipc_server.py`: `_handle_enqueue_scan()` correctly calls enqueue - this is the pattern to follow

## Testing

1. Run `python -m qbuilder daemon --fresh`
2. Verify discovery is enqueued (>0 discovery tasks message)
3. Verify build queue populates after discovery runs
4. Verify worker processes items
