# AI-Assisted Development: Guardrails & Best Practices

> **Context:** Response to user questions about AI instruction length, guardrails, and best practices for ck3raven development  
> **Date:** December 18, 2025

---

## Part 1: Documentation Review

### Current Documentation Structure

The documentation is actually well-organized across multiple levels:

```
ck3raven/
├── README.md                          # Project overview, architecture, quick start
├── docs/                              # Core design documents (00-07)
│   ├── README.md                      # Doc index + project status
│   ├── 00_ORIGINAL_CONCEPT.md         
│   ├── 01_PARSER_AND_MERGER_CONCEPTS.md
│   ├── 02_EXISTING_TOOLS_AND_FEASIBILITY.md
│   ├── 03_TRADITION_RESOLVER_V0_DESIGN.md
│   ├── 04_VIRTUAL_MERGE_EXPLAINED.md
│   ├── 05_ACCURATE_MERGE_OVERRIDE_RULES.md
│   ├── 06_CONTAINER_MERGE_OVERRIDE_TABLE.md
│   └── 07_TEST_MOD_AND_LOGGING_COMPATCH.md
│
└── tools/
    ├── ck3lens_mcp/                   # MCP Server
    │   ├── README.md                  # ✅ Exists - architecture, quick start, tool list
    │   └── docs/
    │       ├── DESIGN.md              # ✅ 1025 lines - full UI/architecture spec
    │       ├── SETUP.md               # ✅ Installation guide
    │       ├── TESTING.md             # ✅ Validation procedures
    │       └── TOOLS.md               # ✅ Complete tool reference
    │
    └── ck3lens-explorer/              # VS Code Extension
        └── README.md                  # ✅ Exists - 132 lines, features, commands
```

**Assessment:** Documentation coverage is actually comprehensive. The 00-07 docs are foundational design documents (not sequential chapters needing 08, 09, etc.). Both ck3lens_mcp and ck3lens-explorer have READMEs and appropriate subdocs.

**Potential improvements:**
1. Add `tools/ck3lens-explorer/docs/` folder with ARCHITECTURE.md if extension grows
2. Add `docs/08_EMULATOR_DESIGN.md` when Phase 2 work begins
3. Keep `.github/` for AI-specific instructions (separate from user/dev docs)

---

## Part 2: AI Instruction Length

### Are Long Instructions Effective?

**You are correct** - excessively long instructions degrade AI performance:

| Instruction Length | Effect |
|-------------------|--------|
| < 500 words | ✅ Fully retained, consistently followed |
| 500-2000 words | ⚠️ Mostly retained, occasional drift |
| 2000-5000 words | 🔶 Selective retention, core rules remembered |
| > 5000 words | ❌ Significant information loss, contradictions |

**Our current files:**
- `COPILOT_RAVEN_DEV.md` - ~2000 words (acceptable)
- `COPILOT_LENS_COMPATCH.md` - ~1500 words (good)
- Original `copilot-instructions.md` - ~3500 words (too long)

### Recommendations

1. **Keep mode-specific files short** (< 2000 words)
2. **Use reference links** instead of duplicating content
3. **Prioritize actionable rules** over background knowledge
4. **Test instruction effectiveness** by asking agent to repeat key rules

---

## Part 3: Guardrails for ck3raven Development

### Problem: AI Workarounds That Bypass Infrastructure

You've identified a critical issue: When a tool fails, AI tends to:
1. Create ad-hoc workarounds (e.g., raw regex instead of parser)
2. Create duplicate utilities (e.g., check_db.py when db.status() exists)
3. Silently fail and proceed with incorrect conclusions
4. Not report/fix the original bug

### Proposed Guardrails

#### Guardrail 1: Anti-Duplication Check
**Rule:** Before creating any new file or function, agent MUST search for existing implementations.

```markdown
## MANDATORY: Anti-Duplication Check

Before creating ANY new:
- Script in scripts/
- Function in src/ck3raven/
- Tool in tools/

You MUST:
1. `grep_search` for the core functionality
2. `file_search` for similar filenames
3. List 3 existing modules that might already provide this

If similar functionality exists:
- USE the existing implementation
- FIX bugs in existing code instead of bypassing
- EXTEND existing modules instead of creating parallel ones

NEVER create ad-hoc scripts to work around broken infrastructure.
```

#### Guardrail 2: Bug Escalation
**Rule:** When a tool/module fails, treat it as a bug to fix, not an obstacle to bypass.

```markdown
## MANDATORY: Bug Escalation Protocol

When ANY ck3raven tool returns an error:

1. STOP - Do not work around it
2. DIAGNOSE - What is the actual error?
3. LOCATE - Which module/function failed?
4. FIX - Propose a fix to the source code
5. VERIFY - Test the fix

NEVER:
- Use raw SQL when db modules fail (fix the db module)
- Use regex when parser fails (fix the parser)
- Create scripts to check what tools should report (fix the tools)
```

#### Guardrail 3: Tool Consistency
**Rule:** All database access goes through established layers.

```markdown
## MANDATORY: Code Layer Boundaries

| Layer | Location | Purpose | Never Bypass |
|-------|----------|---------|--------------|
| MCP Tools | tools/ck3lens_mcp/ | AI access point | Direct file I/O |
| DB Module | src/ck3raven/db/ | Data access | Raw SQL in scripts |
| Parser | src/ck3raven/parser/ | AST generation | Regex parsing |
| Resolver | src/ck3raven/resolver/ | Conflict resolution | Manual merge logic |

If you need functionality not in these layers:
1. Add it to the CORRECT layer
2. Expose through proper APIs
3. Never create parallel implementations
```

#### Guardrail 4: File Creation Boundaries
**Rule:** In ck3raven-dev mode, only create files inside the ck3raven folder.

```markdown
## MANDATORY: File Creation Boundaries

When working in ck3raven-dev mode:

ALLOWED file creation locations:
- ck3raven/src/          (source code)
- ck3raven/scripts/      (development scripts)
- ck3raven/tests/        (test files)
- ck3raven/tools/        (MCP server, extensions)
- ck3raven/docs/         (documentation)
- ck3raven/.github/      (AI instructions, workflows)

NEVER create files in:
- AI Workspace/ root     (parent folder, not part of project)
- CK3 game folders       (read-only game content)
- User mod folders       (managed by users, not tooling)
- Temp/scratch locations (use proper project structure)

If you need a test script: put it in ck3raven/scripts/
If you need a utility: add to appropriate src/ module
If you need documentation: put in ck3raven/docs/

RATIONALE: Keeps project organized, prevents orphaned files, maintains clean workspace.
```

#### Guardrail 5: Validation Before Conclusion
**Rule:** Verify search results before concluding "not found."

```markdown
## MANDATORY: Existence Verification

Before concluding something does NOT exist:

1. Use `ck3_confirm_not_exists` (exhaustive fuzzy search)
2. Check at least 3 spelling variations
3. Search by partial name
4. If still not found, state: "Exhaustively searched, not found in index"

NEVER conclude "doesn't exist" from a single failed search.
```

#### Guardrail 6: Schema Awareness
**Rule:** Always verify column/table names against actual schema.

```markdown
## MANDATORY: Schema Verification

Before writing SQL or fixing query bugs:

1. Read src/ck3raven/db/schema.py for actual table/column names
2. Verify column names in file_contents: content_hash, content_blob, content_text, size
3. Verify table names: file_contents (not file_content)

Common mistakes:
- fc.content → should be COALESCE(fc.content_text, fc.content_blob)
- f.file_size → should be fc.size
- file_content → should be file_contents
```

---

## Part 4: Best Practices for AI-Assisted Development

### Structural Best Practices

| Practice | Implementation |
|----------|----------------|
| **Single Source of Truth** | Database schema in schema.py, merge rules in policies.py |
| **Layered Architecture** | Never skip layers (MCP → DB → Parser) |
| **Test Coverage** | Every fix needs a test in tests/ |
| **Documentation Co-location** | Module docs next to module code |

### Process Best Practices

| Practice | Implementation |
|----------|----------------|
| **Fix at Source** | When MCP tool fails, fix the tool, not the caller |
| **Incremental Changes** | One fix per commit, testable in isolation |
| **Schema First** | Read schema.py before any database work |
| **Existing Before New** | Search for existing code before creating new |

### AI Session Best Practices

| Practice | Implementation |
|----------|----------------|
| **Mode Declaration** | Start session with explicit mode (ck3raven-dev vs ck3lens) |
| **State Recap** | Every session starts with "Current status: X, Y, Z" |
| **Exit Summary** | Every session ends with documented status + next steps |
| **Tool Preference** | Prefer MCP tools over terminal commands for searches |

---

## Part 5: Strengthening ck3lens Guardrails

### Current Guardrails
- Live mod whitelist (only MSC, MSCRE, LRE, MRP, PVP2 writable)
- Syntax validation before writes
- Adjacency search prevents false "not found"

### Proposed Additional Guardrails

| Guardrail | Description | Implementation |
|-----------|-------------|----------------|
| **Conflict-Block Focus** | When compatching, agent can only edit blocks flagged as conflicts | Add `ck3_get_editable_blocks` tool |
| **User Affirmation for Scope Creep** | If touching non-conflict blocks, require explicit approval | Add `requires_approval` flag in write response |
| **File Naming Enforcement** | Reject writes that don't follow naming conventions (zzz_, 00_, etc.) | Add validation in `ck3_write_file` |
| **Commit Message Templates** | Enforce structured commit messages | Add format validation in `ck3_git_commit` |
| **Change Size Limits** | Warn/reject if single change is too large | Add line-count check |

---

## Part 6: Immediate Action Items

The following fixes will be applied:

1. **Fix version detection** in `scripts/build_database.py` line 43
   - Change: `VANILLA_PATH.parent / "launcher-settings.json"`
   - To: `VANILLA_PATH.parent / "launcher" / "launcher-settings.json"`

2. **Fix column names** in `tools/ck3lens_mcp/ck3lens/db_queries.py`
   - Change: `fc.content` → `COALESCE(fc.content_text, fc.content_blob)`
   - Change: `f.file_size` → `fc.size`

3. **Run `create_playset.py`** to populate playsets table

4. **Run `populate_symbols.py`** to extract symbols (if time permits)

---

## Summary

| Question | Answer |
|----------|--------|
| Are long instructions effective? | No - keep under 2000 words per mode |
| Can we prevent duplication? | Yes - anti-duplication guardrail + schema awareness |
| Can we prevent workarounds? | Yes - bug escalation protocol + layer enforcement |
| How to switch modes? | Explicit declaration: "Switch to ck3raven-dev mode" |

The key insight: **Guardrails work when they're actionable rules, not background knowledge.** The AI retains "NEVER use raw SQL" better than "the database layer provides abstracted access patterns."

---

*Proceeding with fixes 1-4...*
