# Change Request: Golden Join Helpers for Learner AST Access

**Requester:** ck3lens agent (learner phase)  
**Date:** 2026-01-26  
**Target File:** `tools/ck3lens_mcp/ck3lens/db/golden_join.py`  
**Priority:** Low (learner can work without these, but they would reduce boilerplate)

---

## Context

The AST Differ (Phase 1 of Unified Learner) needs to retrieve symbol definitions with their AST blobs from two content versions for comparison.

Currently, `golden_join.py` provides:
- `GOLDEN_JOIN` - SQL fragment for the join chain
- `build_symbol_query()` - Builds queries with cvid filtering
- `get_symbols_by_name()` - Returns symbol metadata (no AST)
- `symbol_exists()` - Boolean existence check

---

## What the Learner Needs

To diff a symbol across content versions, the learner needs:

1. **Symbol metadata** - name, type, line_number, file_id, relpath
2. **Content version ID** - to know which version this is from
3. **AST blob** - the parsed AST for the file containing this symbol
4. **Node offsets** - `node_start_offset`, `node_end_offset` to extract the symbol's block from the full-file AST

---

## Requested Addition

Two helper functions:

### 1. `get_symbol_with_ast(conn, name, symbol_type, cvid) -> dict | None`

Returns a single symbol with its AST blob for a specific content version.

```python
def get_symbol_with_ast(
    conn: "sqlite3.Connection",
    name: str,
    symbol_type: str | None = None,
    cvid: int | None = None,
) -> dict | None:
    """
    Get a symbol with its parsed AST blob.
    
    Returns dict with: symbol_id, name, symbol_type, line_number,
    node_start_offset, node_end_offset, file_id, relpath,
    content_version_id, ast_blob (parsed JSON)
    """
    # Uses GOLDEN_JOIN + selects a.ast_blob
    # Parses JSON before returning
```

### 2. `get_symbols_for_diff(conn, name, symbol_type, baseline_cvid, compare_cvid) -> tuple`

Convenience wrapper that fetches both symbols for diffing.

```python
def get_symbols_for_diff(
    conn: "sqlite3.Connection",
    name: str,
    symbol_type: str,
    baseline_cvid: int,
    compare_cvid: int,
) -> tuple[dict | None, dict | None]:
    """
    Get matching symbols from two content versions for diffing.
    Returns (baseline_symbol, compare_symbol) tuple.
    """
    baseline = get_symbol_with_ast(conn, name, symbol_type, baseline_cvid)
    compare = get_symbol_with_ast(conn, name, symbol_type, compare_cvid)
    return baseline, compare
```

---

## Alternative: Learner Constructs SQL Directly

The learner can work without these helpers by using the existing `GOLDEN_JOIN` constant:

```python
from ck3lens.db.golden_join import GOLDEN_JOIN, cvid_filter_clause

sql = f"""
    SELECT s.*, a.ast_blob
    FROM symbols s
    {GOLDEN_JOIN}
    WHERE s.name = ? AND s.symbol_type = ?
    {cvid_filter_clause([cvid])[0]}
    LIMIT 1
"""
```

This is what the learner will do if the request is declined.

---

## Rationale for Adding to golden_join.py

1. **Centralizes AST access pattern** - Other tools may need symbol + AST lookup
2. **Prevents schema drift** - If AST storage changes, one place to update
3. **Reduces learner complexity** - Learner stays focused on diffing, not SQL
4. **Consistent with existing API** - Follows pattern of `get_symbols_by_name()`

---

## Decision Requested

- [ ] **Approve** - Add helpers to golden_join.py
- [ ] **Decline** - Learner uses GOLDEN_JOIN constant directly
- [ ] **Defer** - Revisit after learner proves value

---

## Notes

The learner will proceed with Phase 2 using the existing `GOLDEN_JOIN` constant. These helpers are quality-of-life improvements, not blockers.
