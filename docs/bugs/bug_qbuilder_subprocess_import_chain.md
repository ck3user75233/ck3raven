# BUG: QBuilder Subprocess Import Chain Causes 10x+ Build Regression

**Filed**: 2026-02-07  
**Severity**: Critical (blocks all builds)  
**Component**: `src/ck3raven/parser/runtime.py`, `src/ck3raven/__init__.py`, `src/ck3raven/db/__init__.py`  
**Status**: Open  

---

## Summary

QBuilder parse builds have regressed from ~1 hour to 11+ hours (estimated). The root cause is a **transitive import explosion** in `ck3raven/__init__.py` and `ck3raven/db/__init__.py` that forces each subprocess spawned by `runtime.py` to import ~15,000+ lines of code across 20+ modules — when only ~1,650 lines are actually needed.

Every subprocess that runs `from ck3raven.parser.parser import parse_file` triggers Python's package initialization chain, which eagerly loads the entire database layer, resolver layer, and all their dependencies. This turns a <100ms parse operation into a 4-28 second ordeal, and causes trivial vanilla files to **timeout at 30 seconds** before the subprocess even finishes importing.

---

## Symptoms

1. **Parse times**: 4-28 seconds per file for actual subprocess launches (should be <1s)
2. **Timeout errors**: 40 files hit `ParseTimeoutError: Parse timeout after 30s` on trivial vanilla files like `00_accolade_icons.txt`, `coronation.txt`, `feast_grand_activity.txt`
3. **Build ETA**: ~10,466 E_SCRIPT items × ~15s average = ~43 hours (vs ~1 hour previously)
4. **E_LOC stubs**: 12,627 E_LOC items enqueued but both pipeline steps (`parse_loc`, `extract_loc_entries`) are stubs that do nothing (`pass`)
5. **Minimal dedup benefit**: 10,425 unique content hashes out of 10,466 items — only ~41 dedup hits

---

## Root Cause Analysis

### The Import Chain

When `runtime.py` spawns a subprocess, it executes inline Python code that does:

```python
from ck3raven.parser.parser import parse_file
from ck3raven.db.ast_cache import serialize_ast, count_ast_nodes
```

This looks innocent, but Python's import system must initialize the `ck3raven` package first, which triggers:

```
subprocess starts
  └─ import ck3raven               ← __init__.py runs
       ├─ from ck3raven.parser import parse_file, parse_source
       │    └─ ck3raven/parser/__init__.py → imports parser.py (1,088 lines)
       │         └─ imports lexer.py (527 lines) ← ACTUALLY NEEDED
       │
       ├─ from ck3raven.resolver import MergePolicy, CONTENT_TYPES  ← NOT NEEDED
       │    └─ ck3raven/resolver/__init__.py (98 lines)
       │         ├─ sql_resolver.py
       │         ├─ resolver.py
       │         ├─ policies.py
       │         └─ content_types.py
       │
       └─ from ck3raven.db import init_database  ← NOT NEEDED, CATASTROPHIC
            └─ ck3raven/db/__init__.py (175 lines)
                 ├─ schema.py (1,015 lines) — 44 CREATE TABLE statements
                 ├─ models.py (374 lines) — dataclasses
                 ├─ content.py (~300 lines)
                 ├─ parser_version.py (188 lines) — includes subprocess call to git!
                 ├─ ast_cache.py (335 lines) ← ACTUALLY NEEDED (3 functions)
                 ├─ symbols.py (~500 lines)
                 ├─ search.py (436 lines) — FTS5
                 └─ cryo.py (443 lines) — snapshot system
```

### What's Actually Needed

The subprocess only uses **3 pure functions** from `ast_cache.py`:
- `serialize_ast(ast_dict)` → JSON string  
- `deserialize_ast(json_str)` → dict  
- `count_ast_nodes(ast_dict)` → int  

These functions use only the `json` standard library module. Total code actually needed:

| Module | Lines | Purpose |
|--------|-------|---------|
| `lexer.py` | 527 | Tokenizer |
| `parser.py` | 1,088 | Recursive descent parser |
| `json` (stdlib) | 0 | Already loaded |
| **Total needed** | **~1,650** | |
| **Total loaded** | **~15,000+** | ~9x overhead |

### Why This Kills Performance

Each of the ~10,466 E_SCRIPT items spawns a fresh subprocess that must:
1. Start Python interpreter (~200ms)
2. Import `ck3raven` package → loads ~15,000+ lines (~3-25s depending on disk/CPU)
3. Actually parse the CK3 file (~10-100ms)
4. Serialize result and exit

Steps 1-2 dominate. The actual parse (step 3) is negligible. Files that should parse in under 100ms are instead timing out at 30 seconds because the import chain hasn't finished.

---

## Evidence from Build Queue Data

### Completion Times (33 completed items)

| Time Range | Count | Explanation |
|-----------|-------|-------------|
| 0.2-0.4s | ~5 | Content dedup hits (no subprocess spawned) |
| 4-8s | ~10 | Subprocess completed, light import chain |
| 10-20s | ~12 | Subprocess completed, full import chain |
| 20-28s | ~6 | Subprocess barely made it under timeout |

### Error Analysis (40 errors — ALL timeouts)

All 40 errors have the same pattern:
```
ParseTimeoutError: Parse timeout after 30s
```

Sample files that timeout (all trivial vanilla files):
- `common/accolade/00_accolade_icons.txt`
- `events/activities/feast/feast_grand_activity.txt`
- `events/activities/hold_court/coronation.txt`
- `common/ai_war_stances/00_ai_war_stances.txt`
- `events/dlc/ep3/ep3_tour_events.txt`

These files are small and parse in <100ms when the parser is already loaded. They timeout because the subprocess can't even finish its import chain in 30 seconds.

### Queue Distribution

| Envelope | Status | Count |
|----------|--------|-------|
| E_SCRIPT | pending | 10,050 |
| E_SCRIPT | completed | 33 |
| E_SCRIPT | error | 40 |
| E_LOC | pending | 12,627 |
| E_LOOKUP_CHARACTER | pending | 140 |
| E_LOOKUP_PROVINCE | pending | 135 |
| E_LOOKUP_TITLE | pending | 133 |
| E_LOOKUP_DYNASTY | pending | 96 |
| E_LOOKUP_FAITH | pending | 75 |
| E_LOOKUP_CULTURE | pending | 20 |

---

## Recommended Fix

### Option A: Inline Pure Functions + Stub sys.modules (Quick Fix, ~30 min)

Modify `runtime.py` to bypass the `__init__.py` import chain entirely by pre-stubbing `sys.modules` and inlining the 3 needed functions.

**Modified `_PARSE_FILE_CODE` in `runtime.py`:**

```python
_PARSE_FILE_CODE = '''
import sys
import types
import json

# Stub the top-level package to prevent __init__.py from running
ck3raven_stub = types.ModuleType('ck3raven')
ck3raven_stub.__path__ = []  # Make it a package
sys.modules['ck3raven'] = ck3raven_stub

# Stub ck3raven.db so ast_cache import doesn't trigger db/__init__.py
db_stub = types.ModuleType('ck3raven.db')
sys.modules['ck3raven.db'] = db_stub

# Stub ck3raven.db.schema and ck3raven.db.models (ast_cache imports them at module level)
schema_stub = types.ModuleType('ck3raven.db.schema')
sys.modules['ck3raven.db.schema'] = schema_stub
models_stub = types.ModuleType('ck3raven.db.models')
sys.modules['ck3raven.db.models'] = models_stub

# Now the actual imports we need will resolve cleanly
from ck3raven.parser.parser import parse_file

# Inline the 3 pure functions instead of importing from ast_cache
def serialize_ast(ast_dict):
    return json.dumps(ast_dict, separators=(",", ":"))

def count_ast_nodes(node):
    if isinstance(node, dict):
        count = 1
        for v in node.values():
            count += count_ast_nodes(v)
        return count
    elif isinstance(node, list):
        return sum(count_ast_nodes(item) for item in node)
    return 0

# ... rest of parse logic unchanged ...
'''
```

**Pros**: Minimal change, immediately unblocks builds  
**Cons**: Fragile — breaks if ast_cache module-level imports change  

### Option B: Persistent Worker Subprocess (Better, 2-4 hours)

Replace spawn-per-file with a long-lived worker process that communicates via stdin/stdout JSON protocol. Import once, parse many.

```python
# Worker subprocess reads parse requests from stdin, writes results to stdout
import sys
import json
from ck3raven.parser.parser import parse_file
from ck3raven.db.ast_cache import serialize_ast, count_ast_nodes

for line in sys.stdin:
    request = json.loads(line)
    filepath = request['filepath']
    result = parse_file(filepath)
    ast_json = serialize_ast(result.ast) if result.ast else None
    node_count = count_ast_nodes(result.ast) if result.ast else 0
    response = {
        'filepath': filepath,
        'ast': ast_json,
        'node_count': node_count,
        'errors': [str(e) for e in result.errors]
    }
    sys.stdout.write(json.dumps(response) + '\n')
    sys.stdout.flush()
```

**Pros**: Import cost paid once, throughput limited only by parse speed  
**Cons**: More complex error handling, need to manage worker lifecycle  

### Option C: Fix `__init__.py` Lazy Loading (Correct, ~1 hour)

Make `ck3raven/__init__.py` and `ck3raven/db/__init__.py` use lazy imports so they don't load the world on package initialization.

**`ck3raven/__init__.py` (before):**
```python
from ck3raven.parser import parse_file, parse_source
from ck3raven.resolver import MergePolicy, CONTENT_TYPES
from ck3raven.db import init_database
```

**`ck3raven/__init__.py` (after):**
```python
def __getattr__(name):
    if name == 'parse_file':
        from ck3raven.parser import parse_file
        return parse_file
    elif name == 'parse_source':
        from ck3raven.parser import parse_source
        return parse_source
    elif name == 'MergePolicy':
        from ck3raven.resolver import MergePolicy
        return MergePolicy
    elif name == 'CONTENT_TYPES':
        from ck3raven.resolver import CONTENT_TYPES
        return CONTENT_TYPES
    elif name == 'init_database':
        from ck3raven.db import init_database
        return init_database
    raise AttributeError(f"module 'ck3raven' has no attribute {name}")
```

Similarly, `ck3raven/db/__init__.py` should lazy-load its submodules.

**Pros**: Fixes the root cause, benefits everything (not just subprocess)  
**Cons**: Need to audit all import patterns to ensure nothing breaks  

### Recommendation

**Do Option A first** (unblocks builds in 30 minutes), then **Option C as follow-up** (correct fix for the codebase). Option B is worth considering for the future but is a larger architectural change.

---

## Files to Modify

| File | Change |
|------|--------|
| `src/ck3raven/parser/runtime.py` | Stub sys.modules in inline code strings (Option A) |
| `src/ck3raven/__init__.py` | Lazy loading via `__getattr__` (Option C) |
| `src/ck3raven/db/__init__.py` | Lazy loading via `__getattr__` (Option C) |
| `src/ck3raven/resolver/__init__.py` | Lazy loading via `__getattr__` (Option C) |

---

## How to Verify

1. **Before fix**: Time a single subprocess parse:
   ```bash
   time python -c "from ck3raven.parser.parser import parse_file; print(parse_file('test.txt'))"
   ```
   Expected: 4-28 seconds

2. **After fix (Option A)**: Run the modified inline code:
   ```bash
   time python -c "<modified_inline_code>"
   ```
   Expected: <1 second

3. **Full build test**: Run `qbuilder daemon --fresh` and monitor completion times in the build queue. All files should complete in <2 seconds.

---

## Related Issues

1. **Discovery trigger bug**: Playset switch doesn't call `enqueue_playset_roots()` — discovery only happens with `--fresh` flag. Separate fix needed in `qbuilder/cli.py`.

2. **E_LOC stubs**: 12,627 localization items are enqueued but both pipeline steps (`parse_loc`, `extract_loc_entries` in `worker.py`) are stubs that just `pass`. These items waste queue space and discovery time. Either implement them or add E_LOC to the skip list.

3. **Content dedup low hit rate**: Only 41 dedup hits out of 10,466 items (0.4%). This is expected for a full build but suggests dedup is not the bottleneck — import overhead is.

---

## Appendix: Import Chain Visualization

```
subprocess.run([python, "-c", inline_code])
│
├─ Python starts (~200ms)
│
├─ "from ck3raven.parser.parser import parse_file"
│   │
│   ├─ Python: "ck3raven" not in sys.modules, load it
│   │   └─ exec ck3raven/__init__.py
│   │       ├─ from ck3raven.parser import ...     ← NEEDED (1,615 lines)
│   │       ├─ from ck3raven.resolver import ...   ← NOT NEEDED (~800 lines)
│   │       └─ from ck3raven.db import ...         ← NOT NEEDED (~4,000+ lines)
│   │           └─ exec ck3raven/db/__init__.py
│   │               ├─ import schema     (1,015 lines)
│   │               ├─ import models     (374 lines)
│   │               ├─ import content    (~300 lines)
│   │               ├─ import parser_version (188 lines, calls git!)
│   │               ├─ import ast_cache  (335 lines) ← only need 3 functions
│   │               ├─ import symbols    (~500 lines)
│   │               ├─ import search     (436 lines)
│   │               └─ import cryo       (443 lines)
│   │
│   └─ Finally: parser.py loaded (1,088 lines)
│
├─ Actual parse: ~10-100ms  ← THE ONLY USEFUL WORK
│
└─ Exit
```

**Total time budget**: 30,000ms timeout  
**Time spent importing**: 4,000-28,000ms  
**Time spent parsing**: 10-100ms  
**Import-to-parse ratio**: 40x-280x overhead
