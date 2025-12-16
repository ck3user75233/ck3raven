# Original Concept: CK3 Game State Emulator

## The Core Idea

Feed it a **playset (JSON)** and it applies CK3 modding rules to that playset and spits out a directory in the CK3 game file structure that represents the **final output** that comes from applying that playset to vanilla CK3.

Each block would have a **comment inserted** to say from where the text came from, e.g. "vanilla" or "RICE mod" etc.

---

## What You're Proposing

* Input:
  * A **playset description** (JSON) → list of mods, load order, enabled/disabled flags.

* Process:
  * Parse all mods + vanilla.
  * Apply CK3's **load-order and override rules** to produce a *resolved* view of:
    * `common/*` (cultures, traditions, laws, etc.)
    * `events`, `decisions`, `scripted_effects`, `scripted_triggers`, `localization`, etc.

* Output:
  * A **synthetic "final game" directory** with the *effective* version of every file/block as the engine would see it.
  * Within each block, insert comments like:

    ```txt
    # SOURCE: vanilla
    # SOURCE: RICE - 01_rice_events.txt
    # SOURCE: CE - decisions\ce_decisions.txt
    ```
  * So a modder can open `final/common/culture/traditions/00_traditions.txt` and see the *actual* definition that will run.

---

## Why This Is a Good Idea

This would solve several real-world headaches:

### "What actually wins?"
When 5 mods touch `tradition_mountain_homes`, which one actually ends up live?

### Detect silent overrides
Mods that accidentally nuke others' defines / blocks because they copied old vanilla files.

### Compatch design
Lets you see exactly what needs reconciling instead of diffing each pair of mods manually.

### Diff vs vanilla
You can generate "final game vs pure vanilla" diffs to see *all* net effects of your playset.

---

## Hard Parts / Risks

### You aren't just merging files, you're merging *semantic blocks*:

* CK3 doesn't use a simple "last file wins" model; it's "last definition of this scope/key wins."
* You need to parse Paradox script into a structured tree:
  * `culture = { ... }`, `tradition_x = { ... }`, `on_action = { ... }`, etc.

### Multiple files defining same scope:

* E.g. `00_defines.txt` from vanilla, plus multiple mods also defining defines.
* Some things are additive (like lists), some are overriding.

### On_actions, scripted effects, triggers:

* These can be **appended** via `on_action_x = { add = { ... } }` style patterns. A naive override-merger could delete important hooks.

### Localization:

* Multiple mods can define the same loc key. You'd need to choose final winner based on load order, language, DLC, etc.

---

## How to Improve / Structure the Idea

### 1. Make it a "Paradox Script Resolver" first, CK3-specific second

* Write a robust parser for `.txt` script → AST.
* Then apply **override rules** at the level of:
  * `top-level object (e.g., culture) keyed by name`.
  * `defines` keyed by `[category].[key]`.
  * `on_action` sections keyed by name, merging sub-blocks where appropriate.
* CK3-specific rules can be plugged in later (e.g. special handling for `on_action`, `scripted_*`).

### 2. Multi-layer provenance metadata instead of just comments

* Internally, store:

  ```json
  {
    "key": "tradition_mountain_homes",
    "final_source": "Mod D",
    "contributors": [
      {"mod": "Vanilla", "file": "...", "line_range": "10-50"},
      {"mod": "RICE", "file": "...", "line_range": "15-40"},
      {"mod": "CE", "file": "...", "line_range": "100-150"}
    ]
  }
  ```

* Then when exporting:
  * Option A: Plain text with `# SOURCE: ...` comments.
  * Option B: A **sidecar JSON report** summarizing each key, who overwrote whom.

### 3. Diff views built-in

* For each object (culture, tradition, etc.), auto-generate:
  * `vanilla` vs `final`
  * `mod X` vs `final`
* Let the user say: "Show me everything where RICE's definition was partially or wholly overwritten by another mod."

### 4. Conflict detector

* On top of the emulator, build:
  * "These 37 keys have conflicting definitions between Mod A and Mod B."
  * "These 5 on_actions have been replaced rather than merged, which is probably bad."
* That alone would make it a killer tool.

### 5. At first, restrict scope

* Phase 1: `common/*` & `events` & `decisions`.
* Phase 2: `on_actions`, `scripted_*`, `defines`.
* Phase 3: localization and GUIs.

---

## Conclusion

**Strong idea**, but big engineering lift. It becomes more realistic if you scope it and build a proper parser/merger instead of trying to hack it with regex.
