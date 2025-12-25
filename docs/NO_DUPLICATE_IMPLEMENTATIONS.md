# CK3Raven Development Policy: No Duplicate Implementations

## Agent Instruction Block

Copy this block to agent instructions or system prompts for ck3raven-dev work:

---

### Instruction: No Duplicate Implementations. Prefer Libraries.

Before writing new code, you MUST search for existing implementations:

**EXISTS_CHECK**: Search keywords + symbol names across:
- `src/ck3raven/`
- `builder/`
- `tools/`

If similar logic exists:
- You MUST either reuse it or refactor it into a shared library (preferred).
- You MUST NOT re-implement the same algorithm/logic in a new file "because it's faster".

If no suitable code exists:
- You MUST create/extend a single canonical library in the correct layer:
  - **parsing/tokenizing**: `src/ck3raven/parser/...`
  - **database/schema**: `src/ck3raven/db/...`
  - **builder orchestration**: `builder/...`
  - **policy/guardrails**: `tools/ck3lens_mcp/ck3lens/policy/...`
  - **MCP tools**: `tools/ck3lens_mcp/...`

**"Quick scripts" are allowed only when:**
- Placed in `.artifacts/` or `temp/`
- Not imported by production modules
- Not committed to the repository

**Any change that adds a new "helper" function must pass this checklist:**

| Check | Evidence Required |
|-------|-------------------|
| Is there already a function that does this? | EXISTS_CHECK tool call showing search results |
| If not, should it be a library function? | ARCH_REVIEW citing ARCHITECTURE.md location |
| If it's script-only, why is it not core? | SCRIPT_JUSTIFICATION in trace notes |

---

## Canonical Module Locations

| Domain | Canonical Location | Purpose |
|--------|-------------------|---------|
| CK3 Script Parsing | `src/ck3raven/parser/` | Tokenizer, AST, grammar |
| File Routing | `src/ck3raven/db/file_routes.py` | Which files get AST vs LOOKUPS |
| Database Schema | `src/ck3raven/db/schema.py` | Tables, triggers, migrations |
| Database Queries | `src/ck3raven/db/queries.py` | Read operations |
| Symbol Extraction | `builder/extractors/` | Extract symbols from AST/content |
| Lookup Extraction | `builder/extractors/lookups/` | Lightweight extraction for LOOKUPS route |
| Builder Daemon | `builder/daemon.py` | Main builder entry point |
| Incremental Updates | `builder/incremental.py` | Single-file refresh |
| MCP Tools | `tools/ck3lens_mcp/server.py` | MCP tool definitions |
| Policy Engine | `tools/ck3lens_mcp/ck3lens/policy/` | Validation rules |
| CLI Wrappers | `tools/ck3lens_mcp/ck3lens/work_contracts.py` | Work contracts, tokens |

## Anti-Patterns to Avoid

### ❌ Bad: Scattered Helper Functions
```
scripts/extract_traits.py      # Duplicate of builder/extractors/trait_extractor.py
scripts/parse_events.py        # Duplicate of src/ck3raven/parser/
tools/quick_symbol_search.py   # Duplicate of src/ck3raven/db/queries.py
```

### ✅ Good: Single Canonical Location
```
# Need trait extraction? Use the builder:
from builder.extractors.trait_extractor import extract_traits

# Need parsing? Use the parser:
from ck3raven.parser import parse_source

# Need symbol search? Use the queries:
from ck3raven.db.queries import search_symbols
```

### ❌ Bad: "Quick Fix" Scripts
```python
# scripts/fix_broken_traits.py
# "Quick script to patch the database"
conn.execute("UPDATE symbols SET ...")  # FORBIDDEN
```

### ✅ Good: Fix Core Code
```python
# Fix the actual bug in src/ck3raven/db/queries.py
# Add regression test in tests/test_queries.py
```

## Enforcement

These rules are enforced by:

1. **Pre-commit hooks** - `code-diff-guard` blocks forbidden patterns
2. **CI gates** - GitHub Actions fail on violations
3. **Policy validator** - `ck3_validate_policy` blocks delivery
4. **Config rules** in `ck3lens_config.yaml`:
   - `allowed_python_paths`: ERROR
   - `scripts_must_be_documented`: ERROR
   - `ephemeral_scripts_location`: ERROR
   - `bugfix_requires_core_change`: ERROR
   - `bugfix_requires_test`: ERROR
   - `architecture_intent_required`: ERROR

## Clone Detection (Phase 2)

Future enhancement: Add lightweight clone detection to catch duplicated logic:

1. Token-hash changed blocks in each commit
2. Compare against existing codebase
3. Warn on >80% similarity to existing code
4. Gate only on NEW duplication (don't block on existing debt)

Tools to consider: `jscpd`, `simian`, or custom Python tokenizer comparison.
