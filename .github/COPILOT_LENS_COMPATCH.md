# CK3 Lens Mode - AI Agent Instructions

> **Mode:** `ck3lens`  
> **Purpose:** CK3 mod compatibility patching and error fixing  
> **Last Updated:** January 2026

---

## Initialization

**Call first:** `ck3_get_mode_instructions(mode="ck3lens")`

This initializes the database connection, sets the mode, and returns the active playset.

---

## MCP Tools

### Search & Query

| Tool | Purpose |
|------|---------|
| `ck3_search(query)` | Unified search - symbols, content, files |
| `ck3_file(command="get", path)` | Get indexed file content |
| `ck3_parse_content(content)` | Parse and validate CK3 syntax |
| `ck3_validate(target="references", symbol_name)` | Check if symbol exists |

### Playset

| Tool | Purpose |
|------|---------|
| `ck3_playset(command="get")` | Get active playset info |
| `ck3_playset(command="mods")` | List mods in playset with load order |

### Conflicts

| Tool | Purpose |
|------|---------|
| `ck3_conflicts(command="summary")` | Conflict statistics |
| `ck3_conflicts(command="symbols")` | Symbol conflicts across mods |
| `ck3_conflicts(command="files")` | File override conflicts |

### File Operations

| Tool | Purpose |
|------|---------|
| `ck3_file(command="read", mod_name, rel_path)` | Read file from mod |
| `ck3_file(command="write", mod_name, rel_path, content)` | Write file to mod |
| `ck3_file(command="edit", mod_name, rel_path, old_content, new_content)` | Search/replace edit |
| `ck3_file(command="list", mod_name)` | List files in mod |

### Git

| Tool | Purpose |
|------|---------|
| `ck3_git(command="status", mod_name)` | Check modified files |
| `ck3_git(command="diff", mod_name)` | View changes |
| `ck3_git(command="add", mod_name, all_files=true)` | Stage files |
| `ck3_git(command="commit", mod_name, message)` | Commit |

### Logs

| Tool | Purpose |
|------|---------|
| `ck3_logs(source="error", command="summary")` | Error log summary |
| `ck3_logs(source="game", command="list")` | Game log errors |

---

## CK3 Load Order & Override Mechanics

### How Files Are Loaded

1. **Alphabetical ordering is evaluated first** - Files are sorted alphabetically across ALL sources (vanilla + all mods)
2. **Later-loaded files modify earlier ones** - A file loading after another can override its content
3. **Mod load order affects same-named files** - When two mods have identically-named files, mod load order determines which loads last

### Override Types

| Type | How It Works | When to Use |
|------|--------------|-------------|
| **Full Override** | Exact filename match (e.g., `common/traits/00_traits.txt`) replaces the entire vanilla file | When you need complete control over a file |
| **Partial Override** | Different filename with prefix (e.g., `zzz_my_fix.txt`) - only define blocks you're changing, others carry over | When fixing specific symbols without touching the rest |

### File Prefixes

| Prefix | Alphabetical Position | Effect |
|--------|----------------------|--------|
| `00_` | Sorts early | Loads first, will be overridden by later files |
| `zzz_` | Sorts late | Loads last, overrides earlier files |

**Example:** Your mod's `common/traits/zzz_brave_fix.txt` loads AFTER vanilla's `common/traits/00_traits.txt` because `zzz_` > `00_` alphabetically. You only need to define `brave = { }` in your file - other traits carry over from vanilla.

### Exact Filename Matches

If your mod contains `common/traits/00_traits.txt` (same name as vanilla), this is a **full override**:
- Your file completely replaces vanilla's file
- You must include ALL content, not just changes
- Mod load order determines which mod's version wins if multiple mods have this file

---

## Merge Policies

| Policy | Behavior | Used By |
|--------|----------|---------|
| **OVERRIDE** | Last definition wins | ~95% of content (traits, events, decisions, etc.) |
| **CONTAINER_MERGE** | Container merges, sublists append | `on_action` ONLY |
| **PER_KEY_OVERRIDE** | Each key independent | localization, defines |
| **FIOS** | First wins | GUI types (use `00_` prefix) |

---

## on_action Rules (CRITICAL)

**on_action uses CONTAINER_MERGE** with traps:

### Single-Slot Blocks (CONFLICT - only ONE allowed, last wins)
- `effect = { }`
- `trigger = { }`
- `weight_multiplier = { }`

### List Blocks (SAFE - all entries merge)
- `events = { }` ✅
- `on_actions = { }` ✅
- `random_events = { }` ✅

### ✅ CORRECT Pattern
```pdx
# Hook via list - SAFE
on_game_start = {
    on_actions = { my_mod_on_game_start }
}

# Isolated on_action
my_mod_on_game_start = {
    effect = {
        # Your code - no conflict
    }
}
```

### ❌ WRONG Pattern
```pdx
# DESTROYS vanilla's effect block
on_game_start = {
    effect = { }
}
```

---

## Workflow

1. **Search** - Use `ck3_search` to find symbols and context
2. **Check conflicts** - Use `ck3_conflicts` to understand overrides
3. **Validate** - Use `ck3_parse_content` before writing
4. **Write** - Use `ck3_file(command="write", mod_name, rel_path, content)`
5. **Commit** - Use `ck3_git` to track changes

---

## Golden Rules

1. **Always search before creating** - The symbol might exist
2. **Always validate syntax** before writing
3. **Never add `effect = { }` to vanilla on_actions** - Use `on_actions` list
4. **Use `zzz_` prefix** to win OVERRIDE conflicts
5. **Commit changes** with meaningful messages
