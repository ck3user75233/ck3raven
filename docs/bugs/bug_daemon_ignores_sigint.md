# Bug Report: QBuilder Daemon Ignores Ctrl+C / SIGINT

**Severity:** High  
**Component:** qbuilder/cli.py, qbuilder/worker.py, qbuilder/ipc_server.py  
**Date:** 2026-02-06

---

## Summary

When pressing Ctrl+C to terminate the qbuilder daemon, it prints "Received signal 2, shutting down..." but **does not actually exit**. The worker thread continues running, requiring the user to forcefully kill the process.

## Symptoms

```
[Worker] Waiting for work... (0 processed, idle for 3965s)
[Worker] Waiting for work... (0 processed, idle for 4025s)

Received signal 2, shutting down...
[Worker] Waiting for work... (0 processed, idle for 4145s)

Received signal 2, shutting down...
Received signal 2, shutting down...
```

User has to:
- Close the terminal window, OR
- Use Task Manager to kill Python process, OR
- `taskkill /F /IM python.exe` from another terminal

## Existing Shutdown Infrastructure (NOT WIRED UP)

An IPC shutdown handler exists in `qbuilder/ipc_server.py` (lines 412-419):

```python
def _handle_shutdown(self, request: IPCRequest) -> dict:
    """Handle shutdown request."""
    graceful = request.params.get("graceful", True)
    self._running = False  # Only affects IPC server thread!
    return {"acknowledged": True, "graceful": graceful}
```

**Problems:**
1. **No CLI command** to invoke it - no `python -m qbuilder stop`
2. **No MCP command** - `ck3_qbuilder` tool lacks `stop` command
3. **Only stops IPC thread** - The main worker loop in `cli.py` doesn't check this flag

## Root Cause

The daemon has three components that don't coordinate shutdown:

| Component | Has Shutdown Flag | Actually Checks It |
|-----------|------------------|--------------------|
| IPC Server | `self._running` | ✅ Yes |
| Worker Loop | No dedicated flag | ❌ No |
| Signal Handler | Sets some flag | ❌ Worker ignores it |

## Recommended Fix

### 1. Add CLI `stop` Command

```python
# In cli.py
def cmd_stop(args):
    """Send shutdown command to running daemon via IPC."""
    import socket
    import json
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect(("127.0.0.1", 19876))
        request = {"v": 1, "id": "stop-1", "method": "shutdown", "params": {"graceful": True}}
        sock.sendall((json.dumps(request) + "\n").encode())
        response = sock.recv(4096).decode()
        print(f"Shutdown acknowledged: {response}")
    except ConnectionRefusedError:
        print("Daemon not running")
    finally:
        sock.close()
```

### 2. Add MCP `stop` Command

```python
# In ck3_qbuilder tool
elif command == "stop":
    # Send shutdown IPC
    result = send_ipc_command("shutdown", {"graceful": True})
    return {"stopped": result.get("acknowledged", False)}
```

### 3. Wire Signal Handler to Worker

```python
# Shared shutdown event
shutdown_event = threading.Event()

def signal_handler(sig, frame):
    print(f"Received signal {sig}, shutting down...")
    shutdown_event.set()

# Worker checks event
def worker_loop():
    while not shutdown_event.is_set():
        try:
            item = queue.get(timeout=5)
            process(item)
        except Empty:
            continue
    print("[Worker] Shutdown complete")

# Main waits for worker
signal.signal(signal.SIGINT, signal_handler)
worker_thread.join(timeout=10)
sys.exit(0)
```

### 4. IPC Shutdown Should Also Set Worker Flag

```python
def _handle_shutdown(self, request: IPCRequest) -> dict:
    self._running = False
    shutdown_event.set()  # Also signal worker to stop
    return {"acknowledged": True}
```

## Platform Note

On Windows, signal handling differs from Unix. Consider:
- `SetConsoleCtrlHandler` for robust Windows Ctrl+C handling
- `atexit` for cleanup on any exit

## Related

- Feature request (unified MCP): Proposes `stop` command - this bug shows why it's needed
- Bug #1 (--fresh no discovery): Daemon sits idle forever, making this bug more painful

## Testing

1. Start daemon: `python -m qbuilder daemon`
2. Press Ctrl+C
3. Verify daemon exits within 5 seconds
4. Alternatively: `python -m qbuilder stop` should work
5. Alternatively: `ck3_qbuilder(command='stop')` should work
