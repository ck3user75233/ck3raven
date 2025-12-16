# CK3 Game State Emulator - Project Overview

This folder contains design documents and notes from AI-assisted discussions about building a CK3 game state emulator tool.

## Document Index

| File | Description |
|------|-------------|
| [00_ORIGINAL_CONCEPT.md](00_ORIGINAL_CONCEPT.md) | The original idea: feed a playset, get a resolved game directory with source annotations |
| [01_PARSER_AND_MERGER_CONCEPTS.md](01_PARSER_AND_MERGER_CONCEPTS.md) | What is a parser? What is a merger? Why not regex? |
| [02_EXISTING_TOOLS_AND_FEASIBILITY.md](02_EXISTING_TOOLS_AND_FEASIBILITY.md) | What tools exist, how hard is this, can AI help build it? |
| [03_TRADITION_RESOLVER_V0_DESIGN.md](03_TRADITION_RESOLVER_V0_DESIGN.md) | Concrete v0 design for a tradition-only resolver with full architecture |
| [04_VIRTUAL_MERGE_EXPLAINED.md](04_VIRTUAL_MERGE_EXPLAINED.md) | What is a virtual merge and why it matters for compatch development |
| [05_ACCURATE_MERGE_OVERRIDE_RULES.md](05_ACCURATE_MERGE_OVERRIDE_RULES.md) | Corrected understanding of CK3's nuanced merge/override behavior |
| [06_CONTAINER_MERGE_OVERRIDE_TABLE.md](06_CONTAINER_MERGE_OVERRIDE_TABLE.md) | Complete reference table for all CK3 container types and their merge behavior |
| [07_TEST_MOD_AND_LOGGING_COMPATCH.md](07_TEST_MOD_AND_LOGGING_COMPATCH.md) | Bonus ideas for auto-generated test harnesses and logging instrumentation |

---

## Project Status

**Status:** ✅ **IMPLEMENTED** - Working prototype at `C:\Users\Nathan\Documents\AI Workspace\ck3_parser\`

**Implementation:** The v0 game state emulator is now functional with:
- Full parser/lexer for CK3 script files
- Playset loader with proper mod ordering
- Content registry supporting 13 content types
- Conflict detection and resolution
- Export with provenance annotations
- CLI interface for queries and reports

See the implementation at: [ck3_parser/README.md](../ck3_parser/README.md)

---

## Key Insights

### CK3's Actual Merge Rules (Not the Myth)

* **Containers** (traditions, events, decisions, etc.) → **Last definition wins**
* **on_actions** → **Container merges**, but sub-blocks with same key overwrite
* **Lists** (`events = {}`) → **Append/merge**
* **Blocks** (`effect = {}`, `trigger = {}`) → **Override**

### What This Tool Would Solve

1. "Which mod's definition actually wins?"
2. Silent overwrites where Mod B nukes Mod A's changes
3. Compatch development - see exactly what needs reconciling
4. Diff final playset state vs vanilla

### Technical Approach

1. Build a proper **lexer/parser** for Paradox script → AST
2. Apply **per-type merge policies** (whole-block-override vs container-merge)
3. Track **provenance** (which mod contributed each block)
4. Export **resolved files** + **conflict reports**

---

## When to Start This Project

This is a **serious engineering effort**, not a weekend script. Best approached when:

* You have several hours to dedicate to the initial parser/lexer
* You have real test cases (actual conflicting mods) to validate against
* You're ready to iterate with AI assistance on edge cases

The documents here provide the complete design blueprint. An agent AI can help bootstrap the code, but human review/testing is essential.

---

*These documents originated from AI-assisted discussions about CK3 modding tool development.*
