"""
Persistent Parse Worker — Long-lived subprocess for amortized parsing.

THIS IS A SUBPROCESS ENTRY POINT. Do not import this module in the main process.

Protocol:
- Supervisor spawns this process
- Worker imports parser/serde ONCE at startup
- Worker reads JSON lines from stdin, parses, writes JSON lines to stdout
- Worker never touches the database
- Worker exits when stdin closes or on fatal error

Request format (JSON line):
    {"id": "uuid", "path": "/abs/path/to/file.txt", "timeout_ms": 30000}
    
    OR for text content:
    {"id": "uuid", "content": "...", "filename": "inline.txt", "timeout_ms": 30000}

Response format (JSON line):
    Success:
    {"id": "uuid", "ok": true, "ast_json": "...", "node_count": 1234}
    
    Failure:
    {"id": "uuid", "ok": false, "error_type": "ParseError", "error": "message"}

Usage:
    python -m ck3raven.parser.parse_worker
"""

import json
import sys
import signal
import traceback
from pathlib import Path

# Recycle after this many parses to bound memory leaks
MAX_PARSES_BEFORE_RECYCLE = 5000

# Track parse count for recycling
_parse_count = 0


def _setup_signal_handlers():
    """Ignore SIGINT in worker - let supervisor handle it."""
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (ValueError, OSError):
        pass  # Not supported on this platform/thread


def _read_ck3_text(path: Path) -> str:
    """Read a CK3 text file with encoding fallback."""
    try:
        return path.read_text(encoding='utf-8-sig')
    except UnicodeDecodeError:
        return path.read_text(encoding='latin-1')


def handle_request(request: dict) -> dict:
    """
    Handle a single parse request.
    
    Returns response dict (always has 'id' and 'ok' fields).
    """
    global _parse_count
    
    req_id = request.get("id", "unknown")
    
    try:
        # Import parser lazily (but only once per worker lifetime)
        from ck3raven.parser.parser import parse_file as _parse_file
        from ck3raven.parser.parser import parse_source as _parse_source
        from ck3raven.parser.ast_serde import serialize_ast, count_ast_nodes, deserialize_ast
        
        if "path" in request:
            # File mode
            filepath = Path(request["path"])
            if not filepath.exists():
                return {
                    "id": req_id,
                    "ok": False,
                    "error_type": "FileNotFoundError",
                    "error": f"File not found: {filepath}",
                }
            
            ast_node = _parse_file(str(filepath))
        
        elif "content" in request:
            # Content mode
            content = request["content"]
            filename = request.get("filename", "<inline>")
            ast_node = _parse_source(content, filename)
        
        else:
            return {
                "id": req_id,
                "ok": False,
                "error_type": "InvalidRequest",
                "error": "Request must have 'path' or 'content'",
            }
        
        # Serialize AST
        ast_blob = serialize_ast(ast_node)
        ast_dict = deserialize_ast(ast_blob)
        node_count = count_ast_nodes(ast_dict)
        
        ast_str = ast_blob.decode('utf-8') if isinstance(ast_blob, bytes) else ast_blob
        
        _parse_count += 1
        
        return {
            "id": req_id,
            "ok": True,
            "ast_json": ast_str,
            "node_count": node_count,
        }
    
    except Exception as e:
        return {
            "id": req_id,
            "ok": False,
            "error_type": type(e).__name__,
            "error": str(e),
        }


def worker_main():
    """
    Main worker loop. Reads JSON lines from stdin, writes responses to stdout.
    """
    global _parse_count
    
    _setup_signal_handlers()
    
    # Signal ready to supervisor
    sys.stdout.write(json.dumps({"ready": True, "pid": __import__("os").getpid()}) + "\n")
    sys.stdout.flush()
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            # Invalid JSON - respond with error
            response = {
                "id": "unknown",
                "ok": False,
                "error_type": "JSONDecodeError",
                "error": f"Invalid request JSON: {e}",
            }
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            continue
        
        # Check for shutdown command
        if request.get("command") == "shutdown":
            break
        
        # Handle parse request
        response = handle_request(request)
        
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
        
        # Check if we should recycle (exit so supervisor can respawn fresh worker)
        if _parse_count >= MAX_PARSES_BEFORE_RECYCLE:
            # Signal recycling
            sys.stdout.write(json.dumps({"recycle": True, "parses": _parse_count}) + "\n")
            sys.stdout.flush()
            break


if __name__ == "__main__":
    # Add src to path if running directly
    import os
    repo_root = Path(__file__).parent.parent.parent.parent
    sys.path.insert(0, str(repo_root / "src"))
    
    worker_main()
