# CK3RAVEN-DEV Policy Architecture

> **Status:** CANONICAL - Ready for Implementation  
> **Scope:** `ck3raven-dev` agent mode ONLY  
> **Last Updated:** December 27, 2025

---

## 1. Purpose of ck3raven-dev Mode

**ck3raven-dev exists to develop, maintain, and evolve the CK3Raven infrastructure itself.**

This includes:
- MCP server code
- Database ingestion pipelines
- AST/symbol extraction
- Policy enforcement logic
- Command-line wrapper (`ck3_exec`)
- Agent tooling

It does **NOT** exist to:
- Edit CK3 mods
- Manipulate playsets
- Perform compatching
- Debug gameplay content directly

Those tasks belong to **ck3lens mode**.

---

## 2. Core Design Principles

> **ck3raven-dev operates on infrastructure source code and controlled execution environments.**
> **It must never modify CK3 mods, playsets, or user content.**

### Core Invariants

1. **ck3raven-dev may modify CK3Raven source code** (with contract)
2. **ck3raven-dev may not modify CK3 mods of any kind** (absolute prohibition)
3. **ck3raven-dev may execute shell commands only through the policy-wrapped command layer** (`ck3_exec`)
4. **All destructive or irreversible operations require explicit approval**
5. **Git history integrity is protected by default**

These are enforced by **hard gates**, not agent judgment.

### Anti-Sloppy Principle

> ck3raven-dev is allowed to be powerful, but never allowed to be sloppy.

Every allowance (Tier A tokens, WIP scripts) exists to reduce friction, not to bypass fixing the system properly.

If the agent feels "it's easier to just script around this than fix it" — that is a **policy violation signal**, not a productivity win.

---

## 3. Scope Domains

| Scope Domain | What It Represents | Visibility | Read | Write/Edit | Delete/Move | Access Mechanism |
|--------------|-------------------|------------|------|------------|-------------|------------------|
| **CK3RAVEN_SOURCE** | MCP server, policy logic, tooling | Always visible | ✅ | ✅ (contract) | 🔶 (approval) | `ck3_file`, git |
| **CK3RAVEN_DATABASE** | Ingested mod & vanilla data | Always visible | ✅ | 🔶 (migration only) | ❌ | DB layer |
| **CK3RAVEN_WIP** | Session-local scratch workspace (see Section 8.1) | Visible | ✅ | ✅ (restricted) | ✅ | FS / `ck3_exec` |
| **CK3_EXECUTION_ENV** | Shell / Python execution | N/A | N/A | 🔶 | 🔶 | `ck3_exec` only |
| **CK3_MODS_READ** | All mod content (for parser/ingestion) | Visible | ✅ | ❌ | ❌ | DB queries OR filesystem (see Section 3.1) |
| **CK3_MODS_WRITE** | Any mod file modification | **Invisible** | ❌ | ❌ | ❌ | **PROHIBITED** |
| **USER_HOME_FS** | Arbitrary filesystem | **Invisible** | ❌ | ❌ | ❌ | **PROHIBITED** |

### Key Clarifications

- **Mods are READ-ONLY**: ck3raven-dev can read mod content but cannot write to any mod files.
- **WIP is restricted**: Unlike ck3lens WIP (general purpose), ck3raven-dev WIP has strict intent constraints (see Section 8).
- **No raw terminal**: All execution goes through `ck3_exec`, never `run_in_terminal`.

### 3.1 Mod Filesystem Read Access

ck3raven-dev may read mod files **directly from the filesystem** for:
- Parser development and testing
- Ingestion and rebuild workflows
- Database construction and validation
- Builder wizard functionality

**Boundaries:**
- This read access does **not** imply permission to modify mod contents
- This read access does **not** bypass the database as the system of record for analysis and tooling
- For analysis, querying, and tool operations, the **database is authoritative** — direct filesystem reads are for infrastructure purposes only

---

## 4. Absolute Prohibitions (Hard Gates)

These are **non-overridable**, even with user request:

| Prohibition | Result |
|-------------|--------|
| Editing **any CK3 mod file** (local, workshop, vanilla) | AUTO_DENY |
| Using `run_in_terminal` directly | AUTO_DENY |
| Git history rewrite without approval token | AUTO_DENY |
| Database write without migration context | AUTO_DENY |
| Filesystem access outside repo/WIP | AUTO_DENY |
| WIP script with unapproved intent | AUTO_DENY |
| WIP script substituting for core code fix | AUTO_DENY |

> If user asks for prohibited operations, redirect to ck3lens mode or deny with explanation.

---

## 5. Intent Types (Contract Level)

Every contract must declare exactly one `Ck3RavenDevIntentType`. Missing → AUTO_DENY.

| Intent Type | Description | Typical Scope |
|-------------|-------------|---------------|
| **BUGFIX** | Fix incorrect or broken behavior in existing code | Narrow, specific files |
| **REFACTOR** | Structural improvement without changing behavior | May span multiple files |
| **FEATURE** | New capability or functionality | New files + integrations |
| **MIGRATION** | One-time transformations (schemas, layouts, compatibility) | Controlled, with rollback |
| **TEST_ONLY** | Adding, modifying, or fixing tests only | `tests/` directory |
| **DOCS_ONLY** | Documentation changes only | `.md` files, docstrings |

### Domain Model

Contracts must also declare `canonical_domains` which identify what areas are in scope. Domains come in two categories:

**Product Domains** (what the code does):
- `parser` - CK3 script parsing, AST generation
- `routing` - Request routing, resolution
- `builder` - Database build/ingestion pipeline
- `extraction` - Symbol extraction, reference linking
- `query` - DB query layer, search APIs
- `cli` - CLI entry points

**Repo Domains** (where changes go):
- `docs` - Documentation files (`docs/**`, `*.md`)
- `tools` - MCP tools, wrappers, utilities (`tools/**`)
- `tests` - Unit tests, fixtures (`tests/**`)
- `policy` - Policy engine, contracts, gates (`ck3lens/`)
- `config` - Config files (`*.yaml`, `*.toml`, `pyproject.toml`)
- `wip` - WIP scripts and scratch artifacts (`.wip/**`)
- `ci` - CI workflows (`.github/workflows/**`)
- `scripts` - Utility scripts (`scripts/**`)
- `src` - Main source code (`src/ck3raven/**`)

Both product and repo domains are valid for contracts. Use product domains when work is conceptually about a subsystem, use repo domains when work is about a repository surface (like documentation).

### Rules

- Intents are **mutually exclusive** per contract
- If work spans multiple intents, **split into multiple contracts**
- `TEST_ONLY` and `DOCS_ONLY` enable fast-path approval (simpler gates)

---

## 6. Contract Requirements

### Required for All Write Operations

- `intent_type`: One of the approved intents
- `affected_subsystems`: Which modules/areas are touched
- `target_files`: Expected file set (see resolution rules below)
- `rollback_plan`: How to undo changes
- `test_plan`: How to verify correctness

### Target Files Resolution Rules

**Approximate target_files are permitted only during discovery or planning phases.**

Before any write/edit operation executes:
1. `target_files` must be resolved to a **concrete, enumerated list**
2. The resolved list is enforced by **DIFF_SANITY** acceptance test
3. Any file touched that was not in the resolved list → operation fails

This preserves flexibility during planning while keeping execution deterministic and auditable.

### Additional Requirements by Intent

| Intent | Additional Requirements |
|--------|------------------------|
| BUGFIX | Evidence of bug (error message, failing test) |
| REFACTOR | Confirmation behavior unchanged |
| FEATURE | Design rationale |
| MIGRATION | Exit condition, one-time confirmation |
| TEST_ONLY | None additional |
| DOCS_ONLY | None additional |

### What Contracts Do NOT Do

- Contracts **do not** grant access to mods
- Contracts **do not** expand scope domains
- Contracts **do not** bypass approval requirements

---

## 7. Token System

### Tier A — Capability Tokens (Auto-Grant)

These are auto-granted because they don't expand scope:

| Token Type | Purpose | Scope Constraints |
|------------|---------|-------------------|
| `TEST_EXECUTE` | Run test suites (pytest) | Repository test directories only, no network, no writes outside test artifacts |
| `SCRIPT_RUN_WIP` | Execute approved WIP script | Bound to script hash + contract ID + TTL, reusable within contract (see scope limits below) |

**SCRIPT_RUN_WIP Scope Limits:**
`SCRIPT_RUN_WIP` authorizes execution of an approved WIP script **only within the file/path scope declared in the active contract**. It does not grant permission to modify additional files or paths, even if the script is technically capable of doing so. The token enables execution, not scope expansion.
| `READ_SAFE` | Read-only access to repo files in declared scope | No traversal, no writes |

**Rule:** If a token allows new files, new paths, or new capabilities → it is NOT Tier A.

### Tier B — Approval Tokens (User Required)

| Token Type | Purpose | TTL |
|------------|---------|-----|
| `DELETE_SOURCE` | Delete ck3raven source files | 15 min |
| `GIT_FORCE_PUSH` | Force push to remote | 10 min |
| `GIT_REWRITE_HISTORY` | Rebase, reset --hard, commit --amend | 15 min |
| `DB_MIGRATION_DESTRUCTIVE` | Destructive database migration | 15 min |
| `FS_WRITE_OUTSIDE_CONTRACT` | Emergency write outside contract scope | 30 min |
| `BYPASS_CONTRACT` | Skip contract check (emergency, logged) | 5 min |

Approval UI must be **distinct from generic VS Code prompts**.

---

## 8. WIP Scripts (Strict Constraints)

### 8.1 WIP Directory Location (Structural Invariants)

`CK3RAVEN_WIP` has the following non-negotiable properties:

| Property | Value | Notes |
|----------|-------|-------|
| Location | `<ck3raven-repo>/.wip/` | Single, fixed directory under repository root |
| Git status | `.gitignore`d | Never committed |
| Relocatable | **NO** | Not configurable or relocatable by agents |
| Session lifecycle | Auto-wiped on new session | Best effort cleanup |

Agents may not comply "in spirit" while relocating WIP to uncontrolled paths. The fixed location is a hard constraint.

### 8.2 The Core Problem

> ck3raven-dev agents have a tendency to solve problems by writing standalone scripts instead of fixing underlying source code. This results in shadow implementations and is unacceptable.

### 8.3 Approved WIP Intents

Only these three `Ck3RavenDevWipIntent` values are valid:

| WIP Intent | Purpose | Example |
|------------|---------|---------|
| **ANALYSIS_ONLY** | One-off analysis, inspection, validation (read-only) | "Count symbols by type across all files" |
| **REFACTOR_ASSIST** | Generate edits, scaffolding, diffs for core source | "Generate migration script for schema change" |
| **MIGRATION_HELPER** | One-time transformation with defined exit condition | "Convert old config format to new format" |

**Any other intent → AUTO_DENY**

### 8.4 Explicitly Forbidden Uses

WIP scripts must **NEVER** be used to:
- Implement production/runtime logic
- Replace or shadow core functionality
- Bypass fixing a bug in core source
- Act as long-term workaround or "temporary fix"
- Duplicate ingestion, indexing, or pipeline logic
- Start servers, dispatch tools, or run runtime entrypoints
- Become required runtime dependencies

> If a script is required to "make the system work," the system itself must be fixed instead.

### 8.5 WIP Script Contract Requirements

Every WIP script contract must include:

1. `wip_intent`: One of `ANALYSIS_ONLY`, `REFACTOR_ASSIST`, `MIGRATION_HELPER`
2. `exit_condition`: When/how the script is no longer needed
3. `expected_artifacts`: What the script produces
4. `runtime_dependency_confirmation`: "false" (artifacts are NOT runtime dependencies)
5. For REFACTOR_ASSIST/MIGRATION_HELPER: `core_change_plan` listing files to be modified as result

### 8.7 Import Rules (The Converse Rule)

WIP scripts:
- **MAY** import core modules for: reading/parsing structures, offline analysis, generating patches, verification
- **MUST NOT**: call runtime entrypoints, start servers, dispatch tools, create alternate execution paths

> Importing core code to **read or transform** is acceptable.
> Importing core code to **run the system** is not.

### 8.6 Enforcement

- WIP directory is `.gitignore`d (see Section 8.1)
- WIP directory is auto-wiped on new session (best effort)
- No WIP script may be imported or referenced by core code

**Workaround Detection (Deterministic Rule):**
> Executing the same WIP script hash more than once within a contract window without any corresponding core source code changes constitutes workaround behavior and **must be denied**.

This is enforced as a hard gate:
- First execution of script hash X → allowed
- Second execution of script hash X → check for core source changes since first execution
- If no core changes → AUTO_DENY with message: "Repeated script execution without core changes detected"

### 8.8 Summary Principle

> **WIP scripts may ASSIST code changes, but may never SUBSTITUTE for code changes.**

---

## 9. Git Operations Policy

### Allowed Without Approval

- `git status`
- `git diff`
- `git log`
- `git add`
- `git commit` (normal, no --amend)
- `git push` (non-force push)
- `git pull`

### Requires Approval Token

| Operation | Token Required |
|-----------|----------------|
| `git push --force` | `GIT_FORCE_PUSH` |
| `git reset --hard` | `GIT_REWRITE_HISTORY` |
| `git rebase` | `GIT_REWRITE_HISTORY` |
| `git commit --amend` | `GIT_REWRITE_HISTORY` |
| `git checkout -B` (force branch) | `GIT_REWRITE_HISTORY` |

### Implementation

- Git command classifier in `ck3_exec` categorizes commands
- Unclassified git commands → blocked by default
- All git operations logged with justification
- History-rewriting operations require explicit approval (amend, rebase, force push)
- Non-destructive operations (commit, push) are allowed with active contract

---

## 10. Database Write Policy

The CK3Raven database is **not** a general-purpose mutable store.

### Allowed (With Migration Context)

- Schema migrations via migration framework
- Re-ingestion routines (controlled)
- Index rebuilds
- Controlled data transformations

### Forbidden

- Manual data patching
- Ad-hoc row edits
- "Fixing" mod data directly
- Direct SQL writes without migration wrapper

### Requirements for DB Writes

- Explicit migration context
- Rollback plan
- Approval token for destructive operations (`DB_MIGRATION_DESTRUCTIVE`)

---

## 11. Command Execution (`ck3_exec`)

All shell/Python execution must go through `ck3_exec`, never direct terminal access.

### Allowed Uses

- Running tests
- Running ingestion jobs
- Running migrations
- Running linters/formatters
- Executing approved WIP scripts

### Prohibited Uses

- Raw shell without policy (`run_in_terminal`)
- Git history rewrites without approval
- Arbitrary filesystem traversal
- Commands outside repo/WIP scope

### Logging Requirements

Every `ck3_exec` invocation logs:
- Command executed
- Working directory
- Contract context (if any)
- Token used (if any)
- Exit code and output summary

---

## 12. Relationship to ck3lens Mode

### Correct Workflow

1. ck3lens detects infrastructure issue
2. ck3lens files structured bug report
3. **New session** starts in ck3raven-dev
4. Fix implemented in infrastructure
5. Tool redeployed
6. ck3lens resumes work

### Anti-Patterns (Disallowed)

- ck3lens "quick fix" to infrastructure
- ck3raven-dev editing mods to "test"
- Blended mode responsibilities
- Mode switching within single task

---

## 13. Hard Gates Summary

| Condition | Result |
|-----------|--------|
| Any mod file write (local, workshop, vanilla) | AUTO_DENY |
| Raw terminal access (`run_in_terminal`) | AUTO_DENY |
| Git history rewrite without approval | AUTO_DENY |
| DB write without migration context | AUTO_DENY |
| Filesystem access outside repo/WIP | AUTO_DENY |
| WIP script with unapproved intent | AUTO_DENY |
| WIP script without exit condition | AUTO_DENY |
| WIP script as runtime dependency | AUTO_DENY |
| Missing intent_type on contract | AUTO_DENY |
| Contract spanning multiple intents | AUTO_DENY |

---

## Appendix A: Quick Reference - What Can ck3raven-dev Do?

| Action | Allowed? | Requirements |
|--------|----------|--------------|
| Read ck3raven source | ✅ | None |
| Read mod content (DB) | ✅ | For parser/debugging only |
| Read database | ✅ | None |
| Write ck3raven source | 🔶 | Contract |
| Delete ck3raven source | 🔶 | Contract + Token |
| Run tests | ✅ | Tier A token (auto) |
| Run WIP scripts | 🔶 | Approved intent + contract |
| Git commit | ✅ | None |
| Git push | 🔶 | Token |
| Git rebase/amend | 🔶 | Token |
| DB migration | 🔶 | Migration context |
| Write to mods | ❌ | Never |
| Use run_in_terminal | ❌ | Never |
| Filesystem traversal | ❌ | Never |

---

## Appendix B: Implementation Checklist

### Phase 1: Type Definitions
- [ ] Create `Ck3RavenDevScopeDomain` enum
- [ ] Create `Ck3RavenDevIntentType` enum (BUGFIX, REFACTOR, FEATURE, MIGRATION, TEST_ONLY, DOCS_ONLY)
- [ ] Create `Ck3RavenDevWipIntent` enum (ANALYSIS_ONLY, REFACTOR_ASSIST, MIGRATION_HELPER)
- [ ] Create `Ck3RavenDevTokenType` enum (Tier A + Tier B)

### Phase 2: Hard Gates
- [ ] Add ck3raven-dev hard gates to `hard_gates.py`
- [ ] Gate: mod write prohibition
- [ ] Gate: run_in_terminal prohibition
- [ ] Gate: git history protection
- [ ] Gate: DB write without migration
- [ ] Gate: WIP intent validation

### Phase 3: Git Command Classification
- [ ] Add git command classifier in `ck3_exec` or dedicated module
- [ ] Categorize: safe (status, diff, log, add, commit) vs risky (push, rebase, amend)
- [ ] Block unclassified git commands by default
- [ ] Bind risky git ops to approval tokens

### Phase 4: WIP Workspace Constraints
- [ ] Add ck3raven-dev WIP intent validation
- [ ] Enforce exit condition requirement
- [ ] Enforce core_change_plan for REFACTOR_ASSIST/MIGRATION_HELPER
- [ ] Add workaround detection (repeated script execution without source changes)

### Phase 5: Mode Initialization
- [ ] Update `ck3_get_mode_instructions()` for ck3raven-dev
- [ ] Return policy context with scope domains
- [ ] Initialize WIP workspace with ck3raven-dev constraints
- [ ] Log mode activation

### Phase 6: DB Write Guardrails
- [ ] Wrap DB writes with migration context requirement
- [ ] Require rollback plan for destructive operations
- [ ] Add `DB_MIGRATION_DESTRUCTIVE` token requirement

### Phase 7: Documentation
- [ ] Update `.github/COPILOT_RAVEN_DEV.md` with new policy
- [ ] Update `copilot-instructions.md` with ck3raven-dev summary
- [ ] Delete V2 document from Downloads

---

## Appendix C: Contract Examples

### Example: BUGFIX Contract

```yaml
intent_type: BUGFIX
affected_subsystems: ["parser/lexer.py"]
target_files: ["src/ck3raven/parser/lexer.py"]
evidence: "Parse failure on file X with error: unexpected token..."
rollback_plan: "Revert commit"
test_plan: "Run pytest tests/parser/ and verify file X parses"
```

### Example: REFACTOR Contract

```yaml
intent_type: REFACTOR
affected_subsystems: ["db/", "resolver/"]
target_files: 
  - "src/ck3raven/db/schema.py"
  - "src/ck3raven/resolver/sql_resolver.py"
behavior_unchanged_confirmation: true
rollback_plan: "Revert to commit abc123"
test_plan: "Full test suite passes, manual verification of query results"
```

### Example: WIP Script Contract (REFACTOR_ASSIST)

```yaml
wip_intent: REFACTOR_ASSIST
script_path: "~/.ck3raven/wip/generate_migration.py"
script_hash: "sha256:abc123..."
exit_condition: "Migration applied and verified"
expected_artifacts: 
  - "migration_001.sql"
  - "diff_preview.txt"
runtime_dependency_confirmation: false
core_change_plan:
  - "src/ck3raven/db/schema.py"
  - "src/ck3raven/db/migrations/001_add_index.py"
```
