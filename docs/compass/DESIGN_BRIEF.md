# CK3 Compass: Design Brief

> **Status:** Planned  
> **Author:** AI Agent  
> **Date:** December 24, 2025

---

## Project Identity

**Name:** ck3compass  
**Tagline:** *Navigate between map worlds*  
**Purpose:** Enable automated and AI-assisted compatching of mods across different CK3 map systems

---

## Architecture

### Integration with ck3raven

ck3compass is **not a separate project** - it's a new capability within ck3raven:

```
ck3raven/
├── src/ck3raven/
│   ├── compass/                    # NEW: Compass module
│   │   ├── __init__.py
│   │   ├── mapping.py              # Mapping table management
│   │   ├── extractor.py            # Extract mappable entities from DB
│   │   ├── matcher.py              # Matching algorithms
│   │   └── converter.py            # Apply mappings to file content
│   │
│   ├── db/
│   │   ├── schema.py               # Add compass tables
│   │   └── compass_queries.py      # NEW: Compass-specific queries
│   │
│   └── resolver/                   # Existing - used for conflict detection
│
├── tools/ck3lens_mcp/
│   └── server.py                   # Add ck3_compass_* tools
│
└── docs/compass/                   # This documentation
```

---

## Database Schema Additions

### Map Systems Table

```sql
CREATE TABLE map_systems (
    map_system_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,           -- 'vanilla', 'more_bookmarks_plus'
    display_name TEXT,                   -- 'More Bookmarks+'
    content_version_id INTEGER,          -- FK to content_versions
    steam_id TEXT,                       -- '2216670956'
    version TEXT,                        -- '1.3'
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### Title Mappings

```sql
CREATE TABLE compass_title_mappings (
    mapping_id INTEGER PRIMARY KEY,
    source_system_id INTEGER NOT NULL,   -- FK to map_systems
    target_system_id INTEGER NOT NULL,   -- FK to map_systems
    source_title TEXT NOT NULL,          -- 'c_santiago'
    target_title TEXT,                   -- 'c_tui' (NULL if no equivalent)
    mapping_type TEXT NOT NULL,          -- 'exact', 'renamed', 'split', 'merged', 'deleted', 'new'
    confidence REAL DEFAULT 1.0,         -- 0.0-1.0
    evidence TEXT,                       -- JSON: why this mapping was made
    reviewed_by TEXT,                    -- NULL = auto-generated
    reviewed_at TEXT,
    UNIQUE(source_system_id, target_system_id, source_title)
);
```

### Province Mappings

```sql
CREATE TABLE compass_province_mappings (
    mapping_id INTEGER PRIMARY KEY,
    source_system_id INTEGER NOT NULL,
    target_system_id INTEGER NOT NULL,
    source_province_id INTEGER NOT NULL,
    target_province_id INTEGER,          -- NULL if deleted
    source_name TEXT,                    -- From definition.csv
    target_name TEXT,
    mapping_type TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    UNIQUE(source_system_id, target_system_id, source_province_id)
);
```

### Holy Site Mappings

```sql
CREATE TABLE compass_holy_site_mappings (
    mapping_id INTEGER PRIMARY KEY,
    source_system_id INTEGER NOT NULL,
    target_system_id INTEGER NOT NULL,
    holy_site_key TEXT NOT NULL,         -- 'santiago', 'jerusalem'
    source_county TEXT,                  -- 'c_santiago'
    target_county TEXT,                  -- 'c_tui'
    source_barony TEXT,
    target_barony TEXT,
    mapping_type TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    UNIQUE(source_system_id, target_system_id, holy_site_key)
);
```

### Region Mappings

```sql
CREATE TABLE compass_region_mappings (
    mapping_id INTEGER PRIMARY KEY,
    source_system_id INTEGER NOT NULL,
    target_system_id INTEGER NOT NULL,
    source_region TEXT NOT NULL,
    target_region TEXT,
    mapping_type TEXT NOT NULL,
    notes TEXT,
    UNIQUE(source_system_id, target_system_id, source_region)
);
```

---

## Playset Strategy

Playsets enable isolated comparisons:

| Playset | Contents | Purpose |
|---------|----------|---------|
| `vanilla_baseline` | Vanilla only | Reference baseline |
| `mb_plus_isolated` | Vanilla + MB+ only | Pure MB+ vs vanilla diff |
| `ibl_isolated` | Vanilla + IBL only | Pure IBL vs vanilla diff |
| `msc_active` | Active modding playset | Normal work |

Each map system gets its own isolated playset for clean extraction.

---

## Mapping Types

| Type | Description | Example |
|------|-------------|---------|
| `exact` | Same ID, same meaning | `k_england` → `k_england` |
| `renamed` | Different ID, same territory | `c_santiago` → `c_tui` |
| `split` | One title became multiple | `d_wessex` → `d_wessex`, `d_hampshire` |
| `merged` | Multiple titles became one | `d_x`, `d_y` → `d_combined` |
| `deleted` | Title removed, no equivalent | `c_oldtitle` → NULL |
| `new` | Title added, no vanilla source | NULL → `c_newtitle` |

---

## Confidence Scoring

| Confidence | Meaning | Action |
|------------|---------|--------|
| 1.0 | Verified by human or exact match | Use directly |
| 0.8-0.99 | High-confidence algorithm match | Use with logging |
| 0.5-0.79 | Plausible match, needs review | Queue for human review |
| 0.0-0.49 | Uncertain, multiple candidates | Block until reviewed |

---

## Matching Algorithms

1. **Exact match** - Same title ID exists in both systems
2. **Localization match** - Different IDs but same display name
3. **Geographic proximity** - Titles covering similar provinces
4. **Semantic match** - Same role (e.g., "capital of X culture")
5. **Manual override** - Human-specified mapping

---

## MCP Tools

### Query Tools

```python
ck3_compass_systems()
# Returns: List of registered map systems

ck3_compass_lookup(
    source_system: str,      # 'vanilla'
    target_system: str,      # 'more_bookmarks_plus'  
    reference: str,          # 'c_santiago'
    reference_type: str      # 'title', 'province', 'holy_site', 'region'
)
# Returns: {target: 'c_tui', type: 'renamed', confidence: 1.0}

ck3_compass_coverage(
    source_system: str,
    target_system: str
)
# Returns: {total: 3074, mapped: 2891, unmapped: 183, needs_review: 45}
```

### Analysis Tools

```python
ck3_compass_analyze_file(
    file_path: str,
    source_system: str,
    target_system: str
)
# Returns: List of references and their mappings

ck3_compass_diff_systems(
    system_a: str,
    system_b: str,
    entity_type: str         # 'titles', 'provinces', 'holy_sites'
)
# Returns: {added: [...], removed: [...], changed: [...]}
```

### Build Tools

```python
ck3_compass_extract_titles(content_version_id: int)
# Populates symbol tables

ck3_compass_generate_mappings(
    source_system: str,
    target_system: str,
    algorithm: str           # 'exact', 'localization', 'all'
)
# Auto-generates mappings

ck3_compass_import_mappings(
    source_system: str,
    target_system: str,
    mappings: list
)
# Import curated mappings
```

---

## Workflow

### Phase 1: Setup

1. Create isolated playset for target map mod
2. Build database for that playset
3. Register map system
4. Link to content_version

### Phase 2: Extract & Match

1. Extract titles from vanilla
2. Extract titles from target map mod
3. Run matching algorithms
4. Identify gaps

### Phase 3: Human Review

1. Queue low-confidence mappings
2. Accept/reject/modify
3. Document unmappable items

### Phase 4: Use Mappings

1. Analyze mod files for references
2. Look up mappings
3. Generate converted files or TODO list

---

## Policy Considerations

### ck3compass-dev Mode

| Rule | Description |
|------|-------------|
| **Read-only map mods** | Never modify MB+, IBL, etc. |
| **Write to ck3raven only** | Schema, extractors, MCP tools |
| **Human review for low confidence** | Never auto-apply <0.8 confidence |
| **No live mod writes** | This mode builds reference data only |

---

## Success Criteria

| Metric | Target |
|--------|--------|
| Title coverage | 95%+ mapped or marked unmappable |
| Holy site coverage | 100% |
| Confidence accuracy | <5% of high-confidence mappings wrong |
| Query latency | <100ms |

---

## Open Questions

1. **Province vs Title focus?** - Which is primary key?
2. **De jure structure?** - Map hierarchy changes?
3. **Versioning?** - Per map mod release?
4. **Community sharing?** - Export format?

---

## Dependencies

- ck3raven core database ✅
- Symbol extraction ✅
- Conflict analysis ✅
- Multi-playset support ✅
- Title lookup tables ⬜ (partial)
- Holy site lookup tables ⬜
