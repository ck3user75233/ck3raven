# **Sprint 0 Canonical Addressing Refactor — Final Directive (Authoritative)**

**Team** — This is now the authoritative Sprint 0 directive for the WA2 \+ ck3\_dir slice.

**Locked decisions:**

* **Token format:** UUID4 string  
* **Token lifetime:** lifetime of current MCP server process / instance  
* **Token policy:** always mint new token per resolve  
* **Canonical syntax:**  
  * root:\<root\_key\>/\<relative\_path\>  
  * mod:\<ModName\>/\<relative\_path\>

**Note:** This supersedes earlier drafts that used ROOT\_X:/... or double-colon forms.

## ---

**0\) Explanation of Canonical Syntax Change**

We are standardizing canonical addressing to:

* root:repo/common/traits/00\_traits.txt  
* mod:SomeMod/common/traits/00\_traits.txt

### **Why this change?**

Earlier drafts used:

* ROOT\_REPO:/common/traits/...  
* mod:SomeMod:/common/traits/...

We are removing:

1. The ROOT\_ prefix  
2. The second : delimiter

### **Rationale**

* **Simpler grammar:** \<namespace\>:\<key\>/\<path\>  
* **Less punctuation** → lower LLM drift risk  
* **Still unambiguous:**  
  * First colon splits namespace  
  * First slash after that splits key from path  
* **Closed set enforcement remains intact**  
* **No functional loss**

### **Canonical Grammar (Locked)**

\<namespace\> : \<key\> / \<relative\_path\>

Where:

* \<namespace\> ∈ { root, mod }  
* \<key\>:  
  * For **root**: closed set (repo, game, steam, ck3raven\_data, local\_user\_docs, etc.)  
  * For **mod**: dynamic mod name  
* \<relative\_path\>: normalized POSIX-style relative path (no leading slash required)

## ---

**1\) Single Resolver Principle**

We are not using context-encoded function names.

**One canonical entry point:**

Python

wa2.resolve(input\_str: str, \*, require\_exists: bool \= True)

**No:**

* resolve\_agent\_path  
* resolve\_tool\_path  
* resolve\_dev\_path

All behavior differences must be expressed via parameters or result shape.

## ---

**2\) Canonical Output and Input Normalization**

**Canonical output must always be:**

* root:\<key\>/\<relative\_path\>  
* mod:\<ModName\>/\<relative\_path\>

### **Sprint 0 Input Acceptance (Compatibility Only)**

We accept, normalize, and canonicalize:

* mod:Name/common/...  
* mod:Name:/common/...  
* ROOT\_REPO:/common/... (legacy alias if needed)

**But we never emit those forms.** Emitter always produces canonical root: / mod: format.

## ---

**3\) VisibilityRef — Option B (Opaque Token Registry)**

**No encryption. No Sigil. No custom crypto.**

### **3.1 Data Model**

Python

@dataclass(frozen=True, slots=True)  
class VisibilityRef:  
    token: str          \# UUID4  
    session\_abs: str    \# canonical root:... or mod:... string

    def \_\_str\_\_(self) \-\> str:  
        return self.session\_abs

    def \_\_repr\_\_(self) \-\> str:  
        return f"VisibilityRef({self.session\_abs})"

**Constraints:**

* No host path stored in object  
* Safe to log  
* Safe to serialize  
* Immutable

### **3.2 Registry**

WA2 owns:

* self.\_token\_registry: Dict\[str, Path\]  
* token → host\_abs\_path  
* Only WA2 may translate ref to host path  
* Missing token → terminal Invalid

### **3.3 Token Policy**

* Always mint new UUID4 per resolve  
* Registry entries live for MCP server process lifetime  
* No persistence across restarts

## ---

**4\) Memory Management Policy**

### **Sprint 0 Policy Decision**

We will **NOT** implement LRU or size limits in Sprint 0\.

**Reason:**

* This is a vertical slice.  
* Premature optimization risks scope creep.  
* Real-world usage volume must be measured first.

### **Hard Guardrail**

Add a simple defensive cap:

MAX\_TOKENS \= 10\_000

If registry exceeds this size:

* Raise a deterministic error: "Visibility registry capacity exceeded — restart server"  
* No eviction logic in Sprint 0\.

This prevents silent leak while keeping implementation simple.

## ---

**5\) Concurrency / Thread Safety**

* If the MCP server is strictly single-threaded → no action needed.  
* If async or threaded: **Wrap registry access in a lock.**

Python

from threading import Lock

self.\_registry\_lock \= Lock()

**Protect:**

* Token mint \+ insert  
* host\_path lookup

Sprint 0 implementation may assume single-threaded unless confirmed otherwise.

## ---

**6\) Existence vs Visibility**

Unified failure surface with explicit existence metadata.

### **Behavior**

1. **resolve(..., require\_exists=True)**  
   * Returns Invalid if:  
     * Path not within visible roots  
     * Path escapes containment  
     * Path does not exist  
   * Error message (agent-visible): **"Invalid path / not found"**  
2. **resolve(..., require\_exists=False)**  
   * Performs **structural validation only** (namespace/key/path containment \+ syntax).  
   * Does not truncate to last existing folder.  
   * May return Success even if the target does not exist.

### **Resolution Metadata**

Add exists: bool to VisibilityResolution on success.

* exists=True: host path exists at resolve time.  
* exists=False: host path does not exist.

**Note on TOCTOU (Time-of-Check Time-of-Use):**

Existence check is a best-effort snapshot; callers must tolerate races (file may change between check and use). Sprint 0 does not attempt atomic “exists \+ register \+ use” semantics.

## ---

**7\) Session Navigation State**

* \_session\_home\_root remains module-level in ck3\_dir (Sprint 0 only).  
* WA2 remains stateless regarding cwd.

## ---

**8\) cd Semantics (Sprint 0\)**

**Allowed:**

* cd root:repo  
* cd root:game

**Not allowed:**

* cd root:repo/some/subdir

Subdirectory homing is explicitly out of scope.

## ---

**9\) Reference Implementation Sketch (Final)**

Python

from dataclasses import dataclass  
from pathlib import Path  
from typing import Optional, Dict  
import uuid  
from threading import Lock

MAX\_TOKENS \= 10\_000

@dataclass(frozen=True, slots=True)  
class VisibilityRef:  
    token: str  
    session\_abs: str

    def \_\_str\_\_(self):  
        return self.session\_abs

    def \_\_repr\_\_(self):  
        return f"VisibilityRef({self.session\_abs})"

@dataclass(frozen=True, slots=True)  
class VisibilityResolution:  
    ok: bool  
    ref: Optional\[VisibilityRef\] \= None  
    root\_category: Optional\[str\] \= None  
    relative\_path: Optional\[str\] \= None  
    exists: Optional\[bool\] \= None      \# NEW: explicit existence signal on success  
    error\_message: Optional\[str\] \= None

class WorldAdapterV2:  
    def \_\_init\_\_(self, \*, roots: dict, mod\_paths: dict):  
        self.\_roots \= roots  
        self.\_mod\_paths \= mod\_paths  
        self.\_token\_registry: Dict\[str, Path\] \= {}  
        self.\_registry\_lock \= Lock()

    def resolve(self, input\_str: str, \*, require\_exists: bool \= True) \-\> VisibilityResolution:  
        parsed \= self.\_parse\_and\_compute(input\_str)  
        if parsed is None:  
            return VisibilityResolution(ok=False, error\_message="Invalid path / not found")

        session\_abs, host\_abs, root\_category, rel\_path \= parsed

        \# TOCTOU Note: exists\_now is advisory; file may change after check.  
        \# Sprint 0 does not enforce strict atomicity here.  
        exists\_now \= host\_abs.exists()

        if require\_exists and not exists\_now:  
            return VisibilityResolution(ok=False, error\_message="Invalid path / not found")

        token \= str(uuid.uuid4())

        with self.\_registry\_lock:  
            if len(self.\_token\_registry) \>= MAX\_TOKENS:  
                return VisibilityResolution(  
                    ok=False,  
                    error\_message="Visibility registry capacity exceeded — restart server"  
                )  
            self.\_token\_registry\[token\] \= host\_abs

        return VisibilityResolution(  
            ok=True,  
            ref=VisibilityRef(token=token, session\_abs=session\_abs),  
            root\_category=root\_category,  
            relative\_path=rel\_path,  
            exists=exists\_now,           \# NEW  
        )

    def host\_path(self, ref: VisibilityRef) \-\> Optional\[Path\]:  
        with self.\_registry\_lock:  
            return self.\_token\_registry.get(ref.token)

    def \_parse\_and\_compute(self, input\_str: str):  
        \# returns (session\_abs, host\_abs: Path, root\_category, rel\_path) or None  
        raise NotImplementedError  
