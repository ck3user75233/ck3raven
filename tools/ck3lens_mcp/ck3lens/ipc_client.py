"""
VS Code IPC Client

TCP client that connects to the VS Code extension's diagnostics server.
Allows MCP tools to access VS Code APIs like diagnostics, open files, etc.

Protocol: JSON-RPC over TCP (newline-delimited)
Default port: 9847 (auto-discovered from port file)
"""

import json
import socket
import os
import tempfile
from typing import Any, Optional, Dict, List
from pathlib import Path


class VSCodeIPCError(Exception):
    """Error communicating with VS Code IPC server"""
    pass


class VSCodeIPCClient:
    """
    Client for communicating with VS Code extension's diagnostics server.
    
    Usage:
        client = VSCodeIPCClient()
        client.connect()
        result = client.get_diagnostics("/path/to/file.py")
        client.close()
        
    Or as context manager:
        with VSCodeIPCClient() as client:
            result = client.get_diagnostics("/path/to/file.py")
    """
    
    DEFAULT_PORT = 9847
    HOST = "127.0.0.1"
    TIMEOUT = 10.0
    
    def __init__(self, port: Optional[int] = None, timeout: float = TIMEOUT):
        """
        Initialize the IPC client.
        
        Args:
            port: TCP port to connect to. If None, auto-discovers from port file.
            timeout: Socket timeout in seconds.
        """
        self.port = port
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None
        self._request_id = 0
    
    def __enter__(self) -> "VSCodeIPCClient":
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def _discover_port(self) -> int:
        """Discover port from the port file written by VS Code extension."""
        port_file = Path(tempfile.gettempdir()) / "ck3lens_ipc_port"
        
        if port_file.exists():
            try:
                data = json.loads(port_file.read_text())
                # Check if the port file is recent (within last hour)
                import time
                if time.time() - data.get("timestamp", 0) < 3600:
                    return data["port"]
            except (json.JSONDecodeError, KeyError):
                pass
        
        return self.DEFAULT_PORT
    
    def connect(self) -> None:
        """Establish connection to the VS Code IPC server."""
        if self._socket:
            return
        
        port = self.port or self._discover_port()
        
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.timeout)
            self._socket.connect((self.HOST, port))
        except ConnectionRefusedError:
            raise VSCodeIPCError(
                f"Cannot connect to VS Code IPC server on port {port}. "
                "Make sure the CK3 Lens extension is active in VS Code."
            )
        except socket.timeout:
            raise VSCodeIPCError(f"Connection to VS Code IPC server timed out")
    
    def close(self) -> None:
        """Close the connection."""
        if self._socket:
            try:
                self._socket.close()
            except:
                pass
            self._socket = None
    
    def _send_request(self, method: str, params: Optional[Dict] = None) -> Any:
        """Send a JSON-RPC request and return the result."""
        if not self._socket:
            raise VSCodeIPCError("Not connected. Call connect() first.")
        
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {}
        }
        
        # Send request
        message = json.dumps(request) + "\n"
        try:
            self._socket.sendall(message.encode("utf-8"))
        except socket.error as e:
            raise VSCodeIPCError(f"Failed to send request: {e}")
        
        # Receive response
        buffer = ""
        try:
            while "\n" not in buffer:
                chunk = self._socket.recv(65536).decode("utf-8")
                if not chunk:
                    raise VSCodeIPCError("Connection closed by server")
                buffer += chunk
        except socket.timeout:
            raise VSCodeIPCError("Request timed out waiting for response")
        except socket.error as e:
            raise VSCodeIPCError(f"Failed to receive response: {e}")
        
        # Parse response
        line = buffer.split("\n")[0]
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            raise VSCodeIPCError(f"Invalid JSON response: {line[:200]}")
        
        if "error" in response:
            error = response["error"]
            raise VSCodeIPCError(f"RPC error {error.get('code')}: {error.get('message')}")
        
        return response.get("result")
    
    # -------------------------------------------------------------------------
    # Public API Methods
    # -------------------------------------------------------------------------
    
    def ping(self) -> Dict:
        """Test connection to the server."""
        return self._send_request("ping")
    
    def get_diagnostics(self, path: str) -> Dict:
        """
        Get diagnostics for a specific file.
        
        Args:
            path: Absolute file path.
            
        Returns:
            Dict with:
                - uri: File URI
                - path: File path
                - diagnostics: List of diagnostic objects
        """
        return self._send_request("getDiagnostics", {"path": path})
    
    def get_all_diagnostics(
        self,
        severity: Optional[str] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Dict:
        """
        Get all diagnostics across all open files.
        
        Args:
            severity: Filter by severity ('error', 'warning', 'info', 'hint')
            source: Filter by source (e.g., 'Pylance', 'CK3 Lens')
            limit: Max number of files to return
            
        Returns:
            Dict with:
                - fileCount: Number of files with diagnostics
                - totalDiagnostics: Total number of diagnostics
                - files: List of {uri, path, diagnostics}
        """
        params = {}
        if severity:
            params["severity"] = severity
        if source:
            params["source"] = source
        if limit:
            params["limit"] = limit
        return self._send_request("getAllDiagnostics", params)
    
    def get_workspace_errors(self, include_warnings: bool = True) -> Dict:
        """
        Get workspace-wide error summary.
        
        Args:
            include_warnings: Include warnings in the summary.
            
        Returns:
            Dict with:
                - summary: {errors, warnings, info, filesWithErrors, filesWithWarnings}
                - bySource: Error counts by source
                - topErrorFiles: Files with most errors
                - sources: List of diagnostic sources
        """
        return self._send_request("getWorkspaceErrors", {
            "includeWarnings": include_warnings
        })
    
    def validate_file(self, path: str) -> Dict:
        """
        Trigger validation for a specific file.
        
        This opens the file (if not already open) to trigger language server validation.
        
        Args:
            path: Absolute file path.
            
        Returns:
            Dict with diagnostics for the file.
        """
        return self._send_request("validateFile", {"path": path})
    
    def get_open_files(self) -> Dict:
        """
        Get list of currently open files in VS Code.
        
        Returns:
            Dict with:
                - count: Number of open files
                - files: List of {uri, path, languageId, isDirty, lineCount}
        """
        return self._send_request("getOpenFiles")
    
    def get_active_file(self) -> Dict:
        """
        Get information about the currently active file.
        
        Returns:
            Dict with file info and diagnostics, or {active: false} if no file.
        """
        return self._send_request("getActiveFile")
    
    def execute_command(self, command: str, args: Optional[List] = None) -> Dict:
        """
        Execute a whitelisted VS Code command.
        
        Args:
            command: VS Code command ID (must be in whitelist).
            args: Command arguments.
            
        Returns:
            Dict with execution result.
        """
        return self._send_request("executeCommand", {
            "command": command,
            "args": args or []
        })


# Convenience function for one-shot queries
def get_vscode_diagnostics(
    path: Optional[str] = None,
    severity: Optional[str] = None,
    source: Optional[str] = None
) -> Dict:
    """
    Convenience function to get diagnostics from VS Code.
    
    Args:
        path: Specific file path (if None, gets all diagnostics)
        severity: Filter by severity
        source: Filter by source
        
    Returns:
        Diagnostic results from VS Code.
    """
    try:
        with VSCodeIPCClient() as client:
            if path:
                return client.get_diagnostics(path)
            else:
                return client.get_all_diagnostics(severity=severity, source=source)
    except VSCodeIPCError as e:
        return {
            "error": True,
            "message": str(e),
            "suggestion": "Ensure VS Code is running with CK3 Lens extension active"
        }


def get_vscode_error_summary() -> Dict:
    """
    Get workspace error summary from VS Code.
    
    Returns:
        Error summary or error message.
    """
    try:
        with VSCodeIPCClient() as client:
            return client.get_workspace_errors()
    except VSCodeIPCError as e:
        return {
            "error": True,
            "message": str(e),
            "suggestion": "Ensure VS Code is running with CK3 Lens extension active"
        }


def is_vscode_available() -> bool:
    """Check if VS Code IPC server is available."""
    try:
        with VSCodeIPCClient(timeout=2.0) as client:
            client.ping()
            return True
    except:
        return False
