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
