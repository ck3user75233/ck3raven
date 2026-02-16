"""
CK3Raven Conflicts Report Generator

Produces deterministic, machine-readable conflict reports for a playset.

Two conflict levels:
1. File-level conflicts - path collisions (who touches the same vpath)
2. ID-level conflicts - semantic collisions within parseable domains

Schema version: ck3raven.conflicts.v1

All operations are database-only - no file I/O.
"""

from __future__ import annotations

import json
import hashlib
import sqlite3
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any, Iterator, Tuple
from datetime import datetime, timezone
from enum import Enum


# =============================================================================
# SCHEMA VERSION
# =============================================================================

SCHEMA_VERSION = "ck3raven.conflicts.v1"
RULESET_VERSION = "rules_0.1.0"


# =============================================================================
# ENUMS
# =============================================================================

class RiskBucket(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class UncertaintyBucket(Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SeparabilityClass(Enum):
    SEPARATELY_RESOLVABLE = "separately_resolvable"
    ENTANGLED = "entangled"
    UNKNOWN = "unknown"


class MergeSemantics(Enum):
    WINNER_ONLY = "winner_only"
    APPEND = "append"
    MERGE_BY_KEY = "merge_by_key"
    UNCERTAIN = "uncertain"


# =============================================================================
# DOMAIN CONFIGURATION
# =============================================================================

# Domains where we can extract ID-level units
ID_LEVEL_SUPPORTED_DOMAINS = {
    "on_action",
    "scripted_effect",
    "scripted_trigger",
    "decisions",
    "defines",
    "localization",
    "modifiers",
    "landed_titles",
    "traits",
    "events",
    "script_values",
    "character_interactions",
}

# Domain risk weights (base score contribution)
DOMAIN_RISK_WEIGHTS = {
    "on_action": 40,
    "events": 35,
    "character_interactions": 35,
    "gui": 45,
    "interface": 40,
    "scripted_effect": 25,
    "scripted_trigger": 25,
    "decisions": 30,
    "traits": 20,
    "landed_titles": 25,
    "modifiers": 15,
    "defines": 10,
    "localization": 5,
    "gfx": 10,
    "portrait": 20,
    "other": 15,
}

# Domain merge confidence
DOMAIN_MERGE_CONFIDENCE = {
    "localization": "high",      # Very deterministic (per-key)
    "defines": "high",           # Per-key override
    "script_values": "medium",
    "scripted_effect": "medium",
    "scripted_trigger": "medium",
    "decisions": "medium",
    "traits": "medium",
    "events": "medium",
    "on_action": "low",          # Complex (container merge + on_add append)
    "gui": "low",                # FIOS behavior
    "character_interactions": "medium",
    "other": "low",
}


# =============================================================================
# DATA CONTRACTS - SOURCE
# =============================================================================

@dataclass
class SourceInfo:
    """Identifies a content source (game files or mod).
    
    No 'kind' field — the name is sufficient. Game files are named
    'CK3 Game Files' and are always mods[0] in the load order.
    """
    content_version_id: int
    name: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {"content_version_id": self.content_version_id, "name": self.name}


@dataclass
class LoadOrderEntry:
    """An entry in the load order.
    
    No 'kind' field — game files are mods[0], identified by name.
    """
    content_version_id: int
    name: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {"content_version_id": self.content_version_id, "name": self.name}


# =============================================================================
# DATA CONTRACTS - FILE-LEVEL CONFLICT
# =============================================================================

@dataclass
class FileCandidate:
    """A candidate in a file-level conflict."""
    source: SourceInfo
    file_id: int
    content_hash: str
    size: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "file_id": self.file_id,
            "content_hash": self.content_hash,
            "size": self.size,
        }


@dataclass
class FileWinner:
    """The winner of a file-level conflict by load order."""
    content_version_id: int
    source_name: str
    reason: str = "last in load order overwrites file"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FileAnalysis:
    """Analysis metadata for a file conflict."""
    id_level_supported: bool
    id_units_extracted: int = 0
    id_units_conflicting: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RiskInfo:
    """Risk assessment for a conflict."""
    bucket: str  # low, medium, high
    score: int   # 0-100
    reasons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FileConflict:
    """A file-level conflict (path collision)."""
    vpath: str
    domain: str
    file_type: str  # ck3_script, localization, gfx, other
    candidates: List[FileCandidate] = field(default_factory=list)
    winner_by_load_order: Optional[FileWinner] = None
    analysis: Optional[FileAnalysis] = None
    risk: Optional[RiskInfo] = None
    
    def to_dict(self) -> Dict[str, Any]:
        d = {
            "vpath": self.vpath,
            "domain": self.domain,
            "file_type": self.file_type,
            "candidates": [c.to_dict() for c in self.candidates],
        }
        if self.winner_by_load_order:
            d["winner_by_load_order"] = self.winner_by_load_order.to_dict()
        if self.analysis:
            d["analysis"] = self.analysis.to_dict()
        if self.risk:
            d["risk"] = self.risk.to_dict()
        return d


# =============================================================================
# DATA CONTRACTS - ID-LEVEL CONFLICT
# =============================================================================

@dataclass
class SymbolRef:
    """A symbol reference."""
    type: str
    name: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateSummary:
    """Summary of what a candidate defines/uses."""
    symbols_defined: List[SymbolRef] = field(default_factory=list)
    refs_used_top: List[SymbolRef] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbols_defined": [s.to_dict() for s in self.symbols_defined],
            "refs_used_top": [r.to_dict() for r in self.refs_used_top],
        }


@dataclass
class IDCandidate:
    """A candidate in an ID-level conflict."""
    candidate_id: str
    source: SourceInfo
    file_id: int
    node_id: Optional[str] = None
    content_hash: Optional[str] = None
    summary: Optional[CandidateSummary] = None
    relpath: Optional[str] = None
    line_number: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        d = {
            "candidate_id": self.candidate_id,
            "source": self.source.to_dict(),
            "file_id": self.file_id,
        }
        if self.node_id:
            d["node_id"] = self.node_id
        if self.content_hash:
            d["content_hash"] = self.content_hash
        if self.summary:
            d["summary"] = self.summary.to_dict()
        if self.relpath:
            d["relpath"] = self.relpath
        if self.line_number:
            d["line_number"] = self.line_number
        return d


@dataclass
class EngineWinner:
    """The effective winner per engine load-order rules."""
    candidate_id: str
    reason: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MergeSemanticInfo:
    """Merge semantics for a unit."""
    expected: str  # winner_only, append, merge_by_key, uncertain
    confidence: str  # high, medium, low
    notes: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        d = {"expected": self.expected, "confidence": self.confidence}
        if self.notes:
            d["notes"] = self.notes
        return d


@dataclass
class UnknownRef:
    """A reference that may be unknown if a candidate wins."""
    type: str
    name: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ImpactInfo:
    """Impact analysis for a conflict."""
    refs_unknown_if_choose_candidate: List[Dict[str, Any]] = field(default_factory=list)
    downstream_units_touched_estimate: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UncertaintyInfo:
    """Uncertainty assessment."""
    bucket: str  # none, low, medium, high
    score: int   # 0-100
    reasons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SeparabilityInfo:
    """Whether this conflict can be resolved independently."""
    class_: str  # separately_resolvable, entangled, unknown
    reasons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {"class": self.class_, "reasons": self.reasons}


@dataclass
class IDConflict:
    """An ID-level conflict (semantic collision)."""
    unit_key: str
    domain: str
    container_vpath: str
    candidates: List[IDCandidate] = field(default_factory=list)
    engine_effective_winner: Optional[EngineWinner] = None
    merge_semantics: Optional[MergeSemanticInfo] = None
    impact: Optional[ImpactInfo] = None
    risk: Optional[RiskInfo] = None
    uncertainty: Optional[UncertaintyInfo] = None
    separability: Optional[SeparabilityInfo] = None
    
    def to_dict(self) -> Dict[str, Any]:
        d = {
            "unit_key": self.unit_key,
            "domain": self.domain,
            "container_vpath": self.container_vpath,
            "candidates": [c.to_dict() for c in self.candidates],
        }
        if self.engine_effective_winner:
            d["engine_effective_winner"] = self.engine_effective_winner.to_dict()
        if self.merge_semantics:
            d["merge_semantics"] = self.merge_semantics.to_dict()
        if self.impact:
            d["impact"] = self.impact.to_dict()
        if self.risk:
            d["risk"] = self.risk.to_dict()
        if self.uncertainty:
            d["uncertainty"] = self.uncertainty.to_dict()
        if self.separability:
            d["separability"] = self.separability.to_dict()
        return d


# =============================================================================
# DATA CONTRACTS - REPORT
# =============================================================================

@dataclass
class DomainSummary:
    """Summary for a single domain."""
    domain: str
    file_conflicts: int
    id_conflicts: int
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReportSummary:
    """Summary statistics for the report."""
    file_conflicts: int
    id_conflicts: int
    high_risk_id_conflicts: int
    uncertain_conflicts: int
    top_domains: List[DomainSummary] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["top_domains"] = [ds.to_dict() for ds in self.top_domains]
        return d


@dataclass
class ReportContext:
    """Context for report generation."""
    playset_id: int
    playset_name: str
    parser_version: str
    ruleset_version: str
    load_order: List[LoadOrderEntry] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = {
            "playset_id": self.playset_id,
            "playset_name": self.playset_name,
            "parser_version": self.parser_version,
            "ruleset_version": self.ruleset_version,
            "load_order": [e.to_dict() for e in self.load_order],
        }
        return d


@dataclass
class ConflictsReport:
    """The complete conflicts report."""
    schema: str = SCHEMA_VERSION
    generated_at: str = ""
    context: Optional[ReportContext] = None
    summary: Optional[ReportSummary] = None
    file_level: List[FileConflict] = field(default_factory=list)
    id_level: List[IDConflict] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    uncertainties: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "generated_at": self.generated_at,
            "context": self.context.to_dict() if self.context else None,
            "summary": self.summary.to_dict() if self.summary else None,
            "file_level": {"items": [f.to_dict() for f in self.file_level]},
            "id_level": {"items": [i.to_dict() for i in self.id_level]},
            "notes": self.notes,
            "uncertainties": self.uncertainties,
        }
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_domain_from_vpath(vpath: str) -> str:
    """Determine domain from virtual path."""
    parts = vpath.replace("\\", "/").lower().split("/")
    
    # Check common folder mappings
    domain_folders = {
        "on_action": "on_action",
        "on_actions": "on_action",
        "scripted_effects": "scripted_effect",
        "scripted_triggers": "scripted_trigger",
        "decisions": "decisions",
        "defines": "defines",
        "localization": "localization",
        "modifiers": "modifiers",
        "static_modifiers": "modifiers",
        "landed_titles": "landed_titles",
        "traits": "traits",
        "events": "events",
        "script_values": "script_values",
        "character_interactions": "character_interactions",
        "gui": "gui",
        "interface": "interface",
        "gfx": "gfx",
        "portrait": "portrait",
        "coat_of_arms": "coat_of_arms",
        "culture": "culture",
        "religion": "religion",
        "governments": "governments",
        "laws": "laws",
        "casus_belli_types": "casus_belli",
    }
    
    for part in parts:
        if part in domain_folders:
            return domain_folders[part]
    
    return "other"


def get_file_type(vpath: str) -> str:
    """Determine file type from path."""
    vpath_lower = vpath.lower()
    
    if vpath_lower.endswith(".yml") or "localization" in vpath_lower:
        return "localization"
    if vpath_lower.endswith((".dds", ".png", ".tga")):
        return "gfx"
    if vpath_lower.endswith(".gui"):
        return "gui"
    if any(x in vpath_lower for x in ["common/", "events/", "history/"]):
        return "ck3_script"
    
    return "other"


def compute_file_risk(
    domain: str,
    candidate_count: int,
    size_delta_ratio: float,
    id_conflicts_inside: int,
) -> RiskInfo:
    """Compute risk for a file conflict."""
    # Base domain risk
    base = DOMAIN_RISK_WEIGHTS.get(domain, DOMAIN_RISK_WEIGHTS["other"])
    
    # Modifiers
    score = base
    reasons = []
    
    if domain in ("on_action", "events", "gui", "interface"):
        reasons.append("hotspot_domain")
    
    # +10 per additional candidate beyond 2
    if candidate_count > 2:
        extra = (candidate_count - 2) * 10
        score += extra
        reasons.append(f"{candidate_count}_candidates")
    
    # +10 if size delta is huge (>50% difference suggests full replacement)
    if size_delta_ratio > 0.5:
        score += 10
        reasons.append("large_size_delta")
    
    # +10 if many ID conflicts inside
    if id_conflicts_inside > 5:
        score += 10
        reasons.append("many_id_conflicts_inside")
    elif id_conflicts_inside > 0:
        score += 5
        reasons.append("has_id_conflicts")
    
    # Cap at 100
    score = min(score, 100)
    
    # Bucket
    if score < 30:
        bucket = "low"
    elif score < 60:
        bucket = "medium"
    else:
        bucket = "high"
    
    return RiskInfo(bucket=bucket, score=score, reasons=reasons)


def compute_id_risk(
    domain: str,
    candidate_count: int,
    has_unknown_refs: bool,
    merge_uncertain: bool,
) -> RiskInfo:
    """Compute risk for an ID-level conflict."""
    base = DOMAIN_RISK_WEIGHTS.get(domain, DOMAIN_RISK_WEIGHTS["other"])
    
    score = base
    reasons = []
    
    if domain in ("on_action", "events"):
        reasons.append("domain_hotspot")
    
    if candidate_count > 2:
        extra = (candidate_count - 2) * 15
        score += extra
        reasons.append(f"{candidate_count}_candidates")
    
    if has_unknown_refs:
        score += 15
        reasons.append("unknown_refs_possible")
    
    if merge_uncertain:
        score += 10
        reasons.append("merge_rule_uncertain")
    
    score = min(score, 100)
    
    if score < 30:
        bucket = "low"
    elif score < 60:
        bucket = "medium"
    else:
        bucket = "high"
    
    return RiskInfo(bucket=bucket, score=score, reasons=reasons)


def compute_id_uncertainty(domain: str, merge_semantics: str) -> UncertaintyInfo:
    """Compute uncertainty for an ID-level conflict."""
    confidence = DOMAIN_MERGE_CONFIDENCE.get(domain, "low")
    
    reasons = []
    if merge_semantics == "uncertain":
        reasons.append("merge_rule_uncertain")
    if confidence == "low":
        reasons.append("domain_behavior_complex")
    
    if confidence == "high" and merge_semantics != "uncertain":
        return UncertaintyInfo(bucket="none", score=0, reasons=[])
    elif confidence == "medium":
        return UncertaintyInfo(bucket="low", score=25, reasons=reasons)
    else:
        return UncertaintyInfo(bucket="medium", score=50, reasons=reasons)


# =============================================================================
# REPORT GENERATOR
# =============================================================================

class ConflictsReportGenerator:
    """
    Generates conflict reports from the ck3raven database.
    
    All operations are database-only - no file I/O.
    """
    
    def __init__(
        self,
        conn: sqlite3.Connection,
        parser_version: str = "parser_0.1.0",
    ):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.parser_version = parser_version
    
    def generate(
        self,
        playset_id: int,
        domains_include: Optional[List[str]] = None,
        domains_exclude: Optional[List[str]] = None,
        paths_filter: Optional[str] = None,
        min_candidates: int = 2,
        min_risk_score: int = 0,
        progress_callback: Optional[callable] = None,
    ) -> ConflictsReport:
        """
        Generate a complete conflicts report for a playset.
        
        Args:
            playset_id: Playset to analyze
            domains_include: Only these domains (None = all)
            domains_exclude: Exclude these domains
            paths_filter: SQL LIKE pattern for paths
            min_candidates: Minimum candidates to count as conflict
            min_risk_score: Minimum risk score to include
            progress_callback: callback(step, total, message)
        
        Returns:
            ConflictsReport with file and ID level conflicts
        """
        report = ConflictsReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        
        # Step 1: Build context
        if progress_callback:
            progress_callback(1, 4, "Building report context...")
        report.context = self._build_context(playset_id)
        
        # Step 2: Build virtual path index and find file conflicts
        if progress_callback:
            progress_callback(2, 4, "Analyzing file-level conflicts...")
        load_order_map = {e.content_version_id: i for i, e in enumerate(report.context.load_order)}
        report.file_level = self._find_file_conflicts(
            playset_id, load_order_map, domains_include, domains_exclude, paths_filter, min_candidates
        )
        
        # Step 3: For parseable files, extract ID-level conflicts
        if progress_callback:
            progress_callback(3, 4, "Analyzing ID-level conflicts...")
        report.id_level = self._find_id_conflicts(
            playset_id, load_order_map, domains_include, domains_exclude, paths_filter, min_candidates
        )
        
        # Step 4: Build summary
        if progress_callback:
            progress_callback(4, 4, "Building summary...")
        report.summary = self._build_summary(report, min_risk_score)
        
        return report
    
    def _build_context(self, playset_id: int) -> ReportContext:
        """Build the report context with load order.
        
        Queries all content_versions ordered by content_version_id.
        Game files are mods[0] — no special identification needed.
        """
        load_order = []
        
        rows = self.conn.execute("""
            SELECT content_version_id, name FROM content_versions
            ORDER BY content_version_id ASC
        """).fetchall()
        
        for row in rows:
            load_order.append(LoadOrderEntry(
                content_version_id=row["content_version_id"],
                name=row["name"] or "Unknown",
            ))
        
        return ReportContext(
            playset_id=playset_id,
            playset_name=f"playset_{playset_id}",
            parser_version=self.parser_version,
            ruleset_version=RULESET_VERSION,
            load_order=load_order,
        )
    
    def _find_file_conflicts(
        self,
        playset_id: int,
        load_order_map: Dict[int, int],
        domains_include: Optional[List[str]],
        domains_exclude: Optional[List[str]],
        paths_filter: Optional[str],
        min_candidates: int,
    ) -> List[FileConflict]:
        """Find all file-level conflicts (path collisions)."""
        conflicts = []
        
        # Query all files from all content_versions, grouped by relpath
        # This finds path collisions (same relpath in multiple CVs)
        sql = """
            SELECT 
                f.relpath as vpath,
                GROUP_CONCAT(DISTINCT f.content_version_id) as cv_ids,
                COUNT(DISTINCT f.content_version_id) as source_count
            FROM files f
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
        """
        params: list = []
        
        if paths_filter:
            sql += " WHERE f.relpath LIKE ?"
            params.append(paths_filter)
        
        sql += " GROUP BY f.relpath HAVING source_count >= ?"
        params.append(min_candidates)
        
        rows = self.conn.execute(sql, params).fetchall()
        
        for row in rows:
            vpath = row["vpath"]
            domain = get_domain_from_vpath(vpath)
            
            # Apply domain filters
            if domains_include and domain not in domains_include:
                continue
            if domains_exclude and domain in domains_exclude:
                continue
            
            # Get candidates for this file
            cv_ids = [int(x) for x in row["cv_ids"].split(",")]
            candidates = []
            
            for cv_id in cv_ids:
                file_row = self.conn.execute("""
                    SELECT 
                        f.file_id, f.content_hash,
                        cv.content_version_id,
                        cv.name as source_name,
                        fc.size as file_size
                    FROM files f
                    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                    LEFT JOIN file_contents fc ON f.content_hash = fc.content_hash
                    WHERE f.content_version_id = ? AND f.relpath = ?
                """, (cv_id, vpath)).fetchone()
                
                if file_row:
                    source = SourceInfo(
                        content_version_id=cv_id,
                        name=file_row["source_name"],
                    )
                    candidates.append(FileCandidate(
                        source=source,
                        file_id=file_row["file_id"],
                        content_hash=file_row["content_hash"] or "",
                        size=file_row["file_size"] or 0,
                    ))
            
            if len(candidates) < min_candidates:
                continue
            
            # Determine winner by load order (last in order wins)
            sorted_candidates = sorted(
                candidates,
                key=lambda c: load_order_map.get(c.source.content_version_id, -1)
            )
            winner_candidate = sorted_candidates[-1]
            winner = FileWinner(
                content_version_id=winner_candidate.source.content_version_id,
                source_name=winner_candidate.source.name,
            )
            
            # Compute analysis
            id_supported = domain in ID_LEVEL_SUPPORTED_DOMAINS
            analysis = FileAnalysis(
                id_level_supported=id_supported,
                id_units_extracted=0,
                id_units_conflicting=0,
            )
            
            # Compute risk
            sizes = [c.size for c in candidates if c.size > 0]
            if len(sizes) >= 2:
                size_delta = abs(max(sizes) - min(sizes)) / max(sizes)
            else:
                size_delta = 0
            
            risk = compute_file_risk(
                domain=domain,
                candidate_count=len(candidates),
                size_delta_ratio=size_delta,
                id_conflicts_inside=0,  # Will be updated in ID pass
            )
            
            conflict = FileConflict(
                vpath=vpath,
                domain=domain,
                file_type=get_file_type(vpath),
                candidates=candidates,
                winner_by_load_order=winner,
                analysis=analysis,
                risk=risk,
            )
            conflicts.append(conflict)
        
        return conflicts
    
    def _find_id_conflicts(
        self,
        playset_id: int,
        load_order_map: Dict[int, int],
        domains_include: Optional[List[str]],
        domains_exclude: Optional[List[str]],
        paths_filter: Optional[str],
        min_candidates: int,
    ) -> List[IDConflict]:
        """Find all ID-level conflicts from contribution_units table.
        
        Contributions are now per-content_version, so we use a CTE to
        select contributions that are part of this playset.
        """
        conflicts = []
        
        # Check if contribution_units table exists and has data
        try:
            count = self.conn.execute("""
                SELECT COUNT(*) FROM contribution_units
            """).fetchone()[0]
        except sqlite3.OperationalError:
            # Table doesn't exist - no ID-level analysis available
            return conflicts
        
        if count == 0:
            return conflicts
        
        # Build CTE for playset contributions with full data.
        # Single JOIN — every content_version has a name, no special cases.
        playset_cte = """
            playset_contribs AS (
                SELECT 
                    cu.contrib_id, cu.content_version_id, cu.file_id,
                    cu.domain, cu.unit_key, cu.node_path, cu.relpath, cu.line_number,
                    cu.merge_behavior, cu.symbols_json, cu.refs_json, cu.node_hash, cu.summary,
                    cv.content_version_id as load_order_index,
                    cv.name as source_name
                FROM contribution_units cu
                JOIN content_versions cv ON cu.content_version_id = cv.content_version_id
            )
        """
        
        # Find unit_keys with multiple candidates
        sql = f"""
            WITH {playset_cte}
            SELECT 
                pc.unit_key,
                pc.domain,
                COUNT(DISTINCT pc.content_version_id) as candidate_count
            FROM playset_contribs pc
        """
        params = {"playset_id": playset_id}
        
        if paths_filter:
            sql += " WHERE pc.relpath LIKE :paths_filter"
            params["paths_filter"] = paths_filter
        
        sql += " GROUP BY pc.unit_key, pc.domain HAVING candidate_count >= :min_candidates"
        params["min_candidates"] = min_candidates
        
        conflict_keys = self.conn.execute(sql, params).fetchall()
        
        for key_row in conflict_keys:
            unit_key = key_row["unit_key"]
            domain = key_row["domain"]
            
            # Apply domain filters
            if domains_include and domain not in domains_include:
                continue
            if domains_exclude and domain in domains_exclude:
                continue
            
            # Get all candidates for this unit_key
            candidates_rows = self.conn.execute(f"""
                WITH {playset_cte}
                SELECT 
                    pc.contrib_id, pc.content_version_id, pc.file_id,
                    pc.node_path, pc.relpath, pc.line_number,
                    pc.node_hash, pc.summary, pc.symbols_json, pc.refs_json,
                    pc.source_name
                FROM playset_contribs pc
                WHERE pc.unit_key = :unit_key
                ORDER BY pc.content_version_id
            """, {"playset_id": playset_id, "unit_key": unit_key}).fetchall()
            
            candidates = []
            container_vpath = ""
            
            for i, cr in enumerate(candidates_rows):
                source = SourceInfo(
                    content_version_id=cr["content_version_id"],
                    name=cr["source_name"],
                )
                
                # Parse symbols and refs
                try:
                    symbols_raw = json.loads(cr["symbols_json"]) if cr["symbols_json"] else []
                    refs_raw = json.loads(cr["refs_json"]) if cr["refs_json"] else []
                except (json.JSONDecodeError, TypeError):
                    symbols_raw = []
                    refs_raw = []
                
                summary = CandidateSummary(
                    symbols_defined=[SymbolRef(**s) for s in symbols_raw[:5]],
                    refs_used_top=[SymbolRef(**r) for r in refs_raw[:5]],
                )
                
                candidate = IDCandidate(
                    candidate_id=f"cand_{i}_{cr['contrib_id'][:8]}",
                    source=source,
                    file_id=cr["file_id"],
                    node_id=cr["node_path"],
                    content_hash=cr["node_hash"],
                    summary=summary,
                    relpath=cr["relpath"],
                    line_number=cr["line_number"],
                )
                candidates.append(candidate)
                
                if not container_vpath:
                    container_vpath = cr["relpath"]
            
            # Sort by load order and determine winner
            sorted_candidates = sorted(
                candidates,
                key=lambda c: load_order_map.get(c.source.content_version_id, -1)
            )
            winner = EngineWinner(
                candidate_id=sorted_candidates[-1].candidate_id,
                reason="later load order defines same unit_key; engine chooses last definition"
            )
            
            # Determine merge semantics
            merge_expected = "winner_only"
            merge_confidence = DOMAIN_MERGE_CONFIDENCE.get(domain, "low")
            merge_notes = None
            
            if domain == "on_action":
                merge_expected = "uncertain"
                merge_notes = "on_action effects often behave as overwrite-per-entry; treat as winner-only unless proven appendable"
            elif domain == "localization":
                merge_expected = "winner_only"
                merge_notes = "per-key override"
            
            merge_semantics = MergeSemanticInfo(
                expected=merge_expected,
                confidence=merge_confidence,
                notes=merge_notes,
            )
            
            # Compute risk and uncertainty
            has_unknown_refs = False  # TODO: Check against symbol table
            merge_uncertain = merge_expected == "uncertain"
            
            risk = compute_id_risk(
                domain=domain,
                candidate_count=len(candidates),
                has_unknown_refs=has_unknown_refs,
                merge_uncertain=merge_uncertain,
            )
            
            uncertainty = compute_id_uncertainty(domain, merge_expected)
            
            # Separability
            separability = SeparabilityInfo(
                class_="separately_resolvable",
                reasons=["single_unit_key", "no_renames_detected"],
            )
            
            conflict = IDConflict(
                unit_key=unit_key,
                domain=domain,
                container_vpath=container_vpath,
                candidates=candidates,
                engine_effective_winner=winner,
                merge_semantics=merge_semantics,
                risk=risk,
                uncertainty=uncertainty,
                separability=separability,
            )
            conflicts.append(conflict)
        
        return conflicts
    
    def _build_summary(self, report: ConflictsReport, min_risk_score: int) -> ReportSummary:
        """Build summary statistics."""
        # Filter by risk if needed
        file_conflicts = [f for f in report.file_level if not min_risk_score or (f.risk and f.risk.score >= min_risk_score)]
        id_conflicts = [i for i in report.id_level if not min_risk_score or (i.risk and i.risk.score >= min_risk_score)]
        
        high_risk_ids = [i for i in id_conflicts if i.risk and i.risk.bucket == "high"]
        uncertain_ids = [i for i in id_conflicts if i.uncertainty and i.uncertainty.bucket in ("medium", "high")]
        
        # Domain summaries
        domain_stats: Dict[str, Dict[str, int]] = {}
        
        for f in file_conflicts:
            if f.domain not in domain_stats:
                domain_stats[f.domain] = {"file_conflicts": 0, "id_conflicts": 0}
            domain_stats[f.domain]["file_conflicts"] += 1
        
        for i in id_conflicts:
            if i.domain not in domain_stats:
                domain_stats[i.domain] = {"file_conflicts": 0, "id_conflicts": 0}
            domain_stats[i.domain]["id_conflicts"] += 1
        
        # Sort by total conflicts
        top_domains = sorted(
            [
                DomainSummary(domain=d, file_conflicts=s["file_conflicts"], id_conflicts=s["id_conflicts"])
                for d, s in domain_stats.items()
            ],
            key=lambda x: x.file_conflicts + x.id_conflicts,
            reverse=True,
        )[:10]
        
        return ReportSummary(
            file_conflicts=len(file_conflicts),
            id_conflicts=len(id_conflicts),
            high_risk_id_conflicts=len(high_risk_ids),
            uncertain_conflicts=len(uncertain_ids),
            top_domains=top_domains,
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def generate_conflicts_report(
    conn: sqlite3.Connection,
    playset_id: int,
    **kwargs,
) -> ConflictsReport:
    """Convenience function to generate a conflicts report."""
    generator = ConflictsReportGenerator(conn)
    return generator.generate(playset_id, **kwargs)


def report_to_json(report: ConflictsReport, path: str) -> None:
    """Write report to JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(report.to_json())


def report_summary_cli(report: ConflictsReport) -> str:
    """Generate CLI-friendly summary text."""
    lines = []
    lines.append("=" * 60)
    lines.append("CK3Raven Conflicts Report")
    lines.append("=" * 60)
    
    if report.context:
        lines.append(f"Playset: {report.context.playset_name}")
        lines.append(f"Mods: {len(report.context.load_order) - 1}")
    
    lines.append(f"Generated: {report.generated_at}")
    lines.append("")
    
    if report.summary:
        s = report.summary
        lines.append("SUMMARY")
        lines.append("-" * 40)
        lines.append(f"File-level conflicts: {s.file_conflicts}")
        lines.append(f"ID-level conflicts:   {s.id_conflicts}")
        lines.append(f"High-risk ID:         {s.high_risk_id_conflicts}")
        lines.append(f"Uncertain:            {s.uncertain_conflicts}")
        lines.append("")
        
        if s.top_domains:
            lines.append("TOP DOMAINS")
            lines.append("-" * 40)
            for d in s.top_domains[:5]:
                lines.append(f"  {d.domain:25} files:{d.file_conflicts:4}  ids:{d.id_conflicts:4}")
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)
