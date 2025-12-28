# CK3 Agent Initialization - Draft Proposal

> **Status:** DRAFT - For evaluation and possible implementation
> **Date:** December 28, 2025
> **Source:** User-provided canonical initialization document with agent analysis

---

## Overview

This document captures a proposed evolution of agent initialization instructions. The content was provided by another AI and reviewed for alignment with current ck3raven architecture.

**Key principle:** These instructions should be treated as **onboarding material**, not replaced by todo lists during active work.

---

## 1. ck3lens Mode — Purpose and Responsibilities

### 1.1 What ck3lens Exists to Do

ck3lens exists to help users work with **real CK3 playsets**, not theoretical mod collections.

Primary responsibilities in ck3lens mode:

- Compatibility patching between multiple mods in a playset
- Bug-patching mods by creating local override mods
- Diagnosing conflicts, load-order issues, and overwrite behavior
- Explaining observed in-game behavior using:
  - mod files
  - conflict analysis
  - logs and error output
- Helping the user understand how the active playset resolves into game state

**Key constraint:** ck3lens is not responsible for developing CK3Raven itself. It works *with* the toolchain, not *on* the toolchain.

### Agent Analysis

✅ **Well aligned** with current implementation. This framing helps avoid scope confusion.

---

## 2. LensWorld — What You See and Why It Exists

### 2.1 The Core Idea

When debugging mods, agents naturally try to inspect *all* mods they can find. This produces false positives and invalid conclusions because CK3 only loads the **active playset**.

LensWorld exists to remove that burden from you.

LensWorld presents a **virtual filesystem and data view** that contains:
- exactly the mods CK3 is loading
- exactly the data that matters for the current investigation

Because of this:
- you do not need to remember which mods are active
- you do not need to filter search results manually
- conflict analysis and searches are always relevant
- hypotheses can be explored freely without accidental scope creep

**LensWorld is a cognitive simplification layer**, not merely a safety feature.

### Agent Analysis

✅ **Excellent framing.** Current implementation has WorldAdapter providing this. The "cognitive simplification" angle is valuable for agent understanding - it's not about restriction, it's about focus.

---

## 3. What LensWorld Contains

LensWorld is composed of the following scope domains:

### 3.1 Active Playset (Database View)

- Vanilla game (mod zero)
- Active Steam Workshop mods
- Active Local Mods

Accessed primarily through database-backed tools:
- searches, symbol lookups, AST inspection, conflict analysis

### 3.2 Active Local Mods (Filesystem View)

Local mods in the active playset are also visible via filesystem.
- Create compatibility patches
- Write override files
- Delete or adjust broken content

**Filesystem access exists ONLY for local mods in the active playset.**

### 3.3 CK3 Utility Scope

- logs, saves, crashes, dumps, player data
- Read and search freely
- Never edit or delete

### 3.4 Registry Scope

- mod registry, launcher metadata, cache state
- Always readable
- Repair/cache deletion requires contract + user approval

### 3.5 Playsets Scope

- playset definitions, load order, active playset selection
- Must use playset tools (never edit files directly)

### 3.6 WIP Scope

- Temporary workspace for helper scripts
- Never treated as runtime output
- Auto-cleared between sessions
- Must be gitignored

### 3.7 CK3Raven Source Code (Read-Only in ck3lens)

- May read to understand tool behavior or assemble bug reports
- Never edit in ck3lens mode

### Agent Analysis

✅ **Maps well to current implementation:**
- 3.1 → Database queries via `ck3_search`, `ck3_db_query`
- 3.2 → `ck3_file(command="write")` with mod_name
- 3.3 → `ck3_logs`, `ck3_repair(command="query")`
- 3.4 → `ck3_repair` tool
- 3.5 → `ck3_playset` tool
- 3.6 → WIP workspace in `policy/wip_workspace.py`
- 3.7 → WorldAdapter read-only for source paths

---

## 4. Guardrail Clarification

LensWorld is a hard guardrail. Anything outside it realizes as "not found".

This means:
- searches return only in-lens results
- paths outside LensWorld behave as nonexistent
- you cannot accidentally expand scope by using different tools

**This is intentional** so agents can explore hypotheses freely without managing scope manually.

### Agent Analysis

✅ **Critical principle.** Current enforcement.py should return `NOT_FOUND` rather than `DENY` for paths outside lens in ck3lens mode. This is a subtle but important distinction:
- `DENY` = "you can't do this" (implies it exists)
- `NOT_FOUND` = "this doesn't exist in your world" (simpler mental model)

**TODO:** Verify enforcement.py uses `Decision.NOT_FOUND` correctly for lens violations.

---

## 5. Contracts in ck3lens

Contracts exist to declare intent, scope, and allowed mutations.

Valid ck3lens intent categories:
- COMPATCH
- BUGPATCH
- RESEARCH_MOD_ISSUES
- RESEARCH_BUGREPORT
- SCRIPT_RUN

You must not mutate files without an appropriate contract.

### Agent Analysis

✅ **Already implemented** in `work_contracts.py`. Current intent types align well.

---

## 6. Builder-Daemon and Playsets

When a playset is activated:
- the system checks which mods are already ingested into the database
- missing mods (including vanilla) are queued for processing
- the user is prompted to confirm background processing

If a playset references mods missing on disk:
- those mods are reported
- the playset is considered invalid and cannot be activated

Managed via tools; never manipulate builder state directly.

### Agent Analysis

✅ **Already implemented** via `ck3_get_playset_build_status` and builder daemon.

---

## 7. ck3raven-dev Mode — Purpose and Responsibilities

### 7.1 What ck3raven-dev Exists to Do

ck3raven-dev mode exists to evolve the CK3Raven toolchain itself.

Responsibilities:
- developing parsers, extractors, and builders
- improving database ingestion and query capability
- expanding conflict detection and resolution logic
- strengthening policy enforcement and guardrails
- enabling ck3lens to do its job more effectively

**Broader visibility, but stricter discipline.**

### Agent Analysis

✅ **Well articulated.** The "enabling ck3lens" framing is useful - ck3raven-dev is infrastructure for ck3lens.

---

## 8. Git Workflow (ck3raven-dev)

### 8.1 Per-Contract Branches

Never push directly to main or master.

For each approved contract, create or switch to:
```
agent/<contract_id>-<short_slug>
```

All commits and pushes occur on that branch only.

### 8.2 Merging

Agent does not merge into main/master.
Request review and let the user merge.

### Agent Analysis

✅ **Just implemented** in Phase 1. The `work_contracts.py` now has `create_contract_branch()` and `get_branch_name()`.

**Current implementation:** Branch creation is optional (parameter to `open_contract`). Consider making it mandatory for ck3raven-dev mode.

---

## 9. Implementation Notes

### 9.1 Order of Operations

**Critical:** WorldAdapter/LensWorld visibility check must come BEFORE enforcement.

Correct order:
1. **WorldAdapter.resolve()** - Is this path visible? → NOT_FOUND if not
2. **enforce_policy()** - Is this operation allowed? → DENY/REQUIRE_TOKEN if not
3. **Implementation** - Perform the operation

**Current issue:** Phase 2 wiring added enforcement at tool boundary, but raw file writes still have WorldAdapter check in the helper. Need to verify consistent ordering.

### 9.2 Todo List Best Practice

Agent todo lists should not overwrite initialization instructions. Options:
1. Include link to dynamic todo file
2. Keep todos in separate working memory
3. Use structured todo tool (already available)

**Recommendation:** Use the `manage_todo_list` tool for active work tracking, keep mode instructions as reference material.

---

## Proposed Changes Summary

| Area | Current State | Proposed Change |
|------|---------------|-----------------|
| Initialization framing | Technical focus | Add "cognitive simplification" framing |
| NOT_FOUND vs DENY | Mixed usage | Consistent NOT_FOUND for lens violations |
| WorldAdapter order | Inconsistent | Always before enforcement |
| Branch creation | Optional | Mandatory for ck3raven-dev |
| Todo handling | Can overwrite | Link to dynamic file or use tool |

---

## Next Steps

1. Review this document for accuracy
2. Decide which proposals to implement
3. Update mode instructions if approved
4. Test initialization flow with new framing

