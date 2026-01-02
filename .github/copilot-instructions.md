# CK3 Lens - Comprehensive Copilot Instructions

> **Last Updated:** January 2, 2026  
> **For use with:** ck3raven, CK3 Lens MCP, CK3 Lens Explorer

---

## REQUIRED READING FOR INFRASTRUCTURE WORK

If you are working on ck3raven source code (ck3raven-dev mode), read this first:

**[docs/CANONICAL_ARCHITECTURE.md](../docs/CANONICAL_ARCHITECTURE.md)** - The 5 rules every agent must follow

Key rules (violations will be rejected):
1. **ONE enforcement boundary** - only `enforcement.py` may deny operations
2. **NO permission oracles** - never ask "am I allowed?" outside enforcement
3. **mods[] is THE mod list** - no parallel lists like `local_mods[]`
4. **WorldAdapter = visibility** - describes what exists, NOT what's allowed
5. **Enforcement = decisions** - decides allow/deny at execution time only

**For MCP tool development:** See [Section 5: MCP Tool Architecture](../docs/CANONICAL_ARCHITECTURE.md#5-mcp-tool-architecture) for the canonical pattern all tools must follow.

---

## Project Architecture

This workspace contains the **CK3 Lens** ecosystem - a complete AI-powered toolkit for Crusader Kings III modding:

### Core Components

| Component | Path | Purpose |
|-----------|------|---------|
| **ck3raven** | `/` (workspace root) | Python parser, resolver, SQLite database |
| **CK3 Lens MCP** | `tools/ck3lens_mcp/` | MCP server exposing 28+ tools to Copilot |
| **CK3 Lens Explorer** | `ck3raven/tools/ck3lens-explorer/` | VS Code extension for human UI |
| **CK3 Parser** | `ck3raven/src/ck3raven/parser/` | Paradox script parser (integrated, 100% vanilla pass rate) |

### Database
- **Path:** `~/.ck3raven/ck3raven.db`
- **Content:** ~81,000 files, 110+ content versions, indexed
- **Includes:** Vanilla CK3, Steam Workshop mods, local mods
- **Symbols:** Run `python builder/daemon.py start --symbols-only` after setup

---

## MCP Tools Reference (28+ Tools)

### Initialization (CRITICAL - Call First!)

| Tool | Purpose | Usage |
|------|---------|-------|
| `ck3_get_mode_instructions` | **THE initialization function** | **Call first with mode="ck3lens" or "ck3raven-dev"** |

**Single Entry Point:**
`ck3_get_mode_instructions(mode="ck3lens")`

This single call handles:
1. Database connection initialization
2. Mode setting (persisted)
3. WIP workspace initialization
4. Playset detection
5. Returns mode instructions + policy boundaries + session info

### Searching Mods in the Database

| Tool | Purpose |
|------|---------|
| `ck3_search` | **PRIMARY SEARCH** - unified search across symbols, content, and files |
| `ck3_search_mods` | Fuzzy search for mods by name or workshop ID |
| `ck3_confirm_not_exists` | Verify symbol truly missing before claiming it doesn't exist |
| `ck3_get_file` | Read indexed file content from database |
| `ck3_parse_content` | Parse script and return AST/errors |

### Playset & Scope

| Tool | Purpose |
|------|---------|
| `ck3_playset` | Get/switch playsets, list mods in playset |
| `ck3_get_scope_info` | Get active playset scope info |
| `ck3_get_db_status` | Check database health and build status |

### Conflict Detection

| Tool | Purpose |
|------|---------|
| `ck3_get_symbol_conflicts` | Fast ID-level conflict detection |
| `ck3_qr_conflicts` | Quick-resolve conflicts using load order |

---

## Write Operations - When Approval is Needed

### Writing to Local Mods

The agent can write to mods located under `local_mods_folder`:
`C:\Users\nateb\Documents\Paradox Interactive\Crusader Kings III\mod\`

**Current local mods in the playset:**

| Mod Name (from descriptor) | Purpose |
|---------------------------|---------|
| Mini Super Compatch | Multi-mod compatibility patches |
| MSC Religion Expanded | Religion expansion compatch |
| Lowborn Rise Expanded | Lowborn character expansion |
| More Raiding and Prisoners (1.18+) | Enhanced raiding and prisoner mechanics |

**Tools for writing:**

| Tool | Purpose |
|------|---------|
| `ck3_file(command="write", mod_name="...", rel_path="...", content="...")` | Write file to mod |
| `ck3_file(command="edit", mod_name="...", rel_path="...", old_content="...", new_content="...")` | Search/replace edit |
| `ck3_file(command="delete", ...)` | Delete file (REQUIRES TOKEN) |

### WIP Workspace

For Python scripts and analysis, use the WIP workspace at `~/.ck3raven/wip/`

**Intent types for WIP:**
- `script_wip` - Draft/run Python scripts

### Operations Requiring Tokens

| Operation | Token Type | TTL |
|-----------|-----------|-----|
| Delete mod file | DELETE_MOD_FILE | 30 min |
| Access inactive mods | INACTIVE_MOD_ACCESS | 60 min |
| Execute scripts | SCRIPT_EXECUTE | 15 min |
| Git push | GIT_PUSH_MOD | 60 min |

### Git Operations

| Tool | Purpose |
|------|---------|
| `ck3_git(command="status", mod_name="...")` | Check modified/staged files |
| `ck3_git(command="diff", mod_name="...")` | View changes |
| `ck3_git(command="add", mod_name="...", all_files=true)` | Stage files |
| `ck3_git(command="commit", mod_name="...", message="...")` | Commit with message |
| `ck3_git(command="push", mod_name="...")` | Push to remote |

---

## CK3 Merge/Override Rules (CRITICAL KNOWLEDGE)

### The 4 Core Merge Policies

| Policy | Behavior | Used By |
|--------|----------|---------|
| **OVERRIDE** | Last definition wins completely | ~95% of content (traits, events, decisions, scripted_effects, etc.) |
| **CONTAINER_MERGE** | Container merges, sublists append | `on_action` ONLY |
| **PER_KEY_OVERRIDE** | Each key independent, last wins | localization, defines |
| **FIOS** | First loaded wins | GUI types/templates (use `00_` prefix to load first) |

### on_action Rules (CONTAINER_MERGE) - CRITICAL

**From Paradox's official `_on_actions.info`:**
> "You cannot have multiple triggers or effect blocks for a given named on-action."

#### Single-Slot Blocks (CONFLICT - only ONE allowed, last wins):
- `effect = { }` - ONE per on_action
- `trigger = { }` - ONE per on_action

#### List Blocks (APPEND - all entries merge from all files):
- `events = { }` - appends
- `on_actions = { }` - appends

#### CORRECT Pattern for Extending on_actions:
`pdx
# Append to the on_actions LIST - safe, no conflict
on_game_start = {
    on_actions = { my_mod_on_game_start }
}

# Your isolated on_action with its own effect block
my_mod_on_game_start = {
    effect = {
        # Your code here - completely isolated, no conflict!
        trigger_event = my_mod_setup.001
    }
}
`

---

## Best Practices for Mod Development

### 1. Always Search Before Creating
Use `ck3_search` to check if something exists before creating.

### 2. Never Claim "Not Found" Without Verification
Use `ck3_search` or `ck3_confirm_not_exists` to verify.

### 3. Validate Syntax Before Writing
Use `ck3_parse_content` to check syntax before `ck3_file(command="write", ...)`.

### 4. Use Proper File Naming
- `zzz_` prefix - loads LAST (wins conflicts for OVERRIDE types)
- `00_` prefix - loads FIRST (wins for FIOS types like GUI)

### 5. Commit Changes with Meaningful Messages
Use `ck3_git` to track modifications.

---

## Quick Reference: Key Files

| Purpose | Path |
|---------|------|
| Canonical Architecture | `docs/CANONICAL_ARCHITECTURE.md` |
| CK3Lens Policy | `docs/CK3LENS_POLICY_ARCHITECTURE.md` |
| Merge Rules | `docs/05_ACCURATE_MERGE_OVERRIDE_RULES.md` |
| MCP Server | `tools/ck3lens_mcp/server.py` |

