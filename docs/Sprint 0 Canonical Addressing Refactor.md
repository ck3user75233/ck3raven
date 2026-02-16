Here is the well-formatted Markdown version of the directive, including the **Strategic Preface** requested in the previous turn to ensure the document is complete and ready for the agent.

# ---

**STRATEGIC PREFACE: The Canonical Path Forward**

**Status:** Aspirational Architecture / Pilot Phase (Sprint 0\)

**Scope:** Strictly limited to ck3\_dir and world\_adapter\_v2

This document outlines the **Canonical Direction** for the future of ck3raven: a secure, unified addressing model where agents never see or touch host-absolute paths. While this is the target architecture for the entire system, we are implementing it today as a **parallel vertical slice**.

**Why we are doing this:**

We must prove that this strict "No Host Paths" model is viable for agent workflows without breaking the existing, functional toolset that you currently rely on.

**The Isolation Mandate:**

To achieve this safe exploration, we are creating **World Adapter v2**.

* **Purpose:** v2 components exist solely to support the new canonical addressing logic.  
* **Constraint:** world\_adapter\_v2 (and any other v2 support modules) **MUST NOT** be connected to, imported by, or used to drive changes in any existing tools (ck3\_file, ck3\_git, etc.) or current workflows.  
* **Strict Boundary:** The existing ecosystem must remain completely unaware of v2. Any proposal to migrate an existing tool to v2 requires explicit discussion and approval from Nate first.

**Sprint 0 Focus:**

We are building one new tool, ck3\_dir, front-to-back using this new architecture. This is our "clean room" to test the design.

# ---

**Sprint 0: Canonical Addressing Refactor (v1.1)**

## **1\. Purpose**

Sprint 0 introduces a new canonical addressing model for agent-facing file and directory interactions, without destabilizing the existing MCP tool ecosystem. This sprint deliberately implements a single vertical slice that proves the model end-to-end while keeping all existing tools and behaviors untouched.

The objective is not to refactor the system wholesale, but to:

* Establish clear invariants for how agents address files.  
* Prevent host-path leakage into agent-visible context.  
* Validate a new WorldAdapter (v2) design using one brand-new tool.

## **2\. Isolation Mandate (Non‑Negotiable)**

Existing tools **MUST NOT** import or depend on world\_adapter\_v2.

Sprint 0 changes are limited to:

* world\_adapter\_v2.py  
* ck3\_dir (new MCP tool)  
* Any private helpers used *only* by these two.

Legacy behavior remains authoritative for all other tools. **This isolation is intentional: Sprint 0 proves semantics, not compatibility.**

## **3\. Canonical Invariants (Global Direction)**

These invariants define the future addressing model. In Sprint 0, they are enforced **only** inside ck3\_dir.

### **Invariant A — Agent inputs are canonical only**

Agent-facing tools **MUST NOT** accept host absolute paths (C:\\..., /Users/...).

Accepted agent path forms:

* **Bare relative path:** wip/x.txt (interpreted relative to session\_home\_root)  
* **Session-absolute path:** ROOT\_REPO:/src/server.py  
* **Mod-absolute path:** mod:\<ModNameOrId\>:/common/traits/00\_traits.txt

### **Invariant B — Agent outputs are session-absolute only**

Any agent-visible output that references files or directories **MUST** return session-absolute paths only and **MUST NOT** expose host absolute paths.

* If the agent supplied a bare relative path, the tool **MUST** echo back the resolved session-absolute address.

### **Invariant C — Agent-facing filesystem touch requires WA provenance**

Every agent-facing filesystem-touching operation (list, tree, read, grep, search, write, etc.) **MUST** use a WA‑minted, non‑serializable VisibilityRef rather than passing host absolute paths.

* *Note:* System/config-driven I/O (logs, journals, tokens, DB files, config paths) is explicitly out of scope and does not require WA or EN.

### **Invariant D — Visibility is not policy denial**

If a path is outside the visible world, WA returns terminal **Invalid** (“not found / not addressable”).

* We do not return “Denied” for invisibility. Enforcement denial is reserved for mutation policy only.

### **Invariant E — Enforcement applies only to mutations**

EN (enforce(...)) is invoked only for **WRITE** operations. Read-only operations are governed solely by world visibility.

### **Invariant F — Terminal semantics**

If WA returns terminal (**I** or **E**), the tool **MUST** return immediately without further processing.

## **4\. Glossary (Canonical Terms)**

* **Session-absolute path:** ROOT\_CATEGORY:/rel/path or mod:\<NameOrId\>:/rel/path (Agent-visible).  
* **Host-absolute path:** OS path such as C:\\Users\\... or /home/... (Must never appear in agent-visible Replies).  
* **session\_home\_root:** The current default Root Category used to interpret bare relative paths.

## **5\. Sprint 0 Scope**

### **1\) New module: world\_adapter\_v2.py**

Create a new module world\_adapter\_v2.py. **Do not** modify or import existing world\_adapter.py in Sprint 0\.

**Public API:**

Python

WorldAdapterV2.resolve(  
    path: Optional\[str\],  
    session\_home\_root: RootCategory,  
    \*,  
    allow\_mod: bool \= True  
) \-\> tuple\[Reply, Optional\[VisibilityRef\]\]

**Resolve semantics:**

* path is None or path \== "" → resolves to session\_home\_root:/  
* Bare relative paths resolve relative to session\_home\_root  
* ROOT\_X:/rel/path resolves as session-absolute  
* mod:\<NameOrId\>:/rel/path resolves as mod-absolute

**Resolve outputs:**

* Always returns a Reply conforming to the Canonical Reply System.  
* On success, returns a VisibilityRef alongside the Reply.  
* On terminal Invalid/Error, returns None for VisibilityRef.

**Reply requirements:**

* Reply.data **MUST** contain only canonical, agent-visible address fields.  
* Reply.data **MUST NOT** contain host absolute paths under any circumstances.

**VisibilityRef requirements:**

* Holds the host-absolute Path internally.  
* Non-serializable (JSON / pickle must fail or omit).  
* Must not stringify to a host path (avoid accidental leakage).

### **2\) Mandatory Design Checkpoint — VisibilityRef sealing**

Before implementing VisibilityRef, the agent **MUST** submit a short design proposal (1–2 pages) covering:

* How VisibilityRef is sealed / protected from leakage.  
* How privileged code dereferences it.  
* Whether Sigil signing, session-key binding, or a simpler module-private mechanism is used.  
* Explicit threat model (preventing accidental misuse, not hostile devs).  
* **Implementation MUST NOT begin until this proposal is approved.**

### **3\) New MCP tool: ck3\_dir**

Implement a brand-new MCP tool ck3\_dir. It is the only Sprint 0 consumer of world\_adapter\_v2.

**Signature:**

Python

ck3\_dir(  
    command: str \= "pwd",  
    path: Optional\[str\] \= None,  
    depth: int \= 3  
) \-\> Reply

**Commands:**

* **pwd**  
  * Returns current session\_home\_root.  
  * Returns session-absolute home path (e.g. ROOT\_CK3RAVEN\_DATA:/).  
  * Does NOT touch the filesystem and does NOT call WA.  
* **cd (Sprint 0 restriction)**  
  * Accepts **Root Category only** (e.g. ROOT\_REPO, ROOT\_CK3RAVEN\_DATA).  
  * Updates session\_home\_root.  
  * *Subdirectory re-homing is explicitly out of scope for Sprint 0\.*  
* **list**  
  * Lists immediate children (files \+ directories).  
  * Operates on: home (if path is None) or resolved target (if path provided).  
* **tree**  
  * Lists directories only.  
  * Default depth \= 3 (override via depth).

**Required execution flow (list / tree):**

1. (reply, vis\_ref) \= wa\_v2.resolve(path, session\_home\_root)  
2. If reply is terminal → return immediately.  
3. Dereference vis\_ref via approved opener mechanism.  
4. Return Reply Success containing:  
   * Resolved session-absolute target.  
   * Entries as session-absolute paths only.

### **4\) Leak Detector Gate (Sprint 0 Acceptance Requirement)**

Add a defensive gate that recursively scans both Reply.data and Reply.message for host-absolute path patterns, including:

* Windows drive paths (C:\\)  
* UNC paths (\\\\server\\share)  
* /Users/, /home/, /mnt/  
* Any absolute /-rooted path

If any are found, fail with terminal **Error**.

### **5\) Purity Gate — v2 isolation**

Add an automated check ensuring:

* world\_adapter\_v2 is imported *only* by ck3\_dir and other \*\_v2.py modules.  
* No legacy tool imports v2.  
* Fail Sprint 0 if violated.

## **6\. Out of Scope for Sprint 0**

* Refactoring existing tools (ck3\_file, ck3\_exec, grep/search, etc.).  
* EN / WRITE policy refactors.  
* ResolutionResult removal.  
* Subdirectory cd.

## **7\. Mandatory Checkpoints (Agent MUST return for review)**

**Checkpoint 1 — VisibilityRef design proposal**

* Approval required before implementation.

**Checkpoint 2 — WA v2 implementation \+ unit tests**

* Bare relative  
* Session-absolute  
* Mod-absolute  
* Invalid handling  
* Proof of no host-path leakage in Reply.data

**Checkpoint 3 — ck3\_dir implementation \+ acceptance tests**

* pwd, cd, list, tree verified  
* Leak detector triggers correctly  
* v2 isolation gate passes

**Only after Checkpoint 3 approval may Sprint 1 be planned.**