"""
Trace Helpers

Utility functions for analyzing MCP tool traces during policy validation.
"""
from __future__ import annotations
from typing import Any, Optional

from .types import ToolCall


# -----------------------------
# Tool Classification
# -----------------------------

# Database search tools
DB_SEARCH_TOOLS = frozenset({
    "ck3_search_symbols",
    "ck3_search_files",
    "ck3_search_content",
    "ck3_get_file",
    "ck3_confirm_not_exists",
})

# Conflict analysis tools
CONFLICT_TOOLS = frozenset({
    "ck3_scan_unit_conflicts",
    "ck3_get_conflict_summary",
    "ck3_list_conflict_units",
    "ck3_get_conflict_detail",
    "ck3_get_unit_content",
    "ck3_get_high_risk_conflicts",
    "ck3_generate_conflicts_report",
    "ck3_resolve_conflict",
})

# Filesystem tools (non-DB)
FS_TOOL_PREFIXES = (
    "fs_",
    "ck3_fs_",
    "filesystem_",
    "grep_",
    "find_",
    "read_file",
    "list_dir",
    "file_search",
)

# Validation tools
VALIDATION_TOOLS = frozenset({
    "ck3_parse_content",
    "ck3_validate_artifact_bundle",
    "ck3_validate_python",
})

# Session/playset tools
SESSION_TOOLS = frozenset({
    "ck3_init_session",
    "ck3_get_active_playset",
    "ck3_get_db_status",
})


# -----------------------------
# Trace Query Functions
# -----------------------------

def trace_has_call(trace: list[ToolCall], tool_name: str) -> bool:
    """Check if the trace contains a call to the specified tool."""
    return any(t.name == tool_name for t in trace)


def trace_calls(trace: list[ToolCall], tool_name: str) -> list[ToolCall]:
    """Get all calls to a specific tool from the trace."""
    return [t for t in trace if t.name == tool_name]


def trace_first_call_ts(trace: list[ToolCall], tool_name: str) -> Optional[int]:
    """Get the timestamp of the first call to a tool, or None if not found."""
    calls = trace_calls(trace, tool_name)
    return min((c.timestamp_ms for c in calls), default=None)


def trace_last_call_ts(trace: list[ToolCall], tool_name: str) -> Optional[int]:
    """Get the timestamp of the last call to a tool, or None if not found."""
    calls = trace_calls(trace, tool_name)
    return max((c.timestamp_ms for c in calls), default=None)


def trace_last_call(trace: list[ToolCall], tool_name: str) -> Optional[ToolCall]:
    """Get the most recent call to a specific tool."""
    calls = trace_calls(trace, tool_name)
    if not calls:
        return None
    return max(calls, key=lambda c: c.timestamp_ms)


# -----------------------------
# Tool Type Checks
# -----------------------------

def is_db_search_tool(tool_name: str) -> bool:
    """Check if a tool is a database search tool."""
    return tool_name in DB_SEARCH_TOOLS


def is_conflict_tool(tool_name: str) -> bool:
    """Check if a tool is a conflict analysis tool."""
    return tool_name in CONFLICT_TOOLS


def is_filesystem_tool(tool_name: str) -> bool:
    """Check if a tool is a filesystem access tool."""
    return any(tool_name.startswith(prefix) for prefix in FS_TOOL_PREFIXES)


def is_validation_tool(tool_name: str) -> bool:
    """Check if a tool is a validation tool."""
    return tool_name in VALIDATION_TOOLS


def is_session_tool(tool_name: str) -> bool:
    """Check if a tool is a session management tool."""
    return tool_name in SESSION_TOOLS


def is_scoped_tool(tool_name: str) -> bool:
    """Check if a tool should be scoped to active playset."""
    return is_db_search_tool(tool_name) or is_conflict_tool(tool_name)


# -----------------------------
# Trace Analysis
# -----------------------------

def trace_any_filesystem_search(trace: list[ToolCall]) -> bool:
    """Check if any filesystem search tools were used."""
    return any(is_filesystem_tool(t.name) for t in trace)


def extract_search_scope_from_call(call: ToolCall) -> dict[str, Any]:
    """
    Extract scope information from a tool call.
    
    Returns normalized scope dict with:
    - playset_id
    - mod_ids (set)
    - roots (set)
    - vanilla_version_id
    - query
    """
    args = call.args
    return {
        "playset_id": args.get("playset_id"),
        "mod_ids": set(args.get("mod_ids", []) or []),
        "roots": set(args.get("roots", []) or []),
        "vanilla_version_id": args.get("vanilla_version_id"),
        "query": args.get("query"),
    }


def get_db_search_calls(trace: list[ToolCall]) -> list[ToolCall]:
    """Get all database search tool calls from trace."""
    return [t for t in trace if is_db_search_tool(t.name)]


def get_conflict_calls(trace: list[ToolCall]) -> list[ToolCall]:
    """Get all conflict analysis tool calls from trace."""
    return [t for t in trace if is_conflict_tool(t.name)]


def get_scoped_calls(trace: list[ToolCall]) -> list[ToolCall]:
    """Get all calls that should be scoped to active playset."""
    return [t for t in trace if is_scoped_tool(t.name)]


def get_resolved_unit_keys(trace: list[ToolCall]) -> set[str]:
    """
    Extract unit_keys that were explicitly resolved via ck3_resolve_conflict.
    """
    resolved = set()
    for call in trace_calls(trace, "ck3_resolve_conflict"):
        # Check both args and result for unit_key
        uk = call.args.get("unit_key") or call.args.get("conflict_unit_id")
        if uk:
            resolved.add(uk)
        # Also check result
        uk_result = call.result_meta.get("unit_key")
        if uk_result:
            resolved.add(uk_result)
    return resolved


def count_tool_calls_by_type(trace: list[ToolCall]) -> dict[str, int]:
    """Count tool calls by category."""
    return {
        "db_search": sum(1 for t in trace if is_db_search_tool(t.name)),
        "conflict": sum(1 for t in trace if is_conflict_tool(t.name)),
        "filesystem": sum(1 for t in trace if is_filesystem_tool(t.name)),
        "validation": sum(1 for t in trace if is_validation_tool(t.name)),
        "session": sum(1 for t in trace if is_session_tool(t.name)),
        "total": len(trace),
    }
