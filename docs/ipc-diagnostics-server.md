# VS Code IPC Diagnostics Server

## Overview

The IPC Diagnostics Server provides a TCP-based communication channel between the MCP server and VS Code extension. This enables MCP tools to access VS Code IDE APIs that are otherwise unavailable from CLI/external processes.

**Key Use Case**: Accessing Pylance diagnostics, language server errors, and other IDE-specific data from MCP tools.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         VS Code                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                  CK3 Lens Extension                       │  │
│  │                                                           │  │
│  │   ┌─────────────────┐    ┌──────────────────────────┐   │  │
│  │   │ DiagnosticsServer│◄──│ vscode.languages API     │   │  │
│  │   │ (TCP :9847)      │    │ - getDiagnostics()       │   │  │
│  │   └────────┬─────────┘    │ - Pylance errors         │   │  │
│  │            │              │ - CK3 Lens linting       │   │  │
│  │            │              └──────────────────────────┘   │  │
│  └────────────┼──────────────────────────────────────────────┘  │
│               │ TCP (JSON-RPC)                                   │
└───────────────┼─────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────┐
│                      MCP Server (Python)                          │
│                                                                   │
│   ┌──────────────────┐     ┌─────────────────────────────────┐  │
│   │ VSCodeIPCClient  │────►│ ck3_vscode MCP Tool             │  │
│   │ (ipc_client.py)  │     │                                  │  │
│   └──────────────────┘     │ Commands:                        │  │
│                            │ - status, ping                   │  │
│                            │ - diagnostics, all_diagnostics   │  │
│                            │ - errors_summary                 │  │
│                            │ - validate_file                  │  │
│                            │ - open_files, active_file        │  │
│                            └─────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────┘
```

## Protocol

### Transport
- **Protocol**: TCP over localhost (127.0.0.1)
- **Default Port**: 9847 (configurable via `ck3lens.ipcPort` setting)
- **Message Format**: JSON-RPC 2.0, newline-delimited

### Port Discovery
The extension writes the actual port to a temp file for MCP client discovery:
- **Location**: `{TEMP}/ck3lens_ipc_port`
- **Content**: `{"port": 9847, "pid": 12345, "timestamp": 1703548800000}`

This allows the MCP client to find the server even if the default port was in use.

## Server API (VS Code Extension)

### File: `src/ipc/diagnosticsServer.ts`

The `DiagnosticsServer` class implements a TCP server with these JSON-RPC methods:

#### `ping`
Test connection to the server.

**Request:**
```json
{"jsonrpc": "2.0", "id": 1, "method": "ping"}
```

**Response:**
```json
{"jsonrpc": "2.0", "id": 1, "result": {"status": "ok", "timestamp": 1703548800000}}
```

#### `getDiagnostics`
Get diagnostics for a specific file.

**Request:**
```json
{"jsonrpc": "2.0", "id": 1, "method": "getDiagnostics", "params": {"path": "/path/to/file.py"}}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "uri": "file:///path/to/file.py",
    "path": "/path/to/file.py",
    "diagnostics": [
      {
        "range": {"start": {"line": 10, "character": 5}, "end": {"line": 10, "character": 15}},
        "message": "Cannot find name 'undefined_var'",
        "severity": "error",
        "source": "Pylance",
        "code": "reportUndefinedVariable"
      }
    ]
  }
}
```

#### `getAllDiagnostics`
Get diagnostics across all open files.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "getAllDiagnostics",
  "params": {
    "severity": "error",    // Optional: 'error', 'warning', 'info', 'hint'
    "source": "Pylance",    // Optional: filter by source
    "limit": 50             // Optional: max files
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "fileCount": 3,
    "totalDiagnostics": 15,
    "files": [
      {"uri": "...", "path": "...", "diagnostics": [...]},
      ...
    ]
  }
}
```

#### `getWorkspaceErrors`
Get workspace-wide error summary.

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "summary": {
      "errors": 5,
      "warnings": 12,
      "info": 3,
      "filesWithErrors": 2,
      "filesWithWarnings": 5
    },
    "bySource": {
      "Pylance": 10,
      "CK3 Lens": 7,
      "ESLint": 3
    },
    "topErrorFiles": [
      {"path": "/path/to/file.py", "errors": 3, "warnings": 2}
    ],
    "sources": ["Pylance", "CK3 Lens", "ESLint"]
  }
}
```

#### `validateFile`
Trigger validation for a specific file (opens it if needed).

**Request:**
```json
{"jsonrpc": "2.0", "id": 1, "method": "validateFile", "params": {"path": "/path/to/file.py"}}
```

#### `getOpenFiles`
List currently open files in VS Code.

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "count": 5,
    "files": [
      {"uri": "...", "path": "...", "languageId": "python", "isDirty": false, "lineCount": 150}
    ]
  }
}
```

#### `getActiveFile`
Get the currently active file with its diagnostics.

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "active": true,
    "uri": "file:///path/to/file.py",
    "path": "/path/to/file.py",
    "languageId": "python",
    "isDirty": false,
    "lineCount": 150,
    "selection": {"line": 25, "column": 10},
    "diagnostics": [...]
  }
}
```

#### `executeCommand`
Execute a whitelisted VS Code command.

**Allowed Commands:**
- `ck3lens.validateFile`
- `ck3lens.validateWorkspace`
- `ck3lens.refreshViews`
- `ck3lens.initSession`
- `workbench.action.problems.focus`
- `editor.action.marker.next`
- `editor.action.marker.prev`

**Request:**
```json
{"jsonrpc": "2.0", "id": 1, "method": "executeCommand", "params": {"command": "ck3lens.refreshViews"}}
```

## Client API (MCP Server)

### File: `ck3lens/ipc_client.py`

#### VSCodeIPCClient Class

```python
from ck3lens.ipc_client import VSCodeIPCClient

# Context manager usage (recommended)
with VSCodeIPCClient() as client:
    # Test connection
    result = client.ping()
    
    # Get diagnostics for a file
    diags = client.get_diagnostics("/path/to/file.py")
    
    # Get all errors
    all_diags = client.get_all_diagnostics(severity="error")
    
    # Get error summary
    summary = client.get_workspace_errors()

# Manual usage
client = VSCodeIPCClient(port=9847, timeout=10.0)
client.connect()
try:
    result = client.ping()
finally:
    client.close()
```

#### Convenience Functions

```python
from ck3lens.ipc_client import get_vscode_diagnostics, get_vscode_error_summary, is_vscode_available

# Check if VS Code is running
if is_vscode_available():
    # Get diagnostics
    result = get_vscode_diagnostics("/path/to/file.py")
    
    # Get error summary
    summary = get_vscode_error_summary()
```

### MCP Tool: `ck3_vscode`

The unified MCP tool provides access to all IPC operations:

```python
# Check server status
ck3_vscode(command="status")
# Returns: {"available": true, "message": "VS Code IPC server is running"}

# Get file diagnostics
ck3_vscode(command="diagnostics", path="/path/to/file.py")

# Get all diagnostics with filters
ck3_vscode(command="all_diagnostics", severity="error", source="Pylance", limit=50)

# Get workspace error summary
ck3_vscode(command="errors_summary")

# Trigger file validation
ck3_vscode(command="validate_file", path="/path/to/file.py")

# Get open files
ck3_vscode(command="open_files")

# Get active file
ck3_vscode(command="active_file")
```

## Configuration

### VS Code Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `ck3lens.ipcPort` | number | 9847 | TCP port for diagnostics IPC server |

### Example settings.json
```json
{
  "ck3lens.ipcPort": 9847
}
```

## Security Considerations

1. **Localhost Only**: Server binds to 127.0.0.1, not accessible from network
2. **Command Whitelist**: Only specific VS Code commands can be executed
3. **No Write Operations**: Server is read-only for diagnostics data
4. **Process Isolation**: Each VS Code window has its own server instance

## Error Handling

### Connection Errors

When VS Code is not running or extension not active:

```python
{
    "error": True,
    "message": "Cannot connect to VS Code IPC server on port 9847. Make sure the CK3 Lens extension is active in VS Code.",
    "suggestion": "Ensure VS Code is running with CK3 Lens extension active"
}
```

### Port Conflicts

If port 9847 is in use, server automatically tries port 9848.

## Troubleshooting

### Server Not Starting

1. Check VS Code Output panel → "CK3 Lens" for startup messages
2. Verify extension is activated (check status bar)
3. Check if port is in use: `netstat -an | findstr 9847`

### Client Cannot Connect

1. Run `ck3_vscode(command="status")` to check availability
2. Check temp file exists: `%TEMP%\ck3lens_ipc_port`
3. Verify firewall isn't blocking localhost connections

### Stale Port File

If VS Code crashed, the port file may be stale. The client checks the timestamp and ignores files older than 1 hour.

## File Locations

| Component | Path |
|-----------|------|
| Server (TypeScript) | `tools/ck3lens-explorer/src/ipc/diagnosticsServer.ts` |
| Client (Python) | `tools/ck3lens_mcp/ck3lens/ipc_client.py` |
| MCP Tool Wrapper | `tools/ck3lens_mcp/server.py` → `ck3_vscode()` |
| Implementation | `tools/ck3lens_mcp/ck3lens/unified_tools.py` → `ck3_vscode_impl()` |
| Port File | `{TEMP}/ck3lens_ipc_port` |

## Comparison with Pylance MCP Tools

| Feature | Pylance MCP | CK3 Lens IPC |
|---------|-------------|--------------|
| Python diagnostics | ✅ | ✅ (via VS Code API) |
| CK3 script diagnostics | ❌ | ✅ |
| Works without VS Code | ❌ | ❌ |
| Custom command execution | ❌ | ✅ (whitelisted) |
| File validation trigger | Limited | ✅ |
| Workspace error summary | ❌ | ✅ |

The IPC server complements Pylance MCP tools by providing access to ALL diagnostics in VS Code, not just Python-specific ones.
