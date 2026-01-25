
yes, in the form of a bug reportt but make it multi part - the engagement with the symbols database is crazy to put in this process - contract open is not meant to do validation of work complete , or enforcement so there is no need for this effort to sit in the open command. A diff assessment of files with the edits done vs. the files before the edits at the end of the contract will identify any symbols. This list can be compared with the database, and any with references in any files /blocks not edited in the work actually completed are by definition not new. Symbols with no refs except for the edited code are new. It's that simple. We do not require a 'snapshot' of the database or anything silly like that. I am uncertain about the git activity there - that sounds wrong too but I am less certain. Perhaps that just ensures the edits are tagged with the appropriate contract in git.

Bug Report: ck3_contract(command="open") Hangs Intermittently
Reported: January 25, 2026
Severity: Critical (blocks all contract-gated operations)
Affected Component: server.py → ck3_contract() function

Part 1: MCP Transport Hang - Enum Serialization Failure
Symptom
ck3_contract(command="open", ...) hangs intermittently. The MCP transport layer fails to return any response (pass or fail). Adding logging confirmed the hang occurs after the contract object is created but before the response is received by the caller.

Root Cause
The return dictionary includes Enum objects that don't serialize to JSON:

File: server.py

return {
    "success": True,
    "contract_id": contract.contract_id,
    "root_category": contract.root_category,   # ← RootCategory Enum
    "operations": contract.operations,          # ← List of Operation Enums
    "expires_at": contract.expires_at,
    "schema_version": "v1",
}

File: contract_v1.py

def __post_init__(self):
    # These normalize TO Enum types, not strings
    self.mode = AgentMode(self.mode)
    self.root_category = RootCategory(self.root_category)
    self.operations = [Operation(op) for op in self.operations]

Standard json.dumps() cannot serialize Enum objects. The FastMCP transport attempts serialization, fails silently or hangs waiting for a response that never completes.

Fix
Convert Enums to their string values before returning:

return {
    "success": True,
    "contract_id": contract.contract_id,
    "root_category": contract.root_category.value,
    "operations": [op.value for op in contract.operations],
    "expires_at": contract.expires_at,
    "schema_version": "v1",
}

Part 2: Architectural Violation - Symbol Snapshot at Contract Open
Symptom
Contract open is slow and sometimes hangs during database operations.

Root Cause
The open_contract() function performs expensive symbol database queries:

File: contract_v1.py

from tools.compliance.symbols_lock import (
    create_symbols_snapshot,
    get_active_playset_identity,
)

# Create baseline snapshot
snapshot = create_symbols_snapshot(f"baseline_{contract_id}")
snapshot_saved_path = snapshot.save()

File: symbols_lock.py

def query_symbol_provenance(cvids: list[int]) -> list[SymbolProvenance]:
    # Queries 147K+ symbols with JOIN across symbols/asts/files tables
    cursor = conn.execute(f"""
        SELECT ... FROM symbols s
        JOIN asts a ON s.ast_id = a.ast_id
        JOIN files f ON a.content_hash = f.content_hash
        WHERE f.content_version_id IN ({placeholders})
        ...
    """, cvids)

Why This Is Wrong
Contract open is NOT validation — It declares intent, not results
Contract open is NOT enforcement — That happens at execution time
A "snapshot" of 147K symbols is absurd — We don't need to capture the entire database state
Correct Architecture: Detect New Symbols at Contract CLOSE
New symbol detection belongs at contract close, not open. The algorithm is simple:

1. At contract close, identify all files that were ACTUALLY edited
2. Diff each edited file: before-state vs after-state
3. Extract symbols from the after-state that weren't in the before-state
4. For each candidate "new" symbol:
   - Query database for references to this symbol
   - If references exist in files NOT edited by this contract → NOT NEW (override)
   - If references exist ONLY in files edited by this contract → NEW symbol
5. Report new symbols for audit

This requires:

File diffs (already tracked by git)
Symbol extraction from changed files only (small, bounded work)
Reference lookup for candidate symbols (indexed, fast)
This does NOT require:

Full database snapshot at open
147K symbol provenance queries
Playset hash tracking at open
Any blocking work at contract open time
Files to Modify
Remove from open_contract():

Lines 583-600 in contract_v1.py
The baseline_snapshot_path, baseline_playset_hash fields (or make them optional/computed at close)
Add to close_contract():

Compute file diffs from git
Extract symbols from modified files
Check references to identify truly new symbols
Part 3: Git Activity Concern (Investigation Needed)
Observation
The open_contract() function also runs git commands:

File: contract_v1.py

result = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=str(repo_root),
    capture_output=True,
    text=True,
    timeout=5,
)
if result.returncode == 0:
    base_commit = result.stdout.strip()

Assessment
This is probably acceptable for tagging the contract with the git state at open time. The base_commit can be used later to:

Compute diffs at close time
Identify which files changed during the contract
However, the 5-second timeout could contribute to intermittent hangs if git is slow (large repo, network issues with remote tracking).

Recommendation
Keep base_commit capture but verify it's not blocking
Consider making it async or best-effort (non-fatal if it fails)
Summary of Required Changes
Priority	Issue	Fix Location	Effort
P0	Enum serialization	server.py L3099-3107	5 min
P1	Remove symbol snapshot from open	contract_v1.py L583-600	30 min
P2	Implement new-symbol detection at close	close_contract()	2-4 hrs
P3	Review git timeout handling	contract_v1.py L566-575	15 min
Immediate Hotfix (Part 1 Only)
To unblock agents immediately, fix the Enum serialization in server.py:

# Line ~3099-3107 in ck3_contract()
return {
    "success": True,
    "contract_id": contract.contract_id,
    "root_category": contract.root_category.value if hasattr(contract.root_category, 'value') else str(contract.root_category),
    "operations": [op.value if hasattr(op, 'value') else str(op) for op in contract.operations],
    "expires_at": contract.expires_at,
    "schema_version": "v1",
}

And in the try/except block, also remove or defer the symbol snapshot creation to avoid the expensive database work entirely.