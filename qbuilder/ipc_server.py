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
    ):
        self.conn = conn
        self.port = port
        self.host = host
        
        self._server_socket: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._handlers: dict[str, Callable] = {}
        
        # Register built-in handlers
        self._register_handlers()
    
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
        
        counts = get_queue_counts(self.conn)
        
        return {
            "daemon_pid": os.getpid(),
            "db_path": str(getattr(self.conn, '_db_path', 'unknown')),
            "writer_lock": "held",
            "state": "idle",  # TODO: track actual state
            "queue": {
                "pending": counts.get('build', {}).get('pending', 0),
                "leased": counts.get('build', {}).get('processing', 0),
                "failed": counts.get('build', {}).get('error', 0),
            },
            "versions": {
                "protocol": PROTOCOL_VERSION,
            },
        }
    
    def _handle_get_status(self, request: IPCRequest) -> dict:
        """Handle status query."""
        from qbuilder.schema import get_queue_counts
        
        counts = get_queue_counts(self.conn)
        
        return {
            "state": "idle",  # TODO: track actual state
            "active_job": None,
            "queue": {
                "pending": counts.get('build', {}).get('pending', 0),
                "leased": counts.get('build', {}).get('processing', 0),
                "failed": counts.get('build', {}).get('error', 0),
            },
        }
    
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
        
        # Get playset file path
        playset_file = request.params.get("playset_file")
        if playset_file:
            playset_path = Path(playset_file)
        else:
            # Use active playset
            playsets_dir = Path(__file__).parent.parent / 'playsets'
            manifest_path = playsets_dir / 'playset_manifest.json'
            if manifest_path.exists():
                import json
                manifest = json.loads(manifest_path.read_text())
                active = manifest.get('active')
                if active:
                    playset_path = playsets_dir / active
                else:
                    return {"scheduled": False, "error": "No active playset"}
            else:
                return {"scheduled": False, "error": "No playset manifest"}
        
        if not playset_path.exists():
            return {"scheduled": False, "error": f"Playset file not found: {playset_path}"}
        
        count = enqueue_playset_roots(self.conn, playset_path)
        
        return {"scheduled": True, "discovery_tasks_enqueued": count}
    
    def _handle_await_idle(self, request: IPCRequest) -> dict:
        """Handle await_idle request - waits for queue to drain."""
        from qbuilder.schema import get_queue_counts
        
        timeout_ms = request.params.get("timeout_ms", 30000)
        deadline = time.time() + (timeout_ms / 1000.0)
        
        while time.time() < deadline:
            counts = get_queue_counts(self.conn)
            pending = counts.get('build', {}).get('pending', 0)
            leased = counts.get('build', {}).get('processing', 0)
            
            if pending == 0 and leased == 0:
                return {"idle": True, "queue_pending": 0}
            
            time.sleep(0.5)  # Poll interval
        
        counts = get_queue_counts(self.conn)
        pending = counts.get('build', {}).get('pending', 0)
        return {"idle": False, "queue_pending": pending, "timeout": True}
    
    def _handle_shutdown(self, request: IPCRequest) -> dict:
        """Handle shutdown request."""
        graceful = request.params.get("graceful", True)
        
        # Signal shutdown (the main loop should check this)
        self._running = False
        
        return {"acknowledged": True, "graceful": graceful}


def get_ipc_port() -> int:
    """Get the IPC port from environment or default."""
    return int(os.environ.get("CK3RAVEN_IPC_PORT", DEFAULT_IPC_PORT))


def get_ipc_address() -> tuple[str, int]:
    """Get the IPC server address."""
    return ("127.0.0.1", get_ipc_port())
