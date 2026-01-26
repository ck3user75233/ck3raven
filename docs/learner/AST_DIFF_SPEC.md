# AST Differ Specification

**Status:** Canonical  
**Version:** 1.0  
**Date:** 2026-01-26  
**Location:** `tools/learners/ast_diff.py`

---

## 1. Purpose

The AST Differ is a schema-agnostic module that compares two ck3raven AST structures and produces flat change records with deterministic json_path addressing.

It forms the foundation of the Unified Learner architecture, replacing symbol-type-specific extractors with a generic differ that works on any CK3 content type.

### Design Principles

1. **No hardcoded field lists** - The differ does not know about "damage", "toughness", "terrain_bonus", etc.
2. **No symbol-specific logic** - Works identically for MAA, buildings, traits, events, decisions
3. **Deterministic output** - Same inputs always produce same outputs
4. **Arbitrary depth** - Handles deeply nested structures without depth limits
5. **Flat output** - Produces records suitable for SQL storage and aggregation

---

## 2. Input Format

The differ accepts AST dictionaries as produced by ck3raven's parser (`ck3_parse_content`).

### AST Node Types

| Node Type | Structure | Example |
|-----------|-----------|---------|
| `root` | `{_type: "root", filename, children: [...]}` | File-level container |
| `block` | `{_type: "block", name, operator, children: [...]}` | Named block `foo = { ... }` |
| `assignment` | `{_type: "assignment", key, operator, value: {...}}` | Key-value `foo = bar` |
| `value` | `{_type: "value", value, value_type}` | Leaf value |

### Value Types

| value_type | Meaning | Example |
|------------|---------|---------|
| `number` | Numeric literal | `35`, `-5`, `0.5` |
| `string` | Quoted string | `"hello world"` |
| `identifier` | Unquoted token | `heavy_infantry`, `yes` |

---

## 3. Output Format

### ChangeRecord

Each detected change produces a `ChangeRecord` with:

| Field | Type | Description |
|-------|------|-------------|
| `json_path` | str | Dot-separated path to the changed element |
| `old_value` | str \| None | Value in baseline (None if ADDED) |
| `new_value` | str \| None | Value in compare (None if REMOVED) |
| `old_type` | ValueType | Type classification of old value |
| `new_type` | ValueType | Type classification of new value |
| `change_type` | ChangeType | MODIFIED, ADDED, or REMOVED |

### ValueType Enum

```python
class ValueType(Enum):
    NUMBER = "number"
    STRING = "string"
    IDENTIFIER = "identifier"
    BLOCK = "block"
    MISSING = "missing"
    UNKNOWN = "unknown"
```

### ChangeType Enum

```python
class ChangeType(Enum):
    MODIFIED = "modified"  # Value changed
    ADDED = "added"        # Key/block added in compare
    REMOVED = "removed"    # Key/block removed from baseline
```

### DiffResult

The top-level result object:

```python
@dataclass
class DiffResult:
    symbol_name: str           # e.g., "heavy_infantry"
    symbol_type: Optional[str] # e.g., "maa_type" (if known)
    baseline_source: str       # e.g., "vanilla"
    compare_source: str        # e.g., "kgd"
    changes: list[ChangeRecord]
```

---

## 4. Path Semantics

### 4.1 Basic Paths

Paths are constructed by joining keys with `.` (dot):

```
damage                           # Top-level key
terrain_bonus.plains             # Nested block
terrain_bonus.plains.damage      # Nested key
```

### 4.2 Repeated Keys

PDX files allow repeated keys. When a key appears multiple times, indices are appended:

```
modifier[0].factor               # First modifier block
modifier[1].factor               # Second modifier block
```

Indices are **0-based** and appear only when necessary (when `count > 1`).

### 4.3 Ordering

Keys are processed in **alphabetically sorted order** for deterministic output.

Within repeated key groups, nodes are matched **positionally** (first-to-first, second-to-second).

### 4.4 Path Examples

| PDX Structure | json_path |
|---------------|-----------|
| `damage = 35` | `damage` |
| `terrain_bonus = { plains = { damage = 10 } }` | `terrain_bonus.plains.damage` |
| `counters = { light_cavalry = 1.5 }` | `counters.light_cavalry` |
| `modifier = { } modifier = { }` | `modifier[0]`, `modifier[1]` |

---

## 5. Diff Algorithm

### 5.1 Recursive Walk

```
diff_nodes(baseline, compare, path):
    if baseline is None and compare is None:
        return
    if baseline is None:
        emit_added(compare, path)
        return
    if compare is None:
        emit_removed(baseline, path)
        return
    
    if types differ:
        emit_removed(baseline, path)
        emit_added(compare, path)
        return
    
    if assignment:
        diff values/blocks
    if block:
        diff children recursively
```

### 5.2 Block Diffing

1. Build index of children by key: `{key: [node, node, ...]}`
2. Collect all keys from both baseline and compare
3. For each key (sorted):
   - Match nodes positionally
   - Recurse into each pair

### 5.3 Value Diffing

Compare string representation of values:
- If different → MODIFIED
- If baseline missing → ADDED
- If compare missing → REMOVED

---

## 6. Invariants

The differ maintains these invariants:

1. **Determinism**: `diff(A, B)` always produces identical output for identical inputs
2. **Symmetry**: `diff(A, B)` produces opposite changes to `diff(B, A)`
3. **Completeness**: Every structural difference produces at least one ChangeRecord
4. **No Interpretation**: The differ never interprets values semantically (e.g., doesn't compute multipliers)
5. **Path Uniqueness**: No two ChangeRecords in the same DiffResult have identical json_paths

---

## 7. Examples

### 7.1 Simple Modification

**Baseline:**
```pdx
heavy_infantry = {
    damage = 35
}
```

**Compare:**
```pdx
heavy_infantry = {
    damage = 30
}
```

**Output:**
```json
{
  "json_path": "damage",
  "old_value": "35",
  "new_value": "30",
  "old_type": "number",
  "new_type": "number",
  "change_type": "modified"
}
```

### 7.2 Nested Modification

**Baseline:**
```pdx
terrain_bonus = {
    plains = { damage = 10 }
}
```

**Compare:**
```pdx
terrain_bonus = {
    plains = { damage = 15 }
}
```

**Output:**
```json
{
  "json_path": "terrain_bonus.plains.damage",
  "old_value": "10",
  "new_value": "15",
  "old_type": "number",
  "new_type": "number",
  "change_type": "modified"
}
```

### 7.3 Addition

**Compare adds:**
```pdx
pursuit = 5
```

**Output:**
```json
{
  "json_path": "pursuit",
  "old_value": null,
  "new_value": "5",
  "old_type": "missing",
  "new_type": "number",
  "change_type": "added"
}
```

### 7.4 Removal

**Baseline has, compare lacks:**
```pdx
hills = { damage = -5 }
```

**Output:**
```json
{
  "json_path": "terrain_bonus.hills.damage",
  "old_value": "-5",
  "new_value": null,
  "old_type": "number",
  "new_type": "missing",
  "change_type": "removed"
}
```

---

## 8. Usage

### Direct AST Comparison

```python
from tools.learners.ast_diff import diff_symbol_asts, extract_symbol_block

# Get ASTs (from ck3_parse_content or database)
vanilla_ast = parse_content(vanilla_content)
mod_ast = parse_content(mod_content)

# Extract symbol blocks
vanilla_block = extract_symbol_block(vanilla_ast, "heavy_infantry")
mod_block = extract_symbol_block(mod_ast, "heavy_infantry")

# Diff
result = diff_symbol_asts(
    baseline_ast=vanilla_block,
    compare_ast=mod_block,
    symbol_name="heavy_infantry",
    baseline_source="vanilla",
    compare_source="kgd",
    symbol_type="maa_type",
)

# Use results
for change in result.changes:
    print(f"{change.change_type}: {change.json_path}")
```

### JSON Export

```python
print(result.to_json())
```

---

## 9. Limitations

### Not Handled

1. **Semantic interpretation** - The differ doesn't know that `0.5 → 0.25` is a "50% reduction"
2. **Reference resolution** - References like `@normal_tax_base` are compared as strings, not resolved
3. **Order-dependent lists** - Lists are matched positionally, not by content
4. **Comments** - Comments in PDX files are not preserved in AST

### Future Considerations

1. **Operator tracking** - Currently ignores `=`, `<`, `>` operator differences
2. **Line number tracking** - Could include source positions for debugging
3. **Block-level hashing** - For quick "unchanged" detection

---

## 10. Integration Points

### Database Integration (Future)

```sql
-- Potential storage schema (Phase 2)
CREATE TABLE symbol_diffs (
    diff_id INTEGER PRIMARY KEY,
    baseline_cv_id INTEGER,
    compare_cv_id INTEGER,
    symbol_type TEXT,
    symbol_name TEXT,
    json_path TEXT,
    old_value TEXT,
    new_value TEXT,
    old_type TEXT,
    new_type TEXT,
    change_type TEXT
);
```

### MCP Tool Integration (Future)

```python
# Potential MCP tool signature
ck3_diff_symbols(
    baseline_cv_id=1,      # vanilla
    compare_cv_id=12345,   # mod
    symbol_name="heavy_infantry",
) -> DiffResult
```

---

## 11. Testing

Run the built-in demo:

```bash
python -m tools.learners.ast_diff
```

This produces sample output comparing a hypothetical vanilla vs KGD heavy_infantry.
