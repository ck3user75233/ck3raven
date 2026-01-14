"""Remove BANNED playset tables from schema.py and models from models.py"""
import pathlib
import re

# 1. Fix schema.py - comment out the playset tables (keep for reference but mark EXPUNGED)
schema_path = pathlib.Path('src/ck3raven/db/schema.py')
c = schema_path.read_text(encoding='utf-8')

# Replace playset tables section with commented version
old_section = '''-- ============================================================================
-- PLAYSETS & BUILDS
-- ============================================================================

-- Playsets - user-defined mod collections with load order
CREATE TABLE IF NOT EXISTS playsets (
    playset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    vanilla_version_id INTEGER NOT NULL,     -- FK to vanilla_versions
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 0,    -- Max 5 active at once (enforced in code)
    -- Contribution lifecycle tracking
    contributions_hash TEXT,                 -- Hash of current contribution state
    contributions_stale INTEGER NOT NULL DEFAULT 1,  -- 1 = needs rescan, 0 = up to date
    contributions_scanned_at TEXT,           -- When last scanned
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vanilla_version_id) REFERENCES vanilla_versions(vanilla_version_id)
);

-- Playset mod membership with load order
CREATE TABLE IF NOT EXISTS playset_mods (
    playset_id INTEGER NOT NULL,
    content_version_id INTEGER NOT NULL,     -- FK to content_versions (mod version)
    load_order_index INTEGER NOT NULL,       -- Lower = loaded first, higher = wins in OVERRIDE
    enabled INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (playset_id, content_version_id),
    FOREIGN KEY (playset_id) REFERENCES playsets(playset_id),
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
);

CREATE INDEX IF NOT EXISTS idx_playset_mods_order ON playset_mods(playset_id, load_order_index);

-- Optional: Build cache for resolved states
CREATE TABLE IF NOT EXISTS builds (
    build_id INTEGER PRIMARY KEY AUTOINCREMENT,
    playset_id INTEGER NOT NULL,
    ruleset_version TEXT NOT NULL,           -- Version of merge rules used
    load_order_hash TEXT NOT NULL,           -- Hash of load order for cache key
    resolved_at TEXT NOT NULL DEFAULT (datetime('now')),
    build_metadata_json TEXT,
    FOREIGN KEY (playset_id) REFERENCES playsets(playset_id),
    UNIQUE(playset_id, ruleset_version, load_order_hash)
);'''

new_section = '''-- ============================================================================
-- PLAYSETS & BUILDS - EXPUNGED 2025-01-02
-- ============================================================================
-- 
-- These tables are EXPUNGED. Playsets are now file-based JSON:
-- - playsets/*.json - playset definitions with mod lists
-- - server.py ck3_playset - MCP tool for playset operations
-- 
-- The database-based playset architecture (playset_id, playset_mods) is BANNED.
-- See docs/CANONICAL_ARCHITECTURE.md for details.
--
-- REMOVED TABLES: playsets, playset_mods, builds
-- These tables will be dropped in a future migration.
'''

c = c.replace(old_section, new_section)
schema_path.write_text(c, encoding='utf-8')
print('schema.py: removed playset/builds table definitions')

# 2. Fix models.py - mark Playset/PlaysetMod as EXPUNGED
models_path = pathlib.Path('src/ck3raven/db/models.py')
c = models_path.read_text(encoding='utf-8')

# Find and replace the Playset class
old_playset = '''@dataclass
class Playset:
    \"\"\"A user-defined mod collection with load order.\"\"\"
    playset_id: Optional[int] = None
    name: str = ""
    vanilla_version_id: int = 0
    description: Optional[str] = None
    is_active: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Populated separately
    mods: List["PlaysetMod"] = field(default_factory=list)
    
    @classmethod
    def from_row(cls, row) -> "Playset":
        return cls(
            playset_id=row['playset_id'],
            name=row['name'],
            vanilla_version_id=row['vanilla_version_id'],
            description=row['description'],
            is_active=bool(row['is_active']),
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )
    
    def __repr__(self):
        active = " [ACTIVE]" if self.is_active else ""
        return f"Playset({self.name}, {len(self.mods)} mods{active})"


@dataclass
class PlaysetMod:
    \"\"\"A mod in a playset with load order.\"\"\"
    playset_id: int = 0
    content_version_id: int = 0
    load_order_index: int = 0
    enabled: bool = True
    
    @classmethod
    def from_row(cls, row) -> "PlaysetMod":
        return cls(
            playset_id=row['playset_id'],
            content_version_id=row['content_version_id'],
            load_order_index=row['load_order_index'],
            enabled=bool(row['enabled']),
        )'''

new_playset = '''# EXPUNGED 2025-01-02: Playset and PlaysetMod models removed.
# Playsets are now file-based JSON. See playsets/*.json and server.py ck3_playset.
# 
# The database-based playset models (Playset, PlaysetMod with playset_id) are BANNED.
# See docs/CANONICAL_ARCHITECTURE.md for details.'''

c = c.replace(old_playset, new_playset)
models_path.write_text(c, encoding='utf-8')
print('models.py: removed Playset/PlaysetMod class definitions')

print('Done fixing schema.py and models.py')
