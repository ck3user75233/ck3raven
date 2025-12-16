# Virtual Merge Explained

A **virtual merge** is a *conceptual* or *synthetic* merging of multiple definitions of the same CK3 object into a single combined block — **even though CK3 itself does NOT merge them at runtime**.

It is extremely important because CK3's real load-order system is **brutally simple**:

> **Final definition wins wholesale**
> Not field-by-field.
> Not selective.
> Entire block is replaced.

A **virtual merge** is something *a tool* would do — **not CK3** — to help a modder understand all the data that exists across multiple mods and what would happen if they were combined semantically.

---

## 1. What a "Virtual Merge" Means (simple definition)

A **virtual merge** means:

> *"Take the final winning block AND all overridden blocks, and combine their fields so I can see all differences side-by-side or as one combined synthetic block."*

This can be used for:

* Debugging
* Conflict detection
* Compatch development
* Understanding "what Mod A changed vs Mod B vs vanilla"
* Seeing partial overlaps in events, modifiers, triggers, etc.

CK3 itself **never** does this kind of merge.
It always uses **last one wins**.

But a tool can do a virtual merge to help humans.

---

## 2. What types of CK3 blocks a virtual merge is useful for

Virtual merging is most useful for:

---

### (A) Objects that are fully overridden in-game

CK3 overrides these ENTIRELY:

#### 1. Culture Traditions

`common/culture/traditions/*.txt`

* Only the **final** block is used.
* Mods that touch the same tradition overwrite it wholesale.

A virtual merge can show:

* What vanilla had
* What RICE adds
* What CE overrides
* What is missing in final output
* Which parts conflict

---

#### 2. Cultures and culture fields

`common/culture/cultures/*.txt`

A virtual merge helps show:

* Difference in ethos/pillars between mods
* Which traditions were changed
* What modifiers were lost

---

#### 3. Events

`events/*.txt`

If two mods define the same event ID, the last one *completely overwrites* the earlier.

A virtual merge lets you compare:

* The two event's immediate blocks
* Trigger differences
* Script effects added/removed
* Differences in tooltips

---

#### 4. Decisions

`decisions/*.txt`

Fully overridden if same decision key is defined by two mods.

A virtual merge helps:

* Compare decision triggers and costs
* Find missing ai_chance blocks
* Spot changed requirements

---

#### 5. Scripted Effects / Scripted Triggers

`common/scripted_effects/*.txt`
`common/scripted_triggers/*.txt`

If two mods define the same effect name:

* Last mod wins
* Undoing all previous logic

Virtual merge identifies:

* Conditions removed
* Logic lost
* Parameters changed

Very useful for debugging.

---

#### 6. Government Types, Laws, Tenets, Doctrines

These are all overridden fully.

A virtual merge shows:

* Missing doctrines/parameters
* Changed opinion modifiers
* Altered AI values

---

#### 7. Game Rules and Men-at-Arms Types

Same rule applies: full override.
Virtual merge helps reveal what changed.

---

## 3. Types of Blocks Where Virtual Merge Is *Not* Needed (because CK3 merges natively)

CK3 *automatically* merges some things:

---

### A) on_actions

These are **natively additive**.

* Any mod can append new blocks inside on_action.
* Only if a mod redefines the *top-level on_action itself* does it override.

Virtual merge may still be useful for inspection, but is not essential.

---

### B) Localization files

Loc keys override per-key, not block.

No virtual merge needed.

---

### C) Any "list-type" appends using `add = {}` or `modifier = {}` patterns

Some scripted objects internally support appending.

Example:

```txt
on_action = {
    on_yearly_pulse = {
        add = { effect = my_mod_effect }
    }
}
```

These **stack** unless completely overridden.

Virtual merging is less urgent here.

---

## 4. Why virtual merging matters for a "tradition resolver" tool

Because:

1. CK3's runtime behaviour is **last block wins**.
2. Mods that partially modify traditions often get **silently overwritten**.
3. Final result may throw away:
   * triggers
   * ai_will_do blocks
   * modifiers
   * military buffs
   * special scripts

A virtual merge would let you compare:

### Final block (actual game result)

vs

### Synthetic merged block (everything reachable across mods)

vs

### Diff highlighting what was removed or altered.

This is HUGELY useful for:

* Compatch authors
* Mod testers
* Anyone debugging cultural issues

---

## TL;DR

### A **virtual merge** is:

A *synthetic*, *tool-generated* block that merges all versions of an object (tradition/event/decision/etc.) so you can see everything together — even though CK3 itself never does this.

### It applies to:

* traditions ✔
* cultures ✔
* events ✔
* decisions ✔
* scripted effects/triggers ✔
* government types ✔
* laws ✔
* doctrines/tenets ✔
* modifiers ✔

### CK3 natively merges:

* on_actions (additive)
* loc keys
* some list-style append systems
