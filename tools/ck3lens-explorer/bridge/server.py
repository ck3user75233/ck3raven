#!/usr/bin/env python3
"""
CK3 Lens Explorer - Python Bridge Server

JSON-RPC server that bridges VS Code extension to ck3raven functionality.
Runs as a child process of the VS Code extension, communicating via stdio.

ARCHITECTURE (January 2026):
- Uses WorldAdapter.db_handle() for visibility-filtered database access
- NO cached _active_cvids (anti-pattern - parallel list)
- mods[] from playset_ops is THE source for CVIDs
- DbHandle carries visible_cvids automatically
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
    from ck3raven.db.schema import DEFAULT_DB_PATH
    CKRAVEN_AVAILABLE = True
except ImportError as e:
    CKRAVEN_AVAILABLE = False
    IMPORT_ERROR = str(e)
    # Define dummy exception types for when imports fail
    class LexerError(Exception):
        pass
    class ParseError(Exception):
        pass

# Import impl modules for playset operations (shared with MCP)
IMPL_AVAILABLE = False
try:
    from ck3lens.impl import playset_ops
    IMPL_AVAILABLE = True
except ImportError as e:
    IMPL_IMPORT_ERROR = str(e)

# Import WorldAdapter for canonical visibility handling
WORLD_AVAILABLE = False
try:
    from ck3lens.world_adapter import WorldAdapter, DbHandle
    from ck3lens.db_queries import DBQueries
    WORLD_AVAILABLE = True
except ImportError as e:
    WORLD_IMPORT_ERROR = str(e)


class CK3LensBridge:
    """Bridge server providing JSON-RPC interface to ck3raven.
    
    Uses WorldAdapter.db_handle() for visibility-filtered database access.
    The DbHandle carries visible_cvids derived from mods[] automatically.
    """
    
    def __init__(self):
        self.db_path = None
        self._db: "DBQueries" = None  # DBQueries instance
        self._world: "WorldAdapter" = None  # WorldAdapter for visibility
        self.initialized = False
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
    
    def _get_db_handle(self, purpose: str = "bridge") -> "DbHandle":
        """Get a DbHandle with visibility filtering from WorldAdapter.
        
        This is THE canonical way to get filtered database access.
        The handle carries visible_cvids derived from mods[].
        """
        if not self._world:
            raise RuntimeError("Session not initialized - call init_session first")
        return self._world.db_handle(purpose=purpose)
    
    def init_session(self, params: dict) -> dict:
        """Initialize session with database connection and WorldAdapter."""
        if not CKRAVEN_AVAILABLE:
            return {
                "error": f"ck3raven not available: {IMPORT_ERROR}",
                "initialized": False
            }
        
        if not WORLD_AVAILABLE:
            return {
                "error": f"WorldAdapter not available: {WORLD_IMPORT_ERROR}",
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
        
        try:
            # Create DBQueries instance
            self._db = DBQueries(db_path=self.db_path)
            
            # Get mods from playset_ops (THE source)
            mods = []
            local_mods_folder = None
            if IMPL_AVAILABLE:
                result = playset_ops.get_playset_mods()
                if result.get("success"):
                    self._playset_name = result.get("playset_name")
                    # Convert dict mods to objects with attributes
                    for m in result.get("mods", []):
                        mods.append(type('Mod', (), {
                            'name': m.get('name'),
                            'path': m.get('path'),
                            'cvid': m.get('content_version_id'),
                        })())
                
                # Get local_mods_folder from active playset
                active = playset_ops.get_active_playset()
                if active.get("success"):
                    local_mods_folder = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
            
            # Create WorldAdapter with mods[] for visibility
            self._world = WorldAdapter(
                mode="ck3lens",
                db=self._db,
                mods=mods if mods else None,
                local_mods_folder=local_mods_folder,
                vanilla_root=Path("C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game"),
            )
            
            self.initialized = True
            
            return {
                "initialized": True,
                "db_path": str(self.db_path),
                "mod_root": str(local_mods_folder) if local_mods_folder else None,
                "local_mods_folder": str(local_mods_folder) if local_mods_folder else None,
                "playset_name": self._playset_name,
                "world_available": True,
                "mod_count": len(mods),
            }
        except Exception as e:
            return {
                "error": f"Failed to initialize: {e}",
                "initialized": False
            }
    
    def parse_content(self, params: dict) -> dict:
        """Parse CK3 script content and return AST or errors with rich diagnostics."""
        content = params.get("content", "")
        filename = params.get("filename", "inline.txt")
        include_warnings = params.get("include_warnings", True)
        
        if not CKRAVEN_AVAILABLE:
            return {"errors": [{"line": 1, "message": "Parser not available"}]}
        
        try:
            ast = parse_source(content, filename)
            
            # Run additional semantic checks if parse succeeded
            warnings = []
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
        
        no_equals_needed = {'if', 'else', 'else_if', 'while', 'switch', 'random', 'random_list', 'limit', 'trigger', 'modifier'}
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            
            comment_pos = stripped.find('#')
            if comment_pos > 0:
                stripped = stripped[:comment_pos].strip()
            
            if '\t' in line and '    ' in line:
                warnings.append({
                    "line": i, "column": 1,
                    "message": "Mixed tabs and spaces in indentation",
                    "severity": "hint", "code": "STYLE002"
                })
            
            yes_no_match = re.search(r'\b(yes|no)\s*=', stripped)
            if yes_no_match:
                col = line.find(yes_no_match.group(0)) + 1
                warnings.append({
                    "line": i, "column": col,
                    "message": f'"{yes_no_match.group(1)}" is typically a value, not a key',
                    "severity": "hint", "code": "STYLE003"
                })
            
            double_eq_match = re.search(r'(?<![!<>=])={2}(?!=)', stripped)
            if double_eq_match:
                col = line.find('==') + 1
                warnings.append({
                    "line": i, "column": col,
                    "message": "Use single = for assignment; == is for comparisons in trigger blocks",
                    "severity": "hint", "code": "STYLE004"
                })
            
            missing_eq_match = re.match(r'^(\w+)\s*\{', stripped)
            if missing_eq_match:
                key = missing_eq_match.group(1).lower()
                if key not in no_equals_needed:
                    col = line.find(missing_eq_match.group(0)) + 1
                    warnings.append({
                        "line": i, "column": col,
                        "message": f'Consider: {missing_eq_match.group(1)} = {{ ... }} (missing = before {{?)',
                        "severity": "hint", "code": "STYLE005"
                    })
        
        open_braces, close_braces = self._count_braces_properly(content)
        if open_braces != close_braces:
            warnings.append({
                "line": 1, "column": 1,
                "message": f"Unbalanced braces: {open_braces} open, {close_braces} close",
                "severity": "warning", "code": "STRUCT001"
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
            
            if char == '"' and (i == 0 or content[i-1] != '\\'):
                in_string = not in_string
                i += 1
                continue
            
            if in_string:
                i += 1
                continue
            
            if char == '#':
                newline_pos = content.find('\n', i)
                if newline_pos == -1:
                    break
                i = newline_pos + 1
                continue
            
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
        
        parse_result = self.parse_content({
            "content": content, 
            "filename": filename,
            "include_warnings": check_style
        })
        
        errors = parse_result.get("errors", [])
        warnings = parse_result.get("warnings", [])
        
        return {
            "errors": errors,
            "warnings": warnings,
            "parse_success": parse_result.get("success", False),
            "stats": parse_result.get("stats", {})
        }
    
    def search_symbols(self, params: dict) -> dict:
        """Search for symbols using WorldAdapter.db_handle() for visibility."""
        query = params.get("query", "")
        symbol_type = params.get("symbol_type")
        limit = params.get("limit", 50)
        
        if not self.initialized:
            return {"results": [], "error": "Not initialized"}
        
        if not query.strip():
            return {"results": [], "adjacencies": [], "query_patterns": [query]}
        
        try:
            # Use DbHandle from WorldAdapter (carries visible_cvids)
            dbh = self._get_db_handle(purpose="search_symbols")
            results = dbh.search_symbols(query, symbol_type=symbol_type, limit=limit)
            
            return {
                "results": [
                    {
                        "symbolId": r.get("symbol_id"),
                        "name": r.get("name"),
                        "symbolType": r.get("symbol_type"),
                        "scope": r.get("scope"),
                        "line": r.get("line_number"),
                        "relpath": r.get("relpath"),
                        "contentVersionId": r.get("content_version_id"),
                        "mod": r.get("mod_name") or "vanilla",
                    }
                    for r in results
                ],
                "adjacencies": [],
                "query_patterns": [query]
            }
        except Exception as e:
            return {"results": [], "error": str(e), "query_patterns": [query]}
    
    def get_file(self, params: dict) -> dict:
        """Get file content using WorldAdapter.db_handle() for visibility."""
        file_path = params.get("file_path", "")
        file_id = params.get("file_id")
        include_ast = params.get("include_ast", False)
        
        if not self.initialized:
            return {"error": "Session not initialized"}
        
        try:
            dbh = self._get_db_handle(purpose="get_file")
            result = dbh.get_file(file_path)
            
            if not result:
                return {"error": f"File not found: {file_path}"}
            
            return {
                "fileId": result.get("file_id"),
                "relpath": result.get("relpath"),
                "content": result.get("content"),
                "mod": result.get("mod_name") or "vanilla",
                "contentVersionId": result.get("content_version_id"),
            }
        except Exception as e:
            return {"error": str(e)}
    
    def list_files(self, params: dict) -> dict:
        """List files in a folder - uses raw SQL with CVIDs from mods[]."""
        folder = params.get("folder", "").rstrip("/")
        
        if not self.initialized:
            return {"error": "Session not initialized", "files": [], "folders": []}
        
        # For list_files, we need raw SQL. Get CVIDs from WorldAdapter
        try:
            dbh = self._get_db_handle(purpose="list_files")
            cvids = dbh.visible_cvids
            
            # Use raw connection for complex queries
            conn = self._db.conn
            
            # Build CVID filter
            if cvids:
                placeholders = ",".join("?" * len(cvids))
                cvid_filter = f"cv.content_version_id IN ({placeholders})"
                cvid_params = list(sorted(cvids))
            else:
                cvid_filter = "1=1"
                cvid_params = []
            
            # Get files directly in this folder
            files_sql = f"""
                SELECT f.file_id, f.relpath, mp.name as mod_name
                FROM files f
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE {cvid_filter}
                AND f.relpath LIKE ? || '/%'
                AND f.relpath NOT LIKE ? || '/%/%'
                ORDER BY f.relpath
            """
            files = conn.execute(files_sql, cvid_params + [folder, folder]).fetchall()
            
            # Get subfolders
            subfolders_sql = f"""
                SELECT DISTINCT 
                    SUBSTR(f.relpath, LENGTH(?) + 2, 
                           INSTR(SUBSTR(f.relpath, LENGTH(?) + 2), '/') - 1
                    ) as subfolder,
                    COUNT(*) as file_count
                FROM files f
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                WHERE {cvid_filter}
                AND f.relpath LIKE ? || '/%/%'
                GROUP BY subfolder
                HAVING subfolder != '' AND subfolder IS NOT NULL
                ORDER BY subfolder
            """
            subfolders = conn.execute(subfolders_sql, [folder, folder] + cvid_params + [folder]).fetchall()
            
            return {
                "files": [
                    {"fileId": f[0], "relpath": f[1], "mod": f[2] or "vanilla"}
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
        """Get conflicts using WorldAdapter.db_handle() for visibility."""
        path_pattern = params.get("path_pattern", "%")
        
        if not self.initialized:
            return {"error": "Session not initialized", "conflicts": []}
        
        try:
            dbh = self._get_db_handle(purpose="get_conflicts")
            result = dbh.get_symbol_conflicts()
            return {"conflicts": result.get("conflicts", [])}
        except Exception as e:
            return {"error": str(e), "conflicts": []}
    
    def get_playset_mods(self, params: dict) -> dict:
        """Get mods in the active playset using playset_ops."""
        if not IMPL_AVAILABLE:
            return {"error": "playset_ops not available", "mods": []}
        
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
    
    def get_top_level_folders(self, params: dict) -> dict:
        """Get top-level folders using CVIDs from WorldAdapter."""
        if not self.initialized:
            return {"error": "Session not initialized", "folders": []}
        
        try:
            dbh = self._get_db_handle(purpose="get_top_level_folders")
            cvids = dbh.visible_cvids
            
            conn = self._db.conn
            
            if cvids:
                placeholders = ",".join("?" * len(cvids))
                cvid_filter = f"WHERE cv.content_version_id IN ({placeholders})"
                params = list(sorted(cvids))
            else:
                cvid_filter = ""
                params = []
            
            sql = f"""
                SELECT 
                    CASE 
                        WHEN INSTR(f.relpath, '/') > 0 THEN SUBSTR(f.relpath, 1, INSTR(f.relpath, '/') - 1)
                        ELSE f.relpath
                    END as folder,
                    COUNT(*) as file_count
                FROM files f
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                {cvid_filter}
                GROUP BY folder
                ORDER BY folder
            """
            
            folders = conn.execute(sql, params).fetchall()
            
            return {
                "folders": [
                    {"name": f[0], "fileCount": f[1]}
                    for f in folders
                ]
            }
        except Exception as e:
            return {"error": str(e), "folders": []}
    
    def confirm_not_exists(self, params: dict) -> dict:
        """Exhaustive search using WorldAdapter.db_handle()."""
        name = params.get("name", "")
        symbol_type = params.get("symbol_type")
        
        if not self.initialized or not name:
            return {"can_claim_not_exists": False, "similar_matches": []}
        
        try:
            dbh = self._get_db_handle(purpose="confirm_not_exists")
            result = dbh.confirm_not_exists(name, symbol_type)
            return result
        except Exception as e:
            return {"can_claim_not_exists": False, "error": str(e), "similar_matches": []}

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
            parser.parse()
            
            patterns = parser.get_cascade_patterns()
            
            return {
                "patterns": [p.to_dict() for p in patterns]
            }
        except Exception as e:
            return {"error": str(e), "patterns": []}

    def list_conflict_units(self, params: dict) -> dict:
        """List conflict units from database."""
        if not self.initialized:
            return {"error": "Not initialized", "conflicts": []}
        
        try:
            dbh = self._get_db_handle(purpose="list_conflict_units")
            result = dbh.get_symbol_conflicts()
            return {"conflicts": result.get("conflicts", [])}
        except Exception as e:
            return {"error": str(e), "conflicts": []}

    def get_conflict_detail(self, params: dict) -> dict:
        """Get detail for a specific conflict unit."""
        if not self.initialized:
            return {"error": "Not initialized"}
        
        conflict_unit_id = params.get("conflict_unit_id")
        if not conflict_unit_id:
            return {"error": "conflict_unit_id required"}
        
        # For detailed conflict info, need to query by specific unit
        return {"error": "Not implemented yet"}

    def create_override_patch(self, params: dict) -> dict:
        """Create an override patch file in a mod."""
        source_path = params.get("source_path")
        target_mod = params.get("target_mod")
        mode = params.get("mode", "override_patch")
        initial_content = params.get("initial_content")
        
        if not source_path or not target_mod:
            return {"success": False, "error": "source_path and target_mod required"}
        
        mod_root = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "mod"
        
        if mode == "override_patch":
            rel_path = source_path
            if '/' in rel_path:
                parts = rel_path.rsplit('/', 1)
                rel_path = f"{parts[0]}/zzz_{parts[1]}"
            else:
                rel_path = f"zzz_{rel_path}"
        else:
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
        """List all playsets using playset_ops."""
        if not IMPL_AVAILABLE:
            return {"error": "playset_ops not available", "playsets": []}
        
        result = playset_ops.list_playsets()
        if not result.get("success"):
            return {"error": result.get("error", "Unknown error"), "playsets": []}
        
        playsets = []
        for p in result.get("playsets", []):
            playsets.append({
                "id": p.get("filename", "").replace(".json", ""),
                "name": p.get("name", "Unknown"),
                "filename": p.get("filename", ""),
                "is_active": p.get("is_active", False),
                "mod_count": p.get("mod_count", 0)
            })
        
        playsets.sort(key=lambda p: (not p['is_active'], p['name'].lower()))
        return {"playsets": playsets}

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
            return {"success": False, "error": "playset_ops not available"}

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
