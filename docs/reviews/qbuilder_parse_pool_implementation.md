# QBuilder Persistent Parse Pool Implementation

**Date:** 2026-02-07  
**Status:** In Progress  
**Owner:** Agent session

---

## Problem Statement

QBuilder's process-per-file architecture creates ~115ms overhead per file:
- Spawn overhead: ~93ms
- Parser import: ~22ms
- Actual parse: varies (0.2ms - 30s for pathological files)

For 25K files: **~1 hour just in spawn/import overhead**

### Root Cause Confirmed

Diagnostic script (`scripts/qbuilder_diagnostic.py`) proved:
1. ✅ Import hygiene fix worked (DB not imported in subprocess)
2. ✅ Running correct repo code path
3. ❌ Architecture is the limitation: `subprocess.run()` per file

---

## Solution: Persistent Worker Pool

Replace per-file subprocess spawn with long-lived worker processes that:
- Import parser ONCE at startup
- Process many files via JSON line protocol on stdin/stdout
- Get killed on timeout (preserves isolation)
- Respawn automatically on crash/recycle

### Design Properties

| Requirement | Implementation |
|-------------|----------------|
| Crash isolation | Worker crash doesn't kill daemon; pool respawns |
| Hard timeout | Supervisor kills hung worker after timeout_ms |
| AST output identical | Same parser/serde, just different IPC |
| Memory safety | Workers recycle after 5,000 parses |
| Feature flag | `QBUILDER_PERSISTENT_PARSE=1` to enable |

---

## Files Created

### 1. `src/ck3raven/parser/parse_worker.py` ✅

The worker subprocess entry point:
- Imports parser/serde once at startup
- Sends ready signal `{"ready": true, "pid": ...}`
- Reads JSON requests from stdin
- Writes JSON responses to stdout
- Recycles after `MAX_PARSES_BEFORE_RECYCLE` (5000)

**Request format:**
```json
{"id": "uuid", "path": "/abs/path/to/file.txt", "timeout_ms": 30000}
```

**Response format:**
```json
{"id": "uuid", "ok": true, "ast_json": "...", "node_count": 1234}
```

### 2. `src/ck3raven/parser/parse_pool.py` ✅

The supervisor/pool manager:
- `ParsePool(num_workers=4)` - creates pool
- `pool.start()` - spawns worker processes
- `pool.parse_file(path, timeout_ms)` - routes request to worker
- `pool.shutdown()` - graceful shutdown
- Auto-respawns crashed/recycled workers
- Round-robin load balancing

Global pool API:
- `get_pool()` - lazy singleton
- `shutdown_pool()` - cleanup
- `is_pool_enabled()` - checks `QBUILDER_PERSISTENT_PARSE` env var

### 3. `qbuilder/worker.py` Modified ✅

`_step_parse()` now checks `is_pool_enabled()`:
- If enabled: uses `get_pool().parse_file()`
- If disabled: uses legacy `runtime.parse_file()` (subprocess per file)

---

## Files Created (Diagnostics/Benchmarks)

### `scripts/qbuilder_diagnostic.py` ✅
Proves where time is going:
- Step A: Pure spawn overhead benchmark
- Step B: Per-file timing breakdown (spawn/import/parse/serialize)
- Step C: Code path verification (`__file__` locations)
- Step D: Call graph for `_run_parse_subprocess`

### `scripts/benchmark_parse_pool.py` ⏳
A/B comparison of legacy vs pool:
- Needs fix for schema query (uses mod_packages not vanilla_versions)
- Will output: files/sec, avg ms, p50, p95, projection for 25K/92K files

---

## TODO (Remaining Work)

### 1. Run A/B Benchmark
```bash
python scripts/benchmark_parse_pool.py
```
Expected: Pool should be 5-10x faster than legacy.

### 2. Write Crash/Timeout Resilience Tests

Need to verify:
- [ ] Worker crash → daemon continues, worker respawned
- [ ] Worker timeout (hang) → supervisor kills, job marked as error
- [ ] Multiple concurrent failures → pool stays healthy

### 3. Test in Production

```bash
# Stop existing daemon
python -m qbuilder daemon stop

# Start with pool enabled
QBUILDER_PERSISTENT_PARSE=1 python -m qbuilder daemon start

# Monitor logs
tail -f ~/.ck3raven/logs/qbuilder_*.jsonl
```

### 4. Handle Edge Cases

- [ ] Content mode parsing (text via stdin) - currently falls back to runtime
- [ ] Error recovery parser mode - needs protocol extension
- [ ] Graceful shutdown on SIGINT - pool.shutdown() integration with daemon

---

## Known Issues

### Portrait Files Timeout

Separately from this work, `common/bookmark_portraits/` files cause 4-30s parse times.
**Fixed:** Added to `SKIP_PATTERNS` in `src/ck3raven/db/file_routes.py`

### Schema Mismatch in Benchmarks

Benchmark script assumed `vanilla_versions.install_path` column.
**Fixed:** Query now uses `mod_packages.source_path` (vanilla stored as mod_package).

---

## Rollback Plan

If pool causes issues:
1. Unset `QBUILDER_PERSISTENT_PARSE` env var
2. Restart daemon
3. Falls back to legacy subprocess-per-file

The feature flag makes this zero-risk to deploy.

---

## Expected Improvement

| Metric | Legacy | Pool (Expected) |
|--------|--------|-----------------|
| Spawn overhead | ~93ms | ~0ms (amortized) |
| Import time | ~22ms | ~0ms (done once) |
| Per-file overhead | ~115ms | ~5-10ms (IPC only) |
| 25K files | ~1 hour | ~5-10 minutes |
| 92K files | ~3.5 hours | ~15-30 minutes |

---

## References

- Diagnostic output: Run `python scripts/qbuilder_diagnostic.py`
- Architecture: `docs/CANONICAL_ARCHITECTURE.md`
- Parser runtime: `src/ck3raven/parser/runtime.py`
- QBuilder worker: `qbuilder/worker.py`
