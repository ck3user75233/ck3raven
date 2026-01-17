"""
QBuilder CLI — Canonical Phase 1

Commands:
    daemon    Start the single-writer daemon (IPC server + build worker)
    init      Initialize QBuilder schema
    discover  Enqueue discovery tasks and run discovery workers
    build     Run build workers on pending items
    run       Run complete pipeline (discover + build)
    status    Show queue status
    reset     Reset queues for fresh build

SINGLE-WRITER ARCHITECTURE (January 2026):
    The `daemon` command is the ONLY process that writes to the database.
    MCP servers are read-only and communicate with the daemon via IPC.
    See docs/SINGLE_WRITER_ARCHITECTURE.md for details.
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

from .schema import init_qbuilder_schema, reset_qbuilder_tables, get_queue_counts
from ck3raven.db.schema import BuilderSession, init_database, get_schema_version, DATABASE_VERSION
from .discovery import enqueue_playset_roots, run_discovery
from .worker import run_build_worker


def get_db_path() -> Path:
    """Get database path."""
    return Path.home() / '.ck3raven' / 'ck3raven.db'


def get_playsets_dir() -> Path:
    """Get playsets directory."""
    return Path(__file__).parent.parent / 'playsets'


def get_playset_manifest_path() -> Path:
    """Get active playset manifest path."""
    return get_playsets_dir() / 'playset_manifest.json'


def get_active_playset_file() -> Optional[Path]:
    """Get the active playset JSON file path."""
    manifest_path = get_playset_manifest_path()
    if not manifest_path.exists():
        return None
    
    with open(manifest_path, 'r', encoding='utf-8-sig') as f:
        manifest = json.load(f)
    
    active_file = manifest.get('active')
    if not active_file:
        return None
    
    return get_playsets_dir() / active_file


def get_connection(auto_init: bool = True) -> sqlite3.Connection:
    """
    Get database connection, auto-initializing schema if needed.
    
    Args:
        auto_init: If True, create database and schema if missing
    
    Returns:
        Database connection with row_factory set
    """
    db_path = get_db_path()
    
    # Check if database exists
    db_exists = db_path.exists()
    
    if not db_exists:
        if not auto_init:
            print(f"Error: Database not found at {db_path}")
            sys.exit(1)
        
        # Create directory if needed
        db_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Creating database at {db_path}")
    
    # Connect
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Check if schema exists and is current version
    if auto_init:
        schema_version = get_schema_version(conn)
        
        if schema_version is None:
            # No schema at all - initialize
            print("Initializing database schema...")
            conn = init_database(db_path, force=False)
            conn.row_factory = sqlite3.Row
            print(f"[OK] Database initialized (schema v{DATABASE_VERSION})")
        elif schema_version < DATABASE_VERSION:
            # Schema is outdated - warn but don't force upgrade
            print(f"Warning: Database schema v{schema_version} is outdated (current: v{DATABASE_VERSION})")
            print("  Run with --force to reset database")
    
    return conn


def cmd_daemon(args: argparse.Namespace) -> int:
    """
    Start the single-writer daemon.
    
    This is the ONLY process that writes to the database.
    It runs both the IPC server (for client requests) and the build worker.
    
    The daemon:
    1. Acquires the writer lock (fails if another daemon running)
    2. Opens database in read-write mode
    3. Starts IPC server for client requests
    4. Runs build worker loop
    """
    import uuid
    import signal
    
    from .writer_lock import WriterLock, WriterLockError
    from .ipc_server import DaemonIPCServer, get_ipc_port
    from .logging import QBuilderLogger
    
    db_path = get_db_path()
    run_id = f"daemon-{uuid.uuid4().hex[:8]}"
    logger = QBuilderLogger(run_id=run_id)
    
    # Fresh build mode
    if args.fresh:
        print("Fresh build mode: will reset all data")
    
    # Acquire writer lock
    print(f"Acquiring writer lock for {db_path}...")
    lock = WriterLock(db_path)
    
    if not lock.acquire():
        holder_info = lock.get_holder_info()
        if holder_info:
            print(f"[ERROR] Another daemon is already running (PID {holder_info.pid})")
        else:
            print("[ERROR] Could not acquire writer lock")
        return 1
    
    print(f"[OK] Writer lock acquired (PID {__import__('os').getpid()})")
    
    try:
        # Open database in read-write mode
        conn = get_connection()
        init_qbuilder_schema(conn)
        
        # Fresh reset if requested
        if args.fresh:
            print("Resetting all data for fresh build...")
            with BuilderSession(conn, "daemon_fresh_reset"):
                for table in ['asts', 'symbols', 'refs', 'localization_entries', 
                              'trait_lookups', 'event_lookups', 'decision_lookups']:
                    try:
                        conn.execute(f"DELETE FROM {table}")
                    except sqlite3.OperationalError:
                        pass
                conn.execute("DELETE FROM files")
                conn.execute("DELETE FROM content_versions")
                conn.execute("DELETE FROM mod_packages")
                conn.commit()
            reset_qbuilder_tables(conn)
            print("[OK] Data reset complete")
        
        # Start IPC server
        port = get_ipc_port()
        ipc_server = DaemonIPCServer(conn, port=port)
        ipc_server.start()
        print(f"[OK] IPC server listening on port {port}")
        
        # Handle shutdown signals
        shutdown_requested = False
        
        def handle_signal(signum, frame):
            nonlocal shutdown_requested
            print(f"\nReceived signal {signum}, shutting down...")
            shutdown_requested = True
        
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
        
        # Log startup
        counts = get_queue_counts(conn)
        pending = counts.get('build', {}).get('pending', 0)
        print(f"\n=== Daemon Started ===")
        print(f"  run_id: {run_id}")
        print(f"  db: {db_path}")
        print(f"  ipc_port: {port}")
        print(f"  pending: {pending}")
        print(f"  poll_interval: {args.poll_interval}s")
        print(f"  log: {logger.log_file}")
        print(f"\nPress Ctrl+C to stop\n")
        
        logger.run_start(total_items=pending)
        start_time = time.time()
        
        # Run build worker loop
        result = run_build_worker(
            conn,
            max_items=args.max_items,
            logger=logger,
            continuous=True,
            poll_interval=args.poll_interval,
        )
        
        elapsed = time.time() - start_time
        
        # Shutdown
        print("\nShutting down...")
        ipc_server.stop()
        
        logger.run_complete(
            processed=result['items_processed'],
            errors=result['errors'],
            duration_ms=elapsed * 1000
        )
        
        print(f"\n[OK] Daemon shutdown complete:")
        print(f"  Processed: {result['items_processed']}")
        print(f"  Completed: {result['completed']}")
        print(f"  Errors: {result['errors']}")
        print(f"  Uptime: {elapsed:.1f}s")
        
        return 0
        
    finally:
        lock.release()
        print("[OK] Writer lock released")


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize QBuilder schema."""
    print("Initializing QBuilder schema...")
    conn = get_connection()
    
    try:
        init_qbuilder_schema(conn)
        print("[OK] QBuilder tables initialized")
        
        counts = get_queue_counts(conn)
        print(f"  Discovery queue: {counts['discovery_total']} items")
        print(f"  Build queue: {counts['build_total']} items")
        return 0
    finally:
        conn.close()


def cmd_discover(args: argparse.Namespace) -> int:
    """Enqueue discovery tasks and run discovery workers."""
    conn = get_connection()
    
    try:
        init_qbuilder_schema(conn)
        
        # Get playset
        playset_path = get_active_playset_file()
        if not playset_path or not playset_path.exists():
            print(f"Error: No active playset found")
            print(f"  Manifest: {get_playset_manifest_path()}")
            return 1
        
        print(f"Loading playset from {playset_path.name}")
        
        # Enqueue discovery tasks
        count = enqueue_playset_roots(conn, playset_path)
        print(f"[OK] Enqueued {count} discovery tasks")
        
        # Run discovery unless --enqueue-only
        if not args.enqueue_only:
            print("\nRunning discovery workers...")
            result = run_discovery(conn, max_tasks=args.max_tasks)
            
            print(f"\n[OK] Discovery complete:")
            print(f"  Tasks processed: {result['tasks_processed']}")
            print(f"  Files discovered: {result['files_discovered']}")
        
        return 0
    finally:
        conn.close()


def cmd_build(args: argparse.Namespace) -> int:
    """Run build daemon (continuous by default)."""
    import uuid
    from .logging import QBuilderLogger
    
    conn = get_connection()
    
    # Generate run_id for tracking
    run_id = f"build-{uuid.uuid4().hex[:8]}"
    logger = QBuilderLogger(run_id=run_id)
    
    # Continuous is default - use --no-continuous to exit on empty queue
    continuous = not args.no_continuous
    
    try:
        init_qbuilder_schema(conn)
        
        counts = get_queue_counts(conn)
        pending = counts.get('build', {}).get('pending', 0)
        
        if pending == 0 and not continuous:
            print("[OK] No pending build items")
            return 0
        
        mode_str = "daemon" if continuous else f"{pending} items"
        print(f"Starting build {mode_str}...")
        print(f"  run_id: {run_id}")
        print(f"  log: {logger.log_file}")
        print(f"  pending: {pending}")
        if continuous:
            print(f"  poll_interval: {args.poll_interval}s")
            print(f"  mode: CONTINUOUS (Ctrl+C to stop)")
        
        start = time.time()
        logger.run_start(total_items=pending)
        
        result = run_build_worker(
            conn, 
            max_items=args.max_items, 
            logger=logger,
            continuous=continuous,
            poll_interval=args.poll_interval,
        )
        
        elapsed = time.time() - start
        rate = result['items_processed'] / elapsed if elapsed > 0 else 0
        
        logger.run_complete(
            processed=result['items_processed'],
            errors=result['errors'],
            duration_ms=elapsed * 1000
        )
        
        print(f"\n[OK] Build complete:")
        print(f"  Processed: {result['items_processed']}")
        print(f"  Completed: {result['completed']}")
        print(f"  Errors: {result['errors']}")
        print(f"  Time: {elapsed:.1f}s ({rate:.1f} items/sec)")
        
        return 0
        
        return 0
    finally:
        conn.close()


def cmd_run(args: argparse.Namespace) -> int:
    """Run complete pipeline: discover + build."""
    conn = get_connection()
    start_time = time.time()
    
    try:
        init_qbuilder_schema(conn)
        
        # Enqueue discovery from playset
        playset_path = get_active_playset_file()
        if playset_path and playset_path.exists():
            print(f"Loading playset from {playset_path.name}")
            count = enqueue_playset_roots(conn, playset_path)
            print(f"[OK] Enqueued {count} discovery tasks")
        
        # Run discovery
        print("\n=== Discovery Phase ===")
        discovery_result = run_discovery(conn)
        print(f"Discovered: {discovery_result['files_discovered']} files")
        
        # Run build
        counts = get_queue_counts(conn)
        pending = counts.get('build', {}).get('pending', 0)
        
        if pending > 0:
            print(f"\n=== Build Phase ({pending} items) ===")
            build_result = run_build_worker(conn)
            print(f"Built: {build_result['completed']} completed, {build_result['errors']} errors")
        
        elapsed = time.time() - start_time
        print(f"\n[OK] Pipeline complete in {elapsed:.1f}s")
        
        return 0
    finally:
        conn.close()


def cmd_status(args: argparse.Namespace) -> int:
    """Show queue status."""
    conn = get_connection()
    
    try:
        counts = get_queue_counts(conn)
        
        print("=== QBuilder Status ===\n")
        
        # Discovery queue
        d = counts.get('discovery', {})
        print("Discovery Queue:")
        print(f"  Pending:    {d.get('pending', 0)}")
        print(f"  Processing: {d.get('processing', 0)}")
        print(f"  Completed:  {d.get('completed', 0)}")
        print(f"  Errors:     {d.get('error', 0)}")
        print(f"  Total:      {counts['discovery_total']}")
        
        # Build queue
        b = counts.get('build', {})
        print("\nBuild Queue:")
        print(f"  Pending:    {b.get('pending', 0)}")
        print(f"  Processing: {b.get('processing', 0)}")
        print(f"  Completed:  {b.get('completed', 0)}")
        print(f"  Errors:     {b.get('error', 0)}")
        print(f"  Total:      {counts['build_total']}")
        
        # Database counts
        print("\nDatabase:")
        for table in ['files', 'asts', 'symbols', 'refs']:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                print(f"  {table}: {row[0]:,}")
            except sqlite3.OperationalError:
                print(f"  {table}: (table not found)")
        
        return 0
    finally:
        conn.close()


def cmd_reset(args: argparse.Namespace) -> int:
    """Reset queues for fresh build."""
    conn = get_connection()
    
    try:
        if args.fresh:
            print("Resetting ALL data for fresh build...")
            
            # Use BuilderSession to clear protected tables
            with BuilderSession(conn, "qbuilder_reset_fresh"):
                # Clear derived data
                for table in ['asts', 'symbols', 'refs', 'localization_entries', 
                              'trait_lookups', 'event_lookups', 'decision_lookups',
                              'character_lookup', 'province_lookup', 'dynasty_lookup',
                              'holy_site_lookup', 'name_lookup']:
                    try:
                        conn.execute(f"DELETE FROM {table}")
                    except sqlite3.OperationalError:
                        pass
                
                # Clear files
                conn.execute("DELETE FROM files")
                
                # Clear content_versions and mod_packages
                conn.execute("DELETE FROM content_versions")
                conn.execute("DELETE FROM mod_packages")
                
                conn.commit()
            print("  Cleared all derived data")
        
        # Reset queue tables
        reset_qbuilder_tables(conn)
        print("[OK] Queue tables reset")
        
        return 0
    finally:
        conn.close()


def cmd_enqueue_file(args: argparse.Namespace) -> int:
    """Enqueue a single file for processing (flash priority by default)."""
    from .api import enqueue_file, PRIORITY_FLASH, PRIORITY_NORMAL
    
    priority = PRIORITY_FLASH if args.flash else PRIORITY_NORMAL
    
    result = enqueue_file(
        mod_name=args.mod_name,
        rel_path=args.rel_path,
        priority=priority,
    )
    
    if result.success:
        if result.already_queued:
            print(f"[OK] Already queued: {args.mod_name}/{args.rel_path}")
        else:
            print(f"[OK] Enqueued: {args.mod_name}/{args.rel_path} (build_id={result.build_id}, priority={priority})")
        return 0
    else:
        print(f"[ERROR] {result.message}")
        return 1


def cmd_delete_file(args: argparse.Namespace) -> int:
    """Remove a file and its artifacts from the database."""
    from .api import delete_file
    
    result = delete_file(
        mod_name=args.mod_name,
        rel_path=args.rel_path,
    )
    
    if result.get("success"):
        print(f"[OK] {result.get('message', 'Deleted')}")
        return 0
    else:
        print(f"[ERROR] {result.get('error', 'Unknown error')}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        prog='qbuilder',
        description='Crash-safe queue-based builder for CK3 mod processing'
    )
    subparsers = parser.add_subparsers(dest='command', required=True)
    
    # daemon (the primary command for single-writer architecture)
    daemon_parser = subparsers.add_parser('daemon', 
        help='Start the single-writer daemon (recommended)')
    daemon_parser.add_argument('--fresh', action='store_true',
                               help='Reset ALL data and start fresh')
    daemon_parser.add_argument('--max-items', type=int, default=None,
                               help='Maximum build items to process (for testing)')
    daemon_parser.add_argument('--poll-interval', type=float, default=5.0,
                               help='Seconds between polls when queue empty (default: 5)')
    daemon_parser.set_defaults(func=cmd_daemon)
    
    # init
    init_parser = subparsers.add_parser('init', help='Initialize QBuilder schema')
    init_parser.set_defaults(func=cmd_init)
    
    # discover
    discover_parser = subparsers.add_parser('discover', help='Run discovery phase')
    discover_parser.add_argument('--enqueue-only', action='store_true',
                                 help='Only enqueue tasks, do not run')
    discover_parser.add_argument('--max-tasks', type=int, default=None,
                                 help='Maximum discovery tasks to process')
    discover_parser.set_defaults(func=cmd_discover)
    
    # build
    build_parser = subparsers.add_parser('build', help='Run build daemon (continuous by default)')
    build_parser.add_argument('--max-items', type=int, default=None,
                              help='Maximum build items to process (for testing only)')
    build_parser.add_argument('--no-continuous', action='store_true',
                              help='Exit when queue empty instead of polling (for testing)')
    build_parser.add_argument('--poll-interval', type=float, default=5.0,
                              help='Seconds between polls when queue empty (default: 5)')
    build_parser.set_defaults(func=cmd_build)
    
    # run
    run_parser = subparsers.add_parser('run', help='Run complete pipeline')
    run_parser.set_defaults(func=cmd_run)
    
    # status
    status_parser = subparsers.add_parser('status', help='Show queue status')
    status_parser.set_defaults(func=cmd_status)
    
    # reset
    reset_parser = subparsers.add_parser('reset', help='Reset queues')
    reset_parser.add_argument('--fresh', action='store_true',
                              help='Clear ALL data for fresh build')
    reset_parser.set_defaults(func=cmd_reset)
    
    # enqueue-file (for MCP flash updates)
    enqueue_parser = subparsers.add_parser('enqueue-file', 
                                           help='Enqueue a single file for processing')
    enqueue_parser.add_argument('mod_name', help='Mod name')
    enqueue_parser.add_argument('rel_path', help='Relative path within the mod')
    enqueue_parser.add_argument('--flash', action='store_true',
                                help='Use flash priority (default behavior)')
    enqueue_parser.add_argument('--normal', dest='flash', action='store_false',
                                help='Use normal priority instead of flash')
    enqueue_parser.set_defaults(flash=True, func=cmd_enqueue_file)
    
    # delete-file (for MCP file deletions)
    delete_parser = subparsers.add_parser('delete-file',
                                          help='Remove a file from the database')
    delete_parser.add_argument('mod_name', help='Mod name')
    delete_parser.add_argument('rel_path', help='Relative path within the mod')
    delete_parser.set_defaults(func=cmd_delete_file)
    
    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
