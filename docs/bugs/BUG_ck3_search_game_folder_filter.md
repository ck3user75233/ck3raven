# Bug Report: ck3_search game_folder Filter Not Applied to Adjacency Results

## Summary
The `game_folder` parameter in `ck3_search` is not being applied to adjacency symbol searches, resulting in results from outside the specified folder being returned.

## Environment
- **Tool**: `mcp_ck3lens_ck3_search`
- **Date Discovered**: 2024-12-25

## Steps to Reproduce
1. Call `ck3_search` with a specific `game_folder` filter:
```python
ck3_search(
    query="on_action",
    game_folder="events",
    limit=50
)
```

2. Observe the results

## Expected Behavior
ALL result categories should respect the `game_folder="events"` filter:
- `content` results: Only from `events/` folder ✅
- `files` results: Only from `events/` folder ✅
- `symbols` results: Only from `events/` folder ❌
- `symbols.adjacencies`: Only from `events/` folder ❌

## Actual Behavior
The `game_folder` filter is correctly applied to:
- ✅ `content` results (all from `events/` folder)
- ✅ `files` results (all from `events/` folder)

But **NOT** applied to:
- ❌ `symbols.adjacencies` - returns results from `common/on_action/` folder

### Example Incorrect Adjacency Results:
```json
{
  "symbol_id": 45594,
  "name": "on_action_add_sexuality",
  "symbol_type": "on_action",
  "file_id": 13717,
  "relpath": "common/on_action/childhood_on_actions.txt",  // NOT in events/
  "mod": "Unofficial Patch",
  "line": 382,
  "match_type": "prefix"
}
```

## Impact
- **Severity**: Medium
- Causes confusion when trying to search within a specific game folder
- Makes it harder to find actual matches within the target folder as the adjacency results pollute the output
- User may miss actual results buried under irrelevant adjacency matches

## Root Cause Analysis
The `game_folder` filter appears to only be applied during the main symbol/content/file search phases, but the adjacency/fuzzy symbol matching is performed against the entire database without the folder constraint.

## Suggested Fix
Apply the `game_folder` filter to the adjacency symbol search query. The adjacency matching SQL should include a `WHERE relpath LIKE '{game_folder}%'` clause when `game_folder` is specified.

## Workaround
Use `ck3_grep_raw` instead for folder-constrained searches, as it correctly limits results to the specified path.
