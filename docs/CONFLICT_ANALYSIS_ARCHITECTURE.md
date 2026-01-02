# Conflict Analysis Architecture

> **Status:** CANONICAL  
> **Last Updated:** January 2, 2026  
> **Purpose:** Authoritative specification for conflict detection

---

## Overview

Conflict analysis detects when multiple mods in a playset modify the same content. There are two levels:

1. **File-level conflicts** - Multiple mods have files at the same relative path
2. **Symbol-level conflicts** - Multiple mods define the same symbol/block ID

---

## Canonical Input/Output

```
INPUT:  mods[] from active playset session (each mod has a cvid)
OUTPUT: List of conflicts found between those mods

NO playset_id needed. Just use cvids from session.mods[].
```

The `session.mods[]` array contains `ModEntry` objects:
- `mods[0]` = vanilla (always present)
- `mods[1:]` = user mods in load order
- Each has `.cvid` (content_version_id) once resolved

---

## File-Level Conflicts

**Definition:** Two or more mods have files at the same `relpath`.

### Detection Query

```sql
SELECT 
    relpath,
    GROUP_CONCAT(content_version_id) as cvids,
    COUNT(DISTINCT content_version_id) as mod_count
FROM files 
WHERE content_version_id IN (?, ?, ?, ...)  -- cvids from mods[]
  AND deleted = 0
GROUP BY relpath 
HAVING COUNT(DISTINCT content_version_id) > 1
```

### Prefix Analysis

CK3's load order means files are loaded alphabetically within each folder:

| Pattern | Meaning |
|---------|---------|
| `foo.txt` | Original file (often vanilla) |
| `zzz_foo.txt` | Loads LAST, wins for OVERRIDE types |
| `00_foo.txt` | Loads FIRST, wins for FIOS types (GUI) |
| `prefix_foo.txt` | Attempts partial merge/override of `foo.txt` |

**Prefix detection:**
- `zzz_[original].txt` -> targets `[original].txt`
- `[prefix]_[original].txt` -> targets `[original].txt`

When multiple mods use prefixes targeting the same original file, that's a **file-level conflict**.

### Conflict Types

| Scenario | Conflict Type |
|----------|---------------|
| Mod A has `foo.txt`, Mod B has `foo.txt` | FULL OVERWRITE conflict |
| Mod A has `foo.txt`, Mod B has `zzz_foo.txt` | Intentional override (may be OK) |
| Mod A has `zzz_foo.txt`, Mod B has `zzz_foo.txt` | PREFIX conflict (both trying to override) |

---

## Symbol-Level Conflicts

**Definition:** Two or more mods define the same symbol (trait, event, decision, etc.)

### Detection Query

```sql
SELECT 
    name,
    symbol_type,
    GROUP_CONCAT(content_version_id) as cvids,
    COUNT(DISTINCT content_version_id) as mod_count
FROM symbols 
WHERE content_version_id IN (?, ?, ?, ...)  -- cvids from mods[]
GROUP BY name, symbol_type 
HAVING COUNT(DISTINCT content_version_id) > 1
```

### Symbol vs Reference

| Table | Purpose | Conflicts? |
|-------|---------|------------|
| `symbols` | Definitions (where something is created) | YES - multiple definitions = conflict |
| `refs` | References (where something is used) | NO - multiple uses are fine |

A symbol conflict means the same ID is **defined** in multiple mods. References (usages) of that symbol are not conflicts.

---

## Implementation Pattern

```python
def detect_conflicts(session: Session, db: DBQueries) -> dict:
    # Get cvids from session.mods[]
    cvids = [m.cvid for m in session.mods if m.cvid is not None]
    
    if not cvids:
        return {"error": "No mods with cvids in session"}
    
    placeholders = ",".join("?" * len(cvids))
    
    # File-level conflicts
    file_conflicts = db.conn.execute(f\"\"\"
        SELECT relpath, GROUP_CONCAT(content_version_id) as cvids,
               COUNT(DISTINCT content_version_id) as mod_count
        FROM files 
        WHERE content_version_id IN ({placeholders}) AND deleted = 0
        GROUP BY relpath HAVING mod_count > 1
    \"\"\", cvids).fetchall()
    
    # Symbol-level conflicts
    symbol_conflicts = db.conn.execute(f\"\"\"
        SELECT name, symbol_type, GROUP_CONCAT(content_version_id) as cvids,
               COUNT(DISTINCT content_version_id) as mod_count
        FROM symbols 
        WHERE content_version_id IN ({placeholders})
        GROUP BY name, symbol_type HAVING mod_count > 1
    \"\"\", cvids).fetchall()
    
    return {
        "file_conflicts": [dict(r) for r in file_conflicts],
        "symbol_conflicts": [dict(r) for r in symbol_conflicts],
    }
```

---

## What This Architecture Does NOT Do

1. **No playset_id** - Conflicts are between mods in session.mods[], not database playsets
2. **No impact assessment** - Just detection, not "is this conflict bad?"
3. **No load-order resolution** - Just identifies conflicts, not who wins
4. **No cross-playset analysis** - Only analyzes the active playset

---

## Related Documents

- CANONICAL_ARCHITECTURE.md - Overall architecture
- 05_ACCURATE_MERGE_OVERRIDE_RULES.md - CK3 merge policies
- 06_CONTAINER_MERGE_OVERRIDE_TABLE.md - Content type behaviors
