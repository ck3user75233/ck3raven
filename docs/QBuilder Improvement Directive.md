# **QBuilder Improvement Directive**

**Version:** 1.0

**Date:** 2026-02-07

**Status:** **APPROVED FOR EXECUTION** **Severity:** Critical (Build Pipeline Broken \+ Control Flow Bug)

## ---

**Overview & Objectives**

This directive consolidates the remediation of two critical issues affecting the QBuilder build pipeline:

1. **Performance Regression:** A massive import chain in the subprocess spawning logic causes a 40-85x slowdown, inflating build times from \~1 hour to 11+ hours. This is caused by ck3raven framework imports leaking into the lightweight parser subprocess.  
2. **Control Flow Bug:** The qbuilder daemon \--fresh command resets data but fails to enqueue discovery tasks, leaving the daemon idle.

**Primary Goal:** Restore sub-second per-file parse times and ensure the daemon correctly processes the active playset on a fresh start.

## ---

**Phase 0: Baseline Benchmarking (Mandatory)**

**Objective:** Establish a concrete performance baseline to measure improvements against. Do not skip.

* **Metric 1: Subprocess Parse Time**  
  * **Method:** Time the \_run\_parse\_subprocess() function on 10 representative files (small, medium, large).  
  * **Current Expected:** 4–28s per file (many timeout at 30s).  
  * **Target:** \< 0.2s per file.  
* **Metric 2: Import Chain Overhead**  
  * **Method:** Run python \-c "import time; t=time.time(); import ck3raven; print(f'{time.time()-t:.3f}s')".  
  * **Current Expected:** Several seconds (imports \~15,000+ lines \+ executes git rev-parse).  
  * **Target:** \< 0.1s for parser-only imports.  
* **Metric 3: Full Build Estimate**  
  * **Method:** Estimate based on current processing rate (files/sec).  
  * **Current Expected:** 11+ hours.  
  * **Target:** \< 1 hour.

**Artifact:** Save results to docs/benchmarks/qbuilder\_baseline\_20260207.md.

## ---

**Phase 1: Architectural Fixes (Performance)**

**Guiding Principle:** "Sanitize Imports & Isolate Dependencies." We must stop the subprocess from loading the database layer.

### **Step 1.1: Sanitize \_\_init\_\_.py Files**

**Goal:** Remove eager imports from package roots to prevent cascade loading.

* **src/ck3raven/\_\_init\_\_.py**:  
  * **Action:** Remove all eager imports (from .db import ..., from .resolver import ...).  
  * **Result:** File should contain only metadata (\_\_version\_\_) or explicit \_\_all\_\_ exports without eager loading.  
* **src/ck3raven/db/\_\_init\_\_.py**:  
  * **Action:** Convert to lazy imports (using \_\_getattr\_\_) or remove barrel exports entirely.  
  * **Result:** Importing ck3raven.db should not trigger imports of submodules like schema, models, or parser\_version.  
* **Call Site Remediation:**  
  * **Action:** Grep codebase for from ck3raven import ... and update to explicit imports (e.g., from ck3raven.parser import ...).

### **Step 1.2: Isolate AST Serialization (ast\_serde.py)**

**Goal:** Create a zero-dependency module for AST/JSON conversion, decoupling the parser from the database.

* **Action:** Create src/ck3raven/parser/ast\_serde.py.  
  * **Dependencies:** STRICTLY limited to json, typing, and ck3raven.parser.parser (node types only).  
  * **Content:** Move serialize\_ast, deserialize\_ast, and count\_ast\_nodes here.  
* **Update runtime.py:**  
  * **Action:** Update the subprocess inline code (\_PARSE\_FILE\_CODE, etc.) to import from ck3raven.parser.ast\_serde instead of ck3raven.db.ast\_cache.  
* **Backward Compatibility:**  
  * **Action:** In src/ck3raven/db/ast\_cache.py, import the functions from ast\_serde.py and re-export them to avoid breaking existing DB code.

### **Step 1.3: Fix parser\_version.py (Lazy Git Execution)**

**Goal:** Stop git rev-parse HEAD from running at module import time.

* **File:** src/ck3raven/db/parser\_version.py (or parser/parser\_version.py if moved).  
* **Action:**  
  1. Remove top-level execution of subprocess.run.  
  2. Wrap logic in a function get\_parser\_version() decorated with @functools.cache.  
  3. Add a timeout (e.g., 5s) to the git command to prevent hangs.  
* **Result:** Git command runs only when explicitly called, not on import.

## ---

**Phase 1.5: Control Flow Fix (Daemon Logic)**

**Objective:** Fix qbuilder daemon \--fresh erroneously sitting idle.

* **File:** src/qbuilder/cli.py  
* **Action:** In cmd\_daemon function, inside the \--fresh handling block:  
  * **After:** reset\_qbuilder\_tables(conn)  
  * **Insert:** Logic to enqueue discovery tasks for the active playset.  
* **Code Pattern:**  
  Python  
  playset\_path \= get\_active\_playset\_file()  
  if playset\_path and playset\_path.exists():  
      print(f"Enqueuing discovery from {playset\_path.name}...")  
      enqueue\_playset\_roots(conn, playset\_path)

* **Verification:** Running python \-m qbuilder daemon \--fresh should immediately show Pending: \>0 and begin processing.

## ---

**Phase 2: Verification & Gates**

**Objective:** Validate correctness and performance before considering further optimization.

### **Gate 1: AST Stability (Correctness)**

1. **Select:** 10-100 representative vanilla files.  
2. **Test:** Parse with old code (baseline) vs. new code (fix).  
3. **Pass Condition:** diff baseline.json new.json is **empty** (byte-identical output).

### **Gate 2: Performance Targets**

1. **Import Time:** python \-c "import ck3raven.parser.ast\_serde" must be **\< 0.05s**.  
2. **Subprocess Time:** \_run\_parse\_subprocess avg must be **\< 0.2s**.  
3. **Daemon Throughput:** Build rate should exceed **10-50 files/second**.

### **Gate 3: Control Flow**

1. **Test:** Run qbuilder daemon \--fresh.  
2. **Pass Condition:** Daemon resets data AND automatically begins discovery/parsing without user intervention.

## ---

**Phase 3: Persistent Worker Pool (Optional / Long-Term)**

**Trigger:** Only implement if Phase 2 benchmarks show subprocess overhead is still the primary bottleneck (e.g., \> 1s per file) *after* architectural fixes.

**Concept:**

* Replace subprocess.run (Process-per-File) with a long-lived worker pool.  
* **Mechanism:** Daemon spawns N workers; workers load imports once; communicate via stdin/stdout.  
* **Note:** This adds significant complexity (IPC, watchdog, restart logic). **Do not implement in Phase 1\.**

## ---

**Execution Checklist**

* \[ \] **Phase 0: Baseline**  
  * \[ \] Measure subprocess parse time (10 files).  
  * \[ \] Measure import chain time.  
  * \[ \] Document in docs/benchmarks/.  
* \[ \] **Phase 1: Architecture**  
  * \[ \] **Step 1.1:** Clean ck3raven/\_\_init\_\_.py & db/\_\_init\_\_.py. Fix broken imports.  
  * \[ \] **Step 1.2:** Create parser/ast\_serde.py. Update runtime.py subprocess code. Update db/ast\_cache.py.  
  * \[ \] **Step 1.3:** Make parser\_version.py git call lazy & cached.  
* \[ \] **Phase 1.5: Daemon Fix**  
  * \[ \] Add enqueue\_playset\_roots call to cli.py (--fresh block).  
* \[ \] **Phase 2: Verification**  
  * \[ \] Run AST Stability Test.  
  * \[ \] Run Performance Benchmarks.  
  * \[ \] Verify Daemon Auto-Start on \--fresh.  
* \[ \] **Phase 3: Decision**  
  * \[ \] If targets met: **Close Ticket**.  
  * \[ \] If targets missed: **Design Phase 3 (Worker Pool)**.