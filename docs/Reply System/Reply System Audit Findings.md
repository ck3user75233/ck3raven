Here is the full, non-truncated content formatted into a clean Markdown document.

# ---

**REPLY SYSTEM AUDIT**

**Note:** The ck3\_file tool is currently disabled. File editing and terminal tools are unavailable. This document docs/reply\_cleanup/REPLY\_SYSTEM\_AUDIT.md must be created manually.

## **1\. Actual Wire Shape (from Reply.to\_dict())**

### **Field-by-Field Comparison**

| Field | v2.0 Spec | Reply Dataclass | Status |
| :---- | :---- | :---- | :---- |
| **status** | "success" | "error" | MISSING | ❌ Not present — no status field exists |
| **reply\_type** | "S" | "I" | "D" | "E" | reply\_type: ReplyType | ✅ Present |
| **data** | {} | data: Dict\[str, Any\] | ✅ Present |
| **meta.duration\_ms** | Required in meta | MISSING | ❌ Not present — MetaInfo has only layer, tool, contract\_id |
| **meta.trace\_id** | Required in meta | MISSING from meta | ❌ Wrong location — it's in trace instead |
| **error** | null (separate field) | MISSING | ❌ Not present — no dedicated error field |
| **code** | Not in spec | Top-level code: str | ⚠️ In code but missing from spec |
| **message** | Not in spec | Top-level message: str | ⚠️ In code but missing from spec |
| **trace** | Not in spec | Top-level trace: TraceInfo | ⚠️ In code but missing from spec |
| **meta.layer** | Not in spec | Inside MetaInfo | ⚠️ In code but missing from spec |
| **meta.tool** | Not in spec | Inside MetaInfo | ⚠️ In code but missing from spec |
| **meta.contract\_id** | Not in spec | Inside MetaInfo | ⚠️ In code but missing from spec |

**Analysis:** The actual wire format is significantly richer than the spec but diverges structurally on 4/5 of the spec's required fields. The spec and the code appear to have been written to different design iterations.

## **4\. Dual Registry Analysis**

### **Code Counts**

| Registry | File | Codes |
| :---- | :---- | :---- |
| **Legacy** | src/ck3raven/core/reply\_registry.py | 83 codes |
| **Canonical** | tools/ck3lens\_mcp/ck3lens/reply\_codes.py | 68 codes |

### **Legacy Layers vs Canonical Layers**

* **Legacy:** Layer \= Literal\["MCP", "WA", "EN", "CT", "DB", "PARSE", "LEARN", "GIT"\] (8 layers)  
* **Canonical:** Layer \= Enum(WA, EN, CT, MCP) (4 layers)

The canonical registry collapsed 4 layers (DB, PARSE, LEARN, GIT) into the 4-layer model.

### **Canonical Layer Coverage**

| Layer | S codes | I codes | D codes | E codes | Total |
| :---- | :---- | :---- | :---- | :---- | :---- |
| **WA** | 14 | 15 | 0 | 12 | 41 |
| **EN** | 5 | 0 | 6 | 5 | 16 |
| **CT** | 4 | 3 | 0 | 3 | 10 |
| **MCP** | 4 | 2 | 0 | 3 | 9 |

### **Migration Gaps**

Codes in legacy with **no canonical equivalent** and no LEGACY\_TO\_CANONICAL entry:

* LEARN-DIFF-\* (3 codes)  
* GIT-HOOK-\* (3 codes)  
* MCP-SYS-D-902 (1 code)

### **Runtime Import Status**

| File | Imports From | Active? |
| :---- | :---- | :---- |
| safety.py | Both: reply\_registry.get\_message AND reply\_codes.validate\_code\_format | Yes |
| unified\_tools.py | reply\_registry.get\_message | Yes |
| core/\_\_init\_\_.py | Both: reply.Reply and reply\_registry.{REGISTRY, validate\_registry} | Yes |

Both registries are actively imported at runtime. Legacy registry is **not marked deprecated**.

### **Migration Path Assessment**

Partially clear. reply\_codes.py has a LEGACY\_TO\_CANONICAL dict, and validate\_code\_format() only accepts canonical patterns. However:

1. Legacy is not deprecated (no warnings, no markers)  
2. safety.py still calls reply\_registry.get\_message for message text — canonical has message\_key/description but no get\_message() equivalent  
3. No shim or adapter exists for transparent translation

## **5\. Behavioral Invariant Audits**

### **5.1 Exception Handler Audit (Invalid vs Error)**

**Canonical Rule:** Unexpected system exceptions → **Error (E)**, never **Invalid (I)**.

| File | except → Reply Blocks | Compliant | Non-Compliant |
| :---- | :---- | :---- | :---- |
| safety.py (wrapper) | 1 | 1 | 0 |
| server.py | 8 | 8 | 0 |
| unified\_tools.py | 3 | 3 | 0 |
| world\_adapter.py | 0 (no Reply construction) | N/A | N/A |
| **TOTAL** | **12** | **12** | **0** |

**RESULT:** 100% compliant. No except Exception → rb.invalid() violations found. ✅

*Notable:* safety.py has a universal catch-all wrapper (mcp\_safe\_tool decorator) that catches any unhandled exception and emits Reply.error('MCP-SYS-E-001') — this is the safety net.

### **5.2 Return Discipline Audit**

**Canonical Rule:** Terminal reply calls (invalid, denied, error) must be immediately returned.

| File | Terminal Calls | Proper return rb.xxx(...) | Violations |
| :---- | :---- | :---- | :---- |
| server.py | 59 | 59 | 0 |
| unified\_tools.py | 13 | 13 | 0 |
| **TOTAL** | **72** | **72** | **0** |

**RESULT:** 100% compliant. Every terminal call uses return. ✅

### **5.3 Empty Result Handling**

**Canonical Rule:** "No results found" → **Success (S)** with empty data: \[\], NOT **Invalid (I)**.

**Compliant ✅**

| Tool | Behavior |
| :---- | :---- |
| ck3\_search | rb.success('WA-READ-S-001') with 0 counts |
| ck3\_grep\_raw | rb.success('WA-READ-S-001', data={matches: \[\], count: 0}) |
| ck3\_file\_search | rb.success('WA-READ-S-001', data={files: \[\], count: 0}) |
| ck3\_conflicts(symbols) | rb.success('WA-READ-S-001', data={conflict\_count: 0}) |
| ck3\_conflicts(files) | rb.success('WA-READ-S-001', data={conflicts: \[\], count: 0}) |
| ck3\_search\_mods | rb.success('WA-READ-S-001', data={results: \[\]}) |
| ck3\_db\_query(table) | rb.success('WA-DB-S-001', data={count: 0, results: \[\]}) |
| ck3\_db\_query(sql) | rb.success('WA-DB-S-001', data={count: 0, results: \[\]}) |

**Non-Compliant ⚠️**

| Tool | Line | Behavior | Expected |
| :---- | :---- | :---- | :---- |
| ck3\_contract(command="status") | server.py \~L3663 | No active contract → rb.invalid('CT-CLOSE-I-001') | Should be rb.success(...) with {has\_active\_contract: false} |

*Rationale:* The caller asked command="status" — a perfectly valid query. "No active contract" is a valid state, not bad input. The comment on L3662 even acknowledges: "No active contract is informational, not governance denial" — yet uses rb.invalid.

**Borderline (Not Strictly Wrong)**

| Tool | Line | Behavior | Notes |
| :---- | :---- | :---- | :---- |
| ck3\_logs | server.py \~L1620 | CK3 error.log not found → rb.error('MCP-SYS-E-001') | Not a system crash — CK3 just hasn't been run. Code implies system failure when issue is "prerequisite not met." |
| ck3\_get\_agent\_briefing | server.py \~L4940 | No active playset → rb.invalid('WA-VIS-I-001') | Defensible — calling playset-dependent tool without a playset is bad input. But could also be Success with empty data \+ hint. |

### **5.4 rb.info() / Reply.info() Usage**

| Location | What | Status |
| :---- | :---- | :---- |
| \_ReplyBuilder.info() (unified\_tools.py L57–63) | Calls Reply.info() which **does not exist** on Reply dataclass | DEAD CODE / WOULD CRASH |
| Callers of rb.info() | Zero callers found across entire codebase | Dead code, safe to delete |
| ReplyBuilder (safety.py) | Correctly has **no** info() method | ✅ Compliant |

## **6\. Layer Ownership Rules**

### **Canonical Rule (Decision-Locked)**

| Layer | Allowed Types | Forbidden Types |
| :---- | :---- | :---- |
| **WA** (World Adapter) | S, I, E | D |
| **EN** (Enforcement) | S, D, E | I |
| **CT** (Contract) | S, I, E | D |
| **MCP** (Infrastructure) | S, I, E | D |

### **Enforcement Status**

| Builder | Enforces Layer Ownership? | How? |
| :---- | :---- | :---- |
| ReplyBuilder (safety.py) | ✅ Yes | \_validate\_and\_get\_layer() at call time |
| \_ReplyBuilder (unified\_tools.py) | ❌ No | Zero validation — layer param passed through directly |
| reply\_codes.py | ✅ Yes | validate\_registry() at import time |

## **7\. Findings Summary Table**

| \# | Finding | Category | Severity |
| :---- | :---- | :---- | :---- |
| **F1** | Envelope schema diverges from v2.0 spec (missing status, error, duration\_ms; trace\_id in wrong location) | Thematic | High — spec vs code mismatch |
| **F2** | Dual code registry: legacy reply\_registry.py (83 codes) \+ canonical reply\_codes.py (68 codes) both active at runtime | Thematic | High — architectural debt |
| **F3** | Dual ReplyBuilder: ReplyBuilder in safety.py \+ \_ReplyBuilder in unified\_tools.py with asymmetric APIs and no validation in the clone | Thematic | High — invariant bypass |
| **F4** | No frozen-builder state: neither ReplyBuilder freezes after terminal reply (invalid/denied/error) | Thematic | Medium — spec requires it |
| **F5** | Dead \_ReplyBuilder.info() method references non-existent Reply.info() — would crash if called | Tactical | Low — dead code, zero callers |
| **F6** | \_ReplyBuilder missing invalid() method — yet rb.invalid() is called 6 times in same file | Tactical | Critical — runtime crash for those paths |
| **F7** | ck3\_contract(command="status") returns Invalid(I) for "no active contract" — should be Success(S) | Tactical | Low — one call site |
| **F8** | Legacy registry codes LEARN-DIFF-\* (3) and GIT-HOOK-\* (3) have no canonical equivalent or migration mapping | Tactical | Low — gap in migration table |
| **F9** | No dedicated reply-code linter or pre-commit hook (Phase 4 of v2.0 spec) | Thematic | Medium — prevention layer missing |
| **F10** | v2.0 spec envelope omits code and message fields that the actual wire format relies on heavily | Thematic | High — spec is incomplete |

## **8\. Compliance Scorecard**

| v2.0 Requirement | Status | Notes |
| :---- | :---- | :---- |
| Four types only (S/I/D/E) | ✅ PASS |  |
| Primary ReplyBuilder has exactly 4 methods | ⚠️ PARTIAL | No rb.info() / rb.fail() / rb.warn(). Primary builder clean; \_ReplyBuilder clone still has dead info() |
| Terminal replies are terminal (return immediately) | ✅ PASS | 72/72 terminal calls use return |
| Frozen builder after terminal call | ❌ FAIL | Not implemented in either builder |
| Layer ownership (WA→S/I, EN→S/D) | ⚠️ PARTIAL | Enforced in primary ReplyBuilder; zero enforcement in \_ReplyBuilder clone |
| Registry codes over ad-hoc text | ✅ PASS | All replies use structured codes; get\_message() renders human text |
| Exception → Error(E), not Invalid(I) | ✅ PASS | All 12 except→Reply handlers are compliant |
| Empty results → Success(S) | ⚠️ PARTIAL | 8/9 compliant; 1 violation in ck3\_contract status |
| Standard envelope shape | ❌ FAIL | Missing status, error, duration\_ms; trace\_id misplaced |
| Pre-commit linter for reply rules | ❌ FAIL | No reply-specific hook exists |

## **9\. Execution Plan (Bite-Sized Chunks)**

Each chunk is designed as an independent unit of work.

### **Chunk A — Spec Reconciliation (Design Decision Required)**

* Resolve **F1 \+ F10**: The v2.0 spec envelope and the actual code envelope disagree. Before any code changes, decide which is source of truth.  
* **Decide:** Does the code adopt the spec's status/error fields? Or does the spec update to match the code's code/message/trace shape?  
* Update the canonical doc (docs/Canonical Reply System Architecture.md) to match the decision.  
* If adding status/error/duration\_ms, modify Reply dataclass in src/ck3raven/core/reply.py and its to\_dict().

### **Chunk B — Kill the Shadow Builder (F3 \+ F5 \+ F6)**

* Eliminate \_ReplyBuilder in unified\_tools.py entirely:  
  * Replace \_create\_reply\_builder() to return the canonical ReplyBuilder from safety.py.  
  * Delete the \_ReplyBuilder class (fixes F5 dead info() and F6 missing invalid()).  
* Verify all 6 rb.invalid() calls in unified\_tools.py now resolve to the real method.  
* Verify layer ownership validation now applies to all unified\_tools paths.

### **Chunk C — Frozen Builder (F4)**

* Implement the freeze-after-terminal-reply mechanism in ReplyBuilder:  
  * Add \_frozen: bool \= False to ReplyBuilder.\_\_init\_\_.  
  * In invalid(), denied(), error() — set self.\_frozen \= True before returning.  
  * Add a guard at the top of success(), invalid(), denied(), error() — if \_frozen, raise RuntimeError("ReplyBuilder already produced a terminal reply").  
* Add unit tests for the freeze invariant.

### **Chunk D — Tactical One-Offs (F7 \+ F8)**

* **F7:** In server.py \~L3663, change rb.invalid('CT-CLOSE-I-001', ...) to rb.success(...) for the "no active contract" status query.  
* **F8:** Add LEARN-DIFF-\* and GIT-HOOK-\* entries to the LEGACY\_TO\_CANONICAL mapping in reply\_codes.py, or explicitly mark them as retired.

### **Chunk E — Registry Consolidation (F2)**

* Migrate from dual registries to single canonical registry:  
  * Add a get\_message(code, \*\*params) function to reply\_codes.py using its description/message\_key fields.  
  * Update safety.py to stop importing from reply\_registry.py.  
  * Update unified\_tools.py likewise (if it survives Chunk B).  
  * Mark reply\_registry.py as deprecated with a DeprecationWarning on import.  
* Validate no remaining runtime imports outside tests.

### **Chunk F — Reply Linter Hook (F9)**

* Add a pre-commit guard for reply system invariants:  
  * Create scripts/guards/reply\_code\_guard.py.  
  * Rules: no rb.info( strings in diff; no raw dicts returned from @mcp\_safe\_tool handlers; all codes match validate\_code\_format().  
  * Register in .pre-commit-config.yaml.

### **Suggested Execution Order**

Chunk A must come first because it determines whether envelope changes ripple into B–E. Chunk B is highest-value (eliminates the validation bypass). Chunks D and F are independent and can happen in parallel with anything.

## **10\. Verification**

* Run existing test suite after each chunk  
* get\_errors on modified files  
* For Chunk C: add dedicated test test\_frozen\_builder\_raises  
* For Chunk E: verify LEGACY\_TO\_CANONICAL covers all codes still in use  
* For Chunk F: run pre-commit hook on a test file with rb.info() and confirm it blocks

## **11\. Open Decisions**

| Decision | Options | Impact |
| :---- | :---- | :---- |
| **F1/F10: Spec vs code** — which is source of truth for envelope shape? | **A)** Code adopts spec fields; **B)** Spec updates to match code | Must resolve before implementation |
| **F2: Legacy registry deprecation strategy** | **A)** Hard-deprecate immediately; **B)** Soft-deprecate with migration period | Affects rollout risk |
| **F4: Frozen builder violation behavior** | **A)** RuntimeError (dev-facing, fail-fast); **B)** Logged warning (graceful degradation) | Affects developer experience |

