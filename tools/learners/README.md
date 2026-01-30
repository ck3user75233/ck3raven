# CK3 Raven Learner Infrastructure

> **Status:** v1 Complete (AST infrastructure) | v2 Proposed (DNA Learner)  
> **Last Updated:** January 31, 2026  
> **Location:** `tools/learners/`

---

## Purpose

The learner infrastructure exists to **build "DNA"** - a framework for understanding how expert modders (like KGD) make balance decisions, so we can:

1. **Detect patterns** in how mods modify vanilla content
2. **Extract reusable rules** that can be applied elsewhere
3. **Generate compatibility patches** for mods that don't adopt the same balance decisions

This is NOT about "learning from modders to help other modders" in a general sense. It's specifically about building a compatch generation framework.

---

## Current Architecture (v1)

### Core Modules

| File | Lines | Purpose |
|------|-------|---------|
| `ast_diff.py` | ~657 | Schema-agnostic AST structural differ |
| `batch_differ.py` | ~291 | Batch processor for diffing across many symbols |
| `db_adapter.py` | ~352 | Read-only database access using golden_join pattern |

### Data Flow

```
Baseline (Vanilla)     Compare (KGD Mod)
       │                      │
       ▼                      ▼
   ck3raven DB ─────────► LearnerDb.golden_join()
                               │
                               ▼
                         SymbolRecord pairs
                               │
                               ▼
                          AstDiffer
                               │
                               ▼
                         DiffResult
                         (ChangeRecords)
                               │
                               ▼
                    JSONL output files
```

### Key Classes

#### `ChangeRecord` (ast_diff.py)
```python
@dataclass
class ChangeRecord:
    change_type: ChangeType  # ADDED, REMOVED, MODIFIED, UNCHANGED
    json_path: str           # "$.levy.max" - addressing into AST
    old_value: Any
    new_value: Any
    value_type: ValueType    # SCALAR, BLOCK, OPERATOR
    context: dict            # Additional metadata
```

#### `DiffResult` (ast_diff.py)
```python
@dataclass
class DiffResult:
    symbol_name: str
    symbol_type: str
    baseline_source: str
    compare_source: str
    changes: list[ChangeRecord]
    is_identical: bool
    metadata: dict
```

#### `SymbolRecord` (db_adapter.py)
```python
@dataclass
class SymbolRecord:
    symbol_id: int
    name: str
    symbol_type: str
    file_id: int
    relative_path: str
    content_version_id: int
    mod_name: str
    line_number: int
    ast_blob: bytes | None
```

### The Golden Join Pattern

The `db_adapter.py` uses a specific SQL pattern for retrieving symbols with their ASTs:

```sql
SELECT 
    s.symbol_id, s.name, s.symbol_type,
    f.file_id, f.relative_path,
    cv.content_version_id, cv.name as mod_name,
    a.ast_blob
FROM symbols s
JOIN files f ON s.file_id = f.file_id
JOIN content_versions cv ON f.content_version_id = cv.content_version_id
LEFT JOIN asts a ON f.file_id = a.file_id
WHERE s.symbol_type = ? AND cv.content_version_id = ?
```

This "golden join" pattern is reused throughout ck3raven for efficient symbol retrieval.

---

## Proposed Architecture (v2 - DNA Learner)

### Concept

The DNA Learner will:
1. **Diff** baseline (vanilla) vs expert mod (KGD) for a symbol type
2. **Extract patterns** from the diffs (e.g., "KGD multiplies all levy values by 0.5")
3. **Store patterns** as reusable "DNA rules"
4. **Apply patterns** to other mods that need the same balance changes

### DNA Rule Schema (Proposed)

```python
@dataclass
class DNARule:
    rule_id: str
    symbol_type: str              # "building", "maa", "trait"
    pattern_type: str             # "multiply", "replace", "add_block"
    target_path: str              # JSON path like "$.levy.max"
    parameters: dict              # {"factor": 0.5} or {"value": 100}
    source_mod: str               # "KGD" - where we learned this
    confidence: float             # 0.0-1.0 based on consistency
    sample_count: int             # How many symbols showed this pattern
```

### Pattern Detection Strategy

1. **Group changes by json_path** across all symbols of a type
2. **Detect mathematical relationships** (multiply, add, replace)
3. **Calculate confidence** based on consistency
4. **Threshold** to filter noise from intentional patterns

Example:
```
Observed changes for "$.levy.max":
  - vanilla: 100, kgd: 50  (ratio: 0.5)
  - vanilla: 200, kgd: 100 (ratio: 0.5)
  - vanilla: 150, kgd: 75  (ratio: 0.5)

Detected pattern: MULTIPLY by 0.5 (confidence: 1.0, samples: 3)
```

### Application Flow

```
Source Mod (needs compatch)
         │
         ▼
    Parse symbols
         │
         ▼
   Match DNA rules
    (by symbol_type + json_path)
         │
         ▼
   Apply transformations
         │
         ▼
   Generate patch files
```

---

## Usage

### Running Batch Diff

```python
from tools.learners.batch_differ import batch_diff_symbols

# Diff all buildings between vanilla (cvid=1) and KGD (cvid=X)
results = batch_diff_symbols(
    symbol_type="building",
    baseline_cvid=1,
    compare_cvid=42,  # KGD's content_version_id
)

# Results written to tools/learners/output/
```

### Accessing Results

```python
import json
from pathlib import Path

output_dir = Path("tools/learners/output")
for jsonl_file in output_dir.glob("*.jsonl"):
    with open(jsonl_file) as f:
        for line in f:
            diff = json.loads(line)
            # Process diff...
```

---

## Design Principles

1. **AST-Native**: All diffing operates on parsed ASTs, not raw text or regex
2. **Schema-Agnostic**: The differ doesn't know CK3 semantics - it compares tree structures
3. **Read-Only DB**: Learners only read from ck3raven.db, never write
4. **Provenance Tracking**: Every change knows its source (baseline vs compare mod)
5. **JSON Path Addressing**: Changes are addressed using `$.path.to.value` notation

---

## Files Reference

```
tools/learners/
├── __init__.py           # Package init
├── README.md             # This file
├── ast_diff.py           # Core AST differ
├── batch_differ.py       # Batch processing orchestrator
├── db_adapter.py         # Database access layer
├── output/               # JSONL output from batch runs
└── reference_data/       # Reference datasets
```

---

## Next Steps

1. **Implement pattern detection** in a new `pattern_extractor.py`
2. **Design DNA rule storage** (SQLite table or JSON files)
3. **Build rule application engine** for generating patches
4. **Create CLI** for running learner workflows
