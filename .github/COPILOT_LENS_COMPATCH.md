# CK3 Lens Compatching Mode - AI Agent Instructions

> **Mode:** `ck3lens`  
> **Purpose:** CK3 mod compatibility patching and error fixing  
> **Last Updated:** December 18, 2025

---

## ⚠️ CRITICAL: Database-Only Mode

**ck3lens is a DATABASE-ONLY mode.** All information is accessed through MCP tools that query the ck3raven SQLite database.

### ✅ ALLOWED Tools
- `mcp_ck3lens_*` - All CK3 Lens MCP tools
- Live file editing via MCP (`ck3_write_file`, `ck3_edit_file`)

### ❌ FORBIDDEN Tools (Do NOT use these)
- `run_in_terminal` - No terminal commands
- `grep_search` - No filesystem grep
- `file_search` - No filesystem search  
- `read_file` - No direct file reads (use `ck3_get_file` or `ck3_read_live_file`)
- `semantic_search` - No semantic search (use `ck3_search_symbols`)
- `list_dir` - No directory listing (use `ck3_list_live_files`)

### Why Database-Only?
The ck3raven database contains:
- **Parsed AST** of all CK3 script files
- **Raw file content** (no need to read from disk)
- **Symbol index** with fuzzy search
- **Conflict detection** across load order
- **Playset management** for mods

Everything you need is in the database. If something is missing, use `ck3raven-dev` mode to add ingestion/extraction tools.

---

## VS Code Tool Set

Select the **"CK3 Lens"** tool set in VS Code to restrict available tools:
- Chat menu → Configure Tool Sets → Select "ck3lens"
- Or use `Chat: Configure Tool Sets` command

---

## Quick Identity Check

**Am I in the right mode?**
- ✅ You're fixing CK3 mod errors (syntax, conflicts, missing refs)
- ✅ You're creating/editing .txt files in mod folders
- ✅ You're writing compatibility patches for MSC/MSCRE/LRE
- ✅ You're analyzing load order conflicts
- ❌ If you're writing Python code for ck3raven → Switch to `ck3raven-dev` mode
- ❌ If you used `grep_search`, `read_file`, or `run_in_terminal` → You're doing it wrong!

---

## Your MCP Tools

You have access to **CK3 Lens MCP tools** that query a 26+ GB indexed database:

### Essential Workflow Tools

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `ck3_init_session` | Initialize database | **First** before any search |
| `ck3_search_symbols` | Find traits, decisions, events | Any time you need to look up a symbol |
| `ck3_confirm_not_exists` | Verify symbol truly missing | **ALWAYS** before claiming something doesn't exist |
| `ck3_get_file` | Read indexed file content | Check vanilla/mod file content |
| `ck3_get_conflicts` | Find load-order conflicts | Diagnosing override issues |
| `ck3_parse_content` | Validate CK3 syntax | Before writing any file |

### Playset Management Tools

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `ck3_get_active_playset` | Get current playset with mod list | Check what mods are loaded |
| `ck3_list_playsets` | List all available playsets | See all playset options |
| `ck3_search_mods` | Search mods by name/ID/abbreviation | Find a mod before adding |
| `ck3_add_mod_to_playset` | Add mod (ingests+extracts symbols) | Add new mod to playset |
| `ck3_remove_mod_from_playset` | Remove mod from playset | Remove mod from playset |

### Unit-Level Conflict Analysis Tools

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `ck3_scan_unit_conflicts` | Full conflict scan of playset | Start of compatch session |
| `ck3_get_conflict_summary` | Summary counts by risk/domain | Quick overview |
| `ck3_list_conflict_units` | List conflicts with filters | Find high-risk conflicts |
| `ck3_get_conflict_detail` | Full detail for one conflict | Analyze specific conflict |
| `ck3_resolve_conflict` | Record resolution decision | After deciding winner |
| `ck3_get_unit_content` | Compare all versions of a unit | See what each mod defines |

### Live Mod Operations

| Tool | Purpose |
|------|---------|
| `ck3_list_live_mods` | List mods you can edit |
| `ck3_read_live_file` | Read from editable mod |
| `ck3_write_file` | Write to mod (auto-validates syntax) |
| `ck3_edit_file` | Search/replace in mod file |
| `ck3_delete_file` | Remove file from mod |

### Git Operations

| Tool | Purpose |
|------|---------|
| `ck3_git_status` | Check modified files |
| `ck3_git_diff` | View changes |
| `ck3_git_add` | Stage files |
| `ck3_git_commit` | Commit with message |

---

## Live Mods (Your Workspace)

You can edit these mods:

| ID | Name | Purpose |
|----|------|---------|
| **MSC** | Mini Super Compatch | Multi-mod compatibility |
| **MSCRE** | MSCRE | Religion expansion compatch |
| **LRE** | Lowborn Rise Expanded | Lowborn character expansion |
| **MRP** | More Raid and Prisoners | Raiding mechanics |
| **PVP2** | PVP2 | (Placeholder - verify purpose) |

**Focus:** Searches are limited to your active playset (vanilla + enabled mods), not all 100+ workshop mods.

---

## CK3 Merge Rules (MEMORIZE THESE)

### The 4 Merge Policies

| Policy | Behavior | Used By |
|--------|----------|---------|
| **OVERRIDE** | Last definition wins | ~95% of content (traits, events, decisions, etc.) |
| **CONTAINER_MERGE** | Container merges, sublists append | `on_action` ONLY |
| **PER_KEY_OVERRIDE** | Each key independent | localization, defines |
| **FIOS** | First wins | GUI types (use `00_` prefix) |

### File Naming for Load Order

| Prefix | Effect | Use For |
|--------|--------|---------|
| `zzz_` | Loads LAST | Winning OVERRIDE conflicts |
| `00_` | Loads FIRST | Winning FIOS (GUI) |
| `_patch` suffix | Convention | Compatibility patches |

---

## on_action Rules (CRITICAL)

**on_action uses CONTAINER_MERGE** - but with traps!

### Single-Slot Blocks (CONFLICT - only ONE allowed)
- `effect = { }` - ONE per on_action, last wins
- `trigger = { }` - ONE per on_action
- `weight_multiplier = { }` - ONE per on_action

### List Blocks (SAFE - all entries merge)
- `events = { }` ✅ appends
- `on_actions = { }` ✅ appends
- `random_events = { }` ✅ appends

### ✅ CORRECT Pattern
```pdx
# Hook into vanilla via list - SAFE
on_game_start = {
    on_actions = { my_mod_on_game_start }
}

# Your isolated on_action
my_mod_on_game_start = {
    effect = {
        # Your code here - no conflict!
    }
}
```

### ❌ WRONG Pattern
```pdx
# This DESTROYS vanilla's effect block!
on_game_start = {
    effect = {
        # Vanilla's code is GONE
    }
}
```

---

## Common Fix Patterns

### Missing Localization
```yaml
# localization/english/replace/my_mod_l_english.yml
l_english:
 missing_key:0 "The text that was missing"
```

### Trait Override (Last Wins)
```pdx
# common/traits/zzz_my_fix.txt
brave = {
    # Your corrected definition
    # This replaces vanilla because of zzz_ prefix
}
```

### Extending on_action Safely
```pdx
# common/on_action/zzz_my_on_actions.txt
on_birth_child = {
    on_actions = { my_mod_birth_handler }
}

my_mod_birth_handler = {
    trigger = { exists = scope:child }
    effect = {
        # Your logic here
    }
}
```

### Scripted Effect/Trigger
```pdx
# common/scripted_effects/zzz_my_effects.txt
my_effect = {
    add_prestige = 100
}

# common/scripted_triggers/zzz_my_triggers.txt
my_trigger = {
    is_adult = yes
    is_landed = yes
}
```

---

## Workflow for Fixing Errors

### Step 1: Understand the Error
What type of error?
- Syntax error → Parse and validate
- Missing reference → Search for the symbol
- Conflict/override → Check conflicts

### Step 2: Search for Context
```
ck3_search_symbols(query="the_symbol", symbol_type="trait")
```

### Step 3: Check for Conflicts
```
ck3_get_conflicts(symbol_name="the_symbol")
```

### Step 4: Read Related Files
```
ck3_get_file(file_path="common/traits/00_traits.txt")
```

### Step 5: Validate Your Fix
```
ck3_parse_content(content="my_fix = { ... }")
```

### Step 6: Write the Fix
```
ck3_write_file(mod_name="MSC", rel_path="common/traits/zzz_fix.txt", content="...")
```

### Step 7: Commit
```
ck3_git_add(mod_name="MSC")
ck3_git_commit(mod_name="MSC", message="Fix: brief description")
```

---

## CK3 File Structure

```
mod/
├── common/
│   ├── traits/              # OVERRIDE
│   ├── cultures/            # OVERRIDE  
│   ├── religions/           # OVERRIDE
│   ├── decisions/           # OVERRIDE
│   ├── on_action/           # CONTAINER_MERGE ⚠️
│   ├── scripted_effects/    # OVERRIDE
│   ├── scripted_triggers/   # OVERRIDE
│   ├── character_interactions/  # OVERRIDE
│   └── defines/             # PER_KEY_OVERRIDE
├── events/                  # OVERRIDE by namespace.id
├── localization/
│   └── english/
│       └── replace/         # Override folder
└── gui/                     # FIOS (first wins)
```

---

## Scope Reference

| Scope | Description |
|-------|-------------|
| `root` | Original scope |
| `this` | Current (implicit) |
| `prev` | Previous in chain |
| `scope:name` | Saved scope |
| `event_target:name` | Event target |

### Character Scopes
`primary_title`, `capital_province`, `liege`, `top_liege`, `dynasty`, `house`, `father`, `mother`, `spouse`, `culture`, `faith`

---

## Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| "Custom deity names undefined" | Missing localization | Add custom_faith_X_god_names blocks |
| "Scope not found" | `scope.name` syntax | Use `scope:name` (colon, not dot) |
| "Invalid trigger" | Trigger in effect block | Check correct context |
| "Effect not running" | on_action effect overridden | Use `on_actions` list pattern |
| "Duplicate key" | Same key in merged files | One file needs zzz_ to win |

---

## MSCRE Religion Prefixes

| Prefix | Origin |
|--------|--------|
| `mscre_` | General MSCRE |
| `pr_` | Pagan Religions |
| `zpp_` | Zoroastrian Pagan Patch |
| `cdr_` | Celtic Druidic Religion |

---

## Key Files in AI Workspace

| File | Purpose |
|------|---------|
| `BUG_REPORTS_FOR_AUTHORS.md` | Tracked mod bugs |
| `active_mod_paths.json` | Active playset config |
| `ck3_error_parser.py` | Parse error.log |
| `ck3_syntax_validator.py` | Validate triggers/effects |

---

## Golden Rules

1. **Always search before creating** - The symbol might exist
2. **Always use `ck3_confirm_not_exists`** before claiming "not found"
3. **Always validate syntax** before writing files
4. **Never add `effect = { }` to vanilla on_actions** - Use `on_actions` list
5. **Use `zzz_` prefix** to win OVERRIDE conflicts
6. **Commit changes** with meaningful messages
7. **Check error.log** after testing in-game
