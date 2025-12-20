#!/usr/bin/env python3
"""
Unified Database Rebuild

Single command to fully rebuild the ck3raven database:
1. Ingest vanilla files
2. Ingest mod files  
3. Extract symbols from parsed AST
4. Build reference graph
5. Initialize conflict tables
6. Populate contribution records

Tracks build state in database to detect partial/stale builds.

Usage:
    python rebuild_database.py                  # Full rebuild
    python rebuild_database.py --resume         # Resume interrupted build
    python rebuild_database.py --status         # Check build status
    python rebuild_database.py --validate       # Validate DB completeness
    python rebuild_database.py --symbols-only   # Just symbol extraction
    python rebuild_database.py --chunk-debug 5  # Debug chunk 5 (files 2500-3000)
"""

import sys
import json
import time
import logging
import argparse
import traceback
import threading
import concurrent.futures
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass, asdict
from enum import Enum

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.db.schema import init_database, get_connection, DEFAULT_DB_PATH

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Parse with Timeout (for detecting hangs)
# =============================================================================

def parse_with_timeout(content: str, filename: str, timeout_seconds: float = 30.0):
    """
    Parse content with a timeout to detect hung files.
    Returns (ast, error_message) tuple.
    """
    from ck3raven.parser import parse_source
    
    result = [None, None]  # [ast, error]
    
    def do_parse():
        try:
            result[0] = parse_source(content, filename)
        except Exception as e:
            result[1] = str(e)
    
    thread = threading.Thread(target=do_parse)
    thread.daemon = True
    thread.start()
    thread.join(timeout=timeout_seconds)
    
    if thread.is_alive():
        # Thread is still running - timed out
        return None, f"TIMEOUT after {timeout_seconds}s"
    
    return result[0], result[1]


# =============================================================================
# Build State Tracking
# =============================================================================

class BuildPhase(Enum):
    """Phases of database build."""
    NOT_STARTED = "not_started"
    SCHEMA_INIT = "schema_init"
    VANILLA_INGEST = "vanilla_ingest"
    MOD_INGEST = "mod_ingest"
    SYMBOL_EXTRACTION = "symbol_extraction"
    REF_EXTRACTION = "ref_extraction"
    CONFLICT_TABLES = "conflict_tables"
    CONTRIBUTIONS = "contributions"
    FTS_INDEX = "fts_index"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class BuildState:
    """Tracks database build state with per-phase timestamps."""
    phase: str
    started_at: str
    updated_at: str
    vanilla_version: str
    playset_hash: str  # Hash of active mods to detect changes
    files_indexed: int
    symbols_extracted: int
    refs_extracted: int
    error_message: Optional[str] = None
    # Per-phase timestamps to detect staleness
    phase_timestamps: Dict[str, str] = None
    
    def __post_init__(self):
        if self.phase_timestamps is None:
            self.phase_timestamps = {}
    
    def to_json(self) -> str:
        data = asdict(self)
        return json.dumps(data, indent=2)
    
    @classmethod
    def from_json(cls, data: str) -> 'BuildState':
        parsed = json.loads(data)
        return cls(**parsed)
    
    def set_phase_complete(self, phase: str):
        """Mark a phase as complete with current timestamp."""
        self.phase_timestamps[phase] = datetime.now().isoformat()
    
    def get_phase_timestamp(self, phase: str) -> Optional[str]:
        """Get when a phase was last completed."""
        return self.phase_timestamps.get(phase)


def init_build_state_table(conn):
    """Create build_state table if not exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS build_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def get_build_state(conn) -> Optional[BuildState]:
    """Get current build state."""
    init_build_state_table(conn)
    row = conn.execute("SELECT value FROM build_state WHERE key = 'current'").fetchone()
    if row:
        try:
            return BuildState.from_json(row[0])
        except:
            return None
    return None


def set_build_state(conn, state: BuildState):
    """Update build state."""
    init_build_state_table(conn)
    state.updated_at = datetime.now().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO build_state (key, value, updated_at)
        VALUES ('current', ?, ?)
    """, (state.to_json(), state.updated_at))
    conn.commit()


def get_playset_hash(mods: list) -> str:
    """Hash of mod paths to detect playset changes."""
    import hashlib
    # Handle both string paths and dict objects
    if mods and isinstance(mods[0], dict):
        paths = sorted([m.get('path', str(m)) for m in mods])
    else:
        paths = sorted([str(m) for m in mods])
    content = json.dumps(paths, sort_keys=True)
    return hashlib.md5(content.encode()).hexdigest()[:12]


# =============================================================================
# Build Phases
# =============================================================================

VANILLA_PATH = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\game")
ACTIVE_MOD_PATHS_FILE = Path(r"C:\Users\Nathan\Documents\AI Workspace\active_mod_paths.json")


def load_active_mods() -> list:
    """Load active mod paths from JSON file."""
    if not ACTIVE_MOD_PATHS_FILE.exists():
        return []
    data = json.loads(ACTIVE_MOD_PATHS_FILE.read_text())
    return data.get("paths", [])


def get_ck3_version() -> str:
    """Detect CK3 version."""
    try:
        launcher_settings = VANILLA_PATH.parent / "launcher" / "launcher-settings.json"
        if launcher_settings.exists():
            data = json.loads(launcher_settings.read_text())
            return data.get("version", "1.18.x")
    except:
        pass
    return "1.18.x"


def phase_schema_init(conn, state: BuildState) -> bool:
    """Initialize database schema."""
    logger.info("Phase 1/7: Initializing database schema...")
    # Schema already initialized by get_connection
    state.phase = BuildPhase.SCHEMA_INIT.value
    state.set_phase_complete(BuildPhase.SCHEMA_INIT.value)
    set_build_state(conn, state)
    return True


def phase_vanilla_ingest(conn, state: BuildState) -> bool:
    """Ingest vanilla CK3 files."""
    logger.info("Phase 2/7: Ingesting vanilla CK3 files...")
    
    from ck3raven.db.ingest import ingest_vanilla
    
    if not VANILLA_PATH.exists():
        logger.error(f"Vanilla path not found: {VANILLA_PATH}")
        return False
    
    version = get_ck3_version()
    vanilla_version, result = ingest_vanilla(conn, VANILLA_PATH, version)
    
    state.phase = BuildPhase.VANILLA_INGEST.value
    state.vanilla_version = version
    state.files_indexed = result.stats.files_scanned
    state.set_phase_complete(BuildPhase.VANILLA_INGEST.value)
    set_build_state(conn, state)
    
    logger.info(f"  Vanilla files indexed: {result.stats.files_scanned}")
    return True


def phase_mod_ingest(conn, state: BuildState) -> bool:
    """Ingest active mod files."""
    logger.info("Phase 3/7: Ingesting mod files...")
    
    from ck3raven.db.ingest import ingest_mod
    
    mods = load_active_mods()
    state.playset_hash = get_playset_hash(mods)
    
    if not mods:
        logger.info("  No active mods to index")
        state.phase = BuildPhase.MOD_INGEST.value
        state.set_phase_complete(BuildPhase.MOD_INGEST.value)
        set_build_state(conn, state)
        return True
    
    total_files = 0
    for mod_entry in mods:
        # Handle both dict format and string format
        if isinstance(mod_entry, dict):
            mod_path_str = mod_entry.get('path', '')
            mod_name = mod_entry.get('name', Path(mod_path_str).name if mod_path_str else 'unknown')
        else:
            mod_path_str = str(mod_entry)
            mod_name = Path(mod_path_str).name
        
        if not mod_path_str:
            continue
            
        path = Path(mod_path_str)
        if not path.exists():
            logger.warning(f"  Mod path not found: {path}")
            continue
        
        logger.info(f"  Indexing: {mod_name}")
        mod_package, result = ingest_mod(conn, path, mod_name)
        total_files += result.stats.files_scanned
    
    state.phase = BuildPhase.MOD_INGEST.value
    state.files_indexed += total_files
    state.set_phase_complete(BuildPhase.MOD_INGEST.value)
    set_build_state(conn, state)
    
    logger.info(f"  Total mod files indexed: {total_files}")
    return True


def phase_symbol_extraction(conn, state: BuildState) -> bool:
    """Extract symbols from parsed files with chunked processing."""
    logger.info("Phase 4/7: Extracting symbols from files...")
    
    # Clear old symbols first - they may be stale
    logger.info("  Clearing old symbols...")
    conn.execute("DELETE FROM symbols")
    conn.commit()
    
    from ck3raven.parser import parse_source
    from ck3raven.db.symbols import extract_symbols_from_ast
    
    # Count total files first
    total_file_count = conn.execute("""
        SELECT COUNT(*) FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.deleted = 0
        AND f.relpath LIKE '%.txt'
        AND fc.content_text IS NOT NULL
    """).fetchone()[0]
    
    logger.info(f"  Total files to process: {total_file_count}")
    
    # Process in chunks to avoid memory issues and enable progress tracking
    chunk_size = 500
    offset = 0
    total_symbols = 0
    processed = 0
    errors = 0
    skipped_large = 0
    error_files = []
    max_file_size = 2_000_000  # Skip files larger than 2MB to avoid hangs
    start_time = time.time()
    
    while offset < total_file_count:
        chunk_start = time.time()
        
        # Get chunk of files with LIMIT/OFFSET
        rows = conn.execute("""
            SELECT f.file_id, f.relpath, f.content_hash, fc.content_text
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE f.deleted = 0
            AND f.relpath LIKE '%.txt'
            AND fc.content_text IS NOT NULL
            ORDER BY f.file_id
            LIMIT ? OFFSET ?
        """, (chunk_size, offset)).fetchall()
        
        if not rows:
            break
        
        chunk_symbols = 0
        chunk_errors = 0
        timed_out_files = []
        
        for file_id, relpath, content_hash, content in rows:
            # Skip very large files that cause parser hangs
            if content and len(content) > max_file_size:
                skipped_large += 1
                if skipped_large <= 5:
                    logger.debug(f"  Skipping large file ({len(content)} bytes): {relpath}")
                continue
            
            if not content:
                continue
            
            # Parse with timeout to detect hung files
            ast, parse_error = parse_with_timeout(content, relpath, timeout_seconds=30.0)
            
            if parse_error:
                errors += 1
                chunk_errors += 1
                if "TIMEOUT" in parse_error:
                    timed_out_files.append(relpath)
                    logger.warning(f"  TIMEOUT: {relpath}")
                elif len(error_files) < 20:
                    error_files.append({"file": relpath, "error": parse_error[:100]})
                continue
            
            if not ast:
                continue
                
            try:
                # Convert AST node to dict for extract_symbols_from_ast
                ast_dict = ast.to_dict() if hasattr(ast, 'to_dict') else ast
                symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
                
                for sym in symbols:
                    conn.execute("""
                        INSERT OR IGNORE INTO symbols 
                        (name, symbol_type, defining_file_id, line_number, metadata_json)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        sym.name if hasattr(sym, 'name') else sym['name'],
                        sym.kind if hasattr(sym, 'kind') else sym.get('symbol_type', 'unknown'),
                        file_id,
                        sym.line if hasattr(sym, 'line') else sym.get('line', 0),
                        json.dumps({'signature': getattr(sym, 'signature', None), 
                                   'doc': getattr(sym, 'doc', None)} if hasattr(sym, 'signature') else sym.get('context', {}))
                    ))
                
                chunk_symbols += len(symbols)
                total_symbols += len(symbols)
                processed += 1
                
            except Exception as e:
                errors += 1
                chunk_errors += 1
                if len(error_files) < 20:
                    error_files.append({"file": relpath, "error": str(e)[:100]})
        
        conn.commit()
        offset += len(rows)
        
        chunk_elapsed = time.time() - chunk_start
        total_elapsed = time.time() - start_time
        files_per_sec = processed / total_elapsed if total_elapsed > 0 else 0
        eta_seconds = (total_file_count - offset) / files_per_sec if files_per_sec > 0 else 0
        
        logger.info(
            f"  Chunk {offset}/{total_file_count} ({100*offset//total_file_count}%): "
            f"+{chunk_symbols} symbols, {chunk_errors} errors, "
            f"{chunk_elapsed:.1f}s, ETA: {eta_seconds/60:.1f}min"
        )
    
    state.phase = BuildPhase.SYMBOL_EXTRACTION.value
    state.symbols_extracted = total_symbols
    state.set_phase_complete(BuildPhase.SYMBOL_EXTRACTION.value)
    set_build_state(conn, state)
    
    logger.info(f"  COMPLETE: {total_symbols} symbols from {processed} files")
    logger.info(f"  Errors: {errors}, Large files skipped: {skipped_large}")
    
    if error_files:
        logger.info("  Sample errors:")
        for ef in error_files[:5]:
            logger.info(f"    - {ef['file']}: {ef['error']}")
    
    return True


def phase_ref_extraction(conn, state: BuildState) -> bool:
    """Extract references from parsed files with chunked processing."""
    logger.info("Phase 5/7: Extracting references...")
    
    # Clear old refs first - they may be stale
    logger.info("  Clearing old refs...")
    conn.execute("DELETE FROM refs")
    conn.commit()
    
    from ck3raven.db.symbols import extract_refs_from_ast
    
    # Count total files first
    total_file_count = conn.execute("""
        SELECT COUNT(*) FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.deleted = 0
        AND f.relpath LIKE '%.txt'
        AND fc.content_text IS NOT NULL
    """).fetchone()[0]
    
    logger.info(f"  Total files to process: {total_file_count}")
    
    # Process in chunks
    chunk_size = 500
    offset = 0
    total_refs = 0
    processed = 0
    errors = 0
    max_file_size = 2_000_000
    start_time = time.time()
    
    while offset < total_file_count:
        chunk_start = time.time()
        
        rows = conn.execute("""
            SELECT f.file_id, f.relpath, f.content_hash, fc.content_text
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE f.deleted = 0
            AND f.relpath LIKE '%.txt'
            AND fc.content_text IS NOT NULL
            ORDER BY f.file_id
            LIMIT ? OFFSET ?
        """, (chunk_size, offset)).fetchall()
        
        if not rows:
            break
        
        chunk_refs = 0
        chunk_errors = 0
        
        for file_id, relpath, content_hash, content in rows:
            if not content or len(content) > max_file_size:
                continue
            
            # Parse with timeout
            ast, parse_error = parse_with_timeout(content, relpath, timeout_seconds=30.0)
            
            if parse_error or not ast:
                errors += 1
                chunk_errors += 1
                continue
                
            try:
                ast_dict = ast.to_dict() if hasattr(ast, 'to_dict') else ast
                refs = list(extract_refs_from_ast(ast_dict, relpath, content_hash))
                
                for ref in refs:
                    conn.execute("""
                        INSERT OR IGNORE INTO refs
                        (name, ref_type, referring_file_id, line_number, context_key)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        ref.name if hasattr(ref, 'name') else ref['name'],
                        ref.kind if hasattr(ref, 'kind') else ref['ref_type'],
                        file_id,
                        ref.line if hasattr(ref, 'line') else ref.get('line', 0),
                        ref.context if hasattr(ref, 'context') else ref.get('context_key', '')
                    ))
                
                chunk_refs += len(refs)
                total_refs += len(refs)
                processed += 1
                
            except:
                errors += 1
                chunk_errors += 1
        
        conn.commit()
        offset += len(rows)
        
        chunk_elapsed = time.time() - chunk_start
        total_elapsed = time.time() - start_time
        files_per_sec = processed / total_elapsed if total_elapsed > 0 else 0
        eta_seconds = (total_file_count - offset) / files_per_sec if files_per_sec > 0 else 0
        
        logger.info(
            f"  Chunk {offset}/{total_file_count} ({100*offset//total_file_count}%): "
            f"+{chunk_refs} refs, {chunk_errors} errors, "
            f"{chunk_elapsed:.1f}s, ETA: {eta_seconds/60:.1f}min"
        )
    
    state.phase = BuildPhase.REF_EXTRACTION.value
    state.refs_extracted = total_refs
    state.set_phase_complete(BuildPhase.REF_EXTRACTION.value)
    set_build_state(conn, state)
    
    logger.info(f"  COMPLETE: {total_refs} refs from {processed} files, {errors} errors")
    return True


def phase_conflict_tables(conn, state: BuildState) -> bool:
    """Initialize conflict detection tables."""
    logger.info("Phase 6/7: Initializing conflict tables...")
    
    try:
        from ck3raven.resolver.contributions import init_contribution_schema
        init_contribution_schema(conn)
    except ImportError:
        logger.warning("  Conflict tables module not found, skipping")
    
    state.phase = BuildPhase.CONFLICT_TABLES.value
    state.set_phase_complete(BuildPhase.CONFLICT_TABLES.value)
    set_build_state(conn, state)
    return True


def phase_fts_rebuild(conn, state: BuildState) -> bool:
    """Rebuild FTS indexes."""
    logger.info("Phase 7/7: Rebuilding FTS indexes...")
    
    # Rebuild symbols FTS
    try:
        conn.execute("INSERT INTO symbols_fts(symbols_fts) VALUES('rebuild')")
        conn.commit()
    except Exception as e:
        logger.debug(f"  symbols_fts rebuild: {e}")
    
    # Rebuild refs FTS
    try:
        conn.execute("INSERT INTO refs_fts(refs_fts) VALUES('rebuild')")
        conn.commit()
    except Exception as e:
        logger.debug(f"  refs_fts rebuild: {e}")
    
    state.phase = BuildPhase.COMPLETE.value
    state.set_phase_complete(BuildPhase.FTS_INDEX.value)
    set_build_state(conn, state)
    
    logger.info("  FTS indexes rebuilt")
    return True


# =============================================================================
# Main Orchestrator
# =============================================================================

BUILD_PHASES = [
    (BuildPhase.SCHEMA_INIT, phase_schema_init),
    (BuildPhase.VANILLA_INGEST, phase_vanilla_ingest),
    (BuildPhase.MOD_INGEST, phase_mod_ingest),
    (BuildPhase.SYMBOL_EXTRACTION, phase_symbol_extraction),
    (BuildPhase.REF_EXTRACTION, phase_ref_extraction),
    (BuildPhase.CONFLICT_TABLES, phase_conflict_tables),
    (BuildPhase.FTS_INDEX, phase_fts_rebuild),
]


def get_phase_index(phase_name: str) -> int:
    """Get index of phase in BUILD_PHASES."""
    for i, (phase, _) in enumerate(BUILD_PHASES):
        if phase.value == phase_name:
            return i
    return 0


def run_build(conn, resume: bool = False) -> bool:
    """Run full database build."""
    
    state = get_build_state(conn)
    start_phase = 0
    
    if resume and state and state.phase != BuildPhase.COMPLETE.value:
        # Resume from last completed phase
        start_phase = get_phase_index(state.phase) + 1
        logger.info(f"Resuming from phase {start_phase + 1}: {BUILD_PHASES[start_phase][0].value}")
    else:
        # Fresh build
        state = BuildState(
            phase=BuildPhase.NOT_STARTED.value,
            started_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            vanilla_version="",
            playset_hash="",
            files_indexed=0,
            symbols_extracted=0,
            refs_extracted=0,
        )
    
    total_phases = len(BUILD_PHASES)
    
    for i, (phase, phase_func) in enumerate(BUILD_PHASES[start_phase:], start=start_phase):
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"Phase {i+1}/{total_phases}: {phase.value}")
            logger.info(f"{'='*60}")
            
            success = phase_func(conn, state)
            
            if not success:
                state.phase = BuildPhase.FAILED.value
                state.error_message = f"Phase {phase.value} failed"
                set_build_state(conn, state)
                return False
                
        except Exception as e:
            logger.error(f"Error in phase {phase.value}: {e}")
            traceback.print_exc()
            state.phase = BuildPhase.FAILED.value
            state.error_message = str(e)
            set_build_state(conn, state)
            return False
    
    logger.info(f"\n{'='*60}")
    logger.info("BUILD COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"Files indexed: {state.files_indexed}")
    logger.info(f"Symbols extracted: {state.symbols_extracted}")
    logger.info(f"References extracted: {state.refs_extracted}")
    
    return True


def check_status(conn) -> Dict[str, Any]:
    """Check database build status including staleness detection."""
    state = get_build_state(conn)
    
    # Get counts
    files = conn.execute("SELECT COUNT(*) FROM files WHERE deleted = 0").fetchone()[0]
    symbols = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    refs = conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
    
    status = {
        "build_state": state.phase if state else "unknown",
        "last_updated": state.updated_at if state else None,
        "vanilla_version": state.vanilla_version if state else None,
        "files_indexed": files,
        "symbols_extracted": symbols,
        "refs_extracted": refs,
        "is_complete": state.phase == BuildPhase.COMPLETE.value if state else False,
        "needs_rebuild": False,
        "stale_phases": [],
        "phase_timestamps": {},
    }
    
    # Check phase timestamps for staleness
    if state and state.phase_timestamps:
        status["phase_timestamps"] = state.phase_timestamps
        
        # Get file ingest time (most recent of vanilla or mod ingest)
        file_ingest_time = None
        vanilla_time = state.get_phase_timestamp(BuildPhase.VANILLA_INGEST.value)
        mod_time = state.get_phase_timestamp(BuildPhase.MOD_INGEST.value)
        
        if vanilla_time and mod_time:
            file_ingest_time = max(vanilla_time, mod_time)
        elif vanilla_time:
            file_ingest_time = vanilla_time
        elif mod_time:
            file_ingest_time = mod_time
        
        # Check if derived data is older than file ingest
        if file_ingest_time:
            symbol_time = state.get_phase_timestamp(BuildPhase.SYMBOL_EXTRACTION.value)
            ref_time = state.get_phase_timestamp(BuildPhase.REF_EXTRACTION.value)
            
            if not symbol_time or symbol_time < file_ingest_time:
                status["stale_phases"].append("symbol_extraction")
            if not ref_time or ref_time < file_ingest_time:
                status["stale_phases"].append("ref_extraction")
    elif state and state.phase in [BuildPhase.VANILLA_INGEST.value, BuildPhase.MOD_INGEST.value]:
        # Files were ingested but no timestamp tracking - symbols likely stale
        if symbols > 0:
            status["stale_phases"].append("symbol_extraction")
            status["stale_phases"].append("ref_extraction")
    
    # Check if rebuild needed
    if state:
        current_mods = load_active_mods()
        current_hash = get_playset_hash(current_mods)
        if current_hash != state.playset_hash:
            status["needs_rebuild"] = True
            status["rebuild_reason"] = "Playset changed"
        elif status["stale_phases"]:
            status["needs_rebuild"] = True
            status["rebuild_reason"] = f"Stale phases: {', '.join(status['stale_phases'])}"
    else:
        status["needs_rebuild"] = True
        status["rebuild_reason"] = "No build state found"
    
    return status


def validate_db(conn) -> Dict[str, Any]:
    """Validate database completeness and detect stale data."""
    issues = []
    warnings = []
    
    # Check build state
    state = get_build_state(conn)
    if not state:
        issues.append("No build state - database may not be initialized")
    elif state.phase != BuildPhase.COMPLETE.value:
        issues.append(f"Build incomplete - stopped at phase: {state.phase}")
    
    # Check file content
    files_no_content = conn.execute("""
        SELECT COUNT(*) FROM files f
        LEFT JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.deleted = 0 AND f.relpath LIKE '%.txt' AND fc.content_text IS NULL
    """).fetchone()[0]
    if files_no_content > 0:
        issues.append(f"{files_no_content} text files missing content")
    
    # Check symbols
    symbols = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    if symbols == 0:
        issues.append("No symbols extracted - run symbol extraction")
    
    # Check refs
    refs = conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
    if refs == 0:
        issues.append("No references extracted - run ref extraction")
    
    # Check for key symbol types
    trait_count = conn.execute("SELECT COUNT(*) FROM symbols WHERE symbol_type = 'trait'").fetchone()[0]
    if trait_count == 0:
        issues.append("No traits found - symbol extraction may have failed")
    
    event_count = conn.execute("SELECT COUNT(*) FROM symbols WHERE symbol_type = 'event'").fetchone()[0]
    if event_count == 0:
        issues.append("No events found - symbol extraction may have failed")
    
    # Check for staleness using phase timestamps
    if state and state.phase_timestamps:
        vanilla_time = state.get_phase_timestamp(BuildPhase.VANILLA_INGEST.value)
        mod_time = state.get_phase_timestamp(BuildPhase.MOD_INGEST.value)
        symbol_time = state.get_phase_timestamp(BuildPhase.SYMBOL_EXTRACTION.value)
        ref_time = state.get_phase_timestamp(BuildPhase.REF_EXTRACTION.value)
        
        file_ingest_time = None
        if vanilla_time and mod_time:
            file_ingest_time = max(vanilla_time, mod_time)
        elif vanilla_time:
            file_ingest_time = vanilla_time
        elif mod_time:
            file_ingest_time = mod_time
        
        if file_ingest_time:
            if not symbol_time or symbol_time < file_ingest_time:
                warnings.append("Symbols may be STALE - extracted before latest file ingest")
            if not ref_time or ref_time < file_ingest_time:
                warnings.append("Refs may be STALE - extracted before latest file ingest")
    elif state and symbols > 0:
        # No timestamps but we have symbols - they might be stale
        warnings.append("Cannot verify symbol freshness - no phase timestamps (rebuild recommended)")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "stats": {
            "symbols": symbols,
            "refs": refs,
            "traits": trait_count,
            "events": event_count,
        },
        "phase_timestamps": state.phase_timestamps if state else {},
    }


def run_from_phase(conn, start_phase: BuildPhase) -> bool:
    """Run build starting from a specific phase (for fixing stale data)."""
    state = get_build_state(conn) or BuildState(
        phase=BuildPhase.NOT_STARTED.value,
        started_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        vanilla_version="",
        playset_hash="",
        files_indexed=0,
        symbols_extracted=0,
        refs_extracted=0,
    )
    
    start_idx = get_phase_index(start_phase.value)
    total_phases = len(BUILD_PHASES)
    
    logger.info(f"Running phases {start_idx + 1} to {total_phases}...")
    
    for i, (phase, phase_func) in enumerate(BUILD_PHASES[start_idx:], start=start_idx):
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"Phase {i+1}/{total_phases}: {phase.value}")
            logger.info(f"{'='*60}")
            
            success = phase_func(conn, state)
            
            if not success:
                state.phase = BuildPhase.FAILED.value
                state.error_message = f"Phase {phase.value} failed"
                set_build_state(conn, state)
                return False
                
        except Exception as e:
            logger.error(f"Error in phase {phase.value}: {e}")
            traceback.print_exc()
            state.phase = BuildPhase.FAILED.value
            state.error_message = str(e)
            set_build_state(conn, state)
            return False
    
    logger.info(f"\n{'='*60}")
    logger.info("BUILD COMPLETE")
    logger.info(f"{'='*60}")
    return True


def debug_chunk(conn, chunk_number: int, chunk_size: int = 500):
    """Debug a specific chunk of files to identify problematic files."""
    from ck3raven.parser import parse_source
    
    offset = chunk_number * chunk_size
    
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, LENGTH(fc.content_text) as size
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.deleted = 0
        AND f.relpath LIKE '%.txt'
        AND fc.content_text IS NOT NULL
        ORDER BY f.file_id
        LIMIT ? OFFSET ?
    """, (chunk_size, offset)).fetchall()
    
    logger.info(f"Chunk {chunk_number}: files {offset} to {offset + len(rows)}")
    logger.info(f"Files in chunk: {len(rows)}")
    
    for file_id, relpath, content_hash, size in rows:
        logger.info(f"  [{file_id}] {relpath} ({size} bytes)")
        
        # Try to parse this file with timeout-like behavior
        content_row = conn.execute(
            "SELECT content_text FROM file_contents WHERE content_hash = ?",
            (content_hash,)
        ).fetchone()
        
        if not content_row or not content_row[0]:
            logger.warning(f"    -> No content!")
            continue
        
        content = content_row[0]
        try:
            start = time.time()
            ast = parse_source(content, relpath)
            elapsed = time.time() - start
            
            if elapsed > 1.0:
                logger.warning(f"    -> SLOW: {elapsed:.2f}s")
            else:
                logger.info(f"    -> OK ({elapsed:.3f}s)")
                
        except Exception as e:
            logger.error(f"    -> ERROR: {e}")


def main():
    parser = argparse.ArgumentParser(description="Unified database rebuild")
    parser.add_argument("--resume", action="store_true", help="Resume interrupted build")
    parser.add_argument("--status", action="store_true", help="Check build status")
    parser.add_argument("--validate", action="store_true", help="Validate DB completeness")
    parser.add_argument("--refresh-symbols", action="store_true", 
                        help="Re-run symbol and ref extraction (fixes stale derived data)")
    parser.add_argument("--force", action="store_true",
                        help="Force complete re-ingest by clearing all file content first")
    parser.add_argument("--symbols-only", action="store_true",
                        help="Only run symbol extraction (skip refs)")
    parser.add_argument("--refs-only", action="store_true",
                        help="Only run ref extraction (skip symbols)")
    parser.add_argument("--chunk-debug", type=int, default=None,
                        help="Process only a specific chunk (for debugging hangs)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Database path")
    args = parser.parse_args()
    
    # Initialize/open database
    logger.info(f"Database: {args.db}")
    init_database(args.db)
    conn = get_connection(args.db)
    
    try:
        if args.force:
            # Force re-ingest: clear all content tables
            logger.info("Force mode: clearing all file content for fresh ingest...")
            # Disable foreign keys temporarily for clean wipe
            conn.execute("PRAGMA foreign_keys = OFF")
            # Use DELETE FROM with EXISTS check for new databases
            for table in ["symbols", "refs", "files", "file_contents", "content_versions", "build_state"]:
                try:
                    conn.execute(f"DELETE FROM {table}")
                except Exception:
                    pass  # Table may not exist in fresh DB
            conn.execute("PRAGMA foreign_keys = ON")
            conn.commit()
            logger.info("  Content tables cleared")
            # --force implies we want to rebuild
            args.resume = False
        
        if args.status and not args.force:
            status = check_status(conn)
            print(json.dumps(status, indent=2))
            if status.get("stale_phases"):
                print(f"\n⚠️  Stale phases detected: {', '.join(status['stale_phases'])}")
                print("   Run with --refresh-symbols to fix")
            
        elif args.validate and not args.force:
            result = validate_db(conn)
            print(json.dumps(result, indent=2))
            if result.get("warnings"):
                print("\n⚠️  Warnings:")
                for w in result["warnings"]:
                    print(f"   - {w}")
            if not result["valid"]:
                print("\n❌ Issues found:")
                for issue in result["issues"]:
                    print(f"   - {issue}")
                print("\nTo fix, run: python rebuild_database.py")
                sys.exit(1)
            else:
                print("\n✅ Database valid")
        
        elif args.refresh_symbols and not args.force:
            # Re-run symbol/ref extraction from freshly ingested files
            logger.info("Refreshing symbols and refs from current file content...")
            start_time = time.time()
            success = run_from_phase(conn, BuildPhase.SYMBOL_EXTRACTION)
            elapsed = time.time() - start_time
            logger.info(f"\nTotal time: {elapsed:.1f} seconds")
            if not success:
                logger.error("Refresh failed!")
                sys.exit(1)
        
        elif args.symbols_only:
            # Just run symbol extraction
            logger.info("Running symbol extraction only...")
            state = get_build_state(conn) or BuildState(
                phase=BuildPhase.NOT_STARTED.value,
                started_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                vanilla_version="",
                playset_hash="",
                files_indexed=0,
                symbols_extracted=0,
                refs_extracted=0,
            )
            start_time = time.time()
            success = phase_symbol_extraction(conn, state)
            elapsed = time.time() - start_time
            logger.info(f"\nTotal time: {elapsed:.1f} seconds")
            if not success:
                logger.error("Symbol extraction failed!")
                sys.exit(1)
        
        elif args.refs_only:
            # Just run ref extraction
            logger.info("Running ref extraction only...")
            state = get_build_state(conn) or BuildState(
                phase=BuildPhase.NOT_STARTED.value,
                started_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                vanilla_version="",
                playset_hash="",
                files_indexed=0,
                symbols_extracted=0,
                refs_extracted=0,
            )
            start_time = time.time()
            success = phase_ref_extraction(conn, state)
            elapsed = time.time() - start_time
            logger.info(f"\nTotal time: {elapsed:.1f} seconds")
            if not success:
                logger.error("Ref extraction failed!")
                sys.exit(1)
        
        elif args.chunk_debug is not None:
            # Debug a specific chunk
            logger.info(f"Debugging chunk {args.chunk_debug}...")
            debug_chunk(conn, args.chunk_debug)
                
        else:
            # Run full build
            start_time = time.time()
            success = run_build(conn, resume=args.resume)
            elapsed = time.time() - start_time
            
            logger.info(f"\nTotal time: {elapsed:.1f} seconds")
            
            if not success:
                logger.error("Build failed!")
                sys.exit(1)
    
    finally:
        conn.close()


if __name__ == "__main__":
    main()