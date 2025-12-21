#!/usr/bin/env python3
"""
Standalone rebuild daemon that runs completely detached from terminals.

This script is designed to be launched and then forgotten - it will:
1. Detach from the parent process completely
2. Write all progress to log files
3. Handle database locks with retries
4. Create a PID file for monitoring
5. Write periodic heartbeats for liveness checking

Usage:
    python rebuild_daemon.py start [--force] [--db PATH]
    python rebuild_daemon.py status
    python rebuild_daemon.py stop
    python rebuild_daemon.py logs [-f]
"""

import sys
import os
import json
import time
import sqlite3
import hashlib
import subprocess
import argparse
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

# Paths
DEFAULT_DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"
DAEMON_DIR = Path.home() / ".ck3raven" / "daemon"
PID_FILE = DAEMON_DIR / "rebuild.pid"
STATUS_FILE = DAEMON_DIR / "rebuild_status.json"
LOG_FILE = DAEMON_DIR / "rebuild.log"
HEARTBEAT_FILE = DAEMON_DIR / "heartbeat"

# Ensure daemon directory exists
DAEMON_DIR.mkdir(parents=True, exist_ok=True)


class DaemonLogger:
    """File-based logger that doesn't use stdout/stderr."""
    
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self._ensure_file()
    
    def _ensure_file(self):
        if not self.log_path.exists():
            self.log_path.write_text("")
    
    def log(self, level: str, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}\n"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line)
    
    def info(self, message: str):
        self.log("INFO", message)
    
    def error(self, message: str):
        self.log("ERROR", message)
    
    def warning(self, message: str):
        self.log("WARN", message)
    
    def debug(self, message: str):
        self.log("DEBUG", message)


class StatusWriter:
    """Writes status to a JSON file for external monitoring."""
    
    def __init__(self, status_path: Path):
        self.status_path = status_path
        self._status = {
            "state": "initializing",
            "phase": None,
            "phase_number": 0,
            "total_phases": 7,
            "progress": 0.0,
            "message": "",
            "started_at": None,
            "updated_at": None,
            "error": None,
            "stats": {}
        }
    
    def update(self, **kwargs):
        self._status.update(kwargs)
        self._status["updated_at"] = datetime.now().isoformat()
        self._write()
    
    def _write(self):
        try:
            # Write atomically
            tmp_path = self.status_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(self._status, indent=2))
            tmp_path.replace(self.status_path)
        except Exception:
            pass  # Best effort
    
    def get(self) -> dict:
        return self._status.copy()


class DatabaseWrapper:
    """Database connection wrapper with lock handling and retries."""
    
    def __init__(self, db_path: Path, logger: DaemonLogger, max_retries: int = 10, base_delay: float = 1.0):
        self.db_path = db_path
        self.logger = logger
        self.max_retries = max_retries
        self.base_delay = base_delay
        self._conn: Optional[sqlite3.Connection] = None
    
    def connect(self) -> sqlite3.Connection:
        """Connect with retry logic for locked databases."""
        for attempt in range(self.max_retries):
            try:
                conn = sqlite3.connect(
                    str(self.db_path),
                    timeout=30.0,  # Wait up to 30s for locks
                    isolation_level=None  # Autocommit mode
                )
                # Enable WAL mode for better concurrency
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=30000")  # 30s busy timeout
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.row_factory = sqlite3.Row
                self._conn = conn
                self.logger.info(f"Database connected: {self.db_path}")
                return conn
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    delay = self.base_delay * (2 ** attempt)
                    self.logger.warning(f"Database locked, retry {attempt + 1}/{self.max_retries} in {delay:.1f}s")
                    time.sleep(delay)
                else:
                    raise
        
        raise RuntimeError(f"Failed to connect to database after {self.max_retries} retries")
    
    def checkpoint(self):
        """Force WAL checkpoint to consolidate changes."""
        if self._conn:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self.logger.debug("WAL checkpoint completed")
            except Exception as e:
                self.logger.warning(f"WAL checkpoint failed: {e}")
    
    def close(self):
        """Close connection cleanly."""
        if self._conn:
            try:
                self.checkpoint()
                self._conn.close()
                self.logger.info("Database connection closed")
            except Exception as e:
                self.logger.warning(f"Error closing database: {e}")
            finally:
                self._conn = None


def write_heartbeat():
    """Write current timestamp to heartbeat file."""
    try:
        HEARTBEAT_FILE.write_text(str(time.time()))
    except Exception:
        pass


def is_daemon_running() -> bool:
    """Check if daemon is already running."""
    if not PID_FILE.exists():
        return False
    
    try:
        pid = int(PID_FILE.read_text().strip())
        # Check if process exists (Windows-compatible)
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            # Also check heartbeat freshness (process might be hung)
            if HEARTBEAT_FILE.exists():
                last_heartbeat = float(HEARTBEAT_FILE.read_text().strip())
                if time.time() - last_heartbeat > 120:  # 2 minutes stale
                    return False  # Daemon is hung
            return True
        return False
    except Exception:
        return False


def write_pid():
    """Write current process PID."""
    PID_FILE.write_text(str(os.getpid()))


def cleanup_pid():
    """Remove PID file."""
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def run_rebuild(db_path: Path, force: bool, logger: DaemonLogger, status: StatusWriter, symbols_only: bool = False):
    """Main rebuild logic - runs in the detached process."""
    
    status.update(state="starting", started_at=datetime.now().isoformat())
    write_heartbeat()
    
    # Add the ck3raven package to path
    src_path = Path(__file__).parent.parent / "src"
    if src_path.exists():
        sys.path.insert(0, str(src_path))
    
    try:
        # Import after path setup
        from ck3raven.db.schema import init_database, get_connection
        from ck3raven.db.ingest import ingest_vanilla, ingest_mod
        
        logger.info(f"Starting rebuild with db={db_path}, force={force}, symbols_only={symbols_only}")
        
        # Connect with retry logic
        db_wrapper = DatabaseWrapper(db_path, logger)
        
        status.update(state="connecting", message="Connecting to database...")
        write_heartbeat()
        
        # Initialize schema first (this creates tables if needed)
        logger.info("Initializing database schema...")
        init_database(db_path)
        
        conn = db_wrapper.connect()
        
        if force and not symbols_only:
            status.update(state="clearing", message="Clearing existing data...")
            write_heartbeat()
            logger.info("Force mode: clearing tables...")
            
            for table in ["symbols", "refs", "files", "file_contents", "content_versions", "build_state"]:
                try:
                    conn.execute(f"DELETE FROM {table}")
                    logger.debug(f"Cleared table: {table}")
                except Exception as e:
                    logger.debug(f"Table {table} clear skipped: {e}")
            
            logger.info("Tables cleared")
        
        if not symbols_only:
            # Phase 1: Vanilla ingest
            status.update(
                state="running",
                phase="vanilla_ingest",
                phase_number=1,
                message="Ingesting vanilla CK3 files..."
            )
            write_heartbeat()
            
            vanilla_path = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\game")
            if not vanilla_path.exists():
                raise RuntimeError(f"Vanilla path not found: {vanilla_path}")
            
            logger.info(f"Ingesting vanilla from {vanilla_path}")
            
            # Use chunked ingest with progress reporting
            version, result = ingest_vanilla_chunked(conn, vanilla_path, "1.18.x", logger, status)
            
            logger.info(f"Vanilla ingest complete: {result}")
            status.update(
                stats={"vanilla_files": result.stats.files_scanned if hasattr(result, 'stats') else 0}
            )
            
            # Checkpoint after vanilla
            db_wrapper.checkpoint()
            write_heartbeat()
            
            # Phase 2: Mod ingest - ALL mods, not just playset
            status.update(
                phase="mod_ingest",
                phase_number=2,
                message="Ingesting all mod files..."
            )
            write_heartbeat()
            
            ingest_all_mods(conn, logger, status)
            db_wrapper.checkpoint()
        else:
            # symbols_only mode - clear only symbols and refs
            logger.info("Symbols-only mode: clearing symbols and refs...")
            conn.execute("DELETE FROM symbols")
            conn.execute("DELETE FROM refs")
            conn.commit()
            logger.info("Symbols and refs cleared")
        
        # Phase 3: AST generation - parse files and store ASTs
        status.update(
            phase="ast_generation",
            phase_number=3,
            message="Generating ASTs..."
        )
        write_heartbeat()
        
        generate_missing_asts(conn, logger, status, force=force)
        db_wrapper.checkpoint()
        
        # Phase 4: Symbol extraction from stored ASTs
        status.update(
            phase="symbol_extraction", 
            phase_number=4,
            message="Extracting symbols..."
        )
        write_heartbeat()
        
        extract_symbols_from_stored_asts(conn, logger, status)
        db_wrapper.checkpoint()
        
        # Phase 5: Ref extraction from stored ASTs
        status.update(
            phase="ref_extraction",
            phase_number=5, 
            message="Extracting references..."
        )
        write_heartbeat()
        
        extract_refs_from_stored_asts(conn, logger, status)
        db_wrapper.checkpoint()
        
        # Done
        status.update(
            state="complete",
            phase="done",
            phase_number=7,
            progress=100.0,
            message="Rebuild complete!"
        )
        
        db_wrapper.close()
        logger.info("Rebuild completed successfully!")
        
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(f"Rebuild failed: {error_msg}")
        logger.error(traceback.format_exc())
        status.update(
            state="error",
            error=error_msg,
            message=f"Failed: {error_msg}"
        )
        raise


def ingest_vanilla_chunked(conn, vanilla_path: Path, version: str, logger: DaemonLogger, status: StatusWriter):
    """Ingest vanilla files with progress reporting via callback."""
    from ck3raven.db.ingest import ingest_vanilla
    
    def progress_callback(done, total):
        write_heartbeat()
        if total > 0:
            pct = (done / total) * 100
            status.update(progress=pct, message=f"Vanilla ingest: {done}/{total} files ({pct:.1f}%)")
            if done % 5000 == 0:
                logger.info(f"Vanilla progress: {done}/{total} ({pct:.1f}%)")
    
    # The updated ingest_vanilla now accepts progress_callback
    return ingest_vanilla(conn, vanilla_path, version, progress_callback=progress_callback)


def extract_symbols_chunked(conn, logger: DaemonLogger, status: StatusWriter):
    """Extract symbols with chunked processing and heartbeat."""
    from ck3raven.parser import parse_source
    from ck3raven.db.symbols import extract_symbols_from_ast
    
    logger.info("Starting symbol extraction...")
    
    # Clear old symbols
    conn.execute("DELETE FROM symbols")
    
    # Count files
    total_count = conn.execute("""
        SELECT COUNT(*) FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.deleted = 0 AND f.relpath LIKE '%.txt'
        AND fc.content_text IS NOT NULL
    """).fetchone()[0]
    
    logger.info(f"Processing {total_count} files for symbols")
    
    chunk_size = 500
    offset = 0
    processed = 0
    total_symbols = 0
    errors = 0
    
    while offset < total_count:
        write_heartbeat()
        
        rows = conn.execute("""
            SELECT f.file_id, f.relpath, f.content_hash, fc.content_text
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE f.deleted = 0 AND f.relpath LIKE '%.txt'
            AND fc.content_text IS NOT NULL
            ORDER BY f.file_id
            LIMIT ? OFFSET ?
        """, (chunk_size, offset)).fetchall()
        
        if not rows:
            break
        
        chunk_symbols = 0
        
        for file_id, relpath, content_hash, content in rows:
            if not content or len(content) > 2_000_000:
                continue
            
            try:
                ast = parse_source(content, relpath)
                if ast:
                    ast_dict = ast.to_dict() if hasattr(ast, 'to_dict') else ast
                    symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
                    
                    for sym in symbols:
                        # ExtractedSymbol is a dataclass - use attribute access
                        # Schema columns: symbol_type, name, scope, defining_file_id, line_number
                        name = sym.name
                        kind = sym.kind
                        line = sym.line
                        scope = getattr(sym, 'scope', None)
                        
                        conn.execute("""
                            INSERT OR IGNORE INTO symbols
                            (symbol_type, name, scope, defining_file_id, line_number, content_version_id)
                            VALUES (?, ?, ?, ?, ?, (SELECT content_version_id FROM files WHERE file_id = ?))
                        """, (kind, name, scope, file_id, line, file_id))
                    
                    chunk_symbols += len(symbols)
                    total_symbols += len(symbols)
                
                processed += 1
                
            except Exception as e:
                errors += 1
                if errors <= 10:
                    logger.warning(f"Parse error in {relpath}: {e}")
        
        conn.commit()
        
        offset += len(rows)
        pct = (offset / total_count) * 100
        status.update(
            progress=pct,
            message=f"Symbols: {offset}/{total_count} files, {total_symbols} symbols"
        )
        
        if offset % 2000 == 0:
            logger.info(f"Symbol progress: {offset}/{total_count} ({pct:.1f}%), {total_symbols} symbols, {errors} errors")
    
    logger.info(f"Symbol extraction complete: {processed} files, {total_symbols} symbols, {errors} errors")


def extract_refs_chunked(conn, logger: DaemonLogger, status: StatusWriter):
    """Extract references with chunked processing and heartbeat."""
    from ck3raven.parser import parse_source
    from ck3raven.db.symbols import extract_refs_from_ast
    
    logger.info("Starting reference extraction...")
    
    # Clear old refs
    conn.execute("DELETE FROM refs")
    
    # Count files
    total_count = conn.execute("""
        SELECT COUNT(*) FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.deleted = 0 AND f.relpath LIKE '%.txt'
        AND fc.content_text IS NOT NULL
    """).fetchone()[0]
    
    logger.info(f"Processing {total_count} files for refs")
    
    chunk_size = 500
    offset = 0
    total_refs = 0
    errors = 0
    
    while offset < total_count:
        write_heartbeat()
        
        rows = conn.execute("""
            SELECT f.file_id, f.relpath, f.content_hash, fc.content_text
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE f.deleted = 0 AND f.relpath LIKE '%.txt'
            AND fc.content_text IS NOT NULL
            ORDER BY f.file_id
            LIMIT ? OFFSET ?
        """, (chunk_size, offset)).fetchall()
        
        if not rows:
            break
        
        for file_id, relpath, content_hash, content in rows:
            if not content or len(content) > 2_000_000:
                continue
            
            try:
                ast = parse_source(content, relpath)
                if ast:
                    ast_dict = ast.to_dict() if hasattr(ast, 'to_dict') else ast
                    refs = list(extract_refs_from_ast(ast_dict, relpath, content_hash))
                    
                    for ref in refs:
                        # ExtractedRef is a dataclass - use attribute access
                        # Schema columns: ref_type, name, using_file_id, line_number, context
                        name = ref.name
                        kind = ref.kind
                        line = ref.line
                        context = ref.context
                        
                        conn.execute("""
                            INSERT OR IGNORE INTO refs
                            (ref_type, name, using_file_id, line_number, context, content_version_id)
                            VALUES (?, ?, ?, ?, ?, (SELECT content_version_id FROM files WHERE file_id = ?))
                        """, (kind, name, file_id, line, context, file_id))
                    
                    total_refs += len(refs)
                
            except Exception as e:
                errors += 1
        
        conn.commit()
        
        offset += len(rows)
        pct = (offset / total_count) * 100
        status.update(
            progress=pct,
            message=f"Refs: {offset}/{total_count} files, {total_refs} refs"
        )
        
        if offset % 2000 == 0:
            logger.info(f"Ref progress: {offset}/{total_count} ({pct:.1f}%), {total_refs} refs")
    
    logger.info(f"Ref extraction complete: {total_refs} refs, {errors} errors")


# =============================================================================
# MOD DISCOVERY AND INGESTION
# =============================================================================

def discover_all_mods(logger: DaemonLogger) -> List[Dict]:
    """
    Discover all mods from Steam Workshop and local mods folders.
    
    Returns list of dicts: {name, path, workshop_id}
    """
    mods = []
    
    # Steam Workshop mods
    workshop_base = Path(r"C:\Program Files (x86)\Steam\steamapps\workshop\content\1158310")
    if workshop_base.exists():
        for mod_dir in workshop_base.iterdir():
            if mod_dir.is_dir():
                workshop_id = mod_dir.name
                # Try to get name from descriptor
                descriptor = mod_dir / "descriptor.mod"
                name = f"Workshop_{workshop_id}"  # Default
                if descriptor.exists():
                    try:
                        content = descriptor.read_text(encoding='utf-8', errors='ignore')
                        for line in content.splitlines():
                            if line.strip().startswith('name='):
                                name = line.split('=', 1)[1].strip().strip('"')
                                break
                    except Exception:
                        pass
                mods.append({
                    "name": name,
                    "path": mod_dir,
                    "workshop_id": workshop_id
                })
    else:
        logger.warning(f"Workshop path not found: {workshop_base}")
    
    # Local mods
    local_mods_base = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
    if local_mods_base.exists():
        for item in local_mods_base.iterdir():
            # Only directories that look like mod folders
            if item.is_dir() and not item.name.endswith('.mod'):
                # Check if it has actual mod content (descriptor or common folder)
                has_descriptor = (item / "descriptor.mod").exists()
                has_common = (item / "common").exists()
                has_events = (item / "events").exists()
                has_localization = (item / "localization").exists()
                
                if has_descriptor or has_common or has_events or has_localization:
                    name = item.name
                    # Try to get name from descriptor
                    descriptor = item / "descriptor.mod"
                    if descriptor.exists():
                        try:
                            content = descriptor.read_text(encoding='utf-8', errors='ignore')
                            for line in content.splitlines():
                                if line.strip().startswith('name='):
                                    name = line.split('=', 1)[1].strip().strip('"')
                                    break
                        except Exception:
                            pass
                    mods.append({
                        "name": name,
                        "path": item,
                        "workshop_id": None  # Local mod
                    })
    else:
        logger.warning(f"Local mods path not found: {local_mods_base}")
    
    logger.info(f"Discovered {len(mods)} mods ({sum(1 for m in mods if m['workshop_id'])} workshop, {sum(1 for m in mods if not m['workshop_id'])} local)")
    return mods


def ingest_all_mods(conn, logger: DaemonLogger, status: StatusWriter):
    """Ingest all discovered mods with progress tracking."""
    from ck3raven.db.ingest import ingest_mod
    
    mods = discover_all_mods(logger)
    
    if not mods:
        logger.warning("No mods found to ingest")
        return
    
    total = len(mods)
    ingested = 0
    skipped = 0
    errors = 0
    total_files = 0
    
    for i, mod in enumerate(mods):
        write_heartbeat()
        
        pct = ((i + 1) / total) * 100
        status.update(
            progress=pct,
            message=f"Mod ingest: {i+1}/{total} - {mod['name'][:30]}"
        )
        
        try:
            mod_package, result = ingest_mod(
                conn=conn,
                mod_path=mod['path'],
                name=mod['name'],
                workshop_id=mod['workshop_id'],
                force=False  # Rely on content hash for dedup
            )
            
            files_added = result.stats.files_new if hasattr(result, 'stats') else 0
            total_files += files_added
            ingested += 1
            
            if i % 20 == 0:
                logger.info(f"Mod {i+1}/{total}: {mod['name']} - {files_added} files")
                conn.commit()  # Commit every 20 mods
            
        except Exception as e:
            errors += 1
            logger.warning(f"Failed to ingest mod {mod['name']}: {e}")
    
    conn.commit()
    logger.info(f"Mod ingest complete: {ingested} mods, {total_files} files, {errors} errors")


# =============================================================================
# AST GENERATION AND STORAGE
# =============================================================================

def get_or_create_parser_version(conn, version_string: str = "1.0.0") -> int:
    """Get or create a parser version record."""
    row = conn.execute(
        "SELECT parser_version_id FROM parsers WHERE version_string = ?",
        (version_string,)
    ).fetchone()
    
    if row:
        return row[0]
    
    cursor = conn.execute(
        "INSERT INTO parsers (version_string, description) VALUES (?, ?)",
        (version_string, "CK3 Parser v1.0")
    )
    conn.commit()
    return cursor.lastrowid


def generate_missing_asts(conn, logger: DaemonLogger, status: StatusWriter, force: bool = False):
    """
    Parse files and store ASTs in the database.
    
    If force=True, clears all ASTs and regenerates.
    Otherwise, only generates ASTs for files missing them.
    """
    from ck3raven.parser import parse_source
    import json
    
    parser_version_id = get_or_create_parser_version(conn)
    
    if force:
        logger.info("Force mode: clearing all ASTs...")
        conn.execute("DELETE FROM asts")
        conn.commit()
    
    # Find files that need AST generation
    # A file needs AST if:
    # 1. Its content_hash doesn't have an AST entry for this parser version
    # 2. It's a .txt file (CK3 script) or .yml file (localization)
    
    # Skip files larger than 5MB - they're usually generated data or massive title files
    # that take too long to parse and aren't useful for symbol extraction
    MAX_FILE_SIZE = 5_000_000
    
    query = """
        SELECT DISTINCT fc.content_hash, fc.content_text, f.relpath
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        LEFT JOIN asts a ON fc.content_hash = a.content_hash 
            AND a.parser_version_id = ?
        WHERE f.deleted = 0
        AND (f.relpath LIKE '%.txt' OR f.relpath LIKE '%.yml')
        AND fc.content_text IS NOT NULL
        AND a.ast_id IS NULL
        AND LENGTH(fc.content_text) < ?
        -- Exclude non-script paths at SQL level for efficiency
        AND f.relpath NOT LIKE 'gfx/%'
        AND f.relpath NOT LIKE 'common/ethnicities/%'
        AND f.relpath NOT LIKE 'common/dna_data/%'
        AND f.relpath NOT LIKE 'common/coat_of_arms/%'
        AND f.relpath NOT LIKE 'history/characters/%'
        AND f.relpath NOT LIKE '%/names/character_names%'
        AND f.relpath NOT LIKE '%_names_l_%'
    """
    
    # First count
    count_query = f"""
        SELECT COUNT(DISTINCT fc.content_hash)
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        LEFT JOIN asts a ON fc.content_hash = a.content_hash 
            AND a.parser_version_id = ?
        WHERE f.deleted = 0
        AND (f.relpath LIKE '%.txt' OR f.relpath LIKE '%.yml')
        AND LENGTH(fc.content_text) < ?
        AND fc.content_text IS NOT NULL
        AND a.ast_id IS NULL
    """
    
    total_count = conn.execute(count_query, (parser_version_id, MAX_FILE_SIZE)).fetchone()[0]
    
    if total_count == 0:
        logger.info("All files already have ASTs - nothing to do")
        return
    
    logger.info(f"Generating ASTs for {total_count} unique content hashes...")
    
    # Process in chunks
    chunk_size = 500
    processed = 0
    errors = 0
    
    # We need to process all results, so fetch in chunks via OFFSET
    offset = 0
    
    while True:
        write_heartbeat()
        
        rows = conn.execute(
            query + " LIMIT ? OFFSET ?",
            (parser_version_id, MAX_FILE_SIZE, chunk_size, offset)
        ).fetchall()
        
        if not rows:
            break
        
        for idx, (content_hash, content, relpath) in enumerate(rows):
            # Write heartbeat every 50 files to prevent stale detection
            if idx % 50 == 0:
                write_heartbeat()
            
            if not content or len(content) > 2_000_000:
                continue
            
            # Skip non-script files (graphics data, generated content, etc.)
            # Only common/, events/, history/, localization/, gui/ are CK3 script folders
            skip_patterns = [
                # Graphics and assets - NOT scripts
                'gfx/',           # ALL graphics - tree transforms, cameras, meshes
                '/fonts/', '/licenses/', '/sounds/', '/music/',
                
                # Generated/backup content
                '#backup/', '/generated/',
                'guids.txt', 'credits.txt', 'readme', 'changelog',
                'checksum', '.dds', '.png', '.tga',
                
                # Portrait/DNA data - huge files with no useful symbols
                'common/ethnicities/',   # 3000+ portrait ethnicity files
                'common/dna_data/',      # DNA appearance data
                'common/coat_of_arms/',  # Procedural coat of arms
                'history/characters/',   # Massive character history files
                
                # Name databases - localization but no symbols
                'moreculturalnames', 'cultural_names_l_',
                '/names/character_names',  # Character name databases
                '_names_l_',  # Name localization files
            ]
            if any(skip in relpath.lower() for skip in skip_patterns):
                continue
            
            try:
                # Use timeout for parsing (some files can hang the parser)
                import signal
                import threading
                
                parse_result = [None]
                parse_error = [None]
                
                def parse_with_timeout():
                    try:
                        parse_result[0] = parse_source(content, relpath)
                    except Exception as e:
                        parse_error[0] = e
                
                parse_thread = threading.Thread(target=parse_with_timeout)
                parse_thread.daemon = True
                parse_thread.start()
                parse_thread.join(timeout=30)  # 30 second timeout per file
                
                if parse_thread.is_alive():
                    # Timeout - skip this file
                    errors += 1
                    if errors <= 30:
                        logger.warning(f"Parse timeout (30s) for {relpath}")
                    continue
                
                if parse_error[0]:
                    raise parse_error[0]
                
                ast = parse_result[0]
                
                if ast:
                    # Convert to dict/JSON
                    ast_dict = ast.to_dict() if hasattr(ast, 'to_dict') else ast
                    ast_json = json.dumps(ast_dict, separators=(',', ':'))
                    
                    # Count nodes (rough estimate from keys)
                    node_count = ast_json.count('{')
                    
                    conn.execute("""
                        INSERT OR REPLACE INTO asts
                        (content_hash, parser_version_id, ast_blob, ast_format, parse_ok, node_count)
                        VALUES (?, ?, ?, 'json', 1, ?)
                    """, (content_hash, parser_version_id, ast_json.encode('utf-8'), node_count))
                else:
                    # Parse returned None - store as failed
                    conn.execute("""
                        INSERT OR REPLACE INTO asts
                        (content_hash, parser_version_id, ast_blob, ast_format, parse_ok, diagnostics_json)
                        VALUES (?, ?, ?, 'json', 0, ?)
                    """, (content_hash, parser_version_id, b'null', json.dumps({"error": "Parse returned None"})))
                
                processed += 1
                
            except Exception as e:
                errors += 1
                # Store the error
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO asts
                        (content_hash, parser_version_id, ast_blob, ast_format, parse_ok, diagnostics_json)
                        VALUES (?, ?, ?, 'json', 0, ?)
                    """, (content_hash, parser_version_id, b'null', json.dumps({"error": str(e)[:500]})))
                except Exception:
                    pass
                
                if errors <= 20:
                    logger.warning(f"Parse error in {relpath}: {e}")
        
        conn.commit()
        offset += len(rows)
        
        pct = min(100, (offset / total_count) * 100)
        status.update(
            progress=pct,
            message=f"AST generation: {offset}/{total_count} ({pct:.1f}%)"
        )
        
        if offset % 2000 == 0:
            logger.info(f"AST progress: {offset}/{total_count} ({pct:.1f}%), {errors} errors")
    
    logger.info(f"AST generation complete: {processed} ASTs, {errors} errors")


# =============================================================================
# SYMBOL/REF EXTRACTION FROM STORED ASTs
# =============================================================================

def extract_symbols_from_stored_asts(conn, logger: DaemonLogger, status: StatusWriter):
    """Extract symbols from stored ASTs (not re-parsing)."""
    from ck3raven.db.symbols import extract_symbols_from_ast
    import json
    
    logger.info("Starting symbol extraction from stored ASTs...")
    
    # Clear old symbols
    conn.execute("DELETE FROM symbols")
    conn.commit()
    
    # Query files that have ASTs
    total_count = conn.execute("""
        SELECT COUNT(*) FROM files f
        JOIN asts a ON f.content_hash = a.content_hash
        WHERE f.deleted = 0 AND a.parse_ok = 1
        AND f.relpath LIKE '%.txt'
    """).fetchone()[0]
    
    logger.info(f"Processing {total_count} files for symbols")
    
    chunk_size = 500
    offset = 0
    total_symbols = 0
    errors = 0
    
    while offset < total_count:
        write_heartbeat()
        
        rows = conn.execute("""
            SELECT f.file_id, f.relpath, f.content_hash, a.ast_blob
            FROM files f
            JOIN asts a ON f.content_hash = a.content_hash
            WHERE f.deleted = 0 AND a.parse_ok = 1
            AND f.relpath LIKE '%.txt'
            ORDER BY f.file_id
            LIMIT ? OFFSET ?
        """, (chunk_size, offset)).fetchall()
        
        if not rows:
            break
        
        for file_id, relpath, content_hash, ast_blob in rows:
            try:
                # Decode AST from blob
                ast_dict = json.loads(ast_blob.decode('utf-8'))
                
                symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
                
                for sym in symbols:
                    name = sym.name
                    kind = sym.kind
                    line = sym.line
                    scope = getattr(sym, 'scope', None)
                    
                    conn.execute("""
                        INSERT OR IGNORE INTO symbols
                        (symbol_type, name, scope, defining_file_id, line_number, content_version_id)
                        VALUES (?, ?, ?, ?, ?, (SELECT content_version_id FROM files WHERE file_id = ?))
                    """, (kind, name, scope, file_id, line, file_id))
                
                total_symbols += len(symbols)
                
            except Exception as e:
                errors += 1
                if errors <= 10:
                    logger.warning(f"Symbol extraction error in {relpath}: {e}")
        
        conn.commit()
        offset += len(rows)
        
        pct = (offset / total_count) * 100
        status.update(
            progress=pct,
            message=f"Symbols: {offset}/{total_count} files, {total_symbols} symbols"
        )
        
        if offset % 2000 == 0:
            logger.info(f"Symbol progress: {offset}/{total_count} ({pct:.1f}%), {total_symbols} symbols")
    
    logger.info(f"Symbol extraction complete: {total_symbols} symbols, {errors} errors")


def extract_refs_from_stored_asts(conn, logger: DaemonLogger, status: StatusWriter):
    """Extract references from stored ASTs (not re-parsing)."""
    from ck3raven.db.symbols import extract_refs_from_ast
    import json
    
    logger.info("Starting reference extraction from stored ASTs...")
    
    # Clear old refs
    conn.execute("DELETE FROM refs")
    conn.commit()
    
    # Query files that have ASTs
    total_count = conn.execute("""
        SELECT COUNT(*) FROM files f
        JOIN asts a ON f.content_hash = a.content_hash
        WHERE f.deleted = 0 AND a.parse_ok = 1
        AND f.relpath LIKE '%.txt'
    """).fetchone()[0]
    
    logger.info(f"Processing {total_count} files for refs")
    
    chunk_size = 500
    offset = 0
    total_refs = 0
    errors = 0
    
    while offset < total_count:
        write_heartbeat()
        
        rows = conn.execute("""
            SELECT f.file_id, f.relpath, f.content_hash, a.ast_blob
            FROM files f
            JOIN asts a ON f.content_hash = a.content_hash
            WHERE f.deleted = 0 AND a.parse_ok = 1
            AND f.relpath LIKE '%.txt'
            ORDER BY f.file_id
            LIMIT ? OFFSET ?
        """, (chunk_size, offset)).fetchall()
        
        if not rows:
            break
        
        for file_id, relpath, content_hash, ast_blob in rows:
            try:
                # Decode AST from blob
                ast_dict = json.loads(ast_blob.decode('utf-8'))
                
                refs = list(extract_refs_from_ast(ast_dict, relpath, content_hash))
                
                for ref in refs:
                    name = ref.name
                    kind = ref.kind
                    line = ref.line
                    context = ref.context
                    
                    conn.execute("""
                        INSERT OR IGNORE INTO refs
                        (ref_type, name, using_file_id, line_number, context, content_version_id)
                        VALUES (?, ?, ?, ?, ?, (SELECT content_version_id FROM files WHERE file_id = ?))
                    """, (kind, name, file_id, line, context, file_id))
                
                total_refs += len(refs)
                
            except Exception as e:
                errors += 1
        
        conn.commit()
        offset += len(rows)
        
        pct = (offset / total_count) * 100
        status.update(
            progress=pct,
            message=f"Refs: {offset}/{total_count} files, {total_refs} refs"
        )
        
        if offset % 2000 == 0:
            logger.info(f"Ref progress: {offset}/{total_count} ({pct:.1f}%), {total_refs} refs")
    
    logger.info(f"Ref extraction complete: {total_refs} refs, {errors} errors")


def start_detached(db_path: Path, force: bool, symbols_only: bool = False):
    """Launch the rebuild as a completely detached process."""
    
    # Create the command to run ourselves in daemon mode
    script_path = Path(__file__).resolve()
    
    # Use pythonw.exe on Windows to avoid any console
    python_exe = sys.executable
    pythonw = Path(python_exe).parent / "pythonw.exe"
    if pythonw.exists():
        python_exe = str(pythonw)
    
    args = [
        python_exe,
        str(script_path),
        "_run_daemon",
        "--db", str(db_path),
    ]
    if force:
        args.append("--force")
    if symbols_only:
        args.append("--symbols-only")
    
    # Launch completely detached
    # DETACHED_PROCESS = 0x00000008
    # CREATE_NEW_PROCESS_GROUP = 0x00000200
    # CREATE_NO_WINDOW = 0x08000000
    creationflags = 0x00000008 | 0x00000200 | 0x08000000
    
    # Clear old status
    if STATUS_FILE.exists():
        STATUS_FILE.unlink()
    if LOG_FILE.exists():
        # Rotate old log
        old_log = LOG_FILE.with_suffix(".log.old")
        LOG_FILE.replace(old_log)
    
    subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=True
    )
    
    print(f"Rebuild daemon started. Monitor with: python {script_path.name} status")
    print(f"Logs: {LOG_FILE}")


def show_status():
    """Show current daemon status."""
    
    running = is_daemon_running()
    
    print(f"Daemon running: {running}")
    
    if PID_FILE.exists():
        print(f"PID: {PID_FILE.read_text().strip()}")
    
    if HEARTBEAT_FILE.exists():
        try:
            last = float(HEARTBEAT_FILE.read_text().strip())
            age = time.time() - last
            print(f"Last heartbeat: {age:.1f}s ago")
        except Exception:
            pass
    
    if STATUS_FILE.exists():
        try:
            status = json.loads(STATUS_FILE.read_text())
            print(f"\nStatus:")
            print(f"  State: {status.get('state', 'unknown')}")
            print(f"  Phase: {status.get('phase', 'unknown')} ({status.get('phase_number', 0)}/{status.get('total_phases', 7)})")
            print(f"  Progress: {status.get('progress', 0):.1f}%")
            print(f"  Message: {status.get('message', '')}")
            if status.get('error'):
                print(f"  Error: {status.get('error')}")
            print(f"  Started: {status.get('started_at', 'unknown')}")
            print(f"  Updated: {status.get('updated_at', 'unknown')}")
        except Exception as e:
            print(f"Error reading status: {e}")
    else:
        print("No status file found")


def show_logs(follow: bool = False):
    """Show daemon logs."""
    if not LOG_FILE.exists():
        print("No log file found")
        return
    
    if follow:
        # Tail -f equivalent
        print(f"Following {LOG_FILE} (Ctrl+C to stop)...")
        with open(LOG_FILE, "r") as f:
            # Go to end
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    print(line, end="")
                else:
                    time.sleep(0.5)
    else:
        # Just print last 50 lines
        lines = LOG_FILE.read_text().splitlines()
        for line in lines[-50:]:
            print(line)


def stop_daemon():
    """Stop the running daemon."""
    if not is_daemon_running():
        print("Daemon is not running")
        return
    
    try:
        pid = int(PID_FILE.read_text().strip())
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_TERMINATE = 0x0001
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if handle:
            kernel32.TerminateProcess(handle, 1)
            kernel32.CloseHandle(handle)
            print(f"Daemon (PID {pid}) terminated")
        cleanup_pid()
    except Exception as e:
        print(f"Error stopping daemon: {e}")


def main():
    parser = argparse.ArgumentParser(description="CK3Raven rebuild daemon")
    parser.add_argument("command", choices=["start", "status", "stop", "logs", "_run_daemon"],
                        help="Command to execute")
    parser.add_argument("--force", action="store_true", help="Force complete rebuild")
    parser.add_argument("--symbols-only", action="store_true", help="Only run symbol/ref extraction (skip ingest)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Database path")
    parser.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    
    args = parser.parse_args()
    
    if args.command == "start":
        if is_daemon_running():
            print("Daemon is already running. Use 'stop' first.")
            sys.exit(1)
        start_detached(args.db, args.force, args.symbols_only)
    
    elif args.command == "status":
        show_status()
    
    elif args.command == "stop":
        stop_daemon()
    
    elif args.command == "logs":
        show_logs(args.follow)
    
    elif args.command == "_run_daemon":
        # Internal: actually run the daemon
        write_pid()
        logger = DaemonLogger(LOG_FILE)
        status = StatusWriter(STATUS_FILE)
        
        try:
            run_rebuild(args.db, args.force, logger, status, args.symbols_only)
        except Exception as e:
            logger.error(f"Daemon crashed: {e}")
            logger.error(traceback.format_exc())
        finally:
            cleanup_pid()


if __name__ == "__main__":
    main()
