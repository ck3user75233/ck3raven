# HAT via IPC — Implementation Plan

> **Status:** PENDING REVIEW  
> **Authority:** [SIGIL_ARCHITECTURE.md](SIGIL_ARCHITECTURE.md) §6 (Protected Files & HAT)  
> **Replaces:** `PROTECTED_FILES_AND_HAT_IMPLEMENTATION_PLAN.md` (stale, file-based design)  
> **Estimated Phases:** 4 sequential phases  
> **Rule:** No code until this plan is approved.

---

## Context

### What's Done

All foundational infrastructure is complete:

| Component | Status | File(s) |
|-----------|--------|---------|
| Sigil module | Done | `tools/compliance/sigil.py` |
| Mode init (inline token) | Done | `agentView.ts`, `server.py` |
| Contract signing | Done | `contract_v1.py` |
| Protected files manifest | Done | `policy/protected_files.json` |
| Protected files module | Done | `tools/compliance/protected_files.py` |
| `ck3_protect` tool | Done | `server.py` |
| Git pre-commit hook | Done | `tools/compliance/install_hooks.py` |

### What Remains

One feature: **HAT via IPC**. The current file-based handshake (`hat_request.json` / `hat_approval.json`) must be replaced with a synchronous IPC call to the extension via the existing `DiagnosticsServer` (JSON-RPC over TCP).

### Architectural Decision (from SIGIL_ARCHITECTURE.md §6.3)

```
Agent calls open_contract() → Server detects protected paths →
Server calls extension via IPC "approveContract" → Extension shows modal dialog →
User approves/declines → Extension signs contract identity payload →
Returns via IPC → Server saves contract → Returns single Reply to agent
```

No files. No retry. No polling. One synchronous call.

---

## Phase 1: Extension Side — `approveContract` IPC Method

**Goal:** Add a new JSON-RPC method to `DiagnosticsServer` that shows a modal approval dialog and signs the contract if approved.

### 1.1 Access to Sigil Secret

The `DiagnosticsServer` currently does not have access to the Sigil secret. It needs it to sign the contract identity payload on approval.

| Edit | File | What |
|------|------|------|
| 1a | `diagnosticsServer.ts` constructor | Accept optional `getSigilSecret?: () => string \| undefined` callback parameter |
| 1b | `extension.ts` ~line 384 | Pass `getSigilSecret` callback when constructing `DiagnosticsServer`. The `activate()` function already has access to `mcpProvider.sigilSecret` (or equivalent). Wire it through. |

**Note:** The existing `mintHat` method in `agentView.ts` already uses `this.getSigilSecret?.()` — the same pattern, just relocated to `DiagnosticsServer`.

### 1.2 Register `approveContract` Method

| Edit | File | What |
|------|------|------|
| 1c | `diagnosticsServer.ts` handleRequest() | Add `case 'approveContract':` to the method dispatch switch (~line 297). Call `this.approveContract(params)`. |

### 1.3 Implement `approveContract`

| Edit | File | What |
|------|------|------|
| 1d | `diagnosticsServer.ts` | New private method `approveContract(params)`. |

**Method signature:**
```typescript
private async approveContract(params: {
    contract_id: string;
    intent: string;
    protected_paths: string[];
    root_category: string;
    created_at: string;
}): Promise<{ approved: boolean; signature?: string }>
```

**Implementation:**
1. Validate all required params present
2. Build modal dialog message showing intent + protected paths
3. `vscode.window.showWarningMessage(message, { modal: true }, 'Approve')`
4. If user clicks Approve:
   a. Compute payload: `contract:{contract_id}|{created_at}` (per SI-E2/SI-E3)
   b. HMAC-SHA256 with Sigil secret → hex signature
   c. Return `{ approved: true, signature: "<hex>" }`
5. If user declines or dismisses:
   a. Return `{ approved: false }`

**Key detail:** The signing payload is `contract:{contract_id}|{created_at}` — the same format used by `_contract_signing_payload()` in `contract_v1.py`. This is per SIGIL_ARCHITECTURE.md §6.6 and invariant SI-E3.

### 1.4 Timeout Handling

The IPC server already handles socket timeouts at the TCP level. For the modal dialog, `showWarningMessage` resolves when the user acts (no built-in timeout). The 120-second timeout (per §3.7) is enforced **by the Python client** (Phase 2), not by the extension.

### 1.5 Verification (Manual)

- Start extension, verify DiagnosticsServer starts on port 9847
- Send raw JSON-RPC `approveContract` request via netcat/telnet
- Verify modal dialog appears
- Verify approve returns `{ approved: true, signature: "..." }`
- Verify decline returns `{ approved: false }`
- Verify signature matches the expected HMAC of `contract:{id}|{created_at}`

---

## Phase 2: Python Side — IPC in `open_contract()`

**Goal:** Replace the file-based HAT block in `contract_v1.py` with an IPC call to the extension.

### 2.1 Add `request_hat_approval` to IPC Client

| Edit | File | What |
|------|------|------|
| 2a | `ipc_client.py` | New method `request_hat_approval(contract_id, intent, protected_paths, root_category, created_at) -> dict`. Calls `_send_request("approveContract", ...)`. |
| 2b | `ipc_client.py` | This method MUST create a new client with `timeout=120.0` (per §3.7), not use the default 10s timeout. Either accept a timeout parameter or use a HAT-specific default. |

**Return value:** `{"approved": True/False, "signature": "..."}` or raises `VSCodeIPCError`.

### 2.2 Replace HAT Block in `open_contract()`

| Edit | File | Lines | What |
|------|------|-------|------|
| 2c | `contract_v1.py` | ~676-706 | **Replace** the entire file-based HAT block |

**Current code (lines ~676-706):**
```python
if protected_hit:
    try:
        from tools.compliance.tokens import consume_hat_approval, write_hat_request
    except ImportError:
        raise ValueError("...")
    valid, msg = consume_hat_approval(required_paths=protected_hit)
    if not valid:
        write_hat_request(intent=..., protected_paths=..., root_category=...)
        raise ValueError("PROTECTED FILE GATE: ... Click the shield icon ... retry.")
```

**New code (conceptual):**
```python
if protected_hit:
    # Generate contract ID early (needed for IPC signing)
    contract_id = ContractV1.generate_id()
    created_at = datetime.now().isoformat()

    try:
        from ck3lens.ipc_client import VSCodeIPCClient, VSCodeIPCError
        with VSCodeIPCClient(timeout=120.0) as client:
            result = client.request_hat_approval(
                contract_id=contract_id,
                intent=intent,
                protected_paths=protected_hit,
                root_category=str(root_category),
                created_at=created_at,
            )
    except (VSCodeIPCError, Exception) as e:
        # IPC failed — per SI-E6, return informational, don't open
        raise ValueError(
            f"PROTECTED FILE GATE: Cannot reach extension for HAT approval ({e}). "
            f"Ensure CK3 Lens is active in VS Code."
        )

    if not result.get("approved"):
        raise ValueError(
            f"PROTECTED FILE GATE: User declined approval for protected files: {protected_hit}"
        )

    # User approved — extension signed the contract identity
    hat_signature = result.get("signature", "")
    # Contract will be created with this pre-assigned ID and signature
```

**Important sequence change:** The contract ID and `created_at` must be generated **before** the IPC call (because the extension needs them to compute the signing payload). The `ContractV1.generate_id()` call and `datetime.now().isoformat()` move above the HAT check. The contract is then created with these pre-assigned values.

### 2.3 Pass Pre-Signed Signature to Contract

| Edit | File | What |
|------|------|------|
| 2d | `contract_v1.py` open_contract() | When HAT was used, pass the extension-provided signature to `save_contract()` instead of letting `save_contract()` sign it server-side. Add an optional `presigned_signature` parameter to `save_contract()`, or set `contract.session_signature` before calling save. |

The simplest approach: set `contract.session_signature = hat_signature` before `save_contract()`, and have `save_contract()` skip signing if `session_signature` is already set.

### 2.4 Restructure Contract ID Generation

Currently, `contract_id = ContractV1.generate_id()` happens after the HAT check (~line 715). For HAT contracts, it must happen before (for the signing payload). The restructure:

```python
# Generate contract ID early (always — needed for HAT signing if applicable)
contract_id = ContractV1.generate_id()
created_at = datetime.now().isoformat()

# HAT gate (uses contract_id + created_at for signing)
hat_signature = None
if protected_hit:
    # ... IPC call ...
    hat_signature = result.get("signature")

# Create contract with pre-generated ID
contract = ContractV1(contract_id=contract_id, created_at=created_at, ...)
if hat_signature:
    contract.session_signature = hat_signature
save_contract(contract)  # skips signing if session_signature already set
```

### 2.5 Verification

- Unit test: `open_contract()` with protected edits, IPC returns approved → contract opens, signature set
- Unit test: `open_contract()` with protected edits, IPC returns declined → ValueError with "declined"
- Unit test: `open_contract()` with protected edits, IPC unreachable → ValueError with "Cannot reach extension"
- Unit test: `open_contract()` with non-protected edits → normal flow, no IPC call
- Signature verification: `load_contract()` successfully verifies extension-signed contracts

---

## Phase 3: Python Side — IPC in `ck3_protect`

**Goal:** Replace file-based HAT in the `ck3_protect` tool's `add` and `remove` commands.

### 3.1 `ck3_protect` Add Command

| Edit | File | Lines | What |
|------|------|-------|------|
| 3a | `server.py` | ~4477-4490 | Replace `consume_hat_approval`/`write_hat_request` with IPC call |

The `add` command doesn't create a contract, so we need a slightly different IPC pattern. Options:

**Option A:** The `ck3_protect` tool opens a mini-contract internally for the manifest edit, and HAT approves that contract. This is clean but adds overhead.

**Option B:** The IPC call uses a synthetic contract ID (e.g., `protect-add-{timestamp}`) just for the signing payload. The response signature is verified locally but not stored in a contract.

**Option C:** The IPC `approveContract` method is used with a well-known synthetic ID. The server verifies the returned signature against the payload and then discards it. The point of the signature is to prove the human clicked Approve in the current session, not to store it.

**Recommended: Option C.** The `ck3_protect` tool generates a synthetic payload `protect:{action}|{path}|{timestamp}`, calls `approveContract` with these fields, verifies the returned signature, and proceeds if valid. This requires a small extension to the IPC method to accept a custom payload prefix, OR we reuse the contract format with a synthetic ID.

**Simplest approach:** Use `approveContract` with a synthetic `contract_id` like `protect-{uuid}` and `created_at` of now. The extension signs `contract:protect-{uuid}|{created_at}`, server verifies, then discards. No contract file is created.

### 3.2 `ck3_protect` Remove Command

| Edit | File | Lines | What |
|------|------|-------|------|
| 3b | `server.py` | ~4545-4556 | Same pattern as 3.1 — replace file-based HAT with IPC call |

### 3.3 Extract Shared Helper

| Edit | File | What |
|------|------|------|
| 3c | `server.py` or new `hat_ipc.py` | Extract a shared function `require_hat_approval(intent, protected_paths, root_category) -> str` that: (1) generates synthetic contract ID, (2) makes IPC call, (3) verifies response, (4) returns signature or raises. Used by both `ck3_protect` and `open_contract()`. |

This helper prevents code duplication between Phase 2 and Phase 3 callers.

### 3.4 Verification

- `ck3_protect(command="add", path="test.md", reason="test")` → shows approval dialog → approved → entry added
- `ck3_protect(command="add", ...)` → declined → Reply(I) with "requires_hat"
- `ck3_protect(command="remove", ...)` → same flow
- IPC down → Reply(I) with "Cannot reach extension"

---

## Phase 4: Cleanup — Remove Deprecated File-Based HAT

**Goal:** Delete all file-based HAT handshake code. This is safe only after Phases 1-3 are working.

### 4.1 Python: `tokens.py`

| Edit | File | Lines | What |
|------|------|-------|------|
| 4a | `tokens.py` | ~646-785 | **Delete** the entire HAT section: module-level comment block, `HAT_CONFIG_DIR`, `HAT_REQUEST_PATH`, `HAT_APPROVAL_PATH`, `write_hat_request()`, `consume_hat_approval()` |

### 4.2 TypeScript: `agentView.ts`

| Edit | File | Lines | What |
|------|------|-------|------|
| 4b | `agentView.ts` | ~995-998 | **Delete** command registration for `ck3lens.agent.mintHat` |
| 4c | `agentView.ts` | ~1003-1121 | **Delete** the `mintHat()` method entirely |

### 4.3 Extension Manifest: `package.json`

| Edit | File | Lines | What |
|------|------|-------|------|
| 4d | `package.json` | ~431-435 | **Delete** the `ck3lens.agent.mintHat` command contribution |
| 4e | `package.json` | ~504-508 | **Delete** the `ck3lens.agent.mintHat` view/title menu entry |

### 4.4 Delete Stale Plan

| Edit | File | What |
|------|------|------|
| 4f | `docs/PROTECTED_FILES_AND_HAT_IMPLEMENTATION_PLAN.md` | **Delete** file entirely (replaced by this document) |

### 4.5 Verification

- `grep -rn "hat_request\|hat_approval\|consume_hat\|write_hat\|mintHat" tools/` → zero hits (excluding docs/archives)
- Extension compiles (`npm run compile`)
- All Python tests pass
- VSIX builds

---

## Dependency Graph

```
Phase 1 (Extension IPC method)
    ↓
Phase 2 (Python: open_contract IPC)  ←── Phase 3 (Python: ck3_protect IPC)
    ↓                                         ↓
    └──────────── Phase 4 (Cleanup deprecated code) ──────────────┘
```

Phase 2 and Phase 3 can run in parallel once Phase 1 is done. They share a common helper (Phase 3.3) which should be extracted first.

Phase 4 depends on both Phase 2 and Phase 3 being verified.

---

## Files Modified/Created Summary

| Phase | File | Action |
|-------|------|--------|
| 1 | `tools/ck3lens-explorer/src/ipc/diagnosticsServer.ts` | Edit — add `approveContract` method, accept Sigil secret callback |
| 1 | `tools/ck3lens-explorer/src/extension.ts` | Edit — pass Sigil secret accessor to DiagnosticsServer constructor |
| 2 | `tools/ck3lens_mcp/ck3lens/ipc_client.py` | Edit — add `request_hat_approval()` method |
| 2 | `tools/ck3lens_mcp/ck3lens/policy/contract_v1.py` | Edit — replace file-based HAT block with IPC call, restructure ID generation |
| 3 | `tools/ck3lens_mcp/server.py` | Edit — replace file-based HAT in `ck3_protect` add/remove |
| 3 | `tools/ck3lens_mcp/ck3lens/hat_ipc.py` (new) | Create — shared HAT IPC helper |
| 4 | `tools/compliance/tokens.py` | Edit — delete HAT section (~140 lines) |
| 4 | `tools/ck3lens-explorer/src/views/agentView.ts` | Edit — delete `mintHat()` + command registration |
| 4 | `tools/ck3lens-explorer/package.json` | Edit — delete `mintHat` command contributions |
| 4 | `docs/PROTECTED_FILES_AND_HAT_IMPLEMENTATION_PLAN.md` | Delete |

---

## Out of Scope

- **Changing the DiagnosticsServer protocol** — reuses existing JSON-RPC over TCP, newline-delimited
- **Adding new IPC port or server** — reuses existing port 9847 discovery
- **Contract V1 schema changes** — no new fields. `session_signature` already exists.
- **Protected files list changes** — manifest remains the same 3 files
- **WIP workspace** — excluded from protection (unchanged)
- **Acceptance tests** — deferred to post-implementation (per user directive)
- **Extension sidebar UI changes** — the shield icon/button is removed (Phase 4), replaced by the modal dialog that appears automatically via IPC

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| DiagnosticsServer not running when HAT needed | Reply(I) with clear message. User must have CK3 Lens extension active. Same requirement as for all IPC tools. |
| Modal dialog blocks extension thread | `showWarningMessage` is async, does not block the event loop. Other IPC methods continue to work. |
| Python socket timeout (120s) too long | Configurable via constant. User can dismiss dialog at any time (resolves immediately). |
| Port file stale / wrong port | Existing zombie cleanup handles this. Port file TTL is 300s. |
| Extension restarts mid-approval | IPC socket drops → Python catches exception → Reply(I). Agent retries. |
| `contract_id` generated before contract saved | Acceptable — ID is a UUID, uniqueness is guaranteed regardless of save order. |

---

## Invariant Compliance Checklist

| Invariant | Addressed In |
|-----------|-------------|
| SI-A3 (All signing through sigil.py API) | Phase 1.3: Extension uses HMAC with Sigil secret directly. Python side uses `sigil_verify()` to validate. |
| SI-E2 (Contract payload format) | Phase 1.3: `contract:{contract_id}\|{created_at}` |
| SI-E3 (HAT = same payload as contract) | Phase 1.3 + 2.3: Extension signs same payload, server verifies same payload |
| SI-E6 (IPC unreachable → Reply(I)) | Phase 2.2: Exception handler returns informational |
| SI-F3 (No crashes from Sigil unavailability) | Phase 2.2: All IPC errors caught, converted to ValueError / Reply(I) |
| §3.7 (120s timeout) | Phase 2.1: Client created with `timeout=120.0` |

---

## Note on SI-A3 Compliance (Extension Side)

Invariant SI-A3 says "All signing and verification MUST pass through `sigil.py`'s 3-function public API." This refers to the Python side. The TypeScript extension necessarily uses `crypto.createHmac` directly (it cannot call `sigil.py`). This is the same pattern as mode init signing in `agentView.ts` and is acceptable because:

1. The extension is the **origin** of the Sigil secret — it generated it
2. TypeScript and Python share the same algorithm (HMAC-SHA256) and secret (via env var)
3. The Python side always **verifies** via `sigil_verify()`, maintaining SI-A3 on the verification path
4. Only two TypeScript locations ever sign: `generateInitPrompt()` (mode init) and `approveContract()` (HAT). Both are in trusted extension code, not agent-accessible.
