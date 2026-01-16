# Content-Keyed Symbols/Refs Schema (January 2026)

> **Status:** MIGRATED — Flag-day completed January 16, 2026  
> **Schema Version:** v5 (content-keyed)  
> **Previous doc:** SYMBOL_CONTENT_MIGRATION_PLAN.md (historical reference)

---

## Summary

As of January 16, 2026, the `symbols` and `refs` tables use **content-identity** binding.

- **Before:** `symbols` and `refs` had `file_id` and `content_version_id` columns
- **After:** `symbols` and `refs` have only `ast_id` — no file/mod binding

This implements Laws 4 and 4b from QBuilder Canonical Architecture.

---

## Current Schema

### symbols table

```sql
CREATE TABLE symbols (
    symbol_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ast_id INTEGER NOT NULL,                  -- FK to asts (content-based)
    line_number INTEGER,
    column_number INTEGER,
    symbol_type TEXT NOT NULL,                -- 'trait', 'event', 'decision', etc.
    name TEXT NOT NULL,
    scope TEXT,
    metadata_json TEXT,
    
    FOREIGN KEY (ast_id) REFERENCES asts(ast_id) ON DELETE CASCADE
);
```

### refs table

```sql
CREATE TABLE refs (
    ref_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ast_id INTEGER NOT NULL,
    line_number INTEGER,
    column_number INTEGER,
    ref_type TEXT NOT NULL,
    name TEXT NOT NULL,
    context TEXT,
    resolution_status TEXT NOT NULL DEFAULT 'unknown',
    resolved_symbol_id INTEGER,
    candidates_json TEXT,
    
    FOREIGN KEY (ast_id) REFERENCES asts(ast_id) ON DELETE CASCADE,
    FOREIGN KEY (resolved_symbol_id) REFERENCES symbols(symbol_id)
);
```

---

## Key Invariants

### 1. Content Identity

Symbols and refs are **derived from ASTs**, not files. The identity chain:

```
Content (bytes) → content_hash → AST → symbols/refs
```

### 2. No File Binding

These columns are **banned** from symbols/refs tables:
- `file_id`
- `content_version_id`
- `relpath`
- Any mod/file identifier

### 3. CASCADE Delete

When an AST is deleted, its symbols and refs are automatically deleted via `ON DELETE CASCADE`.

### 4. Deduplication

If two files have identical content:
- One AST exists (keyed by `content_hash + parser_version_id`)
- One set of symbols/refs exists
- Both files share them via the Golden Join

---

## The Golden Join

To associate symbols/refs back to files for queries:

```sql
SELECT 
    s.name,
    s.symbol_type,
    s.line_number,
    f.relpath,
    cv.content_version_id,
    mp.name AS mod_name
FROM symbols s
JOIN asts a ON a.ast_id = s.ast_id
JOIN files f ON f.content_hash = a.content_hash
JOIN content_versions cv ON cv.content_version_id = f.content_version_id
LEFT JOIN mod_packages mp ON mp.mod_package_id = cv.mod_package_id
WHERE s.name = 'brave';
```

This is the **only allowed resolution path**:
```
symbols/refs → asts (via ast_id) → files (via content_hash) → content_versions
```

---

## Playset Filtering

To filter symbols to a specific playset (e.g., active playset in ck3lens mode):

```sql
WHERE f.content_version_id IN (:playset_cvids)
```

This happens at the `files` table level via the Golden Join.

---

## Worker Behavior

### Symbol Extraction (`qbuilder/worker.py`)

1. Fetch `ast_id` and `ast_blob` from queue item
2. Check if symbols already exist: `SELECT 1 FROM symbols WHERE ast_id = ?`
3. If exists, skip (content already extracted)
4. If not, extract symbols and INSERT with `ast_id` only

### Reference Extraction

Same pattern as symbol extraction.

### Delete Cascade

When files are deleted:
1. Check if other files share the same `content_hash`
2. If yes: do nothing (AST and derived data still valid for other files)
3. If no: delete the AST (symbols/refs CASCADE automatically)

---

## Related Documentation

- [QBuilder Canonical Architecture](QBuilder%20Canonical%20Architecture%20%26%20Non-Negotiable%20Data%20Identity%20Laws.md) — Laws 4, 4b, 5
- [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) — Section 13: AST Identity Invariant
- [DATABASE_BUILDER.md](DATABASE_BUILDER.md) — Build phases overview
