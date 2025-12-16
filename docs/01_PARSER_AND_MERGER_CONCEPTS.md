# CK3 Parser and Merger Concepts

## 1. What is a "parser" here?

CK3 script looks like this:

```txt
culture = {
    name = "english"
    traditions = {
        tradition_longbow_competitions
        tradition_agrarian
    }
}
```

To a **parser**, this isn't just text, it's **structured data**:

* There is a **block** called `culture`
* Inside it are **keys** (`name`, `traditions`)
* `traditions` contains a **list of values**

A **proper parser**:

1. Reads the file character by character.
2. Understands `{`, `}`, `=`, names, strings.
3. Builds a tree-like structure in memory, e.g.:

```json
{
  "type": "block",
  "name": "culture",
  "children": [
    { "key": "name", "value": "english" },
    { "key": "traditions", "value": ["tradition_longbow_competitions", "tradition_agrarian"] }
  ]
}
```

Once you have **this tree**, you can:

* Find "the definition of `tradition_mountain_homes`".
* Merge two definitions intelligently.
* Change one field (`weight`, `ai_will_do` etc.) without breaking the rest.

That's what I mean by a "proper parser".

---

## 2. What is a "merger"?

Imagine you have 3 mods that touch the same thing:

* Vanilla:

```txt
tradition_mountain_homes = {
    ai_will_do = { base = 1 }
    heavy_infantry_damage = 0.10
}
```

* Mod A:

```txt
tradition_mountain_homes = {
    heavy_infantry_damage = 0.20
}
```

* Mod B:

```txt
tradition_mountain_homes = {
    ai_will_do = { base = 5 }
}
```

A **merger** is the bit of code that decides:

> Given all these definitions, what is the **final** one?

Naive CK3 rule is *last key wins*, but a smart tool might want to:

* Combine them into:

```txt
tradition_mountain_homes = {
    ai_will_do = { base = 5 }          # from Mod B
    heavy_infantry_damage = 0.20       # from Mod A
}
```

…and annotate where each line came from.

To do that safely, you need:

* Parsed trees (from the parser).
* Rules for how to merge nodes (that's the "merger").

---

## 3. Why not just "use regex"?

**Regex** = "search text by patterns like `tradition_mountain_homes = { ... }`".

Example:

You might try to grab the whole tradition block with a regex like:

```regex
tradition_mountain_homes\s*=\s*\{[^}]*\}
```

Problems:

1. **Nested braces**
   CK3 script can nest blocks:

   ```txt
   ai_will_do = {
       base = 1
       modifier = {
           factor = 2
           has_trait = brave
       }
   }
   ```

   Your regex thinks `{ ... }` stops at the **first** `}`, but there may be many `}` inside. It gets confused.

2. **Multiple blocks with similar shapes**
   Regex doesn't know which `{` belongs to which `}` logically. Once files get long and complex, regex starts grabbing too much or too little.

3. **Comments, weird spacing, includes**
   `# comment`, weird formatting, line breaks, or future paradox changes will break fragile regexes.

4. **Merging is impossible to do reliably as text**
   If two mods both define `ai_will_do` blocks, you can't easily say:

   * "Keep Mod A's `base`, but Mod B's `modifier`"
     …unless you understand the **structure**, not just the raw characters.

So "hacking it with regex" means:

* Trying to slice and glue raw `.txt` files with pattern matching.
* It might work for small examples.
* It will break in real-world, messy playsets like yours.

---

## 4. So what does "build a proper parser/merger" *actually* imply?

In practical terms, if you (or someone) built this tool:

1. **Parser part**

   * Write code that can read Paradox script and output a structured tree:

     * Blocks with names, keys, values, nested children.
   * This is like what CK3 itself does internally.

2. **Merger part**

   * For each "thing" (event, decision, tradition, define, on_action):

     * Collect all definitions from vanilla + mods, in load order.
     * Decide how to combine or override them.

       * Sometimes last one wins.
       * Sometimes lists are appended.
       * Sometimes you want a custom rule.

3. **Exporter**

   * Turn the merged tree back into `.txt` files.
   * Add comments like:

     ```txt
     # SOURCE: vanilla + RICE + CE
     ```
   * Or create JSON reports summarizing who overwrote what.

That's what I was getting at with:

> "build a proper parser/merger instead of trying to hack it with regex."

It's the difference between:

* Treating CK3 files as **structured data** → robust, but more work up front.
* Treating them as a **pile of text** → quick and dirty, but brittle and unreliable.
