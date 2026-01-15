Excellent — thank you, that clarifies the intent very precisely. Based on your answers, here is a **clean, canonical, agent-facing instruction set** that:

* **Does NOT reference** the deprecated policy architecture file or the audit report
* Treats policy gaps as **forward design**, not remediation
* Is **IRONCLAD** where decisions are made
* Is **explicitly staged**, so mechanics come before logic entanglement
* Assumes an agent may arrive **cold**, and tests whether the docs are sufficient
* Leaves **clearly delineated gray zones** only where you explicitly want proposals

This is written in the tone and structure you can hand directly to the agentic AI doing dev work.

---

# CK3Raven Policy & Contract System

## Canonical Agent Instructions (Phased Implementation)

**Authority level:** Canonical (aspiring to hard law)
**Applies to:** ck3raven-dev mode only
**Purpose:** Establish a deterministic, enforceable contract system without architectural drift

---

## 0. Prime Directive (Read First)

You are implementing **foundational policy infrastructure**, not a feature.

Your goals are, in order:

1. **Mechanical correctness**
2. **Architectural clarity**
3. **Future enforceability**
4. **Only then** completeness

You MUST NOT:

* Invent substitute abstractions
* Patch around missing concepts
* Collapse “how contracts work” and “what contracts decide” into one step

If something is unclear, escalate. Silence and invention are considered failures.

---

## 1. Scope & Authority

### 1.1 Canonical Sources

You must treat the following as authoritative:

* `docs/CANONICAL_ARCHITECTURE.md`
* Existing enforcement boundary rules (`enforcement.py`, `WorldAdapter`)
* Existing path/root abstractions (`ROOT_USER_DOCS`, `ROOT_GAME`, `ROOT_STEAM`, `ROOT_WIP`)

You must NOT rely on:

* Deleted or deprecated policy documents
* Historical terminology unless it appears in canonical docs

If a concept appears **only in old documents**, assume it is invalid until re-justified.

---

## 2. Terminology & Concept Hygiene (Hard Rules)

### 2.1 Banned Concepts

The following are **conceptually banned**, not just renamed:

* “active playset mods” (as a scope or geography)
* “active local mods” (as a filesystem concept)
* Any term that implies **policy scope = directory reach**

These are banned because they conflate:

* **Session semantics**
* **Visibility**
* **Filesystem geography**

This confusion must not re-enter the system.

---

### 2.2 What You Are Allowed to Use Instead

You may express scope **only** using one of the following classes of concepts:

1. **Root abstractions**
   (`ROOT_USER_DOCS`, `ROOT_GAME`, `ROOT_STEAM`, `ROOT_WIP`)

2. **Session-scoped semantic sets**, if and only if they already exist canonically
   (e.g. session identifiers, visibility sets returned by `WorldAdapter`)

3. **Explicit identifiers**
   (mod IDs, CVIDs, resolved file lists)

If you find that existing docs do *not* clearly explain this distinction to a cold agent, you must flag that explicitly and propose a documentation fix — do not “paper over” it in code.

---

## 3. Contracts: What Exists vs What Does Not

### 3.1 Current State (Accepted Reality)

As of now:

* There is **no fully canonical Contract schema**
* There is **partial enforcement logic**
* There is **no single authoritative policy spec**

This is expected. You are not fixing a broken system; you are **building the missing foundation**.

---

### 3.2 Design Goal (End State)

The end state (not all in one phase) is:

* A declarative **Contract schema**
* Deterministic **open-time gates**
* Deterministic **execution-time enforcement**
* Zero policy logic embedded ad-hoc in tools

We will reach this in phases.

---

## 4. Phased Implementation Plan (MANDATORY)

You MUST follow this staging. Do not compress phases.

---

### 🔹 PHASE 1 — Contract Mechanics Only (Stage-1 Mandatory)

**Objective:** Make contracts *real objects* with no policy logic yet.

#### You MUST implement:

1. A canonical **Contract data model**

   * Fields exist
   * Types exist
   * Validation exists
   * No “decision logic” yet

2. Canonical enums:

   * `IntentType`
   * `OperationType`
   * `ContractStatus`

3. A single source of truth for the above:

   * `docs/POLICY_SPECS.md` (specification)
   * Matching Python dataclasses / enums

#### You MUST NOT:

* Decide whether a contract is “allowed”
* Add file counting, glob logic, or thresholds
* Embed special cases (“if BUGFIX then…”)

At the end of Phase 1:

* Contracts can be **created, validated, serialized, logged**
* They do **nothing** beyond existing

This phase is about **shape and correctness**, not safety.

---

### 🔹 PHASE 2 — Deterministic Gates (Stage-2 Mandatory)

**Objective:** Add mechanical gates that require no interpretation.

#### You MAY now implement:

* File count thresholds
* Recursive glob detection
* Domain exclusivity checks
* Required-field enforcement
* Evidence-required flags (but not semantic judgment)

All gates must be:

* Deterministic
* Measurable
* Logged with reason codes

#### You MUST keep these rules:

* Gates run at **contract open time**
* Gates return only:

  * `AUTO_APPROVE`
  * `REQUIRE_APPROVAL`
  * `AUTO_DENY`
* Gates do not mutate contracts
* Gates do not execute operations

---

### 🔹 PHASE 3 — Intent Logic & Semantics (Explicitly Deferred)

**Objective:** Bind *meaning* to intent types.

This phase is **NOT to be implemented yet** unless explicitly requested.

When we reach it, it will include:

* Intent plausibility
* Keyword / intent mismatch detection
* Risk scoring

Until then:

* `IntentType` exists as a label only
* No behavior depends on “what the intent means”

---

## 5. Where Rules Belong (Non-Negotiable)

| Concern               | Location          |
| --------------------- | ----------------- |
| Contract schema       | `POLICY_SPECS.md` |
| Enforcement decisions | `enforcement.py`  |
| Visibility            | `WorldAdapter`    |
| Agent behavior        | `COPILOT_*` docs  |
| UI payloads           | Explorer README   |
| Future ideas          | `docs/BACKLOG.md` |

If you put logic in the wrong layer, it will be rejected even if it “works.”

---

## 6. Grey Zones (Explicitly Allowed — With Constraints)

The following areas are **intentionally not fully specified yet**:

1. How session-semantic sets (e.g. CVIDs) are surfaced in contracts
2. How approval UI payloads are shaped
3. How multi-step workflows reference contracts

For these areas:

* You may propose **options**
* You must label them clearly as **PROPOSAL**
* You must not silently pick one and implement it

---

## 7. Non-Negotiable Safety Rule

> **You may not invent substitute abstractions to make progress.**

If progress requires a missing concept:

* Stop
* Describe the gap
* Propose how to close it
* Wait for instruction

This applies even if the implementation would be “obvious.”

---

## 8. Success Criteria for This Instruction Set

An agent following this correctly should:

* Be able to arrive cold
* Not need legacy policy documents
* Not reintroduce banned scope concepts
* Produce a clean Phase-1 contract system
* Set us up so the answer to
  *“Are contracts a blocking dependency for enforcement?”*
  becomes **YES** in the near future

---

## Next Step (For You, Not the Agent)

If you want, next I can:

1. Draft the **exact contents** of `POLICY_SPECS.md` (Phase 1 only)
2. Produce a **lint-style checklist** the agent can self-validate against
3. Identify **doc gaps** that would confuse a cold agent (per your request in point 2)
4. Write a **Phase-2 instruction delta** that layers on gates cleanly

Just tell me which you want first.

policy specs.md

