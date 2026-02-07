# Bug Report: Contract "Hang" — Actually Copilot Turn Termination

**Date**: 2026-02-07  
**Severity**: Medium (systemic UX issue, not a crash)  
**Component**: MCP contract workflow + Copilot agent lifecycle  
**Reported by**: AI agent investigation at user request  

---

## Summary

When the user observes the contract open command "hanging," the MCP server has actually returned successfully in under 40ms. The Copilot agent's turn is being **terminated by VS Code** before it can issue the next tool call (typically a file write). This leaves orphaned open contracts and gives the false appearance of a server-side hang.

## Evidence

### Trace File Analysis

**Instance `l267-57bc15`** (first ck3raven-dev attempt):
| # | Tool Call | Duration | Result |
|---|-----------|----------|--------|
| 1 | session_start | — | — |
| 2 | ck3_get_mode_instructions | 2,231ms | SUCCESS |
| 3 | ck3_contract (open) | 39ms | SUCCESS → `v1-2026-02-07-71e566` |
| 4 | *(nothing)* | — | Turn terminated |

The MCP server **never received** the file write call. The agent's turn was killed between receiving the contract open success and generating the file write tool call.

**Instance `21ft-b28f4c`** (second ck3raven-dev attempt):
| # | Tool Call | Duration | Result |
|---|-----------|----------|--------|
| 1 | ck3_get_mode_instructions | 1,284ms | SUCCESS |
| 2 | ck3_contract (open) | 9ms | SUCCESS → `v1-2026-02-07-345051` |
| 3 | *(4-minute gap)* | — | Turn terminated |
| 4 | ck3_ping (new turn) | — | Server still alive |

Same pattern: contract opens in 9ms, then silence. The next turn (started by the user) found the contract still open and was able to write the file successfully.

### Contract Validation Retries

**Instance `sebn-7a6f5b`** trace shows an agent needing **3 attempts** to open a single contract:
1. Wrong `root_category` → `EN-OPEN-D-001` DENIED
2. Empty `edits` array → `MCP-SYS-E-001` "Mutating operations require edits in work_declaration"
3. Correct parameters → SUCCESS

Each failed attempt generates a large error response that consumes context window budget.

### Orphaned Contract Epidemic

As of this investigation, the contract list shows **22 open (never-closed) contracts** spanning Jan 20 – Feb 7. Many follow the exact pattern: agent opened contract, turn was terminated, contract was never closed. Examples:
- `v1-2026-02-07-71e566` — "Write bug report" (orphaned from first failed attempt above)
- `v1-2026-02-07-b579c6` — "Commit mode instructions refactor" (orphaned)
- `v1-2026-02-07-9f9e21` — "Review recent commits" (orphaned)
- `v1-2026-02-07-b69e88` — "Stage and commit all changes" (orphaned)
- `v1-2026-02-05-8d13c2` — "Remove deprecated paths.resolve()" (orphaned)
- `v1-2026-02-04-50ce30` — "Simplify mcpServerProvider.ts" (orphaned)
- Plus 16 more from Jan 20 – Feb 4

## Root Cause Analysis

### Primary Cause: Context Window Exhaustion

The Copilot agent operates within a fixed context window. After multi-session conversations with summarization, the available budget for generating tool call responses is reduced. The ck3raven-dev workflow is particularly expensive:

1. **`ck3_get_mode_instructions`** — Returns a large payload (instructions text, policy boundaries, session info, database status, db_warning). Takes 1.2–2.2 seconds. This alone consumes significant context.
2. **Contract open** — Requires `intent`, `root_category`, `operations`, `work_declaration` (with `edits` array). The agent must generate all of this before the tool call.
3. **File write** — Must contain the full file content in the tool call parameters.

When (1) + (2) + conversation history exceeds the budget, Copilot terminates the turn after step (2) returns, before step (3) can be generated.

### Contributing Factors

| Factor | Impact |
|--------|--------|
| `mode_instructions` payload size | Large response consumes context budget |
| `mode_instructions` latency (1.2–2.2s) | Suspiciously slow for config + file read |
| Contract validation strictness | Failed attempts waste context on error responses |
| Multi-session conversation buildup | Summarized history still occupies substantial context |
| No batching support | Cannot combine mode init + contract open + file write into one call |
| Large file content in write params | A 13KB bug report must fit entirely in one tool call parameter |

### What This Is NOT

- **NOT** a server-side hang: MCP responses return in 9–39ms
- **NOT** a network issue: The server is reachable (ping succeeds immediately on next turn)
- **NOT** a contract bug: Contract V1 validation works correctly
- **NOT** a timeout: There is no timeout on the agent side — the turn is simply terminated

## Impact

1. **User-visible**: Appears as "hanging" — user waits, nothing happens, then must start a new turn
2. **Orphaned contracts**: 22 open contracts that will never be closed (8-hour expiry saves them)
3. **Lost work**: Agent generates analysis/content but can't write it before termination
4. **Compounding**: Each failed attempt adds to conversation history, making subsequent attempts MORE likely to fail

## Recommended Mitigations

### Short-term (reduce context pressure)

1. **Slim down `mode_instructions` response**: The agent only needs a mode confirmation + policy hash on subsequent calls. Full instructions should be returned only once per session, not on every mode switch.

2. **Contract open shorthand**: Support a simplified contract open that infers `work_declaration` from a template or accepts a minimal form for documentation-only writes.

3. **Contract auto-close on session end**: When the MCP server detects a new session_start without the previous contract being closed, auto-close or cancel the previous contract.

### Medium-term (architectural)

4. **Batch tool call**: Combine `mode_init + contract_open + file_write + contract_close` into a single compound tool call for simple write operations.

5. **Resume-aware contracts**: When a new turn opens and finds an already-open contract, allow the agent to continue using it without re-opening.

### Long-term

6. **Contract garbage collection**: Periodic sweep of open contracts older than N hours, auto-cancel with "agent_turn_terminated" reason.

7. **Telemetry**: Track tool-call-initiated vs tool-call-completed ratio to detect systematic turn terminations.

---

## Reproduction

1. Start a fresh VS Code session
2. Have a long multi-session conversation (3+ summarizations) in ck3lens mode
3. Switch to ck3raven-dev mode (requires mode_instructions + contract open)
4. Attempt to write a large file (10KB+)
5. Observe: contract opens successfully but file write never executes

## Related

- [bug_qbuilder_subprocess_import_chain.md](bug_qbuilder_subprocess_import_chain.md) — The investigation that triggered this discovery
