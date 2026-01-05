# Banned Term Cleanup Required - January 3, 2026

## Summary

Agent found extensive use of BANNED architectural terms throughout the codebase. These terms imply parallel authority structures which violate CANONICAL_ARCHITECTURE.md.

## Banned Terms Found

| Banned Term | Why Banned | Correct Term |
|-------------|------------|--------------|
| "active local mods" | Implies filtered/derived list | "mods[] under local_mods_folder" |
| "live mods" | Implies separate list | "mods[] under local_mods_folder" |
| "local mods" (as list) | Parallel structure | "mods[] under local_mods_folder" |
| "playset mods" | Architecture drift | "mods[]" |
| "MSC, MSCRE, LRE, MRP" | Hardcoded mod names | Dynamic from mods[] |

## Files Requiring Fixes

### Source Code (PRIORITY)

| File | Hits | Issue |
|------|------|-------|
| 	ools/ck3lens_mcp/ck3lens/policy/ck3lens_rules.py | 1 | "active local mods" |
| 	ools/ck3lens_mcp/ck3lens/policy/contract_schema.py | 1 | "active local mods" |
| 	ools/ck3lens_mcp/ck3lens/policy/types.py | 2 | "active local mods", DELETE_LOCALMOD |
| 	ools/ck3lens_mcp/ck3lens/policy/wip_workspace.py | 1 | "active local mods" |
| .github/agents/lens.chat-agent.md | 1 | "Live Mods You Can Edit" |

### Documentation

| File | Hits | Issue |
|------|------|-------|
| docs/CK3LENS_POLICY_ARCHITECTURE.md | 10 | "active local mods" throughout |
| docs/CANONICAL_ARCHITECTURE.md | 1 | "live mods" |
| docs/drafts/NEXT_SESSION_TODO.md | 1 | "active local mods" |
| docs/drafts/WIP_SCRIPTING_PROPOSAL.md | 2 | "active local mods" |
| docs/Concepts lens - EARLY DRAFT SCRATCHBOOK.md | 7 | "live mods" |
| docs/HARD CODING TO FIX.md | 1 | "live mods" |
| README.md | 1 | "live mods" |
| 	ools/ck3lens-explorer/DESIGN.md | 1 | "liveModsView.ts" |

### Cached/Generated (delete and regenerate)

- 	ools/ck3lens_mcp/ck3lens/policy/__pycache__/*.pyc - multiple hits
- lint_results.json - stale lint output
- .venv/Lib/site-packages/ck3raven-0.1.0.dist-info/METADATA - reinstall package
- src/ck3raven.egg-info/PKG-INFO - regenerate

## Why Agent Didn't Find These Earlier

### Root Cause Analysis

1. **Searched wrong file**: Agent searched COPILOT_LENS_COMPATCH.md for "MSC, MSCRE, LRE, MRP" but the actual source was elsewhere (possibly generated dynamically or in a different policy doc)

2. **Search scope too narrow**: Agent only searched .github/ folder, not the full codebase

3. **Trusted previous grep results**: When earlier grep showed 0 matches, agent declared "already fixed" without verifying the original bug report source

4. **Mode confusion**: Agent was in wrong mode (ck3lens vs ck3raven-dev) limiting visibility

5. **Didn't search source code**: Focused on markdown docs, not Python source files where terms are actually used

### Linter Analysis Needed

Need to check scripts/arch_lint/config.py for:
- Allowlisted paths that exclude policy files
- Missing patterns for "active local mods", "live mods"
- Whitelisted files that should be scanned

## Action Items

1. [ ] Fix all source code files (ck3lens_rules.py, types.py, etc.)
2. [ ] Fix all documentation files
3. [ ] Delete __pycache__ folders
4. [ ] Regenerate egg-info
5. [ ] Reinstall ck3raven in venv
6. [ ] Update arch_lint to catch these patterns
7. [ ] Add regression test for banned terms

## Correct Architecture

Per CANONICAL_ARCHITECTURE.md:

- mods[] is THE mod list (no parallel lists)
- local_mods_folder is a Path for containment checks
- Enforcement checks if mod path is under local_mods_folder at execution time
- No pre-filtering, no derived lists, no "active" or "live" qualifiers
