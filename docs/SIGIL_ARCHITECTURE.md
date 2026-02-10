# Sigil — Session Cryptographic Signing Architecture

> **Status:** CANONICAL  
> **Last Updated:** February 10, 2026  
> **Authority:** Single source of truth for Sigil, its consumers, and the Protected Files system.

---

## 1. What Sigil Is

Sigil is the session-scoped cryptographic signing foundation for CK3 Lens. It provides a single HMAC-SHA256 signing primitive that all authentication and integrity subsystems use. No other module may import `hmac`, `hashlib`, or read the signing secret directly.

### 1.1 Key Properties

| Property | Value |
|----------|-------|
| **Algorithm** | HMAC-SHA256 |
| **Secret** | 16 random bytes, generated per VS Code window activation |
| **Secret location (TS)** | Extension memory (`CK3LensMcpServerProvider.sigilSecret`) |
| **Secret location (Python)** | `CK3LENS_SIGIL_SECRET` env var (set by extension at MCP subprocess launch) |
| **Disk presence** | **Never.** Secret exists only in process memory and env var. |
| **Lifetime** | One VS Code window session. New window = new secret = all prior signatures invalid. |
| **Module** | `tools/compliance/sigil.py` |

### 1.2 Public API

```python
sigil_available() -> bool        # Is the secret present? (False in standalone/test mode)
sigil_sign(payload: str) -> str  # HMAC-SHA256, returns hex. Raises if unavailable.
sigil_verify(payload: str, signature: str) -> bool  # Constant-time comparison. Returns False if unavailable.
```

Callers build canonical string payloads. Sigil signs them. That's it.

### 1.3 Security Model

The agent cannot forge signatures because:
1. The secret is in the MCP subprocess's env var — agents cannot read subprocess env vars through any tool
2. All MCP tools are gated behind mode init (which itself requires a Sigil-signed token)
3. The agent can *replay* a signature it has seen (e.g., re-paste a mode init token from chat), but replayed signatures are constrained by timestamp expiry and scope checks

---

## 2. Sigil Consumers

Sigil has exactly three consumers. Each solves a different problem with the same primitive.

| Consumer | Problem | Payload Format | Who Signs | When Verified |
|----------|---------|----------------|-----------|---------------|
| **Mode Init** | Prevent agent self-initialization | `mode\|timestamp\|nonce` | Extension (inline in prompt) | `ck3_get_mode_instructions()` |
| **Contract Signing** | Detect forged/stale contract files | `contract:{id}\|{created_at}` | MCP server (`save_contract()`) | Every `load_contract()` / `get_active_contract()` |
| **Protected Files (HAT)** | Require human approval for sensitive edits | The contract identity payload | Extension (via IPC, on user approval) | `open_contract()` when edits touch protected paths |

---

## 3. Sigil Invariants

Normative requirements. **MUST** and **SHALL** carry their RFC 2119 meanings. Every invariant has an identifier (SI-*) for cross-referencing in code comments and reviews.

### 3.1 Scope & Authority

| ID | Invariant |
|----|-----------|
| SI-A1 | Sigil is the **sole** cryptographic authority in ck3raven. No other module may perform HMAC, signing, or secret-based verification. |
| SI-A2 | The canonical authority document is `docs/SIGIL_ARCHITECTURE.md`. Any change to Sigil behavior MUST be reflected here first. |
| SI-A3 | All signing and verification MUST pass through `sigil.py`'s 3-function public API. No consumer may call `hmac` or `hashlib` directly for authentication purposes. |
| SI-A4 | `sigil.py` is a **sealed module**. No function may be added, removed, or have its signature changed without updating this document first. |

### 3.2 Secret Generation, Storage & Lifetime

| ID | Invariant |
|----|-----------|
| SI-B1 | The secret MUST be generated exactly once per VS Code window activation, by the extension. |
| SI-B2 | The secret MUST be passed to the MCP subprocess via the `CK3LENS_SIGIL_SECRET` environment variable. No other transport mechanism is permitted. |
| SI-B3 | The secret MUST be at least 16 bytes of cryptographically random data, hex-encoded. |
| SI-B4 | Secret lifetime equals VS Code window lifetime. New window = new secret. All prior signatures become invalid. |
| SI-B5 | The secret MUST NOT be written to disk, logged, included in error messages, or transmitted over any network channel. |

### 3.3 Public API Contract (Sealed API)

| ID | Invariant |
|----|-----------|
| SI-C1 | `sigil.py` exposes exactly 3 public functions: `sigil_available()`, `sigil_sign()`, `sigil_verify()`. This is the **complete** API surface. |
| SI-C2 | `sigil_sign()` and `sigil_verify()` MUST raise `SigilNotAvailable` when the secret is absent. |
| SI-C3 | `sigil_verify()` MUST use constant-time comparison (`hmac.compare_digest`). |
| SI-C4 | All 3 functions are pure: no I/O, no side effects, no state mutation beyond reading the env var on first call. |

### 3.4 Payload Canonicalization

| ID | Invariant |
|----|-----------|
| SI-D1 | Every consumer MUST define a canonical payload string format, documented in this document under the consumer's section. |
| SI-D2 | Payloads MUST be deterministically reproducible from stored or transmitted fields. Given the same inputs, the same payload is produced. |
| SI-D3 | Payloads MUST NOT include mutable fields. Only immutable identity fields (IDs, creation timestamps, mode names) are permitted. |
| SI-D4 | Payload formats use `\|` as the field delimiter. The canonical pattern is `prefix:field1\|field2\|...` or `field1\|field2\|...`. |

### 3.5 Consumer-Specific Invariants

| ID | Invariant |
|----|-----------|
| SI-E1 | Mode init payload format: `{mode}\|{timestamp}\|{nonce}`. Extension signs, server verifies once at init. |
| SI-E2 | Contract payload format: `contract:{contract_id}\|{created_at}`. Server signs at save, verifies at every load. |
| SI-E3 | HAT uses the same payload as SI-E2. Extension signs after user approval via IPC. The contract carries one signature regardless of whether HAT was involved. |
| SI-E4 | Mode init verification failure MUST prevent mode initialization (hard block). |
| SI-E5 | Contract verification failure MUST cause the contract to be treated as non-existent (silent rejection, not crash). |
| SI-E6 | HAT: if IPC is unreachable, server MUST return Reply(I) and MUST NOT open the contract. |

### 3.6 Failure & Degradation

| ID | Invariant |
|----|-----------|
| SI-F1 | If `CK3LENS_SIGIL_SECRET` is unset, `sigil_available()` returns `False`. |
| SI-F2 | When Sigil is unavailable, each consumer degrades independently: mode init falls back to `CK3LENS_DEV_TOKEN` (dev/test only); contracts save without signatures (noted in metadata); HAT is unreachable (contracts touching protected files cannot open). |
| SI-F3 | Sigil unavailability MUST NOT crash the server. All failures are informational (Reply(I)) or logged warnings — never exceptions that propagate to the agent. |

### 3.7 IPC Timeout Contract (HAT-Specific)

When `open_contract()` makes an IPC call to the extension for HAT approval:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Maximum wait** | 120 seconds | User may need to read the dialog and consider the request. |
| **Timeout behavior** | Return Reply(I): "HAT approval timed out" | No contract opened. Agent informed. |
| **User cancellation** | Extension returns `{ approved: false }` | Treated identically to explicit decline. |
| **Extension closes mid-dialog** | IPC connection drops → timeout or connection error → Reply(I) | Server catches exception, returns informational reply. |
| **Concurrent requests** | Server SHOULD serialize HAT requests; only one contract opens at a time. | Agents work sequentially. Race conditions are not a practical concern. |

### 3.8 Non-Goals

| ID | Non-Goal | Rationale |
|----|----------|-----------|
| SI-G1 | **Replay protection (nonce tracking)** | Mode-init tokens have 5-minute expiry, sufficient for the threat model. Contract signatures are bound to a unique `contract_id`, making replay meaningless. Nonce databases add complexity without security benefit. |
| SI-G2 | **Tamper-proof audit** | Startup hash verification of protected files is advisory (log warnings), not enforcement. The pre-commit hook provides the hard enforcement layer. |
| SI-G3 | **Cross-session signature portability** | Signatures are intentionally session-scoped. There is no mechanism to validate a signature from a previous session, and none is planned. |
| SI-G4 | **Network-based signing** | Sigil operates entirely within a single machine (extension → env var → subprocess). Network transport of secrets or signatures is out of scope. |

---

## 4. Consumer 1: Mode Initialization

**Problem:** Agents must not be able to initialize themselves. The human must click the button.

### 4.1 Flow

```
1. User clicks "Initialize Agent" in CK3 Lens sidebar
2. Extension signs payload: "mode|timestamp|nonce" with Sigil secret
3. Token embedded in chat prompt: hat_token="payload::signature"
4. Agent sends prompt → calls ck3_get_mode_instructions(mode="ck3lens", hat_token="...")
5. Server splits on "::", verifies HMAC via sigil_verify()
6. Server checks: mode field matches, timestamp within 5 minutes
7. Mode initialized — agent has tools
```

### 4.2 Token Format

```
{mode}|{ISO-8601 timestamp}|{random nonce}::{HMAC-SHA256 hex signature}
```

Example: `ck3lens|2026-02-10T14:30:00.000Z|a1b2c3d4e5f6...::<64 hex chars>`

### 4.3 Properties

- **Inline:** Token travels in the chat prompt text. No files.
- **5-minute expiry:** Prevents replay of old tokens across sessions.
- **Nonce:** Unique per click. Prevents exact replay within the 5-minute window (server could optionally track seen nonces, but expiry is sufficient — see SI-G1).
- **Fallback:** `CK3LENS_DEV_TOKEN` env var for standalone testing without the extension.

### 4.4 Implementation

| Component | File | Function |
|-----------|------|----------|
| Signing (TS) | `agentView.ts` | `generateInitPrompt()` |
| Verification (Python) | `server.py` | `_ck3_get_mode_instructions_internal()` |

---

## 5. Consumer 2: Contract Signing

**Problem:** Contract JSON files sit on disk. An agent could theoretically write a fake contract file to grant itself permissions. Sigil signing ensures only contracts created by the MCP server (within a live session) are honored.

### 5.1 Flow

```
1. open_contract() creates a ContractV1 object
2. save_contract() computes payload: "contract:{contract_id}|{created_at}"
3. save_contract() calls sigil_sign(payload) → stores as session_signature field
4. Contract JSON written to disk (includes session_signature)
5. Every load_contract() / get_active_contract() / list_contracts() call:
   a. Reads contract JSON
   b. Recomputes payload from contract_id + created_at
   c. Calls sigil_verify(payload, session_signature)
   d. Rejects if invalid or missing
```

### 5.2 Session Isolation

Contracts from previous VS Code sessions have signatures made with a different secret. They will fail verification and be invisible to `get_active_contract()` and `list_contracts()`. This is **intentional** — a new session starts clean. Old contracts are not deleted; they become inert.

### 5.3 Payload Design

The signing payload uses `contract_id` and `created_at` — immutable identity fields set at creation. The signature does not cover the full JSON content. Mutating other fields (status, notes) does not invalidate the signature. This is correct because:
- The signature proves *origin* (created by this session's MCP server), not *integrity of all fields*
- Status transitions (open → closed) are legitimate mutations by the same server

### 5.4 Implementation

| Component | File | Function |
|-----------|------|----------|
| Signing | `contract_v1.py` | `save_contract()` via `_contract_signing_payload()` |
| Verification | `contract_v1.py` | `load_contract()` / `get_active_contract()` via `_verify_contract_signature()` |

---

## 6. Consumer 3: Protected Files & HAT

**Problem:** Certain files (agent instruction docs, policy manifests) must not be modified without explicit human approval, even when the agent has an active contract.

### 6.1 Protected Files Manifest

**Path:** `policy/protected_files.json` (checked into git, self-protected by hardcoded rule)

```json
{
  "schema_version": "1",
  "entries": [
    {
      "path": ".github/copilot-instructions.md",
      "type": "file",
      "sha256": "38a34da9...",
      "added_at": "2026-02-10T13:05:00",
      "reason": "VS Code Copilot root instructions"
    }
  ]
}
```

**Entry types:**

| Type | `sha256` Field | Match Rule |
|------|----------------|------------|
| `file` | SHA-256 of file content | Exact path match |
| `folder` | empty | Any path under the folder prefix |

**Self-protection:** The manifest itself is always protected by hardcoded rule in `_HARDCODED_PROTECTED`, regardless of whether it lists itself. An agent cannot silently remove protections.

### 6.2 HAT — Human Authorization Token

HAT is the mechanism by which the human authorizes a contract that touches protected files. Unlike mode init (where the human acts *before* the agent), HAT fires *during* `open_contract()` when the server discovers protected paths in the work declaration.

### 6.3 HAT Flow (IPC-Based)

```
1. Agent calls open_contract(work_declaration={edits: ["copilot-instructions.md", ...]})
2. Server checks edits against protected manifest → finds protected paths
3. Server calls extension via IPC (JSON-RPC over TCP, port 9847):
     method: "approveContract"
     params: { contract_id, intent, protected_paths, root_category }
4. Extension receives IPC call → shows VS Code modal dialog:
     "Contract v1-xxx wants to edit protected files:
       • .github/copilot-instructions.md
      Approve?"
5a. User clicks Approve:
     → Extension Sigil-signs the contract (same secret, same HMAC)
     → Returns { approved: true, signature: "..." } via IPC
     → Server stores signature in contract, saves as "open"
     → Returns Reply(S) to agent with hat_authorized=true, protected_paths=[...]
5b. User clicks Decline:
     → Extension returns { approved: false } via IPC
     → Server returns Reply(I) to agent: "User declined. Protected files: [...]"
```

### 6.4 Key Properties

| Property | Value |
|----------|-------|
| **Agent awareness** | Agent knows HAT exists. Sees `hat_authorized` in reply. Can reason about protected files. |
| **Agent involvement** | None. Agent calls `open_contract()` once. Server handles everything. No retry. |
| **Signing target** | The contract itself (not a separate approval file) |
| **Consumed artifacts** | None. Signature lives in the contract's `session_signature` field. |
| **IPC channel** | Existing `DiagnosticsServer` (JSON-RPC over TCP, `ipc_client.py`) |
| **Fallback if IPC down** | Reply(I) — "Cannot reach extension for HAT approval. Ensure CK3 Lens is active." (per SI-E6) |
| **Timeout** | 120 seconds maximum (per §3.7) |

### 6.5 Why IPC, Not File Handshake

The previous design used `hat_request.json` / `hat_approval.json` files on disk — the server wrote a request, the agent told the user to click a button, the extension wrote an approval, the agent retried. This had problems:

1. **Two-step retry:** Agent had to know about the handshake and explicitly retry
2. **Two signatures:** Approval file signed separately from the contract
3. **Race conditions:** File presence/absence as synchronization primitive
4. **Agent as messenger:** Agent had to relay "click the shield icon" — unnecessary coupling

The IPC approach makes `open_contract()` synchronous from the agent's perspective. The server blocks on the IPC call (with timeout), user approves or declines, and the agent gets a single reply.

### 6.6 What Gets Signed

When the user approves, the extension signs the same contract identity payload that `save_contract()` would: `contract:{id}|{created_at}`. This means the contract's `session_signature` serves double duty:

1. Proves the contract was created by this session's MCP server
2. Proves the human approved it (for contracts touching protected files)

For contracts that don't touch protected files, the signature is applied server-side by `save_contract()` (no IPC needed). For contracts that do touch protected files, the signature is applied by the extension after user approval. Either way, the contract carries one signature with the same format (per SI-E3).

### 6.7 Enforcement Integration

**HAT is checked in `open_contract()`, NOT in `enforcement.py`.**

| Layer | Responsibility | HAT Awareness |
|-------|---------------|---------------|
| `enforcement.py` | Capability matrix + contract requirement | **None** |
| `open_contract()` | Validates work_declaration against protected manifest | **Yes** — triggers IPC if needed |
| `ck3_protect` tool | Manifest management (add/remove entries) | **Yes** — also requires HAT via IPC |

This preserves enforcement's simple gate model. Enforcement answers: "Given (mode, operation, path, has_contract), allow or deny?" HAT answers: "Did the human approve this plan?" — a question about **intent**, not **capability**.

---

## 7. Defense-in-Depth

Three independent layers. Each catches different failure modes.

| Layer | Mechanism | Catches |
|-------|-----------|---------|
| **1. Contract gate** | HAT required for protected edits via IPC | Agent bypasses (normal operation) |
| **2. Git pre-commit hook** | Checks staged files against manifest | Direct filesystem writes, skipped contract system |
| **3. Startup hash verification** | MCP server checks file hashes on init | Tampering between sessions (advisory — see SI-G2) |

### 7.1 Git Pre-Commit Hook

`.git/hooks/pre-commit` (installed by `tools/compliance/install_hooks.py`, not checked into repo):

```bash
python -m tools.compliance.protected_files check-staged
```

Checks `git diff --cached --name-only` against manifest. Blocked unless `CK3RAVEN_PROTECTED_OK=1` is set in environment (set automatically by `ck3_git` under a HAT-authorized contract).

### 7.2 Startup Hash Verification

On MCP startup (`ck3_get_mode_instructions`):
1. Load manifest, compute SHA-256 for each file entry, compare
2. Mismatches → log warning (not block — files may have been legitimately updated via HAT)

---

## 8. `ck3_protect` MCP Tool

Exposes manifest management to agents. Add/remove operations require HAT approval (same IPC flow as contract open).

| Command | Purpose | HAT Required |
|---------|---------|-------------|
| `list` | List all protected entries | No |
| `verify` | Check all SHA-256 hashes | No |
| `add` | Add file/folder to manifest | Yes (IPC approval dialog) |
| `remove` | Remove entry from manifest | Yes (IPC approval dialog) |

---

## 9. Initial Protected Files

Minimal deployment — the 3 instruction documents:

| Path | Type | Reason |
|------|------|--------|
| `.github/copilot-instructions.md` | file | VS Code Copilot root instructions |
| `.github/COPILOT_LENS_COMPATCH.md` | file | ck3lens agent instructions |
| `.github/COPILOT_RAVEN_DEV.md` | file | ck3raven-dev agent instructions |

---

## 10. Canonical Architecture Rule Compliance

| Rule | Compliance |
|------|-----------|
| Rule 1 (ONE enforcement boundary) | HAT is NOT in enforcement. Contract gate handles it. |
| Rule 2 (NO permission oracles) | No `is_file_protected()` oracle pre-queried by agents. Check happens at `open_contract()` time. |
| Rule 3 (mods[] is THE mod list) | Not affected. Protected files are repo-internal. |
| Rule 4 (WorldAdapter = resolution) | Not affected. WorldAdapter does not know about protected files. |
| Rule 5 (Enforcement = decisions) | Enforcement unchanged. HAT is a contract-open prerequisite. |

---

## 11. WIP Exclusion

WIP (`~/.ck3raven/wip/`) is excluded from protected files. WIP has no contract requirement and is always writable. Protected files only apply to paths that go through the contract system.

---

## 12. Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Sigil module** (`tools/compliance/sigil.py`) | **Done** | Sealed. 3-function API. |
| **Mode init (inline token)** | **Done** | Extension signs in prompt, server verifies. |
| **Contract signing** | **Done** | `save_contract()` signs, `load_contract()` verifies. |
| **Protected files manifest** | **Done** | `policy/protected_files.json` with 3 entries. |
| **Protected files module** | **Done** | `tools/compliance/protected_files.py` — load, verify, check. |
| **`ck3_protect` tool** | **Done** | list, verify, add, remove commands. |
| **Git pre-commit hook** | **Done** | `tools/compliance/install_hooks.py`. |
| **HAT via IPC (contract gate)** | **Not started** | Replaces file-based handshake. Requires IPC endpoint in extension + Python caller in `open_contract()`. |
| **File-based HAT handshake** | **Deprecated** | `hat_request.json`/`hat_approval.json` approach. To be removed when IPC HAT is implemented. |

---

## 13. Resolved Design Questions

**Q: Can the agent forge a contract file on disk?**  
A: No. `load_contract()` verifies the Sigil signature. Without the secret (in env var), the agent cannot produce a valid signature.

**Q: What happens to contracts from a previous VS Code session?**  
A: They become inert. Different session = different secret = signature verification fails. This is intentional session isolation (see SI-B4).

**Q: Why does the agent know about HAT?**  
A: No security benefit to hiding it. The agent can't forge signatures regardless. Transparency lets the agent explain *why* approval is needed and propose alternatives if declined.

**Q: Why IPC instead of file-based handshake for protected files?**  
A: Single call, no retry, no polling. The server blocks on IPC, user approves or declines, agent gets one reply. Cleaner for the agent, cleaner for the user.

**Q: What if the IPC server is down?**  
A: Reply(I) — "Cannot reach extension for HAT approval." The contract is not opened. Agent can inform the user. (Per SI-E6.)

**Q: What about the manifest itself?**  
A: `policy/protected_files.json` is always protected by hardcoded rule. Cannot be removed from protection even by editing the manifest.

**Q: Why no nonce tracking for replay protection?**  
A: Explicit non-goal (SI-G1). Mode-init tokens expire in 5 minutes, making replay windows negligible. Contract signatures are bound to unique `contract_id` values — replaying a signature for contract A onto contract B fails verification. The cost/complexity of a nonce database is not justified.

**Q: Is startup hash verification a security gate?**  
A: No. It is advisory (SI-G2). Mismatches are logged as warnings, not blocks. The pre-commit hook is the hard enforcement layer. Startup verification catches accidental drift, not adversarial tampering.
