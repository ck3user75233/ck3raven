"""
SQL-Based Content Resolver

Resolves conflicts between vanilla + mods using pure SQL queries on the 
symbols/files tables. NO file I/O - operates entirely on data already 
ingested into the database.

Architecture:
  1. File-level override: Same relpath → later load_order wins (file replaced)
  2. Key-level override: Same symbol name → later load_order wins (LIOS)
  3. FIOS for GUI: Same symbol name → earlier load_order wins
  4. CONTAINER_MERGE: Events/on_actions append, trigger/effect conflict
"""

import sqlite3
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
from enum import Enum

from ck3raven.resolver.policies import MergePolicy, get_policy_for_folder


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ResolvedSymbol:
    """A symbol after resolution - the winner for a given name."""
    symbol_id: int
    symbol_type: str
    name: str
    defining_file_id: int
    relpath: str
    content_version_id: int
    load_order_index: int
    line_number: Optional[int]
    metadata_json: Optional[str]
    
    # Conflict info
    was_overridden: bool = False
    overridden_by_count: int = 0


@dataclass
class OverriddenSymbol:
    """A symbol that was overridden (the loser)."""
    symbol_id: int
    symbol_type: str
    name: str
    defining_file_id: int
    relpath: str
    content_version_id: int
    load_order_index: int
    line_number: Optional[int]
    winner_symbol_id: int
    winner_load_order: int


@dataclass 
class FileOverride:
    """A file that was completely replaced by another with same relpath."""
    relpath: str
    loser_file_id: int
    loser_content_version_id: int
    loser_load_order: int
    winner_file_id: int
    winner_content_version_id: int
    winner_load_order: int


@dataclass
class ResolutionResult:
    """Complete resolution result for a folder or symbol type."""
    folder_path: str
    policy: MergePolicy
    
    # Resolved symbols (winners)
    symbols: Dict[str, ResolvedSymbol] = field(default_factory=dict)
    
    # Overridden symbols (losers) - for conflict reporting
    overridden: List[OverriddenSymbol] = field(default_factory=list)
    
    # File-level overrides
    file_overrides: List[FileOverride] = field(default_factory=list)
    
    @property
    def conflict_count(self) -> int:
        """Number of key-level conflicts (same name, different source)."""
        return len(self.overridden)
    
    @property
    def file_override_count(self) -> int:
        """Number of file-level overrides (same relpath)."""
        return len(self.file_overrides)


# =============================================================================
# SQL QUERIES
# =============================================================================

# Get all files in a playset for a specific folder, with load order
SQL_PLAYSET_FILES = """
WITH playset_files AS (
    -- Vanilla files (load_order = -1 to come before all mods)
    SELECT 
        f.file_id,
        f.relpath,
        f.content_hash,
        f.content_version_id,
        -1 as load_order_index,
        cv.kind
    FROM files f
    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
    JOIN playsets p ON cv.vanilla_version_id = p.vanilla_version_id
    WHERE p.playset_id = :playset_id
      AND cv.kind = 'vanilla'
      AND f.relpath LIKE :folder_pattern
      AND f.file_type = 'script'
      AND f.deleted = 0
    
    UNION ALL
    
    -- Mod files with load order
    SELECT 
        f.file_id,
        f.relpath,
        f.content_hash,
        f.content_version_id,
        pm.load_order_index,
        'mod' as kind
    FROM files f
    JOIN playset_mods pm ON f.content_version_id = pm.content_version_id
    WHERE pm.playset_id = :playset_id
      AND pm.enabled = 1
      AND f.relpath LIKE :folder_pattern
      AND f.file_type = 'script'
      AND f.deleted = 0
)
SELECT * FROM playset_files
ORDER BY relpath, load_order_index
"""


# Detect file-level overrides (same relpath, different sources)
SQL_FILE_OVERRIDES = """
WITH playset_files AS (
    SELECT 
        f.file_id,
        f.relpath,
        f.content_version_id,
        COALESCE(pm.load_order_index, -1) as load_order_index
    FROM files f
    LEFT JOIN playset_mods pm ON f.content_version_id = pm.content_version_id 
        AND pm.playset_id = :playset_id
    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
    JOIN playsets p ON (cv.vanilla_version_id = p.vanilla_version_id AND cv.kind = 'vanilla')
        OR (pm.playset_id = p.playset_id AND pm.enabled = 1)
    WHERE p.playset_id = :playset_id
      AND f.relpath LIKE :folder_pattern
      AND f.file_type = 'script'
      AND f.deleted = 0
),
file_max_order AS (
    SELECT relpath, MAX(load_order_index) as max_order
    FROM playset_files
    GROUP BY relpath
    HAVING COUNT(*) > 1
)
SELECT 
    pf.relpath,
    pf.file_id as loser_file_id,
    pf.content_version_id as loser_content_version_id,
    pf.load_order_index as loser_load_order,
    winner.file_id as winner_file_id,
    winner.content_version_id as winner_content_version_id,
    winner.load_order_index as winner_load_order
FROM playset_files pf
JOIN file_max_order fmo ON pf.relpath = fmo.relpath
JOIN playset_files winner ON winner.relpath = pf.relpath 
    AND winner.load_order_index = fmo.max_order
WHERE pf.load_order_index < fmo.max_order
ORDER BY pf.relpath, pf.load_order_index
"""


# Get surviving files after file-level override
SQL_SURVIVING_FILES = """
WITH playset_files AS (
    -- Vanilla files
    SELECT 
        f.file_id,
        f.relpath,
        f.content_version_id,
        -1 as load_order_index
    FROM files f
    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
    JOIN playsets p ON cv.vanilla_version_id = p.vanilla_version_id
    WHERE p.playset_id = :playset_id
      AND cv.kind = 'vanilla'
      AND f.relpath LIKE :folder_pattern
      AND f.file_type = 'script'
      AND f.deleted = 0
    
    UNION ALL
    
    -- Mod files
    SELECT 
        f.file_id,
        f.relpath,
        f.content_version_id,
        pm.load_order_index
    FROM files f
    JOIN playset_mods pm ON f.content_version_id = pm.content_version_id
    WHERE pm.playset_id = :playset_id
      AND pm.enabled = 1
      AND f.relpath LIKE :folder_pattern
      AND f.file_type = 'script'
      AND f.deleted = 0
),
file_winners AS (
    -- For each relpath, keep only the highest load_order_index
    SELECT pf.*
    FROM playset_files pf
    WHERE pf.load_order_index = (
        SELECT MAX(pf2.load_order_index)
        FROM playset_files pf2
        WHERE pf2.relpath = pf.relpath
    )
)
SELECT * FROM file_winners
"""


# Resolve symbols with OVERRIDE policy (LIOS - Last In Only Served)
SQL_RESOLVE_OVERRIDE = """
WITH surviving_files AS (
    -- Vanilla files
    SELECT 
        f.file_id,
        f.relpath,
        f.content_version_id,
        -1 as load_order_index
    FROM files f
    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
    JOIN playsets p ON cv.vanilla_version_id = p.vanilla_version_id
    WHERE p.playset_id = :playset_id
      AND cv.kind = 'vanilla'
      AND f.relpath LIKE :folder_pattern
      AND f.file_type = 'script'
      AND f.deleted = 0
    
    UNION ALL
    
    -- Mod files
    SELECT 
        f.file_id,
        f.relpath,
        f.content_version_id,
        pm.load_order_index
    FROM files f
    JOIN playset_mods pm ON f.content_version_id = pm.content_version_id
    WHERE pm.playset_id = :playset_id
      AND pm.enabled = 1
      AND f.relpath LIKE :folder_pattern
      AND f.file_type = 'script'
      AND f.deleted = 0
),
file_winners AS (
    SELECT sf.*
    FROM surviving_files sf
    WHERE sf.load_order_index = (
        SELECT MAX(sf2.load_order_index)
        FROM surviving_files sf2
        WHERE sf2.relpath = sf.relpath
    )
),
all_symbols AS (
    SELECT 
        s.symbol_id,
        s.symbol_type,
        s.name,
        s.defining_file_id,
        s.line_number,
        s.metadata_json,
        fw.relpath,
        fw.content_version_id,
        fw.load_order_index
    FROM symbols s
    JOIN file_winners fw ON s.defining_file_id = fw.file_id
    WHERE s.symbol_type = :symbol_type OR :symbol_type IS NULL
)
-- Winners: highest load_order_index for each name
SELECT 
    a.*,
    (SELECT COUNT(*) FROM all_symbols a2 WHERE a2.name = a.name AND a2.symbol_id != a.symbol_id) as overridden_count
FROM all_symbols a
WHERE a.load_order_index = (
    SELECT MAX(a2.load_order_index)
    FROM all_symbols a2
    WHERE a2.name = a.name
)
ORDER BY a.name
"""


# Get overridden symbols (losers) for conflict reporting
SQL_OVERRIDDEN_SYMBOLS = """
WITH surviving_files AS (
    SELECT 
        f.file_id,
        f.relpath,
        f.content_version_id,
        COALESCE(pm.load_order_index, -1) as load_order_index
    FROM files f
    LEFT JOIN playset_mods pm ON f.content_version_id = pm.content_version_id 
        AND pm.playset_id = :playset_id AND pm.enabled = 1
    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
    WHERE (
        (cv.kind = 'vanilla' AND cv.vanilla_version_id = (SELECT vanilla_version_id FROM playsets WHERE playset_id = :playset_id))
        OR pm.playset_id = :playset_id
    )
      AND f.relpath LIKE :folder_pattern
      AND f.file_type = 'script'
      AND f.deleted = 0
),
file_winners AS (
    SELECT sf.*
    FROM surviving_files sf
    WHERE sf.load_order_index = (
        SELECT MAX(sf2.load_order_index)
        FROM surviving_files sf2
        WHERE sf2.relpath = sf.relpath
    )
),
all_symbols AS (
    SELECT 
        s.symbol_id,
        s.symbol_type,
        s.name,
        s.defining_file_id,
        s.line_number,
        fw.relpath,
        fw.content_version_id,
        fw.load_order_index
    FROM symbols s
    JOIN file_winners fw ON s.defining_file_id = fw.file_id
    WHERE s.symbol_type = :symbol_type OR :symbol_type IS NULL
),
symbol_winners AS (
    SELECT name, MAX(load_order_index) as max_order, 
           (SELECT symbol_id FROM all_symbols a2 
            WHERE a2.name = all_symbols.name 
            AND a2.load_order_index = MAX(all_symbols.load_order_index)) as winner_id
    FROM all_symbols
    GROUP BY name
    HAVING COUNT(*) > 1
)
SELECT 
    a.*,
    sw.winner_id as winner_symbol_id,
    sw.max_order as winner_load_order
FROM all_symbols a
JOIN symbol_winners sw ON a.name = sw.name
WHERE a.load_order_index < sw.max_order
ORDER BY a.name, a.load_order_index
"""


# Resolve symbols with FIOS policy (First In Only Served) - for GUI types
SQL_RESOLVE_FIOS = """
WITH surviving_files AS (
    SELECT 
        f.file_id,
        f.relpath,
        f.content_version_id,
        COALESCE(pm.load_order_index, -1) as load_order_index
    FROM files f
    LEFT JOIN playset_mods pm ON f.content_version_id = pm.content_version_id 
        AND pm.playset_id = :playset_id AND pm.enabled = 1
    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
    WHERE (
        (cv.kind = 'vanilla' AND cv.vanilla_version_id = (SELECT vanilla_version_id FROM playsets WHERE playset_id = :playset_id))
        OR pm.playset_id = :playset_id
    )
      AND f.relpath LIKE :folder_pattern
      AND f.file_type = 'script'
      AND f.deleted = 0
),
-- Note: For FIOS, file-level is still LIOS, only symbol-level is FIOS
file_winners AS (
    SELECT sf.*
    FROM surviving_files sf
    WHERE sf.load_order_index = (
        SELECT MAX(sf2.load_order_index)
        FROM surviving_files sf2
        WHERE sf2.relpath = sf.relpath
    )
),
all_symbols AS (
    SELECT 
        s.symbol_id,
        s.symbol_type,
        s.name,
        s.defining_file_id,
        s.line_number,
        s.metadata_json,
        fw.relpath,
        fw.content_version_id,
        fw.load_order_index
    FROM symbols s
    JOIN file_winners fw ON s.defining_file_id = fw.file_id
    WHERE s.symbol_type = :symbol_type OR :symbol_type IS NULL
)
-- FIOS: LOWEST load_order_index for each name (first definition wins)
SELECT 
    a.*,
    (SELECT COUNT(*) FROM all_symbols a2 WHERE a2.name = a.name AND a2.symbol_id != a.symbol_id) as overridden_count
FROM all_symbols a
WHERE a.load_order_index = (
    SELECT MIN(a2.load_order_index)
    FROM all_symbols a2
    WHERE a2.name = a.name
)
ORDER BY a.name
"""


# =============================================================================
# RESOLVER CLASS
# =============================================================================

class SQLResolver:
    """
    SQL-based resolver for CK3 content.
    
    Operates entirely on database - NO file I/O.
    
    Usage:
        resolver = SQLResolver(conn)
        result = resolver.resolve_folder(playset_id, "common/culture/traditions")
    """
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        # Ensure row_factory for dict-like access
        self.conn.row_factory = sqlite3.Row
    
    def resolve_folder(
        self,
        playset_id: int,
        folder_path: str,
        symbol_type: Optional[str] = None,
        policy: Optional[MergePolicy] = None
    ) -> ResolutionResult:
        """
        Resolve all symbols in a folder for a playset.
        
        Args:
            playset_id: The playset to resolve
            folder_path: Folder like "common/culture/traditions"
            symbol_type: Optional filter by symbol type
            policy: Override auto-detected policy
        
        Returns:
            ResolutionResult with winners, losers, and file overrides
        """
        # Normalize folder path
        folder = folder_path.replace("\\", "/").rstrip("/")
        folder_pattern = folder + "/%"
        
        # Determine policy
        if policy is None:
            policy = get_policy_for_folder(folder)
        
        result = ResolutionResult(folder_path=folder, policy=policy)
        
        # Get file-level overrides
        result.file_overrides = self._get_file_overrides(playset_id, folder_pattern)
        
        # Resolve based on policy
        if policy == MergePolicy.OVERRIDE:
            result.symbols = self._resolve_override(playset_id, folder_pattern, symbol_type)
            result.overridden = self._get_overridden(playset_id, folder_pattern, symbol_type)
        elif policy == MergePolicy.FIOS:
            result.symbols = self._resolve_fios(playset_id, folder_pattern, symbol_type)
        elif policy == MergePolicy.CONTAINER_MERGE:
            # Container merge uses OVERRIDE for the container itself
            # Sub-block merging happens at a different level
            result.symbols = self._resolve_override(playset_id, folder_pattern, symbol_type)
            result.overridden = self._get_overridden(playset_id, folder_pattern, symbol_type)
        elif policy == MergePolicy.PER_KEY_OVERRIDE:
            # Same as OVERRIDE at symbol level
            result.symbols = self._resolve_override(playset_id, folder_pattern, symbol_type)
            result.overridden = self._get_overridden(playset_id, folder_pattern, symbol_type)
        
        return result
    
    def _get_file_overrides(self, playset_id: int, folder_pattern: str) -> List[FileOverride]:
        """Get all file-level overrides (same relpath, later wins)."""
        rows = self.conn.execute(SQL_FILE_OVERRIDES, {
            'playset_id': playset_id,
            'folder_pattern': folder_pattern
        }).fetchall()
        
        return [
            FileOverride(
                relpath=row['relpath'],
                loser_file_id=row['loser_file_id'],
                loser_content_version_id=row['loser_content_version_id'],
                loser_load_order=row['loser_load_order'],
                winner_file_id=row['winner_file_id'],
                winner_content_version_id=row['winner_content_version_id'],
                winner_load_order=row['winner_load_order']
            )
            for row in rows
        ]
    
    def _resolve_override(
        self, 
        playset_id: int, 
        folder_pattern: str,
        symbol_type: Optional[str]
    ) -> Dict[str, ResolvedSymbol]:
        """Resolve with OVERRIDE policy (LIOS)."""
        rows = self.conn.execute(SQL_RESOLVE_OVERRIDE, {
            'playset_id': playset_id,
            'folder_pattern': folder_pattern,
            'symbol_type': symbol_type
        }).fetchall()
        
        return {
            row['name']: ResolvedSymbol(
                symbol_id=row['symbol_id'],
                symbol_type=row['symbol_type'],
                name=row['name'],
                defining_file_id=row['defining_file_id'],
                relpath=row['relpath'],
                content_version_id=row['content_version_id'],
                load_order_index=row['load_order_index'],
                line_number=row['line_number'],
                metadata_json=row['metadata_json'],
                was_overridden=row['overridden_count'] > 0,
                overridden_by_count=row['overridden_count']
            )
            for row in rows
        }
    
    def _resolve_fios(
        self,
        playset_id: int,
        folder_pattern: str,
        symbol_type: Optional[str]
    ) -> Dict[str, ResolvedSymbol]:
        """Resolve with FIOS policy (first definition wins)."""
        rows = self.conn.execute(SQL_RESOLVE_FIOS, {
            'playset_id': playset_id,
            'folder_pattern': folder_pattern,
            'symbol_type': symbol_type
        }).fetchall()
        
        return {
            row['name']: ResolvedSymbol(
                symbol_id=row['symbol_id'],
                symbol_type=row['symbol_type'],
                name=row['name'],
                defining_file_id=row['defining_file_id'],
                relpath=row['relpath'],
                content_version_id=row['content_version_id'],
                load_order_index=row['load_order_index'],
                line_number=row['line_number'],
                metadata_json=row['metadata_json'],
                was_overridden=row['overridden_count'] > 0,
                overridden_by_count=row['overridden_count']
            )
            for row in rows
        }
    
    def _get_overridden(
        self,
        playset_id: int,
        folder_pattern: str,
        symbol_type: Optional[str]
    ) -> List[OverriddenSymbol]:
        """Get all overridden symbols (losers)."""
        rows = self.conn.execute(SQL_OVERRIDDEN_SYMBOLS, {
            'playset_id': playset_id,
            'folder_pattern': folder_pattern,
            'symbol_type': symbol_type
        }).fetchall()
        
        return [
            OverriddenSymbol(
                symbol_id=row['symbol_id'],
                symbol_type=row['symbol_type'],
                name=row['name'],
                defining_file_id=row['defining_file_id'],
                relpath=row['relpath'],
                content_version_id=row['content_version_id'],
                load_order_index=row['load_order_index'],
                line_number=row['line_number'],
                winner_symbol_id=row['winner_symbol_id'],
                winner_load_order=row['winner_load_order']
            )
            for row in rows
        ]
    
    def get_conflict_summary(
        self,
        playset_id: int,
        folder_paths: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get a summary of all conflicts across folders.
        
        Args:
            playset_id: The playset to analyze
            folder_paths: Specific folders to check (all if None)
        
        Returns:
            Summary dict with counts and details
        """
        if folder_paths is None:
            # Get all script folders in playset
            rows = self.conn.execute("""
                SELECT DISTINCT 
                    substr(f.relpath, 1, length(f.relpath) - length(replace(f.relpath, '/', ''))) as folder
                FROM files f
                JOIN playset_mods pm ON f.content_version_id = pm.content_version_id
                WHERE pm.playset_id = ?
                  AND f.file_type = 'script'
                  AND f.deleted = 0
                UNION
                SELECT DISTINCT 
                    substr(f.relpath, 1, length(f.relpath) - length(replace(f.relpath, '/', ''))) as folder
                FROM files f
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                JOIN playsets p ON cv.vanilla_version_id = p.vanilla_version_id
                WHERE p.playset_id = ?
                  AND cv.kind = 'vanilla'
                  AND f.file_type = 'script'
                  AND f.deleted = 0
            """, (playset_id, playset_id)).fetchall()
            folder_paths = [row['folder'].rstrip('/') for row in rows if row['folder']]
        
        summary = {
            'playset_id': playset_id,
            'folders_analyzed': len(folder_paths),
            'total_file_overrides': 0,
            'total_symbol_conflicts': 0,
            'folders_with_conflicts': 0,
            'by_folder': {}
        }
        
        for folder in folder_paths:
            result = self.resolve_folder(playset_id, folder)
            
            if result.file_override_count > 0 or result.conflict_count > 0:
                summary['folders_with_conflicts'] += 1
                summary['total_file_overrides'] += result.file_override_count
                summary['total_symbol_conflicts'] += result.conflict_count
                
                summary['by_folder'][folder] = {
                    'policy': result.policy.name,
                    'file_overrides': result.file_override_count,
                    'symbol_conflicts': result.conflict_count,
                }
        
        return summary
