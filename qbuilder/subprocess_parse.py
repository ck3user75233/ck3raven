"""
Subprocess-based parsing with hard timeout.

Runs parsing in a subprocess to provide:
- Hard timeout enforcement (kills subprocess on timeout)
- No zombie processes (explicit cleanup)
- Parse failures don't crash the main worker

The subprocess communicates results via stdout JSON.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

# Default timeout for parsing a single file (seconds)
DEFAULT_PARSE_TIMEOUT = 30

# Maximum allowed timeout
MAX_PARSE_TIMEOUT = 120


class ParseTimeoutError(Exception):
    """Raised when parsing exceeds the timeout."""
    def __init__(self, filepath: str, timeout: int):
        self.filepath = filepath
        self.timeout = timeout
        super().__init__(f"Parse timeout after {timeout}s: {filepath}")


class ParseSubprocessError(Exception):
    """Raised when the parse subprocess fails unexpectedly."""
    def __init__(self, filepath: str, error: str, returncode: int = -1):
        self.filepath = filepath
        self.error = error
        self.returncode = returncode
        super().__init__(f"Parse subprocess failed ({returncode}): {error}")


@dataclass
class ParseResult:
    """Result from subprocess parse."""
    success: bool
    ast_json: Optional[str] = None
    node_count: int = 0
    error: Optional[str] = None
    error_type: Optional[str] = None


def parse_file_in_subprocess(
    filepath: Path,
    timeout: int = DEFAULT_PARSE_TIMEOUT,
    python_exe: Optional[str] = None,
) -> ParseResult:
    """
    Parse a file in a subprocess with hard timeout.
    
    On timeout, the subprocess is killed and ParseTimeoutError is raised.
    On parse error, ParseResult with success=False is returned.
    
    Args:
        filepath: Absolute path to the file to parse
        timeout: Timeout in seconds (capped at MAX_PARSE_TIMEOUT)
        python_exe: Python executable to use (defaults to sys.executable)
    
    Returns:
        ParseResult with AST JSON if successful
        
    Raises:
        ParseTimeoutError: If parsing exceeds timeout
        ParseSubprocessError: If subprocess fails unexpectedly
    """
    timeout = min(timeout, MAX_PARSE_TIMEOUT)
    python_exe = python_exe or sys.executable
    
    # The subprocess script - kept minimal to reduce overhead
    # Writes JSON result to stdout
    subprocess_code = '''
import json
import sys
from pathlib import Path

filepath = Path(sys.argv[1])

try:
    # Add src to path for imports
    import os
    repo_root = Path(__file__).parent.parent if "__file__" in dir() else Path.cwd()
    sys.path.insert(0, str(Path(os.environ.get("CK3RAVEN_ROOT", ".")) / "src"))
    
    from ck3raven.parser import parse_file
    from ck3raven.db.ast_cache import serialize_ast, count_ast_nodes, deserialize_ast
    
    ast_node = parse_file(str(filepath))
    ast_blob = serialize_ast(ast_node)  # returns bytes (JSON)
    ast_dict = deserialize_ast(ast_blob)
    node_count = count_ast_nodes(ast_dict)
    
    # ast_blob is bytes, decode to string for JSON output
    ast_str = ast_blob.decode('utf-8') if isinstance(ast_blob, bytes) else ast_blob
    
    result = {
        "success": True,
        "ast_json": ast_str,
        "node_count": node_count,
    }
except Exception as e:
    result = {
        "success": False,
        "error": str(e),
        "error_type": type(e).__name__,
    }

print(json.dumps(result))
'''
    
    # Get repo root for CK3RAVEN_ROOT env var
    repo_root = Path(__file__).parent.parent
    
    env = {
        **dict(__import__('os').environ),
        "CK3RAVEN_ROOT": str(repo_root),
    }
    
    try:
        proc = subprocess.run(
            [python_exe, "-c", subprocess_code, str(filepath)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(repo_root),
        )
    except subprocess.TimeoutExpired:
        # subprocess.run automatically kills the process on TimeoutExpired
        # No manual cleanup needed - the process is already terminated
        raise ParseTimeoutError(str(filepath), timeout)
    
    if proc.returncode != 0:
        # Subprocess failed (not a parse error, an execution error)
        stderr = proc.stderr.strip() if proc.stderr else "Unknown error"
        raise ParseSubprocessError(str(filepath), stderr, proc.returncode)
    
    # Parse the JSON result from stdout
    stdout = proc.stdout.strip()
    if not stdout:
        raise ParseSubprocessError(str(filepath), "Empty output from subprocess", 0)
    
    try:
        result_dict = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise ParseSubprocessError(str(filepath), f"Invalid JSON from subprocess: {e}", 0)
    
    return ParseResult(
        success=result_dict.get("success", False),
        ast_json=result_dict.get("ast_json"),
        node_count=result_dict.get("node_count", 0),
        error=result_dict.get("error"),
        error_type=result_dict.get("error_type"),
    )
