# CK3 Compatibility Patching Tips

> **Status:** Living document  
> **Last Updated:** January 6, 2026  
> **Purpose:** Collected wisdom for creating compatibility patches between CK3 mods

---

## 1. Merge Policies Quick Reference

| Content Type | Policy | Winner | Strategy |
|--------------|--------|--------|----------|
| Events | OVERRIDE | Last loaded | Use `zzz_` prefix, same namespace+ID |
| Traits | OVERRIDE | Last loaded | Use `zzz_` prefix |
| Decisions | OVERRIDE | Last loaded | Use `zzz_` prefix |
| Scripted Effects/Triggers | OVERRIDE | Last loaded | Use `zzz_` prefix |
| on_actions | CONTAINER_MERGE | Lists append, effect/trigger = last | Use `on_actions = { }` list |
| Localization | PER_KEY_OVERRIDE | Last loaded per key | Use `replace/` folder |
| GUI | FIOS | First loaded | Use `00_` prefix |

---

## 2. Overriding Events from Other Mods

### Key Insight: Events Use OVERRIDE Policy

Unlike `on_action` blocks (which use CONTAINER_MERGE), events use **OVERRIDE** - the last definition of an event ID wins completely.

### How to Override Another Mod's Event

1. **Create an event file** in `events/` with a name that sorts AFTER the source mod's file
   - Example: `zzz_msc_histmod_events.txt` sorts after `histmod_events.txt`

2. **Use the SAME namespace** as the original event
   ```pdx
   namespace = histmod  # NOT msc_histmod
   ```

3. **Use the EXACT event ID** you want to override
   ```pdx
   histmod.0059 = {  # NOT msc_histmod.0059
       # your fixed version here
   }
   ```

4. **Your mod must load AFTER** the source mod in the playset load order

### Common Mistake

❌ **Wrong approach:**
```pdx
namespace = msc_histmod
msc_histmod.0059 = { ... }  # Creates NEW orphaned event - never triggered!
```

✅ **Correct approach:**
```pdx
namespace = histmod
histmod.0059 = { ... }  # Overrides original event
```

### When to Use This Pattern

- Fixing bugs in other mods (like adding safety checks)
- Adding compatibility with other mods
- Modifying event behavior without touching on_actions

### When NOT to Use This Pattern

- If you want BOTH versions to run → use `on_action` hooks instead
- If you don't control load order → may not work reliably

---

## 3. Extending on_actions Safely

### The Problem

`on_action` blocks use CONTAINER_MERGE, but **only the `events` and `on_actions` lists merge**. The `effect` and `trigger` blocks are OVERRIDE (last wins).

### Safe Pattern: Use the on_actions List

```pdx
# DON'T add effect blocks to vanilla on_actions - you'll override!
# DO chain to your own on_action via the list

on_game_start = {
    on_actions = { my_mod_on_game_start }  # Appends to list - SAFE
}

# Your isolated on_action with its own effect block
my_mod_on_game_start = {
    effect = {
        # Your code here - completely isolated, no conflict!
        trigger_event = my_mod_setup.001
    }
}
```

### Why This Works

- `on_actions = { }` lists APPEND from all mods
- Your `my_mod_on_game_start` has its own isolated `effect` block
- No conflict with other mods' effects

---

## 4. File Naming Conventions

| Prefix | Load Order | Use For |
|--------|------------|---------|
| `00_` | First | GUI (FIOS), things you want to be base |
| `zzz_` | Last | Overrides, compatibility patches |
| (none) | Middle | Normal content |

### Load Order Within a Mod

Files are loaded **alphabetically** within each folder. So:
- `00_base_traits.txt` loads before `traits.txt`
- `traits.txt` loads before `zzz_override_traits.txt`

### Load Order Between Mods

Determined by playset order. Later mods override earlier mods for OVERRIDE types.

---

## 5. Debugging Conflicts

### Using ck3_conflicts Tool

```
ck3_conflicts(command="symbols")  # Find symbol conflicts
ck3_conflicts(command="files")    # Find file conflicts
ck3_conflicts(symbol_type="event")  # Only event conflicts
```

### Using ck3_search Tool

```
ck3_search("brave", symbol_type="trait")  # Find all definitions
ck3_search("on_game_start", game_folder="common/on_action")
```

---

## 6. Common Compatch Scenarios

### Scenario: Two Mods Define Same Trait

**Problem:** ModA and ModB both define `trait_brave`

**Solution:** Create compatch mod that:
1. Loads AFTER both (use `zzz_` prefix)
2. Defines the merged version with features from both
3. Or picks one and documents why

### Scenario: Event Chain Broken

**Problem:** ModA's event calls `modA.0050` but ModB overwrote it

**Solution:** 
1. Check if ModB's version is compatible
2. If not, create compatch that restores critical logic
3. Use same namespace + event ID to override ModB

### Scenario: on_action Effects Conflict

**Problem:** Both mods add `effect = { }` to `on_birth`

**Solution:**
1. Both should use `on_actions = { my_on_birth }` pattern instead
2. If they don't, compatch needs to merge both effects

---

## 7. Testing Compatch Changes

1. **Check error.log** after game start for missing references
2. **Use console** to trigger events/decisions manually
3. **Verify load order** in launcher matches expectations
4. **Test with both mods disabled** to ensure no hard dependencies

---

## Appendix: Merge Policy Details

See [05_ACCURATE_MERGE_OVERRIDE_RULES.md](05_ACCURATE_MERGE_OVERRIDE_RULES.md) for complete documentation.
