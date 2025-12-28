# LensWorld Architecture

> **Status:** CANONICAL  
> **Last Updated:** December 28, 2025  
> **Scope:** Visibility layer for CK3 Lens agent modes

---

## 1. What LensWorld Is

**LensWorld is a hard visibility guardrail that defines the complete and only world an agent is capable of perceiving.**

LensWorld determines:
- What files exist
- What mods exist
- What paths can be referenced
- What search results may appear

**If something is outside the lens, it does not exist.**

---

## 2. What LensWorld Is Not

LensWorld is **not**:
- A permission system
- A mutation gate
- A substitute for policy

**LensWorld never decides whether an action is allowed.**

---

## 3. Lens vs Policy: Orthogonal Layers

LensWorld and Policy are **orthogonal layers**:

| Layer | Question Answered | Enforcement |
|-------|-------------------|-------------|
| **LensWorld** | What exists and can be referenced? | Visibility filtering |
| **Policy** | What actions are permitted on those references? | Mutation control |

LensWorld is a **hard guardrail on visibility**.  
Policy is a **hard gate on mutation and risk**.

Both apply in ck3lens, but to **different dimensions** of behavior.

### Semantic Separation

| Failure Type | Cause | Result |
|--------------|-------|--------|
| Visibility failure | Reference not in LensWorld | `NOT_FOUND` |
| Mutation failure | Action violates policy | `POLICY_VIOLATION` |

**These cases must never be conflated.**

---

## 4. Architecture

### 4.1 WorldAdapter Interface

`WorldAdapter` is a **FACADE**, not a replacement for existing systems.

It composes:
- `PlaysetLens` - Database query filtering by content_version_id
- `PlaysetScope` - Filesystem path validation
- `DBQueries` - Database access layer
- Utility roots - CK3 logs, saves, crash dumps

It enforces **visibility filtering only**.

**Rule:**
> WorldAdapter decides **what exists**.  
> Policy decides **what may be done** to what exists.

### 4.2 WorldRouter

`WorldRouter` is the **single canonical injection point** for obtaining WorldAdapters.

All MCP tools must:
1. Call `get_world()` to obtain the adapter
2. Resolve references through the adapter
3. Apply policy **only after** reference resolution

**Forbidden patterns:**
- Tool-local agent mode checks
- Tool-local visibility logic
- Policy checks on unresolved paths

### 4.3 Two Implementations

| Adapter | Mode | Visibility | Writability |
|---------|------|------------|-------------|
| `LensWorldAdapter` | ck3lens | Active playset only | Local mods + WIP |
| `DevWorldAdapter` | ck3raven-dev | Full ck3raven source | Source + WIP |

---

## 5. Address Scheme

### 5.1 Canonical Addresses

All references are translated to canonical addresses:

| Prefix | Description | Example |
|--------|-------------|---------|
| `mod:<id>/` | Mod file by mod identifier | `mod:MSC/common/traits/fix.txt` |
| `vanilla:/` | Vanilla game file | `vanilla:/common/traits/00_traits.txt` |
| `utility:/` | CK3 utility file | `utility:/logs/error.log` |
| `ck3raven:/` | ck3raven source | `ck3raven:/src/parser/lexer.py` |
| `wip:/` | WIP workspace | `wip:/analysis.py` |

### 5.2 Raw Path Translation

**Decision:** Addresses are **optional**. Raw paths are allowed as input.

- Raw paths are immediately translated into canonical forms
- If translation fails → `NOT_FOUND`
- No breaking change required

**Rule:**
> Agents may provide raw paths.  
> Tools must never operate on raw paths directly.

---

## 6. Visibility by Mode

### 6.1 ck3lens Mode (LensWorldAdapter)

| Domain | Visible | Writable |
|--------|---------|----------|
| Active playset mods (DB) | ✅ | ❌ |
| Active local mods (FS) | ✅ | ✅ (with contract) |
| Active workshop mods (FS) | ✅ | ❌ |
| Vanilla game | ✅ | ❌ |
| CK3 utility files | ✅ | ❌ |
| ck3raven source | ✅ (bug reports) | ❌ |
| WIP workspace | ✅ | ✅ |
| Inactive mods | ❌ | ❌ |
| Arbitrary filesystem | ❌ | ❌ |

### 6.2 ck3raven-dev Mode (DevWorldAdapter)

| Domain | Visible | Writable |
|--------|---------|----------|
| ck3raven source | ✅ | ✅ (with contract) |
| WIP workspace | ✅ | ✅ |
| Vanilla game | ✅ | ❌ |
| All mod content | ✅ (read-only) | ❌ (absolute prohibition) |
| CK3 utility files | ✅ | ❌ |

**Absolute Prohibition:** ck3raven-dev can **never** write to any mod files.

---

## 7. Policy Interaction

### 7.1 Policy Applies After Resolution

Policy enforcement runs **only after** LensWorld resolution succeeds.

```
Reference → LensWorld.resolve() → Found? → Policy.evaluate() → Action
                                    ↓
                               NOT_FOUND
                           (policy never runs)
```

### 7.2 Examples

| Scenario | LensWorld | Policy | Result |
|----------|-----------|--------|--------|
| Search inactive mod | NOT_FOUND | N/A | Reference not found |
| Read active workshop mod | Found | Read allowed | Success |
| Write to workshop mod | Found | Write denied | Policy violation |
| Write to local mod (no contract) | Found | Write denied | Policy violation |
| Write to local mod (with contract) | Found | Write allowed | Success |

---

## 8. Implementation Files

| File | Purpose |
|------|---------|
| `ck3lens/world_adapter.py` | WorldAdapter interface, LensWorldAdapter, DevWorldAdapter |
| `ck3lens/world_router.py` | WorldRouter, get_world() |
| `ck3lens/playset_scope.py` | PlaysetScope - filesystem path validation |
| `ck3lens/db_queries.py` | PlaysetLens - database query filtering |
| `ck3lens/agent_mode.py` | Agent mode detection and persistence |

---

## 9. Usage in MCP Tools

### 9.1 Correct Pattern

```python
from ck3lens.world_router import get_world

@mcp_tool()
async def ck3_example_tool(path: str):
    # 1. Get world adapter
    world = get_world(db=db, lens=lens, scope=scope)
    
    # 2. Resolve reference
    result = world.resolve(path)
    
    # 3. Handle NOT_FOUND
    if not result.found:
        return {"error": result.error_message}  # NOT DENY!
    
    # 4. For mutations, check writability (policy)
    if wants_to_write and not result.is_writable:
        return {"error": "Policy violation: target is not writable"}
    
    # 5. Proceed with operation using result.absolute_path
    ...
```

### 9.2 Anti-Patterns (Forbidden)

```python
# ❌ WRONG: Tool-local mode check
mode = get_agent_mode()
if mode == "ck3lens":
    # custom visibility logic
    
# ❌ WRONG: Policy check before resolution
if not policy.allows(path):
    return {"error": "Access denied"}

# ❌ WRONG: Operating on raw paths
with open(raw_path) as f:  # Should use result.absolute_path
```

---

## 10. Design Goals

LensWorld ensures ck3lens:
- Cannot accidentally reason about out-of-scope content
- Cannot see unsafe or irrelevant parts of the system
- Does not rely on denials for safety

Policy ensures ck3lens:
- Cannot mutate without explicit intent, scope, and approval
- Leaves an auditable trail for all risk-bearing actions

**The world ends at the lens boundary.**  
**Control begins at the policy boundary.**

---

## 11. Future Work

- [ ] Full VFS abstraction (aspirational, not required for v1)
- [ ] Address autocomplete in tools
- [ ] Lens-aware error messages throughout
- [ ] Tool migration to WorldRouter pattern
