# Tradition Resolver v0 Design Specification

We *do* know enough from CK3's file layout + wiki/modding norms to design a v0 just for **traditions**.

Here's a concrete design sketch.

---

## 0. Scope & assumptions for v0

**Goal (v0):**

Given:

* a **playset JSON** (vanilla + mods, in load order), and
* access to `game/common/culture/traditions/*.txt` for each mod,

produce:

1. A single **resolved traditions file** (or small set of files) where:
   * Each `tradition_xxx` appears **once**, as the engine would see it.
   * You know **which mod "won"** for that tradition.
   * You know which mods were **overridden**.

2. A small **conflict report** (CSV/JSON).

**Important simplification:**
For CK3 itself, a later definition of the *same key* fully overrides earlier ones. v0 will **faithfully emulate that**; we won't do clever field-level merging yet.

---

## 1. Inputs and outputs

### 1.1 Inputs

1. **Playset file (JSON)** – e.g. structure like the launcher's `dlc_load.json` / playset export:

```json
{
  "mods": [
    { "id": "vanilla", "type": "builtin", "path": "/path/to/ck3/game" },
    { "id": "RICE", "type": "local", "path": "/mods/RICE" },
    { "id": "CE", "type": "local", "path": "/mods/CultureExpanded" }
  ]
}
```

Mods are **ordered** as in the launcher: first = lowest priority, last = top priority.

2. For each entry, we assume a CK3-like layout:
   * Vanilla: `game/common/culture/traditions/*.txt`
   * Each mod: `mod_root/common/culture/traditions/*.txt`

### 1.2 Outputs

1. **Resolved traditions file(s)**, e.g.:

`out/common/culture/traditions/00_resolved_traditions.txt`

Containing blocks like:

```txt
# FINAL tradition_mountain_homes
# WINNER: CultureExpanded (common/culture/traditions/02_ce_traditions.txt)
# OVERRIDDEN: vanilla (common/culture/traditions/00_traditions.txt); RICE (common/culture/traditions/01_rice_traditions.txt)

tradition_mountain_homes = {
    ...full final block exactly as in the winning mod...
}
```

2. **Conflicts report**, e.g. `out/reports/tradition_conflicts.json`:

```json
{
  "tradition_mountain_homes": {
    "winner": {
      "mod_id": "CE",
      "file": "common/culture/traditions/02_ce_traditions.txt"
    },
    "overridden": [
      { "mod_id": "vanilla", "file": "common/culture/traditions/00_traditions.txt" },
      { "mod_id": "RICE", "file": "common/culture/traditions/01_rice_traditions.txt" }
    ]
  }
}
```

Plus maybe a CSV for quick eyeballing in Excel.

---

## 2. High-level pipeline

1. **Parse playset JSON → ordered mod list**
2. **Scan all `common/culture/traditions/*.txt`** in each mod.
3. **Lex & parse** each file into a simple AST.
4. Extract top-level **tradition definitions**: `tradition_* = { ... }`.
5. Feed them into a **TraditionRegistry** in *mod-load-order*.
6. After all mods processed, the registry knows, for each tradition:
   * full list of definitions (in order),
   * which one is the final winner.
7. **Export**:
   * a single resolved traditions file, and
   * a conflict report.

---

## 3. Core components

### 3.1 Playset reader

**Module:** `playset.py`

* Input: path to playset JSON.
* Output: list of `ModDescriptor` objects:

```python
class ModDescriptor:
    id: str           # "vanilla", "RICE", etc.
    path: str         # root directory
    priority: int     # 0, 1, 2, ...
```

* `vanilla` is either:
  * a synthetic first entry with `path=/path/to/ck3/game`, or
  * handled specially but treated as lowest priority.

---

### 3.2 File scanner

**Module:** `scanner.py`

For each `ModDescriptor`:

* Look at `<mod.path>/common/culture/traditions/`.
* Collect all `.txt` files (recursive or flat, as CK3 uses).

Yield a stream of `TraditionFile` objects:

```python
class TraditionFile:
    mod: ModDescriptor
    rel_path: str       # "common/culture/traditions/00_traditions.txt"
    abs_path: str
    index_in_mod: int   # to keep deterministic ordering
```

---

### 3.3 Lexer (tokenizer)

**Module:** `pdx_lexer.py`

We keep it **minimal but robust**:

Tokens:

* `IDENT` – `a_z`, `0-9`, `_`, `.`, `:` etc.
* `EQUALS` – `=`
* `LBRACE` – `{`
* `RBRACE` – `}`
* `STRING` – `"..."` with escaped quotes.
* `NUMBER` – `123`, `-0.25`, etc.
* `NEWLINE`, `WHITESPACE` (often ignored).
* `COMMENT` – `# ...` to end of line (ignored in AST but preserved in raw text if we want).

The lexer walks the file line by line, yields tokens, tracking file position (line/column) if we want for nicer error messages.

---

### 3.4 Parser (tradition-level AST)

**Module:** `pdx_parser.py`

We do **not** need to parse every construct semantically in v0. We just need:

* To recognize **top-level assignments** like:

  ```txt
  tradition_mountain_homes = {
      ...
  }
  ```

* To know where the `{ ... }` block starts and ends (brace matching).

Minimal strategy:

1. Scan tokens at top level.

2. Whenever you see pattern:
   * `IDENT` → `EQUALS` → `LBRACE`

   treat that as:

   ```python
   def parse_top_level_block(tokens, i):
       name = tokens[i].value           # IDENT
       assert tokens[i+1].type == EQUALS
       assert tokens[i+2].type == LBRACE
       start_index = i
       # Now walk forward, counting braces
       depth = 0
       while j < len(tokens):
           if tokens[j].type == LBRACE: depth += 1
           if tokens[j].type == RBRACE:
               depth -= 1
               if depth == 0:
                   end_index = j
                   break
           j += 1
       # block_tokens = tokens[start_index : end_index+1]
   ```

3. Store a **BlockNode**:

```python
class BlockNode:
    name: str              # "tradition_mountain_homes"
    tokens: List[Token]    # entire block, including name = { ... }
    mod: ModDescriptor
    file: TraditionFile
```

In v0, we don't need to inspect the inside of `tokens`; we treat it as opaque.

4. We *could* filter for names starting with `"tradition_"`, or we can keep a simple whitelist: "everything in this folder is assumed to be a tradition definition at top level" and later filter by prefix.

---

### 3.5 Tradition registry + merge logic

**Module:** `tradition_registry.py`

We build:

```python
class TraditionDefinition:
    key: str               # "tradition_mountain_homes"
    block: BlockNode
    mod: ModDescriptor
    file: TraditionFile
    sequence_number: int   # global order (for tie-breaking)

class TraditionRegistry:
    defs_by_key: Dict[str, List[TraditionDefinition]]
```

**Population step:**

As we iterate mods in playset order:

* For each `TraditionFile` (in a deterministic order), parse it → list of `BlockNode`.
* For each `BlockNode` with name `tradition_*`:
  * Create `TraditionDefinition`.
  * Append to `registry.defs_by_key[key]`.

**Resolution rule (v0, CK3-faithful):**

For each `key`:

* `definitions = defs_by_key[key]`
* `winner = definitions[-1]`  (last one encountered in playset order)
* `overridden = definitions[:-1]`

No fancy merging; the **last full block wins**, just like in game.

(We can add optional alt-modes later: e.g. "virtual merge" for analysis, but that's not v0.)

---

### 3.6 Exporter

**Module:** `exporter.py`

We want:

1. A final textual file:

   * Choose a path like `out/common/culture/traditions/00_resolved_traditions.txt`.
   * For each tradition key, sorted alphabetically for sanity:

   ```txt
   # ================================
   # FINAL tradition_mountain_homes
   # WINNER: CE (common/culture/traditions/02_ce_traditions.txt)
   # OVERRIDDEN: vanilla (common/culture/traditions/00_traditions.txt); RICE (common/culture/traditions/01_rice_traditions.txt)
   # ================================

   tradition_mountain_homes = {
       ...exact token stream re-serialized...
   }

   ```

   Re-serialization can be as simple as joining original tokens with their original spacing, which we can preserve if we track raw text slices; or we accept a slightly normalized formatting.

2. A machine-readable conflict report:

   ```python
   def export_conflicts(registry, out_path):
       data = {}
       for key, defs in registry.defs_by_key.items():
           if len(defs) <= 1:
               continue
           winner = defs[-1]
           overridden = defs[:-1]
           data[key] = {
               "winner": {
                   "mod_id": winner.mod.id,
                   "file": winner.file.rel_path
               },
               "overridden": [
                   {"mod_id": d.mod.id, "file": d.file.rel_path}
                   for d in overridden
               ]
           }
       write_json(data, out_path)
   ```

Optional: create a `tradition_index.json` with all traditions (even non-conflicting) + source mod, for quick queries.

---

## 4. CLI & workflow

A simple command line tool:

```bash
ck3-traditions-resolve \
    --ck3-root "/games/Crusader Kings III" \
    --playset "/Documents/Paradox Interactive/Crusader Kings III/playsets/my_playset.json" \
    --out "./resolved_traditions"
```

Internally:

1. Build `ModDescriptor` list:
   * First synthetic "vanilla" with `path = ck3-root/game`.
   * Then each mod from playset JSON.

2. For each mod, scan files, parse, populate registry.

3. Export merged results + conflict report.

---

## 5. Where "agent AI" would fit in later

This design is friendly to agent-style assistance:

* Agent helps draft:
  * `pdx_lexer.py` and `pdx_parser.py` given a small set of test `.txt` files.
  * Unit tests for brace-balanced block extraction.

* As you hit weird edge-cases in real CK3/RICE/CE files, you:
  * feed examples to the agent,
  * refine lexer/parser rules,
  * iterate.

But the **core architecture stays as above**:
clear modules, explicit registry, load-order semantics, no regex duct-tape.
