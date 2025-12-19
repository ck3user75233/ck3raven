#!/usr/bin/env python3
"""
CK3 Lens Explorer - Python Bridge Server

JSON-RPC server that bridges VS Code extension to ck3raven functionality.
Runs as a child process of the VS Code extension, communicating via stdio.
"""

import json
import sys
import os
from pathlib import Path

# Add ck3raven to path
SCRIPT_DIR = Path(__file__).parent
CKRAVEN_ROOT = SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(CKRAVEN_ROOT / "src"))

# Now we can import ck3raven
try:
    from ck3raven.parser import parse_source, LexerError, ParseError
    from ck3raven.db.search import SearchEngine
    from ck3raven.db.models import DBSession
    CKRAVEN_AVAILABLE = True
except ImportError as e:
    CKRAVEN_AVAILABLE = False
    IMPORT_ERROR = str(e)
    # Define dummy exception types for when imports fail
    class LexerError(Exception):
        pass
    class ParseError(Exception):
        pass


class CK3LensBridge:
    """Bridge server providing JSON-RPC interface to ck3raven."""
    
    def __init__(self):
        self.db_path = None
        self.session = None
        self.search_engine = None
        self.initialized = False
        
    def handle_request(self, request: dict) -> dict:
        """Handle a JSON-RPC request."""
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")
        
        try:
            result = self.dispatch(method, params)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
    
    def dispatch(self, method: str, params: dict) -> dict:
        """Dispatch method call to appropriate handler."""
        handlers = {
            "init_session": self.init_session,
            "parse_content": self.parse_content,
            "lint_file": self.lint_file,
            "search_symbols": self.search_symbols,
            "get_file": self.get_file,
            "list_files": self.list_files,
            "get_conflicts": self.get_conflicts,
            "confirm_not_exists": self.confirm_not_exists,
            "list_live_mods": self.list_live_mods,
            "read_live_file": self.read_live_file,
            "write_file": self.write_file,
            "git_status": self.git_status,
        }
        
        handler = handlers.get(method)
        if not handler:
            raise ValueError(f"Unknown method: {method}")
        
        return handler(params)
    
    def init_session(self, params: dict) -> dict:
        """Initialize session with database."""
        if not CKRAVEN_AVAILABLE:
            return {
                "error": f"ck3raven not available: {IMPORT_ERROR}",
                "initialized": False
            }
        
        db_path = params.get("db_path")
        if not db_path:
            db_path = Path.home() / ".ck3raven" / "ck3raven.db"
        
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            return {
                "error": f"Database not found: {db_path}",
                "initialized": False
            }
        
        # TODO: Initialize actual database session
        self.initialized = True
        
        return {
            "initialized": True,
            "db_path": str(self.db_path),
            "mod_root": str(Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"),
            "live_mods": {
                "mods": [
                    {"modId": "MSC", "name": "Mini Super Compatch", "path": "", "exists": True},
                    {"modId": "MSCRE", "name": "MSCRE", "path": "", "exists": True},
                    {"modId": "LRE", "name": "Lowborn Rise Expanded", "path": "", "exists": True}
                ]
            }
        }
    
    def parse_content(self, params: dict) -> dict:
        """Parse CK3 script content and return AST or errors with rich diagnostics."""
        content = params.get("content", "")
        filename = params.get("filename", "inline.txt")
        include_warnings = params.get("include_warnings", True)
        
        if not CKRAVEN_AVAILABLE:
            return {"errors": [{"line": 1, "message": "Parser not available"}]}
        
        errors = []
        warnings = []
        
        try:
            ast = parse_source(content, filename)
            
            # Run additional semantic checks if parse succeeded
            if include_warnings:
                warnings = self._check_semantic_issues(content, ast, filename)
            
            return {
                "success": True,
                "ast": self._ast_to_dict(ast),
                "errors": [],
                "warnings": warnings,
                "stats": {
                    "lines": len(content.split('\n')),
                    "blocks": self._count_blocks(ast)
                }
            }
        except LexerError as e:
            # Lexer error - precise location info
            return {
                "success": False,
                "errors": [{
                    "line": e.line,
                    "column": e.column,
                    "message": str(e),
                    "severity": "error",
                    "code": "LEX001",
                    "recovery_hint": self._get_recovery_hint("lexer", str(e))
                }],
                "warnings": []
            }
        except ParseError as e:
            # Parse error - may have partial AST
            line = getattr(e, 'line', 1)
            column = getattr(e, 'column', 1)
            return {
                "success": False,
                "errors": [{
                    "line": line,
                    "column": column,
                    "message": str(e),
                    "severity": "error",
                    "code": "PARSE001",
                    "recovery_hint": self._get_recovery_hint("parse", str(e))
                }],
                "warnings": []
            }
        except Exception as e:
            # Generic error - try to extract location
            error_str = str(e)
            line = 1
            column = 1
            if "line" in error_str.lower():
                import re
                match = re.search(r'line\s*(\d+)', error_str, re.I)
                if match:
                    line = int(match.group(1))
                col_match = re.search(r'column\s*(\d+)', error_str, re.I)
                if col_match:
                    column = int(col_match.group(1))
            
            return {
                "success": False,
                "errors": [{
                    "line": line,
                    "column": column,
                    "message": error_str,
                    "severity": "error",
                    "code": "ERR001",
                    "recovery_hint": self._get_recovery_hint("generic", error_str)
                }],
                "warnings": []
            }
    
    def _check_semantic_issues(self, content: str, ast, filename: str) -> list:
        """Check for semantic issues that aren't parse errors."""
        warnings = []
        lines = content.split('\n')
        
        # Check for common issues
        for i, line in enumerate(lines, 1):
            # Trailing whitespace
            if line.rstrip() != line and line.strip():
                pass  # Too noisy, skip
            
            # Very long lines (>200 chars)
            if len(line) > 200:
                warnings.append({
                    "line": i,
                    "column": 200,
                    "message": f"Line exceeds 200 characters ({len(line)} chars)",
                    "severity": "info",
                    "code": "STYLE001"
                })
            
            # Check for tabs vs spaces inconsistency (just report)
            if '\t' in line and '    ' in line:
                warnings.append({
                    "line": i,
                    "column": 1,
                    "message": "Mixed tabs and spaces in indentation",
                    "severity": "hint",
                    "code": "STYLE002"
                })
        
        # Check for unbalanced braces (sanity check)
        open_braces = content.count('{')
        close_braces = content.count('}')
        if open_braces != close_braces:
            warnings.append({
                "line": 1,
                "column": 1,
                "message": f"Unbalanced braces: {open_braces} open, {close_braces} close",
                "severity": "warning",
                "code": "STRUCT001"
            })
        
        return warnings
    
    def _get_recovery_hint(self, error_type: str, message: str) -> str:
        """Generate recovery hints based on error type and message."""
        msg_lower = message.lower()
        
        if "unterminated string" in msg_lower:
            return "Add a closing quote (\") to complete the string"
        elif "unexpected" in msg_lower and "}" in msg_lower:
            return "Check for missing opening brace { or extra closing brace }"
        elif "unexpected" in msg_lower and "{" in msg_lower:
            return "Check for missing = before the opening brace"
        elif "expected" in msg_lower and "=" in msg_lower:
            return "Add = between the key and value"
        elif "eof" in msg_lower or "end of file" in msg_lower:
            return "Check for unclosed braces or incomplete blocks"
        elif "invalid" in msg_lower and "character" in msg_lower:
            return "Remove or escape the invalid character"
        else:
            return "Check syntax near the reported location"
    
    def _count_blocks(self, ast) -> int:
        """Count total blocks in AST."""
        if ast is None:
            return 0
        count = 1 if hasattr(ast, 'children') else 0
        if hasattr(ast, 'children'):
            for child in ast.children:
                count += self._count_blocks(child)
        if hasattr(ast, 'value') and hasattr(ast.value, 'children'):
            count += self._count_blocks(ast.value)
        return count
    
    def lint_file(self, params: dict) -> dict:
        """Lint a file - parse, validate structure, and optionally check references."""
        content = params.get("content", "")
        filename = params.get("filename", "inline.txt")
        check_references = params.get("check_references", False)
        check_style = params.get("check_style", True)
        
        # First, parse with full diagnostics
        parse_result = self.parse_content({
            "content": content, 
            "filename": filename,
            "include_warnings": check_style
        })
        
        errors = parse_result.get("errors", [])
        warnings = parse_result.get("warnings", [])
        
        # If parse succeeded and reference checking is enabled
        if parse_result.get("success") and check_references and self.initialized:
            ref_errors = self._check_references(content, filename)
            for ref_error in ref_errors:
                if ref_error.get("severity") == "error":
                    errors.append(ref_error)
                else:
                    warnings.append(ref_error)
        
        return {
            "errors": errors,
            "warnings": warnings,
            "parse_success": parse_result.get("success", False),
            "stats": parse_result.get("stats", {})
        }
    
    def _check_references(self, content: str, filename: str) -> list:
        """Check for undefined references in the content."""
        issues = []
        
        # Known trigger/effect prefixes that should be validated
        known_scopes = {
            'root', 'this', 'scope', 'prev', 'from', 'faith', 'culture',
            'liege', 'holder', 'realm', 'capital', 'county', 'duchy', 
            'kingdom', 'empire', 'house', 'dynasty', 'primary_title'
        }
        
        # Check for common reference patterns
        import re
        
        # Check event references: event_id = namespace.number
        event_refs = re.findall(r'\b(\w+\.\d+)\b', content)
        # TODO: Validate against known events when database is connected
        
        # Check flag references: has_character_flag = my_flag
        flag_refs = re.findall(r'has_(?:character|county|realm|dynasty|house|faith|culture)_flag\s*=\s*(\w+)', content)
        # TODO: Cross-reference with flag definitions
        
        return issues
    
    def search_symbols(self, params: dict) -> dict:
        """Search for symbols in the database."""
        query = params.get("query", "")
        symbol_type = params.get("symbol_type")
        limit = params.get("limit", 50)
        adjacency = params.get("adjacency", "auto")
        
        # TODO: Implement actual database search
        return {
            "results": [],
            "adjacencies": [],
            "query_patterns": [query]
        }
    
    def get_file(self, params: dict) -> dict:
        """Get file content from database."""
        file_path = params.get("file_path", "")
        include_ast = params.get("include_ast", False)
        
        # TODO: Implement actual file retrieval
        return {"error": "Not implemented"}
    
    def list_files(self, params: dict) -> dict:
        """List files in a folder."""
        folder = params.get("folder", "")
        pattern = params.get("pattern", "*.txt")
        
        # TODO: Implement actual file listing
        return {"files": []}
    
    def get_conflicts(self, params: dict) -> dict:
        """Get conflicts for a folder or symbol type."""
        path_pattern = params.get("path_pattern")
        symbol_type = params.get("symbol_type")
        
        # TODO: Implement actual conflict detection
        return {"conflicts": []}
    
    def confirm_not_exists(self, params: dict) -> dict:
        """Exhaustive search to confirm something doesn't exist."""
        name = params.get("name", "")
        symbol_type = params.get("symbol_type")
        
        # TODO: Implement exhaustive search
        return {
            "can_claim_not_exists": False,
            "similar_matches": []
        }
    
    def list_live_mods(self, params: dict) -> dict:
        """List live mods that can be written to."""
        mod_root = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
        
        live_mod_names = [
            "Mini Super Compatch",
            "MSCRE",
            "Lowborn Rise Expanded"
        ]
        
        mods = []
        for name in live_mod_names:
            path = mod_root / name
            mods.append({
                "modId": name.replace(" ", "_"),
                "name": name,
                "path": str(path),
                "exists": path.exists()
            })
        
        return {"live_mods": {"mods": mods}}
    
    def read_live_file(self, params: dict) -> dict:
        """Read file from live mod."""
        mod_name = params.get("mod_name", "")
        rel_path = params.get("rel_path", "")
        
        mod_root = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
        file_path = mod_root / mod_name / rel_path
        
        if not file_path.exists():
            return {"exists": False, "content": None}
        
        try:
            content = file_path.read_text(encoding="utf-8-sig")
            return {"exists": True, "content": content}
        except Exception as e:
            return {"exists": False, "error": str(e)}
    
    def write_file(self, params: dict) -> dict:
        """Write file to live mod."""
        mod_name = params.get("mod_name", "")
        rel_path = params.get("rel_path", "")
        content = params.get("content", "")
        validate_syntax = params.get("validate_syntax", True)
        
        # Validate syntax first
        if validate_syntax:
            parse_result = self.parse_content({"content": content})
            if parse_result.get("errors"):
                return {
                    "success": False,
                    "errors": parse_result["errors"]
                }
        
        mod_root = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
        file_path = mod_root / mod_name / rel_path
        
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8-sig")
            return {"success": True, "bytes_written": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def git_status(self, params: dict) -> dict:
        """Get git status for a live mod."""
        mod_name = params.get("mod_name", "")
        
        mod_root = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
        mod_path = mod_root / mod_name
        
        if not (mod_path / ".git").exists():
            return {"error": "Not a git repository"}
        
        import subprocess
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=mod_path,
                capture_output=True,
                text=True
            )
            
            staged = []
            unstaged = []
            untracked = []
            
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                status = line[:2]
                filepath = line[3:]
                
                if status[0] in "MADRC":
                    staged.append(filepath)
                if status[1] in "MD":
                    unstaged.append(filepath)
                if status == "??":
                    untracked.append(filepath)
            
            return {
                "staged": staged,
                "unstaged": unstaged,
                "untracked": untracked
            }
        except Exception as e:
            return {"error": str(e)}
    
    def _ast_to_dict(self, ast) -> dict:
        """Convert AST node to dictionary."""
        if ast is None:
            return None
        
        result = {"type": type(ast).__name__}
        
        if hasattr(ast, "children"):
            result["children"] = [self._ast_to_dict(c) for c in ast.children]
        if hasattr(ast, "name"):
            result["name"] = ast.name
        if hasattr(ast, "value"):
            result["value"] = str(ast.value) if ast.value else None
        if hasattr(ast, "line"):
            result["line"] = ast.line
        
        return result


def main():
    """Main entry point - run JSON-RPC server over stdio."""
    bridge = CK3LensBridge()
    
    # Process requests from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        try:
            request = json.loads(line)
            response = bridge.handle_request(request)
            print(json.dumps(response), flush=True)
        except json.JSONDecodeError as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": f"Parse error: {e}"
                }
            }
            print(json.dumps(error_response), flush=True)


if __name__ == "__main__":
    main()
