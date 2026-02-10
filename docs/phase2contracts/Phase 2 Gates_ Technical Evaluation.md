Here is the technical evaluation and directive, formatted as a high-quality directive for your agent.

# ---

**Technical Evaluation & Phase 2 Directive**

## **Executive Verdict**

**Outcome:** **YES (Conditional)**

The proposal is fundamentally sound and correctly prioritizes Phase 2 readiness. It successfully identifies dead code, aligns the specification with current reality, and reduces operational debt.

**The Condition:**

You must accept the proposal with **one critical architectural constraint added**:

**Phase 2 must freeze the evidence schema before gate logic is written.**

We cannot build deterministic gates against a moving target. The semantic\_validator output must be versioned and canonical before consumption by the gates.

## ---

**1\. Item-by-Item Assessment**

### **1\. Token Architecture Unification (MIT-style)**

* **Assessment:** Correct direction, but wrong timing.  
* **Decision:** **Accept Conceptually, Defer Implementation.**  
* **Reasoning:** Moving to single-use, human-injected tokens (MIT-style) is the correct end-state. However, changing authorization mechanics (Phase 2.5) at the same time as gate mechanics (Phase 2\) creates unmanageable risk.  
* **Directive:** Document MIT-style tokens as the *target* architecture. Keep the current file-backed NST/LXE tokens operational until close\_gates.py is live and the evidence schema is frozen.

### **2\. Symbol Lock Removal (symbols\_lock.py)**

* **Assessment:** Absolutely correct and overdue.  
* **Decision:** **APPROVED (Immediate Action).**  
* **Reasoning:** This component is functionally dead. Documenting it actively harms clarity.  
* **Directive:** Delete symbols\_lock.py references from the canonical doc, mark the component deprecated, and remove artifacts/symbols/ from documentation.

### **3\. Semantic Validator Clarification**

* **Assessment:** Essential.  
* **Decision:** **APPROVED.**  
* **Reasoning:** Clarifying that semantic\_validator is a *sensor* (fact generator) and not an *enforcer* is required for the separation of concerns in Phase 2\.

### **4\. Phase 2 Verification Document Corrections**

* **Assessment:** Correct hygiene.  
* **Decision:** **APPROVED.**  
* **Reasoning:** Prevents false "not ready" signals by distinguishing Phase 2 deliverables from Phase 2 prerequisites.

### **5\. Symbol Artifacts Directory Removal**

* **Assessment:** Correct.  
* **Decision:** **APPROVED.**  
* **Reasoning:** The directory is empty because the architecture changed, not because implementation is missing.

### **6\. close\_gates vs. audit\_contract\_close**

* **Assessment:** Critical architectural distinction.  
* **Decision:** **APPROVED.**  
* **Reasoning:** We need fast, deterministic, shallow checks (**Gates**) separated from slow, exhaustive verification (**Audit**). Without this, Phase 2 is just Phase 1.5 with more if-statements.

### **7\. Capability Matrix Verification**

* **Assessment:** Necessary but bounded.  
* **Decision:** **APPROVED (Documentation Only).**  
* **Reasoning:** Update the documentation to match capability\_matrix.py. Do not modify the implementation to match the docs.

## ---

**2\. The Missing Constraint: Schema Freezing**

**The Rule:**

Before implementing any gates, you must declare the semantic\_validator output schema **canonical**.

**Requirements:**

1. **Versioning:** The output must contain a key like "schema\_version": "v1".  
2. **Determinism:** The validator must produce bit-for-bit identical outputs given the same inputs (stable ordering of lists/keys).  
3. **Stability:** Gates will treat this schema as a contract. Any change to the schema is a Phase 2.5+ concern.

## ---

**3\. Sprint 0 Directive: Prep & Proof Path**

*Paste the following instructions directly into the agent's context to begin execution.*

### **Objective**

Sprint 0 exists to remove Phase 2 blockers and prove the Phase 2 approach works end-to-end in **one narrow context** before generalization.

**Definition of Done:**

1. semantic\_validator is test-proven for determinism and schema stability.  
2. audit\_contract\_close.py no longer depends on the deprecated symbols\_lock.py.  
3. A single, minimal **Close Gate** path is implemented via a "gate runner" tool.  
4. Test artifacts (outputs \+ hashes) confirm determinism.

### **Work Items (In Strict Order)**

#### **0.1 Establish Gate Evidence Folder**

Create artifacts/phase2\_sprint0/ with subdirectories for semantic\_validator, gates, logs, and hashes.

#### **0.2 Build Semantic Validator Fixture Suite**

Create tools/compliance/fixtures/semantic\_validator/:

* **Python:** Simple defs, nested defs, intentional syntax errors.  
* **CK3:** Known identifier categories, intentional parse failures.

**Test Checkpoint (Must Pass):**

* **Repeatability:** Run 5 times → Output hash identical.  
* **Order Independence:** Shuffle input file list → Output hash identical.  
* **Error Visibility:** Malformed files produce specific parse\_errors, not crashes.

#### **0.3 Define "Schema v1"**

Once 0.2 passes, lock the schema.

* Add "schema\_version": "v1" to output.  
* Define which fields are canonical (hashed) vs metadata (ignored by hash).

#### **0.4 Remove symbols\_lock.py Dependency**

Refactor audit\_contract\_close.py to use semantic\_validator evidence instead of symbols\_lock.

* **Success:** The audit tool runs without importing the deprecated module.

#### **0.5 Implement Single "Gate Runner" Tool**

Create a temporary entrypoint (e.g., tools/compliance/run\_close\_gates.py) that does **ONE** thing:

* Input: contract\_id  
* Logic: Run a minimal set of gates (EVIDENCE\_PRESENT, NO\_FATAL\_PARSE\_ERRORS).  
* Output: JSON Report with outcome (AUTO\_APPROVE | REQUIRE\_APPROVAL | AUTO\_DENY).  
* **Constraint:** Do not refactor the entire system. This is a harness.

#### **0.6 Wire Runner to One Close Path**

Integrate the runner into the most direct contract-close code path.

* **Logic:**  
  * If AUTO\_DENY → Stop.  
  * If REQUIRE\_APPROVAL → Stop with message.  
  * If AUTO\_APPROVE → Proceed to audit.

## ---

**4\. Phase 2 Implementation Plan Framework**

*The agent must generate a plan document (docs/phase2contracts/PHASE\_2\_IMPLEMENTATION\_PLAN\_v2.md) adhering to this structure.*

### **1\. Scope & Non-Goals**

* **Includes:** Deterministic gates, open/close gating, git hook integration.  
* **Excludes:** Token redesign (MIT-style), broad refactoring, enforcement redesign.

### **2\. Phased Delivery Roadmap**

* **Phase 2.0 (Sprint 0):** Proof Path (Gate Runner \+ Validator Determinism).  
* **Phase 2.1 (Close Gates Proper):** Canonical close\_gates.py, strict schema checking.  
* **Phase 2.2 (Open Gates):** contract\_gates.py (Scope validity, capability checks).  
* **Phase 2.3 (Git Hooks):** Pre-commit hook calling the Gate Runner.  
* **Phase 2.4 (Expansion):** Applying gates to other workflows.

### **3\. Testing Strategy (Mandatory)**

For every phase, the plan must define:

* **Test ID & Command.**  
* **Expected Artifact:** What JSON/Log is produced?  
* **Rollback:** How to disable if it blocks the team.

### **4\. Acceptance Criteria**

Phase 2 is complete when:

1. Open Gates enforce contract legality.  
2. Close Gates block or require approval deterministically.  
3. Pre-commit hooks are active (warn/block).  
4. Evidence schema is versioned and enforced.