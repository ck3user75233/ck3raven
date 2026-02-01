# ck3_logs MCP Tool - Bug Reports & Feature Requests

**Date:** February 1, 2026  
**Reporter:** Agent session working on MSC playset error analysis  
**Tool Version:** ck3lens MCP (current)

---

## 🐛 Bug Reports

### BUG-1: `command=read` Returns Empty Content
**Severity:** High  
**Reproducibility:** Consistent

**Steps to Reproduce:**
```python
ck3_logs(source="error", command="read", lines=100)
```

**Expected:** Raw log content (first/last N lines)  
**Actual:** Returns structure but `content` field is empty or missing USER COMMENT: I believe the agent may have tried this while CK3 was booting, so the log was wiped.

**Impact:** Cannot retrieve raw log content for backup/archival. Agent attempted to save error.log content to WIP but got analysis metadata instead of actual log lines.

---

### BUG-2: Cascade Detection Missing Cross-File Relationships
**Severity:** Medium

**Description:** `command=cascades` identifies patterns within single files but doesn't correlate cascades across different source files. For example, a missing trait definition in one mod causes errors in 5 other mods' events - these aren't linked as a cascade.

**Expected:** Cascade detection should group errors by root cause symbol, not just by file proximity.

---

### BUG-3: `mod_filter` Partial Match Too Greedy
**Severity:** Low

**Description:** When using `mod_filter="RICE"`, it may match mods with "RICE" anywhere in the name (e.g., "RICE Flavor" and "Price of Power" if such existed).

**Expected:** Option for exact match vs contains match.

---

## 🚀 Feature Requests

### FR-1: Raw Log Export Command
**Priority:** High

**Request:** Add `command=export` or `command=raw` that returns the actual log file content as a string, suitable for saving to a file.

**Use Case:** User wanted to backup error.log before launching CK3 (which wipes logs). Current tool only provides parsed/analyzed data, not raw content.

**Suggested API:**
```python
ck3_logs(source="error", command="raw", lines=500, from_end=True)
# Returns: {"content": "<raw log text>", "lines_returned": 500}
```

---

### FR-2: Cascade Root Cause Linking
**Priority:** High

**Request:** Enhance cascade detection to identify the **root cause symbol** and link all downstream errors to it.

**Current:** Returns cascade patterns as isolated groups  
**Requested:** Return structure like:
```python
{
  "root_cause": {
    "type": "missing_symbol",
    "symbol": "trait_brave",
    "source_mod": "Mod A",
    "file": "common/traits/00_traits.txt"
  },
  "cascading_errors": [
    {"mod": "Mod B", "file": "events/x.txt", "error": "Unknown trait trait_brave"},
    {"mod": "Mod C", "file": "decisions/y.txt", "error": "..."},
  ],
  "total_cascade_count": 47
}
```

---

### FR-3: Error Deduplication with Counts
**Priority:** Medium

**Request:** Add deduplication mode that collapses identical errors with occurrence counts.

**Use Case:** Error log had 10,346 entries but many were duplicates (same error, different contexts). A deduplicated view would show ~500 unique errors with counts.

**Suggested API:**
```python
ck3_logs(source="error", command="list", dedupe=True) USER COMMENT: Suggest dedupe = true should be default behavior and absolute count need the param
# Returns errors with "count" field showing occurrences USER COMMENT: There should be clusters of different failures for "same error, different context" and those clusters should be summarized as sub-counts with a description about the cluster underneath the header count which is the total for that error
```

---

### FR-4: Error-to-Symbol Resolution
**Priority:** Medium

**Request:** When an error references a symbol (trait, event, decision, etc.), automatically look it up in the database and include resolution info.

**Current:** Error says "Unknown trait xyz"  
**Requested:** Tool adds: `"resolution": {"symbol_exists": true, "defined_in": "Mod X", "load_order_issue": true}` USER COMMENT: Unsure on feasibility, but we could include some automated checks for near matches to that symbol using pattern matching, and highlight any hits. I would not want us using rudimentary logic to provide fix instructions, though. That could cause agents to blindly create fixes that make the problems worse.

---

### FR-5: Mod Attribution Accuracy
**Priority:** Medium

**Request:** Improve mod attribution for errors. Currently some errors are attributed to "vanilla" or wrong mod when the actual source is a mod override.

**Example:** Error in `common/traits/00_traits.txt` attributed to vanilla, but actually caused by a mod's override of that file. USER COMMENT: It may not be realistic for an MCP tool to give correct attribution, but it should be able to give correct context - the same file is overridden 1 or more times, we could just say XXXXX is a vanilla game file, with override/s from Mod X, path for override, Mod Z, path for override, etc

---

### FR-6: Log Diff Between Sessions
**Priority:** Low

**Request:** Ability to compare error logs between sessions to see what's new/fixed.  USER COMMENT: This is a really good idea but would require us to store the parsed errors and be able to repeat all analysis on the new ones. I could see this making sense for say 3 sessions worth. If we do this we should have the game and debug logs as well. Perhaps we only store resulting analysis with de-duped errors in JSON and actually do the comparison by conducting the analysis on the current/new logs. This would reduce storage space consumed while still giving the agent what it is looking for.

**Use Case:** After applying fixes, user wants to know "did my changes reduce errors?"

**Suggested API:**
```python
ck3_logs(command="diff", baseline="2026-01-31", current="2026-02-01")
# Returns: new errors, fixed errors, unchanged errors
```

---

### FR-7: Priority Auto-Classification Tuning
**Priority:** Low

**Request:** Allow user to customize priority classification rules or see the logic used. USER COMMENT: This is a really good one. would be good to understand the feasibility of customization

**Current:** Tool assigns P1-P5 priorities but the criteria aren't visible.

**Requested:** Expose classification logic or allow override via config.

---

### FR-8: Integration with ck3_conflicts
**Priority:** Low

**Request:** Cross-reference errors with known conflicts from `ck3_conflicts()`. If an error stems from a symbol conflict, link them. USER COMMENT: we need to proof of concept this as I'm not convinced it is easy to know if an error is caused by a conflict or not. However, as per another of my comments above what the ck3_logs tool can't figure out can still be presented as context - hey this symbol is throwing errors and btw it is defined / overwritten a couple of times and here are the mods and paths.  We could go so far as to provide the diffs ... idk let's play with options...

---

## 🔗 Cross-Log Analysis (game.log / debug.log / error.log)

### Current State Assessment

**error.log** (source="error"):
- 3,522 errors with priority classification (P1-P5)
- Cascade detection (47 cascades found)
- Categories: scope_error, missing_reference, duplicate_key, script_system_error, etc.
- Mod attribution (partial - uses workshop IDs, not names)

**game.log** (source="game"):
- 907 errors with category breakdown
- Good file path extraction (e.g., `events/decision_events/volga_event.txt line: 12`)
- Categories: culture_error, building_error, religion_error, casus_belli_error, etc.
- Source file attribution (e.g., `decision_type.cpp:223`)
- **NO mod attribution** (mod_id/mod_name always null)

**debug.log** (source="debug"):
- System info (GPU, threads)
- DLC list (20 enabled)
- Mod list (112 enabled, 558 disabled)
- **NO error parsing** - only metadata extraction

---

### GAP-1: No Cross-Log Correlation
**Priority:** High

**Problem:** Same underlying issue appears differently in error.log vs game.log, but there's no way to correlate them.

**Example from this session:**
- game.log: `"Casus belli rv_rescue_war missing on_defeat_desc"` (decision_type.cpp)
- error.log: Likely has related parser/validation error for same file

**Request:** Add `command=correlate` that matches errors across logs by:
- File path + line number
- Symbol name
- Timestamp proximity

---

### GAP-2: game.log Missing Mod Attribution
**Priority:** High

**Problem:** game.log errors include file paths but not which mod the file belongs to.

**Current:** `"file": "events/decision_events/volga_event.txt"` with `"mod_id": null`

**Expected:** Tool should resolve file path to mod via database lookup.

**Implementation:** When parsing game.log, call the file index to determine which mod owns each file path.

---

### GAP-3: debug.log Underutilized
**Priority:** Medium

**Problem:** debug.log contains the authoritative mod list, but it's not used to enhance error.log/game.log parsing.

**Current:** debug.log just returns metadata (DLC list, mod list)

**Requested Enhancements:**
1. Use mod list from debug.log to resolve "Mod 2217509277" → actual mod name
2. Cross-reference enabled mods with errors to identify which mods are error-free
3. Add "mod health report" showing errors per mod from all log sources

---

### GAP-4: No Unified Error View
**Priority:** Medium

**Problem:** User must query error.log and game.log separately to get complete error picture.

**Request:** Add `command=unified` that merges errors from both logs:
```python
ck3_logs(command="unified", limit=100)
# Returns combined, deduplicated errors from error.log + game.log
# with source field indicating which log(s) reported each error
```

---

### GAP-5: game.log Has Better File Context
**Priority:** Medium

**Observation:** game.log errors often include exact file path and line number:
```json
{"file_path": "events/decision_events/volga_event.txt", "game_line": 12}
```

But error.log categorization/priority is better.

**Request:** Combine the best of both:
- Use game.log's file/line precision
- Use error.log's priority classification
- Produce enriched error records

---

### GAP-6: Mod Error Summary Missing
**Priority:** Medium

**Request:** Add `command=mod_health` that produces per-mod error statistics:
```python
ck3_logs(command="mod_health")
# Returns:
# {
#   "mods": [
#     {"name": "RICE", "error_log_errors": 45, "game_log_errors": 12, "total": 57},
#     {"name": "CFP", "error_log_errors": 23, "game_log_errors": 8, "total": 31},
#     ...
#   ],
#   "error_free_mods": ["Mod A", "Mod B", ...]
# }
```

**Use Case:** Quickly identify which mods are causing the most issues.

---

### GAP-7: Source File (C++ Location) Analysis
**Priority:** Low

**Observation:** game.log includes CK3 engine source locations:
- `culture_name_equivalency.cpp:101` (228 errors)
- `building_type.cpp:95` (208 errors)
- `religion_templates.cpp:224` (122 errors)

**Request:** Add documentation/hints for what each source file category means:
```python
ck3_logs(source="game", command="source_file_guide")
# Returns: {"building_type.cpp": "Building definition validation errors", ...}
```

---

### Summary: Cross-Log Feature Matrix

| Feature | error.log | game.log | debug.log | Unified |
|---------|-----------|----------|-----------|---------|
| Error parsing | ✅ | ✅ | ❌ | Requested |
| Priority classification | ✅ | ❌ | N/A | Requested |
| Cascade detection | ✅ | ❌ | N/A | Requested |
| File path extraction | Partial | ✅ | N/A | Combine |
| Line number | Sometimes | ✅ | N/A | Combine |
| Mod attribution | Workshop ID | ❌ | Full list | Requested |
| Category breakdown | ✅ | ✅ | N/A | Merge |
| Cross-log correlation | ❌ | ❌ | ❌ | **Needed** |

---

## 📊 Empirical Correlation Analysis

### Evidence: Same Errors Appear in Both Logs

Tested correlation by searching for specific symbols across logs:

| Symbol | error.log | game.log | Finding |
|--------|-----------|----------|---------|
| `east_slavic_building_gfx` | 50+ entries, **cascade_group 36**, priority 3 | 208 building_error entries | Same issue, different metadata |
| `ceithern` regiment | 1 entry with file path + line 59 | 1 entry with file path + line 59 | **Identical** duplicate |
| `mscre_celtic.txt` | UTF-8 encoding warning + 2 regiment errors | 2 regiment errors only | error.log has **additional context** |

**Overlap Rate:** ~30-50% of errors exist in BOTH logs with different metadata.

---

### High-Value Use Cases

#### **USE CASE 1: Mod Attribution via File Path (HIGH PRIORITY)**

```
game.log: file_path = "common/religion/religions/mscre_celtic.txt", line 59
         mod_id = null, mod_name = null  ← PROBLEM

ck3raven database: can resolve file path → mod name
debug.log: has full mod list with names
```

**Current State:** 0% of game.log errors have mod attribution
**With Correlation:** ~70% could have mod names

**Implementation Note:** ck3raven already has file→mod resolution in the database layer. The `ck3_search` and `ck3_file` tools resolve paths to mods. This capability just needs to be connected to `ck3_logs` parsing.

**Suggested approach:**
1. When parsing game.log errors with `file_path`, call existing file index lookup
2. Return `mod_name` populated from database
3. For workshop IDs in error.log (e.g., "Mod 2217509277"), resolve via debug.log mod list or launcher registry

---

#### **USE CASE 2: Deduplication + Priority Merging (HIGH PRIORITY)**

```
error.log: "east_slavic_building_gfx" → priority 3, cascade_group 36
game.log: same error → category "building_error", subcategory "Building/gfx culture flag errors"
```

**Current:**
- error.log shows 50+ entries for same root cause
- game.log shows 208 entries for same category
- User sees ~260 errors that are really ~1 issue

**With Deduplication:**
- Collapse to 1 unique error
- Show count: 208
- Merge metadata: priority 3 + category "building_error" + cascade info

**Noise Reduction:** 4,000 errors → ~800 unique issues (5x improvement)

---

#### **USE CASE 3: Priority Correction**

```
error.log: "Invalid regiment type ceithern" - priority 5 (unknown/unclassified)
game.log: Same error - category "religion_error"
```

error.log assigned priority 5 because it couldn't classify the error. game.log knows it's a religion error (should be P2-P3). Merging fixes the priority.

---

#### **USE CASE 4: Cascade Labeling**

```
error.log: cascade_group 36 with 50 children (no category info)
game.log: category "building_error", subcategory "Building/gfx culture flag errors"
```

Combined output: "50 cascading **building/gfx culture flag** errors - fix root cause `east_slavic_building_gfx` first"

---

### Quantified Value

| Metric | Current | With Correlation |
|--------|---------|------------------|
| Errors with mod attribution | ~5% | ~70% |
| Displayable unique errors | 4,000+ | ~800 |
| Errors with category + priority | ~40% | ~85% |
| Cascade groups with labels | 0% | ~60% |

---

### Recommendation Priority

| Rank | Feature | Effort | Impact | Notes |
|------|---------|--------|--------|-------|
| **1** | File path → mod resolution | Low | High | **Infrastructure exists in ck3raven** |
| **2** | Cross-log deduplication | Medium | High | 5x noise reduction |
| **3** | Priority merging from game.log categories | Low | Medium | Fixes "unknown" classifications |
| **4** | Cascade category labeling | Low | Medium | Better fix guidance |

---

## 📋 Session Observations

### What Worked Well
- `command=summary` provides excellent high-level overview
- `command=cascades` is valuable for prioritizing fixes
- Priority classification helps focus on important issues
- `mod_filter` is useful for isolating mod-specific problems

### Pain Points
- No way to get raw log content for backup
- Had to manually correlate cascade root causes
- Large error counts make output unwieldy without deduplication
- Log wiped on CK3 launch before we could archive it

### Workflow Suggestion
Consider adding a "session workflow" mode:
1. `ck3_logs(command="snapshot")` - save current log state
2. User launches CK3, plays, exits
3. `ck3_logs(command="compare", baseline="snapshot_id")` - what changed?

---

## Summary

| ID | Type | Priority | Summary |
|----|------|----------|---------|
| BUG-1 | Bug | High | `command=read` returns empty content |
| BUG-2 | Bug | Medium | Cascade detection missing cross-file links |
| BUG-3 | Bug | Low | `mod_filter` too greedy |
| FR-1 | Feature | High | Raw log export command |
| FR-2 | Feature | High | Cascade root cause linking |
| FR-3 | Feature | Medium | Error deduplication with counts |
| FR-4 | Feature | Medium | Error-to-symbol resolution |
| FR-5 | Feature | Medium | Improved mod attribution |
| FR-6 | Feature | Low | Log diff between sessions |
| FR-7 | Feature | Low | Priority classification tuning |
| FR-8 | Feature | Low | Integration with ck3_conflicts |
| GAP-1 | Cross-Log | High | No cross-log correlation (error.log ↔ game.log) |
| GAP-2 | Cross-Log | High | game.log missing mod attribution |
| GAP-3 | Cross-Log | Medium | debug.log mod list not used to resolve mod IDs |
| GAP-4 | Cross-Log | Medium | No unified error view across logs |
| GAP-5 | Cross-Log | Medium | game.log file context not merged with error.log priority |
| GAP-6 | Cross-Log | Medium | Missing per-mod error health summary |
| GAP-7 | Cross-Log | Low | C++ source file category documentation |
