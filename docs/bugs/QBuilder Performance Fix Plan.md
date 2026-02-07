Here is the updated diagnosis and implementation plan. It incorporates the feedback to prioritize architectural correctness (sanitizing imports) as the immediate fix, while positioning the persistent worker model as the secondary scalability phase.

# ---

**BUG: QBuilder Subprocess Import Chain Causes 40-85x Performance Regression**

**Date:** 2026-02-07

**Severity:** Critical — build pipeline effectively broken

**Component:** src/ck3raven/parser/runtime.py, src/ck3raven/\_\_init\_\_.py, src/ck3raven/db/\_\_init\_\_.py

**Introduced:** Jan 11, 2026 (commits 8ee9d2c, 5436bf5, 0232963\)

**Status:** **Implementation Plan Approved**

## ---

**Summary**

Every file parsed by QBuilder spawns a subprocess that imports the **entire ck3raven framework** (\~15,000+ lines across 20+ modules) just to run 3 pure functions that only need json.

This causes 4-28 second startup overhead **per file**, turning a \~1 hour build into an 11-25+ hour build. Files that don't finish importing within 30 seconds are killed by the timeout and marked as permanent errors.

**The "Hidden Killer":** It was identified that parser\_version.py executes git rev-parse HEAD at module-level import time. In a subprocess environment (especially on Windows), this adds massive latency and failure potential before a single line of Python is executed.

## ---

**Symptoms**

1. **Build takes 11+ hours** instead of \~1 hour.  
2. **40 out of 73 processed files failed** with ParseTimeoutError: Parse timeout after 30s.  
3. Failed files are **trivial vanilla files** like 00\_accolade\_icons.txt, coronation.txt, feast.txt — files that should parse in milliseconds.  
4. **CPU Usage:** Low/Spiky. The system spends most of its time initializing Python interpreters and waiting on IO/Git, not parsing.  
5. **Deduplication Hits are Fast:** Files that hit the deduplication check (and skip the subprocess) finish instantly, confirming the bottleneck is the subprocess lifecycle.

## ---

**Diagnosis: The Import Chain Explosion**

When runtime.py spawns a subprocess, it executes a script that imports:

from ck3raven.db.ast\_cache import serialize\_ast, count\_ast\_nodes

Because of how \_\_init\_\_.py files are currently structured, this triggers a catastrophic cascade:

Subprocess starts  
└── from ck3raven.db.ast\_cache import ...  
    └── import ck3raven                          ← \_\_init\_\_.py runs eager imports  
        ├── from ck3raven.parser import ...      ← OK  
        ├── from ck3raven.resolver import ...    ← UNNECESSARY OVERHEAD  
        └── from ck3raven.db import ...          ← THE PERFORMANCE KILLER  
            ├── db/schema.py        (SQLAlchemy schema init)  
            ├── db/models.py        (ORM Model registry)  
            ├── db/content.py       (Hashlib, Pathlib scanning)  
            ├── db/parser\_version.py (EXECUTES \`git rev-parse\` ON IMPORT)  
            ├── db/symbols.py       (Complex extraction logic)  
            ├── db/search.py        (FTS5 infrastructure)  
            └── ... 

We are loading the entire database layer, SQL schema, and running git commands just to serialize a JSON object.

## ---

**Implementation Plan**

### **Primary Instruction: Fix Imports & Decouple (Immediate Mandatory Action)**

This is the "Correct Fix." We must stop lying to the import system and instead fix the architectural coupling. This restores correctness and will improve performance across the entire application (CLI, MCP Server, Tests), not just QBuilder.

**Step 1: Sanitize \_\_init\_\_.py files**

* **Action:** Audit ck3raven/\_\_init\_\_.py, ck3raven/db/\_\_init\_\_.py, and ck3raven/resolver/\_\_init\_\_.py.  
* **Rule:** Remove all eager imports. These files should be empty or strictly limited to version metadata.  
* **Result:** Importing ck3raven.parser should no longer trigger an import of ck3raven.db or ck3raven.resolver.

**Step 2: Isolate Pure Functions (The ast\_serde pattern)**

* **Problem:** Currently, serialize\_ast and count\_ast\_nodes live in db/ast\_cache.py, which is inextricably linked to the database stack.  
* **Action:** Move these three pure functions (serialize\_ast, deserialize\_ast, count\_ast\_nodes) into a new, dependency-free module: src/ck3raven/parser/ast\_serde.py (or common/ast\_serde.py).  
* **Constraint:** This new module must **only** import json and the AST node definitions. It must **never** import ck3raven.db.  
* **Update:** Update the subprocess code in runtime.py to import from this new location.

**Step 3: Fix parser\_version.py (The Git killer)**

* **Problem:** The git command runs at module scope.  
* **Action:** Move the subprocess.run(\['git', ...\]) call inside a function (e.g., get\_parser\_version()).  
* **Optimization:** Use @functools.cache on that function so it runs at most once per process, and *only* when explicitly requested (lazy loading).

### ---

**Phase 2: Persistent Worker Pool (Scalability / Long Term)**

Once correctness is restored via the Primary Instruction, we may still face overhead from Windows process creation spawning 70,000 times. If build times are still \>1 hour, implement this phase.

**Concept:**

Instead of subprocess.run (Process-per-File), use a long-lived "Worker Pool" architecture.

1. **Daemon Startup:** Spawn N worker.py subprocesses (where N \= CPU cores).  
2. **Initialization:** Workers perform the expensive imports once.  
3. **Protocol:** Daemon sends { "path": "..." } via stdin. Worker replies { "ast": ... } via stdout.  
4. **Safety:** If a worker crashes (segfault/memory leak), the daemon detects the pipe break and spawns a replacement.

**Why Wait?**

This introduces complexity (protocol management, deadlock prevention, watchdog timers). It is better to implement the architectural fix (Primary Instruction) first, which simplifies the code, before adding the complexity of a worker pool.

## ---

**Verification Plan**

We will verify the fix using two specific tests to ensure we haven't broken functionality while chasing performance.

### **1\. Import-Cost Instrumentation**

Modify the subprocess script temporarily to print timestamps. We expect to see the "Time to Import" drop from \~5s to \<0.1s.

Python

import time  
t0 \= time.time()  
\# ... do imports ...  
t1 \= time.time()  
print(f"Import overhead: {t1-t0:.4f}s")

### **2\. AST Stability Test**

Select 10 representative vanilla files (small, medium, large, complex).

1. Generate AST using the current (slow) codebase. Save as baseline.json.  
2. Apply the fixes (move serde functions, clean imports).  
3. Generate AST using the new codebase. Save as new.json.  
4. **Pass Condition:** diff baseline.json new.json must be empty. This ensures the refactoring didn't alter the data structure.

---

## DETAILED IMPLEMENTATION PLAN (Agent Review Ready)

**Prepared:** 2026-02-07 by Copilot Agent  
**Status:** FOR REVIEW - Do not implement until approved

---

### TASK 1: Create `parser/ast_serde.py` (NEW FILE)

**Location:** `src/ck3raven/parser/ast_serde.py`

**Purpose:** Pure AST serialization functions with ZERO external dependencies.

**Dependencies (STRICT):**
- `json` (stdlib)
- `Dict`, `Any` from `typing` (stdlib)
- AST node types from `ck3raven.parser.parser` (same package, no chain import)

**Functions to create:**

```python
"""
AST Serialization/Deserialization — Zero-Dependency Module

This module provides pure JSON serialization for AST nodes.
CRITICAL: This module must NEVER import from ck3raven.db.

Used by:
- runtime.py subprocess code (needs ultrafast import)
- db/ast_cache.py (re-exports for backward compatibility)
"""

import json
from typing import Dict, Any

# Import only the node types (same package, no chain)
from ck3raven.parser.parser import RootNode, BlockNode, AssignmentNode, ValueNode, ListNode


def serialize_ast(ast: RootNode) -> bytes:
    """Serialize AST to compact JSON bytes."""
    def node_to_dict(node) -> Dict[str, Any]:
        if isinstance(node, RootNode):
            return {
                '_type': 'root',
                'filename': str(node.filename),
                'children': [node_to_dict(c) for c in node.children]
            }
        elif isinstance(node, BlockNode):
            return {
                '_type': 'block',
                'name': node.name,
                'operator': node.operator,
                'line': node.line,
                'column': node.column,
                'children': [node_to_dict(c) for c in node.children]
            }
        elif isinstance(node, AssignmentNode):
            return {
                '_type': 'assignment',
                'key': node.key,
                'operator': node.operator,
                'line': node.line,
                'column': node.column,
                'value': node_to_dict(node.value)
            }
        elif isinstance(node, ValueNode):
            return {
                '_type': 'value',
                'value': node.value,
                'value_type': node.value_type,
                'line': node.line,
                'column': node.column,
            }
        elif isinstance(node, ListNode):
            return {
                '_type': 'list',
                'line': node.line,
                'column': node.column,
                'items': [node_to_dict(i) for i in node.items]
            }
        else:
            return {'_type': 'unknown', 'repr': repr(node)}
    
    data = node_to_dict(ast)
    return json.dumps(data, separators=(',', ':')).encode('utf-8')


def deserialize_ast(data: bytes) -> Dict[str, Any]:
    """Deserialize AST from JSON bytes."""
    return json.loads(data.decode('utf-8'))


def count_ast_nodes(ast_dict: Dict[str, Any]) -> int:
    """Count nodes in a serialized AST dictionary."""
    count = 1
    for key in ('children', 'items', 'value'):
        if key in ast_dict:
            val = ast_dict[key]
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        count += count_ast_nodes(item)
            elif isinstance(val, dict):
                count += count_ast_nodes(val)
    return count
```

**Verification:**
```bash
# Import time should be < 0.05s
python -c "import time; t0=time.time(); from ck3raven.parser.ast_serde import serialize_ast; print(f'{time.time()-t0:.4f}s')"
```

---

### TASK 2: Update `parser/__init__.py`

**Action:** Export the new ast_serde functions for convenience.

**Add to exports:**
```python
from ck3raven.parser.ast_serde import (
    serialize_ast,
    deserialize_ast,
    count_ast_nodes,
)
```

**Add to `__all__`:**
```python
"serialize_ast",
"deserialize_ast", 
"count_ast_nodes",
```

---

### TASK 3: Update `runtime.py` Subprocess Code

**Location:** `src/ck3raven/parser/runtime.py`

**Change ALL subprocess code blocks** (`_PARSE_FILE_CODE`, `_PARSE_TEXT_CODE`, `_PARSE_TEXT_RECOVERING_CODE`):

**BEFORE:**
```python
from ck3raven.db.ast_cache import serialize_ast, count_ast_nodes, deserialize_ast
```

**AFTER:**
```python
from ck3raven.parser.ast_serde import serialize_ast, deserialize_ast, count_ast_nodes
```

**Critical:** The subprocess code must use the new import path. This is the PRIMARY performance fix.

---

### TASK 4: Fix `parser_version.py` (Lazy Git)

**Location:** `src/ck3raven/db/parser_version.py`

**Problem:** Lines 30-38 execute `subprocess.run(['git', ...])` at module import time.

**Fix:** Make it lazy with `@functools.cache`:

```python
import functools

@functools.cache
def get_git_commit() -> Optional[str]:
    """Get current git commit hash if in a git repo. Cached."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
            timeout=5,  # Add timeout to prevent hangs
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]
    except Exception:
        pass
    return None
```

**Verification:** Importing `parser_version.py` should NOT spawn git process until `get_git_commit()` is explicitly called.

---

### TASK 5: Update `db/ast_cache.py` (Backward Compatibility)

**Location:** `src/ck3raven/db/ast_cache.py`

**Change:** Import from new location and re-export for callers still using the old path.

```python
# Import from canonical location (parser/ast_serde.py)
from ck3raven.parser.ast_serde import serialize_ast, deserialize_ast, count_ast_nodes

# Re-export for backward compatibility (existing code importing from here)
__all__ = ['serialize_ast', 'deserialize_ast', 'count_ast_nodes', ...]
```

**Remove:** The duplicate function definitions currently in ast_cache.py.

---

### TASK 6: Clean Up `ck3raven/__init__.py`

**Current Problem:**
```python
from ck3raven.resolver import MergePolicy, CONTENT_TYPES
from ck3raven.db import init_database
```

These trigger import chains.

**FIX:** Remove eager imports. Make them available via explicit import only.

```python
"""
ck3raven - CK3 Game State Emulator
"""

__version__ = "0.1.0"
__author__ = "ck3raven contributors"

# Only re-export parser (it has no heavy deps)
from ck3raven.parser import parse_file, parse_source

# DO NOT import resolver or db at package level
# Users should explicitly import what they need:
#   from ck3raven.resolver import MergePolicy
#   from ck3raven.db import init_database

__all__ = [
    "parse_file",
    "parse_source",
]
```

---

### TASK 7 (OPTIONAL): Clean Up `db/__init__.py`

**Current Problem:** 175 lines of eager imports loading the entire DB stack.

**Recommended Fix:** Convert to lazy imports OR just export names:

```python
"""ck3raven.db - Database Storage Layer"""

# Don't import anything at module level
# Each submodule should be imported explicitly by callers

__all__ = [
    "init_database",
    "get_connection",
    # ... list of names, but don't import them here
]

def __getattr__(name):
    """Lazy import pattern - only load when accessed."""
    if name == "init_database":
        from ck3raven.db.schema import init_database
        return init_database
    # ... etc
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

**Note:** This is optional but recommended for overall framework health.

---

### VERIFICATION CHECKLIST

After implementation, run these checks:

1. **Import Time Test:**
```bash
python -c "import time; t0=time.time(); from ck3raven.parser.ast_serde import serialize_ast; print(f'Import time: {time.time()-t0:.4f}s')"
# Expected: < 0.05s (was 4-28s before fix)
```

2. **Subprocess Import Test:**
```bash
python -c "
import time
t0 = time.time()
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path('.') / 'src'))
from ck3raven.parser.parser import parse_file as _parse_file
from ck3raven.parser.ast_serde import serialize_ast, count_ast_nodes, deserialize_ast
print(f'Subprocess-equivalent import: {time.time()-t0:.4f}s')
"
# Expected: < 0.2s
```

3. **AST Stability Test:**
```bash
# Parse a file with OLD code, save output
# Parse same file with NEW code, compare
# Should be byte-identical
```

4. **Full Build Test:**
```bash
python -m qbuilder daemon --fresh
# Monitor: Processing rate should be 10-50 files/second, not 0.1 files/second
```

---

### RISK ASSESSMENT

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Import cycle from parser.ast_serde → parser.parser | Low | ast_serde only imports node types, not functions |
| Backward compat break from db/ast_cache | Medium | Keep re-exports in ast_cache.py |
| __init__.py cleanup breaks dependent code | Medium | Run test suite after each change |
| git subprocess timeout on Windows | Low | Added 5s timeout to get_git_commit() |

---

### ROLLBACK PLAN

If issues arise, revert in this order:
1. Restore `ck3raven/__init__.py` eager imports
2. Restore `db/__init__.py` if modified
3. Revert runtime.py import changes
4. Keep ast_serde.py (it's additive, won't break anything)

---

**END OF IMPLEMENTATION PLAN**

*Awaiting user approval before implementation.*
