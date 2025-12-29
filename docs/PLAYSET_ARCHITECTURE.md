# Playset Architecture (Deep Dive)

> **Status:** FINAL (LOCKED)  
> **Date:** December 30, 2025  
> **Purpose:** Detailed specification for playset management in ck3raven/ck3lens

**See also:** [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) for the 5 rules every agent must know

---

## Core Architectural Invariant (LOCKED)

**There is NO permission-check phase in this architecture.**

The responsibilities are strictly separated:

| Layer | Responsibility | Example |
|-------|----------------|---------|
| **Visibility** | What exists / what can be seen? | WorldAdapter.resolve() |
| **Validation** | Is a declaration well-formed? | validate_script_declarations() |
| **Enforcement** | Is this operation allowed right now? | mod_files._enforce_write_boundary() |

**Only ENFORCEMENT may deny execution.**

Any code that denies, short-circuits, or blocks an operation BEFORE the enforcement boundary is a PERMISSION ORACLE and is **forbidden**.

---

## NO-ORACLE RULE (ENFORCED)

No function, method, property, or metadata may answer whether an operation is allowed outside the enforcement boundary.

### Banned Ideas (Regardless of Naming)
- Session-level permission helpers
- Scope-level permission helpers
- Visibility-level permission helpers
- Metadata-based early denies

### Banned Naming Patterns
- `can_*` when used to gate execution
- `is_*` when used to gate execution
- `*_writable` (use `path_under_local_mods` for structural descriptor)
- `*_allowed`
- `*_editable` (except UI hints)

### Exception: UI Hints
The field `ui_hint_potentially_editable` on ResolutionResult is permitted because:
- It is explicitly named as non-authoritative
- It MUST NOT be used in control flow
- It MUST NOT gate execution
- It is for display purposes only (lock icons, etc.)

---

## CANONICAL SOURCES (SINGLE POINTS OF TRUTH)

### For Policy/Permission Decisions: `enforcement.py`

**File:** `tools/ck3lens_mcp/ck3lens/policy/enforcement.py`

ALL "can I do X?" questions MUST go through `enforce_policy()` or `enforce_and_log()`.

```python
from ck3lens.policy.enforcement import enforce_policy, EnforcementRequest, OperationType

result = enforce_policy(EnforcementRequest(
    operation=OperationType.FILE_WRITE,
    mode="ck3lens",
    tool_name="ck3_file",
    mod_name="MSC",
    rel_path="common/traits/zzz_fix.txt",
))

if result.decision != Decision.ALLOW:
    return {"error": result.reason}
```

**NEVER:**
- Implement permission logic elsewhere
- Create parallel permission systems
- Import archived gate functions (hard_gates.py is ARCHIVED)

### For Path Visibility/Resolution: `WorldAdapter`

**File:** `tools/ck3lens_mcp/ck3lens/world_adapter.py`

ALL "can I see X?" or "does X exist in my world?" questions go through `WorldAdapter`.

```python
adapter = LensWorldAdapter(lens, db, ...)
result = adapter.resolve("common/traits/00_traits.txt")

if not result.found:
    raise FileNotFoundError(...)  # NOT PermissionError
```

**Key principle:** If WorldAdapter says NOT_FOUND, the resource doesn't exist in LensWorld.
This is NOT a permission denial - it's visibility.

### Enforcement vs Visibility

| Question | Go To | Returns |
|----------|-------|---------|
| "Does this path exist for me?" | WorldAdapter.is_visible() | True/False |
| "Can I write to this path?" | enforcement.enforce_policy() | ALLOW/DENY/REQUIRE_TOKEN |
| "What mods are in my playset?" | Session.mods[] | List of mods |
| "Where is the local mods folder?" | Session.local_mods_folder | Path |

---

## Core Principle: ONE ARRAY

**A playset has exactly ONE list of mods: `mods[]`**

There are no parallel arrays, no whitelists, no separate concepts.

---

## Simple Rules

### Visibility
**CK3Lens can SEE any mod in the active playset.**

Visibility is determined by PlaysetScope.is_path_in_scope() and WorldAdapter.resolve().

### Editability  
**CK3Lens can EDIT any LOCAL mod in the active playset.**

This is enforced AT THE WRITE BOUNDARY in mod_files.py, NOT queried in advance.

### What is a Local Mod?
A mod is LOCAL if its path is under the **local mods folder**.

```
Default: C:\Users\{user}\Documents\Paradox Interactive\Crusader Kings III\mod
```

**Determination is path-based at enforcement time:**
```python
# In mod_files._enforce_write_boundary():
if not is_under_local_mods_folder(file_path, session.local_mods_folder):
    return (False, "Path outside local_mods_folder")
```

---

## Data Model

### Session (DATA-ONLY)

```python
@dataclass
class Session:
    """Data-only session state. NO permission methods."""
    mods: list[ModEntry]              # All mods in playset
    local_mods_folder: Optional[Path] # Configured boundary
    vanilla_root: Optional[Path]      # Vanilla game path
    playset_id: Optional[int]         # Active playset ID
    playset_name: Optional[str]       # Active playset name
    
    def get_mod(self, name: str) -> Optional[ModEntry]:
        """Lookup only - NOT a permission check."""
        ...
```

### PlaysetScope (VISIBILITY ONLY)

```python
@dataclass
class PlaysetScope:
    """Describes visibility, NOT permissions."""
    vanilla_root: Optional[Path]
    mod_roots: Set[Path]
    local_mods_folder: Optional[Path]
    
    def is_path_in_scope(self, path: Path) -> bool:
        """Visibility check - NOT a permission check."""
        ...
    
    def path_under_local_mods(self, path: Path) -> bool:
        """Structural descriptor - NOT a permission oracle.
        Used for UI hints and filtering only."""
        ...
    
    def get_path_location(self, path: Path) -> tuple[str, Optional[str]]:
        """Describes location - NOT a permission check."""
        ...
```

### ResolutionResult (VISIBILITY + UI HINTS)

```python
@dataclass
class ResolutionResult:
    found: bool
    address: Optional[CanonicalAddress]
    absolute_path: Optional[Path]
    mod_name: Optional[str]
    
    # UI HINT ONLY - explicitly non-authoritative
    # MUST NOT be used in control flow
    ui_hint_potentially_editable: bool = False
    
    error_message: Optional[str]
```

---

## Enforcement Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      MCP Tool Request                            │
│                      ck3_file(command="write", ...)             │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│              STEP 1: VISIBILITY (WorldAdapter)                   │
│                                                                  │
│  result = world.resolve(path)                                   │
│                                                                  │
│  if not result.found:                                           │
│      return NOT_FOUND  ← This is visibility, not permission     │
│                                                                  │
│  # NO check of ui_hint_potentially_editable here!               │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│              STEP 2: POLICY GATE (Contract Check)                │
│                                                                  │
│  EnforcementRequest → enforce_and_log()                         │
│                                                                  │
│  if denied:                                                     │
│      return POLICY_DENY                                         │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│              STEP 3: EXECUTION (mod_files.py)                    │
│                      THE WRITE BOUNDARY                          │
│                                                                  │
│  allowed, error = _enforce_write_boundary(session, file_path)   │
│                                                                  │
│  if not allowed:                                                │
│      return DENY  ← ONLY here can execution be blocked          │
│                                                                  │
│  # Actually write the file                                      │
│  file_path.write_text(content)                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Playset JSON Format

```json
{
  "$schema": "./playset.schema.json",
  "playset_name": "My Playset",
  "vanilla": {
    "version": "1.18.0",
    "path": "C:/Program Files (x86)/Steam/.../Crusader Kings III/game"
  },
  "mods": [
    {
      "name": "Unofficial Patch",
      "path": "C:\\...\\workshop\\...\\2871648329",
      "load_order": 0,
      "enabled": true,
      "steam_id": "2871648329"
    },
    {
      "name": "Mini Super Compatch",
      "path": "C:\\Users\\nateb\\...\\mod\\MiniSuperCompatch",
      "load_order": 116,
      "enabled": true
    }
  ],
  "local_mods_folder": "C:\\Users\\nateb\\...\\Crusader Kings III\\mod"
}
```

**Note:** There is no `local_mods[]` array. Local mods are determined at runtime by checking `mod.path` against `local_mods_folder`.

---

## Derived Values (Computed at Runtime)

| Value | Computation | Where Used |
|-------|-------------|------------|
| `path_under_local_mods` | `path.startswith(local_mods_folder)` | UI hints only |
| `is_path_in_scope` | `path in vanilla_root OR path in mod_roots` | Visibility |
| `mod_roots` | `set(mod.path for mod in mods)` | PlaysetScope |

**These are NEVER used for permission decisions.** Permission is determined ONLY at the write boundary.

---

## Anti-Patterns (BANNED)

| Pattern | Why Banned | Correct Alternative |
|---------|-----------|---------------------|
| `session.can_write_path()` | Permission oracle | Enforce at boundary |
| `if not is_writable: return error` | Early denial | Let enforcement decide |
| `local_mods[]` array | Parallel concept | Derive from `mods[]` + path |
| Permission check before action | Oracle pattern | Enforcement at action |

---

## Summary

The architecture is **locked**:

1. **Visibility describes** - WorldAdapter, PlaysetScope
2. **Validation checks structure** - Script declarations, syntax
3. **Enforcement decides** - mod_files._enforce_write_boundary()
4. **No component asks permission** - No oracles
5. **No component denies early** - Only enforcement boundary

This closes the architectural work.
