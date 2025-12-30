"""
Database Query Layer

Provides query wrappers around ck3raven's SQLite database.
Includes adjacency search pattern expansion for robust symbol lookup.
All queries are scoped through the active playset (the "lens").
"""
from __future__ import annotations
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any, Set

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
class ContentMatch:
    """A single match within a file."""
    line: int
    snippet: str


@dataclass
class FileHit:
    """A file found in content search."""
    file_id: int
    relpath: str
    mod_name: str
    matches: list[ContentMatch]


@dataclass
class PlaysetLens:
    """
    A playset lens filters all database queries to a specific set of content.
    
    Think of it as putting on glasses - you only see what's in the playset.
    The underlying data is unchanged; the lens is just a filter.
    """
    playset_id: int
    playset_name: str
    vanilla_cv_id: int  # content_version_id for vanilla
    mod_cv_ids: list[int]  # content_version_ids for mods in load order
    
    @property
    def all_cv_ids(self) -> Set[int]:
        """All content_version_ids visible through this lens."""
        return {self.vanilla_cv_id} | set(self.mod_cv_ids)
    
    def get_file_ids_sql(self, conn: sqlite3.Connection) -> str:
        """Return SQL subquery for valid file_ids."""
        cv_list = ",".join(str(cv) for cv in self.all_cv_ids)
        return f"SELECT file_id FROM files WHERE content_version_id IN ({cv_list})"


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
        self._lens_cache: dict[int, PlaysetLens] = {}
    
    # =========================================================================
    # PLAYSET LENS MANAGEMENT
    # =========================================================================
    
    def get_lens(self, playset_id: int) -> Optional[PlaysetLens]:
        """
        Get the playset lens for a given playset_id.
        
        The lens defines what content is visible for all queries.
        Returns None if playset doesn't exist.
        """
        if playset_id in self._lens_cache:
            return self._lens_cache[playset_id]
        
        # Get playset info
        playset = self.conn.execute("""
            SELECT playset_id, name, vanilla_version_id
            FROM playsets WHERE playset_id = ?
        """, (playset_id,)).fetchone()
        
        if not playset:
            return None
        
        # Get vanilla content_version_id
        vanilla_cv = self.conn.execute("""
            SELECT content_version_id 
            FROM content_versions 
            WHERE vanilla_version_id = ? AND kind = 'vanilla'
            ORDER BY ingested_at DESC LIMIT 1
        """, (playset["vanilla_version_id"],)).fetchone()
        
        if not vanilla_cv:
            return None
        
        # Get mod content_version_ids in load order
        mod_rows = self.conn.execute("""
            SELECT content_version_id 
            FROM playset_mods 
            WHERE playset_id = ? AND enabled = 1
            ORDER BY load_order_index ASC
        """, (playset_id,)).fetchall()
        
        mod_cv_ids = [row["content_version_id"] for row in mod_rows]
        
        lens = PlaysetLens(
            playset_id=playset_id,
            playset_name=playset["name"],
            vanilla_cv_id=vanilla_cv["content_version_id"],
            mod_cv_ids=mod_cv_ids
        )
        
        self._lens_cache[playset_id] = lens
        return lens
    
    def get_active_lens(self) -> Optional[PlaysetLens]:
        """
        Get the lens for the currently active playset.
        
        DEPRECATED: This method queries the database which is empty.
        Use build_lens_from_scope() instead with file-based playset data.
        """
        row = self.conn.execute("""
            SELECT playset_id FROM playsets WHERE is_active = 1 LIMIT 1
        """).fetchone()
        
        if row:
            return self.get_lens(row["playset_id"])
        return None
    
    def build_lens_from_scope(
        self,
        playset_name: str,
        mod_steam_ids: list[str],
        mod_paths: list[str],
        load_order: Optional[list[str]] = None
    ) -> Optional[PlaysetLens]:
        """
        Build a PlaysetLens from file-based playset data.
        
        This is the PRIMARY method for creating a lens from JSON playset files.
        It resolves mod identifiers (steam IDs or paths) to content_version_ids.
        
        Args:
            playset_name: Human-readable name for the playset
            mod_steam_ids: List of Steam Workshop IDs for mods in playset
            mod_paths: List of filesystem paths for mods in playset
            load_order: Optional list of mod names/IDs defining load order
                        (if None, uses database ingestion order)
        
        Returns:
            PlaysetLens with vanilla and mod content_version_ids,
            or None if vanilla not found in database.
        """
        # 1. Get vanilla content_version_id (most recent)
        vanilla_row = self.conn.execute("""
            SELECT content_version_id 
            FROM content_versions 
            WHERE kind = 'vanilla' 
            ORDER BY ingested_at DESC 
            LIMIT 1
        """).fetchone()
        
        if not vanilla_row:
            return None
        
        vanilla_cv_id = vanilla_row["content_version_id"]
        
        # 2. Find mod content_version_ids by steam ID or path
        mod_cv_ids = []
        found_mods = set()
        
        # Build lookup: steam_id -> content_version_id
        # We need the LATEST content_version for each mod
        steam_id_to_cv = {}
        if mod_steam_ids:
            placeholders = ",".join("?" * len(mod_steam_ids))
            rows = self.conn.execute(f"""
                SELECT mp.workshop_id, cv.content_version_id, cv.ingested_at
                FROM mod_packages mp
                JOIN content_versions cv ON cv.mod_package_id = mp.mod_package_id
                WHERE mp.workshop_id IN ({placeholders})
                ORDER BY cv.ingested_at DESC
            """, mod_steam_ids).fetchall()
            
            for row in rows:
                wid = row["workshop_id"]
                if wid not in steam_id_to_cv:  # Keep only latest
                    steam_id_to_cv[wid] = row["content_version_id"]
        
        # Build lookup: normalized_path -> content_version_id
        path_to_cv = {}
        if mod_paths:
            # Use canonical path normalization from world_adapter
            from .world_adapter import normalize_path_for_comparison
            
            # Query all mod packages with paths
            rows = self.conn.execute("""
                SELECT mp.source_path, cv.content_version_id, cv.ingested_at
                FROM mod_packages mp
                JOIN content_versions cv ON cv.mod_package_id = mp.mod_package_id
                WHERE mp.source_path IS NOT NULL
                ORDER BY cv.ingested_at DESC
            """).fetchall()
            
            for row in rows:
                if row["source_path"]:
                    norm = normalize_path_for_comparison(row["source_path"])
                    if norm not in path_to_cv:  # Keep only latest
                        path_to_cv[norm] = row["content_version_id"]
            
            # Match requested paths
            for mod_path in mod_paths:
                norm = normalize_path_for_comparison(mod_path)
                if norm in path_to_cv:
                    cv_id = path_to_cv[norm]
                    if cv_id not in found_mods:
                        mod_cv_ids.append(cv_id)
                        found_mods.add(cv_id)
        
        # Now add steam ID matches (if not already added via path)
        for steam_id in mod_steam_ids:
            if steam_id in steam_id_to_cv:
                cv_id = steam_id_to_cv[steam_id]
                if cv_id not in found_mods:
                    mod_cv_ids.append(cv_id)
                    found_mods.add(cv_id)
        
        # 3. Build the lens
        return PlaysetLens(
            playset_id=-1,  # No database ID for file-based playsets
            playset_name=playset_name,
            vanilla_cv_id=vanilla_cv_id,
            mod_cv_ids=mod_cv_ids
        )
    
    def invalidate_lens_cache(self, playset_id: Optional[int] = None):
        """Clear cached lens (call after playset changes)."""
        if playset_id:
            self._lens_cache.pop(playset_id, None)
        else:
            self._lens_cache.clear()
    
    def list_playsets(self) -> list[dict]:
        """List all available playsets."""
        rows = self.conn.execute("""
            SELECT 
                p.playset_id,
                p.name,
                p.is_active,
                p.created_at,
                (SELECT COUNT(*) FROM playset_mods pm WHERE pm.playset_id = p.playset_id) as mod_count
            FROM playsets p
            ORDER BY p.is_active DESC, p.updated_at DESC
        """).fetchall()
        
        return [dict(row) for row in rows]
    
    def set_active_playset(self, playset_id: int) -> bool:
        """
        Switch the active playset (change the lens).
        
        This is instant - just updates which playset is marked active.
        Does NOT modify any mod data.
        """
        # Verify playset exists
        exists = self.conn.execute(
            "SELECT 1 FROM playsets WHERE playset_id = ?", (playset_id,)
        ).fetchone()
        
        if not exists:
            return False
        
        # Deactivate all, activate this one
        self.conn.execute("UPDATE playsets SET is_active = 0")
        self.conn.execute(
            "UPDATE playsets SET is_active = 1, updated_at = datetime('now') WHERE playset_id = ?",
            (playset_id,)
        )
        self.conn.commit()
        
        # Clear lens cache
        self.invalidate_lens_cache()
        
        return True
    
    # =========================================================================
    # SYMBOL SEARCH
    # =========================================================================
    
    def search_symbols(
        self,
        lens: Optional[PlaysetLens],
        query: str,
        symbol_type: Optional[str] = None,
        file_pattern: Optional[str] = None,
        adjacency: str = "auto",
        limit: int = 100,
        include_references: bool = False,
        verbose: bool = False
    ) -> dict:
        """
        Search symbols with adjacency expansion.
        
        Args:
            lens: PlaysetLens to filter through (None = search ALL content)
            query: Search term
            symbol_type: Optional filter (tradition, event, etc.)
            file_pattern: SQL LIKE pattern for file paths (applies to references)
            adjacency: "strict" | "auto" | "fuzzy"
            limit: Max results per pattern
            include_references: If True, also return mods that reference the symbol
            verbose: If True, include code snippets for definitions
        
        Returns:
            {
                results: [...],  # Exact matches
                adjacencies: [...],  # Similar names
                query_patterns: [...],
                definitions_by_mod: {...},  # Which mods define this symbol
                references_by_mod: {...}  # If include_references=True
            }
        """
        results = []
        adjacencies = []
        patterns_searched = []
        
        # Build content_version filter if lens is active
        cv_filter = ""
        if lens:
            cv_list = ",".join(str(cv) for cv in lens.all_cv_ids)
            cv_filter = f" AND s.content_version_id IN ({cv_list})"
        
        # Determine which patterns to use
        if adjacency == "strict":
            patterns = [(query.lower(), "exact")]
        else:
            patterns = expand_query_patterns(query)
        
        for pattern, match_type in patterns:
            patterns_searched.append(pattern)
            
            sql = f"""
                SELECT DISTINCT
                    s.symbol_id,
                    s.name,
                    s.symbol_type,
                    s.defining_file_id as file_id,
                    f.relpath,
                    COALESCE(mp.name, 'vanilla') as mod_name,
                    s.line_number,
                    s.content_version_id
                FROM symbols s
                JOIN files f ON s.defining_file_id = f.file_id
                JOIN content_versions cv ON s.content_version_id = cv.content_version_id
                LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                WHERE LOWER(s.name) LIKE ?
                {cv_filter}
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
        
        # Build definitions_by_mod: group exact matches by mod
        definitions_by_mod = {}
        for hit in results:
            if hit.mod_name not in definitions_by_mod:
                definitions_by_mod[hit.mod_name] = []
            
            entry = {
                "name": hit.name,
                "type": hit.symbol_type,
                "file": hit.relpath,
                "line": hit.line_number
            }
            
            # Add snippet if verbose
            if verbose:
                snippet = self._get_line_snippet(hit.file_id, hit.line_number)
                if snippet:
                    entry["snippet"] = snippet
            
            definitions_by_mod[hit.mod_name].append(entry)
        
        # Build references_by_mod if requested
        references_by_mod = {}
        if include_references and results:
            # Get all symbol names we found
            symbol_names = list({h.name for h in results})
            refs = self._get_references_for_symbols(symbol_names, lens, file_pattern, limit)
            
            for ref in refs:
                mod = ref["mod_name"]
                if mod not in references_by_mod:
                    references_by_mod[mod] = []
                references_by_mod[mod].append({
                    "symbol": ref["name"],
                    "file": ref["relpath"],
                    "line": ref["line_number"],
                    "context": ref.get("context")
                })
        
        result = {
            "results": [self._hit_to_dict(h) for h in results],
            "adjacencies": [self._hit_to_dict(h) for h in adjacencies],
            "query_patterns": patterns_searched,
            "definitions_by_mod": definitions_by_mod
        }
        
        if include_references:
            result["references_by_mod"] = references_by_mod
        
        return result
    
    def _get_references_for_symbols(
        self, 
        symbol_names: list[str], 
        lens: Optional[PlaysetLens],
        file_pattern: Optional[str] = None,
        limit: int = 500
    ) -> list[dict]:
        """Get all references to the given symbol names."""
        if not symbol_names:
            return []
        
        placeholders = ",".join("?" * len(symbol_names))
        params = list(symbol_names)
        
        cv_filter = ""
        if lens:
            cv_list = ",".join(str(cv) for cv in lens.all_cv_ids)
            cv_filter = f" AND r.content_version_id IN ({cv_list})"
        
        file_filter = ""
        if file_pattern:
            file_filter = " AND LOWER(f.relpath) LIKE LOWER(?)"
            params.append(file_pattern)
        
        params.append(limit)
        
        sql = f"""
            SELECT 
                r.name,
                r.ref_type,
                r.line_number,
                r.context,
                f.relpath,
                COALESCE(mp.name, 'vanilla') as mod_name
            FROM refs r
            JOIN files f ON r.using_file_id = f.file_id
            JOIN content_versions cv ON r.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE r.name IN ({placeholders})
            {cv_filter}
            {file_filter}
            ORDER BY mod_name, f.relpath, r.line_number
            LIMIT ?
        """
        
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    
    def _get_line_snippet(self, file_id: int, line_number: Optional[int], context: int = 0) -> Optional[str]:
        """Get a code snippet from a file at a specific line."""
        if line_number is None:
            return None
        
        row = self.conn.execute("""
            SELECT fc.content_text 
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE f.file_id = ?
        """, (file_id,)).fetchone()
        
        if not row or not row["content_text"]:
            return None
        
        lines = row["content_text"].split("\n")
        
        # Line numbers are 1-indexed
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return None
        
        # Get context lines
        start = max(0, idx - context)
        end = min(len(lines), idx + context + 1)
        
        snippet_lines = lines[start:end]
        return "\n".join(snippet_lines).strip()
    
    def confirm_not_exists(
        self,
        lens: Optional[PlaysetLens],
        query: str,
        symbol_type: Optional[str] = None
    ) -> dict:
        """
        Exhaustive search to confirm something truly doesn't exist.
        
        MUST be called before agent can claim "not found".
        """
        result = self.search_symbols(
            lens=lens,
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
    
    # =========================================================================
    # FILE RETRIEVAL
    # =========================================================================
    
    def get_file(
        self,
        lens: Optional[PlaysetLens],
        file_id: Optional[int] = None,
        relpath: Optional[str] = None,
        include_ast: bool = False
    ) -> Optional[dict]:
        """
        Get file content by file_id or relpath.
        
        Args:
            lens: PlaysetLens to filter through (None = search ALL content)
            file_id: Specific file ID to retrieve
            relpath: Relative path to search for
            include_ast: If True, also return parsed AST
        """
        cv_filter = ""
        if lens:
            cv_list = ",".join(str(cv) for cv in lens.all_cv_ids)
            cv_filter = f" AND f.content_version_id IN ({cv_list})"
        
        sql = f"""
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
            WHERE 1=1 {cv_filter}
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
    
    # =========================================================================
    # FILE SEARCH
    # =========================================================================
    
    def search_files(
        self,
        lens: Optional[PlaysetLens],
        pattern: str,
        source_filter: Optional[str] = None,
        limit: int = 100
    ) -> list[dict]:
        """
        Search for files by path pattern.
        
        Args:
            lens: PlaysetLens to filter through (None = search ALL content)
            pattern: SQL LIKE pattern for file path
            source_filter: Filter by source ("vanilla", mod name, or mod ID)
            limit: Maximum results
        
        Returns:
            List of matching files with source info
        """
        cv_filter = ""
        if lens:
            cv_list = ",".join(str(cv) for cv in lens.all_cv_ids)
            cv_filter = f" AND f.content_version_id IN ({cv_list})"
        
        sql = f"""
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
            {cv_filter}
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
    
    # =========================================================================
    # CONTENT SEARCH (GREP)
    # =========================================================================
    
    def search_content(
        self,
        lens: Optional[PlaysetLens],
        query: str,
        file_pattern: Optional[str] = None,
        source_filter: Optional[str] = None,
        limit: int = 50,
        matches_per_file: int = 5,
        verbose: bool = False
    ) -> list[dict]:
        """
        Search file contents for text matches (grep-style).
        
        Supports multiple search terms:
        - Space-separated words are treated as AND (all must appear in file)
        - Quoted strings search for exact phrases
        - Single words search for that word anywhere
        
        Returns line numbers and snippets for EACH match.
        
        Args:
            lens: PlaysetLens to filter through (None = search ALL content)
            query: Text to search for (case-insensitive). Space = AND, quotes = exact phrase
            file_pattern: SQL LIKE pattern to filter files
            source_filter: Filter by source
            limit: Maximum files to return
            matches_per_file: Max matches to return per file (default 5, more if verbose)
            verbose: If True, return all matches (no per-file limit)
        
        Returns:
            List of files with line-by-line match details
        """
        # Parse query into terms (handle quoted phrases)
        terms = self._parse_search_terms(query)
        
        cv_filter = ""
        if lens:
            cv_list = ",".join(str(cv) for cv in lens.all_cv_ids)
            cv_filter = f" AND f.content_version_id IN ({cv_list})"
        
        # Build SQL with AND for all terms
        term_conditions = []
        params = []
        for term in terms:
            term_conditions.append("LOWER(fc.content_text) LIKE LOWER(?)")
            params.append(f"%{term}%")
        
        term_sql = " AND ".join(term_conditions)
        
        sql = f"""
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
            WHERE {term_sql}
            {cv_filter}
        """
        
        if file_pattern:
            sql += " AND LOWER(f.relpath) LIKE LOWER(?)"
            params.append(file_pattern)
        
        if source_filter:
            sql += " AND (cv.kind = ? OR LOWER(mp.name) LIKE LOWER(?))"
            params.extend([source_filter, f"%{source_filter}%"])
        
        sql += " LIMIT ?"
        params.append(limit)
        
        max_matches = 1000 if verbose else matches_per_file
        
        results = []
        for row in self.conn.execute(sql, params).fetchall():
            content = row["content_text"] if row["content_text"] else ""
            
            # Find ALL matches with line numbers (pass parsed terms)
            matches = self._find_all_matches(content, terms, max_matches)
            
            if not matches:
                continue
            
            results.append({
                "file_id": row["file_id"],
                "relpath": row["relpath"],
                "source_kind": row["kind"],
                "source_name": row["source_name"],
                "match_count": self._count_matches(content, terms),
                "matches": matches,
                "truncated": len(matches) >= max_matches
            })
        
        return results
    
    def _parse_search_terms(self, query: str) -> list[str]:
        """
        Parse search query into terms.
        
        - Quoted strings become exact phrase terms
        - Unquoted words become individual AND terms
        - Empty strings are ignored
        
        Examples:
            'melkite localization' -> ['melkite', 'localization']
            '"has_trait" brave' -> ['has_trait', 'brave']
            'on_action yearly' -> ['on_action', 'yearly']
        """
        import re
        
        terms = []
        
        # Extract quoted phrases first
        for match in re.finditer(r'"([^"]+)"', query):
            terms.append(match.group(1))
        
        # Remove quoted parts from query
        remaining = re.sub(r'"[^"]*"', '', query)
        
        # Split remaining by whitespace
        for word in remaining.split():
            word = word.strip()
            if word:
                terms.append(word)
        
        return terms if terms else [query]  # Fallback to original if parsing fails
    
    def _find_all_matches(self, content: str, terms: list[str], max_matches: int) -> list[dict]:
        """Find all lines containing ANY search term, with line numbers and snippets."""
        matches = []
        lines = content.split("\n")
        terms_lower = [t.lower() for t in terms]
        
        for line_num, line in enumerate(lines, start=1):
            line_lower = line.lower()
            
            # Check if any term matches this line
            matched_term = None
            for term in terms_lower:
                if term in line_lower:
                    matched_term = term
                    break
            
            if not matched_term:
                continue
            
            # Find position of matched term for highlighting
            pos = line_lower.find(matched_term)
            
            # Build snippet with context
            start = max(0, pos - 30)
            end = min(len(line), pos + len(matched_term) + 50)
            snippet = line[start:end].strip()
            
            if start > 0:
                snippet = "..." + snippet
            if end < len(line):
                snippet = snippet + "..."
            
            matches.append({
                "line": line_num,
                "snippet": snippet
            })
            
            if len(matches) >= max_matches:
                break
        
        return matches
    
    def _count_matches(self, content: str, terms: list[str]) -> int:
        """Count total occurrences of all search terms in content."""
        content_lower = content.lower()
        total = 0
        for term in terms:
            total += content_lower.count(term.lower())
        return total
    
    # =========================================================================
    # UNIFIED SEARCH
    # =========================================================================
    
    def unified_search(
        self,
        lens: Optional[PlaysetLens],
        query: str,
        file_pattern: Optional[str] = None,
        source_filter: Optional[str] = None,
        symbol_type: Optional[str] = None,
        adjacency: str = "auto",
        limit: int = 50,
        matches_per_file: int = 5,
        include_references: bool = False,
        verbose: bool = False
    ) -> dict:
        """
        Unified search across symbols AND content.
        
        Searches both:
        1. Symbol definitions (traits, events, decisions, etc.)
        2. File content (grep-style text search)
        
        Returns both in one response - no need to decide if something is a symbol.
        
        Args:
            lens: PlaysetLens to filter (None = search ALL)
            query: Search term
            file_pattern: SQL LIKE pattern for file paths (optional)
            source_filter: Filter by mod/source (optional)
            symbol_type: Filter symbols by type (optional)
            adjacency: Pattern expansion mode ("auto", "strict", "fuzzy")
            limit: Max results per category
            matches_per_file: Max content matches per file (default 5)
            include_references: Include mods that reference found symbols
            verbose: More detail (all matches, snippets)
        
        Returns:
            {
                "query": str,
                "symbols": {
                    "count": int,
                    "results": [...],
                    "adjacencies": [...],
                    "definitions_by_mod": {...}
                },
                "content": {
                    "count": int,
                    "results": [...]  # Line-by-line matches
                },
                "files": {
                    "count": int,
                    "results": [...]  # Matching file paths
                }
            }
        """
        result = {
            "query": query,
            "lens": lens.playset_name if lens else "ALL CONTENT (no lens)",
            "symbols": {"count": 0, "results": [], "adjacencies": [], "definitions_by_mod": {}},
            "content": {"count": 0, "results": []},
            "files": {"count": 0, "results": []}
        }
        
        # 1. Symbol search (file_pattern filters references, not definitions)
        symbol_result = self.search_symbols(
            lens=lens,
            query=query,
            symbol_type=symbol_type,
            file_pattern=file_pattern,
            adjacency=adjacency,
            limit=limit,
            include_references=include_references,
            verbose=verbose
        )
        result["symbols"] = {
            "count": len(symbol_result.get("results", [])),
            "results": symbol_result.get("results", []),
            "adjacencies": symbol_result.get("adjacencies", []),
            "definitions_by_mod": symbol_result.get("definitions_by_mod", {})
        }
        if include_references:
            result["symbols"]["references_by_mod"] = symbol_result.get("references_by_mod", {})
        
        # 2. Content search (grep)
        content_result = self.search_content(
            lens=lens,
            query=query,
            file_pattern=file_pattern,
            source_filter=source_filter,
            limit=limit,
            matches_per_file=matches_per_file if not verbose else 1000,
            verbose=verbose
        )
        result["content"] = {
            "count": len(content_result),
            "results": content_result
        }
        
        # 3. File path search (if file_pattern provided or query looks like a path)
        if file_pattern or '/' in query or '\\' in query or query.endswith('.txt'):
            search_pattern = file_pattern if file_pattern else f"%{query}%"
            files = self.search_files(lens, search_pattern, source_filter, limit)
            result["files"] = {
                "count": len(files),
                "results": files
            }
        
        return result
    
    # =========================================================================
    # CONFLICT ANALYSIS
    # =========================================================================
    
    # Known compatch mod name patterns - these are DESIGNED to conflict
    COMPATCH_PATTERNS = [
        "compatch", "compatibility", "patch",
        "compat", "fix", "hotfix", "tweak", "override"
    ]
    
    def _is_compatch_mod(self, mod_name: str) -> bool:
        """Check if a mod is a compatibility patch (designed to conflict)."""
        if not mod_name:
            return False
        name_lower = mod_name.lower()
        return any(pattern in name_lower for pattern in self.COMPATCH_PATTERNS)
    
    def get_symbol_conflicts(
        self,
        lens: "PlaysetLens",
        symbol_type: Optional[str] = None,
        game_folder: Optional[str] = None,
        limit: int = 100,
        include_compatch: bool = False
    ) -> dict:
        """
        Fast ID-level conflict detection using the symbols table.
        
        This is INSTANT compared to contribution_units extraction.
        Uses GROUP BY to find symbols defined in multiple mods.
        
        Args:
            lens: PlaysetLens to filter through
            symbol_type: Filter by type (trait, event, decision, etc.)
            game_folder: Filter by CK3 folder (e.g., "common/traits")
            limit: Maximum conflicts to return
            include_compatch: If True, include conflicts from compatch mods
                              (default False - compatch mods are expected to conflict)
        
        Returns:
            {
                "conflict_count": int,
                "conflicts": [
                    {
                        "name": str,
                        "symbol_type": str,
                        "source_count": int,
                        "sources": [{"mod": str, "file": str, "line": int}],
                        "is_compatch_conflict": bool  # True if involves compatch mod
                    }
                ],
                "compatch_conflicts_hidden": int  # Count of conflicts filtered out
            }
        """
        cv_list = ",".join(str(cv) for cv in lens.all_cv_ids)
        
        # Build query to find symbols with multiple definitions
        sql = f"""
            SELECT 
                s.symbol_type,
                s.name,
                COUNT(DISTINCT s.content_version_id) as source_count,
                GROUP_CONCAT(DISTINCT s.content_version_id) as cv_ids
            FROM symbols s
            JOIN playset_mods pm ON s.content_version_id = pm.content_version_id
            WHERE pm.playset_id = ? AND pm.enabled = 1
        """
        params = [lens.playset_id]
        
        if symbol_type:
            sql += " AND s.symbol_type = ?"
            params.append(symbol_type)
        
        if game_folder:
            sql += " AND EXISTS (SELECT 1 FROM files f WHERE f.file_id = s.defining_file_id AND f.relpath LIKE ?)"
            params.append(f"{game_folder}%")
        
        sql += """
            GROUP BY s.symbol_type, s.name
            HAVING source_count > 1
            ORDER BY source_count DESC
            LIMIT ?
        """
        params.append(limit * 2)  # Get extra for compatch filtering
        
        rows = self.conn.execute(sql, params).fetchall()
        
        conflicts = []
        compatch_hidden = 0
        
        for row in rows:
            if len(conflicts) >= limit:
                break
                
            symbol_type_val = row["symbol_type"]
            name = row["name"]
            cv_ids = [int(cv) for cv in row["cv_ids"].split(",")]
            
            # Get details for each source
            sources = []
            is_compatch_conflict = False
            
            for cv_id in cv_ids:
                detail_row = self.conn.execute("""
                    SELECT 
                        COALESCE(mp.name, 'vanilla') as mod_name,
                        f.relpath,
                        s.line_number
                    FROM symbols s
                    JOIN files f ON s.defining_file_id = f.file_id
                    JOIN content_versions cv ON s.content_version_id = cv.content_version_id
                    LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
                    WHERE s.content_version_id = ? AND s.symbol_type = ? AND s.name = ?
                    LIMIT 1
                """, (cv_id, symbol_type_val, name)).fetchone()
                
                if detail_row:
                    mod_name = detail_row["mod_name"]
                    if self._is_compatch_mod(mod_name):
                        is_compatch_conflict = True
                    sources.append({
                        "mod": mod_name,
                        "file": detail_row["relpath"],
                        "line": detail_row["line_number"]
                    })
            
            # Filter out compatch conflicts if requested
            if is_compatch_conflict and not include_compatch:
                compatch_hidden += 1
                continue
            
            conflicts.append({
                "name": name,
                "symbol_type": symbol_type_val,
                "source_count": row["source_count"],
                "sources": sources,
                "is_compatch_conflict": is_compatch_conflict
            })
        
        return {
            "conflict_count": len(conflicts),
            "conflicts": conflicts,
            "compatch_conflicts_hidden": compatch_hidden,
            "lens": lens.playset_name
        }

    def get_conflicts(
        self,
        lens: PlaysetLens,
        folder: Optional[str] = None,
        symbol_type: Optional[str] = None
    ) -> dict:
        """Get conflict report for a folder."""
        resolver = SQLResolver(self.conn)
        
        if folder:
            result = resolver.resolve_folder(lens.playset_id, folder, symbol_type)
            policy = result.policy
            
            conflicts = []
            for ov in result.overridden:
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
            summary = resolver.get_conflict_summary(lens.playset_id)
            return summary
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    
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
    
    def close(self):
        """Close database connection."""
        self.conn.close()
