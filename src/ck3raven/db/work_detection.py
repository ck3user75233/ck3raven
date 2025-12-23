"""
Work Detection Functions for Database Builder

These functions detect what work needs to be done without performing it.
Used by the builder wizard to intelligently determine which phases to run.

GUARDRAIL: These functions are designed to enable INCREMENTAL updates.
Full rebuilds should only happen when:
1. Schema version changed
2. Parser version changed (for that specific phase)
3. User explicitly requests --force

Key functions:
- get_files_needing_ingest() - New/changed files on disk
- get_files_needing_ast() - Files with content but no AST
- get_asts_needing_symbols() - ASTs without extracted symbols
- get_stale_entries() - DB entries for deleted files
- get_slow_parses() - Statistical outliers for investigation
- get_build_status() - Overall summary of what needs work
"""

import sqlite3
import logging
import statistics
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Set, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class WorkSummary:
    """Summary of pending work for the builder."""
    # Ingest phase
    files_to_ingest: int = 0
    files_to_delete: int = 0
    files_changed: int = 0
    
    # AST phase
    files_needing_ast: int = 0
    files_with_failed_ast: int = 0
    
    # Symbol phase
    asts_needing_symbols: int = 0
    
    # Localization phase
    loc_files_needing_parse: int = 0
    
    # Cleanup
    orphaned_asts: int = 0
    orphaned_symbols: int = 0
    orphaned_content: int = 0
    
    # Metadata
    total_files: int = 0
    total_asts: int = 0
    total_symbols: int = 0
    last_build_time: Optional[str] = None
    
    def needs_work(self) -> bool:
        """Check if any work is pending."""
        return any([
            self.files_to_ingest > 0,
            self.files_to_delete > 0,
            self.files_changed > 0,
            self.files_needing_ast > 0,
            self.asts_needing_symbols > 0,
            self.loc_files_needing_parse > 0,
        ])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'ingest': {
                'files_to_add': self.files_to_ingest,
                'files_to_delete': self.files_to_delete,
                'files_changed': self.files_changed,
            },
            'ast': {
                'files_needing_ast': self.files_needing_ast,
                'files_with_failed_ast': self.files_with_failed_ast,
            },
            'symbols': {
                'asts_needing_symbols': self.asts_needing_symbols,
            },
            'localization': {
                'files_needing_parse': self.loc_files_needing_parse,
            },
            'cleanup': {
                'orphaned_asts': self.orphaned_asts,
                'orphaned_symbols': self.orphaned_symbols,
                'orphaned_content': self.orphaned_content,
            },
            'totals': {
                'files': self.total_files,
                'asts': self.total_asts,
                'symbols': self.total_symbols,
            },
            'needs_work': self.needs_work(),
            'last_build_time': self.last_build_time,
        }


@dataclass
class SlowParseInfo:
    """Information about a slow parse for investigation."""
    content_hash: str
    filename: str
    parse_time_ms: float
    file_size: int
    node_count: int
    z_score: float  # How many std devs above mean


# =============================================================================
# File Ingestion Detection
# =============================================================================

def get_files_needing_ingest(
    conn: sqlite3.Connection,
    root_path: Path,
    content_version_id: int
) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    Compare filesystem to database and return what needs updating.
    
    Args:
        conn: Database connection
        root_path: Path to content directory (vanilla or mod)
        content_version_id: The content version to compare against
        
    Returns:
        (new_files, deleted_files, changed_files) as sets of relpaths
    """
    from ck3raven.db.content import compute_content_hash, scan_directory
    
    # Get stored manifest from DB
    stored = {}
    rows = conn.execute("""
        SELECT relpath, content_hash 
        FROM files 
        WHERE content_version_id = ? AND deleted = 0
    """, (content_version_id,)).fetchall()
    for row in rows:
        stored[row[0]] = row[1]
    
    # Scan current filesystem
    current = {}
    for entry in scan_directory(root_path):
        try:
            file_path = root_path / entry.relpath
            data = file_path.read_bytes()
            current[entry.relpath] = compute_content_hash(data)
        except Exception as e:
            logger.warning(f"Error reading {entry.relpath}: {e}")
    
    # Compare
    stored_paths = set(stored.keys())
    current_paths = set(current.keys())
    
    new_files = current_paths - stored_paths
    deleted_files = stored_paths - current_paths
    
    common = stored_paths & current_paths
    changed_files = {p for p in common if stored[p] != current[p]}
    
    return new_files, deleted_files, changed_files


def get_content_versions_to_check(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    Get all content versions that should be checked for updates.
    
    Returns list of dicts with content_version_id, source_path, kind, name
    """
    rows = conn.execute("""
        SELECT 
            cv.content_version_id,
            cv.source_path,
            cv.kind,
            COALESCE(mp.name, vv.version_string, 'unknown') as name
        FROM content_versions cv
        LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
        LEFT JOIN vanilla_versions vv ON cv.vanilla_version_id = vv.vanilla_version_id
        WHERE cv.source_path IS NOT NULL
    """).fetchall()
    
    return [
        {
            'content_version_id': r[0],
            'source_path': r[1],
            'kind': r[2],
            'name': r[3],
        }
        for r in rows
    ]


# =============================================================================
# AST Generation Detection
# =============================================================================

def get_files_needing_ast(
    conn: sqlite3.Connection,
    parser_version_id: int,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Get files that have content but no AST for the specified parser version.
    
    Excludes:
    - Localization files (handled by localization parser)
    - Binary files
    - Non-script files (graphics, etc.)
    
    Args:
        conn: Database connection
        parser_version_id: Parser version to check for
        limit: Maximum number to return (None = all)
        
    Returns:
        List of dicts with content_hash, relpath, size
    """
    query = """
        SELECT DISTINCT 
            fc.content_hash,
            f.relpath,
            fc.size
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.deleted = 0
        AND f.relpath LIKE '%.txt'
        AND f.relpath NOT LIKE 'localization/%'
        AND fc.content_text IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM asts a
            WHERE a.content_hash = fc.content_hash
            AND a.parser_version_id = ?
        )
        ORDER BY fc.size ASC  -- Small files first for quick wins
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    rows = conn.execute(query, (parser_version_id,)).fetchall()
    
    return [
        {'content_hash': r[0], 'relpath': r[1], 'size': r[2]}
        for r in rows
    ]


def get_files_with_failed_ast(
    conn: sqlite3.Connection,
    parser_version_id: int
) -> List[Dict[str, Any]]:
    """
    Get files that have a failed AST parse for this parser version.
    
    Useful for reviewing parser bugs or problematic files.
    """
    rows = conn.execute("""
        SELECT 
            a.content_hash,
            f.relpath,
            a.diagnostics_json
        FROM asts a
        JOIN files f ON a.content_hash = f.content_hash
        WHERE a.parser_version_id = ?
        AND a.parse_ok = 0
        AND f.deleted = 0
        GROUP BY a.content_hash
    """, (parser_version_id,)).fetchall()
    
    return [
        {'content_hash': r[0], 'relpath': r[1], 'diagnostics': r[2]}
        for r in rows
    ]


def get_ast_coverage(conn: sqlite3.Connection, parser_version_id: int) -> Dict[str, Any]:
    """
    Get AST coverage statistics.
    
    Returns dict with total_script_files, files_with_ast, coverage_pct, etc.
    """
    # Total script files (excluding localization)
    total_row = conn.execute("""
        SELECT COUNT(DISTINCT fc.content_hash)
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.deleted = 0
        AND f.relpath LIKE '%.txt'
        AND f.relpath NOT LIKE 'localization/%'
        AND fc.content_text IS NOT NULL
    """).fetchone()
    total_script = total_row[0]
    
    # Files with successful AST
    success_row = conn.execute("""
        SELECT COUNT(DISTINCT content_hash)
        FROM asts
        WHERE parser_version_id = ? AND parse_ok = 1
    """, (parser_version_id,)).fetchone()
    with_ast = success_row[0]
    
    # Files with failed AST
    failed_row = conn.execute("""
        SELECT COUNT(DISTINCT content_hash)
        FROM asts
        WHERE parser_version_id = ? AND parse_ok = 0
    """, (parser_version_id,)).fetchone()
    failed = failed_row[0]
    
    coverage_pct = (with_ast / total_script * 100) if total_script > 0 else 0
    
    return {
        'total_script_files': total_script,
        'files_with_ast': with_ast,
        'files_with_failed_ast': failed,
        'files_pending': total_script - with_ast - failed,
        'coverage_pct': round(coverage_pct, 1),
        'parser_version_id': parser_version_id,
    }


# =============================================================================
# Symbol Extraction Detection
# =============================================================================

def get_asts_needing_symbols(
    conn: sqlite3.Connection,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Get ASTs that do not have extracted symbols yet.
    
    Uses centralized skip rules to only count symbol-eligible files.

    Args:
        conn: Database connection
        limit: Maximum number to return

    Returns:
        List of dicts with content_hash, ast_id, node_count
    """
    from ck3raven.db.file_routes import get_symbol_file_filter_sql
    
    file_filter = get_symbol_file_filter_sql()
    
    query = f"""
        SELECT
            a.content_hash,
            a.ast_id,
            a.node_count
        FROM asts a
        JOIN files f ON a.content_hash = f.content_hash
        WHERE a.parse_ok = 1
        AND {file_filter}
        AND NOT EXISTS (
            SELECT 1 FROM symbols s
            WHERE s.defining_ast_id = a.ast_id
        )
        GROUP BY a.ast_id
    """
    rows = conn.execute(query).fetchall()

    return [
        {'content_hash': r[0], 'ast_id': r[1], 'node_count': r[2]}
        for r in rows
    ]


def get_symbol_coverage(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Get symbol extraction coverage statistics.
    
    Uses centralized skip rules to only count symbol-eligible ASTs.
    """
    from ck3raven.db.file_routes import get_symbol_file_filter_sql
    
    file_filter = get_symbol_file_filter_sql()
    
    # ASTs with symbols (count unique AST IDs that have symbols)
    with_symbols_row = conn.execute("""
        SELECT COUNT(DISTINCT defining_ast_id) FROM symbols
    """).fetchone()
    with_symbols = with_symbols_row[0]

    # Total symbol-eligible ASTs (using skip rules)
    total_asts_row = conn.execute(f"""
        SELECT COUNT(DISTINCT a.ast_id) 
        FROM asts a
        JOIN files f ON a.content_hash = f.content_hash
        WHERE a.parse_ok = 1
        AND {file_filter}
    """).fetchone()
    total_asts = total_asts_row[0]

    # Total symbol count
    symbol_count_row = conn.execute("""
        SELECT COUNT(*) FROM symbols
    """).fetchone()
    symbol_count = symbol_count_row[0]

    coverage_pct = (with_symbols / total_asts * 100) if total_asts > 0 else 0

    return {
        'total_eligible_asts': total_asts,
        'asts_pending': total_asts - with_symbols,
        'total_symbols': symbol_count,
        'coverage_pct': round(coverage_pct, 1),
    }


# =============================================================================
# Localization Detection
# =============================================================================

def get_loc_files_needing_parse(
    conn: sqlite3.Connection,
    parser_version_id: int,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Get localization files that have not been parsed yet.
    
    Args:
        conn: Database connection
        parser_version_id: Localization parser version
        limit: Maximum to return
        
    Returns:
        List of dicts with content_hash, relpath, size
    """
    query = """
        SELECT DISTINCT 
            fc.content_hash,
            f.relpath,
            fc.size
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.deleted = 0
        AND f.relpath LIKE 'localization/%.yml'
        AND fc.content_text IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM localization_entries le
            WHERE le.content_hash = fc.content_hash
            AND le.parser_version_id = ?
        )
        ORDER BY fc.size ASC
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    rows = conn.execute(query, (parser_version_id,)).fetchall()
    
    return [
        {'content_hash': r[0], 'relpath': r[1], 'size': r[2]}
        for r in rows
    ]


def get_loc_coverage(conn: sqlite3.Connection, parser_version_id: int) -> Dict[str, Any]:
    """Get localization parsing coverage statistics."""
    # Total loc files
    total_row = conn.execute("""
        SELECT COUNT(DISTINCT fc.content_hash)
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.deleted = 0
        AND f.relpath LIKE 'localization/%.yml'
        AND fc.content_text IS NOT NULL
    """).fetchone()
    total_loc = total_row[0]
    
    # Files with entries
    with_entries_row = conn.execute("""
        SELECT COUNT(DISTINCT content_hash)
        FROM localization_entries
        WHERE parser_version_id = ?
    """, (parser_version_id,)).fetchone()
    with_entries = with_entries_row[0]
    
    # Total entry count
    entry_count_row = conn.execute("""
        SELECT COUNT(*) FROM localization_entries
        WHERE parser_version_id = ?
    """, (parser_version_id,)).fetchone()
    entry_count = entry_count_row[0]
    
    coverage_pct = (with_entries / total_loc * 100) if total_loc > 0 else 0
    
    return {
        'total_loc_files': total_loc,
        'files_with_entries': with_entries,
        'files_pending': total_loc - with_entries,
        'total_entries': entry_count,
        'coverage_pct': round(coverage_pct, 1),
        'parser_version_id': parser_version_id,
    }


# =============================================================================
# Stale/Orphan Detection
# =============================================================================

def get_stale_entries(conn: sqlite3.Connection) -> Dict[str, int]:
    """
    Count entries that are orphaned (no longer linked to active files).
    
    Returns dict with counts for each type.
    """
    # Orphaned ASTs (content_hash not in any active file)
    orphan_ast_row = conn.execute("""
        SELECT COUNT(*) FROM asts a
        WHERE NOT EXISTS (
            SELECT 1 FROM files f
            WHERE f.content_hash = a.content_hash
            AND f.deleted = 0
        )
    """).fetchone()
    
    # Orphaned symbols (linked to deleted files)
    orphan_symbol_row = conn.execute("""
        SELECT COUNT(*) FROM symbols s
        WHERE NOT EXISTS (
            SELECT 1 FROM files f
            WHERE f.file_id = s.defining_file_id
            AND f.deleted = 0
        )
    """).fetchone()
    
    # Orphaned file_contents
    orphan_content_row = conn.execute("""
        SELECT COUNT(*) FROM file_contents fc
        WHERE NOT EXISTS (
            SELECT 1 FROM files f
            WHERE f.content_hash = fc.content_hash
            AND f.deleted = 0
        )
    """).fetchone()
    
    # Deleted files not yet purged
    deleted_row = conn.execute("""
        SELECT COUNT(*) FROM files WHERE deleted = 1
    """).fetchone()
    
    return {
        'orphaned_asts': orphan_ast_row[0],
        'orphaned_symbols': orphan_symbol_row[0],
        'orphaned_content': orphan_content_row[0],
        'deleted_files': deleted_row[0],
    }


# =============================================================================
# Performance Analysis
# =============================================================================

def get_slow_parses(
    conn: sqlite3.Connection,
    threshold_std_devs: float = 2.0,
    min_samples: int = 100
) -> List[SlowParseInfo]:
    """
    Identify statistical outliers in parse times.
    
    Note: This requires parse timing data to be stored in the database.
    If not available, returns empty list.
    
    Args:
        conn: Database connection
        threshold_std_devs: Z-score threshold for "slow"
        min_samples: Minimum samples needed for statistics
        
    Returns:
        List of SlowParseInfo for investigation
    """
    # Check if we have timing data
    # The asts table does not currently have parse_time column
    # This would need to be added to the schema
    
    # For now, we can estimate based on node_count vs file size ratio
    # High node count for small file size might indicate complex parsing
    
    rows = conn.execute("""
        SELECT 
            a.content_hash,
            f.relpath,
            fc.size,
            a.node_count
        FROM asts a
        JOIN files f ON a.content_hash = f.content_hash
        JOIN file_contents fc ON a.content_hash = fc.content_hash
        WHERE a.parse_ok = 1
        AND a.node_count > 0
        AND fc.size > 0
        GROUP BY a.content_hash
    """).fetchall()
    
    if len(rows) < min_samples:
        logger.info(f"Only {len(rows)} samples, need {min_samples} for statistics")
        return []
    
    # Calculate nodes per KB as complexity metric
    complexities = []
    for row in rows:
        content_hash, relpath, size, node_count = row
        nodes_per_kb = (node_count / size) * 1024
        complexities.append((content_hash, relpath, size, node_count, nodes_per_kb))
    
    # Calculate statistics
    values = [c[4] for c in complexities]
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    
    if stdev == 0:
        return []
    
    # Find outliers
    slow_parses = []
    for content_hash, relpath, size, node_count, complexity in complexities:
        z_score = (complexity - mean) / stdev
        if z_score >= threshold_std_devs:
            slow_parses.append(SlowParseInfo(
                content_hash=content_hash,
                filename=relpath,
                parse_time_ms=0,  # Not tracked yet
                file_size=size,
                node_count=node_count,
                z_score=round(z_score, 2),
            ))
    
    # Sort by z_score descending
    slow_parses.sort(key=lambda x: x.z_score, reverse=True)
    
    return slow_parses[:50]  # Top 50 outliers


# =============================================================================
# Rebuild Guardrails
# =============================================================================

@dataclass
class RebuildRecommendation:
    """Result of should_full_rebuild() check.
    
    IMPORTANT: A full rebuild is NEVER auto-approved.
    This recommendation must be shown to the user who can:
    - Accept the rebuild (explicit --force or interactive confirmation)
    - Override and continue with incremental update
    """
    requires_user_approval: bool
    reason: str
    severity: str  # 'required' (schema change), 'recommended', 'optional'
    details: Dict[str, Any]


def should_full_rebuild(conn: sqlite3.Connection) -> RebuildRecommendation:
    """
    Check if a full rebuild is warranted.
    
    GUARDRAIL: This function NEVER auto-approves a full rebuild.
    It only provides a recommendation that must be presented to the user.
    
    Severity levels:
    - 'required': Schema change detected, incremental update will fail
    - 'recommended': Significant changes detected, rebuild advised  
    - 'optional': Rebuild not needed, incremental update is fine
    
    Schema change detection:
    - Compares SCHEMA_VERSION constant against stored db_metadata
    - Schema version includes: table definitions, column names, indexes
    - Does NOT include: parser logic changes (handled by parser_version)
    
    Returns:
        RebuildRecommendation with user-presentable information
    """
    from ck3raven.db.schema import SCHEMA_VERSION
    
    details = {}
    
    # Check if database exists at all
    try:
        row = conn.execute("""
            SELECT value FROM db_metadata WHERE key = 'schema_version'
        """).fetchone()
    except sqlite3.OperationalError:
        return RebuildRecommendation(
            requires_user_approval=True,
            reason="Database schema not initialized - first run setup required",
            severity='required',
            details={'current_schema': None, 'expected_schema': SCHEMA_VERSION}
        )
    
    if not row:
        return RebuildRecommendation(
            requires_user_approval=True,
            reason="No schema version found - database needs initialization",
            severity='required',
            details={'current_schema': None, 'expected_schema': SCHEMA_VERSION}
        )
    
    stored_schema = row[0]
    details['current_schema'] = stored_schema
    details['expected_schema'] = SCHEMA_VERSION
    
    # Schema version comparison
    if stored_schema != SCHEMA_VERSION:
        return RebuildRecommendation(
            requires_user_approval=True,
            reason=f"Schema version mismatch: DB has v{stored_schema}, code expects v{SCHEMA_VERSION}",
            severity='required',
            details=details
        )
    
    # Check for critical data presence
    file_count = conn.execute("SELECT COUNT(*) FROM files WHERE deleted = 0").fetchone()[0]
    details['file_count'] = file_count
    
    if file_count == 0:
        return RebuildRecommendation(
            requires_user_approval=True,
            reason="Database is empty - initial content ingest required",
            severity='required',
            details=details
        )
    
    # All checks passed - incremental update is safe
    return RebuildRecommendation(
        requires_user_approval=False,
        reason="Schema is current, incremental update is safe",
        severity='optional',
        details=details
    )


def get_recommended_actions(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    Get prioritized list of recommended actions.
    
    Returns list of actions with priority, phase, count, and description.
    """
    actions = []
    
    # Get current parser version
    try:
        parser_row = conn.execute("""
            SELECT id FROM parsers WHERE version LIKE '1.%' ORDER BY id DESC LIMIT 1
        """).fetchone()
        script_parser_id = parser_row[0] if parser_row else 1
    except:
        script_parser_id = 1
    
    try:
        loc_parser_row = conn.execute("""
            SELECT id FROM parsers WHERE version LIKE 'loc-%' ORDER BY id DESC LIMIT 1
        """).fetchone()
        loc_parser_id = loc_parser_row[0] if loc_parser_row else 4
    except:
        loc_parser_id = 4
    
    # Check stale entries
    stale = get_stale_entries(conn)
    if stale['deleted_files'] > 0:
        actions.append({
            'priority': 1,
            'phase': 'cleanup',
            'action': 'purge_deleted',
            'count': stale['deleted_files'],
            'description': f"Purge {stale['deleted_files']} deleted file records",
        })
    
    # Check AST coverage
    ast_coverage = get_ast_coverage(conn, script_parser_id)
    if ast_coverage['files_pending'] > 0:
        actions.append({
            'priority': 2,
            'phase': 'ast',
            'action': 'generate_ast',
            'count': ast_coverage['files_pending'],
            'description': f"Generate AST for {ast_coverage['files_pending']} files",
        })
    
    # Check symbol coverage
    symbol_coverage = get_symbol_coverage(conn)
    if symbol_coverage['asts_pending'] > 0:
        actions.append({
            'priority': 3,
            'phase': 'symbols',
            'action': 'extract_symbols',
            'count': symbol_coverage['asts_pending'],
            'description': f"Extract symbols from {symbol_coverage['asts_pending']} ASTs",
        })
    
    # Check localization coverage
    loc_coverage = get_loc_coverage(conn, loc_parser_id)
    if loc_coverage['files_pending'] > 0:
        actions.append({
            'priority': 4,
            'phase': 'localization',
            'action': 'parse_localization',
            'count': loc_coverage['files_pending'],
            'description': f"Parse {loc_coverage['files_pending']} localization files",
        })
    
    # Cleanup orphans (low priority)
    total_orphans = stale['orphaned_asts'] + stale['orphaned_symbols'] + stale['orphaned_content']
    if total_orphans > 0:
        actions.append({
            'priority': 5,
            'phase': 'cleanup',
            'action': 'remove_orphans',
            'count': total_orphans,
            'description': f"Remove {total_orphans} orphaned entries",
        })
    
    return sorted(actions, key=lambda x: x['priority'])


# =============================================================================
# Main Status Function
# =============================================================================

def get_build_status(conn: sqlite3.Connection) -> WorkSummary:
    """
    Get comprehensive summary of what work is pending.
    
    This is the main function the builder wizard should call.
    """
    summary = WorkSummary()
    
    # Get totals
    summary.total_files = conn.execute(
        "SELECT COUNT(*) FROM files WHERE deleted = 0"
    ).fetchone()[0]
    
    summary.total_asts = conn.execute(
        "SELECT COUNT(*) FROM asts WHERE parse_ok = 1"
    ).fetchone()[0]
    
    summary.total_symbols = conn.execute(
        "SELECT COUNT(*) FROM symbols"
    ).fetchone()[0]
    
    # Get stale/orphan counts
    stale = get_stale_entries(conn)
    summary.orphaned_asts = stale['orphaned_asts']
    summary.orphaned_symbols = stale['orphaned_symbols']
    summary.orphaned_content = stale['orphaned_content']
    summary.files_to_delete = stale['deleted_files']
    
    # Get parser versions
    try:
        parser_row = conn.execute("""
            SELECT id FROM parsers WHERE version LIKE '1.%' ORDER BY id DESC LIMIT 1
        """).fetchone()
        script_parser_id = parser_row[0] if parser_row else 1
        
        loc_parser_row = conn.execute("""
            SELECT id FROM parsers WHERE version LIKE 'loc-%' ORDER BY id DESC LIMIT 1
        """).fetchone()
        loc_parser_id = loc_parser_row[0] if loc_parser_row else 4
    except:
        script_parser_id = 1
        loc_parser_id = 4
    
    # AST status
    ast_coverage = get_ast_coverage(conn, script_parser_id)
    summary.files_needing_ast = ast_coverage['files_pending']
    summary.files_with_failed_ast = ast_coverage['files_with_failed_ast']
    
    # Symbol status
    symbol_coverage = get_symbol_coverage(conn)
    summary.asts_needing_symbols = symbol_coverage['asts_pending']
    
    # Localization status
    loc_coverage = get_loc_coverage(conn, loc_parser_id)
    summary.loc_files_needing_parse = loc_coverage['files_pending']
    
    # Last build time from builder_runs (daemon's table)
    try:
        row = conn.execute("""
            SELECT completed_at FROM builder_runs 
            WHERE state = 'complete' 
            ORDER BY started_at DESC 
            LIMIT 1
        """).fetchone()
        if row:
            summary.last_build_time = row[0]
    except:
        pass
    
    return summary
