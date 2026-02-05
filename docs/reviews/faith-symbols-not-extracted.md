# Bug Report: Faith symbols not extracted from religion files

**Date**: 2026-02-05  
**Discovered by**: CK3 Lens agent during compatch work  
**Severity**: Medium (impacts reference validation and conflict detection)

## Summary

The symbol extractor correctly identifies `religion` symbols from the top-level blocks in `common/religion/religions/*.txt` files, but fails to extract nested `faith` symbols from within the `faiths = { }` block inside each religion.

## Evidence

### 1. Parser is working correctly

AST for `00_christianity.txt` shows 1666 nodes, parse_ok=1, and the faith blocks are properly parsed:

```
christianity_religion (root block, line 1)
  └── faiths (nested block, line 248)
        ├── catholic (nested block, line 249)
        ├── orthodox (nested block, line 323)
        ├── coptic (nested block, line 396)
        ├── armenian_apostolic (nested block, line 469)
        ├── conversos (nested block, line 540)
        ├── cathar (nested block, line 568)
        ├── waldensian (nested block, line 615)
        ├── lollard (nested block, line 640)
        ├── iconoclast (nested block, line 665)
        ├── bogomilist (nested block, line 689)
        ├── paulician (nested block, line 732)
        ├── nestorian (nested block, line 766)
        ├── messalian (nested block, line 798)
        ├── adamites (nested block, line 846)
        ├── insular_celtic (nested block, line 892)
        ├── bosnian_church (nested block, line 1014)
        ├── mozarabic_church (nested block, line 1084)
        └── adoptionist (nested block, line 1119)
```

### 2. Symbol extractor only captures religions

```sql
-- Returns 124 results
SELECT * FROM symbols WHERE symbol_type = 'religion';

-- Returns 0 results  
SELECT * FROM symbols WHERE symbol_type = 'faith';
```

### 3. Faith references ARE being used in mods

Examples from error logs (prior to restart):
- `faith:slavic_orthodox` - referenced in A Special World
- `faith:circassian_christianity` - referenced in A Special World

Since faiths aren't indexed, we cannot:
- Validate these references
- Determine if the faiths are defined by a mod in the playset
- Detect conflicts when multiple mods define the same faith

## Expected Behavior

Symbol extractor should:
1. Recognize blocks inside `faiths = { }` within religion files
2. Extract them with `symbol_type = "faith"`
3. Names should be: `catholic`, `orthodox`, `coptic`, `slavic_pagan`, etc.

## Impact

- ❌ Cannot validate `faith:X` references in scripts
- ❌ Cannot detect conflicts when multiple mods define the same faith
- ❌ Cannot search for faith definitions in the database
- ❌ Error log analysis cannot determine if faith references are valid

## Technical Details

**Test file**: `common/religion/religions/00_christianity.txt`  
**AST ID**: 1692  
**File ID**: 1863  

**Only symbol extracted**: 
- `christianity_religion` (symbol_type: religion, line 1)

**Missing symbols** (should be symbol_type: faith):
- `catholic` (line 249)
- `orthodox` (line 323)
- `coptic` (line 396)
- `armenian_apostolic` (line 469)
- `conversos` (line 540)
- `cathar` (line 568)
- `waldensian` (line 615)
- `lollard` (line 640)
- `iconoclast` (line 665)
- `bogomilist` (line 689)
- `paulician` (line 732)
- `nestorian` (line 766)
- `messalian` (line 798)
- `adamites` (line 846)
- `insular_celtic` (line 892)
- `bosnian_church` (line 1014)
- `mozarabic_church` (line 1084)
- `adoptionist` (line 1119)

## Root Cause Hypothesis

The symbol extractor likely has logic like:

```python
if folder == "common/religion/religions":
    # Extract top-level block name as "religion"
    symbol_type = "religion"
    name = block.name
```

But lacks the nested extraction:

```python
if folder == "common/religion/religions":
    for block in top_level_blocks:
        # Extract religion
        emit_symbol(name=block.name, symbol_type="religion")
        
        # Find "faiths" child block
        faiths_block = find_child(block, "faiths")
        if faiths_block:
            for faith_block in faiths_block.children:
                if faith_block.type == "block":
                    emit_symbol(name=faith_block.name, symbol_type="faith")
```

## Suggested Fix Location

Look in the symbol extraction code for:
- `common/religion/religions` folder handling
- Religion symbol extraction logic
- Add nested extraction for faiths block

## Related

This same pattern may apply to other nested game concepts:
- Cultures within heritage groups?
- Doctrines within religions?
- Other nested definitions?

## Verification Query

After fix, this should return results:
```sql
SELECT s.name, s.symbol_type, s.line_number, f.relpath
FROM symbols s
JOIN asts a ON s.ast_id = a.ast_id
JOIN files f ON a.file_id = f.file_id
WHERE s.symbol_type = 'faith'
AND f.relpath LIKE '%christianity%'
ORDER BY s.line_number;
```
