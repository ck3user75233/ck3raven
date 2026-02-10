"""
IPC Server — QBuilder Daemon's API for MCP clients.

This module implements the NDJSON socket server that MCP tools use
to request database mutations.

See docs/SINGLE_WRITER_ARCHITECTURE.md for the canonical IPC contract.

Transport:
    - TCP socket on localhost (configurable port)
    - NDJSON framing (one JSON object per line)
    - No authentication required (localhost only)

Usage:
    from qbuilder.ipc_server import DaemonIPCServer
    
    server = DaemonIPCServer(port=9876, conn=db_connection)
    server.start()  # Runs in background thread
    ...
    server.stop()
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sqlite3
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

# Default port for daemon IPC
DEFAULT_IPC_PORT = 19876  # High port, unlikely to conflict


class RunActivity:
    """
    Thread-safe tracker for daemon run activity.
    
    Shared between the build worker (main thread, writes) and the IPC server
    (handler thread, reads). All access is guarded by a lock.
    
    This solves the problem where `ck3_qbuilder(command="status")` returns
    "idle, pending:0" with no evidence of what work was done. Now the status
    response includes recent_activity showing items processed, timing, etc.
    """
    
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._run_id: str = ""
        self._items_processed: int = 0
        self._completed: int = 0
        self._errors: int = 0
        self._first_item_at: Optional[str] = None
        self._last_item_at: Optional[str] = None
        self._idle_since: Optional[str] = None
        self._started_at: Optional[str] = None
        self._state: str = "starting"  # starting, processing, idle, shutdown
        self._mods_discovered: list[str] = []
    
    def set_run_id(self, run_id: str) -> None:
        """Set the daemon run ID."""
        with self._lock:
            self._run_id = run_id
            self._started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    
    def record_item(self, status: str = "completed") -> None:
        """Record a processed item. Called by build worker after each item."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            self._items_processed += 1
            if status == "completed":
                self._completed += 1
            else:
                self._errors += 1
            if self._first_item_at is None:
                self._first_item_at = now
            self._last_item_at = now
            self._state = "processing"
            self._idle_since = None
    
    def set_idle(self) -> None:
        """Mark the daemon as idle. Called when worker enters poll-wait."""
        with self._lock:
            if self._state != "idle":
                self._state = "idle"
                self._idle_since = time.strftime("%Y-%m-%dT%H:%M:%S")
    
    def set_state(self, state: str) -> None:
        """Set daemon state (starting, processing, idle, shutdown)."""
        with self._lock:
            self._state = state
    
    def record_discovery(self, mod_summary: str) -> None:
        """Record a mod discovered during scan. E.g. 'Dev Debuff (4 files)'."""
        with self._lock:
            self._mods_discovered.append(mod_summary)
    
    def get_snapshot(self) -> dict:
        """Return a snapshot of current activity for IPC responses."""
        with self._lock:
            result: dict[str, Any] = {
                "state": self._state,
            }
            if self._run_id:
                result["run_id"] = self._run_id
            if self._started_at:
                result["started_at"] = self._started_at
            if self._items_processed > 0:
                result["items_processed"] = self._items_processed
                result["completed"] = self._completed
                result["errors_this_run"] = self._errors
                if self._first_item_at:
                    result["first_item_at"] = self._first_item_at
                if self._last_item_at:
                    result["last_item_at"] = self._last_item_at
            if self._idle_since:
                result["idle_since"] = self._idle_since
            if self._mods_discovered:
                result["mods_discovered"] = list(self._mods_discovered)
            return result

# Socket file for Unix domain sockets (alternative to TCP)
DEFAULT_SOCKET_PATH = Path.home() / ".ck3raven" / "daemon.sock"

# Protocol version
PROTOCOL_VERSION = 1

logger = logging.getLogger(__name__)


@dataclass
class IPCRequest:
    """Parsed IPC request."""
    version: int
    id: str
    method: str
    params: dict = field(default_factory=dict)


@dataclass
class IPCResponse:
    """IPC response to be sent back to client."""
    id: str
    ok: bool
    result: Optional[dict] = None
    error: Optional[dict] = None
    
    def to_json(self) -> str:
        resp = {"v": PROTOCOL_VERSION, "id": self.id, "ok": self.ok}
        if self.ok:
            resp["result"] = self.result or {}
        else:
            resp["error"] = self.error or {"code": "UNKNOWN", "message": "Unknown error"}
        return json.dumps(resp)


class DaemonIPCServer:
    """
    NDJSON socket server for daemon IPC.
    
    Handles requests from MCP clients and dispatches to handlers.
    Runs in a background thread to not block the build worker.
    """
    
    def __init__(
        self,
        conn: sqlite3.Connection,
        port: int = DEFAULT_IPC_PORT,
        host: str = "127.0.0.1",
        db_path: Optional[Path] = None,
        shutdown_callback: Optional[Callable[[], None]] = None,
        run_activity: Optional[RunActivity] = None,
    ):
        self.conn = conn  # Main thread connection (not used in handlers)
        self.port = port
        self.host = host
        self.db_path = db_path  # Store for thread-local connections
        self.shutdown_callback = shutdown_callback  # Called on shutdown request
        self.run_activity = run_activity  # Shared activity tracker (thread-safe)
        
        self._server_socket: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._handlers: dict[str, Callable] = {}
        self._thread_local = threading.local()  # Thread-local storage
        
        # Register built-in handlers
        self._register_handlers()
    
    def _get_handler_conn(self) -> sqlite3.Connection:
        """Get thread-local read-only connection for handler queries.
        
        IPC handlers run in a different thread than the main daemon.
        SQLite connections are not thread-safe, so we create a dedicated
        read-only connection for the handler thread.
        """
        if not hasattr(self._thread_local, 'conn') or self._thread_local.conn is None:
            if self.db_path:
                # Open read-only - handlers only query, never write
                db_uri = f"file:{self.db_path}?mode=ro"
                self._thread_local.conn = sqlite3.connect(db_uri, uri=True, timeout=30.0)
            else:
                # Fallback: try to get path from main conn (may not work)
                raise RuntimeError("db_path not set - cannot create handler connection")
        return self._thread_local.conn
    
    def _get_handler_write_conn(self) -> sqlite3.Connection:
        """Get a NEW read-write connection for handler operations that need to write.
        
        Unlike _get_handler_conn(), this creates a fresh connection each call.
        The caller MUST close this connection when done (use context manager).
        
        This follows the per-request connection model for write operations,
        which is simpler and safer than thread-local caching for writes.
        
        Uses busy_timeout to handle concurrent access during rebuilds.
        """
        if not self.db_path:
            raise RuntimeError("db_path not set - cannot create write connection")
        
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")  # 30 second busy wait
        return conn
    
    def _register_handlers(self) -> None:
        """Register IPC method handlers."""
        self._handlers = {
            "health": self._handle_health,
            "get_status": self._handle_get_status,
            "enqueue_files": self._handle_enqueue_files,
            "enqueue_scan": self._handle_enqueue_scan,
            "await_idle": self._handle_await_idle,
            "shutdown": self._handle_shutdown,
        }
    
    def start(self) -> None:
        """Start the IPC server in a background thread."""
        if self._running:
            return
        
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(5)
        self._server_socket.settimeout(1.0)  # Allow periodic shutdown checks
        
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        
        logger.info(f"IPC server listening on {self.host}:{self.port}")
    
    def stop(self) -> None:
        """Stop the IPC server."""
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5.0)
    
    def _accept_loop(self) -> None:
        """Main accept loop running in background thread."""
        assert self._server_socket is not None, "start() must be called first"
        while self._running:
            try:
                client_sock, addr = self._server_socket.accept()
                # Handle each client in a separate thread
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, addr),
                    daemon=True,
                )
                client_thread.start()
            except socket.timeout:
                continue  # Check _running flag
            except Exception as e:
                if self._running:
                    logger.error(f"Accept error: {e}")
    
    def _handle_client(self, sock: socket.socket, addr: tuple) -> None:
        """Handle a single client connection."""
        logger.debug(f"Client connected from {addr}")
        
        try:
            sock.settimeout(30.0)  # Client timeout
            buffer = ""
            
            while self._running:
                # Read data
                try:
                    data = sock.recv(4096)
                    if not data:
                        break  # Client disconnected
                    buffer += data.decode('utf-8')
                except socket.timeout:
                    continue
                
                # Process complete lines (NDJSON)
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    
                    response = self._process_request(line)
                    sock.sendall((response + '\n').encode('utf-8'))
                    
        except Exception as e:
            logger.error(f"Client error: {e}")
        finally:
            sock.close()
            logger.debug(f"Client disconnected: {addr}")
    
    def _process_request(self, line: str) -> str:
        """Process a single request line and return response JSON."""
        try:
            data = json.loads(line)
            request = IPCRequest(
                version=data.get("v", 1),
                id=data.get("id", "unknown"),
                method=data.get("method", ""),
                params=data.get("params", {}),
            )
        except json.JSONDecodeError as e:
            return IPCResponse(
                id="unknown",
                ok=False,
                error={"code": "BAD_JSON", "message": str(e)},
            ).to_json()
        
        # Dispatch to handler
        handler = self._handlers.get(request.method)
        if not handler:
            return IPCResponse(
                id=request.id,
                ok=False,
                error={"code": "UNKNOWN_METHOD", "message": f"Unknown method: {request.method}"},
            ).to_json()
        
        try:
            result = handler(request)
            return IPCResponse(id=request.id, ok=True, result=result).to_json()
        except Exception as e:
            logger.error(f"Handler error: {e}\n{traceback.format_exc()}")
            return IPCResponse(
                id=request.id,
                ok=False,
                error={"code": "INTERNAL", "message": str(e)},
            ).to_json()
    
    # =========================================================================
    # IPC Method Handlers
    # =========================================================================
    
    def _handle_health(self, request: IPCRequest) -> dict:
        """Handle health check request."""
        from qbuilder.schema import get_queue_counts
        
        handler_conn = self._get_handler_conn()
        counts = get_queue_counts(handler_conn)
        
        # Get state from run_activity if available, else fallback
        activity_snapshot = self.run_activity.get_snapshot() if self.run_activity else {}
        state = activity_snapshot.get("state", "idle")
        
        result = {
            "daemon_pid": os.getpid(),
            "db_path": str(self.db_path) if self.db_path else 'unknown',
            "writer_lock": "held",
            "state": state,
            "queue": {
                "pending": counts.get('build', {}).get('pending', 0),
                "leased": counts.get('build', {}).get('processing', 0),
                "failed": counts.get('build', {}).get('error', 0),
            },
            "versions": {
                "protocol": PROTOCOL_VERSION,
            },
        }
        
        if activity_snapshot:
            result["recent_activity"] = activity_snapshot
        
        return result
    
    def _handle_get_status(self, request: IPCRequest) -> dict:
        """Handle status query."""
        from qbuilder.schema import get_queue_counts
        
        handler_conn = self._get_handler_conn()
        counts = get_queue_counts(handler_conn)
        
        activity_snapshot = self.run_activity.get_snapshot() if self.run_activity else {}
        state = activity_snapshot.get("state", "idle")
        
        result = {
            "state": state,
            "active_job": None,
            "queue": {
                "pending": counts.get('build', {}).get('pending', 0),
                "leased": counts.get('build', {}).get('processing', 0),
                "failed": counts.get('build', {}).get('error', 0),
            },
        }
        
        if activity_snapshot:
            result["recent_activity"] = activity_snapshot
        
        return result
    
    def _handle_enqueue_files(self, request: IPCRequest) -> dict:
        """Handle file enqueue request."""
        from qbuilder.api import enqueue_file
        
        paths = request.params.get("paths", [])
        priority = request.params.get("priority", "normal")
        reason = request.params.get("reason", "user_request")
        
        priority_int = 1 if priority == "high" else 0
        
        enqueued = 0
        deduped = 0
        
        for path_str in paths:
            path = Path(path_str)
            # For now, we need mod_name and rel_path
            # The client should provide these, or we derive from path
            # This is a simplification - real impl would resolve path to mod
            result = enqueue_file(
                mod_name=request.params.get("mod_name", "unknown"),
                rel_path=str(path.name),  # Simplified
                priority=priority_int,
            )
            if result.success:
                if result.already_queued:
                    deduped += 1
                else:
                    enqueued += 1
        
        return {"enqueued": enqueued, "deduped": deduped}
    
    def _handle_enqueue_scan(self, request: IPCRequest) -> dict:
        """Handle discovery scan request."""
        from qbuilder.discovery import enqueue_playset_roots
        from qbuilder.cli import get_active_playset_file  # Use unified resolution
        
        # Get playset file path - use param if provided, else active playset
        playset_file = request.params.get("playset_file")
        if playset_file:
            playset_path = Path(playset_file)
        else:
            # Use unified active playset resolution
            playset_path = get_active_playset_file()
            if not playset_path:
                return {"scheduled": False, "error": "No active playset configured"}
        
        if not playset_path.exists():
            return {"scheduled": False, "error": f"Playset file not found: {playset_path}"}
        
        # Use write connection for enqueuing AND discovery (per-request, closed after use)
        write_conn = self._get_handler_write_conn()
        try:
            # Step 1: Enqueue discovery tasks (mod roots → discovery_queue)
            count = enqueue_playset_roots(write_conn, playset_path)
            write_conn.commit()
            
            # Step 2: Run discovery to convert discovery_queue → build_queue
            # This is critical - without this, build worker has nothing to process
            from qbuilder.discovery import run_discovery
            discovery_result = run_discovery(write_conn)
            files_discovered = discovery_result.get('files_discovered', 0)
            
            return {
                "scheduled": True, 
                "discovery_tasks_enqueued": count,
                "files_discovered": files_discovered,
            }
        finally:
            write_conn.close()
    
    def _handle_await_idle(self, request: IPCRequest) -> dict:
        """Handle await_idle request - waits for queue to drain."""
        from qbuilder.schema import get_queue_counts
        
        timeout_ms = request.params.get("timeout_ms", 30000)
        deadline = time.time() + (timeout_ms / 1000.0)
        
        handler_conn = self._get_handler_conn()
        
        while time.time() < deadline:
            counts = get_queue_counts(handler_conn)
            pending = counts.get('build', {}).get('pending', 0)
            leased = counts.get('build', {}).get('processing', 0)
            
            if pending == 0 and leased == 0:
                return {"idle": True, "queue_pending": 0}
            
            time.sleep(0.5)  # Poll interval
        
        counts = get_queue_counts(handler_conn)
        pending = counts.get('build', {}).get('pending', 0)
        return {"idle": False, "queue_pending": pending, "timeout": True}
    
    def _handle_shutdown(self, request: IPCRequest) -> dict:
        """Handle shutdown request."""
        graceful = request.params.get("graceful", True)
        
        # Signal shutdown (the main loop should check this)
        self._running = False
        
        # Invoke callback to signal main daemon/worker
        if self.shutdown_callback:
            self.shutdown_callback()
        
        return {"acknowledged": True, "graceful": graceful}


def get_ipc_port() -> int:
    """Get the IPC port from environment or default."""
    return int(os.environ.get("CK3RAVEN_IPC_PORT", DEFAULT_IPC_PORT))


def get_ipc_address() -> tuple[str, int]:
    """Get the IPC server address."""
    return ("127.0.0.1", get_ipc_port())
