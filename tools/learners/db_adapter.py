#!/usr/bin/env python3
"""
Learner Database Adapter

Provides read-only database access for the learner using the golden_join pattern.
This module does NOT write to the database - it only queries.

The learner uses this to:
1. Find symbols by name/type across content versions
2. Retrieve AST blobs for diffing
3. List symbols of a given type for batch processing

NOTE: We copy the GOLDEN_JOIN constant rather than importing it to keep
the learner package self-contained and avoid import path issues.
The pattern is documented in docs/learner/AST_DIFF_SPEC.md
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Default database path
DEFAULT_DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"


# =============================================================================
# GOLDEN JOIN PATTERN (copied from ck3lens.db.golden_join)
# =============================================================================
# The symbols table uses ast_id only (NOT file_id or content_version_id).
# To filter symbols by content version, use this join chain:
#
#    symbols s
#    JOIN asts a ON s.ast_id = a.ast_id
#    JOIN files f ON a.content_hash = f.content_hash
#    JOIN content_versions cv ON f.content_version_id = cv.content_version_id

GOLDEN_JOIN = """
    JOIN asts a ON s.ast_id = a.ast_id
    JOIN files f ON a.content_hash = f.content_hash
    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
"""


def _cvid_filter_clause(cvids: list[int]) -> tuple[str, list[int]]:
    """
    Build a WHERE clause fragment for content version filtering.
    
    Returns:
        (sql_fragment, params) tuple
    """
    if not cvids:
        return "", []
    
    placeholders = ", ".join("?" * len(cvids))
    return f" AND cv.content_version_id IN ({placeholders})", list(cvids)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SymbolRecord:
    """A symbol with its AST and metadata."""
    symbol_id: int
    name: str
    symbol_type: str
    content_version_id: int
    file_id: int
    relpath: str
    line_number: int
    node_start_offset: int
    node_end_offset: int
    ast: dict | None  # Parsed AST blob (full file AST)
    source_name: str  # e.g., "vanilla" or mod name
    
    def extract_symbol_block(self) -> Optional[dict]:
        """
        Extract this symbol's block from the full-file AST.
        
        The AST stored in the database is the full file. We need to find
        the block matching this symbol's name.
        """
        if not self.ast:
            return None
        
        # The AST is a root node with children
        if self.ast.get("_type") != "root":
            return self.ast  # Already a block
        
        # Find the block by name
        for child in self.ast.get("children", []):
            if child.get("_type") == "block" and child.get("name") == self.name:
                return child
        
        return None


# =============================================================================
# DATABASE ACCESSOR
# =============================================================================

class LearnerDb:
    """
    Read-only database accessor for the learner.
    
    Uses the golden_join pattern to query symbols across content versions.
    Does NOT write to the database.
    """
    
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")
        
        # Open in read-only mode
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
    
    def close(self):
        self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def get_content_version_name(self, cvid: int) -> str:
        """Get display name for a content version."""
        row = self.conn.execute("""
            SELECT cv.name as mod_name
            FROM content_versions cv
            WHERE cv.content_version_id = ?
        """, (cvid,)).fetchone()
        
        if not row:
            return f"cv_{cvid}"
        
        return row["mod_name"] or f"mod_{cvid}"
    
    def get_symbol_with_ast(
        self,
        name: str,
        symbol_type: str,
        cvid: int,
    ) -> Optional[SymbolRecord]:
        """
        Get a symbol with its parsed AST blob.
        
        Args:
            name: Symbol name
            symbol_type: Symbol type (trait, maa_type, building, etc.)
            cvid: Content version ID
        
        Returns:
            SymbolRecord with AST, or None if not found
        """
        cvid_clause, cvid_params = _cvid_filter_clause([cvid])
        
        sql = f"""
            SELECT s.symbol_id, s.name, s.symbol_type, s.line_number,
                   s.node_start_offset, s.node_end_offset,
                   f.file_id, f.relpath, cv.content_version_id,
                   a.ast_blob
            FROM symbols s
            {GOLDEN_JOIN}
            WHERE s.name = ? AND s.symbol_type = ?
            {cvid_clause}
            LIMIT 1
        """
        
        params = [name, symbol_type] + cvid_params
        row = self.conn.execute(sql, params).fetchone()
        
        if not row:
            return None
        
        # Parse AST blob
        ast = None
        if row["ast_blob"]:
            try:
                ast = json.loads(row["ast_blob"])
            except Exception:
                pass
        
        return SymbolRecord(
            symbol_id=row["symbol_id"],
            name=row["name"],
            symbol_type=row["symbol_type"],
            content_version_id=row["content_version_id"],
            file_id=row["file_id"],
            relpath=row["relpath"],
            line_number=row["line_number"],
            node_start_offset=row["node_start_offset"],
            node_end_offset=row["node_end_offset"],
            ast=ast,
            source_name=self.get_content_version_name(cvid),
        )
    
    def list_symbols_by_type(
        self,
        symbol_type: str,
        cvid: int,
        limit: int = 1000,
    ) -> list[dict]:
        """
        List all symbols of a given type in a content version.
        
        Returns lightweight dicts (no AST) for batch processing planning.
        """
        cvid_clause, cvid_params = _cvid_filter_clause([cvid])
        
        sql = f"""
            SELECT DISTINCT s.name, s.symbol_type, f.relpath
            FROM symbols s
            {GOLDEN_JOIN}
            WHERE s.symbol_type = ?
            {cvid_clause}
            ORDER BY s.name
            LIMIT ?
        """
        
        params = [symbol_type] + cvid_params + [limit]
        rows = self.conn.execute(sql, params).fetchall()
        
        return [dict(row) for row in rows]
    
    def find_common_symbols(
        self,
        symbol_type: str,
        baseline_cvid: int,
        compare_cvid: int,
        limit: int = 1000,
    ) -> list[str]:
        """
        Find symbols that exist in both content versions.
        
        Returns list of symbol names that can be diffed.
        """
        baseline_clause, baseline_params = _cvid_filter_clause([baseline_cvid])
        compare_clause, compare_params = _cvid_filter_clause([compare_cvid])
        
        # Symbols in baseline
        sql = f"""
            SELECT DISTINCT s.name
            FROM symbols s
            {GOLDEN_JOIN}
            WHERE s.symbol_type = ?
            {baseline_clause}
            
            INTERSECT
            
            SELECT DISTINCT s.name
            FROM symbols s
            {GOLDEN_JOIN}
            WHERE s.symbol_type = ?
            {compare_clause}
            
            ORDER BY 1
            LIMIT ?
        """
        
        params = [symbol_type] + baseline_params + [symbol_type] + compare_params + [limit]
        rows = self.conn.execute(sql, params).fetchall()
        
        return [row[0] for row in rows]
    
    def get_vanilla_cvid(self) -> int:
        """Get the content_version_id for vanilla (always 1 by convention)."""
        return 1
    
    def get_vanilla_cvid(self) -> int:
        """Get the vanilla content_version_id (always 1 by convention)."""
        return 1
    
    def get_mod_cvid(self, mod_name: str) -> Optional[int]:
        """Look up content_version_id for a mod by name."""
        row = self.conn.execute("""
            SELECT cv.content_version_id
            FROM content_versions cv
            WHERE cv.name LIKE ?
            ORDER BY cv.content_version_id DESC
            LIMIT 1
        """, (f"%{mod_name}%",)).fetchone()
        
        return row[0] if row else None
    
    def get_mod_cvid_by_workshop_id(self, workshop_id: str) -> Optional[int]:
        """Look up content_version_id for a mod by Steam Workshop ID."""
        row = self.conn.execute("""
            SELECT cv.content_version_id
            FROM content_versions cv
            WHERE cv.workshop_id = ?
            ORDER BY cv.content_version_id DESC
            LIMIT 1
        """, (workshop_id,)).fetchone()
        
        return row[0] if row else None


# =============================================================================
# Demo / Testing
# =============================================================================

def demo():
    """Demonstrate database access."""
    print("=" * 70)
    print("Learner Database Adapter Demo")
    print("=" * 70)
    
    try:
        db = LearnerDb()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return
    
    with db:
        # Get KGD content version
        kgd_cvid = db.get_mod_cvid("KGD")
        print(f"\nKGD content_version_id: {kgd_cvid}")
        
        if kgd_cvid:
            # Find common MAA symbols
            common = db.find_common_symbols("maa_type", 1, kgd_cvid, limit=10)
            print(f"\nCommon MAA types (vanilla vs KGD): {len(common)}")
            for name in common[:5]:
                print(f"  - {name}")
            if len(common) > 5:
                print(f"  ... and {len(common) - 5} more")
            
            # Get a specific symbol with AST
            if common:
                symbol = db.get_symbol_with_ast(common[0], "maa_type", 1)
                if symbol:
                    print(f"\nVanilla {common[0]}:")
                    print(f"  File: {symbol.relpath}")
                    print(f"  Line: {symbol.line_number}")
                    print(f"  AST available: {symbol.ast is not None}")
                    
                    block = symbol.extract_symbol_block()
                    if block:
                        print(f"  Block children: {len(block.get('children', []))}")


if __name__ == "__main__":
    demo()
