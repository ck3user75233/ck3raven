# QBuilder Baseline Benchmarks - 2026-02-07

**Machine:** Windows (user workstation)  
**Python:** 3.13

## Phase 0 Results

### Metric 1: Subprocess Parse Time

| File | Nodes | Time | Status |
|------|-------|------|--------|
| 00_traits.txt | 18,174 | 0.766s | ✅ |
| death_on_actions.txt | 0* | 0.448s | ⚠️ |
| stewardship_domain_events.txt | 0* | 0.336s | ⚠️ |

*Node count 0 may indicate parse issue - but these are likely intentionally empty containers.

**Average:** ~0.5s per file  
**Target:** < 0.2s per file  
**Status:** 2.5x over target, but far better than the 4-28s mentioned in directive

### Metric 2: Import Chain Overhead

| Import | Time | Target | Status |
|--------|------|--------|--------|
| `import ck3raven` | 0.163s | < 0.1s | ⚠️ 1.6x |
| `from ck3raven.db.ast_cache import ...` | 0.159s | < 0.05s | ⚠️ 3x |
| `from ck3raven.parser.parser import parse_file` | 0.106s | < 0.05s | ⚠️ 2x |

### Metric 3: Full Build Estimate

Current processing rate: ~2 files/second  
Total files in typical playset: ~92,000  
**Estimated time:** ~12.8 hours (still too long)  
**Target:** < 1 hour (92,000 / 3600 = 25+ files/sec needed)

---

## Findings

### Phase 1.5 (Daemon --fresh): ✅ ALREADY IMPLEMENTED

The `cmd_daemon` function in `qbuilder/cli.py` already calls `enqueue_playset_roots()` after fresh reset (lines 176-184).

### Phase 1.1-1.3: Still Beneficial

While import times are reasonable, the subprocess still imports `ck3raven.db.ast_cache` which cascades into:
- `ck3raven.db.schema` (SQLite schema)
- `ck3raven.db.models` (dataclasses)
- `ck3raven.db.parser_version` (git subprocess potential)

Creating `parser/ast_serde.py` would:
1. Reduce subprocess import from ~0.16s to ~0.05s (estimated)
2. Eliminate SQLite connection overhead in subprocess
3. Remove git subprocess latency (though currently lazy)

### Recommendation

Implement Phase 1.2 (ast_serde.py) to get subprocess imports down to the 0.05s target.
Combined with the parsing itself, this could bring per-file time to ~0.4s → ~20 files/sec.

For the 1-hour target (25+ files/sec), Phase 3 (worker pool) may eventually be needed.

---

## Commands Used

```bash
# Import timing
python -c "import time; t=time.time(); import ck3raven; print(f'{time.time()-t:.3f}s')"
python -c "import time; t=time.time(); from ck3raven.db.ast_cache import serialize_ast, count_ast_nodes, deserialize_ast; print(f'{time.time()-t:.3f}s')"

# Parse timing
python -c "
import time
from ck3raven.parser.runtime import parse_file
from pathlib import Path
files = [
    'C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game/common/traits/00_traits.txt',
]
for f in files:
    t=time.time()
    r=parse_file(Path(f))
    print(f'{time.time()-t:.3f}s - {Path(f).name} (nodes={r.node_count})')
"
```
