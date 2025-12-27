# TEMPORARY: Builder Status Investigation

> **Created:** December 27, 2025  
> **Status:** TEMPORARY - Delete after issue resolved  
> **Purpose:** Document builder failure investigation

---

## Current Situation

The builder appears to be in a "running" state but may have stalled or been interrupted.

### Database Status

```
files_indexed: 56,466
symbols_extracted: 65,099
refs_extracted: 0  ← No references extracted
needs_rebuild: true
rebuild_reason: "Build still in progress or was interrupted"
```

---

## Builder Runs History

| Build ID | Started | State | Error |
|----------|---------|-------|-------|
| `53b66f90...` | 2025-12-27 19:41 | **running** | None |
| `d496b3d0...` | 2025-12-26 21:37 | running (stale) | None |
| `049b67e3...` | 2025-12-26 21:08 | **failed** | `ModuleNotFoundError: No module named 'yaml'` |
| `83c448d4...` | 2025-12-26 16:01 | running (stale) | None |
| `5e39c741...` | 2025-12-26 09:38 | running (stale) | None |

**Multiple "running" builds** - indicates builds were started but not completed. Process may have been killed or hung.

---

## Current Build Progress (Build `53b66f90...`)

| Step | Started | Completed | Duration | State | Output |
|------|---------|-----------|----------|-------|--------|
| 1. vanilla_ingest | 19:41:15 | 19:45:42 | 4.5 min | ✅ complete | 13,670 rows |
| 2. mod_ingest | 19:45:42 | 19:46:22 | 39 sec | ✅ complete | 0 rows |
| 3. ast_generation | 19:46:22 | 20:12:48 | 26.4 min | ✅ complete | 3,149 out, 9,325 skipped, 14 errored |
| 4. symbol_extraction | 20:12:50 | NULL | NULL | **running** | 0 rows |
| 5. ref_extraction | Not started | - | - | pending | - |

**Symbol extraction appears stuck** - started at 20:12:50 but no completion recorded.

---

## Earliest Build That Got Furthest (Build `5e39c741...`)

This build from Dec 26 got the furthest:

| Step | Duration | State | Output |
|------|----------|-------|--------|
| 1. vanilla_ingest | 5.6 min | ✅ complete | 13,670 rows |
| 2. mod_ingest | 15.2 min | ✅ complete | - |
| 3. ast_generation | 84.5 min | ✅ complete | 12,051 out, 18,577 skipped, 105 errored |
| 4. symbol_extraction | 106.7 min | ✅ complete | 0 rows out (but 65,099 symbols exist in DB) |
| 5. ref_extraction | Started 13:11:17 | **running** (stale) | 0 rows |

**Ref extraction started but never completed** - process likely killed.

---

## Investigation Steps Needed

1. **Run builder in debug mode** to see real-time progress and where it hangs
2. **Check file routing table** to see what processing steps are required per file type
3. **Check if ref_extraction is needed** or if it's optional/not yet implemented
4. **Clean up stale build runs** - mark old "running" builds as failed

---

## Recommended Debug Command

```bash
cd c:\Users\nateb\Documents\CK3 Mod Project 1.18\ck3raven
python builder/daemon.py start --debug
```

Or for specific steps:

```bash
python builder/daemon.py start --symbols-only --debug
python builder/daemon.py start --refs-only --debug
```

---

## Questions to Answer

1. Is ref_extraction implemented? Or is it a placeholder step?
2. What's in the file routing table that determines which files need which processing?
3. Why does symbol_extraction show 0 rows_out when 65,099 symbols exist in DB?
4. Is there a timeout or resource exhaustion causing the hangs?

---

## Cleanup

After investigation, clean up stale runs:

```sql
UPDATE builder_runs SET state = 'failed', error_message = 'Marked stale - process died'
WHERE state = 'running' AND started_at < datetime('now', '-1 day');

UPDATE builder_steps SET state = 'failed', error_message = 'Parent build failed'
WHERE state = 'running' AND started_at < datetime('now', '-1 day');
```
