# Architecture TODO - January 31, 2026

> **Status:** ACTIVE - Ready for work  
> **Context:** Issues identified during extension crash debugging session

---

## Completed Today (January 31, 2026)

- [x] **Fix MCP in dev host** - Fixed `launch.json` with workspace path as 3rd argument. MCP server now starts in Extension Development Host.

- [x] **Clean Claude extension artifacts** - Deleted `Sixth.sixth-ai`, `saoudrizwan.claude-dev`, and `workbench.view.extension.claude-dev-ActivityBar.state.hidden` from `state.vscdb`.

- [x] **Fix chat.mcp.discovery.enabled** - Changed from object format `{claude-desktop: true, ...}` to boolean `true` in BOTH user settings AND `ck3lens-modding.code-workspace`.

- [x] **Remove orphaned compiled files** - Deleted orphaned `tokens.cpython-313.pyc` from `policy/__pycache__`.

- [x] **Fix participant tool result handling** - Changed `[tr.result]` to `tr.content` in participant.ts. Error case now creates `LanguageModelTextPart`.

- [x] **Add maxTokens to participant requests** - Added `maxTokens: 16384` to model request options.

- [x] **Agent-as-participant implementation** - Complete V1 implementation with tool orchestration loop and JSONL journaling. See [CHAT_PARTICIPANT.md](CHAT_PARTICIPANT.md).

---

## Priority Items (Remaining)

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

### 8. Map RootCategory to Filesystem Paths
Create canonical mapping from `RootCategory` to actual filesystem paths. `ROOT_REPO` -> ck3raven source, `ROOT_VSCODE` -> `%APPDATA%\Code\`, etc. This replaces the banned `_root` variables.

### 9. Update Workspace Config to Define Domain Paths
Domain path mappings should come from workspace config (`ck3raven-config.json`), not hardcoded. `ROOT_VSCODE` path, `ROOT_REPO` path, etc. should be configurable.

### 10. Redesign agentView (Tools Sidebar) for Participant Architecture

The current agentView (`views/agentView.ts`) was designed before `@ck3raven` chat participant existed. Now that we have agent-as-participant capabilities, the UI needs to reflect the new architecture:

**Current State:**
- Shows generic "Agent" with mode (ck3lens/ck3raven-dev/none)
- Has "+ Add Sub-agent" button that opens quick-pick + sends init prompt to chat
- Mode status updates when agent calls `ck3_get_mode_instructions`
- No distinction between Copilot Chat itself and participant agents

**Proposed Redesign:**

```
Tools
├── Copilot Chat: connected ✓
│   ├── @ck3raven: initialized (ck3raven-dev)
│   └── @other-participant: not initialized
├── MCP Server: connected (28 tools)
├── Policy Rules: active ✓
└── Instance ID: l4zi-b433ff (click to copy)
```

**Key Changes:**
1. **Show Copilot Chat as parent** - This is the LLM that orchestrates participants
2. **List chat participants as children** - `@ck3raven` and any others under Copilot Chat
3. **Show participant initiation status** - Whether participant has successfully initialized its mode
4. **"+ Add Sub-agent" button** - Consider whether this should now:
   - Initiate a new `@ck3raven` participant session, OR
   - Create a new chat window with init prompt (current behavior)

**Status Derivation Logic:**

| Condition | Display Status |
|-----------|---------------|
| MCP tools registered, mode file shows valid mode | `@ck3raven: initialized ({mode})` |
| MCP tools registered, mode file empty/none | `@ck3raven: awaiting initialization` |
| MCP tools NOT registered | `@ck3raven: ⚠️ MCP server not connected` |
| Init attempted but failed, MCP down | `@ck3raven: ⚠️ Initialization failed - MCP offline` |
| MCP was never connected | `@ck3raven: Enable MCP server to initialize` |

**Implementation Notes:**
- The mode file (`agent_mode_{instanceId}.json`) is the authoritative source for mode
- If init fails, mode file should NOT update (currently it may still change)
- agentView should detect MCP status BEFORE showing mode status
- Failed init should preserve previous status + show warning

### 11. Fix Failed Initialization Not Updating Status Correctly

**Problem:** When agent initialization fails (e.g., MCP server down), the status may still change to the attempted mode even though init didn't complete successfully.

**Root Cause:** The mode file is written by the MCP server's `ck3_get_mode_instructions` tool. If the tool is called and returns successfully, mode is set. But if the MCP server is down, the tool is never called, so mode shouldn't change.

**Observed Issue:** User reports that failed initialization still results in status changing. Need to investigate:
1. Is mode file being written even on failure?
2. Is agentView reading stale mode from a previous session?
3. Is there a race condition between mode file watcher and MCP status check?

**Fix Approach:**
- agentView should validate that MCP is connected BEFORE trusting mode file
- If MCP disconnected, show "MCP offline" regardless of mode file content
- On extension startup, don't trust mode file until MCP connection confirmed

---

## Related Issues (Resolved)

### ~~Broken .disabled Extension Folder~~
~~VS Code Shared process errors on startup:~~
```
Error: Unable to read file 'c:\Users\nateb\.vscode\extensions\ck3lens.ck3lens-explorer-0.1.0.disabled\package.json'
```
**Status:** May need manual deletion if folder exists.

### ~~claude-code Chat Participant Error~~
```
Error: chatParticipant must be declared in package.json: claude-code
```
**Status:** ✅ Fixed - deleted remnant entries from state.vscdb.

---

## Architecture Context

Key files involved:
- `tools/ck3lens_mcp/ck3lens/policy/capability_matrix.py` - Canonical `RootCategory` enum
- `tools/ck3lens_mcp/ck3lens/world_adapter.py` - Uses BANNED parallel systems
- `tools/ck3lens_mcp/ck3lens/policy/enforcement.py` - Token bypass bug
- `tools/compliance/tokens.py` - Canonical token system (NST, LXE only)

---

## Related Documentation

- [CHAT_PARTICIPANT.md](CHAT_PARTICIPANT.md) - @ck3raven participant architecture
- [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) - Core architecture rules
