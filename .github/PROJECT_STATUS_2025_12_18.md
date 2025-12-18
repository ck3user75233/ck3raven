# Project Status - December 18, 2025

## Session Summary

This session focused on understanding ck3raven architecture and fixing known issues to get the MCP tools working.

---

## Completed Tasks

### 1. ✅ Documentation Review
- Verified existing documentation is comprehensive
- ck3lens_mcp has README + docs/ folder (DESIGN, SETUP, TESTING, TOOLS)
- ck3lens-explorer has README
- Core docs/ has 00-07 design documents
- No additional documentation needed at this time

### 2. ✅ Created AI Agent Mode System
Created 4 files in `.github/`:
- **COPILOT_RAVEN_DEV.md** - ck3raven development mode instructions (~2000 words)
- **COPILOT_LENS_COMPATCH.md** - ck3lens compatching mode instructions (~1500 words)
- **COPILOT_MODE_SWITCHER.md** - How to switch between modes
- **AI_GUARDRAILS_AND_BEST_PRACTICES.md** - Comprehensive guardrails for AI-assisted development
- **PROPOSED_TOOLS.md** - Tools to add or improve

### 3. ✅ Fixed Version Detection Bug
**File:** `scripts/build_database.py` line 43
- **Was:** `VANILLA_PATH.parent / "launcher-settings.json"` (wrong path)
- **Now:** `VANILLA_PATH.parent / "launcher" / "launcher-settings.json"` (correct)
- **Effect:** New database builds will detect version 1.18.2 instead of falling back to 1.13.x

### 4. ✅ Fixed Column Name Bug in populate_symbols.py
**File:** `scripts/populate_symbols.py` line 75
- **Was:** `SELECT content FROM file_contents`
- **Now:** `SELECT COALESCE(content_text, content_blob) as content FROM file_contents`

### 5. ✅ Created Active Playset
**Result:** 
- Playset "Active Playset" created with ID 1
- 105 mods added (1 skipped: "More Farmlands" not in database)
- Vanilla version shows as 1.13.x (existing database value, fix requires full rebuild)

### 6. ⚠️ Symbol Extraction - Blocked by Design Issue
**File:** `scripts/populate_symbols.py`

**Problem:** The script assumes AST nodes have a `to_dict()` method, but they don't:
```python
ast = parse_source(content, filename=relpath)
ast_dict = ast.to_dict() if hasattr(ast, 'to_dict') else {}  # Returns empty dict!
```

The `extract_symbols_from_ast()` function in `db/symbols.py` expects a serialized dict with `_type`, `name`, `children` keys, but the actual AST uses node objects (`RootNode`, `BlockNode`, `AssignmentNode`).

**Result:** 12,289 files processed, 0 symbols extracted, 10,271 errors

---

## Remaining Issues

### Critical (Must Fix Before MCP Tools Work Fully)

| Issue | Location | Description |
|-------|----------|-------------|
| **AST Serialization Missing** | `parser/` module | AST nodes need `to_dict()` method OR symbols.py needs to work with node objects |
| **Symbols Table Empty** | Database | Blocked by above issue |
| **Refs Table Empty** | Database | Blocked by above issue |
| **MCP Server Cached** | VS Code | MCP server process has stale code; RESTART VS Code to fix |

### Non-Critical (Database Already Has Data)

| Issue | Location | Description |
|-------|----------|-------------|
| **Version Shows 1.13.x** | Database | Existing vanilla_versions row; fix applied but requires rebuild |
| **1 Mod Missing** | active_mod_paths.json | "More Farmlands" not in database index |

---

## Current Database Status

| Table | Count | Status |
|-------|-------|--------|
| vanilla_versions | 1 | ✅ Has data (version 1.13.x) |
| mod_packages | 102 | ✅ All mods indexed |
| content_versions | 106 | ✅ |
| file_contents | 77,121 | ✅ 26 GB deduplicated |
| files | 80,968 | ✅ |
| **playsets** | **1** | ✅ **FIXED THIS SESSION** |
| **playset_mods** | **105** | ✅ **FIXED THIS SESSION** |
| symbols | 0 | ❌ Blocked (needs AST fix) |
| refs | 0 | ❌ Blocked (needs AST fix) |

---

## Next Steps (Priority Order)

### 0. RESTART VS Code (User Action Required)
The MCP server process is caching old code. **Restart VS Code** to pick up fixes:
- Ctrl+Shift+P → "Developer: Reload Window"
- Or close and reopen VS Code entirely

After restart, test:
```
ck3_init_session()
ck3_get_file(file_path="common/traits/00_traits.txt")
```
This should now work (returns file content instead of "file_content" error).

### 1. Fix AST Serialization (ck3raven-dev task)
**Options:**
a) Add `to_dict()` method to AST node classes in `parser/parser.py`
b) Modify `db/symbols.py` extraction functions to accept AST node objects directly

**Recommendation:** Option (a) is cleaner - the serialization should be in the parser module.

**Implementation sketch:**
```python
# In parser.py, add to each Node class:
def to_dict(self) -> dict:
    return {
        '_type': self.node_type,
        'name': getattr(self, 'name', None),
        'line': self.line,
        'column': self.column,
        'children': [c.to_dict() for c in getattr(self, 'children', [])]
    }
```

### 2. Re-run Symbol Extraction
After fixing #1:
```bash
python scripts/populate_symbols.py
```

### 3. Test MCP Tools
After symbols are populated:
```
ck3_init_session()
ck3_search_symbols(query="brave", symbol_type="trait")
```

### 4. (Optional) Rebuild Database for Correct Version
If you want the vanilla version to show 1.18.2:
```bash
python scripts/build_database.py --vanilla-only --force
```
Note: This re-indexes all vanilla files but won't lose mod data.

---

## Mode Switching Reference

### To work on ck3raven infrastructure:
```
Switch to ck3raven-dev mode. I need to fix the AST serialization issue.
```
Or reference: `@.github/COPILOT_RAVEN_DEV.md`

### To work on CK3 mod patching:
```
Switch to ck3lens mode. I need to fix a trait conflict.
```
Or reference: `@.github/COPILOT_LENS_COMPATCH.md`

---

## Files Modified This Session

| File | Change |
|------|--------|
| `scripts/build_database.py` | Fixed version detection path |
| `scripts/populate_symbols.py` | Fixed column name (content → content_text/blob) |
| `.github/COPILOT_RAVEN_DEV.md` | Created |
| `.github/COPILOT_LENS_COMPATCH.md` | Created |
| `.github/COPILOT_MODE_SWITCHER.md` | Created |
| `.github/AI_GUARDRAILS_AND_BEST_PRACTICES.md` | Created |
| `.github/PROPOSED_TOOLS.md` | Created |

## Files Deleted This Session

| File | Reason |
|------|--------|
| `AI Workspace/check_db.py` | Duplicative diagnostic script |

---

## Architecture Notes for Next Session

The ck3raven parser produces AST node objects:
- `RootNode` - contains list of `children`
- `BlockNode` - has `name`, `children`, `line`, `column`
- `AssignmentNode` - has `key`, `value`, `line`, `column`
- `ValueNode` - has `value`, `line`, `column`
- `ListNode` - has `values`, `line`, `column`

The symbols module expects a serialized dict format with `_type` discriminator.

Either the AST needs serialization, or the symbols extraction needs to be rewritten to traverse objects directly. The former is preferred for cleaner separation of concerns.
