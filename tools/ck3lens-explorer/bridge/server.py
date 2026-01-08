#!/usr/bin/env python3
"""
CK3 Lens Explorer - Python Bridge Server

JSON-RPC server that bridges VS Code extension to ck3raven functionality.
Runs as a child process of the VS Code extension, communicating via stdio.

ARCHITECTURE (January 2026):
- Playset operations use ck3lens.impl modules (shared with MCP server)
- NO playset_mods table queries (BANNED per CANONICAL_ARCHITECTURE.md)
- CVIDs are derived from playset_ops.get_playset_mods()
"""

import json
import sys
import os
import sqlite3
from pathlib import Path

# Add ck3raven to path - handle both development and installed extension cases
SCRIPT_DIR = Path(__file__).parent

def find_ck3raven_root():
    """Find ck3raven source directory."""
    # Check PYTHONPATH first (set by VS Code extension)
    if os.environ.get('PYTHONPATH'):
        pythonpath = Path(os.environ['PYTHONPATH'])
        if (pythonpath / 'ck3raven').exists():
            return pythonpath.parent  # PYTHONPATH points to src, return parent
    
    # Development mode: bridge is at tools/ck3lens-explorer/bridge/server.py
    # So ck3raven root is 3 levels up
    dev_root = SCRIPT_DIR.parent.parent.parent
    if (dev_root / "src" / "ck3raven").exists():
        return dev_root
    
    # Installed extension mode: check environment variable or common locations
    common_locations = [
        Path(os.environ.get("CK3RAVEN_PATH", "")) if os.environ.get("CK3RAVEN_PATH") else None,
        Path.home() / ".ck3raven" / "ck3raven",  # Standard user data location
        Path.home() / "ck3raven",
    ]
    for loc in common_locations:
        if loc and (loc / "src" / "ck3raven").exists():
            return loc
    
    return None

CKRAVEN_ROOT = find_ck3raven_root()
if CKRAVEN_ROOT:
    sys.path.insert(0, str(CKRAVEN_ROOT / "src"))
    # Also add ck3lens_mcp for ck3lens module imports
    ck3lens_mcp = CKRAVEN_ROOT / "tools" / "ck3lens_mcp"
    if ck3lens_mcp.exists():
        sys.path.insert(0, str(ck3lens_mcp))

# Now we can import ck3raven
try:
    from ck3raven.parser import parse_source, LexerError, ParseError
    from ck3raven.db.search import search_symbols, search_content, find_definition
    from ck3raven.db.schema import DEFAULT_DB_PATH, get_connection
    CKRAVEN_AVAILABLE = True
except ImportError as e:
    CKRAVEN_AVAILABLE = False
    IMPORT_ERROR = str(e)
    # Define dummy exception types for when imports fail
    class LexerError(Exception):
        pass
    class ParseError(Exception):
        pass

# Import impl modules for shared logic
IMPL_AVAILABLE = False
try:
    from ck3lens.impl import playset_ops, search_ops, file_ops, conflict_ops
    IMPL_AVAILABLE = True
except ImportError as e:
    IMPL_IMPORT_ERROR = str(e)


class CK3LensBridge:
    """Bridge server providing JSON-RPC interface to ck3raven.
    
    Playset operations use ck3lens.impl modules (shared with MCP server).
    This avoids the broken `from server import ck3_playset` pattern and
    prevents duplicating playset logic.
    """
    
    def __init__(self):
        self.db_path = None
        self.db_conn = None  # SQLite connection for search/parse operations
        self.session = None
        self.search_engine = None
        self.initialized = False
        self._active_cvids: set = set()  # CVIDs from active playset
        self._playset_name: str = None
        
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
            "read_local_file": self.read_local_file,
            "write_file": self.write_file,
            "git_status": self.git_status,
            "get_playset_mods": self.get_playset_mods,
            "get_top_level_folders": self.get_top_level_folders,
            # Error/Conflict Analysis
            "get_errors": self.get_errors,
            "get_cascade_patterns": self.get_cascade_patterns,
            "list_conflict_units": self.list_conflict_units,
            "get_conflict_detail": self.get_conflict_detail,
            "create_override_patch": self.create_override_patch,
            "list_playsets": self.list_playsets,
            "reorder_mod": self.reorder_mod,
        }
        
        handler = handlers.get(method)
        if not handler:
            raise ValueError(f"Unknown method: {method}")
        
        return handler(params)
    
    def _refresh_active_cvids(self):
        """Refresh cached CVIDs from active playset using impl module."""
        if not IMPL_AVAILABLE:
            return
        
        try:
            # Use playset_ops to get active playset mods
            result = playset_ops.get_playset_mods()
            if result.get("success"):
                self._playset_name = result.get("playset_name")
                # Extract CVIDs from mods
                # Note: playset JSON has content_version_id if mods are indexed
                mods = result.get("mods", [])
                self._active_cvids = set()
                for mod in mods:
                    cvid = mod.get("content_version_id")
                    if cvid:
                        self._active_cvids.add(cvid)
        except Exception:
            pass
    
    def init_session(self, params: dict) -> dict:
        """Initialize session with database connection.
        
        Gets active playset info from impl modules.
        """
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
        
        # Connect to SQLite database
        try:
            self.db_conn = sqlite3.connect(str(self.db_path))
            self.db_conn.row_factory = sqlite3.Row
            
            # Get active playset info from impl module
            playset_name = None
            if IMPL_AVAILABLE:
                try:
                    result = playset_ops.get_active_playset()
                    if result.get("success"):
                        playset_name = result.get("playset_name")
                    
                    # Refresh CVIDs
                    self._refresh_active_cvids()
                except Exception:
                    pass
            
            self.initialized = True
            
            # Return mod root and local_mods_folder for the UI to derive editability
            mod_root = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
            local_mods_folder = str(mod_root)
            
            return {
                "initialized": True,
                "db_path": str(self.db_path),
                "mod_root": str(mod_root),
                "local_mods_folder": local_mods_folder,
                "playset_name": playset_name,
                "impl_available": IMPL_AVAILABLE,
            }
        except Exception as e:
            return {
                "error": f"Failed to connect to database: {e}",
                "initialized": False
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
        import re
        warnings = []
        lines = content.split('\n')
        
        # Keywords that don't need = before {
        no_equals_needed = {'if', 'else', 'else_if', 'while', 'switch', 'random', 'random_list', 'limit', 'trigger', 'modifier'}
        
        # Check for common issues line by line
        for i, line in enumerate(lines, 1):
            # Skip empty lines and comments
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            
            # Remove inline comments for pattern matching
            comment_pos = stripped.find('#')
            if comment_pos > 0:
                stripped = stripped[:comment_pos].strip()
            
            # Check for tabs vs spaces inconsistency
            if '\t' in line and '    ' in line:
                warnings.append({
                    "line": i,
                    "column": 1,
                    "message": "Mixed tabs and spaces in indentation",
                    "severity": "hint",
                    "code": "STYLE002"
                })
            
            # Check for "yes = " or "no = " (yes/no are values, not keys)
            yes_no_match = re.search(r'\b(yes|no)\s*=', stripped)
            if yes_no_match:
                col = line.find(yes_no_match.group(0)) + 1
                warnings.append({
                    "line": i,
                    "column": col,
                    "message": f'"{yes_no_match.group(1)}" is typically a value, not a key',
                    "severity": "hint",
                    "code": "STYLE003"
                })
            
            # Check for == (comparison operator used where = expected)
            # But only if it's not part of >=, <=, !=
            double_eq_match = re.search(r'(?<![!<>=])={2}(?!=)', stripped)
            if double_eq_match:
                col = line.find('==') + 1
                warnings.append({
                    "line": i,
                    "column": col,
                    "message": "Use single = for assignment; == is for comparisons in trigger blocks",
                    "severity": "hint",
                    "code": "STYLE004"
                })
            
            # Check for missing = before { (e.g., "my_block {" instead of "my_block = {")
            missing_eq_match = re.match(r'^(\w+)\s*\{', stripped)
            if missing_eq_match:
                key = missing_eq_match.group(1).lower()
                if key not in no_equals_needed:
                    col = line.find(missing_eq_match.group(0)) + 1
                    warnings.append({
                        "line": i,
                        "column": col,
                        "message": f'Consider: {missing_eq_match.group(1)} = {{ ... }} (missing = before {{?)',
                        "severity": "hint", 
                        "code": "STYLE005"
                    })
        
        # Check for unbalanced braces (properly accounting for strings and comments)
        open_braces, close_braces = self._count_braces_properly(content)
        if open_braces != close_braces:
            warnings.append({
                "line": 1,
                "column": 1,
                "message": f"Unbalanced braces: {open_braces} open, {close_braces} close",
                "severity": "warning",
                "code": "STRUCT001"
            })
        
        return warnings
    
    def _count_braces_properly(self, content: str) -> tuple:
        """Count braces while ignoring those inside strings and comments."""
        open_count = 0
        close_count = 0
        in_string = False
        i = 0
        
        while i < len(content):
            char = content[i]
            
            # Handle string boundaries
            if char == '"' and (i == 0 or content[i-1] != '\\'):
                in_string = not in_string
                i += 1
                continue
            
            # Skip content inside strings
            if in_string:
                i += 1
                continue
            
            # Handle comments - skip to end of line
            if char == '#':
                # Find end of line
                newline_pos = content.find('\n', i)
                if newline_pos == -1:
                    break  # End of file
                i = newline_pos + 1
                continue
            
            # Count braces
            if char == '{':
                open_count += 1
            elif char == '}':
                close_count += 1
            
            i += 1
        
        return open_count, close_count
    
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
        """Search for symbols in the database.
        
        Uses impl module with CVID filtering (NOT playset_mods table).
        """
        query = params.get("query", "")
        symbol_type = params.get("symbol_type")
        limit = params.get("limit", 50)
        
        if not self.db_conn or not query.strip():
            return {"results": [], "adjacencies": [], "query_patterns": [query]}
        
        if IMPL_AVAILABLE:
            # Use impl module with CVID filtering
            result = search_ops.search_symbols(
                conn=self.db_conn,
                query=query,
                cvids=self._active_cvids if self._active_cvids else None,
                symbol_type=symbol_type,
                limit=limit,
            )
            return result
        else:
            # Fallback to basic search without playset filtering
            try:
                fts_query = self._escape_fts_query(query)
                sql = """
                    SELECT s.symbol_id, s.name, s.symbol_type, s.scope,
                           s.line_number, f.relpath, cv.content_version_id,
                           mp.name as mod_name, rank
                    FROM symbols_fts fts
                    JOIN symbols s ON s.symbol_id = fts.rowid
                    LEFT JOIN files f ON s.defining_file_id = f.file_id
                    LEFT JOIN content_versions cv ON s.content_version_id = cv.content_version_id
                    LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                    WHERE symbols_fts MATCH ?
                """
                params_list = [fts_query]
                if symbol_type:
                    sql += " AND s.symbol_type = ?"
                    params_list.append(symbol_type)
                sql += " ORDER BY rank LIMIT ?"
                params_list.append(limit)
                
                rows = self.db_conn.execute(sql, params_list).fetchall()
                
                return {
                    "results": [
                        {
                            "symbolId": r[0], "name": r[1], "symbolType": r[2],
                            "scope": r[3], "line": r[4], "relpath": r[5],
                            "contentVersionId": r[6], "mod": r[7] or "vanilla",
                            "relevance": -r[8] if r[8] else 0
                        }
                        for r in rows
                    ],
                    "adjacencies": [],
                    "query_patterns": [query, fts_query]
                }
            except Exception as e:
                return {"results": [], "adjacencies": [], "query_patterns": [query], "error": str(e)}
    
    def _escape_fts_query(self, query: str) -> str:
        """Escape special characters for FTS5 queries."""
        query = query.replace('"', '""')
        terms = query.split()
        if not terms:
            return ''
        if len(terms) == 1:
            return f'"{terms[0]}"*'
        return ' OR '.join(f'"{t}"*' for t in terms if t)
    
    def get_file(self, params: dict) -> dict:
        """Get file content from database."""
        file_path = params.get("file_path", "")
        file_id = params.get("file_id")
        include_ast = params.get("include_ast", False)
        
        if not self.initialized or not self.db_conn:
            return {"error": "Session not initialized"}
        
        if IMPL_AVAILABLE:
            result = file_ops.get_file(
                conn=self.db_conn,
                file_id=file_id,
                relpath=file_path,
                cvids=self._active_cvids if self._active_cvids else None,
                include_content=True,
                include_ast=include_ast,
            )
            return result
        else:
            # Fallback to basic file retrieval
            try:
                if file_id:
                    row = self.db_conn.execute("""
                        SELECT f.file_id, f.relpath, f.content_hash, fc.content_text,
                               mp.name as mod_name, cv.content_version_id
                        FROM files f
                        JOIN file_contents fc ON f.content_hash = fc.content_hash
                        JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                        LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                        WHERE f.file_id = ?
                    """, (file_id,)).fetchone()
                else:
                    row = self.db_conn.execute("""
                        SELECT f.file_id, f.relpath, f.content_hash, fc.content_text,
                               mp.name as mod_name, cv.content_version_id
                        FROM files f
                        JOIN file_contents fc ON f.content_hash = fc.content_hash
                        JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                        LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                        WHERE f.relpath = ?
                        ORDER BY cv.content_version_id DESC
                        LIMIT 1
                    """, (file_path,)).fetchone()
                
                if not row:
                    return {"error": f"File not found: {file_path or file_id}"}
                
                return {
                    "fileId": row[0],
                    "relpath": row[1],
                    "contentHash": row[2],
                    "content": row[3],
                    "mod": row[4] or "vanilla",
                    "contentVersionId": row[5]
                }
            except Exception as e:
                return {"error": str(e)}
    
    def list_files(self, params: dict) -> dict:
        """List files in a folder within the active playset."""
        folder = params.get("folder", "").rstrip("/")
        
        if not self.initialized or not self.db_conn:
            return {"error": "Session not initialized", "files": [], "folders": []}
        
        if IMPL_AVAILABLE:
            result = file_ops.list_files(
                conn=self.db_conn,
                folder=folder,
                cvids=self._active_cvids if self._active_cvids else None,
            )
            return result
        else:
            return {"error": "impl modules not available", "files": [], "folders": []}
    
    def get_conflicts(self, params: dict) -> dict:
        """Get conflicts for a folder or symbol type."""
        path_pattern = params.get("path_pattern", "%")
        symbol_type = params.get("symbol_type")
        
        if not self.initialized or not self.db_conn:
            return {"error": "Session not initialized", "conflicts": []}
        
        if IMPL_AVAILABLE:
            if symbol_type:
                result = conflict_ops.get_symbol_conflicts(
                    conn=self.db_conn,
                    cvids=self._active_cvids if self._active_cvids else None,
                    symbol_type=symbol_type,
                )
            else:
                result = conflict_ops.get_file_conflicts(
                    conn=self.db_conn,
                    cvids=self._active_cvids if self._active_cvids else None,
                    path_pattern=path_pattern,
                )
            return result
        else:
            return {"error": "impl modules not available", "conflicts": []}
    
    def get_playset_mods(self, params: dict) -> dict:
        """Get mods in the active playset using impl module."""
        if IMPL_AVAILABLE:
            result = playset_ops.get_playset_mods()
            if not result.get("success"):
                return {"error": result.get("error", "Unknown error"), "mods": []}
            
            # Transform to expected format for extension
            mods_list = []
            for idx, mod in enumerate(result.get("mods", [])):
                mods_list.append({
                    "loadOrder": mod.get("load_order", idx),
                    "name": mod.get("name", "Unknown"),
                    "workshopId": mod.get("steam_id"),
                    "fileCount": mod.get("file_count", 0),
                    "contentVersionId": mod.get("content_version_id"),
                    "sourcePath": mod.get("path", ""),
                    "kind": "steam" if mod.get("steam_id") else "local"
                })
            
            return {"mods": mods_list}
        else:
            return {"error": "impl modules not available", "mods": []}
    
    def get_top_level_folders(self, params: dict) -> dict:
        """Get top-level folders across all mods in the active playset."""
        if not self.initialized or not self.db_conn:
            return {"error": "Session not initialized", "folders": []}
        
        if IMPL_AVAILABLE:
            result = file_ops.get_top_level_folders(
                conn=self.db_conn,
                cvids=self._active_cvids if self._active_cvids else None,
            )
            return result
        else:
            return {"error": "impl modules not available", "folders": []}
    
    def confirm_not_exists(self, params: dict) -> dict:
        """Exhaustive search to confirm something doesn't exist."""
        name = params.get("name", "")
        symbol_type = params.get("symbol_type")
        
        if not self.initialized or not self.db_conn or not name:
            return {"can_claim_not_exists": False, "similar_matches": []}
        
        if IMPL_AVAILABLE:
            result = search_ops.confirm_not_exists(
                conn=self.db_conn,
                name=name,
                cvids=self._active_cvids if self._active_cvids else None,
                symbol_type=symbol_type,
            )
            # Transform keys for extension compatibility
            return {
                "can_claim_not_exists": result.get("can_claim_not_exists", False),
                "similar_matches": [
                    {"name": m["name"], "symbolType": m.get("type"), "mod": m.get("mod", "vanilla")}
                    for m in result.get("similar_matches", [])
                ]
            }
        else:
            return {"can_claim_not_exists": False, "similar_matches": [], "error": "impl not available"}

    def read_local_file(self, params: dict) -> dict:
        """Read file from local mod."""
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
        """Write file to mod - direct filesystem write for local mods."""
        mod_name = params.get("mod_name", "")
        rel_path = params.get("rel_path", "")
        content = params.get("content", "")
        
        mod_root = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
        file_path = mod_root / mod_name / rel_path
        
        try:
            # Ensure parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return {"success": True, "bytes_written": len(content.encode('utf-8'))}
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

    # ========================================================================
    # Error/Conflict Analysis Handlers
    # ========================================================================

    def get_errors(self, params: dict) -> dict:
        """Get errors from error.log."""
        if not self.initialized:
            return {"error": "Not initialized", "errors": []}
        
        try:
            from ck3raven.analyzers.error_parser import CK3ErrorParser
            
            logs_dir = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "logs"
            parser = CK3ErrorParser(logs_dir=logs_dir)
            
            priority = params.get("priority", 4)
            category = params.get("category")
            mod_filter = params.get("mod_filter")
            exclude_cascade = params.get("exclude_cascade_children", True)
            limit = params.get("limit", 100)
            
            errors = parser.get_errors(
                priority=priority,
                category=category,
                mod_filter=mod_filter,
                exclude_cascade_children=exclude_cascade,
                limit=limit
            )
            
            return {
                "errors": [
                    {
                        "message": e.message,
                        "file_path": e.file_path,
                        "game_line": e.game_line,
                        "mod_name": e.mod_name,
                        "category": e.category,
                        "priority": e.priority,
                        "fix_hint": getattr(e, 'fix_hint', None),
                        "is_cascading_root": e.is_cascading_root
                    }
                    for e in errors
                ]
            }
        except Exception as e:
            return {"error": str(e), "errors": []}

    def get_cascade_patterns(self, params: dict) -> dict:
        """Get cascade patterns from error.log."""
        if not self.initialized:
            return {"error": "Not initialized", "patterns": []}
        
        try:
            from ck3raven.analyzers.error_parser import CK3ErrorParser
            
            logs_dir = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "logs"
            parser = CK3ErrorParser(logs_dir=logs_dir)
            parser.parse()  # Need to parse first
            
            patterns = parser.get_cascade_patterns()
            
            return {
                "patterns": [p.to_dict() for p in patterns]
            }
        except Exception as e:
            return {"error": str(e), "patterns": []}

    def list_conflict_units(self, params: dict) -> dict:
        """List conflict units from database."""
        if not self.initialized or not self.db_conn:
            return {"error": "Not initialized", "conflicts": []}
        
        try:
            from ck3raven.resolver.conflict_analyzer import get_conflict_units
            
            # Use impl module to get conflict summary instead of playset_id
            if IMPL_AVAILABLE:
                result = conflict_ops.get_conflict_summary(
                    conn=self.db_conn,
                    cvids=self._active_cvids if self._active_cvids else None,
                )
                return {"conflicts": result}
            else:
                return {"error": "impl not available", "conflicts": []}
        except Exception as e:
            return {"error": str(e), "conflicts": []}

    def get_conflict_detail(self, params: dict) -> dict:
        """Get detail for a specific conflict unit."""
        if not self.initialized or not self.db_conn:
            return {"error": "Not initialized"}
        
        try:
            from ck3raven.resolver.conflict_analyzer import get_conflict_unit_detail
            
            conflict_unit_id = params.get("conflict_unit_id")
            if not conflict_unit_id:
                return {"error": "conflict_unit_id required"}
            
            detail = get_conflict_unit_detail(self.db_conn, conflict_unit_id)
            return detail or {"error": "Not found"}
        except Exception as e:
            return {"error": str(e)}

    def create_override_patch(self, params: dict) -> dict:
        """Create an override patch file in a mod."""
        source_path = params.get("source_path")
        target_mod = params.get("target_mod")
        mode = params.get("mode", "override_patch")
        initial_content = params.get("initial_content")
        
        if not source_path or not target_mod:
            return {"success": False, "error": "source_path and target_mod required"}
        
        # Direct filesystem implementation for local mods
        mod_root = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
        
        # Determine output path based on mode
        if mode == "override_patch":
            # zzz_ prefix for partial patch
            rel_path = source_path
            if '/' in rel_path:
                parts = rel_path.rsplit('/', 1)
                rel_path = f"{parts[0]}/zzz_{parts[1]}"
            else:
                rel_path = f"zzz_{rel_path}"
        else:
            # full_replace: same name
            rel_path = source_path
        
        target_path = mod_root / target_mod / rel_path
        
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            content = initial_content or f"# Override patch for {source_path}\n# Created by CK3 Lens\n\n"
            target_path.write_text(content, encoding="utf-8")
            
            return {
                "success": True,
                "created_path": rel_path,
                "full_path": str(target_path),
                "mode": mode,
                "source_path": source_path,
                "message": f"Created {'override patch' if mode == 'override_patch' else 'full replace'}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_playsets(self, params: dict) -> dict:
        """List all playsets using impl module."""
        if IMPL_AVAILABLE:
            result = playset_ops.list_playsets()
            if not result.get("success"):
                return {"error": result.get("error", "Unknown error"), "playsets": []}
            
            # Transform to expected format for extension
            playsets = []
            for p in result.get("playsets", []):
                playsets.append({
                    "id": p.get("filename", "").replace(".json", ""),
                    "name": p.get("name", "Unknown"),
                    "filename": p.get("filename", ""),
                    "is_active": p.get("is_active", False),
                    "mod_count": p.get("mod_count", 0)
                })
            
            # Sort with active first, then alphabetically
            playsets.sort(key=lambda p: (not p['is_active'], p['name'].lower()))
            return {"playsets": playsets}
        else:
            return {"error": "impl modules not available", "playsets": []}

    def reorder_mod(self, params: dict) -> dict:
        """Reorder a mod in the active playset."""
        mod_identifier = params.get("mod_identifier")
        new_position = params.get("new_position")
        
        if not mod_identifier:
            return {"success": False, "error": "mod_identifier required"}
        if new_position is None:
            return {"success": False, "error": "new_position required"}
        
        if IMPL_AVAILABLE:
            result = playset_ops.reorder_mod(
                mod_identifier=mod_identifier,
                new_position=new_position,
            )
            return result
        else:
            return {"success": False, "error": "impl modules not available"}

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
