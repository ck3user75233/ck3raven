# Single-Writer Architecture — Completion Plan

> **Date:** February 22, 2026  
> **Status:** Plan — Ready for review  
> **Scope:** Close remaining violations, make multi-instance safe  
> **Related docs:** `docs/SINGLE_WRITER_ARCHITECTURE.md`, `docs/CANONICAL_ARCHITECTURE.md §14`

---

## Part 1: What `cleanupDatabaseState` Was (Python Side)

The extension.ts function is gone, but the Python code it called still exists in two places:

| Location | Status | What it does |
|----------|--------|-------------|
| `archive/old_builder/db_health.py` | **DEAD** — archived, never imported | `check_and_recover()`: WAL checkpoint, stale lock file cleanup |
| `qbuilder/api.py` L640 | **LIVE but uncalled** — no imports found | `check_and_recover()`: WAL checkpoint (>50MB), reset stale `build_queue` items |

The `qbuilder/api.py` version is better written — it resets stale `processing` items and checkpoints WAL. But nobody calls it. The archived one is a predecessor that imported `builder.db_health` (the path the extension used to call via Python subprocess).

**Both can stay as-is.** The `qbuilder/api.py` version is useful when wired into the daemon's own shutdown path — it just isn't being called from the extension anymore (which is correct, the extension shouldn't be doing this).

---

## Part 2: Document Review — Docs vs. Reality

### `docs/SINGLE_WRITER_ARCHITECTURE.md` (360 lines, Jan 17 2026)

| Claim in doc | Reality | Gap |
|-------------|---------|-----|
| "MCP processes must connect using `mode=ro`" | `db_queries.py` does open with `?mode=ro` when `read_only=True` | **PARTIAL** — `db_api.py` passes `read_only=True`, but `_get_db()` in server.py returns the same object, and `ck3_db_delete` calls `_get_db()` returning a `DBQueries` opened via `db_api._get_db()` which IS read-only. Yet `_ck3_db_delete_internal` successfully executes DELETE on it. |
| "File writes do not imply DB writes. MCP calls `notify_file_changed`" | `unified_tools.py` `_refresh_file_in_db_internal` does this correctly via `daemon_client.py` | **MATCHES** |
| "IPC client at `daemon_client.py`" | `daemon_client.py` exists, is a singleton, used by MCP tools | **MATCHES** |
| "Read-only DB API at `db_api.py`" | `db_api.py` exists, enforces read-only | **MATCHES** |
| IPC methods: health, enqueue_files, enqueue_scan, await_idle, get_status, shutdown | `ipc_server.py` implements all 6 | **MATCHES** |
| "Multiple VS Code windows can coexist safely" | **FALSE** — IPC port file at `%TEMP%\ck3lens_ipc_port` is last-writer-wins, and `ck3_db_delete` bypasses read-only | **MAJOR GAP** |
| Writer lock prevents duplicate daemons | `writer_lock.py` works correctly with OS-level locking | **MATCHES** |

### Major gap: `ck3_db_delete` violates single-writer

The doc says "No MCP tool may execute INSERT/UPDATE/DELETE." But `_ck3_db_delete_internal` in `server.py` L1087-1360 does exactly this — it gets a `DBQueries` instance and runs `DELETE FROM` + `commit()` directly. The code has a comment saying "this bypasses normal enforcement" but there's a deeper issue: **how does it succeed if the connection is `mode=ro`?**

Looking closely: `db_api._get_db()` creates `DBQueries(read_only=True)`. But `_get_db()` in `server.py` also calls `db_api._get_db()`. The `DBQueries` constructor uses `file:{path}?mode=ro` when `read_only=True`. So `ck3_db_delete` should fail on a truly read-only connection...

**Unless** the connection was opened BEFORE `db_api` was refactored to enforce `read_only=True`. The cached `_db` global in server.py may have been created with an old connection. This needs testing — it may already be broken (deletes silently failing), or the global may have been initialized before `read_only` was added.

### `docs/CANONICAL_ARCHITECTURE.md §14`

| Claim | Reality | Gap |
|-------|---------|-----|
| "Non-Negotiable: No MCP tool may execute INSERT/UPDATE/DELETE" | `ck3_db_delete` does exactly this | **VIOLATION** |
| File locations table matches | All paths exist | **MATCHES** |

### Qbuilder docs

| Doc | Status |
|-----|--------|
| `docs/qbuilder_routing_table.md` | Accurate — matches `routing_table.json` |
| `docs/bugs/qbuilder_implementation_plan.md` | Describes subprocess performance fix (Feb 2026) — historical, accurate |
| `docs/Requests and Reports/qbuilder-status-enhancement.md` | Request doc — describes RunActivity feature that IS implemented |

### Documentation gaps summary

1. **`ck3_db_delete` is undocumented as an exception** to single-writer — the doc says "no exceptions" but the code has one
2. **Multi-window IPC collision** is not mentioned anywhere — the doc claims multi-window works but the IPC port file is a single global
3. **No mention of `_auto_start_daemon`** — `unified_tools.py` auto-spawns the daemon, which is not in any doc
4. **No doc for the diagnosticsServer IPC** (extension→MCP) — separate from daemon IPC but uses the same port file namespace

---

## Part 3: Complete Inventory of Writer Touchpoints

### A. Daemon (qbuilder) — LEGITIMATE writer

| Component | What it writes | Where |
|-----------|---------------|-------|
| `qbuilder/worker.py` | build_queue updates, asts, symbols, refs, lookups, files | Main build loop |
| `qbuilder/ipc_server.py` L222 | `_get_handler_write_conn()` — handles enqueue_scan which writes discovery_queue + build_queue | IPC handler thread |
| `qbuilder/api.py` L81 | `enqueue_file()` — writes build_queue rows | Called by IPC and CLI |
| `qbuilder/api.py` L640 | `check_and_recover()` — WAL checkpoint, stale reset | Uncalled currently |
| `qbuilder/discovery.py` | Writes discovery_queue, build_queue entries | Called by daemon |
| `qbuilder/schema.py` | Creates qbuilder tables | Init only |

### B. MCP server — SHOULD BE read-only

| Component | What it does | Violation? |
|-----------|-------------|-----------|
| `tools/ck3lens_mcp/ck3lens/db_api.py` | Opens `mode=ro`, rejects writes | **CORRECT** |
| `tools/ck3lens_mcp/ck3lens/db_queries.py` L163 | Opens `mode=ro` when `read_only=True` | **CORRECT** |
| `tools/ck3lens_mcp/server.py` `_ck3_db_delete_internal` L1087 | Executes DELETE + commit via `_get_db().conn` | **VIOLATION** — maintenance exception |
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` `_refresh_file_in_db_internal` L1640 | Notifies daemon via IPC, does NOT write DB | **CORRECT** |
| `tools/ck3lens_mcp/ck3lens/daemon_client.py` | TCP client to daemon IPC | **CORRECT** |

### C. Extension (TypeScript) — No DB writes remain

| Component | Status |
|-----------|--------|
| `cleanupDatabaseState` | **DELETED** from source. Still in compiled `out/extension.js` (stale build). |
| `diagnosticsServer` | Writes to `%TEMP%\ck3lens_ipc_port` — file I/O, not DB | **Port collision risk** |

### D. Shared resources with multi-window collision risk

| Resource | Location | Risk |
|----------|----------|------|
| IPC port file | `%TEMP%\ck3lens_ipc_port` | **HIGH** — last window to start overwrites, other window's MCP points to wrong diagnostics server |
| Writer lock | `~/.ck3raven/ck3raven.db.writer.lock` | **LOW** — OS locking correctly prevents 2 daemons |
| SQLite WAL | `~/.ck3raven/ck3raven.db-wal` | **LOW** with single daemon writer, **HIGH** if `ck3_db_delete` bypasses read-only |
| Agent mode files | `~/.ck3raven/agent_mode_*.json` | **LOW** — keyed by instance ID |
| Log files | `~/.ck3raven/logs/*.log` | **LOW** — interleaved but not corrupting |

---

## Part 4: Single-Writer Completion Plan

### Current state: 80% implemented

The architecture is mostly in place. What's missing is **closing the last violation** (`ck3_db_delete`) and **making multi-instance safe**.

### Phase 1: Close `ck3_db_delete` violation (LOW RISK)

**Problem:** `ck3_db_delete` writes directly to the DB from the MCP server.

**Solution:** Route `ck3_db_delete` operations through a new daemon IPC method.

**New daemon IPC method: `db_delete`**

```python
# In ipc_server.py, add handler:
def _handle_db_delete(self, request: IPCRequest) -> dict:
    """Handle database deletion requests from MCP clients."""
    target = request.params.get("target")
    scope = request.params.get("scope", "all")
    ids = request.params.get("ids")
    content_version_ids = request.params.get("content_version_ids")
    confirm = request.params.get("confirm", False)
    
    # Use write connection for deletions
    write_conn = self._get_handler_write_conn()
    try:
        # Reuse existing internal logic (moved from server.py)
        result = _db_delete_internal(write_conn, target, scope, ids, 
                                      content_version_ids, confirm)
        return result
    finally:
        write_conn.close()
```

**In MCP server.py:** Replace direct DB writes with:
```python
result = daemon.send_request("db_delete", {
    "target": target, "scope": scope, "confirm": confirm, ...
})
```

**Risk mitigation:** Build this as a new IPC method only. The existing `_ck3_db_delete_internal` stays as fallback (with a `# BUG: violates single-writer` comment) until the IPC path is proven. Switchover is a one-line change.

**Multi-instance impact:** None new — daemon is already singleton. Multiple MCP instances calling `db_delete` via IPC serialize naturally through the daemon.

### Phase 2: Instance-aware IPC port file (MEDIUM RISK)

**Problem:** `%TEMP%\ck3lens_ipc_port` is global — two windows overwrite each other.

**Solution:** Instance-keyed port files.

```
%TEMP%\ck3lens_ipc_port_{instanceId}    # per-window diagnostics
```

The diagnosticsServer already knows the instance ID. Change `writePortFile()` in `diagnosticsServer.ts` L191 to include instance ID in the filename. Change the MCP-side reader to discover by instance ID (passed as environment variable when MCP server starts).

**Multi-instance impact:** Each window's MCP server finds its own diagnostics port. No collision.

**Risk:** Low — only affects diagnostics IPC, not the daemon.

### Phase 3: Daemon lifecycle for multi-window (LOW RISK)

**Current behavior:** Each MCP instance calls `_auto_start_daemon()` if daemon isn't running. Writer lock correctly prevents duplicate daemons. First one wins, others connect as IPC clients.

**What works already:**
- Writer lock (OS-level, correct)
- Multiple MCP instances can IPC to one daemon (TCP socket, no per-instance state needed)
- Daemon serves all requests regardless of which MCP instance sent them

**What needs attention for 3-4 instances:**
1. **Daemon shutdown lifecycle** — currently `ck3_qbuilder(command="stop")` from any window kills the daemon for all. Need either:
   - Reference counting (daemon tracks connected clients, shuts down when last disconnects)
   - OR: daemon stays alive until explicit stop or system shutdown (preferred — it's cheap)
   
2. **IPC connection pooling** — `daemon_client.py` opens a new TCP socket per request. With 3-4 instances doing concurrent reads + file change notifications, this is fine for now (connections are short-lived). If it becomes a bottleneck, add persistent connections later.

3. **Queue priority from multiple instances** — Currently all flash updates are `priority=1`. If two agents from different windows both enqueue high-priority work, there's no instance-aware prioritization. The queue is FIFO within priority level, which is correct — agents shouldn't step on each other's work.

**New functionality needed:**

| Feature | Why | Implementation |
|---------|-----|----------------|
| `instance_id` in IPC requests | Logging/debugging which window requested what | Add optional field to `IPCRequest.params`, log it in daemon |
| Daemon stays alive policy | Don't let one window's stop kill another's | Add `--keep-alive` mode that ignores shutdown IPC; use task manager / `ck3_qbuilder(command="stop", force=True)` for real stops |
| Health with instance listing | See which MCP instances are connected | Track recent client IPs/request counts in `RunActivity` |

### Phase 4: Risk Management Strategy

Following the WA2/EN-V2 pattern of building copies to avoid taking down live tools:

**Approach: Incremental IPC method additions (NOT a full qbuilder rewrite)**

Unlike WA/EN where we created `world_adapter_v2.py` and `enforcement_v2.py` as parallel modules, the qbuilder daemon doesn't need a full v2. The changes are:

1. **Add IPC methods** — `db_delete`, `notify_instance` (new methods DON'T affect existing ones)
2. **Move `_ck3_db_delete_internal` behind an IPC gate** — switchover is a single conditional:

```python
# In server.py ck3_db_delete:
if daemon.is_available():
    # Phase 1: Route through daemon (new path)
    result = daemon.send_request("db_delete", params)
else:
    # Fallback: direct DB write (existing path, deprecated)
    result = _ck3_db_delete_internal(...)
```

3. **Port file change** is purely additive (new filename format, old code still works)

**Risk assessment:**

| Change | Risk to MCP | Mitigation |
|--------|------------|------------|
| New IPC methods on daemon | Zero — additive only | Test methods individually before wiring MCP |
| `ck3_db_delete` routing | Low — fallback to existing code | Feature flag: `daemon.is_available()` |
| Port file instance-keying | Low — only affects diagnostics | Can revert filename format without data loss |
| Daemon keep-alive policy | Low — behavioral only | Default to keep-alive, opt-in stop |

**What we should NOT do:**
- Do NOT create `qbuilder_v2/` — the daemon architecture is correct, we're just closing gaps
- Do NOT rewrite `ipc_server.py` — add methods to it
- Do NOT change the DB schema — no migration risk
- Do NOT change the writer lock mechanism — it works

### Execution order

1. Add `db_delete` IPC method to `ipc_server.py` (daemon side)
2. Add `db_delete` to `daemon_client.py` (client side)
3. Wire `ck3_db_delete` to use IPC when available, fallback to direct
4. Instance-key the port file
5. Add daemon keep-alive behavior
6. Comment-annotate all resolved touchpoints

Each step is independently deployable and testable. No step breaks the MCP server if it fails.



2: PowerShell Extension (ck3raven)
Good — sign_script_for_contract DOES exist. Let me dig deeper into the remaining pieces.

Now let me check the remaining pieces — the OPERATIONS_MATRIX entry for exec, leak scanning, script path WA2 resolution, and the test results.

Now let me check where the human trigger for signing would come from (extension side) and check what tests exist overall:

Let me also quickly check the enforcement_v2 enforce function and see how it handles ck3_exec:

Now let me check the test results file and any enforcement tests for ck3_exec:

Here's the full status assessment of ck3_exec against the Migration Policy:

ck3_exec — Current State (Feb 22, 2026)
What IS working
Requirement	Status	Evidence
WA2 resolution for working_dir	DONE	server.py:4075-4085 — wa2.resolve() called, defaults to root:ck3raven_data/wip
enforce() v2 integration	DONE	server.py:4115-4123 — calls enforce() with mode, tool, root_key, subdirectory, context kwargs
OPERATIONS_MATRIX gating	DONE	capability_matrix_v2.py:519-523 — EXEC_COMMANDS rule exists at ("*", "ck3raven_data", "wip") only, with _EXEC_GATE condition
exec_gate() condition predicate	DONE	capability_matrix_v2.py:142-197 — 3-branch decision tree: whitelist → script signing → deny
_is_command_whitelisted() function	DONE	capability_matrix_v2.py:252-261 — prefix matching against whitelist
_load_command_whitelist() loader	DONE	capability_matrix_v2.py:215-250 — reads command_whitelist.json, caches
command_whitelist.json file	EXISTS	command_whitelist.json — but "commands": [] (empty list)
sign_script_for_contract() signer	EXISTS	contract_v1.py:506-552 — produces HMAC-signed dict, stores on contract
validate_script_signature() verifier	EXISTS	contract_v1.py:556-598 — checks HMAC against contract_id + path + hash
_detect_script_path() helper	DONE	server.py:4009-4041 — extracts script path from python <path> commands
Unit tests (22 pass)	ALL GREEN	test_script_signing.py — sign/verify round trip, tamper detection, cross-contract forgery, exec_gate integration — 22/22 passed
What is NOT working / NOT hooked up
Requirement	Status	Gap
§1 Inline ban	HALF-DONE	Whitelist machinery exists but commands: [] is empty. This means _is_command_whitelisted() always returns false. The policy doc says "only python <path> is allowed" — that pattern needs to be added. However, the empty whitelist combined with exec_gate branch 3 means non-script commands are currently denied anyway (correct by accident).
§2 Script path resolution via WA2	NOT DONE	Only working_dir is resolved via WA2 (server.py L4075-4085). The script path itself (extracted by _detect_script_path) is a raw host-absolute path that never goes through wa2.resolve(). Enforcement receives the working_dir's root_key/subdirectory, not the script's. If the script is elsewhere, this is wrong.
§3 Human approval trigger (signer UI)	NOT IMPLEMENTED	sign_script_for_contract() exists in Python, but nothing calls it. No extension UI button, no MCP tool exposes it to humans. There is no way to actually sign a script. The verifier will always fail because contract.script_signature is always None.
§5 Leak scanning on output	NOT DONE	_ck3_exec_internal returns stdout/stderr in raw dict without running check_no_host_paths(). The leak detector exists (leak_detector.py) and is used by ck3_dir, but is not wired into ck3_exec.
§7 Return type normalization	NOT DONE	_ck3_exec_internal return type is [Reply
Practical consequence right now
Due to the gaps, ck3_exec currently:

Cannot execute anything in practice — the whitelist is empty AND no script can be signed (no signer UI), so exec_gate() always returns False → enforce() denies everything. The tool is effectively dead.
If the whitelist were populated (e.g., with "python"), script execution would proceed but without HMAC verification — because _detect_script_path returns a host path, but nobody ever called sign_script_for_contract to populate contract.script_signature.
What needs to happen to complete the migration
Tier 1 — Make it functional again (minimum viable):

Populate the whitelist — Add "python" to command_whitelist.json so python <path> commands pass the fast-path in exec_gate. This restores basic functionality.
Resolve script path via WA2 — After _detect_script_path, resolve the detected script path through wa2.resolve() → get the script's root_key/subdirectory. This ensures enforcement gets the right coordinates (script must be in wip).
Return type normalization — Convert all dict-returning paths in _ck3_exec_internal to Reply.
Leak-scan output — Add check_no_host_paths() to stdout/stderr before returning.
Tier 2 — Complete signing pipeline (deferred):

Wire up sign_script_for_contract — Either expose via an MCP tool (ck3_exec with a sign subcommand?) or via extension UI. The policy doc says this needs a Sigil-based mechanism with human button click, NOT the HAT system, and NOT the shield-click.
Extension UI for approval — A distinct button that triggers signing. Per the policy doc: "Previous attempts to extend shield-click for other purposes caused crashes."
Test coverage summary
Area	Tests	Status
Sign/verify round trip	2 tests	PASS
Content hash mismatch	4 tests	PASS
Path mismatch	2 tests	PASS
Missing signature	3 tests	PASS
Contract state guards	2 tests	PASS
Sigil unavailable	2 tests	PASS
Cross-contract forgery	1 test	PASS
exec_gate integration	6 tests	PASS
Integration test of full _ck3_exec_internal	0 tests	MISSING
Leak scanning on exec output	0 tests	MISSING
Script path WA2 resolution	0 tests	MISSING
Whitelist with python entry	0 tests	MISSING
Bottom line: The building blocks are solid and well-tested (22/22 green), but they're not connected to each other. The tool is currently a no-op because the signing trigger doesn't exist and the whitelist is empty.

> test_script_signing.py — sign/verify round trip, tamper detection, cross-contract forgery, exec_gate inte

I am really questioning this now, how was the human 

> whitelisting

I have given direction several times around this and I would like it to be captured, finally. I want the git commands, the qbuilder, the linters and if there are any other regular processes that part of our operational work and executed with in-line python, you can recommend those to me

Well I think your gap assessment is really good and I want you to add it to the markdown you created that is now placed in /docs/ , such that a server crash will not cause us to lose all this pre work.

I would demote the leak scan output to deferred - this doesn't matter at all while the overall refactor is only a tiny % complete  ... the agents will see plenty of host paths until all the mcp tools are refactored.

our tests are poorly designed if they are passing 22/22, I suggest before entering into the coding you recommend an extended set of tests.