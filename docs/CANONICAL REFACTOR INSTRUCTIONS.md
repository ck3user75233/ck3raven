================================================================================
CK3LENS / CK3RAVEN — BANNED TERMS, NO-ORACLE LINTER, AND FINAL RESET DIRECTIVES
================================================================================

Status: AUTHORITATIVE RESET
Scope: ck3lens, ck3raven, MCP tools, world adapter, enforcement
Effective: Immediately
Supersedes: All prior informal guidance

This document exists to prevent regression and to allow a clean re-implementation
after refactor loss. Treat it as binding.

-------------------------------------------------------------------------------
1. CORE INVARIANTS (RE-ISSUED, NON-NEGOTIABLE)
-------------------------------------------------------------------------------

1) There is NO permission-check phase.
2) There is exactly ONE enforcement boundary.
3) Visibility describes. Validation checks structure. Enforcement decides.
4) Permission is never queried; it is only enforced.
5) mods[] is the only authoritative mod list.

Any deviation is a violation.

-------------------------------------------------------------------------------
2. BANNED IDEAS (STRONGER THAN BANNED WORDS)
-------------------------------------------------------------------------------

The following IDEAS are forbidden, regardless of naming:

- Asking “am I allowed to do this?” outside enforcement
- Early denial before contract + invariant checks
- Session-level permission logic
- Scope-level permission logic
- Visibility-based denial
- UI metadata influencing execution
- Parallel mod lists
- Derived permission sets
- “Helpful” pre-checks
- “Fail fast” permission logic

If code answers permission anywhere other than enforcement, it is wrong.

-------------------------------------------------------------------------------
3. BANNED TERMS (HARD BAN)
-------------------------------------------------------------------------------

The following terms MUST NOT appear in executable code (except documentation
describing the ban):

Permission / oracle terms:
- can_write
- can_edit
- can_delete
- is_writable
- is_editable
- is_allowed
- is_path_allowed
- is_path_writable
- writable_mod
- editable_mod
- mod_write
- mod_read
- mod_delete

Parallel-list / authority terms:
- local_mods (as an array or list)
- editable_mods
- writable_mods
- live_mods
- mod_whitelist
- whitelist
- blacklist
- mod_roots   (this term is banned — see replacement below)

Any semantic equivalent is also banned.

-------------------------------------------------------------------------------
4. REQUIRED TERMINOLOGY REPLACEMENTS
-------------------------------------------------------------------------------

The following replacements are canonical:

❌ mod_roots
✅ mod_paths
Reason: “roots” implies authority; “paths” describe structure only.

❌ is_writable
✅ ui_hint_potentially_editable
Reason: explicit non-authority, UI-only

❌ local_mods[]
✅ mods[] + path containment check at enforcement

Renaming is not optional; these names encode architectural meaning.

-------------------------------------------------------------------------------
5. NO-ORACLE LINTER (NOW ENFORCED)
-------------------------------------------------------------------------------

This linter is conceptual AND mechanical.

------------------------------------
5.1 Conceptual Lint Rule (Human)
------------------------------------

If a function, method, property, or field answers:
“Can this operation proceed?”

and it is NOT the enforcement boundary, it is a violation.

There is no exception for:
- tests
- WIP code
- sandbox code
- UI helpers
- routing logic

------------------------------------
5.2 Mechanical Lint Rules (Automated)
------------------------------------

Flag as ERROR if ANY of the following are true:

- Identifiers matching:
  can_*
  is_* (when used to gate execution)
  *_writable
  *_editable
  *_allowed

- Control flow that looks like:
  if <something about writable/editable/allowed>:
      deny / return error

- Early returns before enforcement based on metadata

Allowed exceptions:
- Documentation
- Comments explaining the ban
- Pure UI display code with NO control flow impact

------------------------------------
5.3 Enforcement
------------------------------------

- New permission oracles = automatic rejection
- Renaming an oracle = rejection
- Any early-deny logic = rejection
- Linter failures block merge

-------------------------------------------------------------------------------
6. ONE ARRAY RULE (RE-ISSUED)
-------------------------------------------------------------------------------

A playset has EXACTLY ONE mod list:

    mods[]

There are:
- no local_mods[]
- no editable_mods[]
- no writable_mods[]
- no whitelists
- no derived arrays persisted anywhere

Everything derives from mods[] + runtime checks.

-------------------------------------------------------------------------------
7. LOCAL MOD DEFINITION (STRUCTURAL FACT ONLY)
-------------------------------------------------------------------------------

A mod is considered “local” if and only if:

    mod.path is under local_mods_folder

This check:
- is structural
- is path-based
- is not a permission decision
- must only be enforced at the enforcement boundary

-------------------------------------------------------------------------------
8. SESSION OBJECT RULES
-------------------------------------------------------------------------------

Session is DATA-ONLY.

Session may contain:
- mods[]
- playset metadata
- local_mods_folder
- vanilla_root

Session may do:
- lookups (get_mod)

Session MUST NOT:
- answer permission questions
- contain can_* or is_* permission helpers
- cache permission state

-------------------------------------------------------------------------------
9. VISIBILITY AND SCOPE RULES
-------------------------------------------------------------------------------

Visibility layers (WorldAdapter, PlaysetScope):

May:
- resolve paths
- describe where things live
- return structural facts

Must NOT:
- deny execution
- gate routing
- answer permission questions

Structural helpers are allowed ONLY if they describe facts, e.g.:
- path_under_local_mods(path)

-------------------------------------------------------------------------------
10. UI METADATA RULE
-------------------------------------------------------------------------------

UI metadata:
- must be explicitly non-authoritative
- must never affect control flow
- must never deny execution

Any UI metadata used to gate behavior is a violation.

-------------------------------------------------------------------------------
11. ENFORCEMENT (ONLY PLACE DENIAL IS ALLOWED)
-------------------------------------------------------------------------------

All write/delete operations converge here:

1) Contract validation (file_write, file_delete, etc.)
2) Hard invariants (path containment)
3) Execute OR deny

No other layer may deny.

-------------------------------------------------------------------------------
12. TESTING RULE (RE-ISSUED)
-------------------------------------------------------------------------------

Tests MUST:
- attempt operations
- assert enforcement behavior

Tests MUST NOT:
- test permission helpers
- test “can I write?”

-------------------------------------------------------------------------------
13. STOP CONDITION
-------------------------------------------------------------------------------

Once the following are true:
- banned terms removed
- no-oracle linter passes
- MCP smoke tests pass

STOP refactoring.
No “cleanup”, no “improvements”, no “one more rename”.

-------------------------------------------------------------------------------
FINAL STATEMENT
-------------------------------------------------------------------------------

This document is the reset point.

Any future work must conform to:
- NO-ORACLE RULE
- ONE ARRAY RULE
- CENTRALIZED ENFORCEMENT
- STRUCTURAL FACTS ONLY

Deviation requires explicit re-authorization.

================================================================================
END RESET DIRECTIVE
================================================================================

================================================================================
SUPPLEMENTAL ARCHITECTURAL EXPLANATION
WHY `mod_write` IS WRONG AND `file_write` IS CORRECT
================================================================================

Status: SUPPLEMENTAL (REQUIRED READING)
Audience: ck3lens / ck3raven agents and maintainers
Purpose: Explain the architectural reasoning behind the NO-ORACLE RULE
Relation: This document explains the WHY behind the reset directives

-------------------------------------------------------------------------------
1. THE CORE CONFUSION THIS DOCUMENT RESOLVES
-------------------------------------------------------------------------------

Agents repeatedly invent operations like:

- mod_write
- mod_edit
- mod_delete
- write_mod
- editable_mods

These feel intuitive, but they encode a **fundamental architectural mistake**.

This document explains why.

-------------------------------------------------------------------------------
2. MODS ARE NOT OPERABLE ENTITIES
-------------------------------------------------------------------------------

A “mod” is NOT a thing you operate on.

A mod is:
- a directory
- containing files
- referenced by a path
- included in a playset

There is no such operation as “write a mod”.

What actually happens is always:
- writing a FILE
- deleting a FILE
- reading a FILE

Therefore, the only real operations are:
- file_read
- file_write
- file_delete

Anything else is a conceptual lie.

-------------------------------------------------------------------------------
3. WHAT GOES WRONG WHEN YOU INVENT `mod_write`
-------------------------------------------------------------------------------

When you introduce `mod_write`, you implicitly assert all of the following:

1) That a mod is an operable object
2) That mods can have permissions
3) That some mods are writable and others are not
4) That permission can be reasoned about at the mod level
5) That permission can be decided before knowing the file path

All five assumptions are false — and dangerous.

This is how:
- local_mods arrays appear
- editable_mods lists appear
- whitelists appear
- early-deny logic appears
- permission oracles are invented

`mod_write` is the *seed* of architectural drift.

-------------------------------------------------------------------------------
4. FILE OPERATIONS ARE REAL — MOD OPERATIONS ARE NOT
-------------------------------------------------------------------------------

At runtime, the system must answer concrete questions:

- What file is being written?
- What is the absolute path?
- Is this path under local_mods_folder?
- Does the contract allow file_write?

These questions cannot be answered at the “mod” level.

They require a FILE PATH.

Therefore:
- Permission is about FILES
- Enforcement is about PATHS
- Mods only provide CONTEXT

-------------------------------------------------------------------------------
5. WHY `file_write` IS THE ONLY CORRECT OPERATION
-------------------------------------------------------------------------------

`file_write` has the correct properties:

- It maps to an actual filesystem action
- It requires a concrete path
- It can be validated by contracts
- It can be constrained by hard invariants
- It does not invent new permission domains

`file_write` forces enforcement to occur:
- late
- concretely
- centrally

This is exactly what we want.

-------------------------------------------------------------------------------
6. WHY “MOD-LEVEL PERMISSIONS” ARE A DEAD END
-------------------------------------------------------------------------------

The moment you allow yourself to think in terms of “writable mods”:

- You create parallel lists
- You cache decisions prematurely
- You decouple permission from enforcement
- You allow early denial
- You make the system brittle

Even if implemented “correctly”, mod-level permissions:

- cannot represent mixed-path mods
- cannot handle subdirectories safely
- cannot express partial writes
- cannot enforce invariants reliably

They always collapse back into file checks — but too late.

-------------------------------------------------------------------------------
7. THE CORRECT MENTAL MODEL (MEMORIZE THIS)
-------------------------------------------------------------------------------

Say this out loud:

> “Mods do not have permissions.  
> Files have permissions.  
> Mods only give me paths.”

If an operation cannot be expressed as:
- file_read
- file_write
- file_delete

Then it does not belong in the system.

-------------------------------------------------------------------------------
8. HOW THIS RELATES TO THE NO-ORACLE RULE
-------------------------------------------------------------------------------

`mod_write` encourages asking:

“Can I write to this mod?”

That question is illegal.

The only legal question is:

“Am I performing a file_write, and does enforcement allow it?”

This is why:
- mod_write is banned
- file_write is canonical
- permission oracles are forbidden

-------------------------------------------------------------------------------
9. FINAL LOCK-IN STATEMENT
-------------------------------------------------------------------------------

Any future proposal that introduces:
- mod_write
- mod_edit
- writable_mods
- editable_mods
- mod-level permissions

is architecturally invalid by definition.

This is not a preference.
This is a correctness requirement.

================================================================================
END SUPPLEMENTAL EXPLANATION
================================================================================
