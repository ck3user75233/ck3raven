# Content-Identity Symbols & Refs Migration Plan

> **Status:** READY FOR EXECUTION  
> **Created:** January 15, 2026  
> **Authority:** Migration Protocol for Content-Identity Symbols & References.md  
> **Mode:** Flag day (no compatibility)

---

## 0. Precondition Verification

### AST Identity Check ✅

Current schema confirms:
```sql
CREATE TABLE asts (
    ...
    UNIQUE(content_hash, parser_version_id)  -- ✅ Correct identity
)
```

**Verification passed:** AST identity is `(content_hash, parser_version_id)`.

---

## 1. Complete Inventory

### 1.1 Code Paths That WRITE to symbols

| File | Line | Operation |
|------|------|-----------|
| `qbuilder/worker.py` | 224 | `DELETE FROM symbols WHERE file_id = ?` |
| `qbuilder/worker.py` | 229 | `INSERT INTO symbols (file_id, content_version_id, ...)` |
| `qbuilder/api.py` | 302, 307 | `DELETE FROM symbols WHERE file_id = ?` |
| `tools/ck3lens_mcp/server.py` | 1047-1111 | `DELETE FROM symbols` (ck3_db_delete) |

### 1.2 Code Paths That WRITE to refs

| File | Line | Operation |
|------|------|-----------|
| `qbuilder/worker.py` | 260 | `DELETE FROM refs WHERE file_id = ?` |
| `qbuilder/worker.py` | 265 | `INSERT INTO refs (file_id, content_version_id, ...)` |
| `qbuilder/api.py` | 303, 308 | `DELETE FROM refs WHERE file_id = ?` |
| `tools/ck3lens_mcp/server.py` | 1052-1113 | `DELETE FROM refs` (ck3_db_delete) |

### 1.3 Code Paths That READ from symbols

| File | Line | Operation |
|------|------|-----------|
| `tools/ck3lens_mcp/ck3lens/db_queries.py` | 362, 1018, 1066, 1165, 1210 | Symbol search/lookup queries |
| `tools/ck3lens_mcp/ck3lens/impl/search_ops.py` | 75, 156, 190 | FTS search + symbol fetch |
| `tools/ck3lens_mcp/ck3lens/impl/conflict_ops.py` | 140 | Conflict detection |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | 2374 | Symbol queries |
| `tools/ck3lens_mcp/server.py` | 619, 1563 | COUNT and status queries |
| `scripts/inspect_db.py` | 50 | Debug inspection |
| `tests/test_builder_daemon.py` | 260, 280 | Test assertions |

### 1.4 Code Paths That READ from refs

| File | Line | Operation |
|------|------|-----------|
| `tools/ck3lens_mcp/ck3lens/db_queries.py` | 486, 1099 | Reference lookup queries |
| `tools/ck3lens_mcp/server.py` | 620, 1052 | COUNT and status queries |
| `scripts/inspect_db.py` | 68 | Debug inspection |

### 1.5 Dependent Lookup Tables

These tables have FK to `symbols(symbol_id)` with ON DELETE CASCADE:

| Table | FK Column |
|-------|-----------|
| `trait_lookups` | `symbol_id` |
| `event_lookups` | `symbol_id` |
| `decision_lookups` | `symbol_id` |

### 1.6 FTS Virtual Tables (Will Be Dropped/Recreated)

| Table | Content Table |
|-------|---------------|
| `symbols_fts` | `symbols` |
| `refs_fts` | `refs` |

---

## 2. Final DDL

### 2.1 Drop Legacy Tables

```sql
-- Drop FTS tables first (depend on content tables)
DROP TABLE IF EXISTS symbols_fts;
DROP TABLE IF EXISTS refs_fts;

-- Drop lookup tables (have FK to symbols)
DROP TABLE IF EXISTS trait_lookups;
DROP TABLE IF EXISTS event_lookups;
DROP TABLE IF EXISTS decision_lookups;

-- Drop main tables
DROP TABLE IF EXISTS symbols;
DROP TABLE IF EXISTS refs;
```

### 2.2 Create Canonical Tables

```sql
-- Symbols: definitions derived from content
CREATE TABLE symbols (
    symbol_id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Identity: bound to AST (content-based)
    ast_id INTEGER NOT NULL,                  -- FK to asts (which has content_hash + parser_version_id)
    
    -- Location within AST
    ast_node_path TEXT,                       -- JSON path to AST node
    line_number INTEGER,
    column_number INTEGER,
    
    -- Symbol identity
    symbol_type TEXT NOT NULL,                -- 'trait', 'event', 'decision', etc.
    name TEXT NOT NULL,
    scope TEXT,                               -- Namespace (e.g., event namespace)
    
    -- Metadata
    metadata_json TEXT,
    
    FOREIGN KEY (ast_id) REFERENCES asts(ast_id) ON DELETE CASCADE,
    
    -- Uniqueness: same symbol at same location in same AST = one row
    -- (allows multiple definitions of same name at different lines)
    UNIQUE(ast_id, symbol_type, name, line_number)
);

-- Refs: usage edges derived from content
CREATE TABLE refs (
    ref_id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Identity: bound to AST
    ast_id INTEGER NOT NULL,
    
    -- Location within AST
    ast_node_path TEXT,
    line_number INTEGER,
    column_number INTEGER,
    
    -- Reference identity
    ref_type TEXT NOT NULL,                   -- 'trait_ref', 'event_ref', etc.
    name TEXT NOT NULL,                       -- Referenced symbol name
    context TEXT,                             -- Which effect/trigger contains this
    
    -- Resolution (symbol_id now points to content-scoped symbol)
    resolution_status TEXT NOT NULL DEFAULT 'unknown',
    resolved_symbol_id INTEGER,
    candidates_json TEXT,
    
    FOREIGN KEY (ast_id) REFERENCES asts(ast_id) ON DELETE CASCADE,
    FOREIGN KEY (resolved_symbol_id) REFERENCES symbols(symbol_id),
    
    -- Uniqueness
    UNIQUE(ast_id, ref_type, name, context, line_number)
);
```

### 2.3 Create Indices

```sql
-- Symbols indices
CREATE INDEX idx_symbols_ast ON symbols(ast_id);
CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_symbols_type ON symbols(symbol_type);
CREATE INDEX idx_symbols_type_name ON symbols(symbol_type, name);

-- Refs indices
CREATE INDEX idx_refs_ast ON refs(ast_id);
CREATE INDEX idx_refs_name ON refs(name);
CREATE INDEX idx_refs_type ON refs(ref_type);
CREATE INDEX idx_refs_type_name ON refs(ref_type, name);
CREATE INDEX idx_refs_status ON refs(resolution_status);
```

### 2.4 Create FTS Tables

```sql
CREATE VIRTUAL TABLE symbols_fts USING fts5(
    name,
    symbol_type,
    content=symbols,
    content_rowid=symbol_id
);

CREATE VIRTUAL TABLE refs_fts USING fts5(
    name,
    ref_type,
    content=refs,
    content_rowid=ref_id
);
```

### 2.5 Recreate Lookup Tables (FK to new symbols)

```sql
CREATE TABLE trait_lookups (
    trait_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    trait_group TEXT,
    level INTEGER,
    is_genetic INTEGER DEFAULT 0,
    is_physical INTEGER DEFAULT 0,
    is_health INTEGER DEFAULT 0,
    is_fame INTEGER DEFAULT 0,
    opposites_json TEXT,
    flags_json TEXT,
    modifiers_json TEXT,
    FOREIGN KEY (symbol_id) REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    UNIQUE(symbol_id)
);

CREATE TABLE event_lookups (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL,
    event_name TEXT NOT NULL,
    namespace TEXT,
    event_type TEXT,
    is_hidden INTEGER DEFAULT 0,
    theme TEXT,
    FOREIGN KEY (symbol_id) REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    UNIQUE(symbol_id)
);

CREATE TABLE decision_lookups (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    is_shown_check TEXT,
    is_valid_check TEXT,
    major INTEGER DEFAULT 0,
    ai_check_interval INTEGER,
    FOREIGN KEY (symbol_id) REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    UNIQUE(symbol_id)
);
```

---

## 3. Code Changes Required

### 3.1 qbuilder/worker.py - Symbol Extraction

**Current (file-bound):**
```python
INSERT INTO symbols (file_id, content_version_id, name, symbol_type, ...)
```

**Target (AST-bound):**
```python
INSERT INTO symbols (ast_id, name, symbol_type, line_number, ...)
```

**Changes:**
1. Remove `file_id` and `content_version_id` from INSERT
2. Pass `ast_id` from the processing context instead
3. Change delete to: `DELETE FROM symbols WHERE ast_id = ?`

### 3.2 qbuilder/worker.py - Ref Extraction

**Current:**
```python
INSERT INTO refs (file_id, content_version_id, name, ref_type, ...)
```

**Target:**
```python
INSERT INTO refs (ast_id, name, ref_type, line_number, ...)
```

### 3.3 qbuilder/api.py - delete_file()

**Current:**
```python
conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
conn.execute("DELETE FROM refs WHERE file_id = ?", (file_id,))
```

**Target:**
```python
# Symbols/refs cascade-delete when AST is deleted
# If AST is shared by multiple files, DO NOT delete (content may still be needed)
# Only delete AST if no other files reference same content_hash
```

**Logic change:**
- Check if other files share the same `content_hash`
- If yes: do nothing (AST and derived data still valid)
- If no: delete the AST (cascades to symbols/refs)

### 3.4 db_queries.py - Golden Join Pattern

**Current queries use:**
```sql
SELECT ... FROM symbols s
JOIN files f ON f.file_id = s.file_id
```

**Target (Golden Join):**
```sql
SELECT 
    s.symbol_type,
    s.name,
    s.line_number,
    f.relpath,
    cv.content_version_id,
    mp.name AS mod_name
FROM symbols s
JOIN asts a ON a.ast_id = s.ast_id
JOIN files f ON f.content_hash = a.content_hash
JOIN content_versions cv ON cv.content_version_id = f.content_version_id
LEFT JOIN mod_packages mp ON mp.mod_package_id = cv.mod_package_id
WHERE s.name = :symbol_name
```

**Key insight:** The join goes `symbols → asts → files` via `content_hash`.

### 3.5 Playset Filtering

**Current:** `symbols.content_version_id IN (playset_cvids)`

**Target:** Filter via join to files:
```sql
WHERE f.content_version_id IN (playset_cvids)
```

This is slightly more expensive but correct. Index on `files.content_version_id` already exists.

### 3.6 ck3_db_delete Tool

**Current:** Deletes by `content_version_id` directly on symbols/refs

**Target:** 
- For `target="symbols"` or `target="refs"`: Delete ASTs that belong to the specified content_versions
- Let CASCADE handle symbols/refs cleanup

---

## 4. Execution Sequence

### Phase 0: Pre-Migration
```bash
# 1. Stop any running builds
python -m qbuilder.cli stop

# 2. Backup database
cp ~/.ck3raven/ck3raven.db ~/.ck3raven/ck3raven.db.pre-migration

# 3. Verify AST table identity constraint
python -c "
import sqlite3
conn = sqlite3.connect(str(Path.home() / '.ck3raven/ck3raven.db'))
result = conn.execute('''
    SELECT sql FROM sqlite_master 
    WHERE type=\\'table\\' AND name=\\'asts\\'
''').fetchone()
assert 'UNIQUE(content_hash, parser_version_id)' in result[0]
print('✅ AST identity constraint verified')
"
```

### Phase 1: Schema Migration
```bash
# Run migration script (to be created)
python -m qbuilder.migrate_to_content_identity
```

This script will:
1. Drop legacy tables (in correct dependency order)
2. Create new tables
3. Create indices
4. Create FTS tables

### Phase 2: Deploy Code
```bash
# Commit code changes (already prepared)
git add .
git commit -m "feat(schema): migrate symbols/refs to content-identity"
```

### Phase 3: Full Rebuild
```bash
# Clear all queues
python -m qbuilder.cli reset --fresh

# Rediscover all roots
python -m qbuilder.cli discover

# Run full build
python -m qbuilder.cli build
```

---

## 5. Verification Checklist

### Schema Verification
```sql
-- Verify NO file_id or content_version_id in symbols/refs
SELECT sql FROM sqlite_master WHERE name = 'symbols';
-- Should NOT contain 'file_id' or 'content_version_id'

SELECT sql FROM sqlite_master WHERE name = 'refs';
-- Should NOT contain 'file_id' or 'content_version_id'
```

### Deduplication Verification
```sql
-- Find files with identical content
SELECT content_hash, COUNT(*) as file_count
FROM files
GROUP BY content_hash
HAVING file_count > 1
LIMIT 5;

-- For those, verify ONE AST exists
SELECT a.content_hash, COUNT(*) as ast_count
FROM asts a
WHERE a.content_hash IN (
    SELECT content_hash FROM files
    GROUP BY content_hash
    HAVING COUNT(*) > 1
)
GROUP BY a.content_hash;
-- Each row should show ast_count = 1
```

### Golden Join Verification
```sql
-- Test: find where 'brave' trait is defined
SELECT 
    s.name,
    s.symbol_type,
    s.line_number,
    f.relpath,
    mp.name as mod_name
FROM symbols s
JOIN asts a ON a.ast_id = s.ast_id
JOIN files f ON f.content_hash = a.content_hash
JOIN content_versions cv ON cv.content_version_id = f.content_version_id
LEFT JOIN mod_packages mp ON mp.mod_package_id = cv.mod_package_id
WHERE s.name = 'brave' AND s.symbol_type = 'trait';
```

### Grep Verification
```bash
# Confirm no reads of dropped columns
grep -r "symbols.*file_id" tools/ qbuilder/ --include="*.py"
grep -r "symbols.*content_version_id" tools/ qbuilder/ --include="*.py"
grep -r "refs.*file_id" tools/ qbuilder/ --include="*.py"
grep -r "refs.*content_version_id" tools/ qbuilder/ --include="*.py"
# All should return 0 matches
```

---

## 6. Files To Modify (Summary)

| File | Changes |
|------|---------|
| `qbuilder/worker.py` | Change INSERT/DELETE to use ast_id |
| `qbuilder/api.py` | Change delete_file() logic for AST cascade |
| `tools/ck3lens_mcp/ck3lens/db_queries.py` | Update all symbol/ref queries to golden join |
| `tools/ck3lens_mcp/ck3lens/impl/search_ops.py` | Update FTS + symbol fetch |
| `tools/ck3lens_mcp/ck3lens/impl/conflict_ops.py` | Update conflict detection |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | Update symbol queries |
| `tools/ck3lens_mcp/server.py` | Update ck3_db_delete, status queries |
| `scripts/inspect_db.py` | Update debug queries |
| `tests/test_builder_daemon.py` | Update test assertions |

---

## 7. Rollback Plan

If migration fails:
```bash
# Restore pre-migration backup
cp ~/.ck3raven/ck3raven.db.pre-migration ~/.ck3raven/ck3raven.db

# Revert code changes
git checkout HEAD~1

# Rebuild
python -m qbuilder.cli build
```

---

## 8. Success Criteria

Migration is complete when:

- [ ] Schema contains NO `file_id` or `content_version_id` in symbols/refs
- [ ] Identical content produces exactly ONE AST and ONE symbol set
- [ ] Golden joins return correct file paths
- [ ] grep confirms no reads of dropped columns
- [ ] `ck3_search("brave")` returns correct results
- [ ] Playset filtering works via file join
- [ ] All tests pass
