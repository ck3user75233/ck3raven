Here is the text converted into a well-formatted Markdown work order.

# ---

**Agent Work Order: Canonical Reply System Refactor (Phase-Gated)**

**Authority:** The **Canonical Reply System Architecture (Final)** is the sole source of truth. The MCP\_AUDIT\_PROTOCOL.md v2.0 is the authoritative measurement instrument. Do not reinterpret canon. If ambiguity arises, stop and request human direction.

**Operating Mode:** Phase-gated execution. You must complete **one phase at a time**. After each phase you must:

1. Run validation.  
2. Produce required deliverables.  
3. **Pause for human concurrence** before starting the next phase.

**Non-Negotiable:** Do not "bundle phases." Do not continue "because it’s easy." **Stop at gates.**

## ---

**A. Global Rules**

### **A1) Separation Rule: Reply vs Envelope**

* **Semantic Reply** compliance is audited by protocol.  
* **Transport Envelope** completeness is tracked as **TRANSPORT GAP**, not as semantic violations.  
* Do not "fix envelope" unless explicitly assigned in a phase.

### **A2) Controlled Vocabulary (AREA)**

* **AREA** is controlled.  
* Do not introduce new AREA values without explicit human approval.

### **A3) Denied Ownership**

* **Denied (D)** originates **ONLY** from **EN**.  
* **WA / CT / MCP** must never emit **D**.

### **A4) MIT Semantics (Must Not Regress)**

* MIT missing/invalid/expired must remain:  
  * **Invalid (I)**  
  * **MCP-owned**  
  * Example: MCP-CFG-I-001  
* MIT is **not** a governance decision and must not route through Enforcement (EN).

## ---

**B. Deliverables Required After Every Phase**

At the end of each phase, produce a report with the following structure:

1. **Phase Summary**  
   * What you changed.  
   * Files touched.  
   * Any notable design assumptions.  
2. **Mapping Table (if codes changed)**  
   * Old code → New code.  
   * Rationale (one line each).  
3. **Validation Evidence**  
   * Re-run MCP\_AUDIT\_PROTOCOL.md v2.0.  
   * Provide the updated delta audit output for the phase.  
   * **Explicitly report the counts for:**  
     * LAYER×TYPE violations.  
     * AREA violations.  
     * REQ-02 (Error classification) failures.  
     * Legacy layer occurrences.  
4. **Remaining Issues**  
   * If any violations remain, list them with:  
     * Code.  
     * Location (file \+ line).  
     * Why not fixed in this phase.  
5. **Human Decision Requests**  
   * If any step requires human direction, list as **H-XXX** items.  
   * **Then STOP and ask for concurrence to proceed.**

## ---

**C. Phase Plan**

### **Phase 0 — Measurement Lock and H-001 Embedding**

**Goal:** Ensure protocol is stable and incorporates the human decision: OPEN/CLOSE → GATE.

* **Work:**  
  * Update protocol/docs so OPEN/CLOSE are no longer "requires human decision"; they are treated as GATE mappings.  
  * Ensure protocol continues to classify envelope items as **TRANSPORT GAP**, not semantic.  
* **Acceptance Gate:**  
  * Re-run audit: baseline counts match, except H-001 is removed and OPEN/CLOSE findings are now actionable mappings to GATE.  
  * **STOP after deliverables.**

### **Phase 1 — Registry Normalization: Remove Illegal LAYER×TYPE Codes**

**Goal:** Eliminate all LAYER×TYPE violations from registry and active code references.

* **Work:**  
  * Fix/remove all non-EN \*-\*-D-\* reply codes:  
    * CT--D- → **must not exist**.  
    * WA--D- → **must not exist**.  
    * MCP--D- → **must not exist**.  
  * Update call sites minimally to use the corrected codes.  
  * Do not do broader refactors yet—keep scope narrow.  
* **Acceptance Gate:**  
  * Audit shows LAYER×TYPE violations \= **0**.  
  * **STOP after deliverables.**

### **Phase 2 — AREA Normalization (Controlled Vocabulary Enforcement)**

**Goal:** Eliminate non-canonical AREA usage.

* **Work:**  
  * Apply mapping decisions (no new AREA values):  
    * OPEN/CLOSE → GATE (per human decision).  
    * Tool-name AREAs (FILE-OP/FOLDER-OP/PLAYSET-OP) → IO or VIS as appropriate.  
    * GIT area usage → EXEC or IO (choose based on semantics; document choice).  
    * POL → VAL or SYS (choose based on meaning; document choice).  
* **Required Step Before Editing:**  
  * Produce a mapping table first (Old → New).  
  * If any mapping is non-obvious, flag it as **H-XXX** and request confirmation.  
* **Acceptance Gate:**  
  * Audit shows AREA violations \= **0** (or only those explicitly deferred as H-XXX).  
  * **STOP after deliverables.**

### **Phase 3 — Error vs Invalid Routing: Remove “if error then rb.error” Anti-pattern**

**Goal:** Fix systemic misclassification of errors.

* **Work:**  
  * Replace patterns like if result.get("error"): return rb.error(...) with deterministic routing that distinguishes:  
    * **Invalid (I):** bad input, not found, unmet prerequisites, missing required inputs.  
    * **Denied (D):** governance refusal (EN-owned only).  
    * **Error (E):** system/infrastructure failure (exceptions, crashes, timeouts).  
  * If \_impl() returns only {error: "...text..."}, improve the internal return shape so the handler can classify deterministically (e.g., kind or reply\_type hint), but keep the public tool contract as ReplyBuilder outcomes.  
  * Use ck3\_exec as the exemplar routing pattern.  
* **Acceptance Gate:**  
  * Audit shows REQ-02 failures \= **0** (or only those explicitly justified and documented as H-XXX).  
  * **STOP after deliverables.**

### **Phase 4 — Retire Legacy Layers Cleanly (DB/PARSE/LEARN/GIT as LAYER)**

**Goal:** Remove runtime ambiguity and ensure a single canonical registry.

* **Work:**  
  * Ensure no runtime-used codes have forbidden LAYER prefixes (DB-, PARSE-, LEARN-, GIT-).  
  * Retired codes may remain only in an explicit retired/quarantine structure, not used by tools.  
  * Remove/redirect imports so canonical registry is the only active source.  
  * If a shim is required temporarily, isolate it in one module and document it.  
* **Acceptance Gate:**  
  * Audit shows Legacy layer occurrences \= **0** for runtime-used codes/tools.  
  * Any remaining retired codes are quarantined and not referenced.  
  * **STOP after deliverables.**

### **Phase 5 — Builder Unification and Invariants Hardening**

**Goal:** Enforce "one ReplyBuilder," freeze semantics, ban forbidden methods.

* **Work:**  
  * Eliminate any shadow/duplicate ReplyBuilder implementations.  
  * Ensure terminal calls freeze builder state and prevent overwrite.  
  * Ensure rb.info/warn/fail do not exist or are unreachable/removed.  
  * Add minimal tests or proof points demonstrating freeze behavior.  
* **Acceptance Gate:**  
  * Protocol REQ-07 passes across tool surface.  
  * Demonstrable evidence that duplicate builder paths are gone.  
  * **STOP after deliverables.**

## ---

**D. Stop Conditions**

**Stop and request human direction if:**

* A mapping requires adding a new **AREA** or **LAYER**.  
* A code family cannot be mapped without changing semantics.  
* Any change would require "bundling" phases.  
* You discover conflicts between implementation and Final Canon.