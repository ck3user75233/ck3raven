# B0 Proof Bundle: Symbols Lock v2 (Playset Identity + Symbol Identity)

> **Generated:** 2026-01-20  
> **Contract:** v1-2026-01-20-7f05dd (ROOT_REPO)  
> **Schema Version:** v2 (B0-corrected)

---

## Summary

All B0 corrections have been implemented and verified:

| B0 Task | Status | Evidence |
|---------|--------|----------|
| B0.1: Playset identity metadata | ✅ PASS | Proof 1 |
| B0.2: Remove DISTINCT, fix ORDER BY | ✅ PASS | SQL verified |
| B0.3: Symbol identity = (type, scope, name) | ✅ PASS | Proof 5 |
| B0.4: check_symbol_identities_exist() API | ✅ PASS | Proof 4 |
| B0.5: Proof bundle | ✅ PASS | This document |

---

## Proof 1: Playset Identity in Snapshot

**Requirement:** Snapshot includes `playset_cvids`, `playset_mods`, and `playset_hash`.

**Evidence:**
```
=== B0.5 PROOF 1: Playset Identity ===
CVIDs: 123
Mods: 123
Playset hash: sha256:d643953660fddf9433c0f2072bc703ba9f7e7004b46497c1879f2b47a
```

**JSON Structure:**
```json
{
  "playset": {
    "playset_name": "MSC",
    "cvids": [1, 2, 3, ...],  // 123 entries
    "mods": [
      {"cvid": 1, "mod_id": null, "name": "vanilla", "workshop_id": null, "source_root": "..."},
      {"cvid": 2, "mod_id": "...", "name": "...", "workshop_id": "...", "source_root": "..."},
      // ... 122 more entries
    ],
    "playset_hash": "sha256:d643953660fddf9433c0f2072bc703ba9f7e7004b46497c1879f2b47aea08e75"
  }
}
```

**Result:** ✅ PASS

---

## Proof 2: Determinism

**Requirement:** Two consecutive runs produce identical symbols_hash values.

**Evidence:**
```
=== B0.5 PROOF 2: Determinism ===
Run 1 symbols_hash: sha256:23401bd20bee3e0cbcb52cbdaa9bd35da482890bb57fb3560a89b844d
Run 2 symbols_hash: sha256:23401bd20bee3e0cbcb52cbdaa9bd35da482890bb57fb3560a89b844d
Match: True
```

**Test:**
```bash
python -m tools.compliance.symbols_lock snapshot proof-b0-test-1
python -m tools.compliance.symbols_lock snapshot proof-b0-test-2
python -m tools.compliance.symbols_lock diff proof-b0-test-1 proof-b0-test-2
```

**Output:**
```
=== Symbols Diff Summary ===
Baseline: proof-b0-test-1_2026-01-20T08-42-41 (sha256:23401bd20...)
Current:  proof-b0-test-2_2026-01-20T08-42-58 (sha256:23401bd20...)
Hashes match: True
Playset match: True

No changes detected.
```

**Result:** ✅ PASS

---

## Proof 3: Playset Drift Detection (verify-playset)

**Requirement:** `verify-playset` command confirms playset hasn't drifted.

**Evidence:**
```bash
$ python -m tools.compliance.symbols_lock verify-playset proof-b0-test-1
[OK] Playset verified: sha256:d643953660fddf9433c0f2072bc703ba9f7e7004b46497c1879f2b47aea08e75
```

**How drift detection works:**
- `check_playset_drift()` compares baseline and current playset
- Checks: CVIDs match, hash matches
- On drift: returns `PLAYSET_DRIFT` error with details

**Result:** ✅ PASS

---

## Proof 4: check_symbol_identities_exist() API

**Requirement:** API correctly identifies existing and non-existing symbols.

**Evidence:**
```bash
$ python -m tools.compliance.symbols_lock check-exists proof-b0-final trait::brave trait::craven trait::FAKE_NOT_REAL

Exists check saved: .../proof-b0-final.exists_check.json
  Playset hash: sha256:d643953660fddf9433c0f2072...
  Result hash: sha256:e5df1065faa01c2a68a793fa7...

Results:
  [N] trait::FAKE_NOT_REAL
  [Y] trait::brave
  [Y] trait::craven
```

**JSON Artifact:**
```json
{
  "contract_id": "proof-b0-final",
  "checked_at": "2026-01-20T...",
  "playset_hash": "sha256:d643953660...",
  "identities_checked": 3,
  "results": {
    "trait::FAKE_NOT_REAL": false,
    "trait::brave": true,
    "trait::craven": true
  },
  "result_hash": "sha256:e5df1065..."
}
```

**Result:** ✅ PASS

---

## Proof 5: Override Handling

**Requirement:** Same symbol defined in multiple mods counts as 1 identity but multiple provenance records.

**Evidence:**
```
=== B0.5 PROOF 5: Override Handling ===
Identity count: 107,841
Provenance count: 145,542
Override count: 37,701
Ratio: 1.35
```

**Analysis:**
- 107,841 unique symbol identities (type:scope:name)
- 145,542 total provenance records (all definitions across all mods)
- 37,701 records are overrides (same identity defined in different mod)
- Average 1.35 definitions per identity

**Example: trait::brave**
- Appears in vanilla and multiple mods
- Counts as **1 identity** for NST purposes
- Has **multiple provenance records** for conflict detection

**Why this matters:**
- NST only cares about NEW identities (symbols that didn't exist before)
- If mod A and mod B both define `trait::brave`, that's still 1 identity
- Provenance records allow conflict detection while keeping identity counts accurate

**Result:** ✅ PASS

---

## SQL Corrections Applied (B0.2)

### Before (v1 - INCORRECT):
```sql
SELECT DISTINCT s.name, s.symbol_type, ...
ORDER BY s.symbol_type, s.name
```

**Problems:**
- `DISTINCT` hides symbol collisions
- Weak `ORDER BY` doesn't ensure deterministic results

### After (v2 - CORRECT):
```sql
SELECT s.symbol_id, s.name, s.symbol_type, s.scope, s.line_number,
       f.content_version_id, f.relpath
FROM symbols s
JOIN asts a ON s.ast_id = a.ast_id
JOIN files f ON a.content_hash = f.content_hash
WHERE f.content_version_id IN (...)
  AND f.deleted = 0
ORDER BY f.content_version_id, f.relpath, s.symbol_type, 
         s.scope, s.name, s.line_number, s.symbol_id
```

**Fixes:**
- No `DISTINCT` - returns all provenance records
- Full deterministic `ORDER BY` with 7 columns including `symbol_id` tie-breaker
- Includes `scope` for proper identity computation

---

## Symbol Identity Definition (B0.3)

```python
@dataclass
class SymbolIdentity:
    """
    Canonical symbol identity for NST (New Symbol Tracking).
    
    Identity = (symbol_type, scope, name)
    """
    symbol_type: str
    scope: Optional[str]
    name: str
    
    def key(self) -> str:
        """Canonical string key for this identity."""
        return f"{self.symbol_type}:{self.scope or ''}:{self.name}"
```

**Key distinction:**
- **Identity** = (type, scope, name) - for NST "is this new?" checks
- **Provenance** = full source info - for conflict detection and reporting

---

## File Artifacts

| Artifact | Path |
|----------|------|
| symbols_lock.py (v2) | `tools/compliance/symbols_lock.py` |
| Snapshot 1 | `artifacts/symbols/proof-b0-test-1_2026-01-20T08-42-41.symbols.json` |
| Snapshot 2 | `artifacts/symbols/proof-b0-test-2_2026-01-20T08-42-58.symbols.json` |
| Exists check | `artifacts/symbols/proof-b0-final.exists_check.json` |

---

## Ready for Phase 2

All B0 corrections have been implemented and verified. The symbols lock system now correctly:

1. ✅ Includes full playset identity in snapshots
2. ✅ Uses deterministic SQL ordering (no DISTINCT)
3. ✅ Defines symbol identity as (type, scope, name)
4. ✅ Provides check_symbol_identities_exist() API
5. ✅ Detects playset drift for contract closure

**Phase 2 can now proceed with NST gates using this corrected foundation.**
