#!/usr/bin/env python3
"""
CK3 Lens Explorer - Python Bridge Server

JSON-RPC server that bridges VS Code extension to ck3raven functionality.
Runs as a child process of the VS Code extension, communicating via stdio.
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
    
    # Installed extension mode: check common locations
    common_locations = [
        Path.home() / "Documents" / "AI Workspace" / "ck3raven",
        Path.home() / "ck3raven",
        Path(os.environ.get("CK3RAVEN_PATH", "")) if os.environ.get("CK3RAVEN_PATH") else None,
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


class CK3LensBridge:
    """Bridge server providing JSON-RPC interface to ck3raven."""
    
    def __init__(self):
        self.db_path = None
        self.db_conn = None  # SQLite connection
        self.session = None
        self.playset_id = None
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
            "list_local_mods": self.list_local_mods,
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
        
        # Connect to SQLite database
        try:
            self.db_conn = sqlite3.connect(str(self.db_path))
            self.db_conn.row_factory = sqlite3.Row
            
            # Get active playset
            row = self.db_conn.execute(
                "SELECT playset_id, name FROM playsets WHERE is_active = 1 LIMIT 1"
            ).fetchone()
            
            if row:
                self.playset_id = row[0]
                playset_name = row[1]
            else:
                # Use first playset if none active
                row = self.db_conn.execute(
                    "SELECT playset_id, name FROM playsets LIMIT 1"
                ).fetchone()
                self.playset_id = row[0] if row else None
                playset_name = row[1] if row else None
            
            self.initialized = True
            
            # Get local mods from playset config
            local_mods_result = self.list_local_mods({})
            local_mods = local_mods_result.get("local_mods", {"mods": []})
            
            return {
                "initialized": True,
                "db_path": str(self.db_path),
                "mod_root": str(Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"),
                "playset_id": self.playset_id,
                "playset_name": playset_name,
                "local_mods": local_mods
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
        
        Uses FTS5 search on symbols_fts table, filtered to active playset mods.
        """
        query = params.get("query", "")
        symbol_type = params.get("symbol_type")
        limit = params.get("limit", 50)
        adjacency = params.get("adjacency", "auto")  # For future fuzzy matching
        
        if not self.db_conn or not query.strip():
            return {"results": [], "adjacencies": [], "query_patterns": [query]}
        
        try:
            # Escape query for FTS5
            fts_query = self._escape_fts_query(query)
            
            # Build SQL with playset filtering
            # Only return symbols from mods in the active playset
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
            
            # Filter by active playset
            if self.playset_id:
                sql += """
                    AND cv.content_version_id IN (
                        SELECT content_version_id FROM playset_mods 
                        WHERE playset_id = ? AND enabled = 1
                    )
                """
                params_list.append(self.playset_id)
            
            # Filter by symbol type if specified
            if symbol_type:
                sql += " AND s.symbol_type = ?"
                params_list.append(symbol_type)
            
            sql += " ORDER BY rank LIMIT ?"
            params_list.append(limit)
            
            rows = self.db_conn.execute(sql, params_list).fetchall()
            
            results = []
            for r in rows:
                results.append({
                    "symbolId": r[0],
                    "name": r[1],
                    "symbolType": r[2],
                    "scope": r[3],
                    "line": r[4],
                    "relpath": r[5],
                    "contentVersionId": r[6],
                    "mod": r[7] or "vanilla",
                    "relevance": -r[8] if r[8] else 0
                })
            
            return {
                "results": results,
                "adjacencies": [],  # TODO: Implement fuzzy/adjacent matches
                "query_patterns": [query, fts_query]
            }
            
        except Exception as e:
            return {
                "results": [],
                "adjacencies": [],
                "query_patterns": [query],
                "error": str(e)
            }
    
    def _escape_fts_query(self, query: str) -> str:
        """Escape special characters for FTS5 queries."""
        # Escape double quotes
        query = query.replace('"', '""')
        terms = query.split()
        if not terms:
            return ''
        if len(terms) == 1:
            # Single term: use prefix match for autocomplete
            return f'"{terms[0]}"*'
        # Multiple terms: OR them together
        return ' OR '.join(f'"{t}"*' for t in terms if t)
    
    def get_file(self, params: dict) -> dict:
        """Get file content from database."""
        file_path = params.get("file_path", "")
        file_id = params.get("file_id")
        include_ast = params.get("include_ast", False)
        
        if not self.initialized or not self.db_conn:
            return {"error": "Session not initialized"}
        
        try:
            # Query by file_id or relpath
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
                # Search by relpath in active playset (returns winner)
                row = self.db_conn.execute("""
                    SELECT f.file_id, f.relpath, f.content_hash, fc.content_text,
                           mp.name as mod_name, cv.content_version_id
                    FROM files f
                    JOIN file_contents fc ON f.content_hash = fc.content_hash
                    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                    LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                    JOIN playset_mods pm ON pm.content_version_id = cv.content_version_id
                    WHERE f.relpath = ? AND pm.playset_id = ? AND pm.enabled = 1
                    ORDER BY pm.load_order_index DESC
                    LIMIT 1
                """, (file_path, self.playset_id)).fetchone()
            
            if not row:
                return {"error": f"File not found: {file_path or file_id}"}
            
            result = {
                "fileId": row[0],
                "relpath": row[1],
                "contentHash": row[2],
                "content": row[3],
                "mod": row[4] or "vanilla",
                "contentVersionId": row[5]
            }
            
            # Optionally include AST
            if include_ast:
                ast_row = self.db_conn.execute("""
                    SELECT ast_blob FROM asts WHERE content_hash = ?
                """, (row[2],)).fetchone()
                if ast_row and ast_row[0]:
                    try:
                        import zlib
                        ast_json = zlib.decompress(ast_row[0]).decode('utf-8')
                    except:
                        ast_json = ast_row[0].decode('utf-8') if isinstance(ast_row[0], bytes) else ast_row[0]
                    result["ast"] = ast_json
            
            return result
            
        except Exception as e:
            return {"error": str(e)}
    
    def list_files(self, params: dict) -> dict:
        """List files in a folder within the active playset."""
        folder = params.get("folder", "").rstrip("/")
        
        if not self.initialized or not self.db_conn:
            return {"error": "Session not initialized", "files": [], "folders": []}
        
        try:
            # Get files directly in this folder
            files = self.db_conn.execute("""
                SELECT f.file_id, f.relpath, mp.name as mod_name, pm.load_order_index
                FROM files f
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                JOIN playset_mods pm ON pm.content_version_id = cv.content_version_id
                WHERE pm.playset_id = ? AND pm.enabled = 1
                AND f.relpath LIKE ? || '/%'
                AND f.relpath NOT LIKE ? || '/%/%'
                ORDER BY f.relpath
            """, (self.playset_id, folder, folder)).fetchall()
            
            # Get subfolders
            subfolders = self.db_conn.execute("""
                SELECT DISTINCT 
                    SUBSTR(f.relpath, LENGTH(?) + 2, 
                           INSTR(SUBSTR(f.relpath, LENGTH(?) + 2), '/') - 1
                    ) as subfolder,
                    COUNT(*) as file_count
                FROM files f
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                JOIN playset_mods pm ON pm.content_version_id = cv.content_version_id
                WHERE pm.playset_id = ? AND pm.enabled = 1
                AND f.relpath LIKE ? || '/%/%'
                GROUP BY subfolder
                HAVING subfolder != '' AND subfolder IS NOT NULL
                ORDER BY subfolder
            """, (folder, folder, self.playset_id, folder)).fetchall()
            
            return {
                "files": [
                    {"fileId": f[0], "relpath": f[1], "mod": f[2] or "vanilla", "loadOrder": f[3]}
                    for f in files
                ],
                "folders": [
                    {"name": sf[0], "fileCount": sf[1]}
                    for sf in subfolders
                ]
            }
            
        except Exception as e:
            return {"error": str(e), "files": [], "folders": []}
    
    def get_conflicts(self, params: dict) -> dict:
        """Get conflicts for a folder or symbol type.
        
        Conflicts occur when multiple mods define the same file path or symbol.
        The mod with higher load order wins.
        """
        path_pattern = params.get("path_pattern", "%")
        symbol_type = params.get("symbol_type")
        
        if not self.initialized or not self.db_conn:
            return {"error": "Session not initialized", "conflicts": []}
        
        try:
            # File-level conflicts: same relpath from multiple mods
            conflicts = self.db_conn.execute("""
                SELECT f.relpath, 
                       GROUP_CONCAT(mp.name || ':' || pm.load_order_index, '|') as sources,
                       COUNT(*) as source_count
                FROM files f
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                JOIN playset_mods pm ON pm.content_version_id = cv.content_version_id
                WHERE pm.playset_id = ? AND pm.enabled = 1
                AND f.relpath LIKE ?
                GROUP BY f.relpath
                HAVING COUNT(*) > 1
                ORDER BY f.relpath
                LIMIT 100
            """, (self.playset_id, path_pattern)).fetchall()
            
            result_conflicts = []
            for c in conflicts:
                sources = c[1].split('|')
                # Parse mod:load_order pairs and sort by load order desc
                parsed = []
                for s in sources:
                    parts = s.rsplit(':', 1)
                    if len(parts) == 2:
                        mod_name = parts[0] if parts[0] != 'None' else 'vanilla'
                        load_order = int(parts[1])
                        parsed.append((mod_name, load_order))
                
                parsed.sort(key=lambda x: -x[1])  # Highest load order first (winner)
                
                if len(parsed) >= 2:
                    result_conflicts.append({
                        "relpath": c[0],
                        "winner": {"mod": parsed[0][0], "loadOrder": parsed[0][1]},
                        "losers": [{"mod": p[0], "loadOrder": p[1]} for p in parsed[1:]]
                    })
            
            return {"conflicts": result_conflicts}
            
        except Exception as e:
            return {"error": str(e), "conflicts": []}
    
    def get_playset_mods(self, params: dict) -> dict:
        """Get mods in the active playset with load order."""
        if not self.initialized or not self.db_conn:
            return {"error": "Session not initialized", "mods": []}
        
        try:
            # Get mods in playset with load order
            mods = self.db_conn.execute("""
                SELECT pm.load_order_index, mp.name, mp.workshop_id, 
                       cv.file_count, cv.content_version_id, mp.source_path
                FROM playset_mods pm
                JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
                JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE pm.playset_id = ? AND pm.enabled = 1
                ORDER BY pm.load_order_index
            """, (self.playset_id,)).fetchall()
            
            return {
                "mods": [
                    {
                        "loadOrder": m[0],
                        "name": m[1],
                        "workshopId": m[2],
                        "fileCount": m[3],
                        "contentVersionId": m[4],
                        "sourcePath": m[5],
                        "kind": "steam" if m[2] else "local"
                    }
                    for m in mods
                ]
            }
        except Exception as e:
            return {"error": str(e), "mods": []}
    
    def get_top_level_folders(self, params: dict) -> dict:
        """Get top-level folders across all mods in the active playset."""
        if not self.initialized or not self.db_conn:
            return {"error": "Session not initialized", "folders": []}
        
        try:
            # Get unique folder prefixes from files
            folders = self.db_conn.execute("""
                SELECT 
                    CASE 
                        WHEN INSTR(f.relpath, '/') > 0 THEN SUBSTR(f.relpath, 1, INSTR(f.relpath, '/') - 1)
                        ELSE f.relpath
                    END as folder,
                    COUNT(*) as file_count
                FROM files f
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                JOIN playset_mods pm ON pm.content_version_id = cv.content_version_id
                WHERE pm.playset_id = ? AND pm.enabled = 1
                GROUP BY folder
                ORDER BY folder
            """, (self.playset_id,)).fetchall()
            
            return {
                "folders": [
                    {"name": f[0], "fileCount": f[1]}
                    for f in folders
                ]
            }
        except Exception as e:
            return {"error": str(e), "folders": []}

    def confirm_not_exists(self, params: dict) -> dict:
        """Exhaustive search to confirm something doesn't exist.
        
        This performs a thorough search to prevent false negatives when
        claiming a symbol doesn't exist.
        """
        name = params.get("name", "")
        symbol_type = params.get("symbol_type")
        
        if not self.initialized or not self.db_conn or not name:
            return {"can_claim_not_exists": False, "similar_matches": []}
        
        try:
            # 1. Exact match search
            sql = """
                SELECT s.name, s.symbol_type, mp.name as mod_name
                FROM symbols s
                LEFT JOIN content_versions cv ON s.content_version_id = cv.content_version_id
                LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE s.name = ?
            """
            params_list = [name]
            if symbol_type:
                sql += " AND s.symbol_type = ?"
                params_list.append(symbol_type)
            sql += " LIMIT 10"
            
            exact_matches = self.db_conn.execute(sql, params_list).fetchall()
            
            if exact_matches:
                # Found exact matches - cannot claim it doesn't exist
                return {
                    "can_claim_not_exists": False,
                    "similar_matches": [
                        {"name": m[0], "symbolType": m[1], "mod": m[2] or "vanilla"}
                        for m in exact_matches
                    ]
                }
            
            # 2. Fuzzy/similar match search using FTS
            fts_query = f'"{name}"*'
            similar_sql = """
                SELECT s.name, s.symbol_type, mp.name as mod_name
                FROM symbols_fts fts
                JOIN symbols s ON s.symbol_id = fts.rowid
                LEFT JOIN content_versions cv ON s.content_version_id = cv.content_version_id
                LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE symbols_fts MATCH ?
            """
            params_list = [fts_query]
            if symbol_type:
                similar_sql += " AND s.symbol_type = ?"
                params_list.append(symbol_type)
            similar_sql += " LIMIT 20"
            
            similar_matches = self.db_conn.execute(similar_sql, params_list).fetchall()
            
            return {
                "can_claim_not_exists": len(similar_matches) == 0,
                "similar_matches": [
                    {"name": m[0], "symbolType": m[1], "mod": m[2] or "vanilla"}
                    for m in similar_matches
                ]
            }
            
        except Exception as e:
            return {"can_claim_not_exists": False, "similar_matches": [], "error": str(e)}
    
    def list_local_mods(self, params: dict) -> dict:
        """List local mods that can be written to.
        
        Loads from playset configuration. If no playset is active, returns empty list.
        This is valid - read-only mode with no writable mods.
        """
        mod_root = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
        raven_dir = Path.home() / ".ck3raven"
        
        mods = []
        
        # Try to load from active playset
        active_file = raven_dir / "playsets" / "active.txt"
        if active_file.exists():
            try:
                playset_name = active_file.read_text().strip()
                playset_file = raven_dir / "playsets" / f"{playset_name}.json"
                if playset_file.exists():
                    import json
                    playset_data = json.loads(playset_file.read_text())
                    local_mods_config = playset_data.get("local_mods", [])
                    
                    for mod_cfg in local_mods_config:
                        # Support both old and new formats
                        if isinstance(mod_cfg, dict):
                            mod_id = mod_cfg.get("short_id", mod_cfg.get("name", ""))
                            display_name = mod_cfg.get("name", mod_id)
                            folder_name = mod_cfg.get("folder", display_name)
                        else:
                            # Legacy: just a folder name string
                            mod_id = folder_name = display_name = mod_cfg
                        
                        path = mod_root / folder_name
                        mods.append({
                            "mod_id": mod_id,
                            "name": display_name,
                            "path": str(path),
                            "exists": path.exists()
                        })
            except Exception:
                pass  # Fall through to empty list
        
        return {"local_mods": {"mods": mods}}

    
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
        """Write file to live mod."""
        mod_name = params.get("mod_name", "")
        rel_path = params.get("rel_path", "")
        content = params.get("content", "")
        validate_syntax = params.get("validate_syntax", True)
        
        # Validate syntax first
        if validate_syntax:
            parse_result = self.parse_content({"content": content, "include_warnings": True})
            if parse_result.get("errors"):
                return {
                    "success": False,
                    "errors": parse_result["errors"],
                    "warnings": parse_result.get("warnings", [])
                }
            # Include warnings in successful write too
            warnings = parse_result.get("warnings", [])
        else:
            warnings = []
        
        mod_root = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
        file_path = mod_root / mod_name / rel_path
        
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8-sig")
            return {
                "success": True, 
                "bytes_written": len(content),
                "warnings": warnings  # Return any style warnings even on success
            }
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
            
            conflicts = get_conflict_units(
                self.db_conn,
                self.playset_id,
                risk_filter=params.get("risk_filter"),
                domain_filter=params.get("domain_filter"),
                status_filter=params.get("status_filter"),
                limit=params.get("limit", 50),
                offset=params.get("offset", 0)
            )
            
            return {"conflicts": conflicts}
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
        """Create an override patch file in a live mod."""
        from datetime import datetime
        
        source_path = params.get("source_path")
        target_mod = params.get("target_mod")
        mode = params.get("mode", "override_patch")
        initial_content = params.get("initial_content")
        
        if not source_path or not target_mod:
            return {"success": False, "error": "source_path and target_mod required"}
        
        try:
            source = Path(source_path)
            
            # Determine output filename
            if mode == "override_patch":
                new_name = f"zzz_msc_{source.name}"
            elif mode == "full_replace":
                new_name = source.name
            else:
                return {"success": False, "error": f"Invalid mode: {mode}"}
            
            # Build target path
            target_rel_path = str(source.parent / new_name)
            
            # Get mod path from playset config or try direct folder match
            mod_root = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
            mod_path = None
            
            # Try to load from playset config first
            raven_dir = Path.home() / ".ck3raven"
            active_file = raven_dir / "playsets" / "active.txt"
            if active_file.exists():
                try:
                    playset_name = active_file.read_text().strip()
                    playset_file = raven_dir / "playsets" / f"{playset_name}.json"
                    if playset_file.exists():
                        import json
                        playset_data = json.loads(playset_file.read_text())
                        for mod_cfg in playset_data.get("local_mods", []):
                            if isinstance(mod_cfg, dict):
                                if mod_cfg.get("short_id") == target_mod or mod_cfg.get("name") == target_mod:
                                    folder = mod_cfg.get("folder", mod_cfg.get("name", target_mod))
                                    mod_path = mod_root / folder
                                    break
                            elif mod_cfg == target_mod:
                                mod_path = mod_root / target_mod
                                break
                except Exception:
                    pass
            
            # Fall back to direct name match
            if mod_path is None:
                mod_path = mod_root / target_mod
            
            if not mod_path.exists():
                return {"success": False, "error": f"Mod directory not found: {mod_path}"}
            
            # Create full path
            full_path = mod_path / target_rel_path
            
            # Generate default content if not provided
            if initial_content is None:
                initial_content = f"""# Override patch for: {source_path}
# Created: {datetime.now().strftime("%Y-%m-%d %H:%M")}
# Mode: {mode}
# 
# Add your overrides below. For 'override_patch' mode, only include
# the specific units you want to override/add.

"""
            
            # Create directories and write file
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(initial_content, encoding="utf-8")
            
            return {
                "success": True,
                "created_path": target_rel_path,
                "full_path": str(full_path),
                "mode": mode,
                "source_path": source_path,
                "message": f"Created override patch: {target_rel_path}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_playsets(self, params: dict) -> dict:
        """List all playsets in the launcher database."""
        try:
            if not self.db:
                return {"error": "Database not initialized", "playsets": []}
            
            # Query playsets from the launcher database
            # This uses the same connection the MCP server uses
            playsets = []
            
            # Try to use the MCP tool if available
            if CKRAVEN_AVAILABLE:
                from ck3lens_mcp.server import ck3_list_playsets
                result = ck3_list_playsets()
                return result
            
            # Fallback: Direct database query
            cursor = self.db.conn.execute("""
                SELECT 
                    id,
                    name,
                    CASE WHEN id = (SELECT value FROM metadata WHERE key = 'active_playset_id') THEN 1 ELSE 0 END as is_active
                FROM playsets
                ORDER BY name
            """)
            
            for row in cursor.fetchall():
                playsets.append({
                    "id": row[0],
                    "name": row[1],
                    "is_active": bool(row[2])
                })
            
            return {"playsets": playsets}
        except Exception as e:
            return {"error": str(e), "playsets": []}

    def reorder_mod(self, params: dict) -> dict:
        """Reorder a mod in the active playset."""
        try:
            mod_identifier = params.get("mod_identifier")
            new_position = params.get("new_position")
            
            if not mod_identifier:
                return {"success": False, "error": "mod_identifier required"}
            if new_position is None:
                return {"success": False, "error": "new_position required"}
            
            # Use the MCP tool
            if CKRAVEN_AVAILABLE:
                from ck3lens_mcp.server import ck3_reorder_mod_in_playset
                result = ck3_reorder_mod_in_playset(
                    mod_identifier=mod_identifier,
                    new_position=new_position
                )
                return result
            
            return {"success": False, "error": "ck3raven not available"}
        except Exception as e:
            return {"success": False, "error": str(e)}

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

