# QBuilder Performance Fix — Stepwise Implementation Plan

**Date**: 2026-02-07  
**Prerequisite**: [bug_qbuilder_subprocess_import_chain.md](bug_qbuilder_subprocess_import_chain.md)  
**Approach**: Each step is independently benchmarkable. Execute one step, measure, then proceed.

---

## Problem Recap

QBuilder subprocess parsing regressed from ~1 hour (full playset build) to 11+ hours.  
Root cause: Each per-file subprocess imports the entire `ck3raven` package (~15,000+ lines) when only the parser (~1,650 lines) is needed. Additionally, `parser_version.py` runs `git rev-parse HEAD` at module-level import time, adding a shell call to every subprocess.

40/40 build errors are `ParseTimeoutError: Parse timeout after 30s` on trivial vanilla files.

---

## Baseline Benchmark (Do This First)

Before any changes, capture current performance metrics:

```
Metric: subprocess_parse_time
Method: Time 10 representative files (small, medium, large) through _run_parse_subprocess()
Current expected: 4–28s per file, 30s timeout on many

Metric: import_chain_time  
Method: python -c "import time; t=time.time(); import ck3raven; print(f'{time.time()-t:.3f}s')"
Current expected: Several seconds (imports ~15,000 lines + git subprocess)

Metric: full_build_time
Method: Time qbuilder daemon on full playset (92,608 files)
Current expected: 11+ hours (many timeouts)
```

Save results to `docs/benchmarks/qbuilder_baseline_YYYYMMDD.md`.

---

## Step 1: Sanitize `__init__.py` Import Chains

**Goal**: Reduce subprocess import overhead from ~15,000 lines to ~1,650 lines.

### What to Change

#### `src/ck3raven/__init__.py`
**Current** (approximate — imports db, resolver, parser eagerly):
```python
from .db import ...          # ~4,000 lines (8+ submodules)
from .resolver import ...    # ~800 lines
from .parser import ...      # ~1,650 lines (needed)
```

**Target**: Remove all eager imports. Use lazy loading or remove entirely:
```python
# src/ck3raven/__init__.py
# Metadata only — no eager imports
__version__ = "0.1.0"

# Consumers import directly:
#   from ck3raven.parser import Lexer, Parser
#   from ck3raven.db import Database
```

#### `src/ck3raven/db/__init__.py`
**Current**: Eagerly imports all 8+ database submodules (~4,000 lines total).

**Target**: Either remove the barrel exports or replace with `__getattr__` lazy loading:
```python
def __getattr__(name):
    if name == "Database":
        from .database import Database
        return Database
    # ... etc
    raise AttributeError(f"module 'ck3raven.db' has no attribute {name}")
```

### Verification

Run the same 3 benchmarks from baseline:

| Metric | Baseline | After Step 1 | Expected |
|--------|----------|--------------|----------|
| subprocess_parse_time (10 files avg) | 4–28s | ? | < 2s |
| import_chain_time | Several seconds | ? | < 0.5s |
| full_build_time (est.) | 11+ hrs | ? | < 2 hrs |

**Success gate**: subprocess parse time for trivial files drops below 2 seconds.  
**Failure gate**: If any existing `from ck3raven import X` breaks, fix each call site to use direct imports.

### Risk Assessment

- **Risk**: Other code relies on barrel imports from `ck3raven.__init__`
- **Mitigation**: Grep for `from ck3raven import` and `import ck3raven.` across the entire codebase. Update each call site to import from the specific submodule.
- **Risk**: `ck3raven.db.__init__` barrel is used widely
- **Mitigation**: Same grep approach. The db barrel likely has more consumers — prioritize lazy `__getattr__` over removal.

---

## Step 2: Extract Pure Parser Functions to `parser/ast_serde.py`

**Goal**: Ensure the subprocess inline code (`_PARSE_FILE_CODE`, `_PARSE_TEXT_CODE`, etc.) only needs `lexer.py` + `parser.py` — no utility imports that pull in heavy dependencies.

### What to Change

#### Identify cross-imports in `runtime.py`
The inline code strings in `runtime.py` use:
- `from ck3raven.parser.lexer import Lexer`
- `from ck3raven.parser.parser import Parser`
- Possibly `from ck3raven.parser import ...` (which triggers `parser/__init__.py`)

**Check**: Does `src/ck3raven/parser/__init__.py` have eager imports of heavy modules?

#### Create `src/ck3raven/parser/ast_serde.py`
Move any pure serialization/deserialization functions (AST → JSON, JSON → AST) that are currently tangled in modules with heavy dependencies:

```python
# ast_serde.py — zero heavy imports
# Only: json, typing, dataclasses from stdlib
# Plus: ast_nodes.py (lightweight data definitions)

def ast_to_dict(node) -> dict: ...
def dict_to_ast(data) -> ASTNode: ...
```

#### Update `runtime.py` subprocess inline code
Ensure inline code imports only from:
- `ck3raven.parser.lexer` (527 lines)  
- `ck3raven.parser.parser` (1,088 lines)
- `ck3raven.parser.ast_serde` (new, lightweight)
- stdlib

### Verification

| Metric | After Step 1 | After Step 2 | Expected |
|--------|--------------|--------------|----------|
| subprocess_parse_time (10 files avg) | ? | ? | ≤ Step 1 (no regression) |
| import_chain_time (subprocess) | ? | ? | Stable or improved |

**AST stability test**: Parse 100 files before and after. Compare JSON-serialized ASTs byte-for-byte. Zero differences = pass.

**Success gate**: No AST regressions, import time does not increase.

---

## Step 3: Fix `parser_version.py` Git Call

**Goal**: Eliminate the `git rev-parse HEAD` subprocess that runs on every import of `parser_version.py`.

### What to Change

#### `src/ck3raven/parser/parser_version.py`

**Current** (approximate):
```python
import subprocess

def get_parser_version():
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip()

PARSER_VERSION = get_parser_version()  # Runs at import time!
```

**Target**: Lazy evaluation with caching:
```python
import functools

@functools.cache
def get_parser_version() -> str:
    """Returns git HEAD hash, cached after first call."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"

# NO module-level execution
# Consumers call get_parser_version() when needed
```

**Also**: Remove `PARSER_VERSION = get_parser_version()` or replace with a property/descriptor that calls lazily.

### Verification

| Metric | After Step 2 | After Step 3 | Expected |
|--------|--------------|--------------|----------|
| subprocess_parse_time (10 files avg) | ? | ? | ~50–200ms faster if git was in import path |
| import_chain_time (subprocess) | ? | ? | ~50–200ms faster |

**Success gate**: `python -c "import time; t=time.time(); from ck3raven.parser import Lexer, Parser; print(f'{time.time()-t:.3f}s')"` completes in < 0.3s.

---

## Phase 2 (Future): Persistent Worker Pool

**Not part of this immediate plan** — saved for after Steps 1-3 are verified.

### Concept
Replace per-file subprocess spawning with a persistent worker pool that keeps the parser imported:

```
QBuilder Daemon
  └── Worker Pool (N processes)
       ├── Worker 1: Lexer+Parser already loaded, waiting for file
       ├── Worker 2: Lexer+Parser already loaded, waiting for file
       └── Worker N: ...
```

### Why Defer
- Steps 1-3 should reduce subprocess time from 4-28s to < 1s
- At < 1s per file with 92,608 files, full build = ~25 hours single-threaded
- A 4-worker pool would bring this to ~6 hours
- **But**: If subprocess overhead drops to ~200ms, the current approach may be adequate with the 30s timeout
- Benchmark after Step 3 to decide if persistent workers are needed

### Design Considerations
- Workers must be crash-isolated (one bad file shouldn't kill the pool)
- Memory leaks from keeping parsers alive across thousands of files
- Process recycling after N parses to bound memory growth
- IPC overhead (passing file content + receiving AST) vs subprocess startup cost

---

## Execution Checklist

```
[ ] Baseline benchmark captured
[ ] Step 1: Sanitize __init__.py
    [ ] Grep all import sites
    [ ] Modify ck3raven/__init__.py
    [ ] Modify ck3raven/db/__init__.py
    [ ] Fix broken import sites
    [ ] Run tests
    [ ] Benchmark → compare to baseline
    [ ] Document results in docs/benchmarks/
[ ] Step 2: Extract ast_serde.py
    [ ] Audit parser/__init__.py imports
    [ ] Create ast_serde.py
    [ ] Update runtime.py inline code
    [ ] AST stability test (100 files)
    [ ] Benchmark → compare to Step 1
    [ ] Document results
[ ] Step 3: Fix parser_version.py
    [ ] Make git call lazy
    [ ] Remove module-level execution
    [ ] Benchmark → compare to Step 2
    [ ] Document results
[ ] Decision gate: Is Phase 2 (persistent workers) needed?
    [ ] If subprocess time < 500ms → probably not
    [ ] If subprocess time > 1s → design worker pool
```

---

## File Locations

| File | Purpose | Approximate Size |
|------|---------|-----------------|
| `src/ck3raven/__init__.py` | Root package barrel imports | 35 lines |
| `src/ck3raven/db/__init__.py` | Database barrel imports | 175 lines |
| `src/ck3raven/parser/__init__.py` | Parser barrel imports | ~20-30 lines (verify) |
| `src/ck3raven/parser/runtime.py` | Subprocess launching + inline code | 358 lines |
| `src/ck3raven/parser/parser_version.py` | Git call at import time | ~20-30 lines (verify) |
| `src/ck3raven/parser/lexer.py` | The lexer (NEEDED in subprocess) | 527 lines |
| `src/ck3raven/parser/parser.py` | The parser (NEEDED in subprocess) | 1,088 lines |
