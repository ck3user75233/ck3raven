# Bug Report: QBuilder Shutdown Handler Exists But Is Unreachable

**Severity:** High  
**Component:** qbuilder/cli.py, qbuilder/ipc_server.py, tools/ck3lens_mcp  
**Date:** 2026-02-06

---

## Summary

The qbuilder daemon has a `shutdown` IPC handler implemented, but there is **no way to invoke it**. Neither the CLI nor the MCP tool exposes a `stop` command, leaving users unable to gracefully terminate the daemon.

## Current State

### What Exists (ipc_server.py lines 412-419)

```python
def _handle_shutdown(self, request: IPCRequest) -> dict:
    """Handle shutdown request."""
    graceful = request.params.get("graceful", True)
    self._running = False
    return {"acknowledged": True, "graceful": graceful}
```

### What's Missing

| Component | Stop Command | Status |
|-----------|-------------|--------|
| CLI (`python -m qbuilder`) | `stop` | ❌ Not implemented |
| MCP tool (`ck3_qbuilder`) | `command="stop"` | ❌ Not implemented |
| Direct IPC | Manual socket call | ⚠️ Works but undocumented |

### Current CLI Commands (cli.py)

```
daemon    Start the single-writer daemon
init      Initialize QBuilder schema
discover  Enqueue discovery tasks
build     Run build workers
run       Run complete pipeline
status    Show queue status
reset     Reset queues for fresh build
```

No `stop` command.

### Current MCP Commands

```python
ck3_qbuilder(command="status")    # ✅ Works
ck3_qbuilder(command="build")     # ✅ Works
ck3_qbuilder(command="discover")  # ✅ Works
ck3_qbuilder(command="reset")     # ✅ Works
ck3_qbuilder(command="stop")      # ❌ Not implemented
```

## Impact

1. **Users can't stop daemon gracefully** - Must kill process or close terminal
2. **Ctrl+C doesn't work** - Signal handler is broken (see related bug)
3. **MCP sessions can't manage daemon lifecycle** - Agent can start but not stop

## Recommended Fix

### 1. Add CLI `stop` Command

**File:** `qbuilder/cli.py`

```python
def cmd_stop(args):
    """Send shutdown command to running daemon via IPC."""
    import socket
    import json
    from .ipc_server import get_ipc_port
    
    port = get_ipc_port()
    timeout = getattr(args, 'timeout', 10)
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    
    try:
        sock.connect(("127.0.0.1", port))
        request = {
            "v": 1, 
            "id": "cli-stop-1", 
            "method": "shutdown", 
            "params": {"graceful": True, "timeout": timeout}
        }
        sock.sendall((json.dumps(request) + "\n").encode())
        
        response = sock.recv(4096).decode().strip()
        result = json.loads(response)
        
        if result.get("ok"):
            print("[OK] Shutdown signal sent")
            # Optionally wait for daemon to exit
            if args.wait:
                wait_for_daemon_exit(port, timeout)
        else:
            print(f"[ERROR] {result.get('error', {}).get('message', 'Unknown error')}")
            
    except ConnectionRefusedError:
        print("[INFO] Daemon not running (connection refused)")
    except socket.timeout:
        print("[WARN] Daemon did not respond - may need to kill manually")
    finally:
        sock.close()


def wait_for_daemon_exit(port: int, timeout: int = 10):
    """Wait for daemon to actually exit."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(("127.0.0.1", port))
            sock.close()
            time.sleep(0.5)  # Still running, wait
        except ConnectionRefusedError:
            print("[OK] Daemon stopped")
            return
    print("[WARN] Daemon still running after timeout")
```

**Add to argparse:**

```python
# In main() argument parser setup
stop_parser = subparsers.add_parser('stop', help='Stop running daemon')
stop_parser.add_argument('--timeout', type=int, default=10, help='Shutdown timeout seconds')
stop_parser.add_argument('--wait', action='store_true', help='Wait for daemon to exit')
stop_parser.set_defaults(func=cmd_stop)
```

### 2. Add MCP `stop` Command

**File:** `tools/ck3lens_mcp/server.py` (or wherever ck3_qbuilder is defined)

```python
@mcp.tool()
def ck3_qbuilder(command: str, ...):
    if command == "stop":
        return _stop_daemon(force=params.get("force", False))

def _stop_daemon(force: bool = False) -> dict:
    """Send shutdown command to daemon via IPC."""
    import socket
    import json
    
    port = 19876  # Or get from config
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(("127.0.0.1", port))
        
        request = {
            "v": 1,
            "id": "mcp-stop-1", 
            "method": "shutdown",
            "params": {"graceful": not force}
        }
        sock.sendall((json.dumps(request) + "\n").encode())
        
        response = sock.recv(4096).decode().strip()
        result = json.loads(response)
        
        return {
            "success": result.get("ok", False),
            "acknowledged": result.get("result", {}).get("acknowledged", False)
        }
        
    except ConnectionRefusedError:
        return {"success": True, "note": "Daemon was not running"}
    except socket.timeout:
        return {"success": False, "error": "Daemon did not respond"}
    finally:
        sock.close()
```

### 3. Fix Shutdown Handler to Actually Stop Worker

The current handler only sets `self._running = False` on the IPC server thread. The main worker loop doesn't check this.

**File:** `qbuilder/ipc_server.py`

```python
# Add a shared shutdown callback
class DaemonIPCServer:
    def __init__(self, ..., shutdown_callback: Optional[Callable] = None):
        self._shutdown_callback = shutdown_callback
        ...
    
    def _handle_shutdown(self, request: IPCRequest) -> dict:
        graceful = request.params.get("graceful", True)
        self._running = False
        
        # Invoke callback to signal main daemon
        if self._shutdown_callback:
            self._shutdown_callback(graceful=graceful)
        
        return {"acknowledged": True, "graceful": graceful}
```

**File:** `qbuilder/cli.py` (in cmd_daemon)

```python
# Create shared shutdown event
shutdown_event = threading.Event()

def on_shutdown(graceful: bool):
    print(f"[Daemon] Shutdown requested (graceful={graceful})")
    shutdown_event.set()

# Pass callback to IPC server
ipc_server = DaemonIPCServer(
    conn=conn, 
    port=port, 
    shutdown_callback=on_shutdown
)

# Worker loop checks event
while not shutdown_event.is_set():
    # ... worker logic
```

## Testing

After fix:

```bash
# Terminal 1: Start daemon
python -m qbuilder daemon

# Terminal 2: Stop it
python -m qbuilder stop
# Expected: "[OK] Shutdown signal sent" then "[OK] Daemon stopped"

# Or via MCP
ck3_qbuilder(command="stop")
# Expected: {"success": true, "acknowledged": true}
```

## Related

- Bug: Daemon ignores Ctrl+C - Same root cause (worker doesn't check shutdown flag)
- Feature: Unified qbuilder MCP - Includes `stop` command in proposed API
