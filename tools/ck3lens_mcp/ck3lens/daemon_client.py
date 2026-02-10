"""
Daemon Client — IPC client for MCP tools to communicate with QBuilder daemon.

This is the ONLY way MCP tools should request database mutations.
All write operations go through this client to the daemon.

See docs/SINGLE_WRITER_ARCHITECTURE.md for the canonical design.

Usage:
    from ck3lens.daemon_client import daemon
    
    # Check if daemon is running
    if daemon.is_available():
        status = daemon.health()
        
    # Request file processing
    result = daemon.enqueue_files(["/path/to/file.txt"], priority="high")
    
    # Wait for processing to complete
    daemon.await_idle(timeout_ms=30000)
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Default IPC port (must match ipc_server.py)
DEFAULT_IPC_PORT = 19876
PROTOCOL_VERSION = 1

# Connection timeout
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0

logger = logging.getLogger(__name__)


class DaemonNotAvailableError(Exception):
    """Raised when daemon is not running or unreachable."""
    pass


class DaemonError(Exception):
    """Raised when daemon returns an error response."""
    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{code}: {message}")


@dataclass
class DaemonStatus:
    """Status information from daemon health check."""
    daemon_pid: int
    db_path: str
    state: str
    queue_pending: int
    queue_leased: int
    queue_failed: int
    recent_activity: Optional[dict] = None  # RunActivity snapshot from daemon
    
    @property
    def is_idle(self) -> bool:
        return self.queue_pending == 0 and self.queue_leased == 0


class DaemonClient:
    """
    IPC client for communicating with the QBuilder daemon.
    
    Singleton pattern - use the global `daemon` instance.
    """
    
    _instance: Optional["DaemonClient"] = None
    
    def __new__(cls) -> "DaemonClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._host = "127.0.0.1"
        self._port = int(os.environ.get("CK3RAVEN_IPC_PORT", DEFAULT_IPC_PORT))
        self._last_check: float = 0
        self._cached_available: bool = False
    
    # =========================================================================
    # Connection Management
    # =========================================================================
    
    def is_available(self, force_check: bool = False) -> bool:
        """
        Check if the daemon is running and reachable.
        
        Caches result for 5 seconds unless force_check=True.
        """
        now = time.time()
        if not force_check and (now - self._last_check) < 5.0:
            return self._cached_available
        
        try:
            self.health()
            self._cached_available = True
        except (DaemonNotAvailableError, Exception):
            self._cached_available = False
        
        self._last_check = now
        return self._cached_available
    
    def _send_request(self, method: str, params: Optional[dict] = None) -> dict:
        """
        Send a request to the daemon and return the response.
        
        Raises:
            DaemonNotAvailableError: If daemon is not running
            DaemonError: If daemon returns an error response
        """
        request_id = str(uuid.uuid4())[:8]
        request = {
            "v": PROTOCOL_VERSION,
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(CONNECT_TIMEOUT)
            sock.connect((self._host, self._port))
            sock.settimeout(READ_TIMEOUT)
            
            # Send request
            sock.sendall((json.dumps(request) + '\n').encode('utf-8'))
            
            # Read response
            buffer = ""
            while '\n' not in buffer:
                data = sock.recv(4096)
                if not data:
                    raise DaemonNotAvailableError("Daemon closed connection")
                buffer += data.decode('utf-8')
            
            sock.close()
            
            # Parse response
            response = json.loads(buffer.strip())
            
            if not response.get("ok", False):
                error = response.get("error", {})
                raise DaemonError(
                    code=error.get("code", "UNKNOWN"),
                    message=error.get("message", "Unknown error"),
                    details=error.get("details"),
                )
            
            return response.get("result", {})
            
        except socket.error as e:
            raise DaemonNotAvailableError(f"Cannot connect to daemon: {e}")
        except json.JSONDecodeError as e:
            raise DaemonError("BAD_RESPONSE", f"Invalid JSON from daemon: {e}")
    
    # =========================================================================
    # IPC Methods
    # =========================================================================
    
    def health(self) -> DaemonStatus:
        """
        Get daemon health status.
        
        Returns:
            DaemonStatus with daemon info and queue state.
        
        Raises:
            DaemonNotAvailableError: If daemon is not running
        """
        result = self._send_request("health")
        queue = result.get("queue", {})
        
        return DaemonStatus(
            daemon_pid=result.get("daemon_pid", 0),
            db_path=result.get("db_path", ""),
            state=result.get("state", "unknown"),
            queue_pending=queue.get("pending", 0),
            queue_leased=queue.get("leased", 0),
            queue_failed=queue.get("failed", 0),
            recent_activity=result.get("recent_activity"),
        )
    
    def get_status(self) -> dict:
        """
        Get lightweight daemon status.
        
        Returns:
            Dict with state, active_job, and queue info.
        """
        return self._send_request("get_status")
    
    def enqueue_files(
        self,
        paths: list[str],
        mod_name: Optional[str] = None,
        priority: str = "normal",
        reason: str = "user_request",
    ) -> dict:
        """
        Request daemon to process files.
        
        Args:
            paths: List of absolute file paths to process
            mod_name: Optional mod name (for path resolution)
            priority: "normal" or "high"
            reason: Why files need processing
        
        Returns:
            Dict with enqueued/deduped counts
        """
        params = {
            "paths": [str(p) for p in paths],
            "priority": priority,
            "reason": reason,
        }
        if mod_name:
            params["mod_name"] = mod_name
        
        return self._send_request("enqueue_files", params)
    
    def enqueue_scan(
        self,
        playset_file: Optional[str] = None,
        include_globs: Optional[list[str]] = None,
        exclude_globs: Optional[list[str]] = None,
        priority: str = "normal",
    ) -> dict:
        """
        Request daemon to scan a content root for files.
        
        Args:
            playset_file: Path to playset JSON (uses active if None)
            include_globs: File patterns to include
            exclude_globs: File patterns to exclude
            priority: "normal" or "high"
        
        Returns:
            Dict with scheduled status
        """
        params = {"priority": priority}
        if playset_file:
            params["playset_file"] = str(playset_file)
        if include_globs:
            params["include_globs"] = include_globs
        if exclude_globs:
            params["exclude_globs"] = exclude_globs
        
        return self._send_request("enqueue_scan", params)
    
    def await_idle(self, timeout_ms: int = 30000) -> dict:
        """
        Wait for daemon to finish processing all pending work.
        
        Args:
            timeout_ms: Maximum time to wait in milliseconds
        
        Returns:
            Dict with idle status
        """
        return self._send_request("await_idle", {"timeout_ms": timeout_ms})
    
    def shutdown(self, graceful: bool = True) -> dict:
        """
        Request daemon shutdown.
        
        Args:
            graceful: If True, wait for current work to complete
        
        Returns:
            Acknowledgment dict
        """
        return self._send_request("shutdown", {"graceful": graceful})
    
    # =========================================================================
    # Convenience Methods for MCP Tools
    # =========================================================================
    
    def notify_file_changed(self, path: str, mod_name: Optional[str] = None) -> dict:
        """
        Notify daemon that a file was changed (after MCP file write).
        
        This is the method MCP tools should call after writing to mod files.
        """
        return self.enqueue_files(
            paths=[path],
            mod_name=mod_name,
            priority="high",
            reason="file_changed",
        )
    
    def request_rebuild(self, paths: list[str]) -> dict:
        """
        Request rebuild of specific files.
        
        This is for user-initiated rebuilds.
        """
        return self.enqueue_files(
            paths=paths,
            priority="normal",
            reason="user_request",
        )
    
    def get_queue_status(self) -> dict:
        """
        Get queue status for UI display.
        
        Returns a dict suitable for status bar display.
        Includes recent_activity snapshot from RunActivity tracker
        when daemon is connected.
        """
        try:
            status = self.health()
            result = {
                "connected": True,
                "daemon_state": status.state,
                "queue": {
                    "pending": status.queue_pending,
                    "leased": status.queue_leased,
                    "failed": status.queue_failed,
                },
            }
            if status.recent_activity:
                result["recent_activity"] = status.recent_activity
            return result
        except DaemonNotAvailableError:
            return {
                "connected": False,
                "daemon_state": "not_running",
                "queue": {"pending": 0, "leased": 0, "failed": 0},
            }


# Singleton instance - import this in MCP tools
daemon = DaemonClient()
