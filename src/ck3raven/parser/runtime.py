"""
Canonical Parser Runtime — subprocess-based parsing with hard timeout.

THIS IS THE ONLY WAY TO RUN THE PARSER.

All callers (qbuilder worker, MCP tools, CLI) MUST use this module.
Direct calls to Parser().parse() are PROHIBITED outside this module.

The parser runs in an isolated subprocess to provide:
- Hard timeout enforcement (kills subprocess on timeout)
- No zombie processes (explicit cleanup)  
- Parse failures don't crash the calling process
- MCP tools remain responsive even on pathological files

Usage:
    from ck3raven.parser.runtime import parse_file, parse_text
    
    # Parse a file
    result = parse_file(Path("/path/to/file.txt"), timeout=30)
    if result.success:
        ast_dict = json.loads(result.ast_json)
    
    # Parse content string
    result = parse_text(content, filename="inline.txt", timeout=10)
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


# Default timeout for parsing (seconds)
DEFAULT_PARSE_TIMEOUT = 30

# Maximum allowed timeout
MAX_PARSE_TIMEOUT = 120


class ParseTimeoutError(Exception):
    """Raised when parsing exceeds the timeout."""
    def __init__(self, source: str, timeout: int):
        self.source = source
        self.timeout = timeout
        super().__init__(f"Parse timeout after {timeout}s: {source}")


class ParseSubprocessError(Exception):
    """Raised when the parse subprocess fails unexpectedly."""
    def __init__(self, source: str, error: str, returncode: int = -1):
        self.source = source
        self.error = error
        self.returncode = returncode
        super().__init__(f"Parse subprocess failed ({returncode}): {error}")


@dataclass
class ParseDiagnostic:
    """A single parse error or warning."""
    line: int
    column: int
    end_line: int
    end_column: int
    message: str
    code: str = "PARSE_ERROR"
    severity: str = "error"


@dataclass
class ParseResult:
    """Result from subprocess parse."""
    success: bool
    ast_json: Optional[str] = None
    node_count: int = 0
    error: Optional[str] = None
    error_type: Optional[str] = None
    diagnostics: Optional[List[ParseDiagnostic]] = None


def _get_repo_root() -> Path:
    """Get the ck3raven repository root."""
    # This file is at src/ck3raven/parser/runtime.py
    # Repo root is 4 levels up
    return Path(__file__).parent.parent.parent.parent


def _run_parse_subprocess(
    subprocess_code: str,
    args: List[str],
    timeout: int,
    source_name: str,
    input_data: Optional[str] = None,
) -> ParseResult:
    """
    Run parsing in a subprocess with timeout.
    
    Internal helper - use parse_file() or parse_text() instead.
    """
    timeout = min(timeout, MAX_PARSE_TIMEOUT)
    python_exe = sys.executable
    repo_root = _get_repo_root()
    
    env = {
        **os.environ,
        "CK3RAVEN_ROOT": str(repo_root),
    }
    
    try:
        proc = subprocess.run(
            [python_exe, "-c", subprocess_code] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(repo_root),
            input=input_data,
        )
    except subprocess.TimeoutExpired:
        # subprocess.run automatically kills the process on TimeoutExpired
        raise ParseTimeoutError(source_name, timeout)
    
    if proc.returncode != 0:
        stderr = proc.stderr.strip() if proc.stderr else "Unknown error"
        raise ParseSubprocessError(source_name, stderr, proc.returncode)
    
    stdout = proc.stdout.strip()
    if not stdout:
        raise ParseSubprocessError(source_name, "Empty output from subprocess", 0)
    
    try:
        result_dict = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise ParseSubprocessError(source_name, f"Invalid JSON from subprocess: {e}", 0)
    
    # Parse diagnostics if present
    diagnostics = None
    if result_dict.get("diagnostics"):
        diagnostics = [
            ParseDiagnostic(
                line=d.get("line", 0),
                column=d.get("column", 0),
                end_line=d.get("end_line", 0),
                end_column=d.get("end_column", 0),
                message=d.get("message", ""),
                code=d.get("code", "PARSE_ERROR"),
                severity=d.get("severity", "error"),
            )
            for d in result_dict["diagnostics"]
        ]
    
    return ParseResult(
        success=result_dict.get("success", False),
        ast_json=result_dict.get("ast_json"),
        node_count=result_dict.get("node_count", 0),
        error=result_dict.get("error"),
        error_type=result_dict.get("error_type"),
        diagnostics=diagnostics,
    )


# Subprocess code for file parsing
_PARSE_FILE_CODE = '''
import json
import sys
import os
from pathlib import Path

filepath = Path(sys.argv[1])

try:
    sys.path.insert(0, str(Path(os.environ.get("CK3RAVEN_ROOT", ".")) / "src"))
    
    from ck3raven.parser.parser import parse_file as _parse_file
    from ck3raven.db.ast_cache import serialize_ast, count_ast_nodes, deserialize_ast
    
    ast_node = _parse_file(str(filepath))
    ast_blob = serialize_ast(ast_node)
    ast_dict = deserialize_ast(ast_blob)
    node_count = count_ast_nodes(ast_dict)
    
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


# Subprocess code for text parsing (content via stdin)
_PARSE_TEXT_CODE = '''
import json
import sys
import os
from pathlib import Path

filename = sys.argv[1] if len(sys.argv) > 1 else "<inline>"
content = sys.stdin.read()

try:
    sys.path.insert(0, str(Path(os.environ.get("CK3RAVEN_ROOT", ".")) / "src"))
    
    from ck3raven.parser.parser import parse_source as _parse_source
    from ck3raven.db.ast_cache import serialize_ast, count_ast_nodes, deserialize_ast
    
    ast_node = _parse_source(content, filename)
    ast_blob = serialize_ast(ast_node)
    ast_dict = deserialize_ast(ast_blob)
    node_count = count_ast_nodes(ast_dict)
    
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


# Subprocess code for text parsing with error recovery
_PARSE_TEXT_RECOVERING_CODE = '''
import json
import sys
import os
from pathlib import Path

filename = sys.argv[1] if len(sys.argv) > 1 else "<inline>"
content = sys.stdin.read()

try:
    sys.path.insert(0, str(Path(os.environ.get("CK3RAVEN_ROOT", ".")) / "src"))
    
    from ck3raven.parser.parser import parse_source_recovering as _parse_source_recovering
    from ck3raven.db.ast_cache import serialize_ast, count_ast_nodes, deserialize_ast
    
    parse_result = _parse_source_recovering(content, filename)
    
    if parse_result.ast:
        ast_blob = serialize_ast(parse_result.ast)
        ast_dict = deserialize_ast(ast_blob)
        node_count = count_ast_nodes(ast_dict)
        ast_str = ast_blob.decode('utf-8') if isinstance(ast_blob, bytes) else ast_blob
    else:
        ast_str = None
        node_count = 0
    
    diagnostics = [
        {
            "line": d.line,
            "column": d.column,
            "end_line": d.end_line,
            "end_column": d.end_column,
            "message": d.message,
            "code": d.code,
            "severity": d.severity,
        }
        for d in parse_result.diagnostics
    ]
    
    result = {
        "success": parse_result.success,
        "ast_json": ast_str,
        "node_count": node_count,
        "diagnostics": diagnostics,
    }
except Exception as e:
    result = {
        "success": False,
        "error": str(e),
        "error_type": type(e).__name__,
    }

print(json.dumps(result))
'''


def parse_file(
    filepath: Path,
    timeout: int = DEFAULT_PARSE_TIMEOUT,
) -> ParseResult:
    """
    Parse a file in a subprocess with hard timeout.
    
    CANONICAL API: All file parsing MUST use this function.
    
    Args:
        filepath: Absolute path to the file to parse
        timeout: Timeout in seconds (capped at MAX_PARSE_TIMEOUT)
    
    Returns:
        ParseResult with AST JSON if successful
        
    Raises:
        ParseTimeoutError: If parsing exceeds timeout
        ParseSubprocessError: If subprocess fails unexpectedly
    """
    return _run_parse_subprocess(
        _PARSE_FILE_CODE,
        [str(filepath)],
        timeout,
        str(filepath),
    )


def parse_text(
    content: str,
    filename: str = "<inline>",
    timeout: int = DEFAULT_PARSE_TIMEOUT,
    recovering: bool = False,
) -> ParseResult:
    """
    Parse text content in a subprocess with hard timeout.
    
    CANONICAL API: All content parsing MUST use this function.
    
    Args:
        content: Text content to parse
        filename: Filename for error messages
        timeout: Timeout in seconds (capped at MAX_PARSE_TIMEOUT)
        recovering: If True, use error-recovering parser (collects all errors)
    
    Returns:
        ParseResult with AST JSON if successful.
        If recovering=True, diagnostics field contains all parse errors.
        
    Raises:
        ParseTimeoutError: If parsing exceeds timeout
        ParseSubprocessError: If subprocess fails unexpectedly
    """
    code = _PARSE_TEXT_RECOVERING_CODE if recovering else _PARSE_TEXT_CODE
    return _run_parse_subprocess(
        code,
        [filename],
        timeout,
        filename,
        input_data=content,
    )
