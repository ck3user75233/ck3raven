# Unified Learner Architecture: Emergent Template Extraction

**Status:** Design Brief  
**Date:** 2026-01-26  
**Purpose:** Architecture for a unified learner that extracts mod difference patterns without hardcoded field definitions

---

## 1. Problem Statement

### Current Approach (Hardcoded)

The existing learners (`kgd_maa_patterns_v3.py`, `kgd_building_values_learner.py`) require:
- Manually specifying which symbol types to compare (MAA, buildings, scripted_values)
- Hardcoding which fields to extract (`province_modifier.monthly_income`, `terrain_bonus.mountains`)
- Writing custom extraction logic for each data shape

**Pain points:**
- Each new symbol type requires a new learner
- Nested structures require nested extraction code
- Missing fields cause errors instead of graceful omission
- Can't discover what changed—must know what to look for

### Proposed Approach (Emergent Templates)

A unified learner that:
1. **Diffs AST structures** without knowing their schema
2. **Discovers changed fields** by walking both trees
3. **Produces emergent templates** describing the transformation
4. **Stores structured diff data** in queryable tables

---

## 2. Core Architecture

### 2.1 AST Diff Engine

```
Vanilla AST ─┐
             ├── AST Differ ──> Structural Diff ──> Change Records
   Mod AST ──┘
```

The differ walks both ASTs simultaneously:
- **Same key, same value** → Skip (unchanged)
- **Same key, different value** → Record delta
- **Key in vanilla only** → Record deletion
- **Key in mod only** → Record addition
- **Recurse into nested blocks**

### 2.2 Change Record Schema

```sql
CREATE TABLE symbol_diffs (
    diff_id INTEGER PRIMARY KEY,
    baseline_cv_id INTEGER,      -- vanilla content_version
    compare_cv_id INTEGER,       -- mod content_version
    symbol_type TEXT,            -- 'building', 'maa_type', 'scripted_effect'
    symbol_name TEXT,            -- 'heavy_infantry', 'castle_01'
    json_path TEXT,              -- 'province_modifier.monthly_income'
    baseline_value TEXT,         -- '0.5'
    compare_value TEXT,          -- '0.25'
    value_type TEXT,             -- 'number', 'string', 'reference', 'block'
    change_type TEXT             -- 'modified', 'added', 'removed'
);

CREATE TABLE symbol_additions (
    addition_id INTEGER PRIMARY KEY,
    compare_cv_id INTEGER,
    symbol_type TEXT,
    symbol_name TEXT,
    -- New symbol, no baseline
);

CREATE TABLE symbol_deletions (
    deletion_id INTEGER PRIMARY KEY,
    baseline_cv_id INTEGER,
    compare_cv_id INTEGER,
    symbol_type TEXT,
    symbol_name TEXT,
    -- Symbol removed by mod
);
```

### 2.3 Emergent Template Derivation

After collecting diffs, aggregate patterns:

```sql
-- Find numeric multipliers by json_path
SELECT 
    json_path,
    COUNT(*) as occurrences,
    AVG(CAST(compare_value AS REAL) / CAST(baseline_value AS REAL)) as avg_multiplier,
    MIN(CAST(compare_value AS REAL) / CAST(baseline_value AS REAL)) as min_mult,
    MAX(CAST(compare_value AS REAL) / CAST(baseline_value AS REAL)) as max_mult
FROM symbol_diffs
WHERE value_type = 'number' AND baseline_value != '0'
GROUP BY json_path
HAVING COUNT(*) > 3  -- Only patterns with multiple occurrences
ORDER BY occurrences DESC;
```

**Example output:**
| json_path | occurrences | avg_multiplier |
|-----------|-------------|----------------|
| `province_modifier.monthly_income` | 127 | 0.52 |
| `province_modifier.levy_size` | 98 | 0.44 |
| `terrain_bonus.plains.damage` | 45 | 1.15 |

This IS the emergent template—no hardcoding needed.

---

## 3. Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      INGESTION PHASE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [Vanilla ASTs]         [Mod ASTs]                             │
│       │                      │                                  │
│       └──────┬───────────────┘                                  │
│              ▼                                                  │
│      ┌───────────────┐                                          │
│      │ Symbol Matcher │  Match by symbol name across versions   │
│      └───────┬───────┘                                          │
│              ▼                                                  │
│      ┌───────────────┐                                          │
│      │   AST Differ   │  Recursive structural diff              │
│      └───────┬───────┘                                          │
│              ▼                                                  │
│      ┌───────────────┐                                          │
│      │ symbol_diffs   │  Flat table of all changes              │
│      └───────────────┘                                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      ANALYSIS PHASE                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│      ┌───────────────┐                                          │
│      │ symbol_diffs   │                                         │
│      └───────┬───────┘                                          │
│              ▼                                                  │
│      ┌───────────────────────────┐                              │
│      │ Pattern Aggregator (SQL)   │                             │
│      └───────┬───────────────────┘                              │
│              ▼                                                  │
│   ┌──────────────────────────────────┐                          │
│   │       Emergent Templates          │                         │
│   │  - Multipliers by json_path       │                         │
│   │  - Constant replacements          │                         │
│   │  - Added/removed block patterns   │                         │
│   └──────────────────────────────────┘                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      APPLICATION PHASE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   [Emergent Templates]   [New Mod AST]                          │
│           │                    │                                │
│           └────────┬───────────┘                                │
│                    ▼                                            │
│           ┌────────────────┐                                    │
│           │ Patch Generator │  Apply multipliers to new mod     │
│           └────────┬───────┘                                    │
│                    ▼                                            │
│           ┌────────────────┐                                    │
│           │ Patched AST     │                                   │
│           └────────┬───────┘                                    │
│                    ▼                                            │
│           ┌────────────────┐                                    │
│           │ Code Generator  │  Emit zzz_*.txt override          │
│           └────────────────┘                                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. What It Would Deliver

### 4.1 Queryable Diff Database

Instead of JSON files with nested structures, get flat queryable tables:

```sql
-- What did KGD change about buildings?
SELECT json_path, COUNT(*), AVG(multiplier)
FROM symbol_diffs 
WHERE compare_cv_id = 12345 AND symbol_type = 'building'
GROUP BY json_path;

-- Which symbols were completely removed?
SELECT symbol_name FROM symbol_deletions 
WHERE compare_cv_id = 12345;

-- What new symbols did mod X add?
SELECT symbol_name FROM symbol_additions
WHERE compare_cv_id = 67890 AND symbol_type = 'trait';
```

### 4.2 Automatic Pattern Discovery

No need to ask "what fields should I extract?" The differ captures EVERYTHING that changed, and SQL aggregation surfaces the patterns.

### 4.3 Cross-Mod Comparison

Compare any two content versions:
- Vanilla vs KGD
- KGD vs CFP
- Vanilla vs ModX
- ModX vs ModY (for conflict analysis)

### 4.4 Batch Analysis

```sql
-- For each mod, how many symbols does it modify?
SELECT cv.display_name, COUNT(DISTINCT sd.symbol_name)
FROM symbol_diffs sd
JOIN content_versions cv ON sd.compare_cv_id = cv.content_version_id
WHERE sd.baseline_cv_id = 1  -- vanilla
GROUP BY cv.content_version_id;
```

### 4.5 Emergent Template Export

```json
{
  "learned_from": ["KGD: The Great Rebalance"],
  "baseline": "vanilla 1.18",
  "patterns": {
    "building.province_modifier.monthly_income": {
      "type": "multiplier",
      "value": 0.52,
      "confidence": 0.95,
      "samples": 127
    },
    "maa_type.terrain_bonus.plains.damage": {
      "type": "multiplier", 
      "value": 1.15,
      "confidence": 0.88,
      "samples": 45
    },
    "scripted_value.low_development_growth_base": {
      "type": "constant",
      "value": 0,
      "confidence": 1.0,
      "samples": 1
    }
  }
}
```

---

## 5. Comparison: Hardcoded vs Emergent

| Aspect | Hardcoded Approach | Emergent Approach |
|--------|-------------------|-------------------|
| **Setup effort** | High—write extractor per type | Low—one-time differ implementation |
| **New symbol types** | Requires new code | Automatic |
| **Missing fields** | Errors or silent failures | Graceful—just not in diff |
| **Unexpected changes** | Not discovered | Automatically captured |
| **Query flexibility** | Limited to what was extracted | Full SQL on all changes |
| **Template maintenance** | Manual updates | Self-updating from data |
| **Understanding why** | Clear—you wrote the extractor | Opaque—need to interpret patterns |
| **Precision** | High—extract exactly what's needed | Lower—noise in irrelevant diffs |
| **Storage** | Minimal (targeted) | Large (comprehensive) |
| **Debugging** | Easy—clear code path | Harder—diffing complex trees |

---

## 6. Pros and Cons

### Pros

1. **Write once, learn anything** - Same code handles MAA, buildings, traits, events, decisions
2. **Discovers the unknown** - Finds patterns you didn't think to look for
3. **Queryable** - SQL aggregation is more powerful than nested JSON walking
4. **Cross-mod** - Compare any two mods with zero additional code
5. **Future-proof** - New CK3 content types work automatically
6. **Audit trail** - See exactly what changed at every json_path

### Cons

1. **Noisy output** - Captures EVERYTHING, including cosmetic/irrelevant changes
2. **No semantic understanding** - Doesn't know that `monthly_income` means "tax", just that it's a number
3. **Harder to debug** - Recursive tree walking is tricky to debug when it goes wrong
4. **Storage overhead** - Storing all diffs takes more space than targeted extraction
5. **Pattern interpretation** - Still need humans to understand what patterns mean
6. **Block changes are messy** - When a whole block is restructured, diff gets noisy

---

## 7. Limitations and Hybrid Approaches

### Still Need Symbol Selection

The differ can compare ANY symbols, but you still need to PICK which symbols to compare. Options:

1. **Compare everything** - Diff all symbols of all types (expensive, noisy)
2. **Compare by type** - "Diff all buildings" (more focused)
3. **Compare specific symbols** - "Diff heavy_infantry" (targeted)

**Recommendation:** Support all three modes. Default to "by type" for practical use.

### Still Need Semantic Hints

The differ produces patterns like:
```
province_modifier.monthly_income → 0.52x
```

But doesn't know this means "building income reduced by half." Semantic layer options:

1. **None** - Users interpret patterns themselves
2. **Annotation table** - Map json_paths to human descriptions
3. **AI interpretation** - LLM summarizes patterns into prose

**Recommendation:** Start with none, add annotation table later.

### Complex Block Changes

When a mod restructures a block (adds conditions, moves things around), pure AST diff gets noisy:

```
# Vanilla
ai_will_do = { base = 100 }

# Mod
ai_will_do = {
    base = 100
    modifier = { factor = 0.5 trigger = { is_ai = yes } }
}
```

This produces: "added modifier block" not "AI behavior halved under condition."

**Mitigation:** Post-processing heuristics to detect common restructuring patterns.

---

## 8. Implementation Phases

### Phase 1: AST Differ Core

- Recursive tree walker
- Value comparison (number, string, reference)
- json_path generation
- Change record emission

**Deliverable:** Can diff any two AST blobs, produces flat list of changes

### Phase 2: Batch Differ

- Query symbols by type/name
- Match vanilla↔mod symbols
- Bulk diff processing
- Write to `symbol_diffs` table

**Deliverable:** "Diff all buildings between vanilla and KGD"

### Phase 3: Pattern Aggregator

- SQL queries for multipliers, constants, additions, deletions
- Statistical confidence measures
- Export to JSON template format

**Deliverable:** Emergent template extraction

### Phase 4: Patch Generator

- Read emergent templates
- Apply to new mod ASTs
- Generate patched AST
- Emit PDX script output

**Deliverable:** "Apply KGD patterns to VIET buildings"

---

## 9. Proof of Concept Scope

A minimal PoC would demonstrate:

1. **Input:** Two AST blobs (one vanilla building, one KGD building)
2. **Process:** Recursive diff, emit change records
3. **Output:** List of (json_path, old_value, new_value, change_type)

**Estimated complexity:** ~150 lines Python

**Success criteria:**
- Correctly identifies numeric changes
- Correctly identifies added/removed keys
- Handles nested blocks at least 3 levels deep
- Produces json_paths matching the structure

---

## 10. Questions to Resolve

1. **Granularity of json_path** - Should `province_modifier.monthly_income` be leaf-level, or also capture parent paths?

2. **Array handling** - CK3 has lists like `terrain_bonus = { ... }`. How to diff unordered lists with named entries?

3. **Reference resolution** - When value is `normal_tax_base` (a reference), should we resolve it or keep the symbol?

4. **AST format dependency** - This assumes ck3raven's AST format. Changes to parser output could break differ.

5. **Performance** - Diffing 1000+ buildings each with 50+ fields. Acceptable runtime?

---

## 11. Recommendation

**Proceed with PoC**, but with these caveats:

1. **Symbol selection still needed** - Don't expect magic; user picks "diff buildings"
2. **Semantic interpretation manual** - Patterns need human/LLM interpretation
3. **Hybrid may be best** - Emergent discovery + hardcoded semantic layer
4. **Start small** - PoC on buildings, prove value before expanding

The key insight: **The differ doesn't replace domain knowledge—it replaces the tedium of writing extractors.** You still need to understand what the patterns mean, but you don't need to write code to find them.

---

## 12. Appendix: Example Diff Output

**Input:** Vanilla `barracks_01` vs KGD `barracks_01`

**Output:**
```json
{
  "symbol": "barracks_01",
  "symbol_type": "building",
  "changes": [
    {
      "json_path": "province_modifier.monthly_income",
      "baseline": "0.5",
      "compare": "0.25",
      "value_type": "number",
      "change_type": "modified"
    },
    {
      "json_path": "province_modifier.levy_size",
      "baseline": "0.1",
      "compare": "0.05",
      "value_type": "number",
      "change_type": "modified"
    },
    {
      "json_path": "cost.gold",
      "baseline": "100",
      "compare": "140",
      "value_type": "number",
      "change_type": "modified"
    },
    {
      "json_path": "desc_flavor_trigger",
      "baseline": null,
      "compare": "{ always = yes }",
      "value_type": "block",
      "change_type": "added"
    }
  ]
}
```

This single diff record tells us:
- Income halved (0.5 → 0.25)
- Levy halved (0.1 → 0.05)
- Cost increased 40% (100 → 140)
- A new block added (desc_flavor_trigger)

Multiply by 500+ buildings → aggregate patterns emerge automatically.
