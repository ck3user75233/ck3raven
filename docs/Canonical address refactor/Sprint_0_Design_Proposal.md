# Sprint 0 — Design Proposal: VisibilityRef, Design Questions, and Implementation Plan

> **Author:** Agent (ck3raven-dev mode)
> **Date:** February 17, 2026
> **Status:** AWAITING REVIEW — Implementation blocked until Nate approves
> **Directive:** Sprint 0 Canonical Addressing Refactor (v1.1)
> **Contract:** v1-2026-02-17-53e641

---

## Table of Contents

1. [Design Questions and Recommendations](#1-design-questions-and-recommendations)
2. [VisibilityRef Design Proposal (Checkpoint 1)](#2-visibilityref-design-proposal-checkpoint-1)
3. [Implementation Plan](#3-implementation-plan)

---

## 1. Design Questions and Recommendations

Three design decisions need to be settled before implementation can begin. Each is presented with the full problem statement, options considered, and a recommended answer.

---

### 1.1 Canonical Address Syntax — Colon-Slash or Plain Slash?

**Problem:** There is a divergence between the current v1 address syntax and what the Sprint 0 spec describes.

**Current v1** (`world_adapter.py` line 438) parses mod addresses as:
```
mod:MyModName/common/traits/00_traits.txt
```
The separator between mod name and relative path is a single `/`. The parsing code does `rest.split("/", 1)`.

**Sprint 0 spec** describes:
```
mod:<ModNameOrId>:/common/traits/00_traits.txt
```
That is a `:/` separator — colon then slash — mimicking URI authority syntax.

Similarly for root-category addresses, v1 has only `ck3raven:/<path>` as a scheme. Sprint 0 proposes the general form `ROOT_CATEGORY:/<path>` (e.g., `ROOT_REPO:/src/server.py`).

**Why this matters:**

- If v2 uses `mod:Name:/path` and v1 uses `mod:Name/path`, agents see two different syntaxes during the coexistence period, creating confusion.
- When existing tools are eventually migrated to v2, callers using the old syntax break.
- Mod names can theoretically contain `/` (unlikely but possible in CK3 descriptor names). A `:/` separator eliminates that ambiguity.

**Options:**

| Syntax | Example | Pros | Cons |
|--------|---------|------|------|
| Plain `/` (v1 style) | `mod:Unofficial Patch/common/traits` | Shorter, familiar | Ambiguous if mod name contains `/` |
| `:/` separator | `mod:Unofficial Patch:/common/traits` | Unambiguous, mirrors URI authority | Slightly longer, diverges from v1 |

**Recommendation: Use `:/` as the canonical separator for v2.**

The forms become:
```
ROOT_REPO:/src/server.py              (root-category)
ROOT_CK3RAVEN_DATA:/wip/analysis.py   (root-category)
ROOT_GAME:/game/common/traits         (root-category)
mod:Unofficial Patch:/common/traits    (mod-addressing)
```

v1 continues to accept `mod:Name/path` unchanged during coexistence. v2 only accepts `mod:Name:/path`. When migration happens (Sprint 1+), v1's parser gets updated. The isolation mandate means they don't need to agree until then.

---

### 1.2 Where Does `session_home_root` State Live?

**Problem:** The `cd` command changes `session_home_root` (the default RootCategory used to interpret bare relative paths like `wip/x.txt`). The Sprint 0 spec doesn't specify where this mutable state is stored.

**Architectural constraint:** Canonical Architecture Rule 4 states *"WorldAdapter = visibility — describes what exists, NOT what's allowed."* WA is a stateless lens over the filesystem. Adding mutable session navigation state turns it into a session navigator, which is an architectural smell.

**Options:**

| Option | Pros | Cons |
|--------|------|------|
| **On WorldAdapterV2** | Simple, self-contained for Sprint 0 | Violates WA's stateless visibility role. Must be extracted later. |
| **On Session (workspace.py)** | Session already holds mutable agent state (playset, mods). Natural home. | Breaks isolation mandate — Session is a v1 object, `ck3_dir` would need to import/modify it. |
| **New SessionContext class** | Clean separation. WA stays stateless. | Extra object to manage. Needs to persist across tool calls. |
| **Module-level state in ck3_dir** | Simplest. One variable. Fully isolated. WA stays pure. | Module globals are ugly — but it's one variable in a pilot tool. |

**Recommendation: Module-level state in the `ck3_dir` implementation module.**

Reasoning:
- WA stays a pure visibility resolver (no mutable state).
- No v1 Session coupling (isolation mandate respected).
- It's one variable (`_session_home_root: RootCategory`) — doesn't warrant a new class yet.
- When Sprint 1 designs the broader session model, this gets promoted into whatever SessionContext emerges.

```python
# In ck3lens/impl/dir_ops.py (or wherever ck3_dir_impl lives)
from ck3lens.paths import RootCategory

# Sprint 0: session navigation state — migrate to SessionContext in Sprint 1
_session_home_root: RootCategory = RootCategory.ROOT_CK3RAVEN_DATA
```

The `cd` command validates and updates this. The `pwd` command reads it. `list` and `tree` use it as the default when `path` is None.

---

### 1.3 What Does `VisibilityRef.__str__` Return?

**Problem:** `VisibilityRef` holds an encrypted host-absolute path internally. When code (or logging, or accidental f-string interpolation) calls `str()` on it, what should appear?

**Threat model (per Sprint 0 spec):** Prevent accidental misuse, not hostile developers.

The primary leak vector is someone writing `f"Resolved: {vis_ref}"` and the host path ending up in a Reply's `data` or `message` field, which is serialized to JSON and sent to the agent.

**Options:**

| Option | `str(vis_ref)` output | Leak risk | Debugging value |
|--------|----------------------|-----------|-----------------|
| Opaque token | `<VisibilityRef:0xa3f2b>` | Zero | Useless |
| Session-absolute form | `ROOT_REPO:/src/server.py` | Zero (no host path) | Excellent |
| Redacted hint | `<VisibilityRef:ROOT_REPO:…/server.py>` | Near-zero | Moderate |

**Recommendation: `__str__` returns the session-absolute form.**

```python
str(vis_ref)   # → "ROOT_REPO:/src/server.py"
repr(vis_ref)  # → "VisibilityRef(ROOT_REPO:/src/server.py)"
```

This is:
- **Safe:** Contains no host path information. The leak detector gate won't trigger.
- **Useful:** If it accidentally appears in logs, error messages, or even a Reply, it's informative AND non-leaking.
- **Natural:** The agent already thinks in session-absolute terms. Accidental leakage reads correctly rather than appearing as garbage.

The host path is *only* recoverable via `open_ref()` — see Section 2.

---

## 2. VisibilityRef Design Proposal (Checkpoint 1)

This section is the mandatory design proposal required by Sprint 0 §5.2 before implementation may begin.

### 2.1 Core Design: Sigil-Encrypted Sealing

**Mechanism:** The host-absolute path is encrypted using the existing Sigil session key. The plaintext host path never exists as a readable attribute on the `VisibilityRef` object.

**Why Sigil encryption (not structural privacy):**

The simpler alternative — storing the host path in an underscore-private attribute (`_host_path`) — was considered and rejected. Structural privacy alone means:
- `vars(vis_ref)` or `vis_ref.__dict__` exposes the plaintext `Path`
- A debugger or `getattr()` call recovers it trivially
- The host path exists in memory as a readable string

With Sigil encryption, the host path is ciphertext on the object. Even reflection, serialization, or debugger inspection reveals only encrypted bytes.

**Why Sigil is available:** The MCP server cannot initialize without the extension providing a Sigil-signed HAT token. No HAT → no mode → no tools. The Sigil session secret (`CK3LENS_SIGIL_SECRET`) is guaranteed to be present whenever any v2 tool could be called. No plaintext fallback is needed. Tests set the env var as a fixture — same as they already must for HAT and contract tests.

### 2.2 VisibilityRef Class

```python
from __future__ import annotations
from ck3lens.paths import RootCategory


class VisibilityRef:
    """
    Sealed reference to a host-absolute filesystem path.
    
    The host path is Sigil-encrypted. The only way to recover
    it is via open_ref(), which uses the session key to decrypt.
    
    Agent-safe: str() returns the session-absolute form.
    Non-serializable: pickle/JSON raise TypeError.
    """
    __slots__ = ('_sealed', '_session_abs', '_root_category')
    
    def __init__(self, sealed: bytes, session_abs: str, root_category: RootCategory):
        object.__setattr__(self, '_sealed', sealed)
        object.__setattr__(self, '_session_abs', session_abs)
        object.__setattr__(self, '_root_category', root_category)
    
    def __setattr__(self, name, value):
        raise AttributeError("VisibilityRef is immutable")
    
    def __delattr__(self, name):
        raise AttributeError("VisibilityRef is immutable")
    
    def __str__(self) -> str:
        """Returns session-absolute address. Safe for agent-visible output."""
        return self._session_abs
    
    def __repr__(self) -> str:
        return f"VisibilityRef({self._session_abs})"
    
    @property
    def session_absolute(self) -> str:
        """The canonical session-absolute address (agent-safe)."""
        return self._session_abs
    
    @property
    def root_category(self) -> RootCategory:
        """The RootCategory this path belongs to."""
        return self._root_category
    
    # --- Serialization blockers ---
    
    def __getstate__(self):
        raise TypeError("VisibilityRef cannot be serialized")
    
    def __reduce__(self):
        raise TypeError("VisibilityRef cannot be pickled")
```

**Key properties:**
- `__slots__` prevents `__dict__` — no `vars(vis_ref)` leak
- `__setattr__`/`__delattr__` overrides make it immutable after construction
- `__getstate__`/`__reduce__` block pickle
- No `__json__`, `to_dict()`, or similar — JSON serialization of the object itself fails
- The `_sealed` attribute is `bytes` (ciphertext) — even `getattr(vis_ref, '_sealed')` returns encrypted bytes, not a path

### 2.3 Sigil Encryption / Decryption

New functions added to `tools/compliance/sigil.py`, alongside the existing `sigil_sign`/`sigil_verify`:

```python
def sigil_encrypt(plaintext: str) -> bytes:
    """
    Encrypt a string with the session secret.
    
    Uses HMAC-SHA256 in CTR mode as a keystream generator.
    Random IV ensures identical inputs produce different ciphertexts.
    
    Ciphertext is meaningless after session key rotation (next VS Code window).
    """
    secret = _get_secret_bytes()
    if secret is None:
        raise RuntimeError(f"Sigil secret not available ({_ENV_VAR} not set)")
    
    iv = os.urandom(16)
    data = plaintext.encode("utf-8")
    
    # Generate keystream: HMAC(secret, iv || counter) per 32-byte block
    keystream = b""
    for i in range((len(data) // 32) + 1):
        keystream += hmac.new(
            secret, iv + i.to_bytes(4, 'big'), hashlib.sha256
        ).digest()
    
    encrypted = bytes(a ^ b for a, b in zip(data, keystream[:len(data)]))
    return iv + encrypted


def sigil_decrypt(ciphertext: bytes) -> str:
    """
    Decrypt ciphertext produced by sigil_encrypt().
    
    Raises RuntimeError if the session secret is unavailable.
    """
    secret = _get_secret_bytes()
    if secret is None:
        raise RuntimeError(f"Sigil secret not available ({_ENV_VAR} not set)")
    
    iv = ciphertext[:16]
    encrypted = ciphertext[16:]
    
    keystream = b""
    for i in range((len(encrypted) // 32) + 1):
        keystream += hmac.new(
            secret, iv + i.to_bytes(4, 'big'), hashlib.sha256
        ).digest()
    
    decrypted = bytes(a ^ b for a, b in zip(encrypted, keystream[:len(encrypted)]))
    return decrypted.decode("utf-8")
```

**Design notes:**
- stdlib-only (hmac, hashlib, os) — no new dependencies
- Random 16-byte IV per encryption — identical paths produce different ciphertexts
- HMAC-SHA256 in CTR-like mode — not a standard named construction, but for the threat model (accidental leakage, not cryptanalysis) it is more than sufficient
- Session-scoped: ciphertext becomes garbage when `CK3LENS_SIGIL_SECRET` rotates (next VS Code window)
- If the threat model ever escalates, swap in `cryptography.fernet.Fernet` (AES-128-CBC+HMAC) — the API surface is identical

### 2.4 The Opener: `open_ref()`

The single authorized way to recover the host-absolute `Path` from a VisibilityRef:

```python
# In world_adapter_v2.py
from pathlib import Path
from tools.compliance.sigil import sigil_decrypt


def open_ref(vis_ref: VisibilityRef) -> Path:
    """
    PRIVILEGED: Recover host-absolute Path from a sealed VisibilityRef.
    
    This is the ONLY function that decrypts the sealed path.
    Only ck3_dir (and future v2 tools) should call this.
    
    The purity gate (Section 2.6) enforces that no v1 tool imports this.
    """
    return Path(sigil_decrypt(vis_ref._sealed))
```

**Access control:** The purity gate (Sprint 0 §5.5) ensures `open_ref` is only imported by `ck3_dir` and other `*_v2.py` modules. This is enforced by automated scan, not by runtime checks.

### 2.5 Threat Model

| Threat | Mitigation |
|--------|-----------|
| `str(vis_ref)` in Reply.data | Returns `"ROOT_REPO:/src/server.py"` — agent-safe, no host path |
| `f"path: {vis_ref}"` in log/message | Same — session-absolute form |
| `vars(vis_ref)` / `vis_ref.__dict__` | Blocked by `__slots__` |
| `getattr(vis_ref, '_sealed')` | Returns `bytes` ciphertext — not a readable path |
| `pickle.dumps(vis_ref)` | Raises `TypeError` |
| `json.dumps(vis_ref)` | Raises `TypeError` (not JSON-serializable) |
| Debugger inspection of `._sealed` | Shows ciphertext bytes |
| Session key rotation (new window) | Old VisibilityRefs automatically become undecryptable |
| Test environments | Tests set `CK3LENS_SIGIL_SECRET` env var as fixture |
| Hostile developer with source access | **Out of scope** — Sprint 0 threat model is "accidental misuse" only |

### 2.6 Leak Detector Gate

Sprint 0 §5.4 requires a defensive scan of Reply output. This is implemented as a function called before any Reply is returned from `ck3_dir`:

```python
import re

_HOST_PATH_PATTERNS = [
    re.compile(r'[A-Za-z]:\\'),           # Windows drive (C:\)
    re.compile(r'\\\\[A-Za-z]'),          # UNC path (\\server)
    re.compile(r'/Users/[A-Za-z]'),       # macOS home
    re.compile(r'/home/[A-Za-z]'),        # Linux home
    re.compile(r'/mnt/[A-Za-z]'),         # WSL/mount
]

def check_no_host_paths(data: dict, context: str = "") -> None:
    """
    Recursively scan dict for host-absolute path patterns.
    Raises ValueError if any are found.
    """
    def _scan(obj, path=""):
        if isinstance(obj, str):
            for pattern in _HOST_PATH_PATTERNS:
                if pattern.search(obj):
                    raise ValueError(
                        f"Host-absolute path leaked in {context} "
                        f"at {path}: {obj[:80]}..."
                    )
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _scan(v, f"{path}.{k}")
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                _scan(v, f"{path}[{i}]")
    _scan(data)
```

This is called on `Reply.data` and `Reply.message` before returning from `ck3_dir`. If triggered, the tool returns terminal Error instead of the leaking Reply.

---

## 3. Implementation Plan

### 3.1 File Layout

All Sprint 0 files are new. No existing files are modified except `sigil.py` (adding encrypt/decrypt) and `server.py` (registering the new tool).

```
tools/compliance/sigil.py                          # MODIFY: add sigil_encrypt, sigil_decrypt
tools/ck3lens_mcp/ck3lens/world_adapter_v2.py      # NEW: WorldAdapterV2 + VisibilityRef + open_ref
tools/ck3lens_mcp/ck3lens/impl/dir_ops.py          # NEW: ck3_dir_impl + session_home_root state
tools/ck3lens_mcp/ck3lens/leak_detector.py         # NEW: check_no_host_paths utility
tools/ck3lens_mcp/server.py                        # MODIFY: register ck3_dir tool
tests/test_world_adapter_v2.py                     # NEW: WA v2 unit tests
tests/test_dir_ops.py                              # NEW: ck3_dir acceptance tests
tests/test_leak_detector.py                        # NEW: leak detector tests
linters/arch_lint/rules/v2_isolation.py            # NEW: purity gate rule
```

### 3.2 Implementation Sequence

Work is organized in three phases matching the Sprint 0 checkpoints.

#### Phase 1 — Sigil Encryption + VisibilityRef + WA v2 (Checkpoint 2)

**Step 1: Add `sigil_encrypt` / `sigil_decrypt` to sigil.py**

- Add the two functions from Section 2.3 to `tools/compliance/sigil.py`
- They sit alongside existing `sigil_sign` / `sigil_verify` — same module, same secret
- Write unit tests: encrypt→decrypt round-trip, different IVs produce different ciphertexts, decrypt fails with wrong key, decrypt fails on truncated input

**Step 2: Create `world_adapter_v2.py`**

New module at `tools/ck3lens_mcp/ck3lens/world_adapter_v2.py` containing:

- `VisibilityRef` class (Section 2.2)
- `open_ref()` function (Section 2.4)
- `WorldAdapterV2` class with:

```python
class WorldAdapterV2:
    """
    World Adapter v2 — canonical addressing with sealed VisibilityRefs.
    
    Differences from v1 WorldAdapter:
    - resolve() returns (Reply, Optional[VisibilityRef]) not ResolutionResult
    - Host paths are encrypted in VisibilityRef, never in Reply
    - Only accepts canonical address forms (no raw host paths)
    - Uses :/ separator for mod addresses
    """
    
    def __init__(self, mode: str, *, roots: dict, mod_paths: dict):
        ...
    
    @classmethod
    def create(cls, mode: str, *, mods: list | None = None) -> WorldAdapterV2:
        """Factory using paths.py constants — same pattern as v1."""
        ...
    
    def resolve(
        self,
        path: str | None,
        session_home_root: RootCategory,
        *,
        allow_mod: bool = True,
    ) -> tuple[Reply, VisibilityRef | None]:
        """
        Resolve a canonical address to (Reply, VisibilityRef).
        
        On success: Reply(reply_type="S"), VisibilityRef with sealed host path
        On invalid:  Reply(reply_type="I"), None
        
        The Reply.data contains ONLY session-absolute fields. Never host paths.
        """
        ...
```

Resolve semantics (from Sprint 0 spec):
- `path` is None or `""` → resolves to `session_home_root:/`
- Bare relative path (no `:`) → resolves relative to `session_home_root`
- `ROOT_X:/rel/path` → root-category addressing
- `mod:Name:/rel/path` → mod addressing (note `:/` separator)
- Host-absolute paths (`C:\...`, `/Users/...`) → **terminal Invalid** (Invariant A)

**Step 3: Write WA v2 unit tests**

Test cases in `tests/test_world_adapter_v2.py`:

| Test | Input | Expected |
|------|-------|----------|
| Bare relative, default home | `"wip/x.txt"`, home=ROOT_CK3RAVEN_DATA | Success, session_abs=`ROOT_CK3RAVEN_DATA:/wip/x.txt` |
| Session-absolute | `"ROOT_REPO:/src/server.py"` | Success, session_abs=`ROOT_REPO:/src/server.py` |
| Mod-absolute | `"mod:SomeTestMod:/common/traits"` | Success, session_abs=`mod:SomeTestMod:/common/traits` |
| Host path rejected | `"C:\\Users\\test\\file.txt"` | Invalid reply, VisibilityRef=None |
| Unix host path rejected | `"/home/test/file.txt"` | Invalid reply, VisibilityRef=None |
| Empty path → home root | `None` | Success, resolves to home root |
| Unknown root category | `"ROOT_FAKE:/foo"` | Invalid reply |
| Mod not in playset | `"mod:NonexistentMod:/foo"` | Invalid reply |
| VisibilityRef str safety | — | `str(vis_ref)` contains no host path |
| VisibilityRef pickle blocked | — | `pickle.dumps()` raises TypeError |
| VisibilityRef dict blocked | — | `vars()` raises TypeError or returns empty |
| open_ref round-trip | — | `open_ref(vis_ref)` recovers correct host Path |
| Reply.data has no host paths | — | Leak detector passes on every success Reply |

**Checkpoint 2 deliverable:** WA v2 implemented, all tests pass, `open_ref` round-trips correctly, no host paths in Reply.data.

---

#### Phase 2 — ck3_dir Tool + Leak Detector (Checkpoint 3)

**Step 4: Create `leak_detector.py`**

New module at `tools/ck3lens_mcp/ck3lens/leak_detector.py` with:
- `check_no_host_paths(data, context)` function (Section 2.6)
- Unit tests that verify detection of Windows, macOS, Linux, UNC, and WSL path patterns
- Verify that session-absolute addresses (`ROOT_REPO:/...`) do NOT trigger false positives

**Step 5: Create `dir_ops.py`**

New module at `tools/ck3lens_mcp/ck3lens/impl/dir_ops.py` containing:

```python
from ck3lens.paths import RootCategory

# Sprint 0: session navigation state — migrate to SessionContext in Sprint 1
_session_home_root: RootCategory = RootCategory.ROOT_CK3RAVEN_DATA


def ck3_dir_impl(
    command: Literal["pwd", "cd", "list", "tree"],
    path: str | None = None,
    depth: int = 3,
    *,
    wa_v2: WorldAdapterV2,
    rb: ReplyBuilder,
) -> Reply:
    ...
```

**Command implementations:**

**`pwd`** — Pure state read, no WA call:
```python
if command == "pwd":
    return rb.success("WA-DIR-S-001", {
        "home": f"{_session_home_root.name}:/",
        "root_category": _session_home_root.name,
    })
```

**`cd`** — Validates and updates session_home_root. Sprint 0 restriction: root category only (no subdirectory re-homing):
```python
if command == "cd":
    try:
        new_root = RootCategory[path]   # e.g., "ROOT_REPO" → RootCategory.ROOT_REPO
    except (KeyError, TypeError):
        return rb.invalid("WA-DIR-I-001", {"error": f"Unknown root category: {path}"})
    _session_home_root = new_root
    return rb.success("WA-DIR-S-002", {
        "home": f"{new_root.name}:/",
        "root_category": new_root.name,
    })
```

**`list`** — Lists immediate children of a directory:
```python
if command == "list":
    reply, vis_ref = wa_v2.resolve(path, _session_home_root)
    if reply.reply_type != "S":
        return reply   # Terminal — Invariant F
    
    host_path = open_ref(vis_ref)
    if not host_path.is_dir():
        return rb.invalid("WA-DIR-I-002", {"error": "Not a directory", "path": str(vis_ref)})
    
    entries = []
    for child in sorted(host_path.iterdir()):
        child_session_abs = f"{vis_ref.session_absolute}/{child.name}"
        entries.append({
            "name": child.name,
            "path": child_session_abs + ("/" if child.is_dir() else ""),
            "type": "dir" if child.is_dir() else "file",
        })
    
    data = {"target": str(vis_ref), "entries": entries}
    check_no_host_paths(data, context="ck3_dir.list")  # Leak gate
    return rb.success("WA-DIR-S-003", data)
```

**`tree`** — Recursive directory listing (directories only):
```python
if command == "tree":
    reply, vis_ref = wa_v2.resolve(path, _session_home_root)
    if reply.reply_type != "S":
        return reply
    
    host_path = open_ref(vis_ref)
    dirs = _walk_dirs(host_path, vis_ref.session_absolute, depth)
    
    data = {"target": str(vis_ref), "depth": depth, "directories": dirs}
    check_no_host_paths(data, context="ck3_dir.tree")
    return rb.success("WA-DIR-S-004", data)
```

**Step 6: Register `ck3_dir` in server.py**

Add the `@mcp_safe_tool` decorated `ck3_dir` function in `server.py` that:
1. Gets trace info and creates ReplyBuilder
2. Gets or creates the WorldAdapterV2 instance (lazy singleton, same pattern as v1 `_get_world()`)
3. Delegates to `ck3_dir_impl`
4. Returns the Reply

**Step 7: Write ck3_dir acceptance tests**

Test cases in `tests/test_dir_ops.py`:

| Test | Command | Expected |
|------|---------|----------|
| pwd returns default home | `pwd` | `ROOT_CK3RAVEN_DATA:/` |
| cd changes home | `cd ROOT_REPO`, then `pwd` | `ROOT_REPO:/` |
| cd invalid root | `cd BOGUS` | Invalid reply |
| list home directory | `list` (no path) | Success, entries with session-absolute paths |
| list with explicit path | `list ROOT_REPO:/src` | Success, entries under src/ |
| list non-directory | `list ROOT_REPO:/pyproject.toml` | Invalid — not a directory |
| list non-existent | `list ROOT_REPO:/nonexistent` | Invalid — does not exist |
| tree with depth | `tree ROOT_REPO:/src depth=2` | Directory tree, depth-limited |
| tree default depth 3 | `tree` | Home directory tree, depth=3 |
| No host paths in any output | All commands | Leak detector passes on every Reply.data |
| Host path input rejected | `list C:\Users\...` | Invalid — Invariant A |

**Checkpoint 3 deliverable:** `ck3_dir` all commands working, leak detector triggers correctly, purity gate passes.

---

#### Phase 3 — Purity Gate (also Checkpoint 3)

**Step 8: Create v2 isolation rule**

New arch_lint rule at `linters/arch_lint/rules/v2_isolation.py`:

Scans all `.py` files in `tools/ck3lens_mcp/` and checks:
- If a file imports from `world_adapter_v2`, the file MUST be one of:
  - `world_adapter_v2.py` itself
  - `impl/dir_ops.py` (the `ck3_dir` implementation)
  - `leak_detector.py`
  - Any file matching `*_v2.py`
  - `server.py` (for tool registration only — the `@mcp_safe_tool` wrapper)
- If any other file imports `world_adapter_v2`, the rule fails.

This can be implemented as a simple grep-based check or integrated into the existing arch_lint scanner.

---

### 3.3 Dependency Graph

```
sigil.py (sigil_encrypt, sigil_decrypt)
    ↑
world_adapter_v2.py (VisibilityRef, WorldAdapterV2, open_ref)
    ↑
leak_detector.py (check_no_host_paths)
    ↑
impl/dir_ops.py (ck3_dir_impl, _session_home_root)
    ↑
server.py (ck3_dir registration — @mcp_safe_tool wrapper only)
```

No arrows point toward v1 modules. The isolation is one-directional.

### 3.4 Open Design Detail: Non-Existent But Addressable Paths

The Sprint 0 spec says Invariant D governs visibility, but there are two distinct cases:

1. **Path not addressable** — e.g., `ROOT_FAKE:/foo` or a mod not in the playset. WA returns Invalid.
2. **Path addressable but doesn't exist on disk** — e.g., `ROOT_REPO:/src/nonexistent.py`. WA can resolve it (the root exists, the relative path is valid), but `host_path.exists()` is False.

**Proposed behavior:** WA v2 `resolve()` succeeds if the root/mod is valid — it doesn't check disk existence. The `ck3_dir` commands (`list`, `tree`) check existence themselves and return Invalid if the resolved path doesn't exist on disk. This keeps WA as a pure address resolver (structural) and puts existence checks in the tool (operational).

### 3.5 What Is NOT Touched

Per the isolation mandate:
- `world_adapter.py` (v1) — no changes
- `workspace.py` — no changes
- `unified_tools.py` — no changes
- `enforcement.py` — no changes
- Any existing MCP tool — no changes
- `db_queries.py` — no changes

---

## Appendix A: Session-Absolute Address Grammar (v2)

```
address       = root_address | mod_address | bare_relative
root_address  = ROOT_CATEGORY ":/" rel_path
mod_address   = "mod:" mod_name ":/" rel_path
bare_relative = rel_path                         (resolved against session_home_root)

ROOT_CATEGORY = "ROOT_REPO" | "ROOT_CK3RAVEN_DATA" | "ROOT_GAME"
              | "ROOT_STEAM" | "ROOT_USER_DOCS" | "ROOT_VSCODE"

mod_name      = <any string not containing ":/">
rel_path      = <POSIX-style path segments, no leading />
```

## Appendix B: Reply Codes (New)

| Code | Type | Context | Meaning |
|------|------|---------|---------|
| `WA-DIR-S-001` | S | pwd | Home root returned |
| `WA-DIR-S-002` | S | cd | Home root changed |
| `WA-DIR-S-003` | S | list | Directory listing returned |
| `WA-DIR-S-004` | S | tree | Directory tree returned |
| `WA-DIR-I-001` | I | cd | Unknown root category |
| `WA-DIR-I-002` | I | list/tree | Target is not a directory |
| `WA-DIR-I-003` | I | list/tree | Target does not exist |
| `WA-DIR-I-004` | I | resolve | Host-absolute path rejected (Invariant A) |
| `WA-DIR-I-005` | I | resolve | Unknown mod (not in playset) |
| `WA-DIR-E-001` | E | any | Host path leaked in output (leak detector) |
| `WA-VIS-S-001` | S | resolve | Address resolved successfully |
| `WA-VIS-I-001` | I | resolve | Address not resolvable |
