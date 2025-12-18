"""
Contribution Unit Extraction

Extracts ContributionUnits from parsed ASTs in the database.
Works entirely on indexed data - no file I/O.
"""

import hashlib
import json
import sqlite3
from typing import List, Dict, Optional, Iterator, Tuple, Any
from dataclasses import asdict

from ck3raven.resolver.contributions import (
    ContributionUnit,
    ConflictUnit,
    ConflictCandidate,
    MergeCapability,
    RiskLevel,
    UncertaintyLevel,
    get_domain_from_path,
    make_unit_key,
    get_merge_behavior,
    compute_risk_score,
    compute_uncertainty,
    get_merge_capability,
    init_contribution_schema,
)


# =============================================================================
# AST TRAVERSAL
# =============================================================================

def extract_top_level_blocks(ast: Dict[str, Any]) -> Iterator[Tuple[str, Dict[str, Any], int]]:
    """
    Extract top-level block definitions from an AST.
    
    Yields:
        Tuples of (block_name, block_node, line_number)
    """
    if not ast or not isinstance(ast, dict):
        return
    
    # Handle root node (usually "root" or list of statements)
    children = ast.get("children", [])
    if not children and "statements" in ast:
        children = ast.get("statements", [])
    if not children and isinstance(ast.get("value"), list):
        children = ast.get("value", [])
    
    for child in children:
        if not isinstance(child, dict):
            continue
        
        # BlockNode format: {"kind": "block", "name": "...", "value": {...}}
        kind = child.get("kind", child.get("type", ""))
        
        if kind in ("block", "BlockNode", "assignment"):
            name = child.get("name", child.get("key", ""))
            if name and isinstance(name, str):
                line = child.get("line", child.get("line_number", 1))
                yield name, child, line


def compute_node_hash(node: Dict[str, Any]) -> str:
    """Compute a hash of an AST node for diff detection."""
    # Serialize deterministically
    serialized = json.dumps(node, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def extract_symbols_from_node(node: Dict[str, Any], domain: str) -> List[Dict[str, str]]:
    """Extract symbol definitions from an AST node."""
    symbols = []
    name = node.get("name", node.get("key", ""))
    if name:
        symbols.append({"type": domain, "name": name})
    return symbols


def extract_refs_from_node(node: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extract references used by an AST node.
    
    Looks for common reference patterns:
    - has_trait = <trait_name>
    - trigger_event = <event_id>
    - run_interaction = <interaction_name>
    - etc.
    """
    refs = []
    
    def walk(n: Any, context: str = ""):
        if not isinstance(n, dict):
            return
        
        kind = n.get("kind", n.get("type", ""))
        name = n.get("name", n.get("key", ""))
        value = n.get("value")
        
        # Known reference patterns
        ref_patterns = {
            "has_trait": "trait",
            "add_trait": "trait",
            "remove_trait": "trait",
            "trigger_event": "event",
            "fire_on_action": "on_action",
            "has_culture": "culture",
            "has_faith": "faith",
            "has_religion": "religion",
            "run_interaction": "character_interaction",
            "scripted_effect": "scripted_effect",
            "scripted_trigger": "scripted_trigger",
        }
        
        if name in ref_patterns and value and isinstance(value, str):
            refs.append({"type": ref_patterns[name], "name": value})
        
        # Recurse into children
        for child in n.get("children", []):
            walk(child, name)
        if isinstance(n.get("value"), dict):
            walk(n["value"], name)
        elif isinstance(n.get("value"), list):
            for item in n["value"]:
                walk(item, name)
    
    walk(node)
    return refs


def summarize_node(node: Dict[str, Any], domain: str) -> str:
    """Generate a human-readable summary of an AST node."""
    name = node.get("name", node.get("key", "unknown"))
    children = node.get("children", node.get("value", []))
    
    if isinstance(children, dict):
        child_keys = list(children.keys())[:5]
    elif isinstance(children, list):
        child_keys = [c.get("name", c.get("key", "?")) for c in children[:5] if isinstance(c, dict)]
    else:
        child_keys = []
    
    if child_keys:
        return f"{domain}:{name} with {', '.join(str(k) for k in child_keys)}"
    return f"{domain}:{name}"


# =============================================================================
# EXTRACTION FROM DATABASE
# =============================================================================

def extract_contributions_for_file(
    conn: sqlite3.Connection,
    file_id: int,
    content_version_id: int,
    relpath: str,
) -> List[ContributionUnit]:
    """
    Extract ContributionUnits from a single file's AST.
    
    Args:
        conn: Database connection
        file_id: File ID
        content_version_id: Content version ID
        relpath: Relative file path
    
    Returns:
        List of ContributionUnit objects
    """
    contributions = []
    
    # Get the AST for this file
    row = conn.execute("""
        SELECT a.ast_blob, a.ast_format
        FROM asts a
        JOIN files f ON a.content_hash = f.content_hash
        WHERE f.file_id = ?
        ORDER BY a.ast_id DESC
        LIMIT 1
    """, (file_id,)).fetchone()
    
    if not row:
        return contributions
    
    # Parse AST
    try:
        if row[1] == "json":
            ast = json.loads(row[0])
        else:
            # Could be msgpack, but we primarily use JSON
            ast = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return contributions
    
    # Determine domain
    domain = get_domain_from_path(relpath)
    merge_behavior = get_merge_behavior(domain, relpath)
    
    # Extract top-level blocks
    for block_name, block_node, line_number in extract_top_level_blocks(ast):
        unit_key = make_unit_key(domain, block_name)
        node_path = f"$.children[?(@.name=='{block_name}')]"
        
        contrib = ContributionUnit(
            contrib_id="",  # Will be computed
            content_version_id=content_version_id,
            file_id=file_id,
            domain=domain,
            unit_key=unit_key,
            node_path=node_path,
            relpath=relpath,
            line_number=line_number,
            merge_behavior_hint=merge_behavior,
            symbols_defined=extract_symbols_from_node(block_node, domain),
            refs_used=extract_refs_from_node(block_node),
            node_hash=compute_node_hash(block_node),
            summary=summarize_node(block_node, domain),
        )
        contrib.contrib_id = contrib.compute_id()
        contributions.append(contrib)
    
    return contributions


def extract_contributions_for_content_version(
    conn: sqlite3.Connection,
    content_version_id: int,
    folder_filter: Optional[str] = None,
    progress_callback: Optional[callable] = None,
    force: bool = False,
) -> int:
    """
    Extract all ContributionUnits for a single content_version (mod or vanilla).
    
    Contributions are extracted per content_version and reused across all playsets.
    If contributions already exist for this CV and force=False, skips extraction.
    
    Args:
        conn: Database connection
        content_version_id: Content version to extract
        folder_filter: Optional folder path filter (e.g., "common/on_action")
        progress_callback: Optional callback(current, total, message)
        force: If True, re-extract even if already done
    
    Returns:
        Number of contributions extracted (0 if already done and not forced)
    """
    # Check if already extracted (unless forcing)
    if not force:
        existing = conn.execute("""
            SELECT contributions_extracted_at FROM content_versions 
            WHERE content_version_id = ? AND contributions_extracted_at IS NOT NULL
        """, (content_version_id,)).fetchone()
        if existing:
            return 0
    
    # Initialize schema if needed
    init_contribution_schema(conn)
    
    # Clear existing contributions for this content_version
    conn.execute(
        "DELETE FROM contribution_units WHERE content_version_id = ?",
        (content_version_id,)
    )
    
    # Get all files for this content_version
    folder_pattern = f"{folder_filter}%" if folder_filter else "%"
    
    files = conn.execute("""
        SELECT f.file_id, f.relpath
        FROM files f
        WHERE f.content_version_id = ?
          AND f.relpath LIKE ?
          AND f.file_type = 'script'
          AND f.deleted = 0
        ORDER BY f.relpath
    """, (content_version_id, folder_pattern)).fetchall()
    
    total_files = len(files)
    total_contributions = 0
    
    for idx, (file_id, relpath) in enumerate(files):
        if progress_callback:
            progress_callback(idx + 1, total_files, f"Processing {relpath}")
        
        contributions = extract_contributions_for_file(
            conn, file_id, content_version_id, relpath
        )
        
        # Insert contributions
        for contrib in contributions:
            conn.execute("""
                INSERT OR REPLACE INTO contribution_units
                (contrib_id, content_version_id, file_id, domain, unit_key,
                 node_path, relpath, line_number, merge_behavior, symbols_json, refs_json,
                 node_hash, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                contrib.contrib_id,
                contrib.content_version_id,
                contrib.file_id,
                contrib.domain,
                contrib.unit_key,
                contrib.node_path,
                contrib.relpath,
                contrib.line_number,
                contrib.merge_behavior_hint,
                json.dumps(contrib.symbols_defined),
                json.dumps(contrib.refs_used),
                contrib.node_hash,
                contrib.summary,
            ))
            total_contributions += 1
    
    # Mark as extracted
    conn.execute("""
        UPDATE content_versions 
        SET contributions_extracted_at = datetime('now'),
            is_stale = 0
        WHERE content_version_id = ?
    """, (content_version_id,))
    
    conn.commit()
    return total_contributions


def extract_contributions_for_playset(
    conn: sqlite3.Connection,
    playset_id: int,
    folder_filter: Optional[str] = None,
    progress_callback: Optional[callable] = None,
    force: bool = False,
) -> int:
    """
    Extract contributions for all content_versions in a playset.
    
    This is a convenience function that iterates over vanilla + all mods
    and calls extract_contributions_for_content_version for each.
    
    Args:
        conn: Database connection
        playset_id: Playset to analyze
        folder_filter: Optional folder path filter (e.g., "common/on_action")
        progress_callback: Optional callback(current, total, message)
        force: If True, re-extract even if already done
    
    Returns:
        Total number of contributions extracted
    """
    # Get all content_versions in this playset (vanilla + mods)
    content_versions = conn.execute("""
        -- Vanilla
        SELECT cv.content_version_id, 'vanilla' as name
        FROM content_versions cv
        JOIN vanilla_versions vv ON cv.vanilla_version_id = vv.vanilla_version_id
        JOIN playsets p ON p.vanilla_version_id = vv.vanilla_version_id
        WHERE p.playset_id = ? AND cv.kind = 'vanilla'
        
        UNION ALL
        
        -- Mods
        SELECT cv.content_version_id, COALESCE(mp.name, 'Unknown Mod') as name
        FROM playset_mods pm
        JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
        LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
        WHERE pm.playset_id = ? AND pm.enabled = 1
    """, (playset_id, playset_id)).fetchall()
    
    total_cv = len(content_versions)
    total_contributions = 0
    
    for idx, (cv_id, name) in enumerate(content_versions):
        if progress_callback:
            progress_callback(idx + 1, total_cv, f"Extracting from {name}")
        
        count = extract_contributions_for_content_version(
            conn, cv_id, folder_filter, None, force
        )
        total_contributions += count
    
    return total_contributions


# =============================================================================
# CONFLICT GROUPING
# =============================================================================

def get_playset_contributions_query() -> str:
    """
    Get SQL CTE for selecting all contributions in a playset.
    
    Joins contribution_units with playset_mods and vanilla to get
    only contributions from content_versions that are part of the playset.
    """
    return """
        playset_contribs AS (
            -- Vanilla contributions
            SELECT 
                cu.contrib_id,
                cu.content_version_id,
                cu.file_id,
                cu.domain,
                cu.unit_key,
                cu.node_path,
                cu.relpath,
                cu.line_number,
                cu.merge_behavior,
                cu.symbols_json,
                cu.refs_json,
                cu.node_hash,
                cu.summary,
                -1 as load_order_index,
                'vanilla' as source_kind,
                'vanilla' as source_name
            FROM contribution_units cu
            JOIN content_versions cv ON cu.content_version_id = cv.content_version_id
            JOIN vanilla_versions vv ON cv.vanilla_version_id = vv.vanilla_version_id
            JOIN playsets p ON p.vanilla_version_id = vv.vanilla_version_id
            WHERE p.playset_id = :playset_id AND cv.kind = 'vanilla'
            
            UNION ALL
            
            -- Mod contributions  
            SELECT 
                cu.contrib_id,
                cu.content_version_id,
                cu.file_id,
                cu.domain,
                cu.unit_key,
                cu.node_path,
                cu.relpath,
                cu.line_number,
                cu.merge_behavior,
                cu.symbols_json,
                cu.refs_json,
                cu.node_hash,
                cu.summary,
                pm.load_order_index,
                'mod' as source_kind,
                COALESCE(mp.name, 'Unknown Mod') as source_name
            FROM contribution_units cu
            JOIN playset_mods pm ON cu.content_version_id = pm.content_version_id
            JOIN content_versions cv ON cu.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE pm.playset_id = :playset_id AND pm.enabled = 1
        )
    """


def group_conflicts_for_playset(
    conn: sqlite3.Connection,
    playset_id: int,
    min_candidates: int = 2,
) -> int:
    """
    Group ContributionUnits into ConflictUnits for a playset.
    
    Since contributions are per-content_version (not per-playset),
    this function joins through playset_mods to find which contributions
    are relevant to this playset.
    
    A ConflictUnit is created when multiple contributions share the same unit_key.
    
    Args:
        conn: Database connection
        playset_id: Playset to analyze
        min_candidates: Minimum candidates to be considered a conflict (default 2)
    
    Returns:
        Number of conflict units created
    """
    # Clear existing conflicts for this playset
    conn.execute("""
        DELETE FROM conflict_candidates WHERE conflict_unit_id IN (
            SELECT conflict_unit_id FROM conflict_units WHERE playset_id = ?
        )
    """, (playset_id,))
    conn.execute("DELETE FROM conflict_units WHERE playset_id = ?", (playset_id,))
    
    # Find all unit_keys with multiple contributions in this playset
    cte = get_playset_contributions_query()
    conflict_keys = conn.execute(f"""
        WITH {cte}
        SELECT 
            pc.unit_key,
            pc.domain,
            COUNT(*) as candidate_count,
            pc.merge_behavior
        FROM playset_contribs pc
        GROUP BY pc.unit_key
        HAVING COUNT(*) >= :min_candidates
        ORDER BY candidate_count DESC
    """, {"playset_id": playset_id, "min_candidates": min_candidates}).fetchall()
    
    total_conflicts = 0
    
    for unit_key, domain, candidate_count, merge_behavior in conflict_keys:
        # Get all candidates for this unit_key
        candidates = conn.execute(f"""
            WITH {cte}
            SELECT 
                pc.contrib_id,
                pc.content_version_id,
                pc.file_id,
                pc.relpath,
                pc.line_number,
                pc.node_hash,
                pc.summary,
                pc.load_order_index,
                pc.source_kind,
                pc.source_name
            FROM playset_contribs pc
            WHERE pc.unit_key = :unit_key
            ORDER BY pc.load_order_index
        """, {"playset_id": playset_id, "unit_key": unit_key}).fetchall()
        
        # Compute risk and uncertainty
        has_vanilla = any(c[8] == 'vanilla' for c in candidates)
        has_unknown_refs = False  # TODO: compute from refs_json
        has_rename_pattern = False  # TODO: detect renames
        
        risk_score, risk_level, reasons = compute_risk_score(
            domain=domain,
            candidate_count=candidate_count,
            merge_behavior=merge_behavior,
            has_vanilla=has_vanilla,
            has_unknown_refs=has_unknown_refs,
            has_rename_pattern=has_rename_pattern,
        )
        
        # Check if candidates differ significantly (different node hashes)
        node_hashes = set(c[5] for c in candidates if c[5])
        candidates_differ = len(node_hashes) > 1
        
        uncertainty = compute_uncertainty(domain, merge_behavior, candidates_differ)
        merge_capability = get_merge_capability(domain, merge_behavior)
        
        # Create conflict unit
        conflict_id = hashlib.sha256(f"{playset_id}:{unit_key}".encode()).hexdigest()[:16]
        
        conn.execute("""
            INSERT INTO conflict_units
            (conflict_unit_id, playset_id, unit_key, domain, candidate_count,
             merge_capability, risk, risk_score, uncertainty, reasons_json,
             resolution_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unresolved')
        """, (
            conflict_id,
            playset_id,
            unit_key,
            domain,
            candidate_count,
            merge_capability.name.lower(),
            risk_level.value,
            risk_score,
            uncertainty.value,
            json.dumps(reasons),
        ))
        
        # Determine winner by load order
        max_load_order = max(c[7] for c in candidates)
        
        # Create candidates
        for idx, (contrib_id, cv_id, file_id, relpath, line_number, node_hash, 
                  summary, load_order, source_kind, source_name) in enumerate(candidates):
            
            candidate_id = f"c{idx}"
            is_winner = 1 if load_order == max_load_order else 0
            
            conn.execute("""
                INSERT INTO conflict_candidates
                (conflict_unit_id, candidate_id, contrib_id, source_kind, source_name,
                 load_order_index, is_winner)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                conflict_id,
                candidate_id,
                contrib_id,
                source_kind,
                source_name,
                load_order,
                is_winner,
            ))
        
        total_conflicts += 1
    
    conn.commit()
    return total_conflicts


# =============================================================================
# QUERY FUNCTIONS
# =============================================================================

def get_conflict_summary(
    conn: sqlite3.Connection,
    playset_id: int,
) -> Dict[str, Any]:
    """
    Get a summary of all conflicts for a playset.
    
    Returns:
        Summary dict with counts by risk, domain, etc.
    """
    summary = {
        "playset_id": playset_id,
        "total": 0,
        "by_risk": {"low": 0, "med": 0, "high": 0},
        "by_domain": {},
        "by_status": {"unresolved": 0, "resolved": 0, "deferred": 0},
        "unresolved_high_risk": 0,
    }
    
    # Total and by risk
    rows = conn.execute("""
        SELECT risk, COUNT(*) 
        FROM conflict_units 
        WHERE playset_id = ?
        GROUP BY risk
    """, (playset_id,)).fetchall()
    
    for risk, count in rows:
        summary["by_risk"][risk] = count
        summary["total"] += count
    
    # By domain
    rows = conn.execute("""
        SELECT domain, COUNT(*) 
        FROM conflict_units 
        WHERE playset_id = ?
        GROUP BY domain
        ORDER BY COUNT(*) DESC
    """, (playset_id,)).fetchall()
    
    for domain, count in rows:
        summary["by_domain"][domain] = count
    
    # By status
    rows = conn.execute("""
        SELECT resolution_status, COUNT(*) 
        FROM conflict_units 
        WHERE playset_id = ?
        GROUP BY resolution_status
    """, (playset_id,)).fetchall()
    
    for status, count in rows:
        summary["by_status"][status] = count
    
    # Unresolved high risk
    summary["unresolved_high_risk"] = conn.execute("""
        SELECT COUNT(*) 
        FROM conflict_units 
        WHERE playset_id = ? AND risk = 'high' AND resolution_status = 'unresolved'
    """, (playset_id,)).fetchone()[0]
    
    return summary


def get_conflict_units(
    conn: sqlite3.Connection,
    playset_id: int,
    risk_filter: Optional[str] = None,
    domain_filter: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Get conflict units with filters.
    
    Args:
        conn: Database connection
        playset_id: Playset to query
        risk_filter: Filter by risk level (low, med, high)
        domain_filter: Filter by domain (on_action, decision, etc.)
        status_filter: Filter by resolution status
        limit: Max results
        offset: Offset for pagination
    
    Returns:
        List of conflict unit dicts with candidates
    """
    query = """
        SELECT 
            cu.conflict_unit_id,
            cu.unit_key,
            cu.domain,
            cu.candidate_count,
            cu.merge_capability,
            cu.risk,
            cu.risk_score,
            cu.uncertainty,
            cu.reasons_json,
            cu.resolution_status,
            cu.resolution_id
        FROM conflict_units cu
        WHERE cu.playset_id = ?
    """
    params: List[Any] = [playset_id]
    
    if risk_filter:
        query += " AND cu.risk = ?"
        params.append(risk_filter)
    if domain_filter:
        query += " AND cu.domain = ?"
        params.append(domain_filter)
    if status_filter:
        query += " AND cu.resolution_status = ?"
        params.append(status_filter)
    
    query += " ORDER BY cu.risk_score DESC, cu.candidate_count DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    conflicts = []
    for row in conn.execute(query, params).fetchall():
        conflict = {
            "conflict_unit_id": row[0],
            "unit_key": row[1],
            "domain": row[2],
            "candidate_count": row[3],
            "merge_capability": row[4],
            "risk": row[5],
            "risk_score": row[6],
            "uncertainty": row[7],
            "reasons": json.loads(row[8]) if row[8] else [],
            "resolution_status": row[9],
            "resolution_id": row[10],
            "candidates": [],
        }
        
        # Get candidates
        candidates = conn.execute("""
            SELECT 
                cc.candidate_id,
                cc.contrib_id,
                cc.source_kind,
                cc.source_name,
                cc.load_order_index,
                cc.is_winner,
                cu.relpath,
                cu.line_number,
                cu.node_hash,
                cu.summary
            FROM conflict_candidates cc
            JOIN contribution_units cu ON cc.contrib_id = cu.contrib_id
            WHERE cc.conflict_unit_id = ?
            ORDER BY cc.load_order_index
        """, (row[0],)).fetchall()
        
        for c in candidates:
            conflict["candidates"].append({
                "candidate_id": c[0],
                "contrib_id": c[1],
                "source_kind": c[2],
                "source_name": c[3],
                "load_order_index": c[4],
                "is_winner": bool(c[5]),
                "relpath": c[6],
                "line_number": c[7],
                "node_hash": c[8],
                "summary": c[9],
            })
        
        conflicts.append(conflict)
    
    return conflicts


def get_conflict_unit_detail(
    conn: sqlite3.Connection,
    conflict_unit_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Get detailed information about a specific conflict unit.
    
    Includes full AST nodes for each candidate.
    """
    row = conn.execute("""
        SELECT 
            cu.conflict_unit_id,
            cu.playset_id,
            cu.unit_key,
            cu.domain,
            cu.candidate_count,
            cu.merge_capability,
            cu.risk,
            cu.risk_score,
            cu.uncertainty,
            cu.reasons_json,
            cu.resolution_status,
            cu.resolution_id
        FROM conflict_units cu
        WHERE cu.conflict_unit_id = ?
    """, (conflict_unit_id,)).fetchone()
    
    if not row:
        return None
    
    conflict = {
        "conflict_unit_id": row[0],
        "playset_id": row[1],
        "unit_key": row[2],
        "domain": row[3],
        "candidate_count": row[4],
        "merge_capability": row[5],
        "risk": row[6],
        "risk_score": row[7],
        "uncertainty": row[8],
        "reasons": json.loads(row[9]) if row[9] else [],
        "resolution_status": row[10],
        "resolution_id": row[11],
        "candidates": [],
    }
    
    # Get candidates with full content
    candidates = conn.execute("""
        SELECT 
            cc.candidate_id,
            cc.contrib_id,
            cc.source_kind,
            cc.source_name,
            cc.load_order_index,
            cc.is_winner,
            cu.relpath,
            cu.line_number,
            cu.node_hash,
            cu.summary,
            cu.file_id,
            cu.symbols_json,
            cu.refs_json
        FROM conflict_candidates cc
        JOIN contribution_units cu ON cc.contrib_id = cu.contrib_id
        WHERE cc.conflict_unit_id = ?
        ORDER BY cc.load_order_index
    """, (conflict_unit_id,)).fetchall()
    
    for c in candidates:
        candidate = {
            "candidate_id": c[0],
            "contrib_id": c[1],
            "source_kind": c[2],
            "source_name": c[3],
            "load_order_index": c[4],
            "is_winner": bool(c[5]),
            "relpath": c[6],
            "line_number": c[7],
            "node_hash": c[8],
            "summary": c[9],
            "file_id": c[10],
            "symbols_defined": json.loads(c[11]) if c[11] else [],
            "refs_used": json.loads(c[12]) if c[12] else [],
        }
        
        # Get file content for this candidate
        content_row = conn.execute("""
            SELECT fc.content_text
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE f.file_id = ?
        """, (c[10],)).fetchone()
        
        if content_row and content_row[0]:
            candidate["content_preview"] = content_row[0][:2000]
        
        conflict["candidates"].append(candidate)
    
    # Get resolution if exists
    if conflict["resolution_id"]:
        resolution = conn.execute("""
            SELECT decision_type, winner_candidate_id, merge_policy_json, notes, applied_at
            FROM resolution_choices
            WHERE resolution_id = ?
        """, (conflict["resolution_id"],)).fetchone()
        
        if resolution:
            conflict["resolution"] = {
                "decision_type": resolution[0],
                "winner_candidate_id": resolution[1],
                "merge_policy": json.loads(resolution[2]) if resolution[2] else None,
                "notes": resolution[3],
                "applied_at": resolution[4],
            }
    
    return conflict


# =============================================================================
# FULL SCAN
# =============================================================================

def scan_playset_conflicts(
    conn: sqlite3.Connection,
    playset_id: int,
    folder_filter: Optional[str] = None,
    progress_callback: Optional[callable] = None,
) -> Dict[str, Any]:
    """
    Full conflict scan for a playset.
    
    1. Extracts all ContributionUnits
    2. Groups them into ConflictUnits
    3. Returns summary
    
    Args:
        conn: Database connection
        playset_id: Playset to scan
        folder_filter: Optional folder filter
        progress_callback: Optional progress callback
    
    Returns:
        Scan result with summary and timing
    """
    import time
    start = time.time()
    
    # Extract contributions
    if progress_callback:
        progress_callback(0, 100, "Extracting contributions...")
    
    contrib_count = extract_contributions_for_playset(
        conn, playset_id, folder_filter,
        progress_callback=lambda c, t, m: progress_callback(int(c/t * 50), 100, m) if progress_callback else None
    )
    
    # Group conflicts
    if progress_callback:
        progress_callback(50, 100, "Grouping conflicts...")
    
    conflict_count = group_conflicts_for_playset(conn, playset_id)
    
    # Get summary
    if progress_callback:
        progress_callback(90, 100, "Computing summary...")
    
    summary = get_conflict_summary(conn, playset_id)
    
    elapsed = time.time() - start
    
    if progress_callback:
        progress_callback(100, 100, "Done")
    
    return {
        "playset_id": playset_id,
        "contributions_extracted": contrib_count,
        "conflicts_found": conflict_count,
        "summary": summary,
        "elapsed_seconds": round(elapsed, 2),
    }
