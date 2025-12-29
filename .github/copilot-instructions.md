# CK3 Lens - Comprehensive Copilot Instructions

> **Last Updated:** December 30, 2025  
> **For use with:** ck3raven, CK3 Lens MCP, CK3 Lens Explorer

---

## ⚠️ REQUIRED READING FOR INFRASTRUCTURE WORK

If you are working on ck3raven source code (ck3raven-dev mode), read this first:

**[docs/CANONICAL_ARCHITECTURE.md](../docs/CANONICAL_ARCHITECTURE.md)** — The 5 rules every agent must follow

Key rules (violations will be rejected):
1. **ONE enforcement boundary** — only `enforcement.py` may deny operations
2. **NO permission oracles** — never ask "am I allowed?" outside enforcement
3. **mods[] is THE mod list** — no parallel lists like `local_mods[]`
4. **WorldAdapter = visibility** — describes what exists, NOT what's allowed
5. **Enforcement = decisions** — decides allow/deny at execution time only

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
```
ck3_get_mode_instructions(mode="ck3lens")
```

This single call handles:
1. Database connection initialization
2. Mode setting (persisted)
3. WIP workspace initialization
4. Playset detection
5. Returns mode instructions + policy boundaries + session info

> ⚠️ `ck3_init_session` is **DEPRECATED**. Use `ck3_get_mode_instructions` instead.

### Session & Status
| Tool | Purpose |
|------|---------|
| `ck3_get_db_status` | Check database health and build status |
| `ck3_get_scope_info` | Get active playset/lens info |
| `ck3_list_local_mods` | List editable mods (MSC, MSCRE, LRE, MRP) |
| `ck3_get_detected_mode` | Check current mode from trace |

### Symbol Search & Validation
| Tool | Purpose | Critical Notes |
|------|---------|----------------|
| `ck3_search` | **PRIMARY SEARCH** - unified search across symbols, content, and files | Searches EVERYTHING at once - no need to decide if something is a symbol |
| `ck3_search_symbols` | Find traits, decisions, events by name (legacy) | Use `ck3_search` instead |
| `ck3_search_files` | Find files by path pattern | Use SQL LIKE patterns: "%on_action%", "common/traits/%" |
| `ck3_search_content` | Grep-style content search | Find text inside files, returns snippets |
| `ck3_confirm_not_exists` | Verify symbol truly missing | **ALWAYS call before claiming something doesn't exist** |
| `ck3_get_file` | Read indexed file content | Returns raw content + optional AST |
| `ck3_parse_content` | Parse script, return AST/errors | Use for syntax validation before writing |
| `ck3_validate_patchdraft` | Validate patches before applying | Checks path policy + references |

### Playset Management
| Tool | Purpose |
|------|---------|
| `ck3_get_active_playset` | Get current playset with mod list |
| `ck3_list_playsets` | List all available playsets |
| `ck3_search_mods` | Fuzzy search mods by name/ID/abbreviation |
| `ck3_add_mod_to_playset` | Full workflow: find → ingest → extract → add |
| `ck3_remove_mod_from_playset` | Remove with load order adjustment |

### Conflict Detection (File-Level)
| Tool | Purpose |
|------|---------|
| `ck3_get_conflicts` | Find load-order conflicts by path |

### Unit-Level Conflict Analysis (ID-Level)
| Tool | Purpose |
|------|---------|
| `ck3_scan_unit_conflicts` | Scan playset for all unit-level conflicts |
| `ck3_get_conflict_summary` | Summary counts by risk/domain |
| `ck3_list_conflict_units` | List conflicts with filters |
| `ck3_get_conflict_detail` | Full detail for one conflict |
| `ck3_resolve_conflict` | Record resolution decision |
| `ck3_get_unit_content` | Compare all versions of a unit |

### Conflicts Report
| Tool | Purpose |
|------|---------|
| `ck3_generate_conflicts_report` | Full file + ID conflict report (JSON or CLI) |
| `ck3_get_high_risk_conflicts` | Get highest-risk conflicts for priority review |

### Live Mod Operations
| Tool | Purpose |
|------|---------|
| `ck3_list_live_files` | List files in editable mod |
| `ck3_read_live_file` | Read file from live mod |
| `ck3_write_file` | Write file to live mod (validates syntax automatically) |
| `ck3_edit_file` | Search/replace edit in mod file |
| `ck3_delete_file` | Delete file from mod |

### Git Operations
| Tool | Purpose |
|------|---------|
| `ck3_git_status` | Check modified/staged files |
| `ck3_git_diff` | View changes |
| `ck3_git_add` | Stage files |
| `ck3_git_commit` | Commit with message |
| `ck3_git_push` / `ck3_git_pull` | Sync with remote |
| `ck3_git_log` | View commit history |

---

## Live Mods (Whitelisted for Writes)

| Mod ID | Full Name | Purpose |
|--------|-----------|---------|
| **MSC** | Mini Super Compatch | Multi-mod compatibility patches |
| **MSCRE** | MSCRE (Religion Expansion) | Religion expansion compatch |
| **LRE** | Lowborn Rise Expanded | Lowborn character expansion |
| **MRP** | More Raid and Prisoners | Raiding and prisoner mechanics |

**Paths:**
- MSC: `C:\Users\nateb\Documents\Paradox Interactive\Crusader Kings III\mod\Mini Super Compatch`
- MSCRE: `C:\Users\nateb\Documents\Paradox Interactive\Crusader Kings III\mod\MSCRE`
- LRE: `C:\Users\nateb\Documents\Paradox Interactive\Crusader Kings III\mod\Lowborn Rise Expanded`
- MRP: `C:\Users\nateb\Documents\Paradox Interactive\Crusader Kings III\mod\More Raid and Prisoners`

**Focus:** CK3 Lens is configured to search ONLY the active playset (vanilla + active mods) via the ck3raven database. This keeps the AI focused on MSC/MSCRE development without distractions from inactive mods.

---

## CK3 Merge/Override Rules (CRITICAL KNOWLEDGE)

### The 4 Core Merge Policies

| Policy | Behavior | Used By |
|--------|----------|---------|
| **OVERRIDE** | Last definition wins completely | ~95% of content (traits, events, decisions, scripted_effects, etc.) |
| **CONTAINER_MERGE** | Container merges, sublists append | `on_action` ONLY |
| **PER_KEY_OVERRIDE** | Each key independent, last wins | localization, defines |
| **FIOS** | First loaded wins | GUI types/templates (use `00_` prefix to load first) |

### File-Level Resolution (Happens BEFORE merge policies)

| Scenario | Behavior |
|----------|----------|
| Same path + same filename | **Complete file replacement** - earlier file's content GONE |
| Same path + different filename | All files loaded, then key-level merge applies |
| `replace_path=` in .mod file | Entire vanilla folder ignored |
| Localization `replace/` folder | Keys override without duplicate errors |

### on_action Rules (CONTAINER_MERGE) ⚠️ CRITICAL

**From Paradox's official `_on_actions.info`:**
> "You cannot have multiple triggers or effect blocks for a given named on-action. You cannot append an effect block directly to an on_action which already has an effect block."

#### Single-Slot Blocks (CONFLICT - only ONE allowed, last wins):
- `effect = { }` - ONE per on_action
- `trigger = { }` - ONE per on_action
- `weight_multiplier = { }` - ONE per on_action
- `fallback = name` - ONE per on_action

#### List Blocks (APPEND - all entries merge from all files):
- `events = { }` ✅ appends
- `on_actions = { }` ✅ appends
- `random_events = { }` ✅ appends
- `random_on_actions = { }` ✅ appends
- `first_valid = { }` ✅ appends
- `first_valid_on_action = { }` ✅ appends

#### ✅ CORRECT Pattern for Extending on_actions:
```pdx
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
```

#### ❌ WRONG Pattern (Destroys Vanilla):
```pdx
# This REPLACES vanilla's entire effect block!
on_game_start = {
    effect = {
        # Vanilla's setup code is COMPLETELY GONE
        # Other mods' effects are GONE
        my_effect = yes
    }
}
```

---

## CK3 File Structure

```
mod/
├── common/                    # Game definitions
│   ├── traits/                # Character traits (OVERRIDE)
│   ├── cultures/              # Culture definitions (OVERRIDE)
│   ├── religions/             # Religion/faith definitions (OVERRIDE)
│   ├── decisions/             # Player decisions (OVERRIDE)
│   ├── on_action/             # Event triggers (CONTAINER_MERGE!)
│   ├── scripted_effects/      # Reusable effects (OVERRIDE)
│   ├── scripted_triggers/     # Reusable triggers (OVERRIDE)
│   ├── character_interactions/ # Interactions (OVERRIDE)
│   ├── defines/               # Game defines (PER_KEY_OVERRIDE)
│   └── ...
├── events/                    # Event files (OVERRIDE by namespace.id)
├── localization/              # Text strings (PER_KEY_OVERRIDE)
│   ├── english/
│   │   └── replace/           # Intentional override folder
│   └── ...
├── gfx/                       # Graphics
└── gui/                       # Interface files (FIOS - first wins!)
```

---

## Common CK3 Syntax Patterns

### Trait Definition
```pdx
brave = {
    index = 1
    opposites = { craven }
    type = personality
    
    # Modifiers
    martial = 2
    prowess = 3
    monthly_prestige = 0.1
    
    # AI behavior
    ai_boldness = 30
    ai_honor = 10
    
    icon = trait_brave
}
```

### Event
```pdx
namespace = my_events

my_events.001 = {
    type = character_event
    title = my_events.001.t
    desc = my_events.001.desc
    
    trigger = { is_alive = yes }
    
    immediate = {
        save_scope_as = event_target
    }
    
    option = {
        name = my_events.001.a
        add_prestige = 100
    }
}
```

### Decision
```pdx
my_decision = {
    picture = "gfx/interface/illustrations/decisions/decision_misc.dds"
    major = yes
    
    is_shown = {
        is_ruler = yes
        NOT = { has_character_flag = did_my_decision }
    }
    
    is_valid = {
        gold >= 100
        prestige >= 500
    }
    
    effect = {
        add_gold = -100
        add_prestige = -500
        add_character_flag = did_my_decision
        trigger_event = my_events.001
    }
    
    ai_check_interval = 60
    ai_will_do = {
        base = 0
        modifier = {
            add = 100
            gold >= 500
        }
    }
}
```

### On Action (Proper Mod Pattern)
```pdx
# File: common/on_action/zzz_my_mod_on_actions.txt

# Hook into vanilla on_action via list append
on_birth_child = {
    on_actions = { my_mod_on_birth }
}

# Your isolated on_action
my_mod_on_birth = {
    trigger = {
        exists = scope:child
    }
    effect = {
        scope:child = {
            # Your birth logic here
            if = {
                limit = { has_trait = genius }
                add_character_flag = special_birth
            }
        }
    }
}
```

### Scripted Effect
```pdx
# File: common/scripted_effects/my_mod_effects.txt

my_custom_effect = {
    add_prestige = 100
    if = {
        limit = { has_trait = ambitious }
        add_prestige = 50
    }
}
```

### Scripted Trigger
```pdx
# File: common/scripted_triggers/my_mod_triggers.txt

my_custom_trigger = {
    is_adult = yes
    is_landed = yes
    NOT = { has_trait = incapable }
}
```

---

## Scopes Reference

| Scope | Description |
|-------|-------------|
| `root` | Original scope that started the chain |
| `this` | Current scope (implicit, usually omitted) |
| `prev` | Previous scope in chain |
| `from` | Scope passed from calling context |
| `scope:name` | Saved scope reference (via `save_scope_as`) |
| `event_target:name` | Event target reference |

### Common Character Scopes
- `primary_title`, `capital_province`, `capital_county`
- `liege`, `top_liege`, `dynasty`, `house`
- `father`, `mother`, `spouse`, `primary_spouse`
- `culture`, `faith`, `religion`

---

## Best Practices for Mod Development

### 1. Always Search Before Creating
```
Use ck3_search to check if something exists before creating.
This searches symbols, content, AND files in one call.
```

### 2. Never Claim "Not Found" Without Verification
```
CRITICAL RULE: A null/empty answer is ONLY valid if BOTH:
  - Symbol search returns empty AND
  - Content search returns empty

Filename-only searches are NOT sufficient to claim something doesn't exist.
Content must be checked. Use ck3_search (unified) or ck3_confirm_not_exists.
```

### 3. Validate Syntax Before Writing
```
Use ck3_parse_content to check syntax before ck3_write_file
```

### 4. Use Proper File Naming
- `zzz_` prefix → loads LAST (wins conflicts for OVERRIDE types)
- `00_` prefix → loads FIRST (wins for FIOS types like GUI)
- `_patch` suffix → indicates compatibility patch
- `_fix` suffix → indicates bugfix

### 5. Remember on_action is CONTAINER_MERGE
- Your `on_actions = { }` list APPENDS - safe!
- Your `effect = { }` block REPLACES - dangerous!
- Always chain via `on_actions` list, never add direct `effect` blocks

### 6. Add Localization
Every user-visible string needs an `l_english` entry:
```yaml
l_english:
 my_decision:0 "My Decision Title"
 my_decision_desc:0 "Description of what this does."
 my_decision_tooltip:0 "Click to do the thing."
```

### 7. Commit Changes with Meaningful Messages
```
Use ck3_git_add and ck3_git_commit to track modifications
Include what was changed and why
```

### 8. Test In-Game
The `error.log` reveals runtime issues that static analysis can't catch.

---

## Workflow for Mod Fixes

### Step 1: Understand the Context
- What mods are active?
- What's the load order?
- Which mod owns the file?

### Step 2: Search for Existing Symbols
```
ck3_search_symbols(query="symbol_name", symbol_type="trait|decision|event")
```

### Step 3: Check for Conflicts
```
ck3_get_conflicts(symbol_name="the_symbol")
```

### Step 4: Read Current Content
```
ck3_get_file(file_path="common/traits/00_traits.txt")
ck3_read_live_file(mod_name="MSC", rel_path="common/traits/zzz_fix.txt")
```

### Step 5: Validate New Content
```
ck3_parse_content(content="my_trait = { ... }")
```

### Step 6: Write the Fix
```
ck3_write_file(mod_name="MSC", rel_path="common/traits/zzz_fix.txt", content="...")
```

### Step 7: Commit and Document
```
ck3_git_add(mod_name="MSC")
ck3_git_commit(mod_name="MSC", message="Fix: corrected trait definition")
```

---

## MSCRE Religion Prefixes

When working with MSCRE religion content:

| Prefix | Origin Mod |
|--------|------------|
| `mscre_` | General MSCRE content |
| `pr_` | Pagan Religions mod |
| `zpp_` | Zoroastrian Pagan Patch |
| `cdr_` | Celtic Druidic Religion |

---

## Common Issues and Solutions

### "Custom deity names undefined" Errors
**Cause:** Religion files missing vanilla paganism localization blocks
**Fix:** Add custom_faith_X_god_names blocks referencing valid localization keys

### "Scope not found" Errors
**Cause:** Using `scope.name` instead of `scope:name`
**Fix:** Replace `.` with `:` for saved scope references

### "Invalid trigger/effect" Errors
**Cause:** Using trigger in effect block or vice versa
**Fix:** Check CK3 syntax database for correct context

### on_action Effects Not Running
**Cause:** Effect block being overridden by another mod
**Fix:** Use `on_actions = { }` list to chain, not direct `effect = { }`

---

## Project-Specific Reminders

1. **Database may have schema issues** - Some MCP tools return SQL errors (under investigation)
2. **Live mods are Git repos** - Always commit changes with meaningful messages
3. **CK3 1.15+ renamed modifiers** - `monthly_character_paycheck` → `monthly_character_income_mult`
4. **Workshop mod IDs are numeric** - Map to names via `active_mod_paths.json`

---

## Quick Reference: Key Files

| Purpose | Path |
|---------|------|
| Project Status | `PROJECT_STATUS.md` |
| Bug Reports | `BUG_REPORTS_FOR_AUTHORS.md` |
| Mod Paths | `active_mod_paths.json` |
| Error Parser | `scripts/ck3_error_parser.py` |
| MCP Server | `tools/ck3lens_mcp/server.py` |
| Merge Rules | `docs/05_ACCURATE_MERGE_OVERRIDE_RULES.md` |
| Content Types | `docs/06_CONTAINER_MERGE_OVERRIDE_TABLE.md` |
| CK3Lens Policy | `docs/CK3LENS_POLICY_ARCHITECTURE.md` |
| CK3Raven-Dev Policy | `docs/CK3RAVEN_DEV_POLICY_ARCHITECTURE.md` |

---

## Policy Architecture (ck3lens Mode)

### Access Control Domains

| Domain | Visibility | Access |
|--------|-----------|--------|
| Active Playset (DB) | Always visible | Read only (DB view) |
| Active Local Mods | Always visible | Read + Write (contract) + Delete (token) |
| Active Workshop Mods | Always visible | Read only |
| Vanilla Game | Always visible | Read only |
| Inactive Mods | Hidden | User prompt + token required |
| WIP Workspace | Session-local | Full access (Python scripts) |
| Launcher Registry | Special | Via ck3_repair only |

### Intent Types

| Intent | Purpose | Access Level |
|--------|---------|--------------|
| `compatch` | Multi-mod compatibility patches | Full write to live mods |
| `bugpatch` | Bug patches via local override | Write to live mods |
| `research_mod_issues` | Research conflicts/errors | Read-only |
| `research_bugreport` | Research for bug reports | Read-only |
| `script_wip` | Draft/run Python in WIP | WIP workspace only |

### Hard Gates (AUTO_DENY)

These rules are architectural - they cannot be bypassed:

1. **Intent Type Required** - Every operation must have declared intent
2. **Write Only Active Local Mods** - Cannot write to workshop/vanilla
3. **Python Only in WIP** - .py files restricted to ~/.ck3raven/wip/
4. **Delete Requires Token** - File deletion needs explicit approval
5. **Inactive Mod Access Requires User Prompt** - Must quote user's request

### Token Types

| Token | Purpose | TTL | Requires |
|-------|---------|-----|----------|
| DELETE_MOD_FILE | Delete files from live mods | 30 min | User prompt evidence |
| INACTIVE_MOD_ACCESS | Read inactive mods | 60 min | User prompt evidence |
| SCRIPT_EXECUTE | Run scripts in WIP | 15 min | Script hash binding |
| GIT_PUSH_MOD | Push to mod git remote | 60 min | User prompt evidence |

### Repair Tool

For launcher/cache issues:

```python
ck3_repair(command="query")              # Get system status
ck3_repair(command="diagnose_launcher")  # Analyze launcher DB
ck3_repair(command="backup_launcher")    # Backup before changes
ck3_repair(command="delete_cache", dry_run=False)  # Clear cache
```

---

## Policy Architecture (ck3raven-dev Mode)

See full specification: `docs/CK3RAVEN_DEV_POLICY_ARCHITECTURE.md`

### Key Differences from ck3lens

| Aspect | ck3lens | ck3raven-dev |
|--------|---------|--------------|
| **Mod writes** | Allowed to active local mods | **ABSOLUTE PROHIBITION** |
| **ck3raven source** | Read-only | Full write access |
| **WIP location** | `~/.ck3raven/wip/` | `<repo>/.wip/` |
| **run_in_terminal** | Not available | **PROHIBITED** (use ck3_exec) |
| **ck3_repair** | Available | **Not available** |

### Hard Gates (ck3raven-dev)

1. **Mod Write Prohibition** - Cannot write to ANY mod files (absolute)
2. **run_in_terminal Prohibition** - Must use ck3_exec
3. **Git History Protection** - rebase/amend requires token
4. **DB Destructive Protection** - DROP/DELETE require migration context + token
5. **WIP Workaround Detection** - Repeated script execution without core changes = AUTO_DENY

### Intent Types (ck3raven-dev)

| Intent | Purpose |
|--------|---------|
| `BUGFIX` | Fix infrastructure bug |
| `REFACTOR` | Code reorganization |
| `FEATURE` | New feature implementation |
| `MIGRATION` | Database/config migration |
| `TEST_ONLY` | Tests only |
| `DOCS_ONLY` | Documentation only |

### WIP Intents (ck3raven-dev)

| Intent | Constraints |
|--------|-------------|
| `ANALYSIS_ONLY` | Read-only analysis, no writes |
| `REFACTOR_ASSIST` | Generate patches, requires `core_change_plan` |
| `MIGRATION_HELPER` | Generate migrations, requires `core_change_plan` |

---

## Auxiliary Tools (Python Scripts)

### CK3 Syntax Validator
- **Path:** `scripts/ck3_syntax_validator.py`
- **Database:** `data/ck3_syntax_db.json` (2541 triggers, 1127 effects)
- **Purpose:** Validate triggers, effects, scopes against actual vanilla files

### CK3 Modding Mechanics Analyzer
- **Path:** `scripts/ck3_modding_mechanics_analyzer.py`
- **Database:** `data/ck3_modding_mechanics.json`
- **Purpose:** Learn modding patterns from workshop mods (merge vs override, naming conventions)

### CK3 Drafting Assistant
- **Path:** `scripts/ck3_drafting_assistant.py`
- **Purpose:** Template generation, batch fixes, real-time validation, smart search/replace

### Error Log Parser
- **Path:** `scripts/ck3_error_parser.py`
- **Purpose:** Parse CK3's error.log into structured reports
