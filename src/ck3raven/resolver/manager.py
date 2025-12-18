"""
Contributions Manager

Lifecycle-aware management of contribution and conflict data.

This module provides the ContributionsManager class which:
1. Tracks when contribution data is stale (playset changed)
2. Automatically refreshes data when stale
3. Provides clean API for conflict analysis queries
4. Integrates with the existing playset lifecycle hooks

Usage:
    manager = ContributionsManager(conn)
    
    # Get conflicts (auto-refreshes if stale)
    conflicts = manager.get_conflicts(playset_id)
    
    # Force a refresh
    manager.refresh(playset_id)
    
    # Check if refresh is needed
    if manager.is_stale(playset_id):
        print("Contribution data is out of date")
"""

import sqlite3
import hashlib
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from ck3raven.db.playsets import (
    get_playset,
    get_playset_mods,
    get_playset_load_order,
    is_contributions_stale,
    mark_contributions_current,
    compute_load_order_hash,
)

logger = logging.getLogger(__name__)


@dataclass
class RefreshResult:
    """Result of a contribution refresh operation."""
    playset_id: int
    contributions_extracted: int
    conflicts_found: int
    contributions_hash: str
    elapsed_seconds: float
    was_stale: bool


@dataclass 
class ConflictSummary:
    """Summary statistics for conflicts in a playset."""
    playset_id: int
    total: int
    by_risk: Dict[str, int]  # {"low": n, "med": n, "high": n}
    by_domain: Dict[str, int]
    by_status: Dict[str, int]  # {"unresolved": n, "resolved": n, "deferred": n}
    unresolved_high_risk: int
    is_stale: bool  # True if data might be out of date


class ContributionsManager:
    """
    Lifecycle-aware manager for contribution and conflict data.
    
    This class is the primary interface for conflict analysis. It:
    - Tracks staleness and triggers refreshes when needed
    - Provides query methods for conflicts
    - Handles the full extraction → grouping → storage pipeline
    """
    
    def __init__(self, conn: sqlite3.Connection, auto_refresh: bool = True):
        """
        Initialize the manager.
        
        Args:
            conn: Database connection
            auto_refresh: If True, automatically refresh stale data on queries
        """
        self.conn = conn
        self.auto_refresh = auto_refresh
        self._ensure_tables_exist()
    
    def _ensure_tables_exist(self) -> None:
        """Ensure contribution tables exist (for backward compatibility)."""
        # Check if tables exist
        tables = self.conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='contribution_units'
        """).fetchone()
        
        if not tables:
            # Tables don't exist - they should have been created by init_database()
            # but we can create them here for backward compatibility
            from ck3raven.resolver.contributions import init_contribution_schema
            logger.warning("Contribution tables not found - creating them now")
            init_contribution_schema(self.conn)
    
    def is_stale(self, playset_id: int) -> bool:
        """Check if a playset's contribution data needs refresh."""
        return is_contributions_stale(self.conn, playset_id)
    
    def refresh(
        self,
        playset_id: int,
        folder_filter: Optional[str] = None,
        force: bool = False
    ) -> RefreshResult:
        """
        Refresh contribution and conflict data for a playset.
        
        This is the main entry point for updating conflict data.
        It extracts contributions from all sources, groups them into conflicts,
        and updates the database tables.
        
        Args:
            playset_id: Target playset
            folder_filter: Optional filter like "common/on_action"
            force: If True, refresh even if not stale
        
        Returns:
            RefreshResult with statistics
        """
        import time
        start = time.time()
        
        was_stale = self.is_stale(playset_id)
        
        if not force and not was_stale:
            # Data is current, return quick result
            summary = self.get_summary(playset_id)
            return RefreshResult(
                playset_id=playset_id,
                contributions_extracted=0,
                conflicts_found=summary.total,
                contributions_hash="",
                elapsed_seconds=0.0,
                was_stale=False
            )
        
        # Import here to avoid circular imports
        from ck3raven.resolver.conflict_analyzer import (
            extract_contributions_for_playset,
            group_conflicts_for_playset,
        )
        
        # Extract contributions for all content_versions in this playset
        # This now extracts per-content_version and reuses across playsets
        contributions_count = extract_contributions_for_playset(
            self.conn,
            playset_id,
            folder_filter,
            force=force
        )
        
        # Group into conflicts for this playset (always per-playset)
        conflicts_count = group_conflicts_for_playset(
            self.conn,
            playset_id
        )
        
        # Compute hash and mark as current
        load_order = get_playset_load_order(self.conn, playset_id)
        contributions_hash = compute_load_order_hash(load_order)
        mark_contributions_current(self.conn, playset_id, contributions_hash)
        
        elapsed = time.time() - start
        
        return RefreshResult(
            playset_id=playset_id,
            contributions_extracted=contributions_count,
            conflicts_found=conflicts_count,
            contributions_hash=contributions_hash,
            elapsed_seconds=elapsed,
            was_stale=was_stale
        )
    
    def get_summary(self, playset_id: int) -> ConflictSummary:
        """
        Get summary statistics for conflicts in a playset.
        
        If auto_refresh is True and data is stale, refreshes first.
        """
        if self.auto_refresh and self.is_stale(playset_id):
            self.refresh(playset_id)
        
        is_stale = self.is_stale(playset_id)
        
        # Total count
        total_row = self.conn.execute("""
            SELECT COUNT(*) as cnt FROM conflict_units WHERE playset_id = ?
        """, (playset_id,)).fetchone()
        total = total_row['cnt'] if total_row else 0
        
        # By risk
        by_risk = {"low": 0, "med": 0, "high": 0}
        for row in self.conn.execute("""
            SELECT risk, COUNT(*) as cnt FROM conflict_units 
            WHERE playset_id = ? GROUP BY risk
        """, (playset_id,)):
            by_risk[row['risk']] = row['cnt']
        
        # By domain
        by_domain = {}
        for row in self.conn.execute("""
            SELECT domain, COUNT(*) as cnt FROM conflict_units 
            WHERE playset_id = ? GROUP BY domain
        """, (playset_id,)):
            by_domain[row['domain']] = row['cnt']
        
        # By status
        by_status = {"unresolved": 0, "resolved": 0, "deferred": 0}
        for row in self.conn.execute("""
            SELECT resolution_status, COUNT(*) as cnt FROM conflict_units 
            WHERE playset_id = ? GROUP BY resolution_status
        """, (playset_id,)):
            by_status[row['resolution_status']] = row['cnt']
        
        # Unresolved high risk
        hr_row = self.conn.execute("""
            SELECT COUNT(*) as cnt FROM conflict_units 
            WHERE playset_id = ? AND risk = 'high' AND resolution_status = 'unresolved'
        """, (playset_id,)).fetchone()
        unresolved_high = hr_row['cnt'] if hr_row else 0
        
        return ConflictSummary(
            playset_id=playset_id,
            total=total,
            by_risk=by_risk,
            by_domain=by_domain,
            by_status=by_status,
            unresolved_high_risk=unresolved_high,
            is_stale=is_stale
        )
    
    def list_conflicts(
        self,
        playset_id: int,
        risk_filter: Optional[str] = None,
        domain_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List conflicts with optional filters.
        
        If auto_refresh is True and data is stale, refreshes first.
        """
        if self.auto_refresh and self.is_stale(playset_id):
            self.refresh(playset_id)
        
        sql = """
            SELECT cu.*, GROUP_CONCAT(
                cc.candidate_id || '|' || cc.source_kind || '|' || 
                cc.source_name || '|' || cc.load_order_index || '|' || cc.is_winner
            ) as candidates_csv
            FROM conflict_units cu
            LEFT JOIN conflict_candidates cc ON cu.conflict_unit_id = cc.conflict_unit_id
            WHERE cu.playset_id = ?
        """
        params: List[Any] = [playset_id]
        
        if risk_filter:
            sql += " AND cu.risk = ?"
            params.append(risk_filter)
        
        if domain_filter:
            sql += " AND cu.domain = ?"
            params.append(domain_filter)
        
        if status_filter:
            sql += " AND cu.resolution_status = ?"
            params.append(status_filter)
        
        sql += " GROUP BY cu.conflict_unit_id ORDER BY cu.risk_score DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        results = []
        for row in self.conn.execute(sql, params):
            conflict = dict(row)
            
            # Parse candidates
            candidates = []
            if conflict.get('candidates_csv'):
                for cand_str in conflict['candidates_csv'].split(','):
                    parts = cand_str.split('|')
                    if len(parts) >= 5:
                        candidates.append({
                            'candidate_id': parts[0],
                            'source_kind': parts[1],
                            'source_name': parts[2],
                            'load_order_index': int(parts[3]),
                            'is_winner': bool(int(parts[4]))
                        })
            
            conflict['candidates'] = candidates
            del conflict['candidates_csv']
            
            # Parse reasons JSON
            if conflict.get('reasons_json'):
                conflict['reasons'] = json.loads(conflict['reasons_json'])
                del conflict['reasons_json']
            
            results.append(conflict)
        
        return results
    
    def get_conflict_detail(self, conflict_unit_id: str) -> Optional[Dict[str, Any]]:
        """Get full details for a specific conflict unit."""
        row = self.conn.execute("""
            SELECT * FROM conflict_units WHERE conflict_unit_id = ?
        """, (conflict_unit_id,)).fetchone()
        
        if not row:
            return None
        
        conflict = dict(row)
        
        # Parse reasons
        if conflict.get('reasons_json'):
            conflict['reasons'] = json.loads(conflict['reasons_json'])
        
        # Get candidates with contribution details
        candidates = []
        for cand_row in self.conn.execute("""
            SELECT cc.*, cu.relpath, cu.line_number, cu.node_hash, cu.summary
            FROM conflict_candidates cc
            JOIN contribution_units cu ON cc.contrib_id = cu.contrib_id
            WHERE cc.conflict_unit_id = ?
            ORDER BY cc.load_order_index
        """, (conflict_unit_id,)):
            candidates.append(dict(cand_row))
        
        conflict['candidates'] = candidates
        
        # Get resolution if exists
        res_row = self.conn.execute("""
            SELECT * FROM resolution_choices WHERE conflict_unit_id = ?
        """, (conflict_unit_id,)).fetchone()
        
        if res_row:
            conflict['resolution'] = dict(res_row)
        
        return conflict
    
    def resolve_conflict(
        self,
        conflict_unit_id: str,
        decision_type: str,
        winner_candidate_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Record a resolution decision for a conflict.
        
        Args:
            conflict_unit_id: The conflict to resolve
            decision_type: 'winner' or 'defer'
            winner_candidate_id: Required if decision_type is 'winner'
            notes: Optional notes
        
        Returns:
            Resolution record
        """
        resolution_id = hashlib.sha256(
            f"{conflict_unit_id}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]
        
        self.conn.execute("""
            INSERT INTO resolution_choices
            (resolution_id, conflict_unit_id, decision_type, winner_candidate_id, notes, applied_by)
            VALUES (?, ?, ?, ?, ?, 'user')
        """, (resolution_id, conflict_unit_id, decision_type, winner_candidate_id, notes))
        
        # Update conflict status
        status = 'deferred' if decision_type == 'defer' else 'resolved'
        self.conn.execute("""
            UPDATE conflict_units 
            SET resolution_status = ?, resolution_id = ?
            WHERE conflict_unit_id = ?
        """, (status, resolution_id, conflict_unit_id))
        
        self.conn.commit()
        
        return {
            'resolution_id': resolution_id,
            'conflict_unit_id': conflict_unit_id,
            'decision_type': decision_type,
            'winner_candidate_id': winner_candidate_id,
            'status': status
        }
