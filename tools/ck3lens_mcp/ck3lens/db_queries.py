"""
Database Query Layer

Provides query wrappers around ck3raven's SQLite database.
Includes adjacency search pattern expansion for robust symbol lookup.

CAPABILITY-GATED ARCHITECTURE (December 2025):
- All queries go through _*_internal methods
- _*_internal methods accept visible_cvids: Optional[FrozenSet[int]] directly
- DbHandle (from WorldAdapter) calls these internal methods
- External callers MUST use DbHandle, NOT direct DB methods

BANNED (December 2025 purge):
- _validate_visibility() method
- _build_cv_filter() method
- _lens_cache or any caching of visibility
- invalidate_lens_cache() method
- lens as parameter
- VisibilityScope (replaced by visible_cvids parameter to internal methods)
"""
from __future__ import annotations
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any, FrozenSet

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
    """Query interface to ck3raven database.
    
    CAPABILITY-GATED ARCHITECTURE (December 2025):
    - External callers MUST use DbHandle from WorldAdapter
    - DbHandle calls _*_internal methods with visible_cvids
    - _*_internal methods build CV filter inline
    
    BANNED:
    - _validate_visibility() - REMOVED
    - _build_cv_filter() - REMOVED
    - _lens_cache - REMOVED
    - invalidate_lens_cache() - REMOVED
    """
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = get_connection(db_path)
        self.conn.row_factory = sqlite3.Row
    
    # =========================================================================
    # INTERNAL: CV FILTER BUILDER (inline, not a method)
    # =========================================================================
    
    @staticmethod
    def _cv_filter_sql(cvids: Optional[FrozenSet[int]], column: str = "content_version_id") -> str:
        """
        Build SQL WHERE clause fragment for cvid filtering.
        
        This is a static helper, NOT an instance method that could be overridden.
        
        Args:
            cvids: FrozenSet of allowed cvids, or None for no filter
            column: Column name (default: content_version_id)
            
        Returns:
            SQL fragment like " AND s.content_version_id IN (1,2,3)" or ""
        """
        if cvids is None:
            return ""
        if not cvids:
            return " AND 1=0"  # Empty set = no results
        cv_list = ",".join(str(cv) for cv in cvids)
        return f" AND {column} IN ({cv_list})"
    
    # =========================================================================
    # CVID RESOLUTION (used during playset activation)
    # =========================================================================
    
    def get_cvids(self, mods: list, normalize_func=None) -> dict:
        """
        Resolve cvids for all mods (including vanilla at mods[0]).
        
        This is the CANONICAL method for looking up mod database IDs.
        Call this when a playset is activated to populate mods[].cvid.
        
        Args:
            mods: List of ModEntry objects. mods[0] should be vanilla.
            normalize_func: Optional path normalization function.
            
        Returns:
            Dict with resolution stats:
            - mods_resolved: int (count)
            - mods_missing: list of mod names not found in DB
            
        Side effect: Updates mod.cvid on each mod
        """
        # Path normalization helper
        def normalize(path: str) -> str:
            if normalize_func:
                return normalize_func(path)
            try:
                return str(Path(path).resolve()).lower().replace("\\", "/").rstrip("/")
            except Exception:
                return path.lower().replace("\\", "/").rstrip("/")
        
        stats = {
            "mods_resolved": 0,
            "mods_missing": []
        }
        
        if not mods:
            return stats
        
        # Get latest vanilla cvid
        vanilla_row = self.conn.execute("""
            SELECT content_version_id 
            FROM content_versions 
            WHERE kind = 'vanilla' 
            ORDER BY ingested_at DESC 
            LIMIT 1
        """).fetchone()
        vanilla_cvid = vanilla_row["content_version_id"] if vanilla_row else None
        
        # workshop_id -> cvid (latest)
        workshop_to_cv: dict[str, int] = {}
        rows = self.conn.execute("""
            SELECT mp.workshop_id, cv.content_version_id
            FROM mod_packages mp
            JOIN content_versions cv ON cv.mod_package_id = mp.mod_package_id
            WHERE mp.workshop_id IS NOT NULL
            ORDER BY cv.ingested_at DESC
        """).fetchall()
        for row in rows:
            wid = row["workshop_id"]
            if wid and wid not in workshop_to_cv:
                workshop_to_cv[wid] = row["content_version_id"]
        
        # normalized_path -> cvid (latest)
        path_to_cv: dict[str, int] = {}
        rows = self.conn.execute("""
            SELECT mp.source_path, cv.content_version_id
            FROM mod_packages mp
            JOIN content_versions cv ON cv.mod_package_id = mp.mod_package_id
            WHERE mp.source_path IS NOT NULL
            ORDER BY cv.ingested_at DESC
        """).fetchall()
        for row in rows:
            if row["source_path"]:
                norm = normalize(row["source_path"])
                if norm not in path_to_cv:
                    path_to_cv[norm] = row["content_version_id"]
        
        # Resolve each mod
        for mod in mods:
            mod_id = getattr(mod, 'mod_id', None)
            
            # Handle vanilla (mods[0])
            if mod_id == "vanilla":
                if vanilla_cvid:
                    mod.cvid = vanilla_cvid
                    stats["mods_resolved"] += 1
                else:
                    stats["mods_missing"].append("vanilla")
                continue
            
            cv_id = None
            
            # Try workshop_id first
            workshop_id = getattr(mod, 'workshop_id', None)
            if workshop_id and workshop_id in workshop_to_cv:
                cv_id = workshop_to_cv[workshop_id]
            
            # Try path lookup
            if cv_id is None:
                path = getattr(mod, 'path', None)
                if path:
                    norm = normalize(str(path))
                    if norm in path_to_cv:
                        cv_id = path_to_cv[norm]
            
            if cv_id is not None:
                mod.cvid = cv_id
                stats["mods_resolved"] += 1
            else:
                mod_name = getattr(mod, 'name', str(mod))
                stats["mods_missing"].append(mod_name)
        
        return stats
    
    # ARCHIVED 2025-01-02: list_playsets and set_active_playset removed.
    # These used BANNED playsets/playset_mods tables (now deleted).
    # Playsets are now file-based JSON. See playsets/*.json and server.py ck3_playset.
    
    # =========================================================================
    # SYMBOL SEARCH - INTERNAL
    # =========================================================================
    
    def _search_symbols_internal(
        self,
        query: str,
        *,
        visible_cvids: Optional[FrozenSet[int]],
        symbol_type: Optional[str] = None,
        file_pattern: Optional[str] = None,
        adjacency: str = "auto",
        limit: int = 100,
        include_references: bool = False,
        verbose: bool = False
    ) -> dict:
        """
        Search symbols with adjacency expansion.
        
        INTERNAL: Called by DbHandle.search_symbols()
        
        Args:
            query: Search term
            visible_cvids: FrozenSet of content_version_ids to search within, or None for all
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
        
        # Build content_version filter
        cv_filter = self._cv_filter_sql(visible_cvids, "s.content_version_id")
        
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
                    s.file_id,
                    f.relpath,
                    COALESCE(mp.name, 'vanilla') as mod_name,
                    s.line_number,
                    s.content_version_id
                FROM symbols s
                JOIN files f ON s.file_id = f.file_id
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
            refs = self._get_references_for_symbols_internal(symbol_names, visible_cvids, file_pattern, limit)
            
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
    
    def _get_references_for_symbols_internal(
        self, 
        symbol_names: list[str], 
        visible_cvids: Optional[FrozenSet[int]],
        file_pattern: Optional[str] = None,
        limit: int = 500
    ) -> list[dict]:
        """Get all references to the given symbol names."""
        if not symbol_names:
            return []
        
        placeholders = ",".join("?" * len(symbol_names))
        params = list(symbol_names)
        
        cv_filter = self._cv_filter_sql(visible_cvids, "r.content_version_id")
        
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
            JOIN files f ON r.file_id = f.file_id
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
    
    def _confirm_not_exists_internal(
        self,
        query: str,
        symbol_type: Optional[str] = None,
        *,
        visible_cvids: Optional[FrozenSet[int]]
    ) -> dict:
        """
        Exhaustive search to confirm something truly doesn't exist.
        
        MUST be called before agent can claim "not found".
        """
        result = self._search_symbols_internal(
            query=query,
            symbol_type=symbol_type,
            adjacency="fuzzy",
            limit=50,
            visible_cvids=visible_cvids
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
    # FILE RETRIEVAL - INTERNAL
    # =========================================================================
    
    def _get_file_internal(
        self,
        relpath: str,
        *,
        visible_cvids: Optional[FrozenSet[int]],
        file_id: Optional[int] = None,
        expand: Optional[List[str]] = None,
    ) -> Optional[dict]:
        """
        Get file content by file_id or relpath.
        
        INTERNAL: Called by DbHandle.get_file()
        
        Args:
            relpath: Relative path to search for
            visible_cvids: FrozenSet of cvids to filter, or None for all
            file_id: Specific file ID to retrieve (overrides relpath)
            expand: List of derived data to include IF ALREADY EXISTS in DB.
                    Valid values: ["ast"]
                    NOTE: This is read-only retrieval - never triggers parsing.
        """
        cv_filter = self._cv_filter_sql(visible_cvids, "f.content_version_id")
        
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
        
        # expand=["ast"] - retrieve AST from DB if it exists (read-only, no parsing)
        expand = expand or []
        if "ast" in expand:
            ast_row = self.conn.execute("""
                SELECT ast_blob FROM asts 
                WHERE file_id = ? AND content_hash = ?
            """, (row["file_id"], row["content_hash"])).fetchone()
            
            if ast_row and ast_row["ast_blob"]:
                try:
                    import json
                    result["ast"] = json.loads(ast_row["ast_blob"])
                except Exception:
                    result["ast"] = None
            else:
                # AST not yet built - return None, do NOT trigger parsing
                result["ast"] = None
        
        return result
    
    # =========================================================================
    # FILE SEARCH - INTERNAL
    # =========================================================================
    
    def _search_files_internal(
        self,
        pattern: str,
        *,
        visible_cvids: Optional[FrozenSet[int]],
        source_filter: Optional[str] = None,
        limit: int = 100
    ) -> list[dict]:
        """
        Search for files by path pattern.
        
        INTERNAL: Called by DbHandle.search_files()
        
        Args:
            pattern: SQL LIKE pattern for file path
            visible_cvids: FrozenSet of cvids to filter, or None for all
            source_filter: Filter by source ("vanilla", mod name, or mod ID)
            limit: Maximum results
        
        Returns:
            List of matching files with source info
        """
        cv_filter = self._cv_filter_sql(visible_cvids, "f.content_version_id")
        
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
    # CONTENT SEARCH (GREP) - INTERNAL
    # =========================================================================
    
    def _search_content_internal(
        self,
        query: str,
        *,
        visible_cvids: Optional[FrozenSet[int]],
        file_pattern: Optional[str] = None,
        source_filter: Optional[str] = None,
        limit: int = 50,
        matches_per_file: int = 5,
        verbose: bool = False
    ) -> list[dict]:
        """
        Search file contents for text matches (grep-style).
        
        INTERNAL: Called by DbHandle.search_content()
        
        Supports multiple search terms:
        - Space-separated words are treated as AND (all must appear in file)
        - Quoted strings search for exact phrases
        - Single words search for that word anywhere
        
        Returns line numbers and snippets for EACH match.
        
        Args:
            query: Text to search for (case-insensitive). Space = AND, quotes = exact phrase
            visible_cvids: FrozenSet of cvids to filter, or None for all
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
        
        cv_filter = self._cv_filter_sql(visible_cvids, "f.content_version_id")
        
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
    # UNIFIED SEARCH - INTERNAL
    # =========================================================================
    
    def _unified_search_internal(
        self,
        query: str,
        *,
        visible_cvids: Optional[FrozenSet[int]],
        file_pattern: Optional[str] = None,
        source_filter: Optional[str] = None,
        symbol_type: Optional[str] = None,
        adjacency: str = "auto",
        limit: int = 50,
        matches_per_file: int = 5,
        include_references: bool = False,
        verbose: bool = False,
        playset_name: Optional[str] = None
    ) -> dict:
        """
        Unified search across symbols AND content.
        
        INTERNAL: Called by DbHandle.unified_search()
        
        Searches both:
        1. Symbol definitions (traits, events, decisions, etc.)
        2. File content (grep-style text search)
        
        Returns both in one response - no need to decide if something is a symbol.
        """
        result = {
            "query": query,
            "playset": playset_name if playset_name else ("ACTIVE PLAYSET" if visible_cvids else "ALL CONTENT"),
            "symbols": {"count": 0, "results": [], "adjacencies": [], "definitions_by_mod": {}},
            "content": {"count": 0, "results": []},
            "files": {"count": 0, "results": []}
        }
        
        # 1. Symbol search (file_pattern filters references, not definitions)
        symbol_result = self._search_symbols_internal(
            query=query,
            symbol_type=symbol_type,
            file_pattern=file_pattern,
            adjacency=adjacency,
            limit=limit,
            include_references=include_references,
            verbose=verbose,
            visible_cvids=visible_cvids
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
        content_result = self._search_content_internal(
            query=query,
            file_pattern=file_pattern,
            source_filter=source_filter,
            limit=limit,
            matches_per_file=matches_per_file if not verbose else 1000,
            verbose=verbose,
            visible_cvids=visible_cvids
        )
        result["content"] = {
            "count": len(content_result),
            "results": content_result
        }
        
        # 3. File path search - ALWAYS search file paths
        # Normalize separators: _ - . : all match each other via wildcard
        # Auto-add wildcards to catch partial matches
        file_search_pattern = file_pattern
        if not file_search_pattern:
            # Normalize the query: replace common separators with % to match any separator
            normalized_query = re.sub(r'[-_.:]+', '%', query)
            file_search_pattern = f"%{normalized_query}%"
        
        files = self._search_files_internal(file_search_pattern, visible_cvids=visible_cvids, source_filter=source_filter, limit=limit)
        result["files"] = {
            "count": len(files),
            "results": files
        }
        
        return result
    
    # =========================================================================
    # SYMBOL BY NAME/FILE - INTERNAL
    # =========================================================================
    
    def _get_symbol_internal(
        self,
        name: str,
        symbol_type: Optional[str] = None,
        *,
        visible_cvids: Optional[FrozenSet[int]]
    ) -> Optional[dict]:
        """
        Get a symbol by exact name.
        
        INTERNAL: Called by DbHandle.get_symbol()
        """
        cv_filter = self._cv_filter_sql(visible_cvids, "s.content_version_id")
        
        sql = f"""
            SELECT 
                s.symbol_id,
                s.name,
                s.symbol_type,
                s.file_id,
                f.relpath,
                COALESCE(mp.name, 'vanilla') as mod_name,
                s.line_number
            FROM symbols s
            JOIN files f ON s.file_id = f.file_id
            JOIN content_versions cv ON s.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE s.name = ?
            {cv_filter}
        """
        params = [name]
        
        if symbol_type:
            sql += " AND s.symbol_type = ?"
            params.append(symbol_type)
        
        sql += " LIMIT 1"
        
        row = self.conn.execute(sql, params).fetchone()
        if not row:
            return None
        
        return {
            "symbol_id": row["symbol_id"],
            "name": row["name"],
            "symbol_type": row["symbol_type"],
            "file_id": row["file_id"],
            "relpath": row["relpath"],
            "mod": row["mod_name"],
            "line": row["line_number"]
        }
    
    def _get_symbols_by_file_internal(
        self,
        file_id: int,
        *,
        visible_cvids: Optional[FrozenSet[int]]
    ) -> list[dict]:
        """
        Get all symbols defined in a file.
        
        INTERNAL: Called by DbHandle.get_symbols_by_file()
        """
        cv_filter = self._cv_filter_sql(visible_cvids, "s.content_version_id")
        
        sql = f"""
            SELECT 
                s.symbol_id,
                s.name,
                s.symbol_type,
                s.line_number
            FROM symbols s
            WHERE s.file_id = ?
            {cv_filter}
            ORDER BY s.line_number
        """
        
        rows = self.conn.execute(sql, (file_id,)).fetchall()
        return [dict(row) for row in rows]
    
    def _get_refs_internal(
        self,
        symbol_name: str,
        *,
        visible_cvids: Optional[FrozenSet[int]],
        file_pattern: Optional[str] = None,
        limit: int = 100
    ) -> list[dict]:
        """
        Get references to a symbol.
        
        INTERNAL: Called by DbHandle.get_refs()
        """
        cv_filter = self._cv_filter_sql(visible_cvids, "r.content_version_id")
        
        sql = f"""
            SELECT 
                r.ref_id,
                r.name,
                r.ref_type,
                r.line_number,
                r.context,
                f.relpath,
                COALESCE(mp.name, 'vanilla') as mod_name
            FROM refs r
            JOIN files f ON r.file_id = f.file_id
            JOIN content_versions cv ON r.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE r.name = ?
            {cv_filter}
        """
        params = [symbol_name]
        
        if file_pattern:
            sql += " AND LOWER(f.relpath) LIKE LOWER(?)"
            params.append(file_pattern)
        
        sql += " ORDER BY mod_name, f.relpath, r.line_number LIMIT ?"
        params.append(limit)
        
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    
    # =========================================================================
    # CONFLICT ANALYSIS - INTERNAL
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
    
    def _get_symbol_conflicts_internal(
        self,
        *,
        visible_cvids: Optional[FrozenSet[int]],
        symbol_type: Optional[str] = None,
        game_folder: Optional[str] = None,
        limit: int = 100,
        include_compatch: bool = False,
        playset_name: Optional[str] = None
    ) -> dict:
        """
        Fast ID-level conflict detection using the symbols table.
        
        INTERNAL: Called by DbHandle.get_symbol_conflicts()
        
        This is INSTANT compared to contribution_units extraction.
        Uses GROUP BY to find symbols defined in multiple mods.
        """
        if not visible_cvids:
            return {"conflict_count": 0, "conflicts": [], "compatch_conflicts_hidden": 0}
        
        cv_filter = self._cv_filter_sql(visible_cvids, "s.content_version_id")
        
        # Build query to find symbols with multiple definitions
        sql = f"""
            SELECT 
                s.symbol_type,
                s.name,
                COUNT(DISTINCT s.content_version_id) as source_count,
                GROUP_CONCAT(DISTINCT s.content_version_id) as cv_ids
            FROM symbols s
            WHERE 1=1
            {cv_filter}
        """
        params = []
        
        if symbol_type:
            sql += " AND s.symbol_type = ?"
            params.append(symbol_type)
        
        if game_folder:
            sql += " AND EXISTS (SELECT 1 FROM files f WHERE f.file_id = s.file_id AND f.relpath LIKE ?)"
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
            cv_ids_found = [int(cv) for cv in row["cv_ids"].split(",")]
            
            # Get details for each source
            sources = []
            is_compatch_conflict = False
            
            for cv_id in cv_ids_found:
                detail_row = self.conn.execute("""
                    SELECT 
                        COALESCE(mp.name, 'vanilla') as mod_name,
                        f.relpath,
                        s.line_number
                    FROM symbols s
                    JOIN files f ON s.file_id = f.file_id
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
            "playset": playset_name if playset_name else "ACTIVE PLAYSET"
        }
    
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
    
    # =========================================================================
    # DEPRECATED: Legacy wrapper methods for gradual migration
    # These accept the old visibility parameter and extract cvids from it.
    # All new code should use DbHandle from WorldAdapter instead.
    # =========================================================================
    
    def _extract_cvids_from_visibility(self, visibility) -> Optional[FrozenSet[int]]:
        """Extract visible_cvids from legacy visibility parameter.
        
        DEPRECATED: This exists only for backward compatibility.
        New code should use DbHandle from WorldAdapter.db_handle().
        """
        if visibility is None:
            return None
        # Handle both old VisibilityScope and new patterns
        if hasattr(visibility, 'visible_cvids'):
            cvids = visibility.visible_cvids
            return frozenset(cvids) if cvids else None
        return None
    
    def search_symbols(self, query: str, *, visibility=None, **kwargs) -> dict:
        """DEPRECATED: Use DbHandle.search_symbols() instead."""
        cvids = self._extract_cvids_from_visibility(visibility)
        return self._search_symbols_internal(query, visible_cvids=cvids, **kwargs)
    
    def search_files(self, pattern: str, *, visibility=None, **kwargs) -> list:
        """DEPRECATED: Use DbHandle.search_files() instead."""
        cvids = self._extract_cvids_from_visibility(visibility)
        return self._search_files_internal(pattern, visible_cvids=cvids, **kwargs)
    
    def search_content(self, query: str, *, visibility=None, **kwargs) -> list:
        """DEPRECATED: Use DbHandle.search_content() instead."""
        cvids = self._extract_cvids_from_visibility(visibility)
        return self._search_content_internal(query, visible_cvids=cvids, **kwargs)
    
    def get_file(self, *, visibility=None, relpath: str = None, file_id: int = None, include_ast: bool = False) -> Optional[dict]:
        """DEPRECATED: Use DbHandle.get_file() instead."""
        cvids = self._extract_cvids_from_visibility(visibility)
        return self._get_file_internal(relpath or "", visible_cvids=cvids, file_id=file_id, include_ast=include_ast)
    
    def confirm_not_exists(self, query: str, symbol_type: str = None, *, visibility=None) -> dict:
        """DEPRECATED: Use DbHandle.confirm_not_exists() instead."""
        cvids = self._extract_cvids_from_visibility(visibility)
        return self._confirm_not_exists_internal(query, symbol_type, visible_cvids=cvids)
    
    def unified_search(self, query: str, *, visibility=None, **kwargs) -> dict:
        """DEPRECATED: Use DbHandle.unified_search() instead."""
        cvids = self._extract_cvids_from_visibility(visibility)
        return self._unified_search_internal(query, visible_cvids=cvids, **kwargs)
    
    def get_symbol_conflicts(self, *, visibility=None, **kwargs) -> dict:
        """DEPRECATED: Use DbHandle.get_symbol_conflicts() instead."""
        cvids = self._extract_cvids_from_visibility(visibility)
        return self._get_symbol_conflicts_internal(visible_cvids=cvids, **kwargs)
