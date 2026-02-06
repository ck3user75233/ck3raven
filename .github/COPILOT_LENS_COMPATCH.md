# CK3 Lens Mode

**Mode:** `ck3lens` | **Purpose:** CK3 mod compatibility patching and error fixing

---

## Key Tools

| Tool | Purpose |
|------|---------|
| `ck3_search(query)` | Search symbols, content, files |
| `ck3_file(command="read/write/edit")` | Read/write mod files |
| `ck3_parse_content(content)` | Validate CK3 syntax |
| `ck3_conflicts` | Find symbol/file conflicts |
| `ck3_playset` | Get active playset and mods |
| `ck3_git` | Git operations on mods |

---

## Write Access

Enforcement decides at execution based on location:
- **Local mods folder** → ✅ Writable (with contract)
- **Workshop/vanilla** → ❌ Read-only

Just attempt the write - enforcement will respond.

---

## CK3 Merge Rules

| Policy | Behavior | Used By |
|--------|----------|---------|
| **OVERRIDE** | Last definition wins | ~95% (traits, events, decisions) |
| **CONTAINER_MERGE** | Lists append, single-slots conflict | on_action ONLY |
| **PER_KEY_OVERRIDE** | Each key independent | localization, defines |
| **FIOS** | First wins | GUI types (use `00_` prefix) |

### File Loading Order
Files sort **alphabetically across ALL sources**. Use prefixes:
- `00_` → Loads early (gets overridden)
- `zzz_` → Loads late (wins conflicts)

---

## on_action (CRITICAL)

**CONTAINER_MERGE with traps:**

| Block | Behavior |
|-------|----------|
| `events = { }`, `on_actions = { }` | ✅ Lists append safely |
| `effect = { }`, `trigger = { }` | ⚠️ Single-slot - last wins, CONFLICTS |

### ✅ Correct Pattern
```pdx
on_game_start = {
    on_actions = { my_mod_init }  # Hook via list - safe
}

my_mod_init = {
    effect = { }  # Your own on_action - no conflict
}
```

### ❌ Wrong Pattern
```pdx
on_game_start = {
    effect = { }  # DESTROYS vanilla's effect block
}
```

---

## Workflow

1. **Search** → `ck3_search`
2. **Validate** → `ck3_parse_content` before writing
3. **Write** → `ck3_file(command="write")`
4. **Commit** → `ck3_git`

---

## Golden Rules

1. **Search before creating** - symbol might exist
2. **Validate syntax** before writing
3. **Never add `effect = { }` to vanilla on_actions**
4. **Use `zzz_` prefix** to win OVERRIDE conflicts
