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