# **Agent Directive — Canonical Reply System Authority & Registry Consolidation**

**Applies to:** All agents, MCP tools, ck3raven core

**Effective:** Immediately

**Status:** FINAL / NON-NEGOTIABLE

## ---

**1\. Determination of Authority (Root Cause)**

There has been agentic drift because multiple artifacts were treated as peers. That is incorrect.

**The following document is the single authoritative source of truth for the Reply system:**

**Canonical Reply System Architecture (Final / Normative)**

**By definition:**

Any file, implementation, registry, audit note, or agent interpretation that contradicts this document is **wrong**, regardless of recency, usage, or convenience.

This explicitly invalidates:

* Legacy registries  
* Drifted helper files  
* Tool-local namespaces  
* Arguments based on current code implementation ("But the code currently does X")

## ---

**2\. Canonical Registry Decision (Resolved)**

There must be **exactly one** reply code registry.

### **The Canonical Registry**

* reply\_codes.py (Canonical)

### **Explicitly Rejected Sources**

The following are rejected as sources of truth:

* reply\_registry.py  
* Per-tool reply code lists  
* Runtime-constructed registries  
* Agent-invented codes

**Outcome:**

1. reply\_registry.py is legacy, invalid, and to be eliminated.  
2. reply\_codes.py is the only valid registry.  
3. This is not an optimization—it is **architectural law**.

## ---

**3\. Why the Agent’s Prior Review Was Incorrect**

The agent failed previously because it:

* Treated multiple files as co-equal.  
* Attempted reconciliation instead of enforcement.  
* Did not recognize that a **FINAL / NORMATIVE** document supersedes implementation.

**Class Error:** When a canonical document exists, the correct behavior is **conformance**, not comparison.

## ---

**4\. Binding Rules Going Forward (No Exceptions)**

Agents must obey the following rules. Violations are architecture bugs, not edge cases.

| Rule Name | Requirement |
| :---- | :---- |
| **Precedence Rule** | If a canonical document exists, it **always** overrides code. |
| **Registry Rule** | One registry only. One builder only. One meaning per code. |
| **Ownership Rule** | Only **EN** may emit Denied (D). **WA**, **CT**, and **MCP** must not deny. |
| **Migration Rule** | Legacy codes with forbidden semantics are retired, not migrated. Absence of a legacy equivalent is not a justification to invent one. |
| **Agent Behavior Rule** | Do not propose alternatives. Do not "keep both for now." Do not add compatibility layers unless explicitly instructed. |

## ---

**5\. Required Actions (Execution, Not Discussion)**

Agents working on this area must:

* Treat **Canonical Reply System Architecture** as binding law.  
* Implement **R17: Registry Consolidation Proposal** exactly as written.  
* **Remove** all imports, references, and dependencies on reply\_registry.py.  
* Ensure safety.py and all builders source messages from the canonical registry.  
* **Reject** any PR or patch that introduces:  
  * A second registry.  
  * A new layer.  
  * A denial outside EN.  
  * Non-canonical reply types.

## ---

**6\. Final Instruction to Agents**

**Stop reconciling. Stop debating. Stop inferring intent.**

The architecture is settled. Your task is to enforce it exactly. Any further drift in this area will be treated as a failure to follow explicit instruction, not as ambiguity in the system.

---

**Would you like me to proceed with creating the plan to delete reply\_registry.py and refactor the dependencies to reply\_codes.py?**