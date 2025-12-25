"""
Local Mod File Operations

Sandboxed file operations for user-configured local mods only.
Mods are loaded from playset configuration, not hardcoded.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional

from .workspace import Session, LocalMod, validate_relpath


def list_local_mods(session: Session) -> dict:
    """List all mods the agent can write to.
    
    Returns mods configured in the active playset's local_mods list.
    May return empty list if no playset is active or no local mods configured.
    This is valid - read-only mode is fully supported.
    """
    return {
        "mods": [
            {
                "mod_id": mod.mod_id,
                "name": mod.name,
                "path": str(mod.path),
                "exists": mod.exists()
            }
            for mod in session.local_mods
        ]
    }


def read_local_file(session: Session, mod_id: str, relpath: str) -> dict:
    """
    Read a file from a local mod (current disk state).
    
    This reads the actual file on disk, not from DB.
    Use for seeing current state after modifications.
    """
    mod = session.get_local_mod(mod_id)
    if not mod:
        return {"error": f"Unknown mod_id: {mod_id}", "exists": False}
    
    # Validate path
    valid, err = validate_relpath(relpath)
    if not valid:
        return {"error": err, "exists": False}
    
    file_path = mod.path / relpath
    
    if not file_path.exists():
        return {
            "mod_id": mod_id,
            "relpath": relpath,
            "exists": False,
            "content": None
        }
    
    try:
        content = file_path.read_text(encoding="utf-8-sig")
        return {
            "mod_id": mod_id,
            "relpath": relpath,
            "exists": True,
            "content": content,
            "size": len(content)
        }
    except Exception as e:
        return {"error": str(e), "exists": True}


# Backwards compatibility alias
read_live_file = read_local_file


def write_file(
    session: Session,
    mod_id: str,
    relpath: str,
    content: str,
    create_dirs: bool = True
) -> dict:
    """
    Write or create a file in a local mod.
    
    Args:
        mod_id: Target mod
        relpath: Relative path within mod
        content: File content
        create_dirs: Create parent directories if needed
    """
    mod = session.get_local_mod(mod_id)
    if not mod:
        return {"success": False, "error": f"Unknown mod_id: {mod_id}"}
    
    # Validate path
    valid, err = validate_relpath(relpath)
    if not valid:
        return {"success": False, "error": err}
    
    file_path = mod.path / relpath
    
    # Double-check path is within mod
    if not session.is_path_allowed(file_path):
        return {"success": False, "error": "Path escapes sandbox"}
    
    try:
        if create_dirs:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_path.write_text(content, encoding="utf-8")
        
        return {
            "success": True,
            "mod_id": mod_id,
            "relpath": relpath,
            "bytes_written": len(content.encode("utf-8")),
            "full_path": str(file_path)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def edit_file(
    session: Session,
    mod_id: str,
    relpath: str,
    old_content: str,
    new_content: str
) -> dict:
    """
    Edit a portion of an existing file.
    
    Like replace_string_in_file - finds old_content and replaces with new_content.
    """
    mod = session.get_local_mod(mod_id)
    if not mod:
        return {"success": False, "error": f"Unknown mod_id: {mod_id}"}
    
    valid, err = validate_relpath(relpath)
    if not valid:
        return {"success": False, "error": err}
    
    file_path = mod.path / relpath
    
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {relpath}"}
    
    try:
        current = file_path.read_text(encoding="utf-8-sig")
        
        count = current.count(old_content)
        if count == 0:
            return {"success": False, "error": "old_content not found in file", "file_length": len(current)}
        
        updated = current.replace(old_content, new_content)
        file_path.write_text(updated, encoding="utf-8")
        
        return {
            "success": True,
            "mod_id": mod_id,
            "relpath": relpath,
            "replacements": count
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_file(session: Session, mod_id: str, relpath: str) -> dict:
    """Delete a file from a local mod."""
    mod = session.get_local_mod(mod_id)
    if not mod:
        return {"success": False, "error": f"Unknown mod_id: {mod_id}"}
    
    valid, err = validate_relpath(relpath)
    if not valid:
        return {"success": False, "error": err}
    
    file_path = mod.path / relpath
    
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {relpath}"}
    
    try:
        file_path.unlink()
        return {
            "success": True,
            "mod_id": mod_id,
            "relpath": relpath
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def rename_file(
    session: Session,
    mod_id: str,
    old_relpath: str,
    new_relpath: str
) -> dict:
    """
    Rename/move a file within a local mod.
    
    Args:
        mod_id: Target mod
        old_relpath: Current relative path within mod
        new_relpath: New relative path within mod
    """
    mod = session.get_local_mod(mod_id)
    if not mod:
        return {"success": False, "error": f"Unknown mod_id: {mod_id}"}
    
    # Validate both paths
    valid, err = validate_relpath(old_relpath)
    if not valid:
        return {"success": False, "error": f"old_relpath: {err}"}
    
    valid, err = validate_relpath(new_relpath)
    if not valid:
        return {"success": False, "error": f"new_relpath: {err}"}
    
    old_path = mod.path / old_relpath
    new_path = mod.path / new_relpath
    
    # Security checks
    if not session.is_path_allowed(old_path):
        return {"success": False, "error": "Old path escapes sandbox"}
    if not session.is_path_allowed(new_path):
        return {"success": False, "error": "New path escapes sandbox"}
    
    if not old_path.exists():
        return {"success": False, "error": f"File not found: {old_relpath}"}
    
    if new_path.exists():
        return {"success": False, "error": f"Destination already exists: {new_relpath}"}
    
    try:
        # Create parent directories if needed
        new_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Rename/move the file
        old_path.rename(new_path)
        
        return {
            "success": True,
            "mod_id": mod_id,
            "old_relpath": old_relpath,
            "new_relpath": new_relpath,
            "full_path": str(new_path)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_local_files(
    session: Session,
    mod_id: str,
    folder: str = "",
    pattern: str = "*.txt"
) -> dict:
    """List files in a local mod folder."""
    mod = session.get_local_mod(mod_id)
    if not mod:
        return {"error": f"Unknown mod_id: {mod_id}"}
    
    target = mod.path / folder if folder else mod.path
    
    if not target.exists():
        return {"files": [], "folder": folder}
    
    files = []
    for f in target.rglob(pattern):
        if f.is_file():
            try:
                rel = f.relative_to(mod.path)
                stat = f.stat()
                files.append({
                    "relpath": str(rel).replace("\\", "/"),
                    "size": stat.st_size,
                    "modified": stat.st_mtime
                })
            except Exception:
                pass
    
    return {
        "mod_id": mod_id,
        "folder": folder,
        "pattern": pattern,
        "files": sorted(files, key=lambda x: x["relpath"])
    }
