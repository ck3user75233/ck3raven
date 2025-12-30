Here’s a serious “take a stab” at an **exhaustive concept taxonomy** for the *current* state of your ecosystem (ck3lens + ck3raven-dev), aimed at preventing exactly the drift you described (duplicate “gates”, “approval”, “hard_*”, etc.). I’m going to list concepts at the level that’s useful for a `CANONICAL_INDEX.md` / `concepts.yaml` ownership map.

This is intentionally a bit over-complete; you can collapse later.

---

## A) Boundary, authority, and safety concepts

1. **Mode selection / active lens**

   * ck3lens vs ck3raven-dev vs (future) ck3creator
   * how mode is chosen, represented, and propagated

2. **Tool boundary / dispatcher**

   * single entrypoint pattern (e.g., `ck3_file` dispatcher)
   * routing to implementation functions

3. **Enforcement decision boundary**

   * ALLOW / DENY / REQUIRE_TOKEN
   * “never oracle” rule
   * one enforcement per tool invocation

4. **Contracts**

   * contract request format, validation, and lifecycle
   * contract-required operations vs contract-optional ones

5. **Token / approval gating**

   * token format, verification, expiry, scope
   * how REQUIRE_TOKEN is satisfied and recorded

6. **Audit logging / attribution**

   * enforce_and_log / logging schema
   * user/agent attribution + session correlation
   * immutable audit artifacts / commit messages conventions

7. **Banned terms / banned ideas compliance**

   * no-oracle invariants
   * anti-parallel-lists invariants
   * enforcement of bans (eventually via linter)

---

## B) Identity, addressing, and world modeling concepts

8. **Canonical addressing scheme**

   * `mod:<name>:<rel_path>`, `vanilla:`, `workshop:`, `wip:`, `ck3raven:`, `launcher_registry:`
   * parsing/serialization rules

9. **WorldAdapter / World resolution**

   * resolve user input → `ResolutionResult(address, absolute_path, domain, ui_hints)`
   * domain classification rules

10. **Path normalization pipeline**

* the single canonical “input → resolve → enforcement target → exec path” flow
* no relpath/abspath derivations elsewhere

11. **LensWorld / scoped visibility model**

* ck3lens: playset-scoped “world”
* (proposed) ck3raven-dev: concept-scoped “working set world”

12. **Playset + launcher state interpretation**

* where playset comes from (launcher JSON / descriptors)
* order, enabled state, dependency expansion

13. **Mods[] data model**

* the “only array rule”
* what fields exist (name, root path, etc.)
* explicit prohibition on derived lists

---

## C) File operation semantics concepts

14. **File mutation operations**

* `file_read`, `file_write`, `file_delete` (and whether `file_edit` is distinct)
* how edit is implemented (read+patch+write?) and validated

15. **Syntax / schema validation**

* Python syntax validation (if required)
* CK3 script validation / lint (if any)
* “validation is correctness, not permission”

16. **Filesystem scope rules**

* ck3lens: writes only under mods[] roots (enforced)
* ck3raven-dev: repo paths / dev scope rules (enforced)

17. **Error model / return conventions**

* how DENY/REQUIRE_TOKEN is represented (no PermissionError if you standardize on Decision returns)
* consistent tool error payload format

---

## D) CK3 domain parsing and compatching concepts (ck3raven core)

18. **CK3 file type classification**

* how you categorize files into domains (common/, events/, decisions/, gui/, localization/, etc.)

19. **CK3 “load order semantics” model**

* overwrite/append/merge behaviors by file/type/keyword
* on_action append semantics + effect overwrite, etc.

20. **Parser / AST representation (CK3 script)**

* tokenization / parsing
* AST nodes, IDs, blocks, keyword merging logic

21. **Virtual merge model**

* what you can safely “compose” vs what must be replaced wholesale
* per-domain merge strategies

22. **Conflict discovery**

* file-level conflicts (same path across mods)
* ID-level conflicts (same object id within a file/domain)
* conflict unit key scheme

23. **Conflict ranking / separability heuristic**

* what is “separately resolvable”
* entanglement detection

24. **Resolver strategies**

* tradition-only resolver (your earlier request)
* domain-specific resolvers (on_actions, scripted_effects, buildings, etc.)

25. **Output generation**

* compatch output folder layout
* plan/audit files
* reproducible build artifacts

26. **Diff guard / anti-shadow-pipeline mechanisms**

* preventing ad-hoc scripts from becoming architecture
* ensuring changes land in core modules, not one-off scripts

---

## E) UX / tooling integration concepts

27. **MCP server**

* server bootstrapping
* tool registration and exposure

28. **VS Code extension UI model**

* state objects / JSON contracts
* lens selector widget
* conflict report UI

29. **Trace/logging for MCP activities**

* structured trace events
* storage location and retention
* privacy boundaries (if relevant)

---

## F) Build, test, and maintenance concepts

30. **Test harness / golden tests**

* canonical places for test scripts and outputs
* fixtures for CK3 parsing and merging

31. **CI checks**

* import sanity checks
* lint gates (no-oracle, banned terms)
* formatting / typing

32. **Versioning / compatibility**

* CK3 version support
* mod compatibility metadata

---

# How to turn this into something enforceable (without guessing)

Even if this list is 80–90% right, the next step to make it *exhaustive in your repo* is mechanical:

* Start a `architecture/concepts.yaml`
* Seed it with the 32 concepts above
* Then add an agent rule: **every time the agent touches a file, it must tag the change with one (or more) concept IDs**
* After a week, you’ll see missing concept buckets immediately (because changes won’t fit neatly)

If you want, I can format the above into a ready-to-paste `concepts.yaml` skeleton (with IDs, descriptions, and “owner_modules” placeholders), but you said “take a stab at the exhaustive list” — so I kept this at the taxonomy level.

If you tell me whether you want the concept list to be **coarse (~20 concepts)** or **fine-grained (~60 concepts)**, I’ll normalize it into the right granularity for your enforcement map.
