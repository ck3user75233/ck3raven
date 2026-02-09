Here is the document converted into a structured, normative Markdown specification.

# ---

**Canonical Reply System Architecture (Final)**

**Status:** FINAL / NORMATIVE

**Applies to:** ck3raven core, MCP server, all MCP tools, all agents

**Supersedes:** All prior Reply System architecture documents, interim audits, reviews, or agent interpretations.

**Document Authority**

This document is the **single source of truth** for the Canonical Reply System. Any behavior, implementation, audit, or agent instruction that contradicts this document is **incorrect by definition**.

It explicitly resolves every ambiguity that caused audit confusion:

* Reply vs. Envelope separation  
* Spec vs. Implementation framing  
* Layer vs. Area vs. Type  
* Invalid vs. Error semantics  
* Legacy code status (retired, not migrated)  
* Forbidden architectural states (multiple builders, multiple registries, info/warn/fail)

## ---

**1\. Purpose and Problem Statement**

The Canonical Reply System exists to eliminate:

* **Context poisoning:** Agents branching on text.  
* **Semantic drift:** "Success with warnings" or mixed meanings.  
* **Silent failures:** Exceptions swallowed or misclassified.  
* **Retry loops:** Caused by confusion between Invalid and Error.

It replaces ad-hoc exceptions, booleans, strings, and dictionaries with a **deterministic, registry-backed outcome protocol**.

## ---

**2\. Core Principle: One Reply, One Meaning**

Every tool invocation produces **exactly one semantic outcome**.

There are **no** auxiliary outcome classes such as:

* info  
* warning  
* partial success  
* soft error

All such concepts must be expressed using **Success (S)** containing structured data.

## ---

**3\. The Four Canonical Reply Types**

| Type | Name | Meaning | Who Is at Fault | Agent Action |
| :---- | :---- | :---- | :---- | :---- |
| **S** | **Success** | Operation completed as requested. | Nobody | Proceed |
| **I** | **Invalid** | Request malformed or not executable as stated. | Agent | Self-correct and retry |
| **D** | **Denied** | Valid request rejected by governance. | Policy | Escalate / request scope |
| **E** | **Error** | Unexpected system or infrastructure failure. | System | Stop, report trace\_id |

### **Critical Invariant**

**Invalid (I)** and **Error (E)** are mutually exclusive.

* **Invalid:** The agent made a mistake (HTTP 4xx semantics).  
* **Error:** The system broke (HTTP 5xx semantics).

**Warning:** Mixing these causes infinite retry loops and is strictly forbidden.

## ---

**4\. Decision Ownership (LAYER)**

**LAYER** identifies *who* decided the outcome, not what the tool was. The LAYER set is **closed and minimal**.

| LAYER | Owns | Allowed Types | Forbidden Types |
| :---- | :---- | :---- | :---- |
| **WA** | World structure, resolution, interpretation | S, I, E | D |
| **EN** | Governance, authorization, policy | S, D, E | I |
| **CT** | Contract lifecycle validity | S, I, E | D |
| **MCP** | Infrastructure, transport, ungoverned system ops | S, I, E | D |

### **Non‑Negotiable Rules**

* **Denied (D)** originates **only** from **EN**.  
* **WorldAdapter** never denies.  
* **Enforcement** never returns Invalid.  
* Adding a new LAYER requires an architecture revision.

## ---

**5\. Domain Description (AREA)**

**AREA** describes what domain the operation concerns. It is orthogonal to LAYER.

| AREA | Meaning |
| :---- | :---- |
| **SYS** | Fallback system semantics |
| **RES** | Resolution / mapping |
| **VIS** | Visibility / hidden / deprecated |
| **IO** | Generic I/O |
| **READ** | Reads |
| **WRITE** | Mutations |
| **EXEC** | Execution |
| **DB** | Database |
| **PARSE** | Parsing / AST |
| **VAL** | Validation (non-governance) |
| **GATE** | Preconditions |
| **LOG** | Logging / journaling |
| **CFG** | Configuration / setup |

### **Rules**

* AREA must **never** be a tool name.  
* AREA does not imply ownership.  
* New AREA values require registry \+ doc update.

### **Clarification: Contract Operations Map to GATE**

Contract open/close operations are **precondition checks and state transition gates** controlling whether future actions are allowed. They map to **GATE**, not to hypothetical "OPEN" or "CLOSE" AREA values.

* `CT-GATE-S-*` — Contract gate passed (opened or closed successfully)
* `CT-GATE-I-*` — Contract gate invalid (bad parameters, wrong state)
* `CT-GATE-E-*` — Contract gate system error

OPEN and CLOSE are not AREA values. The semantic domain is **gating**—the operation concerns whether subsequent actions may proceed.

## ---

**6\. Canonical Reply Code Format**

Format: LAYER-AREA-TYPE-NNN

**Examples:**

* WA-RES-I-001  
* EN-WRITE-D-002  
* MCP-SYS-E-001

**Properties:**

* Codes are **stable** and never reused.  
* Agents branch on **TYPE** and **CODE**, never message text.  
* Human-readable messages are derived, never authoritative.

## ---

**7\. Semantic Reply Object (Logical Layer)**

The Reply is the semantic decision object used throughout core logic.

Python

@dataclass(frozen=True)  
class Reply:  
    reply\_type: Literal\["S", "I", "D", "E"\]  
    code: str  
    data: Optional\[dict\] \= None

### **Non‑Goals of Reply**

The Reply object does **not**:

* Guarantee human message text.  
* Include timing or trace metadata.  
* Represent transport readiness.

## ---

**8\. Transport Envelope (Wire Contract)**

The ReplyEnvelope is the MCP transport wrapper.

JSON

{  
  "status": "success",  
  "reply\_type": "S",  
  "data": {},  
  "meta": {  
    "trace\_id": "req-123",  
    "duration\_ms": 12  
  },  
  "error": null  
}

### **Separation Rule**

1. Tools and core logic operate on **Reply**.  
2. Only MCP wrappers construct the **Envelope**.  
3. Missing envelope fields are implementation gaps, not semantic ambiguity.

## ---

**9\. ReplyBuilder (The Only Constructor)**

There must be **exactly one** ReplyBuilder in the entire runtime.

### **Canonical API**

Python

rb.success(data=...)  
rb.invalid(code, data=...)  
rb.denied(code, data=...)  
rb.error(code, data=...)

### **Explicitly Forbidden**

* rb.info  
* rb.warn  
* rb.fail

**Note:** Informational outcomes are **Success (S)** with structured data.

## ---

**10\. Terminal Semantics (State Machine Law)**

Constructing any of the following is **terminal**:

* **Invalid (I)**  
* **Denied (D)**  
* **Error (E)**

### **Rules**

1. Terminal replies must be returned immediately.  
2. Builder enters a **frozen state** after terminal construction.  
3. Any subsequent builder call raises a runtime error.  
   * *This prevents silent overwrites and invalid control flow.*

## ---

**11\. Safety Wrapper (mcp\_safe\_tool)**

The wrapper is a pure transport safety net.

**Responsibilities:**

* Generate trace\_id.  
* Measure duration.  
* Inject envelope metadata.  
* Catch unhandled exceptions → **Error (E)**.

### **Critical Rule**

System crashes are **always Error (E)** — never Invalid.

## ---

**12\. Legacy and Migration Rules**

* Legacy raw dict returns were allowed **only** during Phase 1\.  
* The **Canonical registry** is the only active registry.  
* Legacy codes with forbidden layers are **retired**, not migrated.  
* Multiple registries or builders at runtime are **forbidden states**.

## ---

**13\. Compliance and Enforcement**

Violations of this document are:

* **Architecture bugs** (not stylistic issues).  
* Valid reasons to **block PRs**.  
* Grounds for **rejecting agent output**.

Linting, pre-commit hooks, and runtime guards must enforce this standard.

## ---

**14\. Final Canonical Rule**

**AREA** describes what happened.

**LAYER** describes who decided.

**TYPE** describes what it means.

**These dimensions must never be conflated.**

---

Would you like me to help you draft the ReplyBuilder Python class or the JSON schema for the Envelope based on this spec?