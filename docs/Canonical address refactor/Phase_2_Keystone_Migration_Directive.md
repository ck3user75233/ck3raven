# Phase 2 — Keystone Tool Migration Directive (Authoritative)

> **Issued:** February 17, 2026 — Nate  
> **Status:** Active  
> **Supersedes:** Nothing (extends Sprint 0 Canonical Addressing Refactor)  
> **Prerequisite:** Sprint 0 formally verified (92/92, mutation-tested, clean git, purity gate standalone pass)

---

Team — Sprint 0 is now **formally verified** (not just "green"). We have full collateral: raw pytest output (92/92), durations, mutation sensitivity proof, clean git state, and standalone purity gate pass. This means WA2 addressing + VisibilityRef + leak detector + purity gate are validated as a reliable substrate.

We are **not** doing a big-bang migration of all tools. Instead we will expand WA2 addressing authority via a controlled "keystone tool" approach, and only then proceed with broader Phase 2.1 deterministic gates.

---

## 0) Sprint 0 Validation Wrap-up (Lock + Tag)

### Required actions (complete immediately)

1. **Freeze Sprint 0**: no further changes to Sprint 0 tests or WA2 semantics unless Nate explicitly re-opens.
2. **Record verification artifacts** in a single markdown file committed to the repo (e.g., `docs/phase2/sprint0_validation_receipts.md`) containing:

   * full pytest header+summary
   * `--durations=20` output
   * mutation description + failing tests list + revert confirmation
   * `git rev-parse HEAD`, `git status --porcelain`, `git diff --stat`
   * purity gate standalone run output
3. **Tag the verified commit** (or note the commit hash in the receipts doc).

*(This is governance hygiene — prevents "we were green once" drift.)*

---

## 1) Immediate Next Step: Expand WA2 Addressing Authority via Keystone Tools

We will migrate **three tools** to WA2 addressing before continuing Phase 2.1 gates rollout:

* **ck3_file** (mandatory)
* **ck3_exec** (mandatory)
* **One additional keystone tool (agent selects)**

### 1.1 Keystone tool selection criteria (for the agent-chosen 3rd tool)

Pick the tool that best satisfies these:

* High-frequency usage OR high-risk I/O surface
* Exercises a different addressing pattern than ck3_file / ck3_exec
* Touches reads + writes OR directory traversal
* Historically associated with path ambiguity / visibility issues

Provide Nate a one-paragraph justification for the chosen 3rd tool.

---

## 2) Non-Negotiable Migration Rule

**A tool must be fully on WA2 addressing before any Phase 2.1 deterministic gates are added to that tool.**

And:

**No tool may use both v1 world_adapter and WA2 in the same codepath.**

Migration is tool-by-tool, clean cutover.

---

## 3) Migration Scope for Each Tool (ck3_file, ck3_exec, chosen keystone)

For each tool migration, implement the following:

### 3.1 Replace path input handling with WA2 resolve()

* All user/agent-provided paths must be parsed via **WA2 `resolve()`**.
* Canonical accepted inputs:

  * `root:<key>/<path>`
  * `mod:<name>/<path>`
* Legacy inputs are accepted only if Sprint 0 normalization rules already accept them; all outputs must emit canonical form only.

### 3.2 VisibilityRef usage requirements

* Tool must not store/emit host-absolute paths.
* Tool must use `VisibilityRef` token workflow:

  * resolve → token minted → registry stores host path
  * tool obtains host path only via `wa2.host_path(ref)`
* After every Success reply, run leak detector on reply payloads (or ensure the existing guard is applied to reply emission).

### 3.3 Existence semantics (must be explicit)

* For operations that **read/list/execute an existing file**:

  * call `resolve(..., require_exists=True)`
* For operations that **create/overwrite** where the target may not exist:

  * call `resolve(..., require_exists=False)` and use `res.exists` to decide behavior
* **Never truncate** paths for non-existent targets. The full requested canonical path must be preserved in session_abs.

### 3.4 Unified failure surface

Tool must not reveal whether a failure was:

* invisible root
* missing file
* traversal escape
* unknown mod

Agent-visible failures remain generic:

* "Invalid path / not found" (or canonical Invalid reply code)

---

## 4) Testing Requirements Per Migrated Tool

### 4.1 "Tool Migration Test Battery" (new tests)

For each migrated tool:

* Add tests proving:

  * canonical address inputs succeed
  * host-path inputs are rejected
  * traversal escapes rejected
  * output contains only canonical `root:` / `mod:` paths
  * leak detector passes on all success replies
  * `require_exists=True` fails for missing targets
  * `require_exists=False` succeeds with `exists=False` for structurally valid non-existent targets (when relevant)
  * **no truncation** in any case

### 4.2 Mutation Sensitivity (required once per tool category)

For one of the migrated tools (pick the highest-risk), perform a controlled mutation to prove tests fail:

* example mutations:

  * bypass leak detector
  * allow host-absolute path through
  * allow `..` escape
    Then revert and re-run green.

### 4.3 Purity Gate extension

Extend purity gate rules to enforce:

* migrated tool module(s) must not import v1 world_adapter
* v1 tool modules must not import WA2 unless explicitly part of the migrated set
* no mixed imports in shared utility modules

---

## 5) ck3_exec Special Rule (because it is a loophole vector)

ck3_exec is inherently dangerous. For the WA2 migration, enforce:

* Script path (if any) must be a `VisibilityRef`-resolved path under visible roots.
* If ck3_exec supports inline `-c` code:

  * treat as restricted surface; ensure no mechanism allows emitting host paths.
  * ensure outputs are leak-scanned.

No additional gating logic is required yet — just the addressing cutover + leak safety.

---

## 6) Deliverables

For each tool migration (ck3_file, ck3_exec, keystone #3):

1. A short migration note (markdown) containing:

   * which paths are accepted
   * which operations use require_exists True vs False
   * examples of canonical inputs + outputs
2. Test file(s) added and passing
3. Proof of:

   * full pytest run green
   * purity gate run green

---

## 7) Stop Condition / Review Point

After all three keystone tools are migrated and tests are green:

* Stop and report:

  * chosen 3rd tool + justification
  * summary of code changes (high-level)
  * any newly discovered semantic edge cases vs v1
  * confirmation that outputs never include host paths

Only after Nate reviews this report do we resume Phase 2.1 deterministic gates rollout broadly.
