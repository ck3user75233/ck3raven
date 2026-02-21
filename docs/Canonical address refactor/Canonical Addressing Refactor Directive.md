# **Sprint 0 Canonical Addressing Refactor — Final Directive (Authoritative)**

**Team** — This is now the authoritative Sprint 0 directive for the WA2 + ck3_dir slice.

**Locked decisions:**

* **Token format:** UUID4 string
* **Token lifetime:** lifetime of current MCP server process / instance
* **Token policy:** always mint new token per resolve
* **Canonical syntax:**
  * `root:<root_key>/<relative_path>`
  * `mod:<ModName>/<relative_path>`

**Note:** This supersedes earlier drafts that used ROOT_X:/... or double-colon forms.

---

## 0) Explanation of Canonical Syntax Change

We are standardizing canonical addressing to:

* `root:repo/common/traits/00_traits.txt`
* `mod:SomeMod/common/traits/00_traits.txt`

### Why this change?

Earlier drafts used:

* `ROOT_REPO:/common/traits/...`
* `mod:SomeMod:/common/traits/...`

We are removing:

1. The ROOT_ prefix
2. The second `:` delimiter

### Rationale

* **Simpler grammar:** `<namespace>:<key>/<path>`
* **Less punctuation** → lower LLM drift risk
* **Still unambiguous:**
  * First colon splits namespace
  * First slash after that splits key from path
* **Closed set enforcement remains intact**
* **No functional loss**

### Canonical Grammar (Locked)

`<namespace> : <key> / <relative_path>`

Where:

* `<namespace>` ∈ { root, mod }
* `<key>`:
  * For **root**: closed set: `repo`, `game`, `steam`, `user_docs`, `ck3raven_data`, `vscode`
  * For **mod**: dynamic mod name from `session.mods`
* `<relative_path>`: normalized POSIX-style relative path (no leading slash required)

**Important:** The `root:` namespace uses v2 shorthand keys only. `root:ROOT_REPO/...` does NOT work — the legacy bridge only handles the `ROOT_REPO:/...` (colon-slash) form and normalizes it to `root:repo/...` on output. Bare relative paths are also rejected — all input must use an explicit namespace prefix.

---

## 1) Single Resolver Principle

We are not using context-encoded function names.

**One canonical entry point:**

```python
wa2.resolve(input_str: str, *, require_exists: bool = True, rb=None) -> tuple[Reply, Optional[VisibilityRef]]
```

**No:**

* resolve_agent_path
* resolve_tool_path
* resolve_dev_path

All behavior differences must be expressed via parameters or result shape.

---

## 2) Canonical Output and Input Normalization

**Canonical output must always be:**

* `root:<key>/<relative_path>`
* `mod:<ModName>/<relative_path>`

### Sprint 0 Input Acceptance (Compatibility Only)

We accept, normalize, and canonicalize:

* `mod:Name/common/...`
* `mod:Name:/common/...`
* `ROOT_REPO:/common/...` (legacy alias if needed)

**But we never emit those forms.** Emitter always produces canonical `root:` / `mod:` format.

**Rejected inputs:**

* Bare relative paths (no namespace prefix)
* Host-absolute paths (e.g., `C:\Users\...`)
* `root:ROOT_REPO/...` (ROOT_ prefix is NOT a valid v2 key)

---

## 3) VisibilityRef — Option B (Opaque Token Registry)

**No encryption. No Sigil. No custom crypto.**

### 3.1 Data Model

```python
@dataclass(frozen=True, slots=True)
class VisibilityRef:
    token: str          # UUID4
    session_abs: str    # canonical root:... or mod:... string

    def __str__(self) -> str:
        return self.session_abs

    def __repr__(self) -> str:
        return f"VisibilityRef({self.session_abs})"
```

**Constraints:**

* No host path stored in object
* Safe to log
* Safe to serialize
* Immutable

### 3.2 Registry

WA2 owns:

* `self._token_registry: Dict[str, Path]`
* token → host_abs_path
* Only WA2 may translate ref to host path
* Missing token → terminal Invalid

### 3.3 Token Policy

* Always mint new UUID4 per resolve
* Registry entries live for MCP server process lifetime
* No persistence across restarts

---

## 4) Memory Management Policy

### Sprint 0 Policy Decision

We will **NOT** implement LRU or size limits in Sprint 0.

**Reason:**

* This is a vertical slice.
* Premature optimization risks scope creep.
* Real-world usage volume must be measured first.

### Hard Guardrail

Add a simple defensive cap:

`MAX_TOKENS = 10_000`

If registry exceeds this size:

* Raise a deterministic error: "Visibility registry capacity exceeded — restart server"
* No eviction logic in Sprint 0.

This prevents silent leak while keeping implementation simple.

---

## 5) Concurrency / Thread Safety

* If the MCP server is strictly single-threaded → no action needed.
* If async or threaded: **Wrap registry access in a lock.**

```python
from threading import Lock
self._registry_lock = Lock()
```

**Protect:**

* Token mint + insert
* host_path lookup

Sprint 0 implementation may assume single-threaded unless confirmed otherwise.

---

## 6) Existence vs Visibility

Unified failure surface.

### Behavior

1. **`resolve(..., require_exists=True)`**
   * Returns `(Invalid Reply, None)` if:
     * Path not within visible roots
     * Path escapes containment
     * Path does not exist
   * Reply code: `WA-RES-I-001`

2. **`resolve(..., require_exists=False)`**
   * Performs **structural validation only** (namespace/key/path containment + syntax).
   * Does not truncate to last existing folder.
   * May return Success even if the target does not exist.
   * VisibilityRef is still minted and registered.

### Existence at the caller level

Callers who need to know whether the target exists can call `wa2.host_path(ref).exists()` after resolution. There is no `exists` field on the resolution result — `resolve()` returns `tuple[Reply, Optional[VisibilityRef]]`, not an intermediate dataclass.

**Note on TOCTOU (Time-of-Check Time-of-Use):**

Existence check is a best-effort snapshot; callers must tolerate races (file may change between check and use). Sprint 0 does not attempt atomic "exists + register + use" semantics.

---

## 7) Session Navigation State

* `_session_home_root` remains module-level in ck3_dir (Sprint 0 only).
* WA2 remains stateless regarding cwd.

---

## 8) cd Semantics (Sprint 0)

**Allowed:**

* `cd root:repo`
* `cd root:game`

**Not allowed:**

* `cd root:repo/some/subdir`

Subdirectory homing is explicitly out of scope.

---

## 9) Reference Implementation Sketch (Current API)

> Updated 2026-02-21 to reflect actual implemented API.

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Dict
import uuid
from threading import Lock

from ck3raven.core.reply import Reply

MAX_TOKENS = 10_000

@dataclass(frozen=True, slots=True)
class VisibilityRef:
    token: str
    session_abs: str

    def __str__(self):
        return self.session_abs

    def __repr__(self):
        return f"VisibilityRef({self.session_abs})"


class WorldAdapterV2:
    """
    Mode-agnostic: does NOT store agent mode. resolve() reads mode
    dynamically via _get_mode() on every call. If mode is None (agent
    not initialized), returns WA-SYS-I-001.

    Construction: WorldAdapterV2(session=..., roots=...)
    - session: Session object with .mods list and .get_mod() method
              session.mods is THE authoritative mod list (Canonical Architecture Rule 3)
    - roots: dict of v2 root key -> host-absolute Path
             Keys must be from VALID_ROOT_KEYS: {repo, game, steam, user_docs, ck3raven_data, vscode}
    """

    def __init__(self, *, session: Any, roots: dict[str, Path]):
        self._session = session
        self._roots: dict[str, Path] = dict(roots)
        self._token_registry: Dict[str, Path] = {}
        self._registry_lock = Lock()

    def resolve(
        self, input_str: str, *, require_exists: bool = True, rb: Any = None,
    ) -> tuple[Reply, Optional[VisibilityRef]]:
        """
        Resolve a canonical address.

        Returns:
            (Reply, VisibilityRef) on success — Reply.data["resolved"] is the
            session-absolute path. Reply.data also contains root_key, subdirectory,
            relative_path for enforcement and matrix lookup.

            (Reply, None) on failure — Reply is Invalid (WA-RES-I-001).
        """
        ...

    def host_path(self, ref: VisibilityRef) -> Optional[Path]:
        """Recover host-absolute Path from a VisibilityRef token.
        Only WA2 owns this — callers must go through WA2 to get a real path."""
        with self._registry_lock:
            return self._token_registry.get(ref.token)
```
