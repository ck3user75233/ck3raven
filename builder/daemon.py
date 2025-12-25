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
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

# Paths
DEFAULT_DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"
DAEMON_DIR = Path.home() / ".ck3raven" / "daemon"
PID_FILE = DAEMON_DIR / "rebuild.pid"
LOCK_FILE = DAEMON_DIR / "rebuild.lock"
STATUS_FILE = DAEMON_DIR / "rebuild_status.json"
LOG_FILE = DAEMON_DIR / "rebuild.log"
HEARTBEAT_FILE = DAEMON_DIR / "heartbeat"
DEBUG_OUTPUT_FILE = DAEMON_DIR / "debug_output.json"

# Ensure daemon directory exists
DAEMON_DIR.mkdir(parents=True, exist_ok=True)


class DaemonLogger:
    """File-based logger that doesn't use stdout/stderr."""
    
    def __init__(self, log_path: Path, also_print: bool = False):
        self.log_path = log_path
        self.also_print = also_print
        self._ensure_file()
    
    def _ensure_file(self):
        if not self.log_path.exists():
            self.log_path.write_text("")
    
    def log(self, level: str, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}\n"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line)
        if self.also_print:
            print(line.rstrip())
    
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


# =============================================================================
# BUILD TRACKING
# =============================================================================

BUILDER_VERSION = "1.0.0"
MANIFEST_FILE = DAEMON_DIR / "build_manifest.json"


@dataclass
class StepStats:
    """Statistics for a single build step."""
    rows_in: int = 0
    rows_out: int = 0
    rows_skipped: int = 0
    rows_errored: int = 0


class BuildTracker:
    """
    Tracks build progress and records to builder_runs/builder_steps tables.
    
    Ensures every build is recorded and produces a manifest on completion.
    """
    
    def __init__(self, conn: sqlite3.Connection, logger: DaemonLogger, 
                 vanilla_path: Optional[str] = None, playset_id: Optional[int] = None,
                 force: bool = False):
        self.conn = conn
        self.logger = logger
        self.build_id = str(uuid.uuid4())
        self.vanilla_path = vanilla_path
        self.playset_id = playset_id
        self.force = force
        self.started_at = datetime.now().isoformat()
        self._current_step: Optional[str] = None
        self._current_step_start: Optional[float] = None
        self._step_number = 0
        self._steps: Dict[str, dict] = {}
        
        # Try to get git commit
        self.git_commit = self._get_git_commit()
        
        # Record the build start
        self._init_build()
    
    def _get_git_commit(self) -> Optional[str]:
        """Get current git commit hash if in a git repo."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=Path(__file__).parent.parent
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None
    
    def _init_build(self):
        """Record build start in database."""
        from ck3raven.db.schema import DATABASE_VERSION
        
        try:
            self.conn.execute("""
                INSERT INTO builder_runs 
                (build_id, builder_version, git_commit, schema_version, started_at, 
                 vanilla_path, playset_id, force_rebuild)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self.build_id, BUILDER_VERSION, self.git_commit, DATABASE_VERSION,
                self.started_at, self.vanilla_path, self.playset_id, int(self.force)
            ))
            self.conn.commit()
            self.logger.info(f"Build started: {self.build_id}")
        except Exception as e:
            self.logger.warning(f"Failed to record build start: {e}")
    
    def acquire_lock(self) -> bool:
        """Try to acquire build lock. Returns True if acquired."""
        try:
            # Check for existing lock
            existing = self.conn.execute(
                "SELECT build_id, heartbeat_at, pid FROM build_lock WHERE lock_id = 1"
            ).fetchone()
            
            if existing:
                # Check if lock is stale (>2 minutes old)
                last_heartbeat = datetime.fromisoformat(existing['heartbeat_at'])
                age = (datetime.now() - last_heartbeat).total_seconds()
                if age < 120:
                    self.logger.error(f"Build lock held by {existing['build_id']} (pid {existing['pid']})")
                    return False
                # Stale lock - take it over
                self.logger.warning(f"Taking over stale lock from {existing['build_id']}")
            
            # Acquire or update lock
            self.conn.execute("""
                INSERT OR REPLACE INTO build_lock (lock_id, build_id, acquired_at, heartbeat_at, pid)
                VALUES (1, ?, ?, ?, ?)
            """, (self.build_id, datetime.now().isoformat(), datetime.now().isoformat(), os.getpid()))
            self.conn.commit()
            self.logger.info("Build lock acquired")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to acquire build lock: {e}")
            return False
    
    def release_lock(self):
        """Release build lock."""
        try:
            self.conn.execute("DELETE FROM build_lock WHERE build_id = ?", (self.build_id,))
            self.conn.commit()
            self.logger.info("Build lock released")
        except Exception as e:
            self.logger.warning(f"Failed to release build lock: {e}")
    
    def update_lock_heartbeat(self):
        """Update lock heartbeat to prevent takeover."""
        try:
            self.conn.execute(
                "UPDATE build_lock SET heartbeat_at = ? WHERE build_id = ?",
                (datetime.now().isoformat(), self.build_id)
            )
        except Exception:
            pass
    
    def start_step(self, step_name: str, step_version: str = "1.0"):
        """Start tracking a build step."""
        self._step_number += 1
        self._current_step = step_name
        self._current_step_start = time.time()
        
        try:
            self.conn.execute("""
                INSERT INTO builder_steps
                (build_id, step_name, step_version, step_number, started_at, state)
                VALUES (?, ?, ?, ?, ?, 'running')
            """, (self.build_id, step_name, step_version, self._step_number, 
                  datetime.now().isoformat()))
            self.conn.commit()
        except Exception as e:
            self.logger.warning(f"Failed to record step start: {e}")
    
    def end_step(self, step_name: str, stats: StepStats, success: bool = True, error: str = None):
        """Complete tracking a build step."""
        duration = time.time() - self._current_step_start if self._current_step_start else 0
        state = 'complete' if success else 'failed'
        
        self._steps[step_name] = {
            'duration_sec': duration,
            'state': state,
            'rows_in': stats.rows_in,
            'rows_out': stats.rows_out,
            'rows_skipped': stats.rows_skipped,
            'rows_errored': stats.rows_errored,
            'error': error
        }
        
        try:
            self.conn.execute("""
                UPDATE builder_steps
                SET completed_at = ?, duration_sec = ?, state = ?, error_message = ?,
                    rows_in = ?, rows_out = ?, rows_skipped = ?, rows_errored = ?
                WHERE build_id = ? AND step_name = ?
            """, (
                datetime.now().isoformat(), duration, state, error,
                stats.rows_in, stats.rows_out, stats.rows_skipped, stats.rows_errored,
                self.build_id, step_name
            ))
            self.conn.commit()
        except Exception as e:
            self.logger.warning(f"Failed to record step end: {e}")
        
        self._current_step = None
        self._current_step_start = None
    
    def skip_step(self, step_name: str, reason: str = "skipped"):
        """Mark a step as skipped."""
        self._step_number += 1
        try:
            self.conn.execute("""
                INSERT INTO builder_steps
                (build_id, step_name, step_number, started_at, completed_at, 
                 duration_sec, state, error_message)
                VALUES (?, ?, ?, ?, ?, 0, 'skipped', ?)
            """, (self.build_id, step_name, self._step_number, 
                  datetime.now().isoformat(), datetime.now().isoformat(), reason))
            self.conn.commit()
        except Exception as e:
            self.logger.warning(f"Failed to record step skip: {e}")
    
    def complete(self, counts: Dict[str, int]):
        """Mark build as complete and generate manifest."""
        try:
            self.conn.execute("""
                UPDATE builder_runs
                SET completed_at = ?, state = 'complete',
                    files_ingested = ?, asts_produced = ?, symbols_extracted = ?,
                    refs_extracted = ?, localization_rows = ?, lookup_rows = ?
                WHERE build_id = ?
            """, (
                datetime.now().isoformat(),
                counts.get('files', 0), counts.get('asts', 0), counts.get('symbols', 0),
                counts.get('refs', 0), counts.get('localization', 0), counts.get('lookups', 0),
                self.build_id
            ))
            self.conn.commit()
            self.logger.info(f"Build completed: {self.build_id}")
        except Exception as e:
            self.logger.warning(f"Failed to record build completion: {e}")
        
        # Generate manifest
        self._write_manifest(counts)
        self.release_lock()
    
    def fail(self, error: str):
        """Mark build as failed."""
        try:
            self.conn.execute("""
                UPDATE builder_runs
                SET completed_at = ?, state = 'failed', error_message = ?
                WHERE build_id = ?
            """, (datetime.now().isoformat(), error, self.build_id))
            self.conn.commit()
            self.logger.error(f"Build failed: {self.build_id} - {error}")
        except Exception as e:
            self.logger.warning(f"Failed to record build failure: {e}")
        
        self.release_lock()
    
    def _write_manifest(self, counts: Dict[str, int]):
        """Write build_manifest.json."""
        from ck3raven.db.schema import DATABASE_VERSION
        
        manifest = {
            "build_id": self.build_id,
            "builder_version": BUILDER_VERSION,
            "git_commit": self.git_commit,
            "schema_version": DATABASE_VERSION,
            "started_at": self.started_at,
            "completed_at": datetime.now().isoformat(),
            "inputs": {
                "vanilla_path": self.vanilla_path,
                "playset_id": self.playset_id,
                "force_rebuild": self.force
            },
            "counts": counts,
            "steps": [
                {
                    "name": name,
                    "duration_sec": info['duration_sec'],
                    "state": info['state'],
                    "rows_in": info['rows_in'],
                    "rows_out": info['rows_out'],
                    "rows_skipped": info['rows_skipped'],
                    "rows_errored": info['rows_errored']
                }
                for name, info in self._steps.items()
            ],
            "total_duration_sec": sum(s['duration_sec'] for s in self._steps.values())
        }
        
        try:
            MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))
            self.logger.info(f"Manifest written: {MANIFEST_FILE}")
        except Exception as e:
            self.logger.warning(f"Failed to write manifest: {e}")


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


def acquire_exclusive_lock() -> bool:
    """
    Acquire exclusive lock to prevent multiple daemon instances.
    
    Uses a lockfile with exclusive access. This is more robust than just
    PID checking because:
    1. The lock is held by the OS, not just a file we created
    2. If the process crashes, the OS releases the lock automatically
    3. Prevents race conditions between checking and starting
    
    Returns:
        True if lock acquired, False if another instance is running
    """
    import msvcrt
    
    try:
        # Open lockfile for exclusive access
        lock_fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR)
        
        try:
            # Try to acquire exclusive lock (non-blocking)
            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
            
            # Write our PID to the lock file
            os.write(lock_fd, str(os.getpid()).encode())
            os.fsync(lock_fd)
            
            # Keep the file descriptor open (held until process exits)
            # Store in module global so it doesn't get garbage collected
            global _lock_fd
            _lock_fd = lock_fd
            return True
            
        except (IOError, OSError):
            # Lock is held by another process
            os.close(lock_fd)
            return False
            
    except Exception as e:
        print(f"Lock acquisition error: {e}")
        return False


def release_exclusive_lock():
    """Release the exclusive lock if we hold it."""
    global _lock_fd
    try:
        if '_lock_fd' in globals() and _lock_fd is not None:
            import msvcrt
            try:
                msvcrt.locking(_lock_fd, msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            os.close(_lock_fd)
            _lock_fd = None
    except Exception:
        pass


# Module global for lock file descriptor
_lock_fd = None


def write_pid():
    """Write current process PID."""
    PID_FILE.write_text(str(os.getpid()))


def cleanup_pid():
    """Remove PID file and release lock."""
    try:
        PID_FILE.unlink(missing_ok=True)
        release_exclusive_lock()
    except Exception:
        pass


def run_rebuild(db_path: Path, force: bool, logger: DaemonLogger, status: StatusWriter, symbols_only: bool = False, vanilla_path: str = None, skip_mods: bool = False, playset_file: Path = None):
    """Main rebuild logic - runs in the detached process."""
    
    status.update(state="starting", started_at=datetime.now().isoformat())
    write_heartbeat()
    
    # Add the ck3raven package to path
    src_path = Path(__file__).parent.parent / "src"
    if src_path.exists():
        sys.path.insert(0, str(src_path))
    
    # Add the ck3raven project root to path (for builder package)
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    
    build_tracker = None
    
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
        
        # Initialize build tracking
        build_tracker = BuildTracker(
            conn, logger, 
            vanilla_path=str(vanilla_path) if vanilla_path else None,
            playset_id=None,
            force=force
        )
        
        # Acquire build lock
        if not build_tracker.acquire_lock():
            raise RuntimeError("Failed to acquire build lock - another build may be in progress")
        
        if force and not symbols_only:
            status.update(state="clearing", message="Clearing existing data...")
            write_heartbeat()
            logger.info("Force mode: clearing tables...")
            
            for table in ["symbols", "refs", "files", "file_contents", "content_versions", 
                          "builder_steps", "trait_lookups", "event_lookups", "decision_lookups"]:
                try:
                    conn.execute(f"DELETE FROM {table}")
                    logger.debug(f"Cleared table: {table}")
                except Exception as e:
                    logger.debug(f"Table {table} clear skipped: {e}")
            
            logger.info("Tables cleared")
        
        # Aggregate counts for final manifest
        build_counts = {
            'files': 0, 'asts': 0, 'symbols': 0, 
            'refs': 0, 'localization': 0, 'lookups': 0
        }
        
        if not symbols_only:
            # Phase 1: Vanilla ingest
            build_tracker.start_step("vanilla_ingest")
            status.update(
                state="running",
                phase="vanilla_ingest",
                phase_number=1,
                message="Ingesting vanilla CK3 files..."
            )
            write_heartbeat()
            build_tracker.update_lock_heartbeat()
            
            if vanilla_path:
                vanilla_path = Path(vanilla_path).resolve()
            else:
                # Use config for default path
                from builder.config import get_config
                config = get_config()
                vanilla_path = config.vanilla_path
            if not vanilla_path.exists():
                raise RuntimeError(f"Vanilla path not found: {vanilla_path}")
            
            logger.info(f"Ingesting vanilla from {vanilla_path}")
            
            # Use chunked ingest with progress reporting
            version, result = ingest_vanilla_chunked(conn, vanilla_path, "1.18.x", logger, status)
            
            vanilla_files = result.stats.files_scanned if hasattr(result, 'stats') else 0
            build_counts['files'] += vanilla_files
            
            logger.info(f"Vanilla ingest complete: {result}")
            status.update(stats={"vanilla_files": vanilla_files})
            build_tracker.end_step("vanilla_ingest", StepStats(rows_out=vanilla_files))
            
            # Checkpoint after vanilla
            db_wrapper.checkpoint()
            write_heartbeat()
            
            # Phase 2: Mod ingest - playset mods only if playset_file provided, else ALL mods
            if not skip_mods:
                build_tracker.start_step("mod_ingest")
                if playset_file:
                    status.update(
                        phase="mod_ingest",
                        phase_number=2,
                        message="Ingesting playset mod files..."
                    )
                else:
                    status.update(
                        phase="mod_ingest",
                        phase_number=2,
                        message="Ingesting all mod files..."
                    )
                write_heartbeat()
                build_tracker.update_lock_heartbeat()

                mod_files = ingest_all_mods(conn, logger, status, playset_file=playset_file)
                build_counts['files'] += mod_files if isinstance(mod_files, int) else 0
                build_tracker.end_step("mod_ingest", StepStats(rows_out=mod_files if isinstance(mod_files, int) else 0))
                db_wrapper.checkpoint()
            else:
                build_tracker.skip_step("mod_ingest", "test mode with skip_mods=True")
                logger.info("Skipping mod ingestion (test mode with skip_mods=True)")
        else:
            # symbols_only mode - skip ingest phases, go straight to symbols/refs
            build_tracker.skip_step("vanilla_ingest", "symbols_only mode")
            build_tracker.skip_step("mod_ingest", "symbols_only mode")
            logger.info("Symbols-only mode: skipping ingest, extracting symbols incrementally...")
        
        # Phase 3: AST generation - parse files and store ASTs
        build_tracker.start_step("ast_generation")
        status.update(
            phase="ast_generation",
            phase_number=3,
            message="Generating ASTs..."
        )
        write_heartbeat()
        build_tracker.update_lock_heartbeat()
        
        ast_stats = generate_missing_asts(conn, logger, status, force=force)
        ast_count = ast_stats.get('generated', 0) if isinstance(ast_stats, dict) else 0
        build_counts['asts'] = ast_count
        build_tracker.end_step("ast_generation", StepStats(
            rows_out=ast_count,
            rows_skipped=ast_stats.get('skipped', 0) if isinstance(ast_stats, dict) else 0,
            rows_errored=ast_stats.get('errors', 0) if isinstance(ast_stats, dict) else 0
        ))
        db_wrapper.checkpoint()
        
        # Phase 4: Symbol extraction from stored ASTs
        build_tracker.start_step("symbol_extraction")
        status.update(
            phase="symbol_extraction", 
            phase_number=4,
            message="Extracting symbols..."
        )
        write_heartbeat()
        build_tracker.update_lock_heartbeat()
        
        symbol_stats = extract_symbols_from_stored_asts(conn, logger, status)
        symbol_count = symbol_stats.get('extracted', 0) if isinstance(symbol_stats, dict) else 0
        build_counts['symbols'] = symbol_count
        build_tracker.end_step("symbol_extraction", StepStats(rows_out=symbol_count))
        db_wrapper.checkpoint()
        
        # Phase 5: Ref extraction from stored ASTs
        build_tracker.start_step("ref_extraction")
        status.update(
            phase="ref_extraction",
            phase_number=5, 
            message="Extracting references..."
        )
        write_heartbeat()
        build_tracker.update_lock_heartbeat()
        
        ref_stats = extract_refs_from_stored_asts(conn, logger, status)
        ref_count = ref_stats.get('extracted', 0) if isinstance(ref_stats, dict) else 0
        build_counts['refs'] = ref_count
        build_tracker.end_step("ref_extraction", StepStats(rows_out=ref_count))
        db_wrapper.checkpoint()
        
        # Phase 6: Localization parsing
        build_tracker.start_step("localization_parsing")
        status.update(
            phase="localization_parsing",
            phase_number=6,
            message="Parsing localization files..."
        )
        write_heartbeat()
        build_tracker.update_lock_heartbeat()
        
        loc_stats = parse_localization_files(conn, logger, status, force=force)
        loc_count = loc_stats.get('entries', 0) if isinstance(loc_stats, dict) else 0
        build_counts['localization'] = loc_count
        build_tracker.end_step("localization_parsing", StepStats(rows_out=loc_count))
        db_wrapper.checkpoint()
        
        # Phase 7: Lookup table extraction (TBC - provisional)
        build_tracker.start_step("lookup_extraction")
        status.update(
            phase="lookup_extraction",
            phase_number=7,
            message="Extracting lookup tables..."
        )
        write_heartbeat()
        build_tracker.update_lock_heartbeat()
        
        lookup_stats = extract_lookup_tables(conn, logger, status)
        lookup_count = lookup_stats.get('total', 0) if isinstance(lookup_stats, dict) else 0
        build_counts['lookups'] = lookup_count
        build_tracker.end_step("lookup_extraction", StepStats(rows_out=lookup_count))
        db_wrapper.checkpoint()
        
        # Done - record build completion
        build_tracker.complete(build_counts)
        
        status.update(
            state="complete",
            phase="done",
            phase_number=8,
            progress=100.0,
            message="Rebuild complete!"
        )
        
        db_wrapper.close()
        logger.info("Rebuild completed successfully!")
        
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(f"Rebuild failed: {error_msg}")
        logger.error(traceback.format_exc())
        
        # Record build failure
        if build_tracker:
            build_tracker.fail(error_msg)
        
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


# =============================================================================
# MOD DISCOVERY AND INGESTION
# =============================================================================

def discover_playset_mods(playset_file: Path, logger: DaemonLogger) -> List[Dict]:
    """
    Load mod list from an active_mod_paths.json file (exported from launcher).
    
    Returns list of dicts in same format as discover_all_mods(): {name, path, workshop_id}
    Respects load_order from the file.
    """
    import json
    
    if not playset_file.exists():
        logger.error(f"Playset file not found: {playset_file}")
        return []
    
    try:
        data = json.loads(playset_file.read_text(encoding='utf-8'))
    except Exception as e:
        logger.error(f"Failed to parse playset file: {e}")
        return []
    
    playset_name = data.get('playset_name', 'Unknown')
    paths = data.get('paths', [])
    
    mods = []
    for entry in paths:
        if not entry.get('enabled', True):
            continue  # Skip disabled mods
        
        mod_path = Path(entry.get('path', ''))
        if not mod_path.exists():
            logger.warning(f"Mod path not found: {mod_path}")
            continue
        
        mods.append({
            "name": entry.get('name', mod_path.name),
            "path": mod_path,
            "workshop_id": entry.get('steam_id') or None,  # Empty string -> None
            "load_order": entry.get('load_order', 999)
        })
    
    # Sort by load order
    mods.sort(key=lambda m: m.get('load_order', 999))
    
    workshop_count = sum(1 for m in mods if m['workshop_id'])
    local_count = len(mods) - workshop_count
    logger.info(f"Loaded playset '{playset_name}' with {len(mods)} mods ({workshop_count} workshop, {local_count} local)")
    
    return mods


def discover_all_mods(logger: DaemonLogger) -> List[Dict]:
    """
    Discover all mods from Steam Workshop and local mods folders.
    
    Returns list of dicts: {name, path, workshop_id}
    """
    from builder.config import get_config
    config = get_config()
    
    mods = []
    
    # Steam Workshop mods
    workshop_base = config.workshop_path
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
    local_mods_base = config.local_mods_path
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


def ingest_all_mods(conn, logger: DaemonLogger, status: StatusWriter, playset_file: Path = None):
    """Ingest mods with progress tracking.
    
    If playset_file is provided, only ingest mods from that playset.
    Otherwise, discover and ingest all mods.
    """
    from ck3raven.db.ingest import ingest_mod
    
    if playset_file:
        mods = discover_playset_mods(playset_file, logger)
    else:
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
        AND f.relpath LIKE '%.txt'
        AND f.relpath NOT LIKE 'localization/%'
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
        AND f.relpath LIKE '%.txt'
        AND f.relpath NOT LIKE 'localization/%'
        AND LENGTH(fc.content_text) < ?
        AND fc.content_text IS NOT NULL
        AND a.ast_id IS NULL
    """
    
    total_count = conn.execute(count_query, (parser_version_id, MAX_FILE_SIZE)).fetchone()[0]
    
    if total_count == 0:
        logger.info("All files already have ASTs - nothing to do")
        return {'generated': 0, 'skipped': 0, 'errors': 0}
    
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
    return {'generated': processed, 'skipped': total_count - processed - errors, 'errors': errors}


# =============================================================================
# LOCALIZATION PARSING
# =============================================================================

def parse_localization_files(conn, logger: DaemonLogger, status: StatusWriter, force: bool = False):
    """
    Parse localization files and store entries in localization_entries table.
    
    This handles .yml files in localization/ folders using the Paradox localization parser.
    Unlike AST generation, localization uses a different format (pseudo-YAML).
    
    If force=True, clears all localization entries and re-parses.
    Otherwise, only parses files that don't have entries yet.
    """
    from ck3raven.parser.localization import parse_localization, LocalizationFile
    
    parser_version_id = get_or_create_parser_version(conn)
    
    if force:
        logger.info("Force mode: clearing all localization entries...")
        conn.execute("DELETE FROM localization_entries")
        conn.execute("DELETE FROM localization_refs")
        conn.commit()
    
    # Find localization files that need parsing
    # A file needs parsing if:
    # 1. Its content_hash doesn't have localization entries for this parser version
    # 2. It's a .yml file in a localization folder
    
    query = """
        SELECT DISTINCT fc.content_hash, fc.content_text, f.relpath
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        LEFT JOIN localization_entries le ON fc.content_hash = le.content_hash 
            AND le.parser_version_id = ?
        WHERE f.deleted = 0
        AND (f.relpath LIKE 'localization/%%.yml' OR f.relpath LIKE '%/localization/%%.yml')
        AND fc.content_text IS NOT NULL
        AND le.loc_id IS NULL
    """
    
    # Count first
    count_query = """
        SELECT COUNT(DISTINCT fc.content_hash)
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        LEFT JOIN localization_entries le ON fc.content_hash = le.content_hash 
            AND le.parser_version_id = ?
        WHERE f.deleted = 0
        AND (f.relpath LIKE 'localization/%%.yml' OR f.relpath LIKE '%/localization/%%.yml')
        AND fc.content_text IS NOT NULL
        AND le.loc_id IS NULL
    """
    
    total_count = conn.execute(count_query, (parser_version_id,)).fetchone()[0]
    
    if total_count == 0:
        logger.info("All localization files already parsed - nothing to do")
        return {'files': 0, 'entries': 0, 'refs': 0, 'errors': 0}
    
    logger.info(f"Parsing {total_count} localization files...")
    
    # Process in chunks
    chunk_size = 100  # Smaller chunks since loc files can have many entries
    processed = 0
    total_entries = 0
    total_refs = 0
    errors = 0
    
    offset = 0
    
    while True:
        write_heartbeat()
        
        rows = conn.execute(
            query + " LIMIT ? OFFSET ?",
            (parser_version_id, chunk_size, offset)
        ).fetchall()
        
        if not rows:
            break
        
        for idx, (content_hash, content, relpath) in enumerate(rows):
            if idx % 20 == 0:
                write_heartbeat()
            
            if not content:
                continue
            
            try:
                # Parse the localization file
                result: LocalizationFile = parse_localization(content, relpath)
                
                # Insert entries
                for entry in result.entries:
                    # Insert the localization entry
                    cursor = conn.execute("""
                        INSERT INTO localization_entries
                        (content_hash, language, loc_key, version, raw_value, 
                         plain_text, line_number, parser_version_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        content_hash,
                        result.language,
                        entry.key,
                        entry.version,
                        entry.raw_value,
                        entry.plain_text,
                        entry.line_number,
                        parser_version_id
                    ))
                    
                    loc_id = cursor.lastrowid
                    total_entries += 1
                    
                    # Insert references (scripted, variable, icon)
                    for ref in entry.scripted_refs:
                        conn.execute("""
                            INSERT INTO localization_refs (loc_id, ref_type, ref_value)
                            VALUES (?, 'scripted', ?)
                        """, (loc_id, ref))
                        total_refs += 1
                    
                    for ref in entry.variable_refs:
                        conn.execute("""
                            INSERT INTO localization_refs (loc_id, ref_type, ref_value)
                            VALUES (?, 'variable', ?)
                        """, (loc_id, ref))
                        total_refs += 1
                    
                    for ref in entry.icon_refs:
                        conn.execute("""
                            INSERT INTO localization_refs (loc_id, ref_type, ref_value)
                            VALUES (?, 'icon', ?)
                        """, (loc_id, ref))
                        total_refs += 1
                
                processed += 1
                
            except Exception as e:
                errors += 1
                if errors <= 20:
                    logger.warning(f"Localization parse error in {relpath}: {e}")
        
        conn.commit()
        offset += len(rows)
        
        pct = min(100, (offset / total_count) * 100)
        status.update(
            progress=pct,
            message=f"Localization: {offset}/{total_count} files ({pct:.1f}%)"
        )
        
        if offset % 500 == 0:
            logger.info(f"Localization progress: {offset}/{total_count}, {total_entries} entries, {errors} errors")
    
    logger.info(f"Localization parsing complete: {processed} files, {total_entries} entries, {total_refs} refs, {errors} errors")
    return {'files': processed, 'entries': total_entries, 'refs': total_refs, 'errors': errors}


def extract_lookup_tables(conn, logger: DaemonLogger, status: StatusWriter):
    """
    Extract ID-keyed lookup data into denormalized tables.
    
    This is Phase 7: Lookup Extraction.
    
    Lookups are for OPAQUE NUMERIC IDs that need resolution to names:
    - province_lookup: province ID → name, RGB, culture, religion
    - character_lookup: character ID → name, dynasty, dates
    - dynasty_lookup: dynasty ID → name key, culture
    - title_lookup: title key → tier, capital, colors
    
    Note: traits, events, decisions are STRING-KEYED and use symbols table.
    """
    from pathlib import Path
    from builder.config import get_config
    
    logger.info("Starting ID-keyed lookup table extraction...")
    
    total_extracted = 0
    total_errors = 0
    results = {}
    
    # Get vanilla content_version_id
    vanilla_cv_row = conn.execute("""
        SELECT cv.content_version_id 
        FROM content_versions cv
        WHERE cv.kind = 'vanilla'
        ORDER BY cv.content_version_id DESC
        LIMIT 1
    """).fetchone()
    
    if not vanilla_cv_row:
        logger.warning("No vanilla content_version found, skipping lookups")
        return {'total': 0, 'errors': 0, 'status': 'no_vanilla'}
    
    vanilla_cv_id = vanilla_cv_row[0]
    config = get_config()
    vanilla_path = config.vanilla_path
    
    # 1. Province lookup (from definition.csv)
    write_heartbeat()
    status.update(message="Extracting province lookups from definition.csv...")
    try:
        from builder.extractors.lookups.province import extract_provinces
        stats = extract_provinces(conn, vanilla_path, vanilla_cv_id)
        logger.info(f"  provinces: inserted={stats['inserted']}, errors={stats['errors']}")
        results['provinces'] = stats
        total_extracted += stats['inserted']
        total_errors += stats['errors']
    except Exception as e:
        logger.warning(f"  province extraction failed: {e}")
        total_errors += 1
    
    # 2. Dynasty lookup (from common/dynasties/ ASTs)
    write_heartbeat()
    status.update(message="Extracting dynasty lookups...")
    try:
        from builder.extractors.lookups.dynasty import extract_dynasties
        stats = extract_dynasties(conn, vanilla_cv_id)
        logger.info(f"  dynasties: inserted={stats['inserted']}, errors={stats['errors']}")
        results['dynasties'] = stats
        total_extracted += stats['inserted']
        total_errors += stats['errors']
    except Exception as e:
        logger.warning(f"  dynasty extraction failed: {e}")
        total_errors += 1
    
    # 3. Character lookup (from history/characters/ ASTs)
    write_heartbeat()
    status.update(message="Extracting character lookups...")
    try:
        from builder.extractors.lookups.character import extract_characters
        stats = extract_characters(conn, vanilla_cv_id)
        logger.info(f"  characters: inserted={stats['inserted']}, errors={stats['errors']}")
        results['characters'] = stats
        total_extracted += stats['inserted']
        total_errors += stats['errors']
    except Exception as e:
        logger.warning(f"  character extraction failed: {e}")
        total_errors += 1
    
    # 4. Title lookup (from common/landed_titles/ ASTs)
    write_heartbeat()
    status.update(message="Extracting landed title lookups...")
    try:
        from builder.extractors.lookups.landed_titles import extract_landed_titles
        stats = extract_landed_titles(conn, vanilla_cv_id)
        logger.info(f"  landed_titles: inserted={stats['inserted']}, errors={stats['errors']}")
        results['landed_titles'] = stats
        total_extracted += stats['inserted']
        total_errors += stats['errors']
    except Exception as e:
        logger.warning(f"  landed_titles extraction failed: {e}")
        total_errors += 1
    
    logger.info(f"Lookup extraction complete: {total_extracted} records, {total_errors} errors")
    return {'total': total_extracted, 'errors': total_errors, 'details': results}

# =============================================================================
# SYMBOL/REF EXTRACTION FROM STORED ASTs
# =============================================================================

def extract_symbols_from_stored_asts(conn, logger: DaemonLogger, status: StatusWriter, force_rebuild: bool = False):
    """Extract symbols from stored ASTs using the library's incremental function.
    
    Delegates to ck3raven.db.symbols.extract_symbols_incremental which:
    - Only processes ASTs that don't have symbols yet (unless force_rebuild)
    - Doesn't delete existing valid symbols (unless force_rebuild)
    - Uses centralized file routing from file_routes.py
    - Maintains full source traceability
    
    Enhanced logging:
    - Progress every 50 ASTs with timing
    - Bloat file tracking (large ASTs)
    - File routing verification
    """
    from ck3raven.db.symbols import extract_symbols_incremental
    from ck3raven.db.file_routes import get_file_route, FileRoute
    import json as _json

    logger.info("Starting incremental symbol extraction...")
    
    # Track timing and bloat files
    start_time = time.time()
    last_log_time = start_time
    last_log_count = 0
    bloat_files = []  # Files with large ASTs or many symbols
    
    # Verify file routing is working - sample check
    sample_routes = conn.execute("""
        SELECT relpath, 
               CASE WHEN relpath LIKE 'localization/%' THEN 'localization'
                    WHEN relpath LIKE 'gfx/%' OR relpath LIKE 'gui/%' THEN 'skip'
                    ELSE 'script' END as expected_route
        FROM files WHERE deleted = 0
        ORDER BY RANDOM() LIMIT 5
    """).fetchall()
    
    logger.info("File routing spot-check:")
    for relpath, expected in sample_routes:
        actual_route, reason = get_file_route(relpath)
        match = "✓" if actual_route.value == expected else "✗"
        logger.info(f"  {match} {relpath[:60]} -> {actual_route.value} (expected {expected})")

    def progress_callback(processed, total, symbols):
        nonlocal last_log_time, last_log_count
        write_heartbeat()
        pct = (processed / total * 100) if total > 0 else 0
        status.update(
            progress=pct,
            message=f"Symbols: {processed}/{total} ASTs, {symbols} symbols"
        )
        
        # Log every 50 ASTs with timing info
        if processed - last_log_count >= 50 or processed == total:
            now = time.time()
            elapsed_batch = now - last_log_time
            elapsed_total = now - start_time
            rate = (processed - last_log_count) / elapsed_batch if elapsed_batch > 0 else 0
            avg_rate = processed / elapsed_total if elapsed_total > 0 else 0
            eta_sec = (total - processed) / avg_rate if avg_rate > 0 else 0
            eta_min = eta_sec / 60
            
            logger.info(
                f"Symbol progress: {processed}/{total} ({pct:.1f}%) | "
                f"{symbols} symbols | {rate:.1f} AST/s (avg {avg_rate:.1f}) | "
                f"ETA: {eta_min:.1f}min"
            )
            last_log_time = now
            last_log_count = processed

    result = extract_symbols_incremental(
        conn,
        batch_size=50,  # Smaller batches for more frequent logging
        progress_callback=progress_callback,
        force_rebuild=force_rebuild
    )
    
    total_time = time.time() - start_time

    logger.info(
        f"Symbol extraction complete in {total_time:.1f}s: "
        f"extracted={result['symbols_extracted']}, "
        f"inserted={result['symbols_inserted']}, duplicates={result['duplicates']}, "
        f"errors={result['errors']}, skipped={result.get('files_skipped', 0)}"
    )
    
    # Report bloat files (top 10 largest ASTs by symbol count)
    bloat_query = conn.execute("""
        SELECT f.relpath, COUNT(s.symbol_id) as sym_count
        FROM symbols s
        JOIN files f ON s.defining_file_id = f.file_id
        GROUP BY f.file_id
        ORDER BY sym_count DESC
        LIMIT 10
    """).fetchall()
    
    if bloat_query:
        logger.info("Top 10 files by symbol count (bloat check):")
        for relpath, sym_count in bloat_query:
            logger.info(f"  {sym_count:5d} symbols: {relpath[:70]}")
    
    return {'extracted': result['symbols_extracted'], 'inserted': result['symbols_inserted'], 
            'duplicates': result['duplicates'], 'errors': result['errors']}


def extract_refs_from_stored_asts(conn, logger: DaemonLogger, status: StatusWriter):
    """Extract references from stored ASTs (not re-parsing).
    
    Optimized for performance:
    - Batch inserts instead of individual INSERTs
    - Pre-fetch content_version_id to avoid subquery per ref
    - Process in larger batches
    """
    from ck3raven.db.symbols import extract_refs_from_ast
    import json
    
    logger.info("Starting reference extraction from stored ASTs...")
    
    # Track timing
    start_time = time.time()
    last_log_time = start_time
    last_log_count = 0
    
    # Clear old refs
    conn.execute("DELETE FROM refs")
    conn.commit()
    
    # Build file_id -> content_version_id lookup for performance
    logger.info("Building content_version_id lookup...")
    cv_lookup = {}
    cv_rows = conn.execute("SELECT file_id, content_version_id FROM files WHERE deleted = 0").fetchall()
    for file_id, cv_id in cv_rows:
        cv_lookup[file_id] = cv_id
    logger.info(f"Cached {len(cv_lookup)} file -> content_version mappings")
    
    # Query files that have ASTs
    total_count = conn.execute("""
        SELECT COUNT(*) FROM files f
        JOIN asts a ON f.content_hash = a.content_hash
        WHERE f.deleted = 0 AND a.parse_ok = 1
        AND f.relpath LIKE '%.txt'
    """).fetchone()[0]
    
    logger.info(f"Processing {total_count} files for refs")
    
    chunk_size = 100  # Larger chunks for better performance
    offset = 0
    total_refs = 0
    errors = 0
    batch_refs = []  # Accumulate refs for batch insert
    
    while offset < total_count:
        write_heartbeat()
        
        rows = conn.execute("""
            SELECT f.file_id, f.relpath, f.content_hash, a.ast_id, a.ast_blob
            FROM files f
            JOIN asts a ON f.content_hash = a.content_hash
            WHERE f.deleted = 0 AND a.parse_ok = 1
            AND f.relpath LIKE '%.txt'
            ORDER BY f.file_id
            LIMIT ? OFFSET ?
        """, (chunk_size, offset)).fetchall()
        
        if not rows:
            break
        
        for file_id, relpath, content_hash, ast_id, ast_blob in rows:
            try:
                # Decode AST from blob
                ast_dict = json.loads(ast_blob.decode('utf-8'))
                
                refs = list(extract_refs_from_ast(ast_dict, relpath, content_hash))
                
                # Use cached content_version_id instead of subquery per ref
                cv_id = cv_lookup.get(file_id)
                if cv_id is None:
                    # Fallback query if not in cache (shouldn't happen)
                    row = conn.execute(
                        "SELECT content_version_id FROM files WHERE file_id = ?", (file_id,)
                    ).fetchone()
                    cv_id = row[0] if row else None
                
                if cv_id is not None:
                    for ref in refs:
                        batch_refs.append((
                            ref.kind, ref.name, file_id, ast_id, 
                            ref.line, ref.context, cv_id
                        ))
                
                total_refs += len(refs)
                
            except Exception as e:
                errors += 1
        
        # Batch insert all refs from this chunk
        if batch_refs:
            conn.executemany("""
                INSERT OR IGNORE INTO refs
                (ref_type, name, using_file_id, using_ast_id, line_number, context, content_version_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, batch_refs)
            batch_refs = []  # Reset for next chunk
        
        conn.commit()
        offset += len(rows)
        
        pct = (offset / total_count) * 100
        status.update(
            progress=pct,
            message=f"Refs: {offset}/{total_count} files, {total_refs} refs"
        )
        
        # Log every 50 files with timing
        if offset - last_log_count >= 50 or offset >= total_count:
            now = time.time()
            elapsed_batch = now - last_log_time
            elapsed_total = now - start_time
            rate = (offset - last_log_count) / elapsed_batch if elapsed_batch > 0 else 0
            avg_rate = offset / elapsed_total if elapsed_total > 0 else 0
            eta_sec = (total_count - offset) / avg_rate if avg_rate > 0 else 0
            eta_min = eta_sec / 60
            
            logger.info(
                f"Ref progress: {offset}/{total_count} ({pct:.1f}%) | "
                f"{total_refs} refs | {rate:.1f} files/s (avg {avg_rate:.1f}) | "
                f"ETA: {eta_min:.1f}min"
            )
            last_log_time = now
            last_log_count = offset
    
    total_time = time.time() - start_time
    logger.info(f"Ref extraction complete in {total_time:.1f}s: {total_refs} refs, {errors} errors")
    return {'extracted': total_refs, 'errors': errors}


def debug_daemon_phase(db_path: Path, phase: str, limit: int = 10) -> Path:
    """
    Debug any daemon phase using DebugSession architecture.
    
    Uses the unified DebugSession for phase-agnostic instrumentation.
    Outputs:
        - ~/.ck3raven/daemon/debug_trace.jsonl (JSONL event stream)
        - ~/.ck3raven/daemon/debug_summary.json (aggregated stats)
    
    Supported phases:
        - "all": Run all phases sequentially
        - "ingest": File discovery and content storage timing
        - "parse": Content → AST parsing 
        - "symbols": AST → symbol extraction
        - "refs": AST → reference extraction
        - "localization": YML → localization_entries extraction
        - "lookups": Symbol → lookup table extraction
    
    Args:
        db_path: Path to database
        phase: Which phase to debug
        limit: Number of files to process
        
    Returns:
        Path to output directory containing debug_trace.jsonl and debug_summary.json
    """
    import sqlite3
    from builder.debug import DebugSession
    
    conn = sqlite3.connect(db_path)
    
    # Determine which phases to run
    if phase == "all":
        phases = ["ingest", "parse", "symbols", "refs", "localization", "lookups"]
    else:
        phases = [phase]
    
    # Create debug session
    with DebugSession.from_config(
        output_dir=DAEMON_DIR,
        enabled=True,
        sample_limit=limit,
        phase_filter=phases if phase != "all" else None,
    ) as debug:
        
        for p in phases:
            debug.phase_start(p)
            
            try:
                if p == "ingest":
                    _debug_ingest_with_session(conn, debug, limit)
                elif p == "parse":
                    _debug_parse_with_session(conn, debug, limit)
                elif p == "symbols":
                    _debug_symbols_with_session(conn, debug, limit)
                elif p == "refs":
                    _debug_refs_with_session(conn, debug, limit)
                elif p == "localization":
                    _debug_localization_with_session(conn, debug, limit)
                elif p == "lookups":
                    _debug_lookups_with_session(conn, debug, limit)
                else:
                    debug.emit("error", message=f"Unknown phase: {p}")
            except Exception as e:
                debug.emit("error", message=str(e), phase=p)
            
            debug.phase_end(p)
        
    conn.close()
    
    # Also write legacy format for backwards compatibility
    _write_legacy_debug_output(db_path, phase, limit)
    
    return DAEMON_DIR


def _debug_ingest_with_session(conn, debug, limit: int):
    """Debug ingest phase using DebugSession."""
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, fc.size, fc.is_binary
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        LIMIT ?
    """, (limit,)).fetchall()
    
    for file_id, relpath, content_hash, size, is_binary in rows:
        with debug.span("file", phase="ingest", path=relpath) as s:
            s.add(
                file_id=file_id,
                input_bytes=size,
                is_binary=bool(is_binary),
                output_count=1,  # One file stored
            )


def _debug_parse_with_session(conn, debug, limit: int):
    """Debug parse phase using DebugSession."""
    from ck3raven.parser import parse_source
    import json as json_mod
    
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, fc.content_text
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.relpath LIKE '%.txt'
        AND fc.content_text IS NOT NULL
        AND LENGTH(fc.content_text) < 500000
        LIMIT ?
    """, (limit,)).fetchall()
    
    for file_id, relpath, content_text in rows:
        with debug.span("file", phase="parse", path=relpath) as s:
            input_bytes = len(content_text) if content_text else 0
            s.add(input_bytes=input_bytes)
            
            try:
                ast = parse_source(content_text, relpath)
                if ast:
                    ast_dict = ast.to_dict() if hasattr(ast, 'to_dict') else ast
                    ast_json = json_mod.dumps(ast_dict, separators=(',', ':'))
                    s.add(
                        output_bytes=len(ast_json),
                        output_count=ast_json.count('{'),  # node count estimate
                        ok=True,
                    )
                else:
                    s.add(ok=False, output_count=0)
            except Exception as e:
                s.add(ok=False, error=str(e)[:100])
                debug.emit("error", phase="parse", path=relpath, message=str(e)[:200])


def _debug_symbols_with_session(conn, debug, limit: int):
    """Debug symbols phase using DebugSession."""
    from ck3raven.db.symbols import extract_symbols_from_ast
    import json as json_mod
    
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, a.ast_blob, a.ast_id
        FROM files f
        JOIN asts a ON f.content_hash = a.content_hash
        WHERE a.parse_ok = 1
        LIMIT ?
    """, (limit,)).fetchall()
    
    for file_id, relpath, content_hash, ast_blob, ast_id in rows:
        with debug.span("file", phase="symbols", path=relpath) as s:
            s.add(input_bytes=len(ast_blob) if ast_blob else 0, ast_id=ast_id)
            
            try:
                ast_dict = json_mod.loads(ast_blob.decode('utf-8'))
                symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
                s.add(output_count=len(symbols), ok=True)
            except Exception as e:
                s.add(ok=False, error=str(e)[:100])
                debug.emit("error", phase="symbols", path=relpath, message=str(e)[:200])


def _debug_refs_with_session(conn, debug, limit: int):
    """Debug refs phase using DebugSession."""
    from ck3raven.db.symbols import extract_refs_from_ast
    import json as json_mod
    
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, a.ast_blob, a.ast_id
        FROM files f
        JOIN asts a ON f.content_hash = a.content_hash
        WHERE a.parse_ok = 1
        LIMIT ?
    """, (limit,)).fetchall()
    
    for file_id, relpath, content_hash, ast_blob, ast_id in rows:
        with debug.span("file", phase="refs", path=relpath) as s:
            s.add(input_bytes=len(ast_blob) if ast_blob else 0, ast_id=ast_id)
            
            try:
                ast_dict = json_mod.loads(ast_blob.decode('utf-8'))
                refs = list(extract_refs_from_ast(ast_dict, relpath, content_hash))
                s.add(output_count=len(refs), ok=True)
            except Exception as e:
                s.add(ok=False, error=str(e)[:100])
                debug.emit("error", phase="refs", path=relpath, message=str(e)[:200])


def _debug_localization_with_session(conn, debug, limit: int):
    """Debug localization phase using DebugSession."""
    from ck3raven.parser.localization import parse_localization
    
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, fc.content_text
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.relpath LIKE '%_l_english.yml'
        AND fc.content_text IS NOT NULL
        LIMIT ?
    """, (limit,)).fetchall()
    
    for file_id, relpath, content_text in rows:
        with debug.span("file", phase="localization", path=relpath) as s:
            s.add(input_bytes=len(content_text) if content_text else 0)
            
            try:
                loc_file = parse_localization(content_text, relpath)
                s.add(output_count=len(loc_file.entries), ok=True)
            except Exception as e:
                s.add(ok=False, error=str(e)[:100])
                debug.emit("error", phase="localization", path=relpath, message=str(e)[:200])


def _debug_lookups_with_session(conn, debug, limit: int):
    """Debug lookups phase using DebugSession."""
    tables = ["trait_lookups", "event_lookups", "decision_lookups"]
    
    for table in tables:
        with debug.span("file", phase="lookups", path=table) as s:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                s.add(output_count=count, ok=True)
            except Exception as e:
                s.add(ok=False, error=str(e)[:100])


def _write_legacy_debug_output(db_path: Path, phase: str, limit: int):
    """Write legacy debug_output.json format for backwards compatibility."""
    import sqlite3
    
    conn = sqlite3.connect(db_path)
    
    output = {
        "started_at": datetime.now().isoformat(),
        "phase": phase,
        "limit": limit,
        "db_path": str(db_path),
        "files": [],
        "blocks": {},
        "summary": {},
        "errors": []
    }
    
    try:
        if phase == "all":
            phases = ["ingest", "parse", "symbols", "refs", "localization", "lookups"]
            output["phases"] = {}
            for p in phases:
                phase_output = {"files": [], "summary": {}, "errors": []}
                try:
                    if p == "ingest":
                        _debug_ingest_phase(conn, phase_output, limit)
                    elif p == "parse":
                        _debug_parse_phase(conn, phase_output, limit)
                    elif p == "symbols":
                        _debug_symbols_phase(conn, phase_output, limit)
                    elif p == "refs":
                        _debug_refs_phase(conn, phase_output, limit)
                    elif p == "localization":
                        _debug_localization_phase(conn, phase_output, limit)
                    elif p == "lookups":
                        _debug_lookups_phase(conn, phase_output, limit)
                except Exception as e:
                    phase_output["errors"].append(str(e))
                output["phases"][p] = phase_output
            output["summary"] = {"phases_run": len(phases)}
        else:
            if phase == "ingest":
                _debug_ingest_phase(conn, output, limit)
            elif phase == "parse":
                _debug_parse_phase(conn, output, limit)
            elif phase == "symbols":
                _debug_symbols_phase(conn, output, limit)
            elif phase == "refs":
                _debug_refs_phase(conn, output, limit)
            elif phase == "localization":
                _debug_localization_phase(conn, output, limit)
            elif phase == "lookups":
                _debug_lookups_phase(conn, output, limit)
    except Exception as e:
        output["errors"].append(str(e))
    finally:
        conn.close()
    
    output["completed_at"] = datetime.now().isoformat()
    _write_debug_output(output)


# Legacy debug functions - kept for backwards compatibility
def _debug_ingest_phase(conn: sqlite3.Connection, output: dict, limit: int):
    """Debug file ingestion - measure file discovery and content storage."""
    
    # Get sample of files with their content
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, fc.size, fc.is_binary
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        LIMIT ?
    """, (limit,)).fetchall()
    
    if not rows:
        output["errors"].append("No files found in database")
        return
    
    total_size = 0
    for file_id, relpath, content_hash, size, is_binary in rows:
        file_result = {
            "file": relpath,
            "file_id": file_id,
            "content_hash": content_hash[:16] + "...",
            "size_bytes": size,
            "is_binary": bool(is_binary)
        }
        output["files"].append(file_result)
        total_size += size or 0
    
    output["summary"] = {
        "files_sampled": len(rows),
        "total_size_bytes": total_size,
        "avg_size_bytes": round(total_size / len(rows), 0) if rows else 0,
        "note": "Ingest timing requires running actual ingest - this shows stored data stats"
    }


def _debug_parse_phase(conn: sqlite3.Connection, output: dict, limit: int):
    """Debug parsing - measure content → AST timing."""
    from ck3raven.parser import parse_source_recovering
    
    # Get files that need parsing (have content but no AST, or sample existing)
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, fc.content_text
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE fc.is_binary = 0 AND fc.content_text IS NOT NULL
        AND f.relpath LIKE '%.txt'
        LIMIT ?
    """, (limit,)).fetchall()
    
    if not rows:
        output["errors"].append("No parseable files found")
        return
    
    total_parse_ms = 0
    total_size = 0
    parsed_count = 0
    
    for file_id, relpath, content_hash, content_text in rows:
        file_result = {
            "file": relpath,
            "file_id": file_id,
            "input_size_bytes": len(content_text) if content_text else 0
        }
        
        try:
            # Time the parsing - use recovering parser to get error info
            t0 = time.time()
            result = parse_source_recovering(content_text, filename=relpath)
            parse_ms = (time.time() - t0) * 1000
            
            file_result["parse_ms"] = round(parse_ms, 2)
            file_result["parse_ok"] = result.success
            file_result["error_count"] = len([d for d in result.diagnostics if d.severity == "error"])
            
            if result.ast:
                file_result["node_count"] = _count_ast_nodes(result.ast.to_dict())
                # Measure AST bloat
                ast_json = json.dumps(result.ast.to_dict())
                file_result["output_size_bytes"] = len(ast_json)
                file_result["bloat_ratio"] = round(len(ast_json) / max(1, len(content_text)), 2)
            
            total_parse_ms += parse_ms
            total_size += len(content_text) if content_text else 0
            parsed_count += 1
            
        except Exception as e:
            file_result["error"] = str(e)
            output["errors"].append({"file": relpath, "error": str(e)})
        
        output["files"].append(file_result)
    
    if parsed_count > 0:
        avg_ms = total_parse_ms / parsed_count
        output["summary"] = {
            "files_parsed": parsed_count,
            "total_parse_ms": round(total_parse_ms, 2),
            "avg_parse_ms": round(avg_ms, 2),
            "projected_rate_per_sec": round(1000 / avg_ms, 1) if avg_ms > 0 else 0,
            "total_input_bytes": total_size,
            "avg_input_bytes": round(total_size / parsed_count, 0)
        }


def _debug_symbols_phase(conn: sqlite3.Connection, output: dict, limit: int):
    """Debug symbol extraction - measure AST → symbols timing."""
    from ck3raven.db.symbols import extract_symbols_from_ast
    
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, a.ast_blob, a.ast_id
        FROM asts a
        JOIN files f ON a.content_hash = f.content_hash
        WHERE a.parse_ok = 1
        LIMIT ?
    """, (limit,)).fetchall()
    
    if not rows:
        output["errors"].append("No ASTs found in database")
        return
    
    total_extract_ms = 0
    total_symbols = 0
    
    for file_id, relpath, content_hash, ast_blob, ast_id in rows:
        file_result = {
            "file": relpath,
            "file_id": file_id,
            "ast_id": ast_id,
            "ast_size_bytes": len(ast_blob) if ast_blob else 0
        }
        
        try:
            # Decode AST
            t0 = time.time()
            ast_dict = json.loads(ast_blob.decode('utf-8'))
            decode_ms = (time.time() - t0) * 1000
            file_result["decode_ms"] = round(decode_ms, 2)
            
            # Extract symbols
            t1 = time.time()
            symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
            extract_ms = (time.time() - t1) * 1000
            file_result["extract_ms"] = round(extract_ms, 2)
            file_result["symbols_count"] = len(symbols)
            file_result["total_ms"] = round(decode_ms + extract_ms, 2)
            
            total_extract_ms += decode_ms + extract_ms
            total_symbols += len(symbols)
            
        except Exception as e:
            file_result["error"] = str(e)
            output["errors"].append({"file": relpath, "error": str(e)})
        
        output["files"].append(file_result)
    
    valid = [f for f in output["files"] if "total_ms" in f]
    if valid:
        avg_ms = sum(f["total_ms"] for f in valid) / len(valid)
        output["summary"] = {
            "files_processed": len(valid),
            "total_symbols": total_symbols,
            "avg_ms_per_file": round(avg_ms, 2),
            "projected_rate_per_sec": round(1000 / avg_ms, 1) if avg_ms > 0 else 0
        }


def _debug_refs_phase(conn: sqlite3.Connection, output: dict, limit: int):
    """Debug ref extraction - measure AST → refs timing."""
    from ck3raven.db.symbols import extract_refs_from_ast
    
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, a.ast_blob, a.ast_id
        FROM asts a
        JOIN files f ON a.content_hash = f.content_hash
        WHERE a.parse_ok = 1
        LIMIT ?
    """, (limit,)).fetchall()
    
    if not rows:
        output["errors"].append("No ASTs found in database")
        return
    
    total_decode_ms = 0
    total_extract_ms = 0
    total_refs = 0
    
    for file_id, relpath, content_hash, ast_blob, ast_id in rows:
        file_result = {
            "file": relpath,
            "file_id": file_id,
            "ast_id": ast_id,
            "ast_size_bytes": len(ast_blob) if ast_blob else 0
        }
        
        try:
            # Block 1: Decode AST
            t0 = time.time()
            ast_dict = json.loads(ast_blob.decode('utf-8'))
            decode_ms = (time.time() - t0) * 1000
            file_result["decode_ms"] = round(decode_ms, 2)
            total_decode_ms += decode_ms
            
            file_result["ast_node_count"] = _count_ast_nodes(ast_dict)
            
            # Block 2: Extract refs
            t1 = time.time()
            refs = list(extract_refs_from_ast(ast_dict, relpath, content_hash))
            extract_ms = (time.time() - t1) * 1000
            file_result["extract_ms"] = round(extract_ms, 2)
            file_result["refs_count"] = len(refs)
            total_refs += len(refs)
            total_extract_ms += extract_ms
            
            file_result["total_ms"] = round(decode_ms + extract_ms, 2)
            
            if file_result["ast_size_bytes"] > 0:
                file_result["refs_per_kb"] = round(
                    len(refs) / (file_result["ast_size_bytes"] / 1024), 2
                )
                
        except Exception as e:
            file_result["error"] = str(e)
            output["errors"].append({"file": relpath, "error": str(e)})
        
        output["files"].append(file_result)
    
    valid = [f for f in output["files"] if "total_ms" in f]
    if valid:
        times = [f["total_ms"] for f in valid]
        sizes = [f["ast_size_bytes"] for f in valid]
        avg_ms = sum(times) / len(times)
        
        output["summary"] = {
            "files_processed": len(valid),
            "total_refs": total_refs,
            "total_decode_ms": round(total_decode_ms, 2),
            "total_extract_ms": round(total_extract_ms, 2),
            "avg_ms_per_file": round(avg_ms, 2),
            "min_ms": round(min(times), 2),
            "max_ms": round(max(times), 2),
            "projected_rate_per_sec": round(1000 / avg_ms, 1) if avg_ms > 0 else 0,
            "total_ast_bytes": sum(sizes),
            "bloat_indicator": round(sum(sizes) / (total_refs + 1), 2)
        }


def _debug_localization_phase(conn: sqlite3.Connection, output: dict, limit: int):
    """Debug localization extraction - measure YML → loc entries timing."""
    from ck3raven.parser.localization import parse_localization
    
    # Get YML files
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, fc.content_text
        FROM files f
        JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE f.relpath LIKE '%_l_english.yml'
        AND fc.content_text IS NOT NULL
        LIMIT ?
    """, (limit,)).fetchall()
    
    if not rows:
        output["errors"].append("No localization files found")
        return
    
    total_parse_ms = 0
    total_entries = 0
    
    for file_id, relpath, content_text in rows:
        file_result = {
            "file": relpath,
            "file_id": file_id,
            "input_size_bytes": len(content_text) if content_text else 0
        }
        
        try:
            t0 = time.time()
            loc_file = parse_localization(content_text, relpath)
            parse_ms = (time.time() - t0) * 1000
            
            file_result["parse_ms"] = round(parse_ms, 2)
            file_result["entries_count"] = len(loc_file.entries)
            file_result["entries_per_kb"] = round(
                len(loc_file.entries) / max(1, len(content_text) / 1024), 2
            )
            
            total_parse_ms += parse_ms
            total_entries += len(loc_file.entries)
            
        except Exception as e:
            file_result["error"] = str(e)
            output["errors"].append({"file": relpath, "error": str(e)})
        
        output["files"].append(file_result)
    
    valid = [f for f in output["files"] if "parse_ms" in f]
    if valid:
        avg_ms = total_parse_ms / len(valid)
        output["summary"] = {
            "files_processed": len(valid),
            "total_entries": total_entries,
            "avg_ms_per_file": round(avg_ms, 2),
            "projected_rate_per_sec": round(1000 / avg_ms, 1) if avg_ms > 0 else 0
        }


def _debug_lookups_phase(conn: sqlite3.Connection, output: dict, limit: int):
    """Debug lookup extraction - show current lookup table stats."""
    
    # This phase doesn't process files individually, so just show stats
    tables = ["trait_lookups", "event_lookups", "decision_lookups"]
    
    table_stats = {}
    for table in tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            table_stats[table] = {"count": count}
        except Exception as e:
            table_stats[table] = {"error": str(e)}
    
    # Sample some lookups
    try:
        traits = conn.execute("SELECT name, category FROM trait_lookups LIMIT ?", (limit,)).fetchall()
        output["files"] = [{"name": t[0], "category": t[1]} for t in traits]
        output["summary"] = {
            "note": "Lookups phase builds aggregate tables from symbols",
            "tables": table_stats
        }
    except Exception as e:
        output["errors"].append({"phase": "lookups", "error": str(e)})


def _count_ast_nodes(node, depth=0) -> int:
    """Count nodes in AST for bloat measurement."""
    if depth > 100:  # Prevent infinite recursion
        return 1
    
    if isinstance(node, dict):
        count = 1
        for v in node.values():
            count += _count_ast_nodes(v, depth + 1)
        return count
    elif isinstance(node, list):
        return sum(_count_ast_nodes(item, depth + 1) for item in node)
    else:
        return 1


def _write_debug_output(output: dict):
    """Write debug output to JSON file."""
    DEBUG_OUTPUT_FILE.write_text(json.dumps(output, indent=2))


def start_detached(db_path: Path, force: bool, symbols_only: bool = False, playset_file: Path = None):
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
    if playset_file:
        args.extend(["--playset-file", str(playset_file)])
    
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
    # Ensure paths are set up early for detached process
    src_path = Path(__file__).parent.parent / "src"
    if src_path.exists() and str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
        
    parser = argparse.ArgumentParser(description="CK3Raven rebuild daemon")
    parser.add_argument("command", choices=["start", "status", "stop", "logs", "_run_daemon"],
                        help="Command to execute")
    parser.add_argument("--force", action="store_true", help="Force complete rebuild")
    parser.add_argument("--symbols-only", action="store_true", help="Only run symbol/ref extraction (skip ingest)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Database path")
    parser.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    
    # Debug mode options - unified for any phase
    parser.add_argument("--debug", type=str, metavar="PHASE",
                        choices=["all", "ingest", "parse", "symbols", "refs", "localization", "lookups"],
                        help="Debug daemon phase(s) with detailed timing. Use 'all' for all phases. Output to ~/.ck3raven/daemon/debug_output.json")
    parser.add_argument("--debug-limit", type=int, default=10, metavar="N",
                        help="Number of files to process in debug mode (default: 10)")
    
    # Test mode options
    parser.add_argument("--test", action="store_true", 
                        help="Run synchronously with verbose output (for testing)")
    parser.add_argument("--vanilla-path", type=Path, 
                        help="Custom vanilla path (for testing with fixtures)")
    parser.add_argument("--skip-mods", action="store_true",
                        help="Skip mod ingestion (for vanilla-only testing)")
    parser.add_argument("--playset-file", type=Path,
                        help="Path to active_mod_paths.json to build only active playset mods")
    
    args = parser.parse_args()
    
    if args.command == "start":
        if args.debug:
            # Debug a specific phase - outputs to file, not terminal
            print(f"Running {args.debug} phase debug on {args.debug_limit} files...")
            print(f"Output will be written to: {DAEMON_DIR}")
            output_dir = debug_daemon_phase(args.db, args.debug, args.debug_limit)
            print(f"\nDebug complete. Results saved to: {output_dir}")
            
            # Print summary from the new debug_summary.json
            summary_file = output_dir / "debug_summary.json"
            legacy_file = output_dir / "debug_output.json"
            
            try:
                if summary_file.exists():
                    result = json.loads(summary_file.read_text())
                    print(f"\n=== DebugSession Summary ===")
                    print(f"Run ID: {result.get('run_id', 'N/A')}")
                    print(f"Duration: {result.get('duration_sec', 0):.1f}s")
                    for phase_name, phase_stats in result.get("phases", {}).items():
                        print(f"\n{phase_name}:")
                        print(f"  Files: {phase_stats.get('files_processed', 0)}")
                        print(f"  Rate: {phase_stats.get('rate_per_sec', 0):.1f} files/sec")
                        print(f"  Errors: {phase_stats.get('errors', 0)}")
                
                # Also show legacy format summary
                if legacy_file.exists():
                    legacy = json.loads(legacy_file.read_text())
                    if legacy.get("summary"):
                        s = legacy["summary"]
                        print(f"\n=== Legacy Summary ===")
                        for key, value in s.items():
                            if isinstance(value, float):
                                print(f"  {key}: {value:.1f}")
                            else:
                                print(f"  {key}: {value}")
                    if legacy.get("errors"):
                        print(f"\nErrors: {len(legacy['errors'])}")
                        for err in legacy["errors"][:3]:
                            print(f"  - {err}")
                            
            except Exception as e:
                print(f"Error reading output: {e}")
            sys.exit(0)
        
        if args.test:
            # Run synchronously for testing - no daemon, no duplicate check
            print(f"Running in TEST mode (synchronous, verbose)")
            print(f"  Database: {args.db}")
            print(f"  Vanilla: {args.vanilla_path or 'default'}")
            print(f"  Skip mods: {args.skip_mods}")
            print(f"  Playset file: {args.playset_file or 'all mods'}")
            logger = DaemonLogger(LOG_FILE, also_print=True)
            status = StatusWriter(STATUS_FILE)
            run_rebuild(
                args.db, args.force, logger, status, args.symbols_only,
                vanilla_path=args.vanilla_path,
                skip_mods=args.skip_mods,
                playset_file=args.playset_file
            )
            sys.exit(0)
        
        # Check for running instance using both PID check and exclusive lock
        if is_daemon_running():
            print("Daemon is already running (PID check). Use 'stop' first.")
            sys.exit(1)
        
        start_detached(args.db, args.force, args.symbols_only, playset_file=args.playset_file)
    
    elif args.command == "status":
        show_status()
    
    elif args.command == "stop":
        stop_daemon()
    
    elif args.command == "logs":
        show_logs(args.follow)
    
    elif args.command == "_run_daemon":
        # Internal: actually run the daemon
        # Try to acquire exclusive lock first
        if not acquire_exclusive_lock():
            # Another daemon has the lock - exit silently
            sys.exit(1)
        
        write_pid()
        logger = DaemonLogger(LOG_FILE)
        status = StatusWriter(STATUS_FILE)
        
        try:
            run_rebuild(args.db, args.force, logger, status, args.symbols_only, playset_file=args.playset_file)
        except Exception as e:
            logger.error(f"Daemon crashed: {e}")
            logger.error(traceback.format_exc())
        finally:
            cleanup_pid()


if __name__ == "__main__":
    main()

