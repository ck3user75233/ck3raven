#!/usr/bin/env python3
"""
Queue-based build daemon for CK3 Raven.

This daemon uses a work queue with:
- File-keyed work items (not path-based)
- Deterministic routing via ProcessingEnvelope
- Crash-safe leasing with automatic recovery
- O(n) complexity, not O(n*m)

Usage:
    python -m builder.queue_daemon start [--playset NAME]
    python -m builder.queue_daemon status
    python -m builder.queue_daemon stop
    python -m builder.queue_daemon run-once [--limit N]
    python -m builder.queue_daemon scan [--playset NAME]
"""

import argparse
import json
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Paths
DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"
DAEMON_DIR = Path.home() / ".ck3raven" / "queue_daemon"
PID_FILE = DAEMON_DIR / "queue_daemon.pid"
STATUS_FILE = DAEMON_DIR / "status.json"
LOG_FILE = DAEMON_DIR / "queue_daemon.log"

# Ensure daemon directory exists
DAEMON_DIR.mkdir(parents=True, exist_ok=True)


class Logger:
    """Simple file logger."""
    
    def __init__(self, log_path: Path, console: bool = True):
        self.log_path = log_path
        self.console = console
    
    def _log(self, level: str, msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if self.console:
            print(line)
    
    def info(self, msg: str):
        self._log("INFO", msg)
    
    def error(self, msg: str):
        self._log("ERROR", msg)
    
    def warning(self, msg: str):
        self._log("WARN", msg)


class StatusWriter:
    """Writes status to JSON for external monitoring."""
    
    def __init__(self, path: Path):
        self.path = path
        self._status = {
            "state": "initializing",
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "updated_at": None,
        }
    
    def update(self, **kwargs):
        self._status.update(kwargs)
        self._status["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._status, indent=2))
            tmp.replace(self.path)
        except Exception:
            pass
    
    def get(self) -> dict:
        return self._status.copy()


def get_connection() -> sqlite3.Connection:
    """Get database connection with proper settings."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def scan_for_changes(
    conn: sqlite3.Connection,
    logger: Logger,
    playset_name: Optional[str] = None,
    limit: Optional[int] = None,
) -> int:
    """
    Scan for files needing processing and queue work.
    
    Returns number of items queued.
    """
    from builder.change_detector import find_pending_work, find_pending_work_for_playset
    from builder.worker import queue_pending_work
    
    # Get playset to scan
    if playset_name:
        row = conn.execute(
            "SELECT playset_id FROM playsets WHERE name = ?",
            (playset_name,)
        ).fetchone()
        if not row:
            logger.error(f"Playset not found: {playset_name}")
            return 0
        playset_id = row["playset_id"]
    else:
        # Use active playset from manifest
        manifest_path = Path(__file__).parent.parent / "playsets" / "playset_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            active_name = manifest.get("active_playset")
            if active_name:
                row = conn.execute(
                    "SELECT playset_id FROM playsets WHERE name = ?",
                    (active_name,)
                ).fetchone()
                if row:
                    playset_id = row["playset_id"]
                else:
                    logger.warning(f"Active playset '{active_name}' not found in database")
                    playset_id = None
            else:
                playset_id = None
        else:
            playset_id = None
    
    queued = 0
    
    if playset_id is not None:
        logger.info(f"Scanning playset {playset_id}...")
        for pending in find_pending_work_for_playset(conn, playset_id, limit=limit):
            work_id = queue_pending_work(conn, pending)
            if work_id:
                logger.info(f"Queued: {pending.relpath} (mask={pending.processing_mask})")
                queued += 1
                if limit and queued >= limit:
                    return queued
    else:
        # Scan all content versions
        logger.info("Scanning all content versions...")
        for pending in find_pending_work(conn, limit=limit):
            work_id = queue_pending_work(conn, pending)
            if work_id:
                logger.info(f"Queued: {pending.relpath} (mask={pending.processing_mask})")
                queued += 1
                if limit and queued >= limit:
                    return queued
    
    return queued


def process_work_item(conn: sqlite3.Connection, work, logger: Logger) -> bool:
    """
    Process a single work item.
    
    Delegates to appropriate processing functions based on processing_mask.
    
    Returns True on success, False on error.
    """
    from builder.routing import ProcessingStage
    
    stages = ProcessingStage(work.processing_mask)
    file_id = work.file_id
    
    logger.info(f"Processing file_id={file_id}, stages={stages}")
    
    try:
        # Get file info
        row = conn.execute("""
            SELECT f.relpath, f.content_hash
            FROM files f
            WHERE f.file_id = ?
        """, (file_id,)).fetchone()
        
        if not row:
            logger.error(f"File not found: file_id={file_id}")
            return False
        
        relpath = row["relpath"]
        content_hash = row["content_hash"]
        
        rows_affected = 0
        
        # PARSE stage
        if ProcessingStage.PARSE in stages:
            rows_affected += _do_parse(conn, file_id, content_hash, relpath, logger)
        
        # SYMBOLS + REFS stages (combined in extract_and_store)
        if ProcessingStage.SYMBOLS in stages or ProcessingStage.REFS in stages:
            sym_count, ref_count = _do_symbols_and_refs(conn, file_id, content_hash, relpath, logger)
            rows_affected += sym_count + ref_count
        
        # LOCALIZATION stage
        if ProcessingStage.LOCALIZATION in stages:
            rows_affected += _do_localization(conn, file_id, relpath, logger)
        
        # LOOKUPS stage
        if ProcessingStage.LOOKUPS in stages:
            rows_affected += _do_lookups(conn, file_id, content_hash, logger)
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing file_id={file_id}: {e}")
        return False


def _do_parse(conn: sqlite3.Connection, file_id: int, content_hash: str, relpath: str, logger: Logger) -> int:
    """Parse file and store AST."""
    from ck3raven.parser import parse_source
    import json as _json
    
    # Get content
    row = conn.execute(
        "SELECT content_text FROM file_contents WHERE content_hash = ?",
        (content_hash,)
    ).fetchone()
    
    if not row or not row["content_text"]:
        return 0
    
    content = row["content_text"]
    
    # Check if already parsed
    exists = conn.execute(
        "SELECT 1 FROM asts WHERE content_hash = ?",
        (content_hash,)
    ).fetchone()
    
    if exists:
        return 0
    
    # Parse
    try:
        ast_result = parse_source(content, filename=relpath)
        ast_json = _json.dumps(ast_result.to_dict())
        
        # Get parser version
        parser_version_id = conn.execute(
            "SELECT parser_version_id FROM parser_versions ORDER BY parser_version_id DESC LIMIT 1"
        ).fetchone()[0]
        
        conn.execute("""
            INSERT INTO asts (content_hash, parser_version_id, ast_blob, ast_format, parse_ok, node_count)
            VALUES (?, ?, ?, 'json', 1, ?)
        """, (content_hash, parser_version_id, ast_json, ast_result.node_count))
        conn.commit()
        return 1
        
    except Exception as e:
        logger.warning(f"Parse error for {relpath}: {e}")
        return 0


def _do_symbols_and_refs(conn: sqlite3.Connection, file_id: int, content_hash: str, relpath: str, logger: Logger) -> tuple[int, int]:
    """Extract symbols and refs from AST using existing extract_and_store."""
    from ck3raven.db.symbols import extract_and_store
    import json as _json
    
    try:
        # Get AST
        row = conn.execute("""
            SELECT ast_id, ast_blob FROM asts WHERE content_hash = ? AND parse_ok = 1
        """, (content_hash,)).fetchone()
        
        if not row:
            logger.warning(f"No AST found for content_hash={content_hash[:16]}...")
            return 0, 0
        
        ast_id = row["ast_id"]
        ast_dict = _json.loads(row["ast_blob"])
        
        # Check if already extracted
        has_symbols = conn.execute(
            "SELECT 1 FROM symbols WHERE defining_file_id = ? LIMIT 1",
            (file_id,)
        ).fetchone()
        
        if has_symbols:
            return 0, 0  # Already done
        
        sym_count, ref_count = extract_and_store(
            conn, file_id, content_hash, ast_id, ast_dict, relpath
        )
        conn.commit()
        return sym_count, ref_count
        
    except Exception as e:
        logger.warning(f"Symbol/ref extraction error for file_id={file_id}: {e}")
        return 0, 0


def _do_localization(conn: sqlite3.Connection, file_id: int, relpath: str, logger: Logger) -> int:
    """Parse localization file."""
    from ck3raven.db.localization import parse_localization_for_file
    
    try:
        result = parse_localization_for_file(conn, file_id)
        return result.get("entries_parsed", 0)
    except Exception as e:
        logger.warning(f"Localization error for {relpath}: {e}")
        return 0


def _do_lookups(conn: sqlite3.Connection, file_id: int, content_hash: str, logger: Logger) -> int:
    """Extract lookup tables."""
    from ck3raven.db.lookups import extract_lookups_for_file
    
    try:
        result = extract_lookups_for_file(conn, file_id)
        return result.get("lookups_extracted", 0)
    except Exception as e:
        logger.warning(f"Lookup extraction error for file_id={file_id}: {e}")
        return 0


def run_worker(
    logger: Logger,
    status: StatusWriter,
    *,
    limit: Optional[int] = None,
    lease_seconds: int = 300,
) -> int:
    """
    Run worker loop processing queued items.
    
    Returns number of items processed.
    """
    from builder.worker import WorkerSession, get_queue_stats
    
    conn = get_connection()
    processed = 0
    
    try:
        with WorkerSession(conn, lease_seconds=lease_seconds) as worker:
            while True:
                # Update status
                stats = get_queue_stats(conn)
                status.update(
                    state="processing",
                    pending=stats["pending"],
                    processing=stats["processing"],
                    completed=stats["completed"],
                    failed=stats["failed"],
                )
                
                # Check limit
                if limit and processed >= limit:
                    break
                
                # Get next work item
                work = worker.claim_work()
                if work is None:
                    logger.info("Queue empty")
                    break
                
                logger.info(f"Claimed work_id={work.work_id}, file_id={work.file_id}")
                
                # Process
                success = process_work_item(conn, work, logger)
                
                if success:
                    worker.complete_work(work.work_id)
                    logger.info(f"Completed work_id={work.work_id}")
                else:
                    worker.error_work(work.work_id, "Processing failed")
                    logger.error(f"Failed work_id={work.work_id}")
                
                processed += 1
        
        status.update(state="idle")
        return processed
        
    finally:
        conn.close()


def cmd_start(args):
    """Start daemon in background."""
    logger = Logger(LOG_FILE)
    status = StatusWriter(STATUS_FILE)
    
    # Check if already running
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        # Check if process exists (Windows-compatible)
        try:
            os.kill(pid, 0)
            logger.error(f"Daemon already running (PID {pid})")
            return 1
        except OSError:
            pass  # Process doesn't exist, clean up
    
    # Write PID
    PID_FILE.write_text(str(os.getpid()))
    
    logger.info("Queue daemon starting...")
    status.update(state="starting")
    
    # Signal handler for graceful shutdown
    running = [True]
    def handle_signal(signum, frame):
        running[0] = False
        logger.info("Shutdown signal received")
    
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    try:
        conn = get_connection()
        
        while running[0]:
            # Scan for changes
            logger.info("Scanning for changes...")
            queued = scan_for_changes(conn, logger, playset_name=args.playset)
            logger.info(f"Queued {queued} items")
            
            # Process queue
            processed = run_worker(logger, status)
            logger.info(f"Processed {processed} items")
            
            # If nothing happened, wait before next cycle
            if queued == 0 and processed == 0:
                status.update(state="idle")
                for _ in range(30):  # 30 second wait, checking for shutdown
                    if not running[0]:
                        break
                    time.sleep(1)
        
        status.update(state="stopped")
        logger.info("Daemon stopped")
        return 0
        
    finally:
        PID_FILE.unlink(missing_ok=True)


def cmd_status(args):
    """Show daemon status."""
    from builder.worker import get_queue_stats
    
    # Check PID file
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, 0)
            print(f"Daemon running (PID {pid})")
        except OSError:
            print("Daemon not running (stale PID file)")
    else:
        print("Daemon not running")
    
    # Queue stats
    try:
        conn = get_connection()
        stats = get_queue_stats(conn)
        conn.close()
        
        print(f"\nQueue Status:")
        print(f"  Pending:    {stats['pending']}")
        print(f"  Processing: {stats['processing']}")
        print(f"  Completed:  {stats['completed']}")
        print(f"  Failed:     {stats['failed']}")
        print(f"  Total:      {stats['total']}")
        
    except Exception as e:
        print(f"Error reading queue: {e}")
    
    # Status file
    if STATUS_FILE.exists():
        try:
            status = json.loads(STATUS_FILE.read_text())
            print(f"\nLast Update: {status.get('updated_at', 'unknown')}")
            print(f"State: {status.get('state', 'unknown')}")
        except Exception:
            pass
    
    return 0


def cmd_stop(args):
    """Stop running daemon."""
    if not PID_FILE.exists():
        print("Daemon not running")
        return 0
    
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to PID {pid}")
        
        # Wait for shutdown
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except OSError:
                print("Daemon stopped")
                PID_FILE.unlink(missing_ok=True)
                return 0
        
        print("Daemon did not stop gracefully, sending SIGKILL")
        os.kill(pid, signal.SIGKILL)
        PID_FILE.unlink(missing_ok=True)
        return 0
        
    except OSError as e:
        print(f"Error stopping daemon: {e}")
        PID_FILE.unlink(missing_ok=True)
        return 1


def cmd_run_once(args):
    """Run one processing cycle."""
    logger = Logger(LOG_FILE, console=True)
    status = StatusWriter(STATUS_FILE)
    
    conn = get_connection()
    
    # Scan
    logger.info("Scanning for changes...")
    queued = scan_for_changes(conn, logger, limit=args.limit)
    logger.info(f"Queued {queued} items")
    
    conn.close()
    
    # Process
    processed = run_worker(logger, status, limit=args.limit)
    logger.info(f"Processed {processed} items")
    
    return 0


def cmd_scan(args):
    """Scan for changes and queue work (no processing)."""
    logger = Logger(LOG_FILE, console=True)
    
    conn = get_connection()
    queued = scan_for_changes(conn, logger, playset_name=args.playset, limit=args.limit)
    conn.close()
    
    print(f"Queued {queued} items")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Queue-based build daemon")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # start
    p_start = subparsers.add_parser("start", help="Start daemon")
    p_start.add_argument("--playset", help="Playset name to watch")
    p_start.set_defaults(func=cmd_start)
    
    # status
    p_status = subparsers.add_parser("status", help="Show status")
    p_status.set_defaults(func=cmd_status)
    
    # stop
    p_stop = subparsers.add_parser("stop", help="Stop daemon")
    p_stop.set_defaults(func=cmd_stop)
    
    # run-once
    p_once = subparsers.add_parser("run-once", help="Run one cycle")
    p_once.add_argument("--limit", type=int, help="Max items to process")
    p_once.set_defaults(func=cmd_run_once)
    
    # scan
    p_scan = subparsers.add_parser("scan", help="Scan and queue only")
    p_scan.add_argument("--playset", help="Playset name")
    p_scan.add_argument("--limit", type=int, help="Max items to queue")
    p_scan.set_defaults(func=cmd_scan)
    
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
