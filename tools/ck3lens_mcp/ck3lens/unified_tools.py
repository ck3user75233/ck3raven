"""
Unified MCP Tool Implementations

Consolidates multiple granular tools into parameterized commands to reduce
tool count while maintaining full functionality.

Consolidated tools:
- ck3_logs: 11 log/error/crash tools -> 1 unified tool
- ck3_conflicts: 7 conflict tools -> 1 unified tool
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from .db.golden_join import GOLDEN_JOIN
# Canonical path constants - use these instead of computing paths from __file__
from .paths import ROOT_REPO

# Canonical Reply System (Phase C migration)
from ck3raven.core.reply import Reply, TraceInfo, MetaInfo


# ============================================================================
# Helpers
# ============================================================================

def _create_reply_builder(trace_info: TraceInfo, tool: str, layer: str = "MCP", contract_id: str | None = None):
    """Create a ReplyBuilder for use in helper functions."""
    from ck3raven.core.reply_registry import get_message
    
    class _ReplyBuilder:
        """Minimal ReplyBuilder for internal use in unified_tools.py"""
        def __init__(self):
            self.trace_info = trace_info
            self.tool = tool
            self.layer = layer
            self.contract_id = contract_id
        
        def _meta(self, layer_override: str | None = None) -> MetaInfo:
            return MetaInfo(
                layer=layer_override or self.layer,  # type: ignore
                tool=self.tool,
                contract_id=self.contract_id,
            )
        
        def success(self, code: str, data: dict, message: str | None = None, layer: str | None = None) -> Reply:
            return Reply.success(
                code=code,
                message=message or get_message(code, **data),
                data=data,
                trace=self.trace_info,

                meta=self._meta(layer),
            )
        
        def info(self, code: str, data: dict, message: str | None = None, layer: str | None = None) -> Reply:
            return Reply.info(
                code=code,
                message=message or get_message(code, **data),
                data=data,
                trace=self.trace_info,
                meta=self._meta(layer),
            )
        
        def denied(self, code: str, data: dict, message: str | None = None, layer: str | None = None) -> Reply:
            return Reply.denied(
                code=code,
                message=message or get_message(code, **data),
                data=data,
                trace=self.trace_info,
                meta=self._meta(layer),
            )
        
        def error(self, code: str, data: dict, message: str | None = None, layer: str | None = None) -> Reply:
            return Reply.error(
                code=code,
                message=message or get_message(code, **data),
                data=data,
                trace=self.trace_info,
                meta=self._meta(layer),
            )
    
    return _ReplyBuilder()


def _compute_mod_prefix(mod_name: str) -> str:
    """
    Generate a short prefix from mod name using first letter of each word.
    
    Used for creating override patch files with zzz_ prefix.
    
    Examples:
        "Mini Super Compatch" → "msc"
        "Adoption Options" → "ao"
        "MSC Religion Expanded" → "mre"
        "Unofficial Patch" → "up"
        "More Game Rules" → "mgr"
        "EPE" → "epe" (single word/acronym preserved)
    
    Returns:
        Lowercase prefix string (e.g., "msc", "ao", "up")
    """
    words = mod_name.split()
    if not words:
        return "mod"
    prefix = "".join(word[0].lower() for word in words if word)
    return prefix or "mod"


# ============================================================================
# ck3_logs - Unified Logging Tool
# ============================================================================

LogSource = Literal["error", "game", "debug", "crash"]
LogCommand = Literal["summary", "list", "search", "detail", "categories", "cascades", "read", "raw"]


def ck3_logs_impl(
    source: LogSource = "error",
    command: LogCommand = "summary",
    # Filters
    priority: int | None = None,
    category: str | None = None,
    mod_filter: str | None = None,
    mod_filter_exact: bool = False,
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
    # FR-1: Custom log source path
    source_path: str | None = None,
    # FR-2: Export results to WIP
    export_to: str | None = None,
) -> dict:
    """
    Unified logging tool implementation.
    
    Source + Command combinations:
    
    error + summary     -> Error log summary with counts by priority/category/mod
    error + list        -> Filtered list of errors with fix hints  
    error + search      -> Search errors by message/path
    error + cascades    -> Get cascading error patterns (root causes)
    
    game + summary      -> Game log summary with category breakdown
    game + list         -> Filtered list of game log errors
    game + search       -> Search game log by message/path
    game + categories   -> Category breakdown with descriptions
    
    debug + summary     -> System info, DLCs, mod list from debug.log
    
    crash + summary     -> Recent crash reports list
    crash + detail      -> Full crash report (requires crash_id)
    
    Any source + read   -> Raw log content (tail/head with optional search)
    
    FR-1: source_path -> Custom log file path (for analyzing backups)
    FR-2: export_to -> Export results to WIP as markdown
    """
    
    # FR-1: Resolve source_path if provided
    resolved_source_path: Path | None = None
    if source_path:
        resolved_source_path = _resolve_log_source_path(source_path)
        if resolved_source_path is None:
            return {"error": f"Cannot resolve source_path: {source_path}"}
    
    # Route based on source and command
    if command == "raw":
        result = _read_log_full(source, resolved_source_path)
    elif command == "read":
        result = _read_log_raw(source, lines, from_end, query, resolved_source_path)
    elif source == "error":
        result = _error_log_handler(command, priority, category, mod_filter, 
                                   mod_filter_exact, exclude_cascade_children, query, limit,
                                   resolved_source_path)
    elif source == "game":
        result = _game_log_handler(command, category, query, limit, resolved_source_path)
    elif source == "debug":
        result = _debug_log_handler(command, resolved_source_path)
    elif source == "crash":
        result = _crash_handler(command, crash_id, limit)
    else:
        return {"error": f"Unknown source: {source}"}
    
    # FR-2: Export results if requested
    if export_to and "error" not in result:
        export_result = _export_logs_result(result, source, command, export_to)
        if "error" in export_result:
            result["export_error"] = export_result["error"]
        else:
            result["export_path"] = export_result["export_path"]
            result["export_success"] = True
    
    return result


def _resolve_log_source_path(source_path: str) -> Path | None:
    """
    Resolve a source_path to an absolute Path.
    
    Supports:
    - Absolute paths: "C:/path/to/error.log"
    - WIP paths: "wip:/log-backups/error.log"
    - Home-relative: "~/backups/error.log"
    
    Returns None if path doesn't exist or can't be resolved.
    """
    # Handle WIP paths
    if source_path.startswith("wip:"):
        wip_base = Path.home() / ".ck3raven" / "wip"
        rel_path = source_path[4:].lstrip("/")
        resolved = wip_base / rel_path
    # Handle home-relative
    elif source_path.startswith("~"):
        resolved = Path(source_path).expanduser()
    # Absolute or relative path
    else:
        resolved = Path(source_path)
        if not resolved.is_absolute():
            # Try relative to WIP
            wip_base = Path.home() / ".ck3raven" / "wip"
            resolved = wip_base / source_path
    
    if resolved.exists():
        return resolved
    return None


def _export_logs_result(
    result: dict,
    source: str,
    command: str,
    export_to: str,
) -> dict:
    """
    Export logs result to markdown file in WIP.
    
    Args:
        result: The result dict from log analysis
        source: Log source (error, game, debug, crash)
        command: Command that was run
        export_to: WIP path for output (supports {timestamp} substitution)
    
    Returns:
        Dict with export_path on success, error on failure
    """
    from datetime import datetime
    
    # Resolve export path
    wip_base = Path.home() / ".ck3raven" / "wip"
    
    # Handle wip: prefix
    if export_to.startswith("wip:"):
        rel_path = export_to[4:].lstrip("/")
    else:
        rel_path = export_to
    
    # Substitute {timestamp}
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    rel_path = rel_path.replace("{timestamp}", timestamp)
    
    export_path = wip_base / rel_path
    
    # Ensure parent directories exist
    export_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Generate markdown content
    md_content = _result_to_markdown(result, source, command)
    
    try:
        export_path.write_text(md_content, encoding='utf-8')
        return {"export_path": str(export_path)}
    except Exception as e:
        return {"error": f"Failed to write export: {e}"}


def _result_to_markdown(result: dict, source: str, command: str) -> str:
    """Convert log result to formatted markdown."""
    from datetime import datetime
    
    lines = [
        f"# CK3 Log Analysis: {source} / {command}",
        f"",
        f"**Generated:** {datetime.now().isoformat()}",
        f"**Source:** {source}",
        f"**Command:** {command}",
        f"",
        "---",
        "",
    ]
    
    if command == "summary":
        lines.append("## Summary")
        lines.append("")
        for key, value in result.items():
            if isinstance(value, dict):
                lines.append(f"### {key}")
                for k, v in value.items():
                    lines.append(f"- **{k}:** {v}")
            else:
                lines.append(f"- **{key}:** {value}")
        lines.append("")
    
    elif command == "cascades":
        lines.append(f"## Cascade Analysis")
        lines.append("")
        lines.append(f"**Total Cascades:** {result.get('cascade_count', 0)}")
        lines.append(f"**Total Errors:** {result.get('total_errors', 0)}")
        lines.append("")
        if result.get("recommendation"):
            lines.append(f"> {result['recommendation']}")
            lines.append("")
        
        for cascade in result.get("cascades", []):
            lines.append(f"### Cascade: {cascade.get('root_pattern', 'Unknown')[:60]}")
            lines.append(f"- **Root Errors:** {cascade.get('root_count', 0)}")
            lines.append(f"- **Child Errors:** {cascade.get('child_count', 0)}")
            if cascade.get("example_root"):
                lines.append(f"- **Example:** `{cascade['example_root'][:100]}`")
            lines.append("")
    
    elif command == "list":
        errors = result.get("errors", [])
        lines.append(f"## Error List ({len(errors)} items)")
        lines.append("")
        for i, error in enumerate(errors[:100], 1):  # Limit to 100 for markdown
            msg = error.get("message", "")[:80]
            lines.append(f"{i}. **{error.get('category', 'unknown')}** - {msg}")
            if error.get("file"):
                lines.append(f"   - File: `{error['file']}`")
            if error.get("fix_hint"):
                lines.append(f"   - Fix: {error['fix_hint']}")
        lines.append("")
    
    else:
        # Generic fallback - dump as code block
        import json
        lines.append("## Raw Result")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(result, indent=2, default=str))
        lines.append("```")
    
    return "\n".join(lines)


def _error_log_handler(
    command: str,
    priority: int | None,
    category: str | None,
    mod_filter: str | None,
    mod_filter_exact: bool,
    exclude_cascade_children: bool,
    query: str | None,
    limit: int,
    source_path: Path | None = None,
) -> dict:
    """Handle error.log commands."""
    from ck3raven.analyzers.error_parser import CK3ErrorParser, ERROR_CATEGORIES
    
    parser = CK3ErrorParser()
    
    try:
        parser.parse_log(log_path=source_path)
        parser.detect_cascading_errors()
    except FileNotFoundError:
        if source_path:
            return {
                "error": f"Log file not found: {source_path}",
                "hint": "Check the source_path parameter",
            }
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
            mod_filter_exact=mod_filter_exact,
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
    source_path: Path | None = None,
) -> dict:
    """Handle game.log commands."""
    from ck3raven.analyzers.log_parser import CK3LogParser, LogType, GAME_LOG_CATEGORIES
    
    parser = CK3LogParser()
    
    try:
        parser.parse_game_log(log_path=source_path)
    except FileNotFoundError:
        if source_path:
            return {"error": f"Log file not found: {source_path}"}
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


def _debug_log_handler(command: str, source_path: Path | None = None) -> dict:
    """Handle debug.log commands."""
    from ck3raven.analyzers.log_parser import CK3LogParser
    
    parser = CK3LogParser()
    
    try:
        parser.parse_debug_log(extract_system_info=True, log_path=source_path)
    except FileNotFoundError:
        if source_path:
            return {"error": f"Log file not found: {source_path}"}
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
    source_path: Path | None = None,
) -> dict:
    """Read raw log content.
    
    MEMORY-SAFE: 
    - For files >100KB with search: refuses (search requires full scan)
    - For files >100KB without search: uses efficient tail-reading
    - Always caps output to 200 lines max
    """
    MAX_SIZE_FOR_SEARCH = 100 * 1024  # 100KB limit when search is used
    MAX_LINES = 200  # Never return more than 200 lines
    
    # If custom source_path provided, use it directly
    if source_path:
        log_path = source_path
    else:
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
            "error": f"Log file not found: {log_path}",
            "hint": "Check the path or make sure CK3 has been run",
        }
    
    try:
        file_size = log_path.stat().st_size
        
        # If search is requested on a large file, refuse
        if search and file_size > MAX_SIZE_FOR_SEARCH:
            size_mb = file_size / 1024 / 1024
            return {
                "error": f"File too large ({size_mb:.1f}MB) for search. Search requires loading entire file.",
                "file_path": str(log_path),
                "file_size": file_size,
                "suggestion": (
                    "For large log files, use structured access instead:\n"
                    "  • ck3_logs(command='summary') - parsed error summary\n"
                    "  • ck3_logs(command='list', mod_filter='...') - filter by mod\n"
                    "  • ck3_logs(command='read', lines=100) - get last N lines without search"
                ),
            }
        
        # Cap lines
        max_lines = min(lines, MAX_LINES)
        
        # For small files (<100KB), just read the whole thing
        if file_size <= MAX_SIZE_FOR_SEARCH:
            content_lines = log_path.read_text(encoding='utf-8', errors='replace').splitlines()
            total_lines = len(content_lines)
        else:
            # Large file, no search - read efficiently from end
            # Read enough to get ~200 lines (assuming ~500 bytes/line avg)
            chunk_size = min(150 * 1024, file_size)  # ~150KB should be plenty for 200 lines
            with open(log_path, 'rb') as f:
                if from_end:
                    f.seek(max(0, file_size - chunk_size))
                chunk = f.read(chunk_size).decode('utf-8', errors='replace')
            content_lines = chunk.splitlines()
            # First line may be partial if we seeked mid-file
            if file_size > chunk_size and content_lines and from_end:
                content_lines = content_lines[1:]  # Drop partial first line
            total_lines = None  # Unknown without full scan
        
        # Apply search filter if provided (only for small files per check above)
        if search:
            search_lower = search.lower()
            content_lines = [l for l in content_lines if search_lower in l.lower()]
        
        # Select lines
        if from_end:
            selected = content_lines[-max_lines:] if len(content_lines) > max_lines else content_lines
        else:
            selected = content_lines[:max_lines]
        
        return {
            "log_source": source,
            "file_path": str(log_path),
            "file_size_bytes": file_size,
            "total_lines": total_lines,  # May be None for large files
            "returned_lines": len(selected),
            "lines_requested": lines,
            "lines_capped_at": max_lines if lines > max_lines else None,
            "from_end": from_end,
            "search": search,
            "content": "\n".join(selected),
        }
    except Exception as e:
        return {"error": str(e)}


def _read_log_full(source: str, source_path: Path | None = None) -> dict:
    """Return raw log file content for backup/archival.
    
    MEMORY-SAFE: Refuses files larger than 100KB to prevent OOM.
    For large files, suggests copying to WIP workspace first.
    
    Returns:
        Dict with:
        - log_source: The log type
        - file_path: Absolute path to the log file
        - file_size: Size in bytes
        - content: File content
        - line_count: Total number of lines
    """
    MAX_SIZE_BYTES = 100 * 1024  # 100KB limit for safety
    
    # If custom source_path provided, use it directly
    if source_path:
        log_path = source_path
    else:
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
            "error": f"Log file not found: {log_path}",
            "hint": "Check the path or make sure CK3 has been run",
        }
    
    try:
        file_size = log_path.stat().st_size
        
        # Refuse large files to prevent OOM
        if file_size > MAX_SIZE_BYTES:
            size_mb = file_size / 1024 / 1024
            return {
                "error": f"File too large ({size_mb:.1f}MB). command='raw' is limited to 100KB.",
                "file_path": str(log_path),
                "file_size": file_size,
                "suggestion": (
                    "For large log files, use targeted access instead:\n"
                    "  • ck3_logs(command='read', lines=100) - get last N lines\n"
                    "  • ck3_logs(command='summary') - get parsed summary\n"
                    "  • ck3_logs(command='list', limit=50) - get filtered errors\n"
                    "  • ck3_logs(command='search', query='...') - search for specific text"
                ),
            }
        
        content = log_path.read_text(encoding='utf-8', errors='replace')
        line_count = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
        
        return {
            "log_source": source,
            "file_path": str(log_path),
            "file_size": file_size,
            "line_count": line_count,
            "content": content,
        }
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# ck3_conflicts - ARCHIVED 2025-01-02
# ============================================================================
# 
# The conflict analysis functions were archived because they used BANNED
# playset_id architecture. See: archive/conflict_analysis_jan2026/
#
# Conflict analysis will be rebuilt with the simple approach:
#
# FILE-LEVEL CONFLICTS:
#   Same relpath across multiple content_version_ids in mods[]
#   SELECT relpath, GROUP_CONCAT(content_version_id)
#   FROM files WHERE content_version_id IN (cvids from mods[])
#   GROUP BY relpath HAVING COUNT(DISTINCT content_version_id) > 1
#
# SYMBOL-LEVEL CONFLICTS:
#   Same symbol name defined in multiple cvids
#   SELECT name, symbol_type, GROUP_CONCAT(content_version_id)
#   FROM symbols WHERE content_version_id IN (cvids from mods[])
#   GROUP BY name, symbol_type HAVING COUNT(DISTINCT content_version_id) > 1
#
# No playset_id needed - just use session.mods[] cvids directly.
# ============================================================================


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
    # For read/write
    content: str | None = None,
    start_line: int = 1,
    end_line: int | None = None,
    max_bytes: int = 200000,
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
    source_mod: str | None = None,  # Source mod containing the file to patch
    patch_mode: str | None = None,  # "partial_patch" or "full_replace"
    # Dependencies (injected)
    session=None,
    db=None,
    trace=None,
    visibility=None,  # VisibilityScope for DB queries
    world=None,  # WorldAdapter for unified path resolution
    # Reply system (Phase C migration)
    trace_info: TraceInfo | None = None,
) -> Reply | dict:
    """
    Unified file operations tool.
    
    Commands:
    
    command=get          -> Get file content from database (path required)
    command=read         -> Read file from filesystem (path or mod_name+rel_path)
    command=write        -> Write file to mod (mod_name, rel_path, content required)
    command=edit         -> Search-replace in mod file (mod_name, rel_path, old_content, new_content)
    command=delete       -> Delete file from mod (mod_name, rel_path required)
    command=rename       -> Rename/move file in mod (mod_name, rel_path, new_path required)
    command=refresh      -> Re-sync file to database (mod_name, rel_path required)
    command=list         -> List files in mod (mod_name required, path_prefix/pattern optional)
    command=create_patch -> Create override patch file (ck3lens only; mod_name, source_path, patch_mode required; source_mod optional)
    
    WARNING: create_patch is ck3lens mode only. Creates override patch files in mods.
    
    The world parameter provides WorldAdapter for unified path resolution:
    - Resolves raw paths to canonical addresses
    - Validates visibility based on agent mode (FOUND/NOT_FOUND)
    - Does NOT provide permission hints (enforcement.py decides)
    """
    from pathlib import Path as P
    from ck3lens.agent_mode import get_agent_mode
    from ck3lens.policy.enforcement import OperationType, Decision, enforce
    from ck3lens.policy.contract_v1 import get_active_contract
    from ck3lens.world_adapter import normalize_path_input
    
    mode = get_agent_mode()
    write_commands = {"write", "edit", "delete", "rename"}
    
    # ==========================================================================
    # STEP 1: CANONICAL PATH NORMALIZATION (FIRST)
    # Use normalize_path_input() for all path resolution.
    # This is the SINGLE resolver - no inline path building anywhere.
    # ==========================================================================
    
    resolution = None
    
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
    
    # ==========================================================================
    # STEP 2: CENTRALIZED ENFORCEMENT GATE (AFTER resolution)
    # Only reached if the path is visible. Now check policy via capability matrix.
    # Uses the clean enforce() API with OperationType.READ/WRITE/DELETE
    # ==========================================================================
    
    if command in write_commands and mode and resolution and resolution.absolute_path:
        # Map command to canonical operation type
        op_type = OperationType.DELETE if command == "delete" else OperationType.WRITE
        
        # Check if we have a contract
        contract = get_active_contract()
        has_contract = contract is not None
        
        # Enforce policy using clean API - pass resolution directly (canonical pattern)
        result = enforce(
            mode=mode,
            operation=op_type,
            resolved=resolution,  # ResolutionResult from normalize_path_input
            has_contract=has_contract,
        )
        
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
                "hint": "Deletion requires confirmation token",
            }
        
        # Decision is ALLOW - continue to implementation
    
    # ==========================================================================
    # ROUTE TO IMPLEMENTATION
    # ==========================================================================
    
    if command == "get":
        return _file_get(path, include_ast, max_bytes, db, trace, visibility)
    
    elif command == "read":
        if path:
            # Use WorldAdapter for visibility check if available
            return _file_read_raw(path, start_line, end_line, trace, world, trace_info=trace_info)
        elif mod_name and rel_path:
            return _file_read_live(mod_name, rel_path, max_bytes, session, trace, trace_info=trace_info)
        else:
            return {"error": "Either 'path' or 'mod_name'+'rel_path' required for read"}
    
    elif command == "write":
        if content is None:
            return {"error": "content required for write"}
        
        # Unified write path: always use absolute_path from resolution
        if resolution and resolution.absolute_path:
            return _file_write_raw(str(resolution.absolute_path), content, validate_syntax, token_id, trace, world, trace_info=trace_info)
        else:
            return {"error": "Path resolution failed - no absolute_path available"}
    
    elif command == "edit":
        if old_content is None or new_content is None:
            return {"error": "old_content and new_content required for edit"}
        
        # Unified edit path: always use absolute_path from resolution
        if resolution and resolution.absolute_path:
            return _file_edit_raw(str(resolution.absolute_path), old_content, new_content, validate_syntax, token_id, trace, world)
        else:
            return {"error": "Path resolution failed - no absolute_path available"}
    
    elif command == "delete":
        if resolution and resolution.absolute_path:
            return _file_delete_raw(str(resolution.absolute_path), token_id, trace, world)
        else:
            return {"error": "Path resolution failed - no absolute_path available for delete"}
    
    elif command == "rename":
        if resolution and resolution.absolute_path and new_path:
            return _file_rename_raw(str(resolution.absolute_path), new_path, token_id, trace, world)
        elif not new_path:
            return {"error": "new_path required for rename"}
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
            source_mod=source_mod,
            source_path=source_path,
            patch_mode=patch_mode,
            initial_content=content,
            validate_syntax=validate_syntax,
            session=session,
            trace=trace,
            mode=mode,
        )
    
    return {"error": f"Unknown command: {command}"}


def _file_get(path, include_ast, max_bytes, db, trace, visibility):
    """Get file from database."""
    if not path:
        return {"error": "path required for get command"}
    
    if db is None:
        return {"error": "Database not available. Use command='read' for filesystem access."}
    
    result = db.get_file(relpath=path, include_ast=include_ast, visibility=visibility)
    
    if trace:
        trace.log("ck3lens.file.get", {"path": path, "include_ast": include_ast}, 
                  {"found": result is not None})
    
    if result:
        result["scope"] = visibility.purpose if visibility else "ALL CONTENT"
        return result
    return {"error": f"File not found: {path}"}


def _file_read_raw(path, start_line, end_line, trace, world=None, *, trace_info: TraceInfo | None = None) -> Reply | dict:
    """
    Read file from filesystem with WorldAdapter visibility enforcement.
    
    Returns Reply if trace_info provided, otherwise legacy dict for backward compat during migration.
    """
    from pathlib import Path as P
    from ck3raven.core.reply_registry import get_message
    
    file_path = P(path)
    
    # Create reply builder if we have trace_info
    rb = None
    if trace_info:
        rb = _create_reply_builder(trace_info, "ck3_file", layer="WA")
    
    # WorldAdapter visibility - THE canonical way
    # world parameter is REQUIRED - no fallback to banned playset_scope
    if world is None:
        err = "WorldAdapter not provided - cannot resolve path visibility"
        if rb:
            return rb.error("WA-RES-E-001", {"error": err, "input_path": str(path)})
        return {
            "success": False,
            "error": err,
            "hint": "Caller must pass world parameter from _get_world()",
        }
    
    resolution = world.resolve(str(file_path))
    if not resolution.found:
        if rb:
            return rb.invalid("WA-RES-I-001", {"input_path": str(path), "mode": world.mode})
        return {
            "success": False,
            "error": f"Path not found: {path}",
            "mode": world.mode,
        }
    
    # Use resolved absolute path (always set when resolution.found is True)
    if resolution.absolute_path is None:
        err = f"Resolution returned no path for: {path}"
        if rb:
            return rb.error("WA-RES-E-001", {"error": err, "input_path": str(path)})
        return {"success": False, "error": err}
    file_path = resolution.absolute_path
    
    if trace:
        trace.log("ck3lens.file.read", {"path": str(file_path)}, {})
    
    if not file_path.exists():
        if rb:
            return rb.invalid("WA-RES-I-001", {"input_path": str(path)})
        return {"success": False, "error": f"File not found: {path}"}
    
    if not file_path.is_file():
        if rb:
            return rb.error("WA-RES-E-002", {"input_path": str(path)})
        return {"success": False, "error": f"Not a file: {path}"}
    
    try:
        content = file_path.read_text(encoding='utf-8', errors='replace')
        lines = content.splitlines(keepends=True)
        
        # Apply line range
        start_idx = max(0, start_line - 1)
        end_idx = end_line if end_line else len(lines)
        selected = lines[start_idx:end_idx]
        
        data = {
            "content": "".join(selected),
            "lines_read": len(selected),
            "total_lines": len(lines),
            "start_line": start_line,
            "end_line": end_idx,
            "canonical_path": str(file_path),
        }
        
        if rb:
            return rb.success("WA-RES-S-001", data)
        return {"success": True, **data}
    except Exception as e:
        if rb:
            return rb.error("WA-RES-E-001", {"error": str(e), "input_path": str(path)})
        return {"success": False, "error": str(e)}


def _file_read_live(mod_name, rel_path, max_bytes, session, trace, *, trace_info: TraceInfo | None = None) -> Reply | dict:
    """
    Read file from mod.
    
    Returns Reply if trace_info provided, otherwise legacy dict for backward compat during migration.
    """
    from ck3lens.workspace import validate_relpath
    
    # Create reply builder if we have trace_info
    rb = None
    if trace_info:
        rb = _create_reply_builder(trace_info, "ck3_file", layer="WA")
    
    mod = session.get_mod(mod_name)
    if not mod:
        if rb:
            return rb.invalid("WA-RES-I-001", {"input_path": f"{mod_name}:{rel_path}", "mod_name": mod_name})
        return {"error": f"Unknown mod_id: {mod_name}", "exists": False}
    
    valid, err = validate_relpath(rel_path)
    if not valid:
        if rb:
            return rb.error("WA-RES-E-002", {"input_path": rel_path, "error": err})
        return {"error": err, "exists": False}
    
    file_path = mod.path / rel_path
    
    if not file_path.exists():
        if rb:
            return rb.invalid("WA-RES-I-001", {
                "input_path": f"{mod_name}:{rel_path}",
                "mod_id": mod_name,
                "relpath": rel_path,
                "exists": False,
            })
        return {"mod_id": mod_name, "relpath": rel_path, "exists": False, "content": None}
    
    try:
        content = file_path.read_text(encoding="utf-8-sig")
        if max_bytes and len(content.encode("utf-8")) > max_bytes:
            content = content[:max_bytes]
        
        data = {
            "mod_id": mod_name,
            "relpath": rel_path,
            "exists": True,
            "content": content,
            "size": len(content),
            "canonical_path": str(file_path),
        }
        
        if trace:
            trace.log("ck3lens.file.read_live", {"mod_name": mod_name, "rel_path": rel_path},
                      {"success": True})
        
        if rb:
            return rb.success("WA-RES-S-001", data)
        return data
        
    except Exception as e:
        if trace:
            trace.log("ck3lens.file.read_live", {"mod_name": mod_name, "rel_path": rel_path},
                      {"success": False})
        if rb:
            return rb.error("WA-RES-E-001", {"error": str(e), "input_path": f"{mod_name}:{rel_path}"})
        return {"error": str(e), "exists": True}


def _file_write(mod_name, rel_path, content, validate_syntax, session, trace, *, trace_info: TraceInfo | None = None) -> Reply | dict:
    """
    Write file to mod.
    
    NOTE: Enforcement already happened in ck3_file dispatcher.
    This function only does the actual write + syntax validation.
    
    Returns Reply if trace_info provided, otherwise legacy dict for backward compat during migration.
    """
    from ck3lens.workspace import validate_relpath
    from ck3lens.validate import parse_content
    
    # Create reply builder if we have trace_info
    rb = None
    if trace_info:
        rb = _create_reply_builder(trace_info, "ck3_file", layer="EN")
    
    # Optional syntax validation
    if validate_syntax and rel_path.endswith(".txt"):
        parse_result = parse_content(content, rel_path)
        if not parse_result["success"]:
            if trace:
                trace.log("ck3lens.file.write", {"mod_name": mod_name, "rel_path": rel_path},
                          {"success": False, "reason": "syntax_error"})
            
            data = {
                "error": "Syntax validation failed",
                "parse_errors": parse_result["errors"],
                "canonical_path": f"{mod_name}:{rel_path}",
            }
            if rb:
                # Use PARSE-AST-E-001 for syntax errors (layer override to PARSE)
                first_error = parse_result["errors"][0] if parse_result["errors"] else {"line": 1, "message": "Unknown error"}
                return rb.error(
                    "PARSE-AST-E-001",
                    {**data, "line": first_error.get("line", 1), "error": first_error.get("message", "Syntax error")},
                    layer="PARSE",
                )
            return {"success": False, **data}
    
    # Inline write operation
    mod = session.get_mod(mod_name)
    if not mod:
        err = f"Unknown mod_id: {mod_name}"
        if rb:
            return rb.invalid("WA-RES-I-001", {"input_path": f"{mod_name}:{rel_path}", "error": err})
        return {"success": False, "error": err}
    
    valid, err = validate_relpath(rel_path)
    if not valid:
        if rb:
            return rb.error("WA-RES-E-002", {"input_path": rel_path, "error": err})
        return {"success": False, "error": err}
    
    file_path = mod.path / rel_path
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        
        data = {
            "mod_id": mod_name,
            "relpath": rel_path,
            "bytes_written": len(content.encode("utf-8")),
            "full_path": str(file_path),
            "canonical_path": str(file_path),
        }
        
        # Auto-refresh in database via daemon IPC
        db_refresh = _refresh_file_in_db_internal(str(file_path), mod_name, rel_path)
        data["db_refresh"] = db_refresh
        
        if trace:
            trace.log("ck3lens.file.write", {"mod_name": mod_name, "rel_path": rel_path},
                      {"success": True})
        
        if rb:
            return rb.success("EN-WRITE-S-001", data)
        return {"success": True, **data}
        
    except Exception as e:
        if trace:
            trace.log("ck3lens.file.write", {"mod_name": mod_name, "rel_path": rel_path},
                      {"success": False, "error": str(e)})
        if rb:
            return rb.error("WA-RES-E-001", {"error": str(e), "input_path": f"{mod_name}:{rel_path}"})
        return {"success": False, "error": str(e)}


def _file_write_raw(path, content, validate_syntax, token_id, trace, world=None, *, trace_info: TraceInfo | None = None) -> Reply | dict:
    """
    Write file to raw filesystem path.
    
    NOTE: Enforcement already happened in ck3_file dispatcher.
    This function only does the actual write + syntax validation.
    
    Returns Reply if trace_info provided, otherwise legacy dict for backward compat during migration.
    """
    from pathlib import Path as P
    from ck3lens.validate import parse_content
    from ck3lens.agent_mode import get_agent_mode
    
    file_path = P(path).resolve()
    mode = get_agent_mode()
    
    # Create reply builder if we have trace_info
    rb = None
    if trace_info:
        rb = _create_reply_builder(trace_info, "ck3_file", layer="EN")
    
    # Validate syntax if requested
    if validate_syntax and path.endswith(".txt"):
        parse_result = parse_content(content, path)
        if not parse_result["success"]:
            data = {
                "error": "Syntax validation failed",
                "parse_errors": parse_result["errors"],
                "canonical_path": str(file_path),
            }
            if rb:
                first_error = parse_result["errors"][0] if parse_result["errors"] else {"line": 1, "message": "Unknown error"}
                return rb.error(
                    "PARSE-AST-E-001",
                    {**data, "line": first_error.get("line", 1), "error": first_error.get("message", "Syntax error")},
                    layer="PARSE",
                )
            return {"success": False, **data}
    
    # Write the file
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        
        # Track core source change for WIP workaround detection
        if mode == "ck3raven-dev":
            from ck3lens.policy.wip_workspace import record_core_source_change
            from ck3lens.policy.contract_v1 import get_active_contract
            contract = get_active_contract()
            if contract:
                # Check if this is a core source file (not WIP)
                path_str = str(file_path).replace("\\", "/").lower()
                if ".wip/" not in path_str:
                    record_core_source_change(contract.contract_id)
        
        if trace:
            trace.log("ck3lens.file.write_raw", {"path": str(file_path), "mode": mode},
                      {"success": True})
        
        data = {
            "path": str(file_path),
            "bytes_written": len(content.encode("utf-8")),
            "canonical_path": str(file_path),
        }
        
        if rb:
            return rb.success("EN-WRITE-S-001", data)
        return {"success": True, **data}
        
    except Exception as e:
        if rb:
            return rb.error("WA-RES-E-001", {"error": str(e), "input_path": str(path)})
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
            from ck3lens.policy.contract_v1 import get_active_contract
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
    Edit file in mod.
    
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
            abs_path = str(mod.path / rel_path) if mod else None
            db_refresh = _refresh_file_in_db_internal(abs_path, mod_name, rel_path)
            result["db_refresh"] = db_refresh
    
    if trace:
        trace.log("ck3lens.file.edit", {"mod_name": mod_name, "rel_path": rel_path},
                  {"success": result.get("success", False)})
    
    return result


def _file_delete(mod_name, rel_path, session, trace):
    """
    Delete file from mod.
    
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
        abs_path = str(mod.path / rel_path) if mod else None
        db_refresh = _refresh_file_in_db_internal(abs_path, mod_name, rel_path, deleted=True)
        result["db_refresh"] = db_refresh
    
    if trace:
        trace.log("ck3lens.file.delete", {"mod_name": mod_name, "rel_path": rel_path},
                  {"success": result.get("success", False)})
    
    return result


def _file_rename(mod_name, old_path, new_path, session, trace):
    """Rename file in mod."""
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
        old_abs = str(mod.path / old_path) if mod else None
        _refresh_file_in_db_internal(old_abs, mod_name, old_path, deleted=True)
        try:
            new_content = (mod.path / new_path).read_text(encoding="utf-8-sig")
            new_abs = str(mod.path / new_path)
            db_refresh = _refresh_file_in_db_internal(new_abs, mod_name, new_path)
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
                result = _refresh_file_in_db_internal(str(file_path), mod_name, rel_path, deleted=True)
            else:
                try:
                    content = file_path.read_text(encoding="utf-8-sig")
                    result = _refresh_file_in_db_internal(str(file_path), mod_name, rel_path)
                except Exception as e:
                    result = {"success": False, "error": str(e)}
    
    if trace:
        trace.log("ck3lens.file.refresh", {"mod_name": mod_name, "rel_path": rel_path},
                  {"success": result.get("success", False)})
    
    return result


def _file_list(mod_name, path_prefix, pattern, session, trace):
    """List files in mod."""
    from .world_adapter import get_world_adapter
    
    mod = session.get_mod(mod_name)
    if not mod:
        result = {"error": f"Unknown mod_id: {mod_name}"}
    else:
        target = mod.path / path_prefix if path_prefix else mod.path
        if not target.exists():
            result = {"files": [], "folder": path_prefix}
        else:
            # Get WorldAdapter for canonical path resolution
            adapter = get_world_adapter(
                mode=session.mode,
                mods=session.mods,
                local_mods_folder=session.local_mods_folder,
            )
            
            files = []
            glob_pattern = pattern or "*.txt"
            for f in target.rglob(glob_pattern):
                if f.is_file():
                    try:
                        # Use WorldAdapter.resolve() to get canonical address
                        resolution = adapter.resolve(str(f)) if adapter else None
                        if resolution and resolution.found and resolution.address:
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
    Requires confirmation via token_id (any value = confirmed).
    """
    from pathlib import Path as P
    
    file_path = P(path).resolve()
    
    # Confirmation required for file deletion
    if not token_id:
        return {
            "success": False, 
            "error": "File deletion requires confirmation. Provide token_id='confirm' to proceed.",
        }
    
    # token_id provided = user confirmed (any value accepted)
    
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


def _file_create_patch(mod_name, source_mod, source_path, patch_mode, initial_content, validate_syntax, session, trace, mode):
    """
    Create an override patch file in a mod.
    
    MODE: ck3lens only. Not available in ck3raven-dev mode.
    
    Parameters:
    - mod_name: Destination mod where the patch file goes (must be local/editable)
    - source_mod: Source mod containing the file to patch (optional - if provided, reads content)
    - source_path: Relative path of the file being overridden (e.g., "common/decisions/foo.txt")
    - patch_mode: "partial_patch" (zzz_ prefix) or "full_replace" (same name)
    - initial_content: Content for the patch (if None and source_mod provided, reads from source)
    
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
        return {"success": False, "error": "mod_name required for create_patch (destination mod)"}
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
    
    # If source_mod provided and no initial_content, read from source mod
    if source_mod and initial_content is None:
        source_mod_entry = session.get_mod(source_mod)
        if not source_mod_entry:
            return {
                "success": False, 
                "error": f"Source mod not found in active playset: {source_mod}",
                "hint": "Use the mod's display name as shown in the playset"
            }
        
        source_file_path = source_mod_entry.path / source_path
        if not source_file_path.exists():
            return {
                "success": False,
                "error": f"Source file not found: {source_path} in {source_mod}",
                "searched_path": str(source_file_path)
            }
        
        try:
            initial_content = source_file_path.read_text(encoding='utf-8-sig')
            # Add header comment
            header = f"""# Override patch for: {source_mod}/{source_path}
# Created: {datetime.now().strftime("%Y-%m-%d %H:%M")}
# Patch mode: {patch_mode}
# Source mod: {source_mod}
# Target mod: {mod_name}
# 
# This file was copied from the source mod. Edit as needed.

"""
            initial_content = header + initial_content
        except Exception as e:
            return {"success": False, "error": f"Failed to read source file: {e}"}
    
    # If no source_mod and no content, generate template
    elif initial_content is None:
        initial_content = f"""# Override patch for: {source_path}
# Created: {datetime.now().strftime("%Y-%m-%d %H:%M")}
# Patch mode: {patch_mode}
# Target mod: {mod_name}
# 
# For 'partial_patch' mode: Add only the specific units you want to override/add.
# For 'full_replace' mode: This file completely replaces the original.

"""
    
    # Compute output filename based on patch mode
    if patch_mode == "partial_patch":
        # Prefix with zzz_[prefix]_ to load LAST (wins for OVERRIDE types)
        # Use first letter of each word for short prefix: "Mini Super Compatch" -> "msc"
        mod_prefix = _compute_mod_prefix(mod_name)
        new_name = f"zzz_{mod_prefix}_{source.name}"
    else:  # full_replace
        # Same name (will override due to load order)
        new_name = source.name
    
    # Build target relative path (same directory structure)
    target_rel_path = str(source.parent / new_name)
    
    # Delegate to existing _file_write (handles folder creation, syntax validation)
    write_result = _file_write(mod_name, target_rel_path, initial_content, validate_syntax, session, trace)
    
    if write_result.get("success"):
        # Enhance result with patch-specific info
        write_result["patch_info"] = {
            "source_mod": source_mod,
            "source_path": source_path,
            "patch_mode": patch_mode,
            "created_path": target_rel_path,
        }
        write_result["message"] = f"Created {patch_mode} patch: {target_rel_path}"
        
        if trace:
            trace.log("ck3lens.file.create_patch", {
                "mod_name": mod_name,
                "source_mod": source_mod,
                "source_path": source_path,
                "patch_mode": patch_mode,
            }, {"success": True, "created_path": target_rel_path})
    
    return write_result


def _refresh_file_in_db_internal(absolute_path, mod_name=None, rel_path=None, deleted=False):
    """Internal helper to notify daemon of file changes via IPC.
    
    Uses the daemon IPC client (daemon_client.py) to notify the QBuilder daemon
    that a file needs re-indexing. The daemon handles all database writes.
    
    If daemon is not running, attempts to auto-start it as a background process.
    
    Args:
        absolute_path: Full filesystem path to the file
        mod_name: Optional mod name for context
        rel_path: Optional relative path within mod
        deleted: True if file was deleted
    
    Design decisions:
    - Uses IPC instead of subprocess CLI calls
    - Daemon handles all database mutations (Single-Writer architecture)
    - Non-blocking: just notifies daemon, doesn't wait for indexing
    - Auto-starts daemon if not running (spawns in background)
    """
    from pathlib import Path as P
    from ck3lens.daemon_client import daemon, DaemonNotAvailableError
    
    if not absolute_path:
        return {"success": False, "error": "No absolute_path provided"}
    
    file_path = str(absolute_path)
    
    try:
        
        # Check if daemon is running, auto-start if not
        if not daemon.is_available(force_check=True):
            # Attempt to auto-start the daemon
            started = _auto_start_daemon()
            if not started:
                return {
                    "success": False,
                    "error": "Daemon not running and auto-start failed",
                    "hint": "Start daemon manually: python -m qbuilder.cli daemon",
                }
        
        # Notify daemon of the file change
        if deleted:
            # For deletion, still use enqueue but the file won't exist
            result = daemon.enqueue_files(
                paths=[file_path],
                mod_name=mod_name,
                priority="high",
                reason="file_deleted",
            )
        else:
            result = daemon.notify_file_changed(file_path, mod_name)
        
        return {
            "success": True,
            "queued": True,
            "daemon_response": result,
            "message": f"File {mod_name}/{rel_path} queued for {'deletion' if deleted else 'processing'}",
        }
        
    except DaemonNotAvailableError as e:
        return {
            "success": False,
            "error": f"Daemon not available: {e}",
            "hint": "Start daemon with: python -m qbuilder.cli daemon",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _auto_start_daemon():
    """Attempt to auto-start the QBuilder daemon as a background process.
    
    RACE CONDITION PROTECTION:
    - Checks writer lock BEFORE spawning to prevent multiple daemon instances
    - If lock is held but IPC not available, waits for daemon to finish starting
    - Only spawns if no lock holder exists
    
    Returns True if daemon started/available, False otherwise.
    """
    import subprocess
    import sys
    import time
    from pathlib import Path as P
    from ck3lens.daemon_client import daemon
    
    project_root = P(__file__).parent.parent.parent.parent
    python_exe = sys.executable
    
    # Add qbuilder to path for writer_lock import
    sys.path.insert(0, str(project_root))
    try:
        from qbuilder.writer_lock import check_writer_lock
    except ImportError:
        # If qbuilder not available, fall back to basic spawn
        pass
    else:
        # CRITICAL: Check writer lock BEFORE spawning to prevent race condition
        # The lock file exists immediately when daemon starts, before IPC is ready
        db_path = P.home() / ".ck3raven" / "ck3raven.db"
        try:
            lock_status = check_writer_lock(db_path)
            
            if lock_status.get("lock_exists") and lock_status.get("holder_alive"):
                # Another daemon holds the lock - wait for IPC to become available
                # Don't spawn a new process, just wait for the existing one
                for _ in range(20):  # Wait up to 10 seconds
                    time.sleep(0.5)
                    if daemon.is_available(force_check=True):
                        return True
                # Lock holder exists but IPC not responding after 10s - something is wrong
                # Still don't spawn - the lock holder will eventually timeout or be killed
                return False
        except Exception:
            # If we can't check the lock, fall back to basic spawn
            pass
    
    # No lock holder detected - safe to spawn
    try:
        import platform
        
        if platform.system() == "Windows":
            # Windows: use DETACHED_PROCESS flag
            CREATE_NO_WINDOW = 0x08000000
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                [python_exe, "-m", "qbuilder.cli", "daemon"],
                cwd=str(project_root),
                creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            # Unix: use nohup equivalent
            subprocess.Popen(
                [python_exe, "-m", "qbuilder.cli", "daemon"],
                cwd=str(project_root),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        
        # Wait a moment for daemon to start
        time.sleep(2)
        
        # Check if it's now available
        return daemon.is_available(force_check=True)
        
    except Exception:
        return False


# ============================================================================
# ck3_folder - Unified Folder Operations
# ============================================================================

FolderCommand = Literal["list", "contents", "top_level", "mod_folders"]


def ck3_folder_impl(
    command: FolderCommand = "list",
    # For list/contents
    path: str | None = None,
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
    cvids: list[int] | None = None,  # CANONICAL: cvids from session.mods[]
    trace=None,
    world=None,  # WorldAdapter for visibility enforcement
) -> dict:
    """
    Unified folder operations tool.
    
    Commands:
    
    command=list        -> List directory contents from filesystem (path required)
    command=contents    -> Get folder contents from database (path required)
    command=top_level   -> Get top-level folders in active playset
    command=mod_folders -> Get folders in specific mod (content_version_id required)
    
    CANONICAL: Uses cvids (list of content_version_ids from session.mods[]) instead of playset_id.
    The caller should pass cvids=[m.cvid for m in session.mods if m.cvid].
    """
    
    if command == "list":
        if not path:
            return {"error": "path required for list command"}
        return _folder_list_raw(path, trace, world)
    
    elif command == "contents":
        if not path:
            return {"error": "path required for contents command"}
        return _folder_contents(path, content_version_id, folder_pattern, text_search,
                                symbol_search, mod_filter, file_type_filter, db, cvids, trace)
    
    elif command == "top_level":
        return _folder_top_level(db, cvids, trace)
    
    elif command == "mod_folders":
        if not content_version_id:
            return {"error": "content_version_id required for mod_folders command"}
        return _folder_mod_folders(content_version_id, db, trace)
    
    return {"error": f"Unknown command: {command}"}


def _folder_list_raw(path, trace, world=None):
    """List directory from filesystem with WorldAdapter visibility enforcement."""
    from pathlib import Path as P
    
    dir_path = P(path).resolve()
    
    # WorldAdapter visibility check (preferred path)
    if world is not None:
        resolution = world.resolve(str(dir_path))
        if not resolution.found:
            return {
                "success": False,
                "error": f"Path not found: {path}",
                "mode": world.mode,
            }
        # Use resolved absolute path
        dir_path = resolution.absolute_path
    
    if trace:
        trace.log("ck3lens.folder.list", {"path": str(dir_path)}, {})
    
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
                     symbol_search, mod_filter, file_type_filter, db, cvids, trace):
    """Get folder contents from database.
    
    CANONICAL: Uses cvids (list of content_version_ids) instead of playset_id.
    """
    # Normalize path
    path = path.replace("\\", "/").strip("/")
    
    if not cvids:
        return {"error": "No cvids provided - session.mods[] may be empty or not resolved"}
    
    # Build query using cvids directly (no playset_mods table!)
    placeholders = ",".join("?" * len(cvids))
    conditions = [f"f.content_version_id IN ({placeholders})", "f.deleted = 0"]
    params = list(cvids)
    
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
            trace.log("ck3lens.folder.contents", {"path": path, "cvids_count": len(cvids)}, {"entries": len(entries)})
        
        return {
            "path": path,
            "entries": entries,
            "count": len(entries),
        }
    except Exception as e:
        return {"error": str(e)}


def _folder_top_level(db, cvids, trace):
    """Get top-level folders.
    
    CANONICAL: Uses cvids (list of content_version_ids) instead of playset_id.
    """
    if not cvids:
        return {"error": "No cvids provided - session.mods[] may be empty or not resolved"}
    
    placeholders = ",".join("?" * len(cvids))
    
    rows = db.conn.execute(f"""
        SELECT 
            SUBSTR(f.relpath, 1, INSTR(f.relpath || '/', '/') - 1) as folder,
            COUNT(*) as file_count
        FROM files f
        WHERE f.content_version_id IN ({placeholders}) AND f.deleted = 0
        GROUP BY folder
        ORDER BY folder
    """, cvids).fetchall()
    
    folders = [{"name": row['folder'], "fileCount": row['file_count']} 
               for row in rows if row['folder']]
    
    if trace:
        trace.log("ck3lens.folder.top_level", {"cvids_count": len(cvids)}, {"folders": len(folders)})
    
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
# DELETED: ck3_playset - Database-Based Playset Operations (January 2, 2026)
# ============================================================================
# The following functions were EXPUNGED as BANNED CONCEPTS:
# - ck3_playset_impl() - used playset_id parameter
# - _playset_get() - JOINed on playset_mods table
# - _playset_list() - JOINed on playset_mods table  
# - _playset_switch() - queried playsets table
# - _playset_mods() - JOINed on playset_mods table
# - _playset_add_mod() - INSERTed to playset_mods table
# - _playset_remove_mod() - DELETEd from playset_mods table
# - _playset_reorder() - UPDATEd playset_mods table
# - _playset_create() - INSERTed to playsets table
# - _playset_import() - placeholder
#
# REASON: playset_mods and playsets are BANNED TABLES that duplicate
# the canonical mods[] array from playset JSON files.
# 
# CANONICAL APPROACH: Playset operations are now FILE-BASED in server.py.
# See ck3_playset() in server.py which reads/writes playset/*.json files.
# ============================================================================


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
    world=None,  # WorldAdapter for canonical path resolution
) -> dict:
    """
    Unified git operations.
    
    Mode-aware behavior:
    - ck3raven-dev mode: Operates on ck3raven repo by default (mod_name ignored)
    - ck3lens mode: Operates on mods (mod_name required)
    
    Commands:
    
    command=status -> Get git status
    command=diff   -> Get git diff (file_path optional)
    command=add    -> Stage files (files or all_files required)
    command=commit -> Commit staged changes (message required)
    command=push   -> Push to remote
    command=pull   -> Pull from remote
    command=log    -> Get commit log (limit optional)
    """
    from ck3lens import git_ops
    from ck3lens.agent_mode import get_agent_mode
    from ck3lens.policy.enforcement import OperationType, Decision, enforce
    from ck3lens.policy.contract_v1 import get_active_contract
    from pathlib import Path as P
    
    # Validate session
    if not session:
        return {"error": "No session available - call ck3_init_session first"}
    
    # Mode detection
    mode = get_agent_mode()
    # Use ROOT_REPO from paths.py instead of computing from __file__
    
    # ==========================================================================
    # CENTRALIZED ENFORCEMENT GATE
    # Git write operations go through enforce() with the clean API
    # All git mutations are WRITE operations (add, commit, push, pull)
    # ==========================================================================
    
    write_commands = {"add", "commit", "push", "pull"}
    
    if command in write_commands and mode and world:
        # Determine target path for enforcement
        if mode == "ck3raven-dev":
            target_path = str(ROOT_REPO)
        else:
            # ck3lens mode - resolve mod path
            mod = session.get_mod(mod_name) if mod_name else None
            target_path = str(mod.path) if mod and hasattr(mod, 'path') else None
            if not target_path:
                return {
                    "error": f"Cannot resolve mod path for: {mod_name}",
                    "hint": "Mod must be in active playset and have valid path"
                }
        
        # Resolve path using WorldAdapter (canonical pattern)
        resolution = world.resolve(target_path)

        if not resolution.found:
            return {
                "error": f"Cannot resolve path for enforcement: {target_path}",
                "hint": resolution.error_message or "Path not in world scope",
            }
        
        # Check if we have a contract
        contract = get_active_contract()
        has_contract = contract is not None
        
        # Enforce policy using clean API - all git ops are WRITE
        result = enforce(
            mode=mode,
            operation=OperationType.WRITE,
            resolved=resolution,  # Pass ResolutionResult directly
            has_contract=has_contract,
        )
        
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
                "hint": "This git operation requires confirmation",
            }
        
        # Decision is ALLOW - continue to implementation
    
    # ==========================================================================
    # ROUTE TO IMPLEMENTATION
    # ==========================================================================
    
    # ck3raven-dev mode: always operate on repo, ignore mod_name
    if mode == "ck3raven-dev":
        if mod_name:
            # Log that we're ignoring mod_name but don't error
            pass  # Could trace.log a warning here
        
        result = _git_ops_for_path(command, ROOT_REPO, file_path, files, all_files, message, limit)
        if trace:
            trace.log(f"ck3lens.git.{command}", {"target": "ck3raven"},
                      {"success": result.get("success", "error" not in result)})
        return result

    # ck3lens mode: require mod_name for mod operations
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
    
    target=syntax     -> Validate CK3 script syntax (content required)
    target=python     -> Check Python syntax (content or file_path required)
    target=references -> Validate symbol references (symbol_name required)
    target=bundle     -> Validate artifact bundle (artifact_bundle required)
    target=policy     -> Validate against policy rules (mode required)
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
    """Validate symbol references.
    
    Uses Golden Join from ck3lens.db.golden_join for consistent schema.
    Note: Multiple files can share the same AST (content-addressed storage),
    so we may get multiple file matches per symbol.
    """
    # Look up symbol
    conditions = ["s.name = ?"]
    params = [symbol_name]
    
    if symbol_type:
        conditions.append("s.symbol_type = ?")
        params.append(symbol_type)
    
    # Join through asts to files via content_hash using Golden Join
    # This handles the content-addressed storage model correctly
    rows = db.conn.execute(f"""
        SELECT s.symbol_id, s.name, s.symbol_type, s.line_number,
               f.relpath, cv.name as mod_name
        FROM symbols s
        {GOLDEN_JOIN}
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
            "mod": row['mod_name'],
        } for row in rows],
    }


def _validate_bundle(artifact_bundle, trace):
    """Validate artifact bundle."""
    from ck3lens.validate import validate_artifact_bundle
    from ck3lens.contracts import ArtifactBundle
    
    try:
        bundle = ArtifactBundle.model_validate(artifact_bundle)
        result = validate_artifact_bundle(bundle)
        
        if trace:
            trace.log("ck3lens.validate.bundle", {}, {"valid": result.ok})
        
        return result.model_dump()
    except Exception as e:
        return {"valid": False, "error": str(e)}


def _validate_policy(mode, trace_path, trace_obj):
    """Validate against policy rules."""
    from typing import Any
    from ck3lens.policy import validate_for_mode
    from pathlib import Path as P
    
    trace_list: list[dict[str, Any]] | None = None
    if trace_path:
        path = P(trace_path)
        if not path.exists():
            return {"error": f"Trace file not found: {trace_path}"}
        import json
        try:
            trace_list = json.loads(path.read_text())
        except json.JSONDecodeError:
            return {"error": f"Trace file is not valid JSON: {trace_path}"}
    
    result = validate_for_mode(mode, trace=trace_list)
    
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
    
    command=ping           -> Test connection to VS Code
    command=diagnostics    -> Get diagnostics for a file (path required)
    command=all_diagnostics -> Get diagnostics for all files
    command=errors_summary -> Get workspace error summary
    command=validate_file  -> Trigger validation for a file (path required)
    command=open_files     -> List currently open files
    command=active_file    -> Get active file info with diagnostics
    command=status         -> Check IPC server status
    
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
