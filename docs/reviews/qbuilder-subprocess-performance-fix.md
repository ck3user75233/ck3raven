# QBuilder Subprocess Performance Fix — Recommended Plan

**Date:** 2026-02-07  
**Based on:** `~/.ck3raven/wip/docs/bugs/bug_qbuilder_subprocess_import_chain.md`  
**Status:** Recommendation only — not yet implemented

---

## Problem Summary

QBuilder performance regressed by **40-85x** due to two compounding issues:

| Issue | Impact | Root Cause |
|-------|--------|------------|
| Import chain bloat | ~5-15s startup per subprocess | `ck3raven/__init__.py` eagerly imports 15,000+ lines when subprocess only needs ~1,650 |
| Subprocess spawn overhead | ~500ms-2s per spawn on Windows | Python interpreter startup cost, spawning 1 process per file |

**Combined effect:** 10,000 files × 10-20s = 28-56 hours instead of ~1 hour.

---

## Recommended Fix Strategy

**Three-phase approach**, implementing in order of urgency:

### Phase 1: Immediate Unblock (Option A) — 30 minutes

**Modify `runtime.py` inline code strings** to pre-stub parent packages and inline the 3 pure functions.

This eliminates the import chain without any architectural changes:
- Pre-populate `sys.modules` with stubs for `ck3raven`, `ck3raven.db`, `ck3raven.resolver`
- Inline `serialize_ast()`, `deserialize_ast()`, `count_ast_nodes()` — these are pure functions using only `json`
- Import ONLY `lexer.py` and `parser.py`

**Expected result:** Per-subprocess time drops from 5-28s to ~1-2s.

**Files to modify:**
- `src/ck3raven/parser/runtime.py` — all three code strings: `_PARSE_FILE_CODE`, `_PARSE_TEXT_CODE`, `_PARSE_TEXT_RECOVERING_CODE`

### Phase 2: Worker Optimization (Option B) — 2-4 hours

**Add persistent subprocess mode for batch workers.**

The subprocess-per-file design is correct for MCP tools (isolation, safety), but wasteful for QBuilder where we process thousands of files in sequence.

**Design:**
```
Worker (single-threaded)              Persistent Parser Subprocess
─────────────────────────             ────────────────────────────
                                      [starts, imports ONCE]
send filepath via stdin ──────────►   parse file
                        ◄──────────   return JSON result via stdout
send filepath via stdin ──────────►   parse file
                        ◄──────────   return JSON result via stdout
[watchdog timer per file]             [crash → restart subprocess]
```

**Why this is superior to direct in-process parsing:**
- Maintains crash isolation (pathological file can't crash worker)
- Import cost paid ONCE at subprocess start
- No Python startup overhead per file
- Watchdog timer still provides timeout protection

**Files to modify:**
- `src/ck3raven/parser/runtime.py` — add `PersistentParseProcess` class
- `qbuilder/worker.py` — use persistent subprocess for batch mode

**Expected result:** Per-file time drops from ~1-2s to ~50-200ms (actual parsing time).

### Phase 3: Architecture Cleanup (Option C) — 1-2 hours

**Fix the root cause: eager imports in `__init__.py` files.**

This is the correct long-term fix that prevents the problem class entirely:

1. **`src/ck3raven/__init__.py`** — Remove all eager imports:
   ```python
   __version__ = "0.1.0"
   # Callers import from submodules directly
   ```

2. **`src/ck3raven/db/__init__.py`** — Same treatment

3. **Update all callers** to use direct imports:
   ```python
   # Before (relies on re-exports):
   from ck3raven.db import serialize_ast
   
   # After (direct):
   from ck3raven.db.ast_cache import serialize_ast
   ```

**Benefits beyond subprocess fix:**
- MCP server startup faster
- CLI commands faster
- Test suite faster
- Prevents future accidental import bloat

---

## Implementation Order

| Phase | Effort | Unblocks | Dependency |
|-------|--------|----------|------------|
| 1 (stub imports) | 30 min | Builds can complete in ~2-3 hours | None |
| 2 (persistent subprocess) | 2-4 hours | Builds complete in ~1 hour | Phase 1 not required |
| 3 (fix __init__.py) | 1-2 hours | Entire codebase faster | None |

**Recommendation:** Do Phase 1 immediately to unblock. Phase 2 and 3 can be done in parallel or sequence.

---

## Verification Plan

### After Phase 1:
```bash
# Time a single subprocess parse
python -c "
import time
start = time.time()
from src.ck3raven.parser.runtime import parse_file
from pathlib import Path
result = parse_file(Path('path/to/small/file.txt'))
print(f'Total: {time.time()-start:.1f}s')
"
# Should be <2s (was 5-28s)
```

### After Phase 2:
```bash
# Run worker with max 100 items
python -m qbuilder daemon --fresh --max-items 100
# Check logs: per-file time should be <500ms average
```

### After Phase 3:
```bash
# Time MCP server startup
python -c "
import time
start = time.time()
import ck3raven
print(f'Import time: {time.time()-start:.3f}s')
"
# Should be <100ms (was potentially seconds)
```

---

## Additional Notes

### Nested Title Extraction

The `symbols.py` changes adding recursive title hierarchy extraction (`_extract_title_hierarchy`) are **not** the primary cause of the slowdown — that only affects `common/landed_titles/` files.

However, this will need optimization via a custom extractor:
- CK3 has ~5000+ titles (e_→k_→d_→c_→b_ hierarchy)
- Current implementation recursively walks all nested blocks
- Consider: batch extraction, depth limits, or skip intermediate levels

### Content Hash Dedup

Files that hit the content-hash dedup in `_step_parse()` complete in ~300ms because they **never spawn a subprocess**. This confirms the subprocess is the bottleneck.

---

## References

- Bug analysis: `~/.ck3raven/wip/docs/bugs/bug_qbuilder_subprocess_import_chain.md`
- `runtime.py` subprocess design: introduced 2026-01-11 (commits `8ee9d2c`, `5436bf5`, `0232963`)
- QBuilder worker: `qbuilder/worker.py`
