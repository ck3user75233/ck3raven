"""
Unified MCP Tool Implementations

Consolidates multiple granular tools into parameterized commands to reduce
tool count while maintaining full functionality.

Consolidated tools:
- ck3_logs: 11 log/error/crash tools → 1 unified tool
- ck3_conflicts: 7 conflict tools → 1 unified tool
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional


# ============================================================================
# ck3_logs - Unified Logging Tool
# ============================================================================

LogSource = Literal["error", "game", "debug", "crash"]
LogCommand = Literal["summary", "list", "search", "detail", "categories", "cascades", "read"]


def ck3_logs_impl(
    source: LogSource = "error",
    command: LogCommand = "summary",
    # Filters
    priority: int | None = None,
    category: str | None = None,
    mod_filter: str | None = None,
    exclude_cascade_children: bool = True,
    # Search
    query: str | None = None,
    # Detail (for crash)
    crash_id: str | None = None,
    # Read raw
    lines: int = 100,
    from_end: bool = True,
    # Pagination
    limit: int = 50,
) -> dict:
    """
    Unified logging tool implementation.
    
    Source + Command combinations:
    
    error + summary     → Error log summary with counts by priority/category/mod
    error + list        → Filtered list of errors with fix hints  
    error + search      → Search errors by message/path
    error + cascades    → Get cascading error patterns (root causes)
    
    game + summary      → Game log summary with category breakdown
    game + list         → Filtered list of game log errors
    game + search       → Search game log by message/path
    game + categories   → Category breakdown with descriptions
    
    debug + summary     → System info, DLCs, mod list from debug.log
    
    crash + summary     → Recent crash reports list
    crash + detail      → Full crash report (requires crash_id)
    
    Any source + read   → Raw log content (tail/head with optional search)
    """
    
    # Route based on source and command
    if command == "read":
        return _read_log_raw(source, lines, from_end, query)
    
    if source == "error":
        return _error_log_handler(command, priority, category, mod_filter, 
                                   exclude_cascade_children, query, limit)
    
    elif source == "game":
        return _game_log_handler(command, category, query, limit)
    
    elif source == "debug":
        return _debug_log_handler(command)
    
    elif source == "crash":
        return _crash_handler(command, crash_id, limit)
    
    return {"error": f"Unknown source: {source}"}


def _error_log_handler(
    command: str,
    priority: int | None,
    category: str | None,
    mod_filter: str | None,
    exclude_cascade_children: bool,
    query: str | None,
    limit: int,
) -> dict:
    """Handle error.log commands."""
    from ck3raven.analyzers.error_parser import CK3ErrorParser, ERROR_CATEGORIES
    
    parser = CK3ErrorParser()
    
    try:
        parser.parse_log()
        parser.detect_cascading_errors()
    except FileNotFoundError:
        return {
            "error": "error.log not found",
            "hint": "Make sure CK3 has been run at least once",
        }
    
    if command == "summary":
        return parser.get_summary()
    
    elif command == "list":
        errors = parser.get_errors(
            category=category,
            priority=priority,
            mod_filter=mod_filter,
            exclude_cascade_children=exclude_cascade_children,
            limit=limit,
        )
        
        results = []
        for error in errors:
            cat = next((c for c in ERROR_CATEGORIES if c.name == error.category), None)
            results.append({
                **error.to_dict(),
                "fix_hint": cat.fix_hint if cat else None,
            })
        
        return {
            "count": len(results),
            "total_in_log": parser.stats['total_errors'],
            "errors": results,
        }
    
    elif command == "search":
        if not query:
            return {"error": "query parameter required for search command"}
        
        errors = parser.search_errors(query, limit=limit)
        return {
            "query": query,
            "count": len(errors),
            "errors": [e.to_dict() for e in errors],
        }
    
    elif command == "cascades":
        cascades = [c.to_dict() for c in parser.cascade_patterns]
        return {
            "cascade_count": len(cascades),
            "total_errors": parser.stats['total_errors'],
            "cascades": cascades,
            "recommendation": "Fix root errors first - they can eliminate many child errors",
        }
    
    return {"error": f"Unknown command for error source: {command}"}


def _game_log_handler(
    command: str,
    category: str | None,
    query: str | None,
    limit: int,
) -> dict:
    """Handle game.log commands."""
    from ck3raven.analyzers.log_parser import CK3LogParser, LogType, GAME_LOG_CATEGORIES
    
    parser = CK3LogParser()
    
    try:
        parser.parse_game_log()
    except FileNotFoundError:
        return {"error": "game.log not found"}
    
    if command == "summary":
        return parser.get_game_log_summary()
    
    elif command == "list":
        entries = parser.entries[LogType.GAME]
        
        if category:
            entries = [e for e in entries if e.category == category]
        
        return {
            "total_parsed": len(parser.entries[LogType.GAME]),
            "filtered_count": len(entries[:limit]),
            "summary": parser.get_game_log_summary(),
            "errors": [e.to_dict() for e in entries[:limit]],
        }
    
    elif command == "search":
        if not query:
            return {"error": "query parameter required for search command"}
        
        entries = parser.search_entries(query, log_type=LogType.GAME, limit=limit)
        return {
            "query": query,
            "count": len(entries),
            "errors": [e.to_dict() for e in entries],
        }
    
    elif command == "categories":
        stats = parser.stats.get(LogType.GAME, {})
        by_category = dict(stats.get('by_category', {}).most_common())
        
        category_info = {name: desc for name, _, _, desc in GAME_LOG_CATEGORIES}
        
        categories = []
        for cat, count in by_category.items():
            categories.append({
                "category": cat,
                "count": count,
                "description": category_info.get(cat, "Other/uncategorized errors"),
            })
        
        return {
            "total_errors": stats.get('total', 0),
            "categories": categories,
        }
    
    return {"error": f"Unknown command for game source: {command}"}


def _debug_log_handler(command: str) -> dict:
    """Handle debug.log commands."""
    from ck3raven.analyzers.log_parser import CK3LogParser
    
    parser = CK3LogParser()
    
    try:
        parser.parse_debug_log(extract_system_info=True)
    except FileNotFoundError:
        return {"error": "debug.log not found"}
    
    if command == "summary":
        return parser.get_debug_info_summary()
    
    return {"error": f"Unknown command for debug source: {command}"}


def _crash_handler(command: str, crash_id: str | None, limit: int) -> dict:
    """Handle crash report commands."""
    
    if command == "summary":
        from ck3raven.analyzers.crash_parser import get_recent_crashes
        
        crashes = get_recent_crashes(limit=limit)
        
        if not crashes:
            return {
                "count": 0,
                "message": "No crash reports found",
            }
        
        return {
            "count": len(crashes),
            "crashes": [c.to_dict() for c in crashes],
        }
    
    elif command == "detail":
        if not crash_id:
            return {"error": "crash_id parameter required for detail command"}
        
        from ck3raven.analyzers.crash_parser import parse_crash_folder
        
        crashes_dir = (
            Path.home() / "Documents" / "Paradox Interactive" / 
            "Crusader Kings III" / "crashes"
        )
        
        crash_path = crashes_dir / crash_id
        
        if not crash_path.exists():
            return {
                "error": f"Crash folder not found: {crash_id}",
                "hint": "Use source=crash, command=summary to see available crashes",
            }
        
        report = parse_crash_folder(crash_path)
        
        if not report:
            return {"error": "Failed to parse crash folder"}
        
        return report.to_dict()
    
    return {"error": f"Unknown command for crash source: {command}"}


def _read_log_raw(
    source: str,
    lines: int,
    from_end: bool,
    search: str | None,
) -> dict:
    """Read raw log content."""
    
    logs_dir = (
        Path.home() / "Documents" / "Paradox Interactive" / 
        "Crusader Kings III" / "logs"
    )
    
    log_files = {
        "error": "error.log",
        "game": "game.log",
        "debug": "debug.log",
        "setup": "setup.log",
        "gui_warnings": "gui_warnings.log",
        "database_conflicts": "database_conflicts.log",
    }
    
    if source not in log_files:
        return {
            "error": f"Unknown log source: {source}",
            "available": list(log_files.keys()),
        }
    
    log_path = logs_dir / log_files[source]
    
    if not log_path.exists():
        return {
            "error": f"Log file not found: {log_files[source]}",
            "hint": "Make sure CK3 has been run",
        }
    
    try:
        content_lines = log_path.read_text(encoding='utf-8', errors='replace').splitlines()
        
        # Apply search filter if provided
        if search:
            search_lower = search.lower()
            content_lines = [l for l in content_lines if search_lower in l.lower()]
        
        # Select lines
        if from_end:
            selected = content_lines[-lines:] if len(content_lines) > lines else content_lines
        else:
            selected = content_lines[:lines]
        
        return {
            "log_source": source,
            "total_lines": len(content_lines),
            "returned_lines": len(selected),
            "from_end": from_end,
            "search": search,
            "content": "\n".join(selected),
        }
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# ck3_conflicts - Unified Conflict Tool
# ============================================================================

ConflictCommand = Literal["scan", "summary", "list", "detail", "resolve", "content", "high_risk", "report"]


def ck3_conflicts_impl(
    command: ConflictCommand = "summary",
    # For scan
    folder_filter: str | None = None,
    # For list
    risk_filter: str | None = None,
    domain_filter: str | None = None,
    status_filter: str | None = None,
    # For detail/resolve/content
    conflict_id: str | None = None,
    unit_key: str | None = None,
    # For resolve
    decision_type: Literal["winner", "defer"] | None = None,
    winner_candidate_id: str | None = None,
    notes: str | None = None,
    # For content
    source_filter: str | None = None,
    # For report/high_risk
    domains_include: list[str] | None = None,
    domains_exclude: list[str] | None = None,
    paths_filter: str | None = None,
    min_candidates: int = 2,
    min_risk_score: int = 0,
    output_format: Literal["summary", "json", "full"] = "summary",
    # Pagination
    limit: int = 50,
    offset: int = 0,
    # Dependencies (injected by caller)
    db=None,
    playset_id: int | None = None,
    trace=None,
) -> dict:
    """
    Unified conflict tool implementation.
    
    Commands:
    
    scan        → Scan playset for unit-level conflicts (folder_filter optional)
    summary     → Get conflict summary with counts by risk/domain/status
    list        → List conflicts with filters (risk_filter, domain_filter, status_filter)
    detail      → Get detailed info for a conflict (conflict_id required)
    resolve     → Record resolution decision (conflict_id, decision_type required)
    content     → Get all contributions for a unit_key (unit_key required)
    high_risk   → Get highest-risk conflicts (min_risk_score default 60)
    report      → Generate full conflicts report (output_format: summary/json/full)
    """
    
    if db is None:
        return {"error": "Database connection required"}
    
    if command == "scan":
        return _conflict_scan(db, playset_id, folder_filter, trace)
    
    elif command == "summary":
        return _conflict_summary(db, playset_id)
    
    elif command == "list":
        return _conflict_list(db, playset_id, risk_filter, domain_filter, 
                             status_filter, limit, offset)
    
    elif command == "detail":
        if not conflict_id:
            return {"error": "conflict_id parameter required for detail command"}
        return _conflict_detail(db, conflict_id)
    
    elif command == "resolve":
        if not conflict_id:
            return {"error": "conflict_id parameter required for resolve command"}
        if not decision_type:
            return {"error": "decision_type parameter required for resolve command"}
        return _conflict_resolve(db, trace, conflict_id, decision_type, 
                                 winner_candidate_id, notes)
    
    elif command == "content":
        if not unit_key:
            return {"error": "unit_key parameter required for content command"}
        return _conflict_content(db, playset_id, unit_key, source_filter)
    
    elif command == "high_risk":
        return _conflict_high_risk(db, trace, playset_id, domain_filter, 
                                   min_risk_score, limit)
    
    elif command == "report":
        return _conflict_report(db, trace, playset_id, domains_include, domains_exclude,
                               paths_filter, min_candidates, min_risk_score, output_format)
    
    return {"error": f"Unknown command: {command}"}


def _conflict_scan(db, playset_id: int, folder_filter: str | None, trace) -> dict:
    """Scan for unit conflicts."""
    try:
        from ck3raven.resolver.conflict_analyzer import scan_unit_conflicts
        
        result = scan_unit_conflicts(
            db.conn,
            playset_id,
            folder_filter=folder_filter,
        )
        
        if trace:
            trace.log("ck3lens.scan_unit_conflicts", 
                      {"folder_filter": folder_filter},
                      {"conflicts_found": result["conflicts_found"]})
        
        return result
        
    except Exception as e:
        return {"error": str(e)}


def _conflict_summary(db, playset_id: int) -> dict:
    """Get conflict summary."""
    try:
        from ck3raven.resolver.conflict_analyzer import get_conflict_summary
        return get_conflict_summary(db.conn, playset_id)
    except Exception as e:
        return {"error": str(e)}


def _conflict_list(
    db, 
    playset_id: int,
    risk_filter: str | None,
    domain_filter: str | None,
    status_filter: str | None,
    limit: int,
    offset: int,
) -> dict:
    """List conflicts with filters."""
    try:
        from ck3raven.resolver.conflict_analyzer import get_conflict_units
        
        conflicts = get_conflict_units(
            db.conn,
            playset_id,
            risk_filter=risk_filter,
            domain_filter=domain_filter,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
        )
        
        return {
            "playset_id": playset_id,
            "count": len(conflicts),
            "conflicts": conflicts,
        }
        
    except Exception as e:
        return {"error": str(e)}


def _conflict_detail(db, conflict_id: str) -> dict:
    """Get conflict detail."""
    try:
        from ck3raven.resolver.conflict_analyzer import get_conflict_unit_detail
        
        detail = get_conflict_unit_detail(db.conn, conflict_id)
        
        if not detail:
            return {"error": f"Conflict unit not found: {conflict_id}"}
        
        return detail
        
    except Exception as e:
        return {"error": str(e)}


def _conflict_resolve(
    db,
    trace,
    conflict_id: str,
    decision_type: str,
    winner_candidate_id: str | None,
    notes: str | None,
) -> dict:
    """Record resolution decision."""
    import hashlib
    from datetime import datetime
    
    # Validate conflict exists
    conflict = db.conn.execute("""
        SELECT unit_key, domain FROM conflict_units WHERE conflict_unit_id = ?
    """, (conflict_id,)).fetchone()
    
    if not conflict:
        return {"error": f"Conflict unit not found: {conflict_id}"}
    
    if decision_type == "winner" and not winner_candidate_id:
        return {"error": "winner_candidate_id required when decision_type is 'winner'"}
    
    # Validate winner candidate
    if winner_candidate_id:
        candidate = db.conn.execute("""
            SELECT source_name FROM conflict_candidates 
            WHERE conflict_unit_id = ? AND candidate_id = ?
        """, (conflict_id, winner_candidate_id)).fetchone()
        
        if not candidate:
            return {"error": f"Candidate not found: {winner_candidate_id}"}
    
    # Create resolution
    resolution_id = hashlib.sha256(
        f"{conflict_id}:{datetime.now().isoformat()}".encode()
    ).hexdigest()[:16]
    
    db.conn.execute("""
        INSERT INTO resolution_choices 
        (resolution_id, conflict_unit_id, decision_type, winner_candidate_id, notes, applied_at, applied_by)
        VALUES (?, ?, ?, ?, ?, datetime('now'), 'user')
    """, (resolution_id, conflict_id, decision_type, winner_candidate_id, notes))
    
    db.conn.execute("""
        UPDATE conflict_units 
        SET resolution_status = ?, resolution_id = ?
        WHERE conflict_unit_id = ?
    """, ('deferred' if decision_type == 'defer' else 'resolved', resolution_id, conflict_id))
    
    db.conn.commit()
    
    if trace:
        trace.log("ck3lens.resolve_conflict", 
                  {"conflict_unit_id": conflict_id, "decision_type": decision_type},
                  {"resolution_id": resolution_id})
    
    return {
        "success": True,
        "resolution_id": resolution_id,
        "unit_key": conflict[0],
        "domain": conflict[1],
        "decision_type": decision_type,
        "winner_candidate_id": winner_candidate_id,
    }


def _conflict_content(
    db,
    playset_id: int,
    unit_key: str,
    source_filter: str | None,
) -> dict:
    """Get all contributions for a unit_key."""
    
    query = """
        WITH playset_contribs AS (
            -- Vanilla contributions
            SELECT 
                cu.contrib_id, cu.content_version_id, cu.file_id,
                cu.domain, cu.unit_key, cu.relpath, cu.line_number,
                cu.merge_behavior, cu.summary, cu.node_hash,
                -1 as load_order_index, 'vanilla' as source_kind, 'vanilla' as source_name
            FROM contribution_units cu
            JOIN content_versions cv ON cu.content_version_id = cv.content_version_id
            JOIN vanilla_versions vv ON cv.vanilla_version_id = vv.vanilla_version_id
            JOIN playsets p ON p.vanilla_version_id = vv.vanilla_version_id
            WHERE p.playset_id = ? AND cv.kind = 'vanilla'
            
            UNION ALL
            
            -- Mod contributions
            SELECT 
                cu.contrib_id, cu.content_version_id, cu.file_id,
                cu.domain, cu.unit_key, cu.relpath, cu.line_number,
                cu.merge_behavior, cu.summary, cu.node_hash,
                pm.load_order_index, 'mod' as source_kind,
                COALESCE(mp.name, 'Unknown Mod') as source_name
            FROM contribution_units cu
            JOIN playset_mods pm ON cu.content_version_id = pm.content_version_id
            JOIN content_versions cv ON cu.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            WHERE pm.playset_id = ? AND pm.enabled = 1
        )
        SELECT 
            pc.contrib_id, pc.content_version_id, pc.file_id,
            pc.domain, pc.relpath, pc.line_number, pc.merge_behavior, pc.summary,
            pc.load_order_index, pc.source_kind, pc.source_name,
            fc.content_text
        FROM playset_contribs pc
        LEFT JOIN files f ON pc.file_id = f.file_id
        LEFT JOIN file_contents fc ON f.content_hash = fc.content_hash
        WHERE pc.unit_key = ?
    """
    params = [playset_id, playset_id, unit_key]
    
    if source_filter:
        query += " AND (pc.source_kind = ? OR LOWER(pc.source_name) LIKE LOWER(?))"
        params.extend([source_filter, f"%{source_filter}%"])
    
    query += " ORDER BY load_order_index"
    
    contributions = []
    for row in db.conn.execute(query, params).fetchall():
        contributions.append({
            "contrib_id": row[0],
            "content_version_id": row[1],
            "file_id": row[2],
            "domain": row[3],
            "relpath": row[4],
            "line_number": row[5],
            "merge_behavior": row[6],
            "summary": row[7],
            "load_order_index": row[8],
            "source_kind": row[9],
            "source_name": row[10],
            "content": row[11][:5000] if row[11] else None,
        })
    
    return {
        "unit_key": unit_key,
        "count": len(contributions),
        "contributions": contributions,
    }


def _conflict_high_risk(
    db,
    trace,
    playset_id: int,
    domain: str | None,
    min_risk_score: int,
    limit: int,
) -> dict:
    """Get highest-risk conflicts."""
    from ck3raven.resolver.report import ConflictsReportGenerator
    
    generator = ConflictsReportGenerator(db.conn)
    report = generator.generate(
        playset_id=playset_id,
        domains_include=[domain] if domain else None,
        min_candidates=2,
        min_risk_score=0,
    )
    
    all_conflicts = []
    
    for fc in report.file_level:
        if fc.risk and fc.risk.score >= min_risk_score:
            all_conflicts.append({
                "type": "file",
                "key": fc.vpath,
                "domain": fc.domain,
                "risk_score": fc.risk.score,
                "risk_bucket": fc.risk.bucket,
                "reasons": fc.risk.reasons,
                "candidate_count": len(fc.candidates),
                "winner": fc.winner_by_load_order.source_name if fc.winner_by_load_order else None,
            })
    
    for ic in report.id_level:
        if ic.risk and ic.risk.score >= min_risk_score:
            all_conflicts.append({
                "type": "id",
                "key": ic.unit_key,
                "domain": ic.domain,
                "container": ic.container_vpath,
                "risk_score": ic.risk.score,
                "risk_bucket": ic.risk.bucket,
                "reasons": ic.risk.reasons,
                "candidate_count": len(ic.candidates),
                "winner": ic.engine_effective_winner.candidate_id if ic.engine_effective_winner else None,
                "merge_semantics": ic.merge_semantics.expected if ic.merge_semantics else None,
            })
    
    all_conflicts.sort(key=lambda x: x["risk_score"], reverse=True)
    
    if trace:
        trace.log("ck3lens.get_high_risk_conflicts", {
            "domain": domain,
            "min_risk_score": min_risk_score,
        }, {"count": len(all_conflicts)})
    
    return {
        "count": len(all_conflicts),
        "conflicts": all_conflicts[:limit],
    }


def _conflict_report(
    db,
    trace,
    playset_id: int,
    domains_include: list[str] | None,
    domains_exclude: list[str] | None,
    paths_filter: str | None,
    min_candidates: int,
    min_risk_score: int,
    output_format: str,
) -> dict:
    """Generate conflicts report."""
    from ck3raven.resolver.report import ConflictsReportGenerator, report_summary_cli
    
    generator = ConflictsReportGenerator(db.conn)
    report = generator.generate(
        playset_id=playset_id,
        domains_include=domains_include,
        domains_exclude=domains_exclude,
        paths_filter=paths_filter,
        min_candidates=min_candidates,
        min_risk_score=min_risk_score,
    )
    
    if trace:
        trace.log("ck3lens.generate_conflicts_report", {
            "domains_include": domains_include,
            "paths_filter": paths_filter,
        }, {
            "file_conflicts": report.summary.file_conflicts if report.summary else 0,
            "id_conflicts": report.summary.id_conflicts if report.summary else 0,
        })
    
    result = {}
    
    if output_format in ("summary", "full"):
        result["summary_text"] = report_summary_cli(report)
    
    if output_format in ("json", "full"):
        result["report"] = report.to_dict()
    
    if report.summary:
        result["stats"] = {
            "file_conflicts": report.summary.file_conflicts,
            "id_conflicts": report.summary.id_conflicts,
            "high_risk": report.summary.high_risk_id_conflicts,
            "uncertain": report.summary.uncertain_conflicts,
        }
    
    return result


# ============================================================================
# ck3_file - Unified File Operations
# ============================================================================

FileCommand = Literal["get", "read", "write", "edit", "delete", "rename", "refresh", "list", "create_patch"]


def ck3_file_impl(
    command: FileCommand,
    # Path identification
    path: str | None = None,
    mod_name: str | None = None,
    rel_path: str | None = None,
    # For get (from DB)
    include_ast: bool = False,
    no_lens: bool = False,
    # For read/write
    content: str | None = None,
    start_line: int = 1,
    end_line: int | None = None,
    max_bytes: int = 200000,
    justification: str | None = None,
    # For edit
    old_content: str | None = None,
    new_content: str | None = None,
    # For rename
    new_path: str | None = None,
    # For write/edit
    validate_syntax: bool = True,
    # For policy-gated raw writes
    token_id: str | None = None,
    # For list
    path_prefix: str | None = None,
    pattern: str | None = None,
    # For create_patch (ck3lens mode only)
    source_path: str | None = None,
    patch_mode: str | None = None,  # "partial_patch" or "full_replace"
    # Dependencies (injected)
    session=None,
    db=None,
    trace=None,
    visibility=None,  # VisibilityScope for DB queries
    world=None,  # WorldAdapter for unified path resolution
) -> dict:
    """
    Unified file operations tool.
    
    Commands:
    
    command=get          → Get file content from database (path required)
    command=read         → Read file from filesystem (path or mod_name+rel_path)
    command=write        → Write file to live mod (mod_name, rel_path, content required)
    command=edit         → Search-replace in live mod file (mod_name, rel_path, old_content, new_content)
    command=delete       → Delete file from live mod (mod_name, rel_path required)
    command=rename       → Rename/move file in live mod (mod_name, rel_path, new_path required)
    command=refresh      → Re-sync file to database (mod_name, rel_path required)
    command=list         → List files in live mod (mod_name required, path_prefix/pattern optional)
    command=create_patch → Create override patch file (ck3lens only; mod_name, source_path, patch_mode required)
    
    ⚠️ create_patch is ck3lens mode only. Creates override patch files in live mods.
    
    The world parameter provides WorldAdapter for unified path resolution:
    - Resolves raw paths to canonical addresses
    - Validates visibility based on agent mode (FOUND/NOT_FOUND)
    - Does NOT provide permission hints (enforcement.py decides)
    """
    from pathlib import Path as P
    from ck3lens.agent_mode import get_agent_mode
    from ck3lens.policy.enforcement import (
        OperationType, Decision, EnforcementRequest, enforce_and_log
    )
    from ck3lens.work_contracts import get_active_contract
    from ck3lens.world_adapter import normalize_path_input
    
    mode = get_agent_mode()
    write_commands = {"write", "edit", "delete", "rename"}
    
    # ==========================================================================
    # STEP 1: CANONICAL PATH NORMALIZATION (FIRST)
    # Use normalize_path_input() for all path resolution.
    # This is the SINGLE resolver - no inline path building anywhere.
    # ==========================================================================
    
    resolution = None
    enforcement_target = None
    
    if command in write_commands and world is not None:
        # Use canonical path normalization utility
        resolution = normalize_path_input(world, path=path, mod_name=mod_name, rel_path=rel_path)
        
        if not resolution.found:
            # Path is outside this world's scope - structural error
            return {
                "success": False,
                "error": resolution.error_message or "Path not in world scope",
                "visibility": "NOT_FOUND",
                "guidance": "This path is outside your current lens/scope",
            }
        
        # Get enforcement target from resolution (the ONLY way to derive it)
        enforcement_target = resolution.get_enforcement_target()
    
    # ==========================================================================
    # STEP 2: CENTRALIZED ENFORCEMENT GATE (AFTER resolution)
    # Only reached if the path is visible. Now check policy.
    # ==========================================================================
    
    if command in write_commands and mode:
        # Map command to operation type
        op_type_map = {
            "write": OperationType.FILE_WRITE,
            "edit": OperationType.FILE_WRITE,  # Edit is a form of write
            "delete": OperationType.FILE_DELETE,
            "rename": OperationType.FILE_RENAME,
        }
        
        # Get contract for scope validation
        contract = get_active_contract()
        
        # Build enforcement request using enforcement_target (derived from resolution)
        request = EnforcementRequest(
            operation=op_type_map[command],
            mode=mode,
            tool_name="ck3_file",
            target_path=enforcement_target.canonical_address if enforcement_target else path,
            mod_name=enforcement_target.mod_name if enforcement_target else mod_name,
            rel_path=enforcement_target.rel_path if enforcement_target else rel_path,
            contract_id=contract.contract_id if contract else None,
            repo_domains=contract.canonical_domains if contract else [],
            token_id=token_id,
        )
        
        # Enforce policy
        result = enforce_and_log(request, trace)
        
        # Handle enforcement decision
        if result.decision == Decision.DENY:
            return {
                "success": False,
                "error": result.reason,
                "policy_decision": "DENY",
            }
        
        if result.decision == Decision.REQUIRE_CONTRACT:
            return {
                "success": False,
                "error": result.reason,
                "policy_decision": "REQUIRE_CONTRACT",
                "guidance": "Use ck3_contract(command='open', ...) to open a work contract",
            }
        
        if result.decision == Decision.REQUIRE_TOKEN:
            return {
                "success": False,
                "error": result.reason,
                "policy_decision": "REQUIRE_TOKEN",
                "required_token_type": result.required_token_type,
                "hint": f"Use ck3_token to request a {result.required_token_type} token",
            }
        
        if result.decision == Decision.REQUIRE_USER_APPROVAL:
            return {
                "success": False,
                "error": result.reason,
                "policy_decision": "REQUIRE_USER_APPROVAL",
                "required_token_type": result.required_token_type,
                "guidance": "This operation requires explicit user approval",
            }
        
        # Decision is ALLOW - continue to implementation
    
    # ==========================================================================
    # ROUTE TO IMPLEMENTATION
    # ==========================================================================
    
    if command == "get":
        return _file_get(path, include_ast, max_bytes, no_lens, db, trace, visibility)
    
    elif command == "read":
        if path:
            # Use WorldAdapter for visibility check if available
            return _file_read_raw(path, justification or "file read", start_line, end_line, trace, world)
        elif mod_name and rel_path:
            return _file_read_live(mod_name, rel_path, max_bytes, session, trace)
        else:
            return {"error": "Either 'path' or 'mod_name'+'rel_path' required for read"}
    
    elif command == "write":
        if path:
            # Raw filesystem write - policy-gated with WorldAdapter
            if content is None:
                return {"error": "content required for write"}
            return _file_write_raw(path, content, validate_syntax, token_id, trace, world)
        elif mod_name and rel_path:
            # Sandboxed mod write
            if content is None:
                return {"error": "content required for write"}
            return _file_write(mod_name, rel_path, content, validate_syntax, session, trace)
        else:
            return {"error": "Either 'path' or 'mod_name'+'rel_path' required for write"}
    
    elif command == "edit":
        if path:
            # Raw filesystem edit - policy-gated with WorldAdapter
            if old_content is None or new_content is None:
                return {"error": "old_content and new_content required for edit"}
            return _file_edit_raw(path, old_content, new_content, validate_syntax, token_id, trace, world)
        elif mod_name and rel_path:
            # Sandboxed mod edit
            if old_content is None or new_content is None:
                return {"error": "old_content and new_content required for edit"}
            return _file_edit(mod_name, rel_path, old_content, new_content, validate_syntax, session, trace)
        else:
            return {"error": "Either 'path' or 'mod_name'+'rel_path' required for edit"}
    
    elif command == "delete":
        if path and mode == "ck3raven-dev":
            # Raw path delete for ck3raven-dev mode
            return _file_delete_raw(path, token_id, trace, world)
        elif mod_name and rel_path:
            return _file_delete(mod_name, rel_path, session, trace)
        else:
            return {"error": "mod_name and rel_path required for delete (or 'path' in ck3raven-dev mode)"}
    
    elif command == "rename":
        if path and new_path and mode == "ck3raven-dev":
            # Raw path rename for ck3raven-dev mode
            return _file_rename_raw(path, new_path, token_id, trace, world)
        elif mod_name and rel_path and new_path:
            return _file_rename(mod_name, rel_path, new_path, session, trace)
        else:
            return {"error": "mod_name, rel_path, new_path required for rename (or 'path' + 'new_path' in ck3raven-dev mode)"}
    
    elif command == "refresh":
        if not all([mod_name, rel_path]):
            return {"error": "mod_name and rel_path required for refresh"}
        return _file_refresh(mod_name, rel_path, session, trace)
    
    elif command == "list":
        if path and mode == "ck3raven-dev":
            # Raw path list for ck3raven-dev mode
            return _file_list_raw(path, pattern, trace, world)
        elif mod_name:
            return _file_list(mod_name, path_prefix, pattern, session, trace)
        else:
            return {"error": "mod_name required for list (or 'path' in ck3raven-dev mode)"}
    
    elif command == "create_patch":
        # ck3lens mode only - creates override patch file
        return _file_create_patch(
            mod_name=mod_name,
            source_path=source_path,
            patch_mode=patch_mode,
            initial_content=content,
            validate_syntax=validate_syntax,
            session=session,
            trace=trace,
            mode=mode,
        )
    
    return {"error": f"Unknown command: {command}"}


def _file_get(path, include_ast, max_bytes, no_lens, db, trace, visibility):
    """Get file from database."""
    if not path:
        return {"error": "path required for get command"}
    
    result = db.get_file(relpath=path, include_ast=include_ast, visibility=visibility)
    
    if trace:
        trace.log("ck3lens.file.get", {"path": path, "include_ast": include_ast}, 
                  {"found": result is not None})
    
    if result:
        result["scope"] = visibility.purpose if visibility else "ALL CONTENT"
        return result
    return {"error": f"File not found: {path}"}


def _file_read_raw(path, justification, start_line, end_line, trace, world=None):
    """Read file from filesystem with WorldAdapter visibility enforcement."""
    from pathlib import Path as P
    from ck3lens.agent_mode import get_agent_mode
    
    file_path = P(path)
    
    # WorldAdapter visibility check (preferred)
    if world is not None:
        resolution = world.resolve(str(file_path))
        if not resolution.found:
            return {
                "success": False,
                "error": resolution.error_message or f"Path not visible in {world.mode} mode: {path}",
                "mode": world.mode,
                "hint": "This path is outside the visibility scope for the current agent mode",
            }
        # Use resolved absolute path
        file_path = resolution.absolute_path
    else:
        # Fallback: Lens enforcement for ck3lens mode (legacy path)
        mode = get_agent_mode()
        if mode == "ck3lens":
            # Import here to avoid circular import
            from ck3lens.playset_scope import PlaysetScope
            try:
                # Try to get scope from server module
                import sys
                server_module = sys.modules.get('__main__')
                if server_module and hasattr(server_module, '_get_playset_scope'):
                    playset_scope = server_module._get_playset_scope()
                else:
                    # Fallback: try to import from server
                    from tools.ck3lens_mcp.server import _get_playset_scope
                    playset_scope = _get_playset_scope()
                
                if playset_scope and not playset_scope.is_path_in_scope(file_path):
                    location_type, _ = playset_scope.get_path_location(file_path)
                    return {
                        "success": False,
                        "error": f"Path outside active playset scope: {path}",
                        "location_type": location_type,
                        "hint": "ck3lens mode restricts filesystem access to paths within the active playset",
                    }
            except Exception:
                pass  # If scope check fails, allow read (fail open for reads)
    
    if trace:
        trace.log("ck3lens.file.read", {"path": str(file_path), "justification": justification}, {})
    
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {path}"}
    
    if not file_path.is_file():
        return {"success": False, "error": f"Not a file: {path}"}
    
    try:
        content = file_path.read_text(encoding='utf-8', errors='replace')
        lines = content.splitlines(keepends=True)
        
        # Apply line range
        start_idx = max(0, start_line - 1)
        end_idx = end_line if end_line else len(lines)
        selected = lines[start_idx:end_idx]
        
        return {
            "success": True,
            "content": "".join(selected),
            "lines_read": len(selected),
            "total_lines": len(lines),
            "start_line": start_line,
            "end_line": end_idx,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _file_read_live(mod_name, rel_path, max_bytes, session, trace):
    """Read file from live mod."""
    from ck3lens.workspace import validate_relpath
    
    mod = session.get_mod(mod_name)
    if not mod:
        return {"error": f"Unknown mod_id: {mod_name}", "exists": False}
    
    valid, err = validate_relpath(rel_path)
    if not valid:
        return {"error": err, "exists": False}
    
    file_path = mod.path / rel_path
    
    if not file_path.exists():
        result = {"mod_id": mod_name, "relpath": rel_path, "exists": False, "content": None}
    else:
        try:
            content = file_path.read_text(encoding="utf-8-sig")
            if max_bytes and len(content.encode("utf-8")) > max_bytes:
                content = content[:max_bytes]
            result = {
                "mod_id": mod_name,
                "relpath": rel_path,
                "exists": True,
                "content": content,
                "size": len(content)
            }
        except Exception as e:
            result = {"error": str(e), "exists": True}
    
    if trace:
        trace.log("ck3lens.file.read_live", {"mod_name": mod_name, "rel_path": rel_path},
                  {"success": result.get("exists", False)})
    
    return result


def _file_write(mod_name, rel_path, content, validate_syntax, session, trace):
    """
    Write file to live mod.
    
    NOTE: Enforcement already happened in ck3_file dispatcher.
    This function only does the actual write + syntax validation.
    """
    from ck3lens.workspace import validate_relpath
    from ck3lens.validate import parse_content
    
    # Optional syntax validation
    if validate_syntax and rel_path.endswith(".txt"):
        parse_result = parse_content(content, rel_path)
        if not parse_result["success"]:
            if trace:
                trace.log("ck3lens.file.write", {"mod_name": mod_name, "rel_path": rel_path},
                          {"success": False, "reason": "syntax_error"})
            return {
                "success": False,
                "error": "Syntax validation failed",
                "parse_errors": parse_result["errors"]
            }
    
    # Inline write operation
    mod = session.get_mod(mod_name)
    if not mod:
        result = {"success": False, "error": f"Unknown mod_id: {mod_name}"}
    else:
        valid, err = validate_relpath(rel_path)
        if not valid:
            result = {"success": False, "error": err}
        else:
            file_path = mod.path / rel_path
            try:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")
                result = {
                    "success": True,
                    "mod_id": mod_name,
                    "relpath": rel_path,
                    "bytes_written": len(content.encode("utf-8")),
                    "full_path": str(file_path)
                }
            except Exception as e:
                result = {"success": False, "error": str(e)}
    
    # Auto-refresh in database
    if result.get("success"):
        db_refresh = _refresh_file_in_db_internal(mod_name, rel_path, content=content)
        result["db_refresh"] = db_refresh
    
    if trace:
        trace.log("ck3lens.file.write", {"mod_name": mod_name, "rel_path": rel_path},
                  {"success": result.get("success", False)})
    
    return result


def _file_write_raw(path, content, validate_syntax, token_id, trace, world=None):
    """
    Write file to raw filesystem path.
    
    NOTE: Enforcement already happened in ck3_file dispatcher.
    This function only does the actual write + syntax validation.
    """
    from pathlib import Path as P
    from ck3lens.validate import parse_content
    from ck3lens.agent_mode import get_agent_mode
    
    file_path = P(path).resolve()
    mode = get_agent_mode()
    
    # Validate syntax if requested
    if validate_syntax and path.endswith(".txt"):
        parse_result = parse_content(content, path)
        if not parse_result["success"]:
            return {
                "success": False,
                "error": "Syntax validation failed",
                "parse_errors": parse_result["errors"],
            }
    
    # Write the file
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        
        # Track core source change for WIP workaround detection
        if mode == "ck3raven-dev":
            from ck3lens.policy.wip_workspace import record_core_source_change
            from ck3lens.work_contracts import get_active_contract
            contract = get_active_contract()
            if contract:
                # Check if this is a core source file (not WIP)
                path_str = str(file_path).replace("\\", "/").lower()
                if ".wip/" not in path_str:
                    record_core_source_change(contract.contract_id)
        
        if trace:
            trace.log("ck3lens.file.write_raw", {"path": str(file_path), "mode": mode},
                      {"success": True})
        
        return {
            "success": True,
            "path": str(file_path),
            "bytes_written": len(content.encode("utf-8")),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _file_edit_raw(path, old_content, new_content, validate_syntax, token_id, trace, world=None):
    """
    Edit file at raw filesystem path.
    
    NOTE: Enforcement already happened in ck3_file dispatcher.
    This function only does the actual edit + syntax validation.
    """
    from pathlib import Path as P
    from ck3lens.validate import parse_content
    from ck3lens.agent_mode import get_agent_mode
    
    file_path = P(path).resolve()
    mode = get_agent_mode()
    
    # Read file, apply edit, validate, write
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {path}"}
    
    try:
        current_content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"success": False, "error": f"Cannot read file: {e}"}
    
    # Check old_content exists
    if old_content not in current_content:
        return {
            "success": False,
            "error": "old_content not found in file",
            "hint": "Ensure old_content matches exactly (including whitespace)",
        }
    
    # Apply edit
    updated_content = current_content.replace(old_content, new_content, 1)
    
    # Validate syntax if requested
    if validate_syntax and path.endswith(".txt"):
        parse_result = parse_content(updated_content, path)
        if not parse_result["success"]:
            return {
                "success": False,
                "error": "Syntax validation failed after edit",
                "parse_errors": parse_result["errors"],
            }
    
    # Write the file
    try:
        file_path.write_text(updated_content, encoding="utf-8")
        
        # Track core source change for WIP workaround detection
        if mode == "ck3raven-dev":
            from ck3lens.policy.wip_workspace import record_core_source_change
            from ck3lens.work_contracts import get_active_contract
            contract = get_active_contract()
            if contract:
                path_str = str(file_path).replace("\\", "/").lower()
                if ".wip/" not in path_str:
                    record_core_source_change(contract.contract_id)
        
        if trace:
            trace.log("ck3lens.file.edit_raw", {"path": str(file_path), "mode": mode},
                      {"success": True})
        
        return {
            "success": True,
            "path": str(file_path),
            "bytes_written": len(updated_content.encode("utf-8")),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _file_edit(mod_name, rel_path, old_content, new_content, validate_syntax, session, trace):
    """
    Edit file in live mod.
    
    NOTE: Enforcement already happened in ck3_file dispatcher.
    This function only does the actual edit + syntax validation.
    """
    from ck3lens.workspace import validate_relpath
    from ck3lens.validate import parse_content
    
    # Inline edit operation
    mod = session.get_mod(mod_name)
    if not mod:
        result = {"success": False, "error": f"Unknown mod_id: {mod_name}"}
    else:
        valid, err = validate_relpath(rel_path)
        if not valid:
            result = {"success": False, "error": err}
        else:
            file_path = mod.path / rel_path
            if not file_path.exists():
                result = {"success": False, "error": f"File not found: {rel_path}"}
            else:
                try:
                    current = file_path.read_text(encoding="utf-8-sig")
                    count = current.count(old_content)
                    if count == 0:
                        result = {"success": False, "error": "old_content not found in file", "file_length": len(current)}
                    else:
                        updated = current.replace(old_content, new_content)
                        file_path.write_text(updated, encoding="utf-8")
                        result = {"success": True, "mod_id": mod_name, "relpath": rel_path, "replacements": count}
                except Exception as e:
                    result = {"success": False, "error": str(e)}
    
    updated_content = None
    if result.get("success") and validate_syntax and rel_path.endswith(".txt"):
        # Re-read file after edit for validation
        try:
            updated_content = (mod.path / rel_path).read_text(encoding="utf-8-sig")
            parse_result = parse_content(updated_content, rel_path)
            result["syntax_valid"] = parse_result["success"]
            if not parse_result["success"]:
                result["syntax_warnings"] = parse_result["errors"]
        except Exception:
            pass
    
    if result.get("success"):
        if updated_content is None:
            try:
                updated_content = (mod.path / rel_path).read_text(encoding="utf-8-sig")
            except Exception:
                pass
        
        if updated_content:
            db_refresh = _refresh_file_in_db_internal(mod_name, rel_path, content=updated_content)
            result["db_refresh"] = db_refresh
    
    if trace:
        trace.log("ck3lens.file.edit", {"mod_name": mod_name, "rel_path": rel_path},
                  {"success": result.get("success", False)})
    
    return result


def _file_delete(mod_name, rel_path, session, trace):
    """
    Delete file from live mod.
    
    NOTE: Enforcement already happened in ck3_file dispatcher.
    This function only does the actual delete.
    """
    from ck3lens.workspace import validate_relpath
    
    mod = session.get_mod(mod_name)
    if not mod:
        result = {"success": False, "error": f"Unknown mod_id: {mod_name}"}
    else:
        valid, err = validate_relpath(rel_path)
        if not valid:
            result = {"success": False, "error": err}
        else:
            file_path = mod.path / rel_path
            if not file_path.exists():
                result = {"success": False, "error": f"File not found: {rel_path}"}
            else:
                try:
                    file_path.unlink()
                    result = {"success": True, "mod_id": mod_name, "relpath": rel_path}
                except Exception as e:
                    result = {"success": False, "error": str(e)}
    
    if result.get("success"):
        db_refresh = _refresh_file_in_db_internal(mod_name, rel_path, deleted=True)
        result["db_refresh"] = db_refresh
    
    if trace:
        trace.log("ck3lens.file.delete", {"mod_name": mod_name, "rel_path": rel_path},
                  {"success": result.get("success", False)})
    
    return result


def _file_rename(mod_name, old_path, new_path, session, trace):
    """Rename file in live mod."""
    from ck3lens.workspace import validate_relpath
    
    mod = session.get_mod(mod_name)
    if not mod:
        result = {"success": False, "error": f"Unknown mod_id: {mod_name}"}
    else:
        valid, err = validate_relpath(old_path)
        if not valid:
            result = {"success": False, "error": f"old_path: {err}"}
        else:
            valid, err = validate_relpath(new_path)
            if not valid:
                result = {"success": False, "error": f"new_path: {err}"}
            else:
                old_file = mod.path / old_path
                new_file = mod.path / new_path
                if not old_file.exists():
                    result = {"success": False, "error": f"File not found: {old_path}"}
                elif new_file.exists():
                    result = {"success": False, "error": f"Destination already exists: {new_path}"}
                else:
                    try:
                        new_file.parent.mkdir(parents=True, exist_ok=True)
                        old_file.rename(new_file)
                        result = {
                            "success": True,
                            "mod_id": mod_name,
                            "old_relpath": old_path,
                            "new_relpath": new_path,
                            "full_path": str(new_file)
                        }
                    except Exception as e:
                        result = {"success": False, "error": str(e)}
    
    if result.get("success"):
        _refresh_file_in_db_internal(mod_name, old_path, deleted=True)
        try:
            new_content = (mod.path / new_path).read_text(encoding="utf-8-sig")
            db_refresh = _refresh_file_in_db_internal(mod_name, new_path, content=new_content)
            result["db_refresh"] = db_refresh
        except Exception:
            pass
    
    if trace:
        trace.log("ck3lens.file.rename", {"mod_name": mod_name, "old_path": old_path, "new_path": new_path},
                  {"success": result.get("success", False)})
    
    return result


def _file_refresh(mod_name, rel_path, session, trace):
    """Refresh file in database."""
    from ck3lens.workspace import validate_relpath
    
    mod = session.get_mod(mod_name)
    if not mod:
        result = {"success": False, "error": f"Unknown mod_id: {mod_name}"}
    else:
        valid, err = validate_relpath(rel_path)
        if not valid:
            result = {"success": False, "error": err}
        else:
            file_path = mod.path / rel_path
            if not file_path.exists():
                result = _refresh_file_in_db_internal(mod_name, rel_path, deleted=True)
            else:
                try:
                    content = file_path.read_text(encoding="utf-8-sig")
                    result = _refresh_file_in_db_internal(mod_name, rel_path, content=content)
                except Exception as e:
                    result = {"success": False, "error": str(e)}
    
    if trace:
        trace.log("ck3lens.file.refresh", {"mod_name": mod_name, "rel_path": rel_path},
                  {"success": result.get("success", False)})
    
    return result


def _file_list(mod_name, path_prefix, pattern, session, trace):
    """List files in live mod."""
    from .world_router import get_world
    
    mod = session.get_mod(mod_name)
    if not mod:
        result = {"error": f"Unknown mod_id: {mod_name}"}
    else:
        target = mod.path / path_prefix if path_prefix else mod.path
        if not target.exists():
            result = {"files": [], "folder": path_prefix}
        else:
            # Get WorldAdapter for canonical path resolution
            # Note: WorldAdapter should be pre-initialized; we use mods from session
            adapter = get_world(
                local_mods_folder=session.local_mods_folder,
                mods=session.mods
            )
            
            files = []
            glob_pattern = pattern or "*.txt"
            for f in target.rglob(glob_pattern):
                if f.is_file():
                    try:
                        # Use WorldAdapter.resolve() to get canonical address
                        resolution = adapter.resolve(str(f)) if adapter else None
                        if resolution and resolution.found:
                            rel = resolution.address.relative_path
                        else:
                            # Fallback: just use filename
                            rel = str(f.name)
                        stat = f.stat()
                        files.append({
                            "relpath": rel,
                            "size": stat.st_size,
                            "modified": stat.st_mtime
                        })
                    except Exception:
                        pass
            result = {
                "mod_id": mod_name,
                "folder": path_prefix,
                "pattern": glob_pattern,
                "files": sorted(files, key=lambda x: x["relpath"])
            }
    
    if trace:
        trace.log("ck3lens.file.list", {"mod_name": mod_name, "path_prefix": path_prefix},
                  {"files_count": len(result.get("files", []))})
    
    return result


def _file_delete_raw(path, token_id, trace, world=None):
    """
    Delete file at raw filesystem path.
    
    MODE: ck3raven-dev only (enforced by caller).
    Requires token for destructive operation.
    """
    from pathlib import Path as P
    from ck3lens.policy.tokens import validate_token
    
    file_path = P(path).resolve()
    
    # Token required for file deletion
    if not token_id:
        return {"success": False, "error": "token_id required for file deletion", "required_token_type": "FS_DELETE_CODE"}
    
    # Validate token
    token_result = validate_token(token_id, capability="FS_DELETE_CODE", path=str(file_path))
    if not token_result.get("valid"):
        return {"success": False, "error": token_result.get("reason", "Invalid token")}
    
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {path}"}
    
    try:
        file_path.unlink()
        if trace:
            trace.log("ck3lens.file.delete_raw", {"path": str(file_path)}, {"success": True})
        return {"success": True, "path": str(file_path)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _file_rename_raw(old_path, new_path, token_id, trace, world=None):
    """
    Rename/move file at raw filesystem path.
    
    MODE: ck3raven-dev only (enforced by caller).
    """
    from pathlib import Path as P
    
    old_file = P(old_path).resolve()
    new_file = P(new_path).resolve()
    
    if not old_file.exists():
        return {"success": False, "error": f"File not found: {old_path}"}
    
    if new_file.exists():
        return {"success": False, "error": f"Destination already exists: {new_path}"}
    
    try:
        new_file.parent.mkdir(parents=True, exist_ok=True)
        old_file.rename(new_file)
        if trace:
            trace.log("ck3lens.file.rename_raw", {"old_path": str(old_file), "new_path": str(new_file)}, {"success": True})
        return {"success": True, "old_path": str(old_file), "new_path": str(new_file)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _file_list_raw(path, pattern, trace, world=None):
    """
    List files at raw filesystem path.
    
    MODE: ck3raven-dev only (enforced by caller).
    """
    from pathlib import Path as P
    
    target = P(path).resolve()
    
    if not target.exists():
        return {"files": [], "path": path}
    
    if not target.is_dir():
        # Single file
        stat = target.stat()
        return {"files": [{"path": str(target), "size": stat.st_size, "modified": stat.st_mtime}], "path": path}
    
    files = []
    glob_pattern = pattern or "*"
    for f in target.rglob(glob_pattern):
        if f.is_file():
            try:
                stat = f.stat()
                files.append({
                    "path": str(f),
                    "relpath": str(f.relative_to(target)),
                    "size": stat.st_size,
                    "modified": stat.st_mtime
                })
            except Exception:
                pass
    
    if trace:
        trace.log("ck3lens.file.list_raw", {"path": path, "pattern": pattern}, {"files_count": len(files)})
    
    return {"path": path, "pattern": glob_pattern, "files": sorted(files, key=lambda x: x.get("relpath", ""))}


def _file_create_patch(mod_name, source_path, patch_mode, initial_content, validate_syntax, session, trace, mode):
    """
    Create an override patch file in a live mod.
    
    ⚠️ MODE: ck3lens only. Not available in ck3raven-dev mode.
    
    Modes:
    - partial_patch: Creates zzz_[mod]_[original_name].txt (for adding/modifying specific units)
    - full_replace: Creates [original_name].txt (full replacement, last-wins)
    
    NOTE: This function computes paths and delegates to _file_write.
    Enforcement happens via the normal _file_write path.
    """
    from pathlib import Path as P
    from datetime import datetime
    
    # Mode check: ck3lens only
    if mode == "ck3raven-dev":
        return {
            "success": False,
            "error": "create_patch command is only available in ck3lens mode",
            "guidance": "This tool creates override patches in CK3 mods, which is not relevant to ck3raven development",
        }
    
    # Validate required parameters
    if not mod_name:
        return {"success": False, "error": "mod_name required for create_patch"}
    if not source_path:
        return {"success": False, "error": "source_path required for create_patch (the file being overridden)"}
    if not patch_mode:
        return {"success": False, "error": "patch_mode required: 'partial_patch' or 'full_replace'"}
    if patch_mode not in ("partial_patch", "full_replace"):
        return {"success": False, "error": f"Invalid patch_mode: {patch_mode}. Use 'partial_patch' or 'full_replace'"}
    
    # Parse and validate source path
    source = P(source_path)
    if source.is_absolute() or ".." in source.parts:
        return {"success": False, "error": "source_path must be relative without '..'"}
    
    # Compute output filename based on patch mode
    if patch_mode == "partial_patch":
        # Prefix with zzz_[mod]_ to load LAST (wins for OVERRIDE types)
        mod_prefix = mod_name.lower().replace(" ", "_")
        new_name = f"zzz_{mod_prefix}_{source.name}"
    else:  # full_replace
        # Same name (will override due to load order)
        new_name = source.name
    
    # Build target relative path (same directory structure)
    target_rel_path = str(source.parent / new_name)
    
    # Generate default content if not provided
    if initial_content is None:
        initial_content = f"""# Override patch for: {source_path}
# Created: {datetime.now().strftime("%Y-%m-%d %H:%M")}
# Patch mode: {patch_mode}
# Target mod: {mod_name}
# 
# For 'partial_patch' mode: Add only the specific units you want to override/add.
# For 'full_replace' mode: This file completely replaces the original.

"""
    
    # Delegate to existing _file_write (handles folder creation, syntax validation)
    write_result = _file_write(mod_name, target_rel_path, initial_content, validate_syntax, session, trace)
    
    if write_result.get("success"):
        # Enhance result with patch-specific info
        write_result["patch_info"] = {
            "source_path": source_path,
            "patch_mode": patch_mode,
            "created_path": target_rel_path,
        }
        write_result["message"] = f"Created {patch_mode} patch: {target_rel_path}"
        
        if trace:
            trace.log("ck3lens.file.create_patch", {
                "mod_name": mod_name,
                "source_path": source_path,
                "patch_mode": patch_mode,
            }, {"success": True, "created_path": target_rel_path})
    
    return write_result


def _refresh_file_in_db_internal(mod_name, rel_path, content=None, deleted=False):
    """Internal helper to refresh file in database."""
    try:
        import sys
        from pathlib import Path as P
        project_root = P(__file__).parent.parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        
        from builder.incremental import refresh_single_file, mark_file_deleted
        from ck3raven.db.schema import get_connection, DEFAULT_DB_PATH
        
        conn = get_connection(DEFAULT_DB_PATH)
        
        if deleted:
            return mark_file_deleted(conn, mod_name, rel_path)
        else:
            return refresh_single_file(conn, mod_name, rel_path, content=content)
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# ck3_folder - Unified Folder Operations
# ============================================================================

FolderCommand = Literal["list", "contents", "top_level", "mod_folders"]


def ck3_folder_impl(
    command: FolderCommand = "list",
    # For list/contents
    path: str | None = None,
    justification: str | None = None,
    # For mod_folders
    content_version_id: int | None = None,
    # For contents
    folder_pattern: str | None = None,
    text_search: str | None = None,
    symbol_search: str | None = None,
    mod_filter: list[str] | None = None,
    file_type_filter: list[str] | None = None,
    # Dependencies
    db=None,
    playset_id: int | None = None,
    trace=None,
    world=None,  # WorldAdapter for visibility enforcement
) -> dict:
    """
    Unified folder operations tool.
    
    Commands:
    
    command=list        → List directory contents from filesystem (path required)
    command=contents    → Get folder contents from database (path required)
    command=top_level   → Get top-level folders in active playset
    command=mod_folders → Get folders in specific mod (content_version_id required)
    
    The world parameter provides WorldAdapter for visibility enforcement on
    filesystem operations (command=list).
    """
    
    if command == "list":
        if not path:
            return {"error": "path required for list command"}
        return _folder_list_raw(path, justification or "folder listing", trace, world)
    
    elif command == "contents":
        if not path:
            return {"error": "path required for contents command"}
        return _folder_contents(path, content_version_id, folder_pattern, text_search,
                                symbol_search, mod_filter, file_type_filter, db, playset_id, trace)
    
    elif command == "top_level":
        return _folder_top_level(db, playset_id, trace)
    
    elif command == "mod_folders":
        if not content_version_id:
            return {"error": "content_version_id required for mod_folders command"}
        return _folder_mod_folders(content_version_id, db, trace)
    
    return {"error": f"Unknown command: {command}"}


def _folder_list_raw(path, justification, trace, world=None):
    """List directory from filesystem with WorldAdapter visibility enforcement."""
    from pathlib import Path as P
    
    dir_path = P(path).resolve()
    
    # WorldAdapter visibility check (preferred path)
    if world is not None:
        resolution = world.resolve(str(dir_path))
        if not resolution.found:
            return {
                "success": False,
                "error": resolution.error_message or f"Path not visible in {world.mode} mode: {path}",
                "mode": world.mode,
                "hint": "This path is outside the visibility scope for the current agent mode",
            }
        # Use resolved absolute path
        dir_path = resolution.absolute_path
    
    if trace:
        trace.log("ck3lens.folder.list", {"path": str(dir_path), "justification": justification}, {})
    
    if not dir_path.exists():
        return {"success": False, "error": f"Directory not found: {path}"}
    
    if not dir_path.is_dir():
        return {"success": False, "error": f"Not a directory: {path}"}
    
    try:
        entries = []
        for item in sorted(dir_path.iterdir()):
            entries.append({
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
        
        return {
            "success": True,
            "path": str(dir_path),
            "entries": entries,
            "count": len(entries),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _folder_contents(path, content_version_id, folder_pattern, text_search,
                     symbol_search, mod_filter, file_type_filter, db, playset_id, trace):
    """Get folder contents from database."""
    # Normalize path
    path = path.replace("\\", "/").strip("/")
    
    # Build query
    conditions = ["pm.playset_id = ?", "pm.enabled = 1", "f.deleted = 0"]
    params = [playset_id]
    
    if content_version_id:
        conditions.append("f.content_version_id = ?")
        params.append(content_version_id)
    
    if path:
        conditions.append("f.relpath LIKE ?")
        params.append(f"{path}/%")
    
    query = f"""
        SELECT DISTINCT
            CASE 
                WHEN INSTR(SUBSTR(f.relpath, LENGTH(?) + 2), '/') > 0
                THEN SUBSTR(SUBSTR(f.relpath, LENGTH(?) + 2), 1, 
                            INSTR(SUBSTR(f.relpath, LENGTH(?) + 2), '/') - 1)
                ELSE SUBSTR(f.relpath, LENGTH(?) + 2)
            END as item_name,
            CASE 
                WHEN INSTR(SUBSTR(f.relpath, LENGTH(?) + 2), '/') > 0 THEN 1
                ELSE 0
            END as is_folder,
            COUNT(*) as file_count
        FROM files f
        JOIN playset_mods pm ON f.content_version_id = pm.content_version_id
        WHERE {" AND ".join(conditions)}
        GROUP BY item_name, is_folder
        ORDER BY is_folder DESC, item_name
    """
    
    prefix_params = [path] * 5
    
    try:
        rows = db.conn.execute(query, prefix_params + params).fetchall()
        
        entries = []
        for row in rows:
            if row['item_name']:
                entries.append({
                    "name": row['item_name'],
                    "type": "folder" if row['is_folder'] else "file",
                    "file_count": row['file_count'],
                })
        
        if trace:
            trace.log("ck3lens.folder.contents", {"path": path}, {"entries": len(entries)})
        
        return {
            "path": path,
            "entries": entries,
            "count": len(entries),
        }
    except Exception as e:
        return {"error": str(e)}


def _folder_top_level(db, playset_id, trace):
    """Get top-level folders."""
    rows = db.conn.execute("""
        SELECT 
            SUBSTR(f.relpath, 1, INSTR(f.relpath || '/', '/') - 1) as folder,
            COUNT(*) as file_count
        FROM files f
        JOIN playset_mods pm ON f.content_version_id = pm.content_version_id
        WHERE pm.playset_id = ? AND pm.enabled = 1 AND f.deleted = 0
        GROUP BY folder
        ORDER BY folder
    """, (playset_id,)).fetchall()
    
    folders = [{"name": row['folder'], "fileCount": row['file_count']} 
               for row in rows if row['folder']]
    
    if trace:
        trace.log("ck3lens.folder.top_level", {}, {"folders": len(folders)})
    
    return {"folders": folders}


def _folder_mod_folders(content_version_id, db, trace):
    """Get folders in specific mod."""
    rows = db.conn.execute("""
        SELECT 
            SUBSTR(f.relpath, 1, INSTR(f.relpath || '/', '/') - 1) as folder,
            COUNT(*) as file_count
        FROM files f
        WHERE f.content_version_id = ? AND f.deleted = 0
        GROUP BY folder
        ORDER BY folder
    """, (content_version_id,)).fetchall()
    
    folders = [{"name": row['folder'], "fileCount": row['file_count']} 
               for row in rows if row['folder']]
    
    if trace:
        trace.log("ck3lens.folder.mod_folders", {"cv_id": content_version_id}, {"folders": len(folders)})
    
    return {"folders": folders}


# ============================================================================
# ck3_playset - Unified Playset Operations
# ============================================================================

PlaysetCommand = Literal["get", "list", "switch", "mods", "add_mod", "remove_mod", "reorder", "create", "import"]


def ck3_playset_impl(
    command: PlaysetCommand = "get",
    # For switch/add_mod/remove_mod/reorder
    playset_name: str | None = None,
    mod_name: str | None = None,
    # For reorder
    new_position: int | None = None,
    # For create
    name: str | None = None,
    description: str | None = None,
    vanilla_version_id: int | None = None,
    mod_ids: list[int] | None = None,
    # For import
    launcher_playset_name: str | None = None,
    # Dependencies
    db=None,
    playset_id: int | None = None,
    trace=None,
) -> dict:
    """
    Unified playset operations tool.
    
    Commands:
    
    command=get        → Get active playset info
    command=list       → List all playsets
    command=switch     → Switch to different playset (playset_name required)
    command=mods       → Get mods in active playset
    command=add_mod    → Add mod to playset (mod_name required)
    command=remove_mod → Remove mod from playset (mod_name required)
    command=reorder    → Change mod load order (mod_name, new_position required)
    command=create     → Create new playset (name required)
    command=import     → Import playset from CK3 launcher
    """
    
    if command == "get":
        return _playset_get(db, playset_id, trace)
    
    elif command == "list":
        return _playset_list(db, trace)
    
    elif command == "switch":
        if not playset_name:
            return {"error": "playset_name required for switch command"}
        return _playset_switch(playset_name, db, trace)
    
    elif command == "mods":
        return _playset_mods(db, playset_id, trace)
    
    elif command == "add_mod":
        if not mod_name:
            return {"error": "mod_name required for add_mod command"}
        return _playset_add_mod(mod_name, db, playset_id, trace)
    
    elif command == "remove_mod":
        if not mod_name:
            return {"error": "mod_name required for remove_mod command"}
        return _playset_remove_mod(mod_name, db, playset_id, trace)
    
    elif command == "reorder":
        if not mod_name or new_position is None:
            return {"error": "mod_name and new_position required for reorder command"}
        return _playset_reorder(mod_name, new_position, db, playset_id, trace)
    
    elif command == "create":
        if not name:
            return {"error": "name required for create command"}
        return _playset_create(name, description, vanilla_version_id, mod_ids, db, trace)
    
    elif command == "import":
        return _playset_import(launcher_playset_name, db, trace)
    
    return {"error": f"Unknown command: {command}"}


def _playset_get(db, playset_id, trace):
    """Get active playset info."""
    row = db.conn.execute("""
        SELECT p.*, 
               (SELECT COUNT(*) FROM playset_mods pm WHERE pm.playset_id = p.playset_id AND pm.enabled = 1) as mod_count
        FROM playsets p
        WHERE p.playset_id = ?
    """, (playset_id,)).fetchone()
    
    if not row:
        return {"error": "No active playset"}
    
    result = {
        "playset_id": row['playset_id'],
        "name": row['name'],
        "description": row['description'],
        "mod_count": row['mod_count'],
        "is_active": bool(row['is_active']),
        "created_at": row['created_at'],
        "updated_at": row['updated_at'],
    }
    
    if trace:
        trace.log("ck3lens.playset.get", {}, {"playset_id": playset_id})
    
    return result


def _playset_list(db, trace):
    """List all playsets."""
    rows = db.conn.execute("""
        SELECT p.*, 
               (SELECT COUNT(*) FROM playset_mods pm WHERE pm.playset_id = p.playset_id AND pm.enabled = 1) as mod_count
        FROM playsets p
        ORDER BY p.is_active DESC, p.name
    """).fetchall()
    
    playsets = [{
        "playset_id": row['playset_id'],
        "name": row['name'],
        "description": row['description'],
        "mod_count": row['mod_count'],
        "is_active": bool(row['is_active']),
    } for row in rows]
    
    if trace:
        trace.log("ck3lens.playset.list", {}, {"count": len(playsets)})
    
    return {"playsets": playsets}


def _playset_switch(playset_name, db, trace):
    """Switch to different playset."""
    row = db.conn.execute(
        "SELECT playset_id FROM playsets WHERE name = ?", (playset_name,)
    ).fetchone()
    
    if not row:
        return {"error": f"Playset not found: {playset_name}"}
    
    new_id = row['playset_id']
    
    # Deactivate all, activate target
    db.conn.execute("UPDATE playsets SET is_active = 0")
    db.conn.execute("UPDATE playsets SET is_active = 1 WHERE playset_id = ?", (new_id,))
    db.conn.commit()
    
    if trace:
        trace.log("ck3lens.playset.switch", {"name": playset_name}, {"new_id": new_id})
    
    return {"success": True, "playset_id": new_id, "name": playset_name}


def _playset_mods(db, playset_id, trace):
    """Get mods in playset."""
    rows = db.conn.execute("""
        SELECT cv.name, cv.content_version_id, pm.load_order_index, pm.enabled,
               cv.kind, cv.source_path,
               (SELECT COUNT(*) FROM files f WHERE f.content_version_id = cv.content_version_id AND f.deleted = 0) as file_count
        FROM playset_mods pm
        JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
        WHERE pm.playset_id = ?
        ORDER BY pm.load_order_index
    """, (playset_id,)).fetchall()
    
    mods = [{
        "name": row['name'],
        "content_version_id": row['content_version_id'],
        "load_order": row['load_order_index'],
        "enabled": bool(row['enabled']),
        "kind": row['kind'],
        "file_count": row['file_count'],
        "source_path": row['source_path'],
    } for row in rows]
    
    if trace:
        trace.log("ck3lens.playset.mods", {}, {"count": len(mods)})
    
    return {"mods": mods, "playset_id": playset_id}


def _playset_add_mod(mod_name, db, playset_id, trace):
    """Add mod to playset."""
    # Find mod
    row = db.conn.execute(
        "SELECT content_version_id FROM content_versions WHERE name = ?", (mod_name,)
    ).fetchone()
    
    if not row:
        return {"error": f"Mod not found in database: {mod_name}"}
    
    cv_id = row['content_version_id']
    
    # Check if already in playset
    existing = db.conn.execute("""
        SELECT 1 FROM playset_mods WHERE playset_id = ? AND content_version_id = ?
    """, (playset_id, cv_id)).fetchone()
    
    if existing:
        return {"error": f"Mod already in playset: {mod_name}"}
    
    # Get next load order
    max_order = db.conn.execute("""
        SELECT COALESCE(MAX(load_order_index), -1) + 1 as next_order
        FROM playset_mods WHERE playset_id = ?
    """, (playset_id,)).fetchone()['next_order']
    
    # Insert
    db.conn.execute("""
        INSERT INTO playset_mods (playset_id, content_version_id, load_order_index, enabled)
        VALUES (?, ?, ?, 1)
    """, (playset_id, cv_id, max_order))
    db.conn.commit()
    
    if trace:
        trace.log("ck3lens.playset.add_mod", {"mod": mod_name}, {"success": True})
    
    return {"success": True, "mod_name": mod_name, "load_order": max_order}


def _playset_remove_mod(mod_name, db, playset_id, trace):
    """Remove mod from playset."""
    row = db.conn.execute(
        "SELECT content_version_id FROM content_versions WHERE name = ?", (mod_name,)
    ).fetchone()
    
    if not row:
        return {"error": f"Mod not found: {mod_name}"}
    
    cv_id = row['content_version_id']
    
    result = db.conn.execute("""
        DELETE FROM playset_mods WHERE playset_id = ? AND content_version_id = ?
    """, (playset_id, cv_id))
    db.conn.commit()
    
    if result.rowcount == 0:
        return {"error": f"Mod not in playset: {mod_name}"}
    
    if trace:
        trace.log("ck3lens.playset.remove_mod", {"mod": mod_name}, {"success": True})
    
    return {"success": True, "mod_name": mod_name}


def _playset_reorder(mod_name, new_position, db, playset_id, trace):
    """Reorder mod in playset."""
    row = db.conn.execute("""
        SELECT pm.load_order_index, cv.content_version_id
        FROM playset_mods pm
        JOIN content_versions cv ON pm.content_version_id = cv.content_version_id
        WHERE pm.playset_id = ? AND cv.name = ?
    """, (playset_id, mod_name)).fetchone()
    
    if not row:
        return {"error": f"Mod not in playset: {mod_name}"}
    
    old_position = row['load_order_index']
    cv_id = row['content_version_id']
    
    if old_position == new_position:
        return {"success": True, "mod_name": mod_name, "position": new_position, "message": "No change needed"}
    
    # Shift other mods
    if new_position < old_position:
        db.conn.execute("""
            UPDATE playset_mods
            SET load_order_index = load_order_index + 1
            WHERE playset_id = ? AND load_order_index >= ? AND load_order_index < ?
        """, (playset_id, new_position, old_position))
    else:
        db.conn.execute("""
            UPDATE playset_mods
            SET load_order_index = load_order_index - 1
            WHERE playset_id = ? AND load_order_index > ? AND load_order_index <= ?
        """, (playset_id, old_position, new_position))
    
    # Set new position
    db.conn.execute("""
        UPDATE playset_mods SET load_order_index = ? 
        WHERE playset_id = ? AND content_version_id = ?
    """, (new_position, playset_id, cv_id))
    db.conn.commit()
    
    if trace:
        trace.log("ck3lens.playset.reorder", {"mod": mod_name, "old": old_position, "new": new_position},
                  {"success": True})
    
    return {"success": True, "mod_name": mod_name, "old_position": old_position, "new_position": new_position}


def _playset_create(name, description, vanilla_version_id, mod_ids, db, trace):
    """Create new playset."""
    from datetime import datetime
    
    # Check name doesn't exist
    existing = db.conn.execute(
        "SELECT 1 FROM playsets WHERE name = ?", (name,)
    ).fetchone()
    
    if existing:
        return {"error": f"Playset already exists: {name}"}
    
    now = datetime.now().isoformat()
    
    cursor = db.conn.execute("""
        INSERT INTO playsets (name, description, vanilla_version_id, is_active, created_at, updated_at)
        VALUES (?, ?, ?, 0, ?, ?)
    """, (name, description or "", vanilla_version_id or 1, now, now))
    
    new_id = cursor.lastrowid
    
    # Add mods if provided
    if mod_ids:
        for i, cv_id in enumerate(mod_ids):
            db.conn.execute("""
                INSERT INTO playset_mods (playset_id, content_version_id, load_order_index, enabled)
                VALUES (?, ?, ?, 1)
            """, (new_id, cv_id, i))
    
    db.conn.commit()
    
    if trace:
        trace.log("ck3lens.playset.create", {"name": name}, {"new_id": new_id})
    
    return {"success": True, "playset_id": new_id, "name": name}


def _playset_import(launcher_playset_name, db, trace):
    """Import playset from CK3 launcher."""
    # This would need access to launcher database - placeholder
    return {"error": "Import from launcher not yet implemented in unified tool"}


# ============================================================================
# ck3_git - Unified Git Operations
# ============================================================================

GitCommand = Literal["status", "diff", "add", "commit", "push", "pull", "log"]


def _run_git_in_path(repo_path, *args: str, timeout: int = 60) -> tuple[bool, str, str]:
    """Run git command in specified directory.
    
    Uses non-interactive mode to prevent hanging on credential prompts.
    Increased timeout for push/pull operations.
    """
    import subprocess
    import os
    from pathlib import Path as P
    
    # Environment variables to prevent git from hanging
    exec_env = os.environ.copy()
    exec_env["GIT_TERMINAL_PROMPT"] = "0"  # Disable credential prompts
    exec_env["GIT_PAGER"] = "cat"  # Disable pager for git commands
    exec_env["PAGER"] = "cat"  # Disable pager generally
    exec_env["GCM_INTERACTIVE"] = "never"  # Disable Git Credential Manager GUI
    exec_env["GIT_ASKPASS"] = ""  # Disable askpass
    exec_env["SSH_ASKPASS"] = ""  # Disable SSH askpass
    exec_env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"  # SSH non-interactive
    
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=P(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=exec_env,
            stdin=subprocess.DEVNULL,  # Prevent any stdin reads
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, "", "Git not found in PATH"
    except Exception as e:
        return False, "", str(e)


def _git_ops_for_path(command, repo_path, file_path, files, all_files, message, limit):
    """Git operations for any git repo path (used in ck3raven-dev mode)."""
    from pathlib import Path as P
    
    repo_path = P(repo_path)
    repo_name = repo_path.name
    
    if not (repo_path / ".git").exists():
        return {"error": f"{repo_path} is not a git repository"}
    
    if command == "status":
        # Get branch
        ok, branch, err = _run_git_in_path(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        if not ok:
            return {"error": f"Failed to get branch: {err}"}
        branch = branch.strip()
        
        # Get status
        ok, status, err = _run_git_in_path(repo_path, "status", "--porcelain")
        if not ok:
            return {"error": f"Failed to get status: {err}"}
        
        staged = []
        unstaged = []
        untracked = []
        
        for line in status.strip().split("\n"):
            if not line:
                continue
            index = line[0]
            worktree = line[1]
            filename = line[3:]
            
            if index == "?":
                untracked.append(filename)
            elif index != " ":
                staged.append({"status": index, "file": filename})
            if worktree not in (" ", "?"):
                unstaged.append({"status": worktree, "file": filename})
        
        return {
            "repo": repo_name,
            "path": str(repo_path),
            "branch": branch,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "clean": len(staged) == 0 and len(unstaged) == 0 and len(untracked) == 0
        }
    
    elif command == "diff":
        args = ["diff"]
        if file_path == "staged":
            args.append("--cached")
        elif file_path:
            args.extend(["--", file_path])
        
        ok, diff, err = _run_git_in_path(repo_path, *args)
        if not ok:
            return {"error": err}
        
        return {
            "repo": repo_name,
            "staged": file_path == "staged",
            "diff": diff
        }
    
    elif command == "add":
        if all_files:
            args = ["add", "-A"]
        elif files:
            args = ["add"] + files
        else:
            return {"error": "Must specify files or all_files=True"}
        
        ok, out, err = _run_git_in_path(repo_path, *args)
        if not ok:
            return {"success": False, "error": err}
        
        return {"success": True, "repo": repo_name}
    
    elif command == "commit":
        if not message:
            return {"error": "message required for commit"}
        
        ok, out, err = _run_git_in_path(repo_path, "commit", "-m", message)
        if not ok:
            if "nothing to commit" in err or "nothing to commit" in out:
                return {"success": False, "error": "Nothing to commit"}
            return {"success": False, "error": err}
        
        # Get commit hash
        ok2, hash_out, _ = _run_git_in_path(repo_path, "rev-parse", "HEAD")
        commit_hash = hash_out.strip() if ok2 else "unknown"
        
        return {
            "success": True,
            "repo": repo_name,
            "commit_hash": commit_hash,
            "message": message
        }
    
    elif command == "push":
        # Network operations need longer timeout
        ok, out, err = _run_git_in_path(repo_path, "push", "origin", timeout=120)
        if not ok:
            return {"success": False, "error": err}
        
        return {
            "success": True,
            "repo": repo_name,
            "output": out + err
        }
    
    elif command == "pull":
        # Network operations need longer timeout
        ok, out, err = _run_git_in_path(repo_path, "pull", "origin", timeout=120)
        if not ok:
            return {"success": False, "error": err}
        
        return {
            "success": True,
            "repo": repo_name,
            "output": out + err
        }
    
    elif command == "log":
        args = ["log", f"-{limit}", "--pretty=format:%H|%an|%ai|%s"]
        if file_path and file_path != "staged":
            args.append("--")
            args.append(file_path)
        
        ok, out, err = _run_git_in_path(repo_path, *args)
        if not ok:
            return {"error": err}
        
        commits = []
        for line in out.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "message": parts[3]
                })
        
        return {
            "repo": repo_name,
            "commits": commits
        }
    
    return {"error": f"Unknown command: {command}"}


def ck3_git_impl(
    command: GitCommand,
    mod_name: str | None = None,  # Optional - auto-detected in ck3raven-dev mode
    # For diff
    file_path: str | None = None,
    # For add
    files: list[str] | None = None,
    all_files: bool = False,
    # For commit
    message: str | None = None,
    # For log
    limit: int = 10,
    # Dependencies
    session=None,
    trace=None,
) -> dict:
    """
    Unified git operations.
    
    Mode-aware behavior:
    - ck3raven-dev mode: Operates on ck3raven repo by default (mod_name ignored)
    - ck3lens mode: Operates on live mods (mod_name required)
    
    Commands:
    
    command=status → Get git status
    command=diff   → Get git diff (file_path optional)
    command=add    → Stage files (files or all_files required)
    command=commit → Commit staged changes (message required)
    command=push   → Push to remote
    command=pull   → Pull from remote
    command=log    → Get commit log (limit optional)
    """
    from ck3lens import git_ops
    from ck3lens.agent_mode import get_agent_mode
    from ck3lens.policy.enforcement import (
        OperationType, Decision, EnforcementRequest, enforce_and_log
    )
    from ck3lens.work_contracts import get_active_contract
    from pathlib import Path as P
    
    # Validate session
    if not session:
        return {"error": "No session available - call ck3_init_session first"}
    
    # Mode detection
    mode = get_agent_mode()
    ck3raven_root = P(__file__).parent.parent.parent.parent
    
    # ==========================================================================
    # CENTRALIZED ENFORCEMENT GATE (Phase 2)
    # Git write operations go through enforce_and_log FIRST
    # ==========================================================================
    
    write_commands = {"add", "commit", "push", "pull"}
    
    if command in write_commands and mode:
        # Map command to operation type
        op_type_map = {
            "add": OperationType.GIT_LOCAL_PACKAGE,
            "commit": OperationType.GIT_LOCAL_PACKAGE,
            "push": OperationType.GIT_PUBLISH,
            "pull": OperationType.GIT_LOCAL_WORKFLOW,
        }
        
        # Helper to get non-interactive git environment
        def get_git_env():
            import os
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["GIT_PAGER"] = "cat"
            env["PAGER"] = "cat"
            env["GCM_INTERACTIVE"] = "never"
            env["GIT_ASKPASS"] = ""
            env["SSH_ASKPASS"] = ""
            env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
            return env
        
        # Get current branch for push enforcement
        branch_name = None
        if command == "push":
            try:
                import subprocess
                if mode == "ck3raven-dev":
                    result_obj = subprocess.run(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        cwd=str(ck3raven_root),
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=get_git_env(),
                        stdin=subprocess.DEVNULL,
                    )
                    if result_obj.returncode == 0:
                        branch_name = result_obj.stdout.strip()
            except Exception:
                pass  # Branch detection failed, enforcement will handle
        
        # Get staged files for scope validation (for push)
        staged_files = []
        if command == "push":
            try:
                import subprocess
                if mode == "ck3raven-dev":
                    result_obj = subprocess.run(
                        ["git", "diff", "--name-only", "--cached"],
                        cwd=str(ck3raven_root),
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=get_git_env(),
                        stdin=subprocess.DEVNULL,
                    )
                    if result_obj.returncode == 0:
                        staged_files = [f for f in result_obj.stdout.strip().split("\n") if f]
            except Exception:
                pass
        
        # Determine target for mod operations
        target_mod = mod_name if mode == "ck3lens" else None
        
        # Get contract
        contract = get_active_contract()
        
        # Build enforcement request
        request = EnforcementRequest(
            operation=op_type_map[command],
            mode=mode,
            tool_name="ck3_git",
            mod_name=target_mod,
            contract_id=contract.contract_id if contract else None,
            repo_domains=contract.canonical_domains if contract else [],
            branch_name=branch_name,
            staged_files=staged_files,
            is_force_push=False,  # Force push not supported via this tool
        )
        
        # Enforce policy
        result = enforce_and_log(request, trace)
        
        # Handle enforcement decision
        if result.decision == Decision.DENY:
            return {
                "success": False,
                "error": result.reason,
                "policy_decision": "DENY",
            }
        
        if result.decision == Decision.REQUIRE_CONTRACT:
            return {
                "success": False,
                "error": result.reason,
                "policy_decision": "REQUIRE_CONTRACT",
                "guidance": "Use ck3_contract(command='open', ...) to open a work contract",
            }
        
        if result.decision == Decision.REQUIRE_TOKEN:
            return {
                "success": False,
                "error": result.reason,
                "policy_decision": "REQUIRE_TOKEN",
                "required_token_type": result.required_token_type,
                "hint": f"Use ck3_token to request a {result.required_token_type} token",
            }
        
        if result.decision == Decision.REQUIRE_USER_APPROVAL:
            return {
                "success": False,
                "error": result.reason,
                "policy_decision": "REQUIRE_USER_APPROVAL",
                "required_token_type": result.required_token_type,
                "guidance": "This operation requires explicit user approval",
            }
        
        # Decision is ALLOW - continue to implementation
        # Include safe_push_autogrant info if applicable
        if result.safe_push_autogrant and trace:
            trace.log("ck3lens.git.safe_push_autogrant", {
                "branch": branch_name,
                "staged_files_count": len(staged_files),
            }, {})
    
    # ==========================================================================
    # ROUTE TO IMPLEMENTATION
    # ==========================================================================
    
    # ck3raven-dev mode: always operate on repo, ignore mod_name
    if mode == "ck3raven-dev":
        if mod_name:
            # Log that we're ignoring mod_name but don't error
            pass  # Could trace.log a warning here
        
        result = _git_ops_for_path(command, ck3raven_root, file_path, files, all_files, message, limit)
        if trace:
            trace.log(f"ck3lens.git.{command}", {"target": "ck3raven"},
                      {"success": result.get("success", "error" not in result)})
        return result

    # ck3lens mode: require mod_name for live mod operations
    if not mod_name:
        return {
            "error": "mod_name required for git operations in ck3lens mode",
            "hint": "Specify which mod to operate on"
        }

    # Get mod from session (mods[] from active playset)
    mod = session.get_mod(mod_name)
    if not mod:
        return {
            "error": f"Mod not found in active playset: {mod_name}",
            "hint": "Use mod folder name, not display name"
        }

    # git_ops functions expect (session, mod_id) - pass correctly
    if command == "status":
        result = git_ops.git_status(session, mod_name)
    
    elif command == "diff":
        result = git_ops.git_diff(session, mod_name, staged=(file_path == "staged"))
    
    elif command == "add":
        if all_files:
            result = git_ops.git_add(session, mod_name, all_files=True)
        elif files:
            result = git_ops.git_add(session, mod_name, files=files)
        else:
            return {"error": "Either 'files' or 'all_files=true' required for add"}
    
    elif command == "commit":
        if not message:
            return {"error": "message required for commit"}
        result = git_ops.git_commit(session, mod_name, message)
    
    elif command == "push":
        result = git_ops.git_push(session, mod_name)
    
    elif command == "pull":
        result = git_ops.git_pull(session, mod_name)
    
    elif command == "log":
        result = git_ops.git_log(session, mod_name, limit=limit, file_path=file_path)
    
    else:
        return {"error": f"Unknown command: {command}"}
    
    if trace:
        trace.log(f"ck3lens.git.{command}", {"mod": mod_name}, 
                  {"success": result.get("success", "error" not in result)})
    
    return result


# ============================================================================
# ck3_validate - Unified Validation Operations
# ============================================================================

ValidateTarget = Literal["syntax", "python", "references", "bundle", "policy"]


def ck3_validate_impl(
    target: ValidateTarget,
    # For syntax/python
    content: str | None = None,
    file_path: str | None = None,
    # For references
    symbol_name: str | None = None,
    symbol_type: str | None = None,
    # For bundle
    artifact_bundle: dict | None = None,
    # For policy
    mode: str | None = None,
    trace_path: str | None = None,
    # Dependencies
    db=None,
    trace=None,
) -> dict:
    """
    Unified validation tool.
    
    Targets:
    
    target=syntax     → Validate CK3 script syntax (content required)
    target=python     → Check Python syntax (content or file_path required)
    target=references → Validate symbol references (symbol_name required)
    target=bundle     → Validate artifact bundle (artifact_bundle required)
    target=policy     → Validate against policy rules (mode required)
    """
    
    if target == "syntax":
        if not content:
            return {"error": "content required for syntax validation"}
        return _validate_syntax(content, file_path or "inline.txt", trace)
    
    elif target == "python":
        return _validate_python(content, file_path, trace)
    
    elif target == "references":
        if not symbol_name:
            return {"error": "symbol_name required for references validation"}
        return _validate_references(symbol_name, symbol_type, db, trace)
    
    elif target == "bundle":
        if not artifact_bundle:
            return {"error": "artifact_bundle required for bundle validation"}
        return _validate_bundle(artifact_bundle, trace)
    
    elif target == "policy":
        if not mode:
            return {"error": "mode required for policy validation"}
        return _validate_policy(mode, trace_path, trace)
    
    return {"error": f"Unknown target: {target}"}


def _validate_syntax(content, filename, trace):
    """Validate CK3 script syntax."""
    from ck3lens.validate import parse_content
    
    result = parse_content(content, filename)
    
    if trace:
        trace.log("ck3lens.validate.syntax", {"filename": filename},
                  {"valid": result.get("success", False)})
    
    return {
        "valid": result.get("success", False),
        "errors": result.get("errors", []),
        "node_count": result.get("node_count", 0),
    }


def _validate_python(content, file_path, trace):
    """Validate Python syntax.
    
    NOTE: For .txt files (CK3 script files), this automatically routes to
    CK3 syntax validation using our Paradox script parser instead of Python's ast.
    This prevents false positives when validating CK3 mod files.
    """
    import ast
    from pathlib import Path as P
    
    # Determine filename for extension check
    filename = file_path or "<string>"
    
    # CK3 script files (.txt) should use CK3 syntax validation, not Python
    if filename.lower().endswith('.txt'):
        # Route to CK3 syntax validation
        if content:
            source = content
        elif file_path:
            path = P(file_path)
            if not path.exists():
                return {"valid": False, "error": f"File not found: {file_path}"}
            source = path.read_text(encoding='utf-8')
        else:
            return {"error": "Either content or file_path required"}
        
        # Use CK3 parser for .txt files
        return _validate_syntax(source, filename, trace)
    
    # Python files - use ast.parse
    if content:
        source = content
    elif file_path:
        path = P(file_path)
        if not path.exists():
            return {"valid": False, "error": f"File not found: {file_path}"}
        source = path.read_text(encoding='utf-8')
    else:
        return {"error": "Either content or file_path required"}
    
    try:
        ast.parse(source, filename)
        
        if trace:
            trace.log("ck3lens.validate.python", {"filename": filename}, {"valid": True})
        
        return {"valid": True}
    except SyntaxError as e:
        if trace:
            trace.log("ck3lens.validate.python", {"filename": filename}, {"valid": False})
        
        return {
            "valid": False,
            "error": str(e),
            "line": e.lineno,
            "column": e.offset,
        }


def _validate_references(symbol_name, symbol_type, db, trace):
    """Validate symbol references."""
    # Look up symbol
    conditions = ["s.name = ?"]
    params = [symbol_name]
    
    if symbol_type:
        conditions.append("s.symbol_type = ?")
        params.append(symbol_type)
    
    rows = db.conn.execute(f"""
        SELECT s.*, f.relpath
        FROM symbols s
        JOIN files f ON s.file_id = f.file_id
        WHERE {" AND ".join(conditions)}
    """, params).fetchall()
    
    if trace:
        trace.log("ck3lens.validate.references", {"symbol": symbol_name},
                  {"found": len(rows) > 0})
    
    if not rows:
        return {"valid": False, "error": f"Symbol not found: {symbol_name}"}
    
    return {
        "valid": True,
        "symbol_name": symbol_name,
        "definitions": [{
            "file": row['relpath'],
            "line": row['line_number'],
            "type": row['symbol_type'],
        } for row in rows],
    }


def _validate_bundle(artifact_bundle, trace):
    """Validate artifact bundle."""
    from ck3lens.validate import validate_artifact_bundle
    from ck3lens.contracts import ArtifactBundle
    
    try:
        bundle = ArtifactBundle.from_dict(artifact_bundle)
        result = validate_artifact_bundle(bundle)
        
        if trace:
            trace.log("ck3lens.validate.bundle", {}, {"valid": not result.get("errors")})
        
        return result
    except Exception as e:
        return {"valid": False, "error": str(e)}


def _validate_policy(mode, trace_path, trace_obj):
    """Validate against policy rules."""
    from ck3lens.policy import validate_for_mode
    from pathlib import Path as P
    
    if trace_path:
        path = P(trace_path)
        if not path.exists():
            return {"error": f"Trace file not found: {trace_path}"}
        trace_data = path.read_text()
    else:
        trace_data = ""
    
    result = validate_for_mode(mode, trace_data)
    
    if trace_obj:
        trace_obj.log("ck3lens.validate.policy", {"mode": mode},
                      {"valid": result.get("valid", False)})
    
    return result


# =============================================================================
# ck3_vscode - VS Code IPC operations
# =============================================================================

VSCodeCommand = Literal[
    "ping",
    "diagnostics",
    "all_diagnostics",
    "errors_summary",
    "validate_file",
    "open_files",
    "active_file",
    "status"
]


def ck3_vscode_impl(
    command: VSCodeCommand = "status",
    # For diagnostics/validate_file
    path: str | None = None,
    # For all_diagnostics
    severity: str | None = None,
    source: str | None = None,
    limit: int = 50,
    # Dependencies
    trace=None,
) -> dict:
    """
    Unified VS Code IPC operations tool.
    
    Connects to VS Code extension's diagnostics server to access IDE APIs.
    Requires VS Code to be running with CK3 Lens extension active.
    
    Commands:
    
    command=ping           → Test connection to VS Code
    command=diagnostics    → Get diagnostics for a file (path required)
    command=all_diagnostics → Get diagnostics for all files
    command=errors_summary → Get workspace error summary
    command=validate_file  → Trigger validation for a file (path required)
    command=open_files     → List currently open files
    command=active_file    → Get active file info with diagnostics
    command=status         → Check IPC server status
    
    Args:
        command: Operation to perform
        path: File path (for diagnostics/validate_file)
        severity: Filter by severity ('error', 'warning', 'info', 'hint')
        source: Filter by source (e.g., 'Pylance', 'CK3 Lens')
        limit: Max files to return for all_diagnostics
    
    Returns:
        Dict with results based on command
    """
    from ck3lens.ipc_client import VSCodeIPCClient, VSCodeIPCError, is_vscode_available
    
    if command == "status":
        available = is_vscode_available()
        return {
            "available": available,
            "message": "VS Code IPC server is running" if available else "VS Code IPC server not available"
        }
    
    try:
        with VSCodeIPCClient() as client:
            if command == "ping":
                result = client.ping()
                if trace:
                    trace.log("ck3lens.vscode.ping", {}, {"ok": True})
                return result
            
            elif command == "diagnostics":
                if not path:
                    return {"error": "path required for diagnostics command"}
                result = client.get_diagnostics(path)
                if trace:
                    trace.log("ck3lens.vscode.diagnostics", {"path": path},
                              {"count": len(result.get("diagnostics", []))})
                return result
            
            elif command == "all_diagnostics":
                result = client.get_all_diagnostics(
                    severity=severity,
                    source=source,
                    limit=limit
                )
                if trace:
                    trace.log("ck3lens.vscode.all_diagnostics",
                              {"severity": severity, "source": source},
                              {"files": result.get("fileCount", 0)})
                return result
            
            elif command == "errors_summary":
                result = client.get_workspace_errors()
                if trace:
                    trace.log("ck3lens.vscode.errors_summary", {},
                              {"errors": result.get("summary", {}).get("errors", 0)})
                return result
            
            elif command == "validate_file":
                if not path:
                    return {"error": "path required for validate_file command"}
                result = client.validate_file(path)
                if trace:
                    trace.log("ck3lens.vscode.validate_file", {"path": path},
                              {"count": len(result.get("diagnostics", []))})
                return result
            
            elif command == "open_files":
                result = client.get_open_files()
                if trace:
                    trace.log("ck3lens.vscode.open_files", {},
                              {"count": result.get("count", 0)})
                return result
            
            elif command == "active_file":
                result = client.get_active_file()
                if trace:
                    trace.log("ck3lens.vscode.active_file", {},
                              {"active": result.get("active", False)})
                return result
            
            return {"error": f"Unknown command: {command}"}
            
    except VSCodeIPCError as e:
        return {
            "error": True,
            "message": str(e),
            "suggestion": "Ensure VS Code is running with CK3 Lens extension active",
            "help": "The VS Code IPC server starts automatically when CK3 Lens extension activates"
        }