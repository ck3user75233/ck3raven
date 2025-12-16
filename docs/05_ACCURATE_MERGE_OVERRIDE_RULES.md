# CK3 Merge/Override Behavior - Accurate Rules

> **Source:** Verified from Paradox's official `game/common/on_action/_on_actions.info` file and MSC mod structure (December 2025).

---

## Official Paradox Documentation (Verbatim)

From `_on_actions.info`:

> "You can declare data for on-actions in multiple files, however, **you cannot have multiple triggers or effect blocks for a given named on-action**. In particular, you cannot append an effect block directly to an on_action which already has an effect block, as this creates a conflict."

And the recommended workaround:

```txt
some_vanilla_on_action = {
    on_actions = { some_modded_on_action }
}
some_modded_on_action = {
    effect = {
        some_fun_modding_effect = yes
    }
}
```

This makes the vanilla on-action call the modded on-action whenever it fires.

---

## 1. The Critical Rule for on_actions

### Each named on_action can have **exactly ONE** of each:

| Block Type | Slots | Behavior |
|------------|-------|----------|
| `effect = { }` | **ONE** | Last loaded wins (conflict) |
| `trigger = { }` | **ONE** | Last loaded wins (conflict) |
| `weight_multiplier = { }` | **ONE** | Last loaded wins |
| `fallback = name` | **ONE** | Last loaded wins |

### Lists inside on_actions **APPEND/MERGE**:

| List Type | Behavior |
|-----------|----------|
| `events = { }` | Appends all entries |
| `random_events = { }` | Appends weights/entries |
| `first_valid = { }` | Appends to list |
| `on_actions = { }` | Appends all named on_actions |
| `random_on_actions = { }` | Appends weights/entries |
| `first_valid_on_action = { }` | Appends to list |

---

## 2. Why This Matters

The previous documentation incorrectly implied:
- ❌ "If they're distinct (e.g. `effect = {}` vs `effect_2 = {}`) they can stack"
- ❌ "If they share the same key/slot, then last one wins"

**The truth is simpler:**
- ✅ There is only **ONE `effect` slot** per on_action
- ✅ There is only **ONE `trigger` slot** per on_action  
- ✅ Effect names don't matter - the syntax doesn't support `effect_2`
- ✅ If two mods define `effect = {}` for the same on_action, it's a **conflict**

---

## 3. How Mods Correctly Extend On_Actions

### Best Practice: Chain custom on_actions from vanilla

**Mod A's file:**
```txt
on_game_start = {
    on_actions = {
        mod_a_on_game_start
    }
}

mod_a_on_game_start = {
    effect = {
        # Mod A's logic here - safe, no conflict
    }
}
```

**Mod B's file:**
```txt
on_game_start = {
    on_actions = {
        mod_b_on_game_start
    }
}

mod_b_on_game_start = {
    effect = {
        # Mod B's logic here - safe, no conflict
    }
}
```

### Result after CK3 merges:

```txt
on_game_start = {
    # From vanilla + all mods - LISTS MERGE:
    on_actions = {
        # vanilla's on_actions...
        mod_a_on_game_start     # appended from Mod A
        mod_b_on_game_start     # appended from Mod B
    }
    events = {
        # vanilla's events...
        # mod events appended...
    }
    # effect = { } - only ONE, from whoever defined it last
}
```

---

## 4. Example of a Conflict

### Vanilla:

```txt
on_character_death = {
    effect = {
        add_prestige = 10
    }
}
```

### Mod A:

```txt
on_character_death = {
    effect = {
        add_piety = 5
    }
}
```

### Result: CONFLICT

- Mod A's `effect` **completely replaces** vanilla's `effect`
- The `add_prestige = 10` is **LOST**
- This is NOT a merge - it's an override

### Correct approach:

```txt
on_character_death = {
    on_actions = { mod_a_death_actions }
}

mod_a_death_actions = {
    effect = {
        add_piety = 5
    }
}
```

Now vanilla's `effect = { add_prestige = 10 }` is preserved AND mod A's effect runs.

---

## 5. Example with Multiple Mods Working Correctly

### Vanilla:

```txt
on_game_start = {
    effect = { 
        # vanilla setup
    }
    events = { vanilla_event.100 }
    on_actions = {
        culture_setup_vanilla
    }
}
```

### Mod A (CAD):

```txt
on_game_start = {
    on_actions = {
        on_game_start_cad
        on_game_start_cad_867
    }
}

on_game_start_cad = {
    effect = {
        # CAD's faith setup
    }
}
```

### Mod B (TCT):

```txt
on_game_start = {
    on_actions = {
        tct_on_start
        tct_on_start_867
    }
}

tct_on_start = {
    effect = {
        # TCT's coronation setup
    }
}
```

### Final merged result:

```txt
on_game_start = {
    effect = { 
        # vanilla setup (preserved - no mod overrode it)
    }
    events = { vanilla_event.100 }
    on_actions = {
        culture_setup_vanilla      # from vanilla
        on_game_start_cad          # appended from CAD
        on_game_start_cad_867      # appended from CAD
        tct_on_start               # appended from TCT
        tct_on_start_867           # appended from TCT
    }
}
```

Each mod's custom on_action runs with its own isolated `effect` block - no conflicts!

---

## 6. Complete on_action Structure Reference

From Paradox's `_on_actions.info`:

```txt
on_action_name = {
    trigger = { }           # ONE per on_action - conditions to fire
    weight_multiplier = { } # ONE per on_action - for random selection
    
    events = { }            # LIST - appends from all files
    random_events = { }     # LIST - appends weights/entries
    first_valid = { }       # LIST - appends entries
    
    on_actions = { }        # LIST - appends named on_actions
    random_on_actions = { } # LIST - appends weights/entries
    first_valid_on_action = { } # LIST - appends entries
    
    effect = { }            # ONE per on_action - runs effects
    fallback = name         # ONE per on_action - fallback if nothing fires
}
```

---

## TL;DR - The Accurate Rules

### ✅ APPENDS (Lists merge across files)
- `events = { }`
- `on_actions = { }`
- `random_events = { }`
- `random_on_actions = { }`
- `first_valid = { }`
- `first_valid_on_action = { }`

### ❌ CONFLICTS (Only ONE per named on_action, last loaded wins)
- `effect = { }`
- `trigger = { }`
- `weight_multiplier = { }`
- `fallback = x`

### ✅ Best Practice
Chain your mod's on_actions from vanilla using the `on_actions = { }` list:
```txt
vanilla_on_action = {
    on_actions = { my_mod_custom_on_action }
}
my_mod_custom_on_action = {
    effect = { /* your code here - no conflict */ }
}
```

---

## Implementation Note for Game State Emulator

The emulator's `CONTAINER_MERGE` policy for on_actions must:

1. **Merge lists**: Concatenate all `events`, `on_actions`, `random_events`, etc. entries
2. **Override singles**: Keep only the last `effect`, `trigger`, `weight_multiplier`, `fallback`
3. **Track conflicts**: Flag when multiple mods define `effect` or `trigger` for the same on_action ID
4. **Report**: Identify which mod's `effect`/`trigger` won and which were overwritten
