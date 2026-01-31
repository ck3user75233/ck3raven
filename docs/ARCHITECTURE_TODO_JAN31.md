# Architecture TODO - January 31, 2026

> **Status:** PARKED - Returning to this after agent-as-participant refactor is complete
> **Context:** Issues identified during extension crash debugging session

---

## Priority Items

### 1. Add ROOT_VSCODE Canonical Domain
Add `ROOT_VSCODE` to `RootCategory` enum in `capability_matrix.py`. Should cover `%APPDATA%\Code\User\` and related VS Code user directories. Set `read=True`, `write=True` for ck3raven-dev mode.

### 2. Consider ROOT_OTHER Catch-All Domain  
Evaluate adding `ROOT_OTHER` as catch-all for paths outside known domains. For ck3lens: `NOT_FOUND`. For ck3raven-dev: visible but enforcement decides write permission. Check if Enum supports this pattern.

### 3. Refactor WorldAdapter to Use RootCategory
WorldAdapter uses **BANNED concepts** (`ck3raven_root`, `wip_root`, `vanilla_root`, `AddressType`, `PathDomain`). Must refactor to use canonical `RootCategory` from `capability_matrix.py`. Single source of truth for domain classification.

### 4. Remove Parallel Domain Systems
Remove `AddressType` enum and `PathDomain` enum from `world_adapter.py`. These are parallel constructions to `RootCategory`. Replace all usages with `RootCategory`.

### 5. Fix token_id='confirm' Bypass
`enforcement.py` lines 697-710 (and similar) allow ANY `token_id` string as confirmation. Must validate `token_id` against canonical token system in `tools/compliance/tokens.py`. No more magic string bypass.

> ⚠️ **NOTE:** Integration of canonical tokens into enforcement is a **Canonical Contract System Phase 2 migration deliverable** and cannot be done now. We are still preparing for Phase 2 of the contract system migration.

### 6. Integrate Canonical Tokens into Enforcement
**DEFERRED TO PHASE 2** - `enforcement.py` must validate tokens via `tools/compliance/tokens.py` Token class. Check signature, expiry, scope, contract_id. Reject tokens that don't pass validation.

### 7. Audit ck3_exec vs ck3_file Consistency
`ck3_exec` bypasses WorldAdapter and goes straight to enforcement. `ck3_file` uses WorldAdapter which rejects paths before enforcement sees them. Must make consistent - both should go through same visibility layer.

### 8. Fix MCP Server Not Starting in Dev Host
Extension dev host shows MCP server as STOPPED. `chat.mcp.discovery.enabled` was fixed in main VS Code settings but dev host may need different handling. Investigate why server not starting.

### 9. Clean Remaining Claude Extension Artifacts
Ran Python script to clean `editorOverrideService.cache`. Verify `claude-code` entries are gone. May need VS Code restart to fully clear.

### 10. Map RootCategory to Filesystem Paths
Create canonical mapping from `RootCategory` to actual filesystem paths. `ROOT_REPO` -> ck3raven source, `ROOT_VSCODE` -> `%APPDATA%\Code\`, etc. This replaces the banned `_root` variables.

### 11. Update Workspace Config to Define Domain Paths
Domain path mappings should come from workspace config (`ck3raven-config.json`), not hardcoded. `ROOT_VSCODE` path, `ROOT_REPO` path, etc. should be configurable.

---

## Completed

- [x] **Remove Orphaned Compiled Files** - Deleted orphaned `tokens.cpython-313.pyc` from `policy/__pycache__`. Audit for other orphaned `.pyc` files that don't have source.

---

## Related Issues

### Broken .disabled Extension Folder
VS Code Shared process errors on startup:
```
Error: Unable to read file 'c:\Users\nateb\.vscode\extensions\ck3lens.ck3lens-explorer-0.1.0.disabled\package.json'
```
This folder should not exist - it's a remnant from a failed disable operation.

### claude-code Chat Participant Error
```
Error: chatParticipant must be declared in package.json: claude-code
```
Remnant from uninstalled Claude extension still cached somewhere.

---

## Architecture Context

Key files involved:
- `tools/ck3lens_mcp/ck3lens/policy/capability_matrix.py` - Canonical `RootCategory` enum
- `tools/ck3lens_mcp/ck3lens/world_adapter.py` - Uses BANNED parallel systems
- `tools/ck3lens_mcp/ck3lens/policy/enforcement.py` - Token bypass bug
- `tools/compliance/tokens.py` - Canonical token system (NST, LXE only)
