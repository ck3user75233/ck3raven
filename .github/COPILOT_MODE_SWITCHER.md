# CK3 AI Agent Mode Switcher

> **Quick Reference:** How to switch between ck3raven development and ck3lens compatching modes.

---

## Two Modes, Two Mindsets

| Mode | File | Purpose | You're Working On |
|------|------|---------|-------------------|
| **ck3raven-dev** | `COPILOT_RAVEN_DEV.md` | Python infrastructure | Parser, DB, emulator, MCP server |
| **ck3lens** | `COPILOT_LENS_COMPATCH.md` | CK3 mod patching | .txt mod files, compatibility fixes |

---

## How to Switch Modes

### Option 1: Tell the Agent Directly

```
Switch to ck3raven-dev mode. I need to work on the database schema.
```

```
Switch to ck3lens mode. I need to fix a trait conflict in MSC.
```

### Option 2: Reference the Instruction File

```
@.github/COPILOT_RAVEN_DEV.md - Use this context for our session.
```

```
@.github/COPILOT_LENS_COMPATCH.md - Use this context for our session.
```

### Option 3: VS Code Copilot Chat Participants

Future enhancement: Create VS Code chat participants:
- `@raven` - Automatically uses ck3raven-dev instructions
- `@lens` - Automatically uses ck3lens instructions

---

## Mode Detection Heuristics

The agent should auto-detect mode based on:

| Indicator | Likely Mode |
|-----------|-------------|
| Editing `.py` files in `ck3raven/` | ck3raven-dev |
| Editing `.txt` files in `mod/` | ck3lens |
| Discussing database, schema, parser | ck3raven-dev |
| Discussing traits, events, conflicts | ck3lens |
| Running `pytest` or Python scripts | ck3raven-dev |
| Using `ck3_write_file`, `ck3_git_commit` | ck3lens |
| Asking about merge policies | Both (but ck3lens uses, raven-dev implements) |

---

## Quick Mode Summaries

### ck3raven-dev Mode
- **Language:** Python 3.10+
- **Database:** SQLite with content-addressed storage
- **Key Modules:** parser/, resolver/, db/, emulator/, tools/
- **Current Focus:** Fix version detection, populate playsets/symbols
- **Don't:** Edit CK3 mod files directly

### ck3lens Mode  
- **Language:** CK3/Paradox script (.txt, .yml)
- **Tools:** CK3 Lens MCP (20 tools for search, validate, write)
- **Key Mods:** MSC, MSCRE, LRE, MRP
- **Current Focus:** Compatibility patches, error fixes
- **Don't:** Write Python infrastructure code

---

## Files Structure

```
ck3raven/.github/
├── copilot-instructions.md     # Original combined instructions (legacy)
├── COPILOT_RAVEN_DEV.md        # ck3raven development mode
├── COPILOT_LENS_COMPATCH.md    # ck3lens compatching mode
└── COPILOT_MODE_SWITCHER.md    # This file
```

---

## Recommended Workflow

### Starting a New Session

1. **Identify the task type** (Python dev or mod patching)
2. **State your mode explicitly** to the agent
3. **Reference the instruction file** if needed

### Mid-Session Mode Switch

```
I need to switch to ck3raven-dev mode now.
We found a bug in the MCP server that needs fixing.
Please refer to COPILOT_RAVEN_DEV.md for context.
```

### Returning to Previous Mode

```
Back to ck3lens mode. Let's continue with the trait fix.
```

---

## Mode-Specific Prompts

### ck3raven-dev Prompts
- "Fix the version detection bug in build_database.py"
- "Add a new MCP tool for X"
- "Implement the emulator module"
- "Why is the symbols table empty?"

### ck3lens Prompts
- "Fix the conflict between ModA and ModB for trait_x"
- "Add localization for missing keys in MSCRE"
- "This on_action isn't firing, diagnose and fix"
- "Create a compatch for the new culture traditions"

---

## Future Enhancements

1. **VS Code Chat Participants** - `@raven` and `@lens` commands
2. **Auto-detection** - Agent infers mode from file context
3. **Mode-specific tool filtering** - Hide irrelevant MCP tools per mode
4. **Project status sync** - Both modes share awareness of current state
