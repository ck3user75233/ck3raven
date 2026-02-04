"""
Journal MCP Tool

Unified tool for accessing journal archives from Copilot Chat sessions.

Commands:
    list      - List workspaces or windows
    read      - Read session content
    search    - Search by tag or content
    status    - Get journal status for current workspace
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal


# Journal storage location
def _get_journals_base() -> Path:
    """Get the journals base directory."""
    return Path.home() / ".ck3raven" / "journals"


def _list_workspaces() -> list[dict[str, Any]]:
    """List all workspace keys that have journal data."""
    base = _get_journals_base()
    if not base.exists():
        return []
    
    workspaces = []
    for entry in base.iterdir():
        # Workspace keys are 16-char hex (first 64 bits of SHA-256)
        # See: tools/ck3lens-explorer/src/journal/workspaceKey.ts
        if entry.is_dir() and len(entry.name) == 16 and entry.name.isalnum():
            windows_path = entry / "windows"
            window_count = 0
            if windows_path.exists():
                window_count = len([w for w in windows_path.iterdir() if w.is_dir()])
            
            workspaces.append({
                "workspace_key": entry.name,
                "window_count": window_count,
            })
    
    return workspaces


def _list_windows(workspace_key: str) -> list[dict[str, Any]]:
    """List windows for a workspace."""
    windows_path = _get_journals_base() / workspace_key / "windows"
    if not windows_path.exists():
        return []
    
    windows = []
    for entry in sorted(windows_path.iterdir(), reverse=True):  # Newest first
        if not entry.is_dir():
            continue
        
        manifest_path = entry / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                windows.append({
                    "window_id": entry.name,
                    "started_at": manifest.get("started_at"),
                    "ended_at": manifest.get("ended_at"),
                    "close_reason": manifest.get("close_reason"),
                    "exports_count": len(manifest.get("exports", [])),
                })
            except (json.JSONDecodeError, OSError):
                windows.append({
                    "window_id": entry.name,
                    "error": "Failed to read manifest",
                })
        else:
            windows.append({
                "window_id": entry.name,
                "error": "No manifest found",
            })
    
    return windows


def _list_sessions(workspace_key: str, window_id: str) -> list[dict[str, Any]]:
    """List sessions in a window."""
    window_path = _get_journals_base() / workspace_key / "windows" / window_id
    manifest_path = window_path / "manifest.json"
    
    if not manifest_path.exists():
        return []
    
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return manifest.get("exports", [])
    except (json.JSONDecodeError, OSError):
        return []


def _read_session(
    workspace_key: str, 
    window_id: str, 
    session_id: str,
    format: Literal["json", "markdown"] = "markdown",
) -> dict[str, Any]:
    """Read a session's content."""
    window_path = _get_journals_base() / workspace_key / "windows" / window_id
    
    if format == "markdown":
        file_path = window_path / f"{session_id}.md"
    else:
        file_path = window_path / f"{session_id}.json"
    
    if not file_path.exists():
        return {"error": f"Session file not found: {file_path.name}"}
    
    try:
        content = file_path.read_text(encoding="utf-8")
        if format == "json":
            return {"session_id": session_id, "data": json.loads(content)}
        else:
            return {"session_id": session_id, "content": content}
    except (json.JSONDecodeError, OSError) as e:
        return {"error": str(e)}


def _read_manifest(workspace_key: str, window_id: str) -> dict[str, Any]:
    """Read a window's manifest."""
    manifest_path = _get_journals_base() / workspace_key / "windows" / window_id / "manifest.json"
    
    if not manifest_path.exists():
        return {"error": "Manifest not found"}
    
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"error": str(e)}


def _search_tags(
    workspace_key: str | None = None,
    pattern: str = "*",
) -> list[dict[str, Any]]:
    """Search for tags matching a pattern."""
    base = _get_journals_base()
    results: list[dict[str, Any]] = []
    
    # Determine which workspaces to search
    if workspace_key:
        workspaces = [workspace_key]
    else:
        workspaces = [e.name for e in base.iterdir() if e.is_dir() and len(e.name) == 64]
    
    regex = re.compile("^" + pattern.replace("*", ".*") + "$", re.IGNORECASE)
    
    for ws_key in workspaces:
        tags_path = base / ws_key / "index" / "tags.jsonl"
        if not tags_path.exists():
            continue
        
        try:
            for line in tags_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if regex.match(entry.get("tag", "")):
                        results.append(entry)
                except json.JSONDecodeError:
                    continue
        except OSError:
            continue
    
    return results


def _get_status(workspace_key: str | None = None) -> dict[str, Any]:
    """Get journal status."""
    base = _get_journals_base()
    
    status: dict[str, Any] = {
        "journals_path": str(base),
        "journals_exist": base.exists(),
    }
    
    if not base.exists():
        status["workspaces"] = []
        return status
    
    # Count workspaces (folder names are hex strings, typically 16 chars from truncated hash)
    workspaces = [e for e in base.iterdir() if e.is_dir() and e.name.replace("-", "").isalnum()]
    status["workspace_count"] = len(workspaces)
    
    if workspace_key:
        # Get specific workspace info
        ws_path = base / workspace_key
        if ws_path.exists():
            windows = _list_windows(workspace_key)
            status["workspace"] = {
                "key": workspace_key,
                "window_count": len(windows),
                "latest_window": windows[0] if windows else None,
            }
        else:
            status["workspace"] = {"error": "Workspace not found"}
    
    return status


def ck3_journal(
    command: Literal["list", "read", "search", "status"] = "status",
    # List parameters
    target: Literal["workspaces", "windows", "sessions"] | None = None,
    workspace_key: str | None = None,
    window_id: str | None = None,
    # Read parameters
    session_id: str | None = None,
    format: Literal["json", "markdown"] = "markdown",
    # Search parameters
    pattern: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """
    Access journal archives from Copilot Chat sessions.
    
    Commands:
    
    command=list     → List workspaces, windows, or sessions
    command=read     → Read session content or manifest
    command=search   → Search tags across journals
    command=status   → Get journal status
    
    Args:
        command: Operation to perform
        target: What to list (workspaces, windows, sessions)
        workspace_key: Workspace identifier (SHA-256)
        window_id: Window identifier
        session_id: Session to read
        format: Output format for read (json, markdown)
        pattern: Tag pattern for search (* = wildcard)
        limit: Max results for search
    
    Returns:
        Dict with results based on command
    
    Examples:
        ck3_journal(command="status")
        ck3_journal(command="list", target="workspaces")
        ck3_journal(command="list", target="windows", workspace_key="abc123...")
        ck3_journal(command="read", workspace_key="...", window_id="...", session_id="...")
        ck3_journal(command="search", pattern="bug*")
    """
    
    if command == "list":
        if target == "workspaces" or target is None:
            workspaces = _list_workspaces()
            return {
                "success": True,
                "message": f"Found {len(workspaces)} workspace(s)",
                "workspaces": workspaces,
            }
        
        elif target == "windows":
            if not workspace_key:
                return {
                    "success": False,
                    "error": "workspace_key required for listing windows",
                }
            windows = _list_windows(workspace_key)
            return {
                "success": True,
                "message": f"Found {len(windows)} window(s)",
                "windows": windows,
                "workspace_key": workspace_key,
            }
        
        elif target == "sessions":
            if not workspace_key or not window_id:
                return {
                    "success": False,
                    "error": "workspace_key and window_id required for listing sessions",
                }
            sessions = _list_sessions(workspace_key, window_id)
            return {
                "success": True,
                "message": f"Found {len(sessions)} session(s)",
                "sessions": sessions,
                "workspace_key": workspace_key,
                "window_id": window_id,
            }
        
        else:
            return {
                "success": False,
                "error": f"Unknown target: {target}",
            }
    
    elif command == "read":
        if session_id:
            if not workspace_key or not window_id:
                return {
                    "success": False,
                    "error": "workspace_key and window_id required for reading session",
                }
            result = _read_session(workspace_key, window_id, session_id, format)
            if "error" in result:
                return {"success": False, "error": result["error"]}
            return {
                "success": True,
                "message": f"Session {session_id} retrieved",
                **result,
            }
        
        elif window_id:
            if not workspace_key:
                return {
                    "success": False,
                    "error": "workspace_key required for reading manifest",
                }
            manifest = _read_manifest(workspace_key, window_id)
            if "error" in manifest:
                return {"success": False, "error": manifest["error"]}
            return {
                "success": True,
                "message": f"Manifest for {window_id} retrieved",
                "manifest": manifest,
            }
        
        else:
            return {
                "success": False,
                "error": "session_id or window_id required for read command",
            }
    
    elif command == "search":
        search_pattern = pattern or "*"
        results = _search_tags(workspace_key, search_pattern)
        
        # Apply limit
        truncated = len(results) > limit
        results = results[:limit]
        
        return {
            "success": True,
            "message": f"Found {len(results)} tag match(es)",
            "matches": results,
            "pattern": search_pattern,
            "truncated": truncated,
        }
    
    elif command == "status":
        status = _get_status(workspace_key)
        return {
            "success": True,
            "message": "Journal status retrieved",
            **status,
        }
    
    else:
        return {
            "success": False,
            "error": f"Unknown command: {command}",
        }
