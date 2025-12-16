# Existing Tools and Feasibility Assessment

## 1. Does anyone already have such a parser?

There are a few things *nearby*:

* People have built **Paradox script highlighters** and some partial parsers for IDEs and tools (VSCode extensions, etc.).
* Some mod tools can do **basic validation** or scanning of `.txt` files.
* There are **EU4/HOI4/Stellaris** script parsers used for map editors or validators.

But what *you're* talking about is:

1. A parser that can:
   * Robustly read CK3 script into an AST.

2. A **merger/resolver** that:
   * Emulates CK3 load order.
   * Resolves conflicting definitions.
   * Produces a **single "final game" directory** + provenance.

I haven't seen anything that goes all the way to:

> "Feed in a playset, get the exact merged final state with per-block source attribution."

So: parsers *exist in pieces*, but your envisioned **full emulator + provenance tool** is, as far as I know, *not* a solved/packaged thing.

---

## 2. How technically hard is this?

### Skill level

You'd want someone (or a small team) comfortable with:

* Writing parsers (or using a parser generator)
* Working with tree/graph structures (ASTs)
* Some domain knowledge of CK3 / Paradox script

Rough difficulty:

* **Harder than a typical hobby script**,
* **Easier than writing a game engine**,
* In the range of: *"serious side project / small tool product"*.

### Main technical chunks

1. **Lexer + Parser**
   * Turn `.txt` into tokens (`identifier`, `=`, `{`, `}`, string, number).
   * Build nested blocks (`foo = { bar = baz }`).
   * Need to handle:
     * Comments `# ...`
     * Weird whitespace
     * Strings with quotes
   * This is work, but the grammar is relatively simple (no crazy recursion beyond nested `{}`).

2. **Semantic model**
   * Understand that `culture = {}` and `tradition_mountain_homes = {}` are objects with keys.
   * Represent them as maps keyed by name, e.g.:
     * `"tradition_mountain_homes"` → node tree.

3. **Load-order & merge logic**
   * Read playset JSON → ordered list of mods.
   * For each mod (in load order) and each parsed file:
     * Insert/override objects into a big registry:
       * Last definition of `foo = {}` wins (unless you define clever merge rules).
   * Special cases:
     * `defines`
     * `on_actions`
     * scripts that rely on `add = {}` patterns

4. **Export + provenance**
   * Walk the final registry and write back `.txt` files.
   * Insert comments or save a JSON metadata file that records:
     * Which mod "won".
     * Which mods previously defined this object.

None of this is "moonshot impossible". It's just **a decent chunk of engineering**.

---

## 3. Can "agent AI" build this?

Your gut that *this is a good agent AI use-case* is pretty solid, **with caveats**:

### What AI *can* realistically help with

* **Bootstrapping the parser**:
  * Drafting the lexer/parser code.
  * Handling common patterns and edge cases.

* **Designing the merge rules**:
  * Given examples ("Mod A does X, Mod B does Y; final expected is Z"), AI can propose or refine heuristics.

* **Scaffolding the tool**:
  * CLI interface skeleton:
    * `ck3-resolve --playset playset.json --output ./final_game`
  * Config formats (JSON/YAML schemas).

* **Writing test cases**:
  * Generate a battery of small CK3 script snippets to test parsing and merging.

So an "agent" system could:
* Iterate over code, run tests, fix obvious bugs.
* Help with **boring plumbing** and refactors.
* Speed up development massively.

### What AI *cannot* safely do alone (yet)

* Be trusted blindly with all edge cases:
  * You will still need a human to:
    * Review logic.
    * Validate against real CK3 behaviour.
    * Decide special cases (like `on_actions` merging).

So: **AI-as-accelerator, not AI-as-solo-developer**.

---

## 4. If you *wanted* to build this, what's a sane first step?

If someday you want to explore this with an AI helper, I'd suggest:

1. **Narrow scope aggressively** for v0:
   * Target *one* folder type, e.g.:
     * `common/culture/traditions/*.txt`
   * Goal: Given several mods touching traditions, produce:
     * Final merged `00_traditions.txt` with `# SOURCE:` comments.

2. Use AI to:
   * Draft the lexer/parser for Paradox script.
   * Draft a small "tradition registry" & merge logic.
   * Generate unit tests like:
     * "Vanilla + Mod A + Mod B" → expected merged tradition.

3. Once that works, expand to:
   * `common/culture/cultures`
   * `decisions`
   * `events`

That's where agents shine: lots of repeated pattern work that still needs a human brain guiding direction.

---

## TL;DR

* **No**, there isn't (as far as I know) a finished, public tool that does exactly what you described (full CK3 playset → final merged directory with provenance).
* **Yes**, what you're imagining is technically realistic, but it's a **serious project**, not a weekend script.
* **Yes**, your instinct that *"this could be built with an agent AI helping"* is correct:
  * AI could handle a lot of scaffolding and boilerplate.
  * A human (you or a collaborator) would still need to steer, test, and enforce correctness.
