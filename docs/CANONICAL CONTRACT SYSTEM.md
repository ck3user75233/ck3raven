# Canonical Contract System

## Schema · Policy · Implementation Guide

**Status:** CANONICAL  
**Applies to:** ck3raven-dev, ck3lens  
**Audience:** Development agents only  
**Authority Level:** Hard Law  

---

## 0. Authority, Scope, and Precedence

This document defines the entire contract system used by CK3Raven.

It unifies:

- contract schema  
- policy governing interpretation  
- canonical implementation model  

### Precedence Rules

In case of conflict:

1. Schema rules override all other sections  
2. Policy rules override implementation guidance  
3. Implementation guidance must never reinterpret schema or policy  

If ambiguity exists:

- stop  
- escalate  
- do not infer  
- do not invent substitute abstractions  

Failure is preferred to ambiguity.

---

# PART I — CORE PRINCIPLE

## 1. Geographic Scope Domain Principle

All authorization and enforcement decisions are based exclusively on geographic filesystem domains, not conceptual meaning.

A contract’s authority is determined by:

- where on disk the target lives  
- not what the files represent  
- not launcher classification  
- not mod activation state  
- not runtime session context  

If two files live in different filesystem roots, they belong to different enforcement domains regardless of semantic relationship.

This rule is absolute.

---

## 1.1 Visibility vs Authority

The system distinguishes three separate concepts:

| Concept | Meaning |
|------|------|
| Visibility | What the system may discover or enumerate |
| Authorization | What the contract may touch |
| Capability | Which operations are permitted |

Visibility never grants permission.

Authorization is determined only by:

- `root_category`  
- execution mode  
- capability matrix  

Reading a file requires both:

- visibility to that path  
- authorization to operate on its root  

**Example**

ck3lens may observe Steam Workshop mods via metadata or playset resolution, but may not enumerate all workshop content. Read access applies only to explicitly targeted paths or playset-resolved discoveries.

---

# PART II — CONTRACT SCHEMA (HARD LAW)

## 2. Prime Directive

A contract must declare intent and impact explicitly.

The system must never infer scope.

You MUST:

- declare what will change  
- declare where it will change  
- make review possible without interpretation  

You MUST NOT:

- infer scope from launcher state  
- infer scope from active mods  
- infer scope from directory structure  
- invent abstractions to bypass restrictions  

---

## 3. Zero-Compatibility Policy

There is no backward compatibility.

### 3.1 Immediate Rejection

Contracts containing deprecated or banned fields must be rejected.

**BANNED (non-exhaustive):**

- `canonical_domains`  
- semantic domain lists  
- active mod sets as authority  
- launcher-derived permission  
- hybrid or inferred scopes  

No migration.  
No fallback.  
No compatibility parsing.  

Legacy contracts must be archived and ignored.

---

## 4. Geographic Root Categories

Each contract operates within exactly one filesystem root.

### 4.1 Root Categories

| Root | Description |
|----|----|
| `ROOT_REPO` | CK3Raven tool source |
| `ROOT_USER_DOCS` | User-authored mods |
| `ROOT_WIP` | Scratch and sandbox workspace |
| `ROOT_STEAM` | Steam Workshop content |
| `ROOT_GAME` | Vanilla CK3 installation |
| `ROOT_UTILITIES` | Logs and diagnostics |
| `ROOT_LAUNCHER` | Paradox launcher registry |

### 4.2 Root Rules

- exactly one root per contract  
- root defines enforcement boundary  
- permissions derive only from capability matrix  
- semantic meaning is irrelevant  
- multi-root work requires multiple contracts  

---

## 5. Contract v1 Required Shape

```json
{
  "contract_id": "string",
  "mode": "ck3raven-dev | ck3lens",
  "root_category": "ROOT_*",
  "intent": "short description",
  "operations": ["READ", "WRITE"],
  "targets": [],
  "work_declaration": {},
  "created_at": "ISO-8601",
  "author": "string"
}
```

No additional fields are permitted.

Unknown fields cause rejection.

---

## 6. Operations

Allowed values:

- READ  
- WRITE  
- DELETE  
- RENAME  
- EXECUTE  
- DB_WRITE  
- GIT_WRITE  

Rules:

- mutating operations require explicit edit declarations  
- EXECUTE permitted only in `ROOT_WIP` unless explicitly authorized  

---

## 7. Targets

Targets define what objects fall under scope.

Each target must include:

- `target_type`: file | folder | command | db_table  
- `path`: canonical relative path  
- `description`: human explanation  

Rules:

- absolute paths are forbidden  
- targets define visibility, not permission  

---

## 8. Work Declaration

Mandatory fields:

- `work_summary`  
- `work_plan` (3–15 bullets)  
- `out_of_scope`  
- `symbol_intent`  

If mutating, edits must include:

- file  
- edit_kind  
- location  
- change_description  
- post_conditions  

---

## 9. Symbol Intent

All symbol creation must be declared.

Purpose:

- prevent silent invention  
- support auditability  
- block hallucinated architecture  

---

# PART III — CONTRACT POLICY

## 10. Concept Hygiene

The following are permanently banned:

- semantic scope inference  
- launcher-based authorization  
- active mod lists as authority  

These concepts must never re-enter enforcement logic.

---

## 11. Mode Capability Principle

Authorization depends on:

- execution mode  
- root_category  
- capability matrix  

### ck3lens

- operational mode  
- limited write authority  
- may repair user mods and launcher registry  

### ck3raven-dev

- development mode  
- broad read access  
- writes limited to repository and WIP  

No mode may infer permission from file meaning.

---

## 12. Launcher Policy

Launcher data is configuration state, not mod content.

`ROOT_LAUNCHER` mutation permitted only for:

- registry repair  
- normalization  
- recovery  
- consistency correction  

---

## 13. Utilities Policy

Utilities represent diagnostic evidence.

Default policy:

- READ only  
- no mutation  
- no execution inference  

---

## 14. Safety Rule

If blocked:

- stop  
- document  
- propose  
- wait  

Never invent substitute mechanisms.

---

# PART IV — IMPLEMENTATION MODEL

## 15. Phase 1 — Contract Mechanics (Complete)

Implements:

- Contract v1 schema  
- enums  
- serialization  
- strict validation  
- legacy archival  

Does not implement:

- enforcement  
- mutation  
- inference logic  

This phase establishes law only.

---

## 16. Phase 2 — Deterministic Gates

Phase 2 introduces pure evaluative gates.

Gates:

- run at contract open time  
- do not mutate  
- do not execute  
- do not infer semantics  

Allowed results:

- AUTO_APPROVE  
- REQUIRE_APPROVAL  
- AUTO_DENY  

### Required Gate Families

#### File Count Threshold Gate

Evaluates resolved file impact deterministically.

Large scope → REQUIRE_APPROVAL  
Extreme scope → AUTO_DENY  

#### Recursive Glob Detection Gate

Detects:

- `**/*`  
- directory-wide mutations  
- inferred breadth expansion  

May never silently approve.

#### Root Exclusivity Gate

Validates:

- exactly one root  
- no target escapes root boundary  

Any violation → AUTO_DENY.

#### Required-Field Completeness Gate

Validates:

- all required schema fields  
- required work declarations  
- symbol intent presence  

Missing data → AUTO_DENY.

### Phase 2 Non-Goals

Phase 2 must NOT:

- interpret intent semantics  
- mutate files  
- consult launcher state  
- rewrite contracts  
- infer user expectations  

It only classifies risk.

---

## 17. Phase 3 — Semantic Reasoning (Deferred)

Not implemented without explicit authorization.

---

# PART V — GREY ZONES

Intentionally undefined:

- approval UI  
- orchestration pipelines  
- automation chaining  

May be proposed but never inferred.

---

# PART VI — FINAL STATEMENT

This system exists to prevent silent expansion.

If something feels inconvenient:

- stop  
- escalate  
- do not reinterpret  

**Determinism over velocity.**  
**Clarity over cleverness.**

---

## Appendix A — Root Capability Matrix

| Root | ck3lens | ck3raven-dev | Notes |
|----|----|----|----|
| `ROOT_REPO` | R | RW | Lens diagnostics only |
| `ROOT_USER_DOCS` | RW | R | Primary lens workspace |
| `ROOT_WIP` | RW | RW | Safe sandbox |
| `ROOT_STEAM` | R | R | Read-only; visibility constrained |
| `ROOT_GAME` | R | R | Never writable |
| `ROOT_UTILITIES` | R | R | Diagnostic evidence |
| `ROOT_LAUNCHER` | RW | R | Lens may repair registry |

Read capability does not imply global enumeration.  
Visibility is constrained by discovery mechanisms and explicit targets.
