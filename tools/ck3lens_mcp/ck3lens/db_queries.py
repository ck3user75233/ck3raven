"""
Database Query Layer

Provides query wrappers around ck3raven's SQLite database.
Includes adjacency search pattern expansion for robust symbol lookup.
"""
from __future__ import annotations
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

# Add ck3raven to path if not installed
CK3RAVEN_PATH = Path(__file__).parent.parent.parent.parent / "src"
if CK3RAVEN_PATH.exists():
    sys.path.insert(0, str(CK3RAVEN_PATH))

from ck3raven.db.schema import get_connection
from ck3raven.resolver import SQLResolver, MergePolicy, get_policy_for_path


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SymbolHit:
    """A symbol found in search."""
    symbol_id: int
    name: str
    symbol_type: str
    file_id: int
    relpath: str
    mod_name: str
    line_number: Optional[int]
    match_type: str = "exact"  # "exact", "prefix", "stem", "tokens", etc.


@dataclass
class FileHit:
    """A file found in content search."""
    file_id: int
    relpath: str
    mod_name: str
    snippet: str
    line: int


@dataclass
class ConflictInfo:
    """Information about a symbol conflict."""
    name: str
    symbol_type: str
    winner_mod: str
    winner_file: str
    winner_line: int
    losers: list[dict]


# =============================================================================
# ADJACENCY SEARCH
# =============================================================================

def expand_query_patterns(query: str) -> list[tuple[str, str]]:
    """
    Expand a query into multiple search patterns.
    
    Returns list of (pattern, match_type) tuples.
    """
    patterns = []
    query_lower = query.lower().strip()
    
    # 1. Exact match
    patterns.append((query_lower, "exact"))
    
    # 2. Prefix (catches plurals, suffixes like _effect, _trigger)
    patterns.append((f"{query_lower}%", "prefix"))
    
    # 3. Suffix (catches prefixes like has_, is_)
    patterns.append((f"%{query_lower}", "suffix"))
    
    # 4. Contains
    patterns.append((f"%{query_lower}%", "contains"))
    
    # Token decomposition for underscore-separated names
    tokens = query_lower.split("_")
    if len(tokens) > 1:
        # 5. Without last token (e.g., tradition_warrior -> tradition_warrior_culture)
        stem = "_".join(tokens[:-1])
        patterns.append((f"{stem}%", "stem"))
        
        # 6. Without first token
        suffix = "_".join(tokens[1:])
        patterns.append((f"%{suffix}", "suffix_tokens"))
        
        # 7. Flexible underscore (tradition_warrior -> tradition%warrior)
        flex = "%".join(tokens)
        patterns.append((f"%{flex}%", "flex_underscore"))
    
    return patterns


def dedupe_results(results: list[SymbolHit]) -> list[SymbolHit]:
    """Remove duplicate symbols, keeping best match_type."""
    seen = {}
    priority = {"exact": 0, "prefix": 1, "stem": 2, "suffix": 3, "contains": 4, 
                "suffix_tokens": 5, "flex_underscore": 6}
    
    for hit in results:
        key = (hit.symbol_id, hit.name)
        if key not in seen or priority.get(hit.match_type, 99) < priority.get(seen[key].match_type, 99):
            seen[key] = hit
    
    return list(seen.values())


# =============================================================================
# DATABASE QUERIES
# =============================================================================

class DBQueries:
    """Query interface to ck3raven database."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = get_connection(db_path)
        self.conn.row_factory = sqlite3.Row
    
    def search_symbols(
        self,
        playset_id: Optional[int],
        query: str,
        symbol_type: Optional[str] = None,
        adjacency: str = "auto",
        limit: int = 100
    ) -> dict:
        """
        Search symbols with adjacency expansion.
        
        Args:
            playset_id: Active playset (optional - if None, search all content)
            query: Search term
            symbol_type: Optional filter (tradition, event, etc.)
            adjacency: "strict" | "auto" | "fuzzy"
            limit: Max results per pattern
        
        Returns:
            {results: [...], adjacencies: [...], query_patterns: [...]}
        """
        results = []
        adjacencies = []
        patterns_searched = []
        
        # Determine which patterns to use
        if adjacency == "strict":
            patterns = [(query.lower(), "exact")]
        else:
            patterns = expand_query_patterns(query)
        
        for pattern, match_type in patterns:
            patterns_searched.append(pattern)
            
            # Simple query that works without playset linkage
            # Searches ALL indexed symbols - playset filtering is optional
            sql = """
                SELECT DISTINCT
                    s.symbol_id,
                    s.name,
                    s.symbol_type,
                    s.defining_file_id as file_id,
                    f.relpath,
                    COALESCE(mp.name, 'vanilla') as mod_name,
                    s.line_number
                FROM symbols s
                JOIN files f ON s.defining_file_id = f.file_id
                JOIN content_versions cv ON s.content_version_id = cv.content_version_id
                LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE LOWER(s.name) LIKE ?
            """
            params = [pattern]
            
            if symbol_type:
                sql += " AND s.symbol_type = ?"
                params.append(symbol_type)
            
            sql += " ORDER BY s.name LIMIT ?"
            params.append(limit)
            
            rows = self.conn.execute(sql, params).fetchall()
            
            for row in rows:
                hit = SymbolHit(
                    symbol_id=row["symbol_id"],
                    name=row["name"],
                    symbol_type=row["symbol_type"],
                    file_id=row["file_id"],
                    relpath=row["relpath"],
                    mod_name=row["mod_name"],
                    line_number=row["line_number"],
                    match_type=match_type
                )
                if match_type == "exact":
                    results.append(hit)
                else:
                    adjacencies.append(hit)
        
        # Dedupe
        results = dedupe_results(results)
        adjacencies = dedupe_results(adjacencies)
        
        # Remove exact matches from adjacencies
        exact_names = {h.name.lower() for h in results}
        adjacencies = [h for h in adjacencies if h.name.lower() not in exact_names]
        
        return {
            "results": [self._hit_to_dict(h) for h in results],
            "adjacencies": [self._hit_to_dict(h) for h in adjacencies],
            "query_patterns": patterns_searched
        }
    
    def confirm_not_exists(
        self,
        playset_id: int,
        query: str,
        symbol_type: Optional[str] = None
    ) -> dict:
        """
        Exhaustive search to confirm something truly doesn't exist.
        
        MUST be called before agent can claim "not found".
        """
        # Always use full fuzzy search
        result = self.search_symbols(
            playset_id=playset_id,
            query=query,
            symbol_type=symbol_type,
            adjacency="fuzzy",
            limit=50
        )
        
        has_exact = len(result["results"]) > 0
        has_adjacencies = len(result["adjacencies"]) > 0
        
        return {
            "query": query,
            "exact_match": has_exact,
            "adjacencies": result["adjacencies"],
            "searched_patterns": result["query_patterns"],
            "can_claim_not_exists": not has_exact and not has_adjacencies
        }
    
    def get_file(
        self,
        playset_id: Optional[int],
        file_id: Optional[int] = None,
        relpath: Optional[str] = None,
        include_ast: bool = False
    ) -> Optional[dict]:
        """
        Get file content by file_id or relpath.
        
        Args:
            playset_id: Active playset (optional - if None, search all content)
            file_id: Specific file ID to retrieve
            relpath: Relative path to search for
            include_ast: If True, also return parsed AST
        """
        # Simple query that works without playset linkage
        sql = """
            SELECT 
                f.file_id,
                f.relpath,
                f.content_hash,
                COALESCE(fc.content_text, fc.content_blob) as content,
                COALESCE(mp.name, 'vanilla') as mod_name,
                fc.size as file_size
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE 1=1
        """
        params = []
        
        if file_id:
            sql += " AND f.file_id = ?"
            params.append(file_id)
        elif relpath:
            sql += " AND f.relpath = ?"
            params.append(relpath)
        else:
            return None
        
        row = self.conn.execute(sql, params).fetchone()
        if not row:
            return None
        
        # Decode content
        content_bytes = row["content"]
        if isinstance(content_bytes, bytes):
            content = content_bytes.decode("utf-8", errors="replace")
        else:
            content = content_bytes
        
        result = {
            "file_id": row["file_id"],
            "relpath": row["relpath"],
            "mod": row["mod_name"],
            "content": content,
            "size": row["file_size"]
        }
        
        if include_ast:
            try:
                from ck3raven.parser import parse_source
                ast = parse_source(content)
                result["ast"] = self._ast_to_dict(ast)
            except Exception as e:
                result["ast"] = None
                result["ast_error"] = str(e)
        
        return result
    
    def get_conflicts(
        self,
        playset_id: int,
        folder: Optional[str] = None,
        symbol_type: Optional[str] = None
    ) -> dict:
        """Get conflict report for a folder."""
        resolver = SQLResolver(self.conn)
        
        if folder:
            result = resolver.resolve_folder(playset_id, folder, symbol_type)
            policy = result.policy
            
            conflicts = []
            for ov in result.overridden:
                # Get winner info
                winner = result.symbols.get(ov.name)
                if winner:
                    conflicts.append({
                        "name": ov.name,
                        "symbol_type": ov.symbol_type,
                        "winner": {
                            "mod": self._get_mod_name(winner.content_version_id),
                            "file": winner.relpath,
                            "line": winner.line_number
                        },
                        "loser": {
                            "mod": self._get_mod_name(ov.content_version_id),
                            "file": ov.relpath,
                            "line": ov.line_number
                        }
                    })
            
            return {
                "folder": folder,
                "policy": policy.name,
                "file_overrides": result.file_override_count,
                "symbol_conflicts": conflicts
            }
        else:
            # Get summary across all folders
            summary = resolver.get_conflict_summary(playset_id)
            return summary
    
    def _get_mod_name(self, content_version_id: int) -> str:
        """Get mod name from content_version_id."""
        row = self.conn.execute("""
            SELECT COALESCE(mp.name, 'vanilla') as name
            FROM content_versions cv
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE cv.content_version_id = ?
        """, (content_version_id,)).fetchone()
        return row["name"] if row else "unknown"
    
    def _hit_to_dict(self, hit: SymbolHit) -> dict:
        return {
            "symbol_id": hit.symbol_id,
            "name": hit.name,
            "symbol_type": hit.symbol_type,
            "file_id": hit.file_id,
            "relpath": hit.relpath,
            "mod": hit.mod_name,
            "line": hit.line_number,
            "match_type": hit.match_type
        }
    
    def _ast_to_dict(self, ast) -> dict:
        """Convert AST node to dictionary (simplified)."""
        # Basic serialization - can be enhanced
        from ck3raven.parser.parser import RootNode, BlockNode, AssignmentNode, ValueNode
        
        def node_to_dict(node):
            if isinstance(node, RootNode):
                return {"type": "root", "children": [node_to_dict(c) for c in node.children]}
            elif isinstance(node, BlockNode):
                return {
                    "type": "block",
                    "name": node.name,
                    "line": node.line,
                    "children": [node_to_dict(c) for c in node.children]
                }
            elif isinstance(node, AssignmentNode):
                return {
                    "type": "assignment",
                    "key": node.key,
                    "operator": node.operator,
                    "value": node_to_dict(node.value),
                    "line": node.line
                }
            elif isinstance(node, ValueNode):
                return {"type": "value", "value": node.value}
            else:
                return {"type": type(node).__name__, "repr": repr(node)}
        
        return node_to_dict(ast)
    
    def search_files(
        self,
        playset_id: Optional[int],
        pattern: str,
        source_filter: Optional[str] = None,
        limit: int = 100
    ) -> list[dict]:
        """
        Search for files by path pattern.
        
        Args:
            playset_id: Active playset (optional - if None, search all content)
            pattern: SQL LIKE pattern for file path
            source_filter: Filter by source ("vanilla", mod name, or mod ID)
            limit: Maximum results
        
        Returns:
            List of matching files with source info
        """
        # Simple query that works without playset linkage
        # Searches ALL indexed files - playset filtering is optional
        sql = """
            SELECT 
                f.file_id,
                f.relpath,
                fc.size as file_size,
                cv.kind,
                COALESCE(mp.name, 'vanilla') as source_name,
                mp.mod_package_id
            FROM files f
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            LEFT JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE LOWER(f.relpath) LIKE LOWER(?)
        """
        params = [pattern]
        
        if source_filter:
            sql += " AND (cv.kind = ? OR LOWER(mp.name) LIKE LOWER(?) OR CAST(mp.mod_package_id AS TEXT) = ?)"
            params.extend([source_filter, f"%{source_filter}%", source_filter])
        
        sql += " ORDER BY f.relpath LIMIT ?"
        params.append(limit)
        
        files = []
        for row in self.conn.execute(sql, params).fetchall():
            files.append({
                "file_id": row["file_id"],
                "relpath": row["relpath"],
                "size": row["file_size"],
                "source_kind": row["kind"],
                "source_name": row["source_name"],
                "mod_id": row["mod_package_id"],
            })
        
        return files
    
    def search_content(
        self,
        playset_id: Optional[int],
        query: str,
        file_pattern: Optional[str] = None,
        source_filter: Optional[str] = None,
        limit: int = 50
    ) -> list[dict]:
        """
        Search file contents for text matches (grep-style).
        
        Args:
            playset_id: Active playset (optional - if None, search all content)
            query: Text to search for (case-insensitive)
            file_pattern: SQL LIKE pattern to filter files
            source_filter: Filter by source
            limit: Maximum results
        
        Returns:
            List of matching files with snippets
        """
        # Simple query that works without playset linkage
        # Searches ALL indexed content - playset filtering is optional
        sql = """
            SELECT 
                f.file_id,
                f.relpath,
                cv.kind,
                COALESCE(mp.name, 'vanilla') as source_name,
                fc.content_text
            FROM files f
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE LOWER(fc.content_text) LIKE LOWER(?)
        """
        params = [f"%{query}%"]
        
        if file_pattern:
            sql += " AND LOWER(f.relpath) LIKE LOWER(?)"
            params.append(file_pattern)
        
        if source_filter:
            sql += " AND (cv.kind = ? OR LOWER(mp.name) LIKE LOWER(?))"
            params.extend([source_filter, f"%{source_filter}%"])
        
        sql += " LIMIT ?"
        params.append(limit)
        
        results = []
        for row in self.conn.execute(sql, params).fetchall():
            content = row["content_text"] if row["content_text"] else ""
            
            # Find snippet around match
            query_lower = query.lower()
            content_lower = content.lower()
            pos = content_lower.find(query_lower)
            
            if pos >= 0:
                start = max(0, pos - 50)
                end = min(len(content), pos + len(query) + 100)
                snippet = content[start:end]
                if start > 0:
                    snippet = "..." + snippet
                if end < len(content):
                    snippet = snippet + "..."
            else:
                snippet = content[:150] + "..." if len(content) > 150 else content
            
            # Count occurrences
            count = content_lower.count(query_lower)
            
            results.append({
                "file_id": row["file_id"],
                "relpath": row["relpath"],
                "source_kind": row["kind"],
                "source_name": row["source_name"],
                "match_count": count,
                "snippet": snippet,
            })
        
        return results
    
    def close(self):
        """Close database connection."""
        self.conn.close()
