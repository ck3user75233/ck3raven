"""
QBuilder Worker — Canonical Phase 1

FIFO lease-based build queue processor with fingerprint binding.

Key behaviors:
- Claims by monotonic build_id (FIFO)
- Resolves file paths via canonical joins (file_id → files → content_versions)
- Executes complete envelope for each file
- Never skips work based on artifact existence
- Writes derived artifacts with fingerprint binding
- **AUTOMATIC RECOVERY**: Reclaims expired leases and marks repeatedly-failing items as errors

No parallel constructs:
- No relpath/cvid in build_queue (derived via joins)
- No steps_completed workflow engine
- No needs_* inference
"""

import json
import os
import signal
import sqlite3
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from qbuilder.lookup_extractors import LOOKUP_EXECUTORS
from pathlib import Path
from typing import Callable, Optional

# Lease duration in seconds
BUILD_LEASE_SECONDS = 180  # 3 minutes

# Maximum retry attempts before marking as permanent error
MAX_RETRIES = 3

# Maximum times a single item can be reclaimed (lease expired without completion)
# After this many reclaims, the item is marked as error even if retry_count < MAX_RETRIES
MAX_RECLAIMS = 3

# Timeout for processing a single item (seconds)
ITEM_TIMEOUT_SECONDS = 120  # 2 minutes


def _safe_print(msg: str) -> None:
    """Print a message safely, handling Unicode encoding errors on Windows.
    
    Windows console (cp1252) cannot display many Unicode characters.
    This replaces non-encodable characters with '?' to avoid crashes.
    """
    try:
        print(msg)
    except (UnicodeEncodeError, OSError):
        # UnicodeEncodeError: Windows console can't display Unicode
        # OSError: stdout is DEVNULL/invalid (daemonized process)
        try:
            encoded = msg.encode(sys.stdout.encoding or 'utf-8', errors='replace')
            print(encoded.decode(sys.stdout.encoding or 'utf-8', errors='replace'))
        except OSError:
            pass  # Stdout completely unavailable, silently skip


def _read_ck3_text(path: Path) -> str:
    """Read a CK3 text file with encoding fallback.
    
    CK3 files are mostly UTF-8 (with BOM), but some vanilla files
    (especially history/provinces) use latin-1 or Windows-1252.
    
    Try UTF-8-sig first, then fall back to latin-1.
    """
    try:
        return path.read_text(encoding='utf-8-sig')
    except UnicodeDecodeError:
        # Fallback to latin-1 which accepts any byte sequence
        return path.read_text(encoding='latin-1')


@dataclass
class BuildContext:
    """Context for envelope execution, derived via canonical joins."""
    build_id: int
    file_id: int
    cvid: int
    relpath: str
    envelope: str
    abspath: Path
    # Fingerprint this work item is bound to
    work_mtime: float
    work_size: int
    work_hash: Optional[str]


class EnvelopeExecutor:
    """
    Executes envelope steps for a build work item.
    
    Each envelope defines steps to run in sequence.
    All steps execute unconditionally (no artifact-based skipping).
    """
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        
        # Load routing table for envelope definitions
        self._load_envelope_steps()
    
    def _load_envelope_steps(self) -> None:
        """Load envelope step definitions from routing table."""
        routing_path = Path(__file__).parent / "routing_table.json"
        if routing_path.exists():
            with open(routing_path, 'r', encoding='utf-8') as f:
                routing = json.load(f)
            self.envelope_steps = routing.get('envelope_steps', {})
        else:
            self.envelope_steps = {
                'E_SCRIPT': ['parse', 'extract_symbols', 'extract_refs'],
                'E_LOC': ['parse_loc', 'extract_loc_entries'],
                'E_GUI': ['parse'],
                'E_SKIP': [],
            }
    
    def execute(self, ctx: BuildContext) -> list[str]:
        """
        Execute all steps in envelope for this file.
        
        Returns list of completed step names.
        """
        steps = self.envelope_steps.get(ctx.envelope, [])
        completed = []
        
        for step_name in steps:
            self._execute_step(ctx, step_name)
            completed.append(step_name)
        
        return completed
    
    def _execute_step(self, ctx: BuildContext, step_name: str) -> None:
        """Execute a single step."""
        step_fn = getattr(self, f'_step_{step_name}', None)
        if step_fn:
            step_fn(ctx)
        else:
            # Unknown step - log but don't fail
            pass
    
    # =========================================================================
    # Step implementations
    # =========================================================================
    
    def _step_parse(self, ctx: BuildContext) -> None:
        """
        Parse PDX script file into AST with fingerprint binding.
        
        CRITICAL: Uses canonical parser runtime (subprocess + timeout).
        This prevents pathological files from blocking the queue indefinitely.
        On timeout, ParseTimeoutError is raised and the file is marked as error.
        
        PERFORMANCE: If QBUILDER_PERSISTENT_PARSE=1, uses persistent worker pool
        which amortizes subprocess spawn + import overhead across many files.
        """
        from src.ck3raven.parser.parse_pool import is_pool_enabled, get_pool
        from src.ck3raven.parser.runtime import (
            parse_file as runtime_parse_file,
            ParseTimeoutError,
            ParseSubprocessError,
            DEFAULT_PARSE_TIMEOUT,
        )
        
        if not ctx.abspath.exists():
            raise FileNotFoundError(f"File not found: {ctx.abspath}")
        
        # Check if AST already exists for this content_hash (deduplication)
        # The asts table has UNIQUE(content_hash, parser_version_id) constraint
        # so if content is identical to a previously-parsed file, skip re-parsing
        existing = self.conn.execute("""
            SELECT ast_id FROM asts 
            WHERE content_hash = ? AND parser_version_id = 1
        """, (ctx.work_hash or '',)).fetchone()
        
        if existing:
            # AST already exists for identical content - skip parsing
            # Symbol/ref extraction will use the existing AST
            return
        
        # Choose parse method based on environment flag
        if is_pool_enabled():
            # Persistent worker pool - amortizes spawn overhead
            pool = get_pool()
            result = pool.parse_file(ctx.abspath, timeout_ms=DEFAULT_PARSE_TIMEOUT * 1000)
        else:
            # Legacy subprocess-per-file (default until pool is proven)
            result = runtime_parse_file(ctx.abspath, timeout=DEFAULT_PARSE_TIMEOUT)
        
        if not result.success:
            # Parse failed (syntax error, etc.) - raise so it's recorded as error
            error_type = result.error_type or "ParseError"
            error_msg = result.error or "Unknown parse error"
            raise RuntimeError(f"{error_type}: {error_msg}")
        
        # Store AST - content deduplication means one AST per unique content_hash
        # Use INSERT OR IGNORE because UNIQUE(content_hash, parser_version_id) constraint
        # means identical content from different files shares one AST row.
        # The file_id column is vestigial (records which file triggered the parse)
        # and is NOT part of AST identity - see docs/CANONICAL_ARCHITECTURE.md Section 13.
        self.conn.execute("""
            INSERT OR IGNORE INTO asts (file_id, content_hash, parser_version_id, ast_blob, 
                              ast_format, parse_ok, node_count, created_at)
            VALUES (?, ?, 1, ?, 'json', 1, ?, datetime('now'))
        """, (ctx.file_id, ctx.work_hash or '', result.ast_json, result.node_count))
    
    def _step_extract_symbols(self, ctx: BuildContext) -> None:
        """Extract symbols from AST with content-keyed storage.
        
        FLAG-DAY MIGRATION: Symbols bind to ast_id ONLY.
        File association derived via Golden Join: symbols → asts → files (via content_hash).
        """
        try:
            from src.ck3raven.db.symbols import extract_symbols_from_ast
            from src.ck3raven.db.schema import BuilderSession
        except ImportError:
            return
        
        # Get AST by content_hash (may be from different file_id due to deduplication)
        row = self.conn.execute(
            "SELECT ast_id, ast_blob FROM asts WHERE content_hash = ? AND parser_version_id = 1",
            (ctx.work_hash or '',)
        ).fetchone()
        
        if not row:
            return
        
        ast_id, ast_blob = row
        ast_data = json.loads(ast_blob)
        
        # Check if symbols already extracted for this AST (content deduplication)
        existing = self.conn.execute(
            "SELECT 1 FROM symbols WHERE ast_id = ? LIMIT 1", (ast_id,)
        ).fetchone()
        
        if existing:
            # Symbols already extracted for this AST - skip (content dedup)
            return
        
        # Read source text for node span extraction and hashing
        source_text = ""
        if ctx.abspath.exists():
            source_text = _read_ck3_text(ctx.abspath)
        
        # extract_symbols_from_ast returns iterator of ExtractedSymbol dataclass
        # Signature: (ast_dict, relpath, content_hash, source_text) -> Iterator[ExtractedSymbol]
        symbols = list(extract_symbols_from_ast(ast_data, ctx.relpath, ctx.work_hash or '', source_text))
        
        # Use BuilderSession to allow writes to protected symbols table
        with BuilderSession(self.conn, f"extract_symbols:{ast_id}"):
            # Insert symbols bound to ast_id ONLY (content identity)
            for sym in symbols:
                self.conn.execute("""
                    INSERT INTO symbols (ast_id, name, symbol_type, 
                                         line_number, column_number,
                                         node_hash_norm, node_start_offset, node_end_offset)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (ast_id, sym.name, sym.kind, sym.line, sym.column,
                      sym.node_hash_norm, sym.node_start_offset, sym.node_end_offset))
            self.conn.commit()
    
    def _step_extract_refs(self, ctx: BuildContext) -> None:
        """Extract references from AST with content-keyed storage.
        
        FLAG-DAY MIGRATION: Refs bind to ast_id ONLY.
        File association derived via Golden Join: refs → asts → files (via content_hash).
        """
        try:
            from src.ck3raven.db.symbols import extract_refs_from_ast
            from src.ck3raven.db.schema import BuilderSession
        except ImportError:
            return
        
        # Get AST by content_hash (may be from different file_id due to deduplication)
        row = self.conn.execute(
            "SELECT ast_id, ast_blob FROM asts WHERE content_hash = ? AND parser_version_id = 1",
            (ctx.work_hash or '',)
        ).fetchone()
        
        if not row:
            return
        
        ast_id, ast_blob = row
        ast_data = json.loads(ast_blob)
        
        # Check if refs already extracted for this AST (content deduplication)
        existing = self.conn.execute(
            "SELECT 1 FROM refs WHERE ast_id = ? LIMIT 1", (ast_id,)
        ).fetchone()
        
        if existing:
            # Refs already extracted for this AST - skip (content dedup)
            return
        
        # extract_refs_from_ast returns iterator of ExtractedRef dataclass
        # Signature: (ast_dict, relpath, content_hash) -> Iterator[ExtractedRef]
        refs = list(extract_refs_from_ast(ast_data, ctx.relpath, ctx.work_hash or ''))
        
        # Use BuilderSession to allow writes to protected refs table
        with BuilderSession(self.conn, f"extract_refs:{ast_id}"):
            # Insert refs bound to ast_id ONLY (content identity)
            for ref in refs:
                self.conn.execute("""
                    INSERT INTO refs (ast_id, name, ref_type, 
                                      line_number, column_number)
                    VALUES (?, ?, ?, ?, ?)
                """, (ast_id, ref.name, ref.kind, ref.line, ref.column))
            self.conn.commit()
    
    def _step_parse_loc(self, ctx: BuildContext) -> None:
        """Parse YAML localization file."""
        # Stub - implement localization parsing
        pass
    
    def _step_extract_loc_entries(self, ctx: BuildContext) -> None:
        """Extract localization entries."""
        # Stub - implement loc extraction
        pass
    
    # =========================================================================
    # Lookup Extractors (specialized, no AST)
    # =========================================================================
    
    def _step_extract_characters(self, ctx: BuildContext) -> None:
        """Extract characters to character_lookup table."""
        content = _read_ck3_text(ctx.abspath)
        LOOKUP_EXECUTORS['extract_characters'](content, ctx.file_id, ctx.cvid, self.conn)
        self.conn.commit()
    
    def _step_extract_provinces(self, ctx: BuildContext) -> None:
        """Extract provinces to province_lookup table."""
        content = _read_ck3_text(ctx.abspath)
        LOOKUP_EXECUTORS['extract_provinces'](content, ctx.file_id, ctx.cvid, self.conn)
        self.conn.commit()
    
    def _step_extract_names(self, ctx: BuildContext) -> None:
        """Extract names to name_lookup table."""
        content = _read_ck3_text(ctx.abspath)
        LOOKUP_EXECUTORS['extract_names'](content, ctx.file_id, ctx.cvid, self.conn)
        self.conn.commit()
    
    def _step_extract_holy_sites(self, ctx: BuildContext) -> None:
        """Extract holy sites to holy_site_lookup table."""
        content = _read_ck3_text(ctx.abspath)
        LOOKUP_EXECUTORS['extract_holy_sites'](content, ctx.file_id, ctx.cvid, self.conn)
        self.conn.commit()
    
    def _step_extract_dynasties(self, ctx: BuildContext) -> None:
        """Extract dynasties to dynasty_lookup table."""
        content = _read_ck3_text(ctx.abspath)
        LOOKUP_EXECUTORS['extract_dynasties'](content, ctx.file_id, ctx.cvid, self.conn)
        self.conn.commit()


class BuildWorker:
    """
    FIFO lease-based build queue worker.
    
    Claims work by monotonic build_id (oldest first).
    Resolves paths via canonical joins.
    Automatically recovers from crashed workers via lease expiration.
    """
    
    def __init__(self, conn: sqlite3.Connection, worker_id: Optional[str] = None):
        self.conn = conn
        self.worker_id = worker_id or f"worker-{os.getpid()}"
        self.executor = EnvelopeExecutor(conn)
    
    def recover_expired_leases(self) -> int:
        """
        Check for items with expired leases and either reset or mark as error.
        
        Items that have been reclaimed too many times (MAX_RECLAIMS) are marked
        as permanent errors to prevent infinite loops on problematic files.
        
        Returns count of items recovered.
        """
        now = time.time()
        
        # First, mark items that have been reclaimed too many times as errors
        cursor = self.conn.execute("""
            UPDATE build_queue
            SET status = 'error',
                error_message = 'Exceeded max reclaims (' || reclaim_count || ') - likely causing worker crashes',
                lease_expires_at = NULL,
                lease_holder = NULL
            WHERE status = 'processing'
              AND lease_expires_at < ?
              AND reclaim_count >= ?
        """, (now, MAX_RECLAIMS))
        
        marked_as_error = cursor.rowcount
        
        # Reset remaining expired items to pending and increment reclaim_count
        cursor = self.conn.execute("""
            UPDATE build_queue
            SET status = 'pending',
                reclaim_count = COALESCE(reclaim_count, 0) + 1,
                lease_expires_at = NULL,
                lease_holder = NULL
            WHERE status = 'processing'
              AND lease_expires_at < ?
        """, (now,))
        
        recovered = cursor.rowcount
        self.conn.commit()
        
        if marked_as_error > 0:
            _safe_print(f"[Recovery] Marked {marked_as_error} repeatedly-failing items as errors")
        if recovered > 0:
            _safe_print(f"[Recovery] Reset {recovered} expired leases to pending")
        
        return recovered + marked_as_error
    
    def claim_work(self) -> Optional[dict]:
        """
        Claim highest-priority pending work item.
        
        Order: priority DESC (flash=1 first), then build_id ASC (FIFO within priority).
        Returns work item with all context resolved via joins.
        
        Automatically recovers expired leases before claiming.
        """
        now = time.time()
        
        # First, recover any expired leases
        self.recover_expired_leases()
        
        lease_until = now + BUILD_LEASE_SECONDS
        
        # Claim pending item (expired items already reset to pending above)
        cursor = self.conn.execute("""
            UPDATE build_queue
            SET status = 'processing',
                lease_expires_at = ?,
                lease_holder = ?,
                started_at = COALESCE(started_at, ?)
            WHERE build_id = (
                SELECT build_id FROM build_queue
                WHERE status = 'pending'
                ORDER BY priority DESC, build_id ASC
                LIMIT 1
            )
            RETURNING build_id, file_id, envelope, priority,
                      work_file_mtime, work_file_size, work_file_hash
        """, (lease_until, self.worker_id, now))
        
        row = cursor.fetchone()
        self.conn.commit()
        
        if not row:
            return None
        
        build_id, file_id, envelope, priority, work_mtime, work_size, work_hash = row
        
        # Resolve file context via canonical join
        file_row = self.conn.execute("""
            SELECT f.content_version_id, f.relpath, mp.source_path
            FROM files f
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE f.file_id = ?
        """, (file_id,)).fetchone()
        
        if not file_row:
            self._mark_error(build_id, f"File not found: file_id={file_id}", None)
            return None
        
        cvid, relpath, source_path = file_row
        
        # source_path is always populated (vanilla and mods both have it on mod_packages)
        root_path = source_path
        
        if not root_path:
            self._mark_error(build_id, f"Cannot resolve root for cvid={cvid}", None)
            return None
        
        return {
            'build_id': build_id,
            'file_id': file_id,
            'cvid': cvid,
            'relpath': relpath,
            'envelope': envelope,
            'abspath': Path(root_path) / relpath,
            'work_mtime': work_mtime,
            'work_size': work_size,
            'work_hash': work_hash,
        }
    
    def _get_vanilla_path(self) -> Optional[str]:
        """Get vanilla path from active playset."""
        manifest_path = Path.home() / ".ck3raven" / "playsets" / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path, 'r', encoding='utf-8-sig') as f:
                manifest = json.load(f)
            active = manifest.get('active_playset')
            if active:
                playset_path = manifest_path.parent / active
                if playset_path.exists():
                    with open(playset_path, 'r', encoding='utf-8-sig') as f:
                        playset = json.load(f)
                    return playset.get('vanilla_path')
        return None
    
    def process_item(self, item: dict) -> dict:
        """
        Process a build queue item.
        
        Returns result dict with status.
        """
        build_id = item['build_id']
        
        ctx = BuildContext(
            build_id=build_id,
            file_id=item['file_id'],
            cvid=item['cvid'],
            relpath=item['relpath'],
            envelope=item['envelope'],
            abspath=item['abspath'],
            work_mtime=item['work_mtime'],
            work_size=item['work_size'],
            work_hash=item['work_hash'],
        )
        
        try:
            completed_steps = self.executor.execute(ctx)
            
            now = time.time()
            self.conn.execute("""
                UPDATE build_queue
                SET status = 'completed', completed_at = ?
                WHERE build_id = ?
            """, (now, build_id))
            self.conn.commit()
            
            return {'build_id': build_id, 'status': 'completed', 'steps': completed_steps}
        
        except Exception as e:
            from src.ck3raven.parser.runtime import ParseTimeoutError
            
            error_msg = f"{type(e).__name__}: {str(e)}"
            
            # Timeouts are permanent failures - no retry
            if isinstance(e, ParseTimeoutError):
                self._mark_error(build_id, error_msg, 'parse', permanent=True)
            else:
                self._mark_error(build_id, error_msg, None)
            
            return {'build_id': build_id, 'status': 'error', 'error': error_msg}
    
    def _mark_error(self, build_id: int, message: str, step: Optional[str], permanent: bool = False) -> None:
        """
        Mark work item as error.
        
        Args:
            build_id: The build queue item ID
            message: Error message
            step: The step that failed (optional)
            permanent: If True, mark as error immediately (no retry)
        """
        retry = self.conn.execute(
            "SELECT retry_count FROM build_queue WHERE build_id = ?",
            (build_id,)
        ).fetchone()
        
        retry_count = (retry[0] if retry else 0) + 1
        
        # Permanent errors (like timeouts) skip retry logic
        if permanent:
            status = 'error'
        else:
            status = 'error' if retry_count >= MAX_RETRIES else 'pending'
        
        self.conn.execute("""
            UPDATE build_queue
            SET status = ?, retry_count = ?, error_message = ?, error_step = ?,
                lease_expires_at = NULL, lease_holder = NULL
            WHERE build_id = ?
        """, (status, retry_count, message, step, build_id))
        self.conn.commit()


def run_build_worker(
    conn: sqlite3.Connection, 
    max_items: Optional[int] = None,
    logger: Optional["QBuilderLogger"] = None,
    continuous: bool = True,  # DEFAULT: daemon mode - never exit on empty queue
    poll_interval: float = 5.0,
    shutdown_event: Optional[threading.Event] = None,
    run_activity: Optional[object] = None,  # RunActivity from ipc_server (thread-safe)
) -> dict:
    """
    Run build worker as a continuous daemon.
    
    CRASH-PROOF DESIGN:
    - Commits after every item (success or error)
    - Catches all exceptions at top level (logs + continues)
    - Polls indefinitely when queue empty (no arbitrary timeouts)
    - Uses file-based logging (no stdout buffer blocking)
    
    Args:
        conn: Database connection
        max_items: Max items to process (execution throttle only, rarely used)
        logger: Optional JSONL logger for structured logging
        continuous: If True (default), keep polling forever. Only False for testing.
        poll_interval: Seconds between polls when queue empty
        shutdown_event: If set, check this event to trigger graceful shutdown
    
    Returns summary.
    """
    worker = BuildWorker(conn)
    
    items_processed = 0
    completed = 0
    errors = 0
    consecutive_idle_polls = 0
    
    if logger:
        logger.log_event("worker_start", {"continuous": continuous, "max_items": max_items, "pid": os.getpid()})
    
    _safe_print(f"[Worker] Starting (continuous={continuous}, max_items={max_items})")
    
    while True:
        try:
            # Check for shutdown signal
            if shutdown_event and shutdown_event.is_set():
                exit_reason = "shutdown signal received"
                if logger:
                    logger.log_event("worker_exit", {"reason": exit_reason, "processed": items_processed})
                _safe_print(f"[Worker] Shutting down ({items_processed} processed)")
                break
            
            # Check max_items limit (rare - mainly for testing)
            if max_items and items_processed >= max_items:
                exit_reason = f"max_items limit reached ({max_items})"
                if logger:
                    logger.log_event("worker_exit", {"reason": exit_reason, "processed": items_processed})
                _safe_print(f"[Worker] Exiting: {exit_reason}")
                break
            
            item = worker.claim_work()
            
            if not item:
                consecutive_idle_polls += 1
                
                # Signal idle state on first idle poll
                if consecutive_idle_polls == 1 and run_activity:
                    run_activity.set_idle()
                
                if not continuous:
                    # Non-continuous mode: exit immediately when queue empty
                    exit_reason = "queue empty (non-continuous mode)"
                    if logger:
                        logger.log_event("worker_exit", {"reason": exit_reason, "processed": items_processed})
                    _safe_print(f"[Worker] Exiting: {exit_reason}")
                    break
                
                # Continuous mode: poll forever (this is a daemon)
                # Log status every ~1 minute (12 polls at 5s interval)
                if consecutive_idle_polls % 12 == 1:
                    if logger:
                        logger.log_event("worker_idle", {"polls": consecutive_idle_polls, "processed": items_processed})
                    _safe_print(f"[Worker] Waiting for work... ({items_processed} processed, idle for {consecutive_idle_polls * poll_interval:.0f}s)")
                
                time.sleep(poll_interval)
                continue
            
            # Reset idle counter when we get work
            consecutive_idle_polls = 0
            if run_activity:
                run_activity.set_state("building")
            
            relpath = item['relpath']
            envelope = item['envelope']
            file_id = item['file_id']
            
            _safe_print(f"Building: {relpath} [{envelope}]")
            
            # Log item claimed
            if logger:
                steps = worker.executor.envelope_steps.get(envelope, [])
                logger.item_claimed(file_id, relpath, envelope, tuple(steps))
            
            result = worker.process_item(item)
            
            items_processed += 1
            if result['status'] == 'completed':
                completed += 1
                if logger:
                    logger.item_complete(file_id, relpath)
            else:
                errors += 1
                err_msg = result.get('error', 'unknown')
                _safe_print(f"  Error: {err_msg}")
                if logger:
                    logger.item_error(file_id, relpath, err_msg, result.get('step'))
            
            # Update RunActivity tracker (thread-safe, visible via IPC)
            if run_activity:
                run_activity.record_item(result['status'])
            
            # Periodic progress logging (every 100 items)
            if items_processed % 100 == 0:
                if logger:
                    logger.log_event("worker_progress", {
                        "processed": items_processed,
                        "completed": completed,
                        "errors": errors,
                    })
                _safe_print(f"[Worker] Progress: {items_processed} processed, {completed} completed, {errors} errors")
        
        except KeyboardInterrupt:
            # Clean shutdown on Ctrl+C
            exit_reason = "keyboard interrupt"
            if logger:
                logger.log_event("worker_exit", {"reason": exit_reason, "processed": items_processed})
            _safe_print(f"\n[Worker] Stopped by user ({items_processed} processed)")
            break
        
        except Exception as e:
            # CRASH-PROOF: Log error but continue processing
            # This catches database errors, unexpected exceptions, etc.
            error_msg = f"{type(e).__name__}: {str(e)}"
            if logger:
                logger.log_event("worker_crash_recovered", {
                    "error": error_msg,
                    "traceback": traceback.format_exc(),
                    "processed": items_processed,
                })
            _safe_print(f"[Worker] RECOVERED FROM CRASH: {error_msg}")
            traceback.print_exc()
            
            # Brief backoff before retrying
            time.sleep(2.0)
    
    return {
        'items_processed': items_processed,
        'completed': completed,
        'errors': errors,
    }
