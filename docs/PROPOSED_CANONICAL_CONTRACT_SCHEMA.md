# Canonical Contract Schema v1 (Agent-Facing)

**Status:** PROPOSED → CANONICAL  
**Last Updated:** January 13, 2026  
**Applies to:** ck3raven-dev mode and ck3lens mode  
**Audience:** Development agents only

This document defines the **only acceptable contract format** for declaring work.
It replaces all prior mixed, legacy, or implicit scope mechanisms.

Read this as *law*, not guidance.

---

## 0) Prime Directive

You are declaring **intent and impact**, not implementation cleverness.

You MUST:
- State **what will change** and **where**.
- Make review possible without guesswork.
- Stop and escalate if anything is unclear.

You MUST NOT:
- Carry legacy concepts forward "for compatibility."
- Infer scope from filesystem structure, playsets, or database state.
- Invent substitute abstractions to make progress.

---

## 1) Zero-Compatibility Policy (Hard Law)

There is **no backward compatibility**.

### 1.1 Immediate Rejection
Any contract containing deprecated or banned fields MUST be rejected.

**BANNED (non-exhaustive):**
- `canonical_domains`
- any field that mixes directories and concepts (e.g. `["src","parser"]`)
- "active playset mods"
- "active local mods"
- any scope inferred indirectly rather than declared

No migration. No mapping. No fallback.

### 1.2 Strict Schema
- Unknown fields → **reject**
- Missing required fields → **reject**

Failure is preferred to ambiguity.

---

## 2) Security Scope: Geographic Roots Only

All permission decisions are based **only** on geographic root categories.

### 2.1 `root_category` (Required)
Exactly one of:

| Root Category | Description | Writable |
|---------------|-------------|----------|
| `ROOT_REPO` | Infrastructure / tool source (ck3raven/) | ✅ Yes |
| `ROOT_USER_DOCS` | User mods / editable content (Documents/mod/) | ✅ Yes |
| `ROOT_WIP` | Scratch / experimental (.wip/, ~/.ck3raven/wip/) | ✅ Yes |
| `ROOT_STEAM` | Steam workshop mods | ❌ READ-ONLY |
| `ROOT_GAME` | Vanilla game files | ❌ READ-ONLY |

### 2.2 Rules
- One root per contract.
- READ-ONLY roots are never writable.
- No other field can override this.
- Work spanning multiple roots requires **multiple contracts**.

---

## 3) Contract v1 — Required Shape

A valid contract MUST contain **exactly** these fields:

```json
{
  "contract_id": "string",
  "mode": "ck3raven-dev | ck3lens",
  "root_category": "ROOT_REPO | ROOT_USER_DOCS | ROOT_WIP | ROOT_STEAM | ROOT_GAME",
  "intent": "short free-text label",
  "operations": ["READ", "WRITE", ...],
  "targets": [...],
  "work_declaration": {...},
  "created_at": "ISO-8601",
  "author": "string"
}
```

No additional fields are allowed.

---

### 3.1 `operations`
Declares **classes of action**, not meaning.

Allowed values:
- `READ`
- `WRITE`
- `DELETE`
- `RENAME`
- `EXECUTE`
- `DB_WRITE`
- `GIT_WRITE`

Rules:
- Any of `WRITE | DELETE | RENAME | DB_WRITE` requires edit declarations.
- `EXECUTE` is only allowed inside `ROOT_WIP` unless explicitly authorized.

---

### 3.2 `targets`
Declares **what objects are in scope**.

Each target MUST include:
- `target_type`: `file` | `folder` | `command` | `db_table`
- `path`: canonical relative path (or name for commands / DB tables)
- `description`: plain-English explanation

Rules:
- Targets define scope, not steps.
- Absolute filesystem paths are forbidden.

---

## 4) Work Declaration (Balanced, Not Over-Precise)

This section replaces taxonomy enums with an explicit, auditable plan.

### 4.1 Required Fields

`work_declaration` MUST contain:

- `work_summary`  
  Short paragraph describing what will change and why.

- `work_plan`  
  3–15 bullets describing the intended work at a conceptual level.

- `out_of_scope`  
  Explicit list of things this work will **not** touch.

- `edits`  
  Required if any write-class operation exists (Section 4.2).

- `symbol_intent`  
  Required always (Section 4.3).

---

### 4.2 Edit Declarations (Required, Soft Precision)

Exact diffs or code snippets are **not required**.

Each edit MUST declare **where** and **what kind of change**.

Each edit entry MUST include:
- `file` — canonical relative path
- `edit_kind` — `modify` | `create` | `delete` | `rename`
- `location` — one of:
  - `whole_file`
  - `block_name` (function, class, table, section name)
  - `approximate_region` (free text, e.g. "parser runtime entrypoint")
- `change_description` — concise explanation
- `post_conditions` — 1–3 statements describing expected outcome

Rules:
- Location must be specific enough that a reviewer knows where to look.
- "Whole file" is acceptable when justified.
- Over-precision is discouraged in v1.

---

### 4.3 Symbol Intent (Mandatory)

This exists to prevent silent invention.

`symbol_intent` MUST include:
- `will_create_new_symbols` (boolean)
- `new_symbols` (array; empty if false)
- `symbol_notes` (free-text rationale)

If `will_create_new_symbols = true`, each symbol MUST include:
- `symbol`
- `symbol_kind` (function, class, enum, table, column, command, other)
- `scope` (`local` | `global`)
- `rationale`
- `alternatives_considered` (at least 3)

No enforcement yet — but false declarations are detectable later.

---

## 5) Meaning of "Triggering Work"

Interactive tools may **cause work to occur**, but must not perform it inline.

Correct behavior includes:
- Enqueuing background work when a playset changes.
- Enqueuing priority work when a file is edited.
- Reading existing indexed data without mutation.

Incorrect behavior includes:
- Performing parsing, mutation, or heavy processing inline inside interactive tools.

---

## 6) Phase-2 Compatibility (Deferred)

This schema is designed to support future checks such as:
- verifying only declared files were modified
- verifying declared symbols match reality
- ensuring work stayed within declared scope

None of this is enforced now.
Do not implement Phase-2 logic unless explicitly instructed.

---

## 7) Required Agent Behavior

Before performing any mutation:

1. Produce a valid v1 contract.
2. Declare:
   - geographic scope
   - targets
   - edit locations
   - symbol intent (explicit yes/no)
3. Only then perform the work.

If you cannot write the contract clearly,
you do not understand the task yet.

---

## 8) Migration from Current System

### Current State (to be deprecated)
The current contract system uses `canonical_domains` which mixes:
- Directory names (`src`, `tools`, `scripts`)
- Conceptual domains (`parser`, `query`, `routing`)

This creates ambiguity about what is actually allowed.

### Target State
Replace with `root_category` + explicit `targets`:

```json
// OLD (deprecated)
{
  "canonical_domains": ["src", "tools", "parser"],
  "allowed_paths": ["src/ck3raven/**/*.py"]
}

// NEW (canonical)
{
  "root_category": "ROOT_REPO",
  "targets": [
    {"target_type": "folder", "path": "src/ck3raven/parser", "description": "Parser module"},
    {"target_type": "folder", "path": "tools/ck3lens_mcp", "description": "MCP server"}
  ]
}
```

### Implementation TODO
1. Update `work_contracts.py` to support new schema
2. Add validation for `root_category`
3. Deprecate `canonical_domains` field
4. Update agent instructions to use new format

---

## 9) Final Statement

This document is authoritative.

If any rule seems inconvenient:
- Stop.
- Escalate.
- Do not weaken or reinterpret it silently.

Clarity and determinism take precedence over speed.
