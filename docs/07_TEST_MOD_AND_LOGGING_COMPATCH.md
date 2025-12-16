# Bonus Idea: Auto-Generated Test Mod + Logging Compatch

Two related sub-ideas for debugging CK3 playsets:

1. **A tool that autogenerates a test mod with decisions** to verify that a playset behaves as intended.
2. **A "logging compatch" generator** that, given a playset or specific problem area, injects logging into key scripts.

---

## 1. Test Mod with Decisions

### Concept

* Input:
  * Metadata about what you want to test:
    * E.g. "this tradition exists & is active",
    * "this event can fire & has no undefined variable",
    * "this decision appears in the UI given X conditions", etc.

* The tool generates a mod with:
  * A **debug decisions category** ("MSC Debug Tools" etc.)
  * Decisions like:
    * "Fire event X on my character."
    * "Print values of key variables to log."
    * "Give my culture tradition Y and then verify effects."
  * The decisions use scripted effects that do `log` and `show_effect` messages.

### What this gives you:

* A **standardized debug harness** you can apply to any playset.
* Instead of hand-writing a dozen temporary debug decisions for each bug, you click a config, rerun the tool, and it spits out an updated test mod.

### How to improve this idea

* Make it **config-driven**:
  * A simple JSON/DSL like:

    ```json
    {
      "tests": [
        {"type": "event", "id": "my_mod.1001"},
        {"type": "decision_visible", "id": "my_decision"},
        {"type": "culture_tradition", "id": "tradition_mountain_homes"}
      ]
    }
    ```
  * Tool reads this and generates the appropriate debug decisions + scripted effects.

* Provide **assertion-style logging**:
  * E.g. `ASSERT(has_culture_tradition = tradition_mountain_homes)`
    → prints clear pass/fail lines in the game log like:

    ```
    [MSC_TEST] PASS: culture has tradition_mountain_homes
    [MSC_TEST] FAIL: decision my_mod_decision not visible at game start
    ```

* Optionally add a **"Run All Tests" decision**:
  * Fires a chain of effects checking all configured tests and prints a summary to log.

---

## 2. Logging Compatch Generator

This one is deliciously evil in a good way.

### Concept

* Input:
  * List of problematic areas: e.g. `events/my_event_file.txt`, `on_actions/00_on_actions.txt`, specific event IDs, etc.
  * Maybe the user marks *"log before / after these triggers/effects"*.

* The tool:
  * Parses those files.
  * **Injects logging** at key points:

    ```txt
    log = "[MSC_LOG] Entering my_event.1001, character = [ROOT.Char.GetName]"
    ```

    or

    ```txt
    custom_tooltip = { text = msc_log_event_1001_trigger_failed }
    ```
  * Wraps them in `if` or `only_run_in_debug_mode` style conditions if desired.

* Output:
  * A **small compatch mod**, last in load order, that:
    * Overrides or appends just enough script to add logging.
    * Can be turned on/off without touching original mods.

### How to make it powerful & safe

#### 1. Idempotent & reversible

* The tool never edits original mods.
* It generates its own files that:
  * Either use `@msc_log` markers, or
  * Use separate `scripted_effects`/`scripted_triggers` that are injected via `on_actions` or wrapper effects.

#### 2. Targeted instrumentation

* Instead of logging *everything*, you specify:
  * "Log entry/exit for these events: X, Y, Z."
  * "Log when `on_actions` `on_character_death` runs from these mods."
* The tool finds those definitions and adds logs automatically.

#### 3. Templates for common problems

* Predefined "instrumentation profiles":
  * "Event chain won't fire" → log event triggers, fire, immediate block.
  * "Tradition effect not applying" → log culture setup on game start.
  * "On_action not working" → log each on_action invocation and count.

#### 4. Optional UI feedback

* For some tests, you can have:

  ```txt
  add_trait = stressed_1
  show_as_tooltip = msc_log_message
  ```
* But more often you just want **clean log-only instrumentation**.

---

## How Both Tools Could Work Together

### Step 1: Run the Game State Emulator

* Get a report: which events, decisions, traditions exist and what overwrote what.
* Spot obvious conflicts before booting the game.

### Step 2: Generate a Test Harness + Logging Compatch

* Based on:
  * "These 5 events look suspicious/conflicted – instrument them."
  * "This decision seems overridden – add a test to check visibility & effect."

### Step 3: Run CK3 with the debug + logging mods

* Use the debug decisions to trigger tests.
* Read logs to see exactly where things go wrong.

Together, that's basically a **semi-automated CK3 mod laboratory**.

---

## Assessment

### Are these good ideas?

**Yes, both are very solid ideas** and very aligned with the real pain points of heavy CK3 playset/modding:

* Idea 1 (emulator) = *harder technically* but insanely useful for serious modders and compatch authors.
* Idea 2 (test mod + logging compatch) = *more feasible as a first project* and could be iterated into a really slick tool.

### Main improvements suggested:

1. **Treat everything as parsed AST, not raw text.**
   Both ideas become much more reliable and extensible if you have a proper Paradox-script parser as the core.

2. **Make them config-driven.**
   So you don't hardcode specific mods; you feed JSON/YAML that describes:
   * The playset.
   * The tests.
   * The logging targets.

3. **Build in conflict detection and summaries.**
   Don't just spit out merged files; also spit out:
   * "Here are 100 keys where more than one mod defines something."
   * "Here are 20 where the last mod likely broke someone else's content."

4. **Start small & iterate.**
   Phase 1 could be:
   * A prototype that:
     * Resolves a single `common/` type (e.g. traditions).
     * Generates a debug decision file for a couple of events.
   * That alone would already be very useful.
