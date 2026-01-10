"""
Path Migration Utilities

Handles cross-machine path portability for playset files.

PROBLEM:
Playset JSON files contain absolute paths like:
    C:\Users\nateb\Documents\Paradox Interactive\Crusader Kings III\mod
When pulled to a different machine (user Nathan), these paths don't exist.

SOLUTION:
1. Detect path mismatches at playset load time
2. Auto-migrate paths to current user's profile
3. Offer to save migrated playset
"""

import os
import re
from pathlib import Path
from typing import Optional, Tuple


def get_current_user_paths() -> dict:
    """Get standard CK3 paths for current user."""
    user_home = Path.home()
    user_docs = user_home / "Documents"
    
    return {
        "user_home": str(user_home),
        "user_docs": str(user_docs),
        "paradox_ck3": str(user_docs / "Paradox Interactive" / "Crusader Kings III"),
        "local_mods": str(user_docs / "Paradox Interactive" / "Crusader Kings III" / "mod"),
        "ck3raven_data": str(user_home / ".ck3raven"),
    }


def detect_path_mismatch(path_str: str) -> Optional[Tuple[str, str]]:
    """
    Detect if a path references a different user profile.
    
    Returns (old_user, current_user) if mismatch detected, None otherwise.
    """
    if not path_str:
        return None
    
    # Windows user path pattern
    win_match = re.match(r'[A-Za-z]:\\Users\\([^\\]+)\\', path_str)
    if win_match:
        old_user = win_match.group(1)
        current_user = os.environ.get('USERNAME', '')
        if old_user != current_user and current_user:
            return (old_user, current_user)
    
    # Unix home path pattern
    unix_match = re.match(r'/home/([^/]+)/', path_str)
    if unix_match:
        old_user = unix_match.group(1)
        current_user = os.environ.get('USER', '')
        if old_user != current_user and current_user:
            return (old_user, current_user)
    
    return None


def migrate_path(path_str: str, old_user: str, new_user: str) -> str:
    """
    Migrate a path from one user profile to another.
    
    Examples:
        C:\Users\nateb\Documents\... -> C:\Users\Nathan\Documents\...
        /home/nateb/... -> /home/nathan/...
    """
    if not path_str:
        return path_str
    
    # Windows
    migrated = re.sub(
        rf'([A-Za-z]:\\Users\\){re.escape(old_user)}(\\)',
        rf'\g<1>{new_user}\g<2>',
        path_str
    )
    
    # Unix
    migrated = re.sub(
        rf'(/home/){re.escape(old_user)}(/)',
        rf'\g<1>{new_user}\g<2>',
        migrated
    )
    
    return migrated


def migrate_playset_paths(playset_data: dict) -> Tuple[dict, bool, str]:
    """
    Migrate all paths in a playset to current user's profile.
    
    Returns:
        (migrated_data, was_modified, message)
    """
    import copy
    
    # Deep copy to avoid mutating original
    data = copy.deepcopy(playset_data)
    
    # Collect all paths to check
    paths_to_check = []
    
    # local_mods_folder
    if "local_mods_folder" in data:
        paths_to_check.append(("local_mods_folder", data.get("local_mods_folder", "")))
    
    # Mod paths
    for i, mod in enumerate(data.get("mods", [])):
        if "path" in mod:
            paths_to_check.append((f"mods[{i}].path", mod.get("path", "")))
    
    # Vanilla path
    vanilla = data.get("vanilla", {})
    if "path" in vanilla:
        paths_to_check.append(("vanilla.path", vanilla.get("path", "")))
    
    # Detect mismatch from first path
    mismatch = None
    for key, path_str in paths_to_check:
        mismatch = detect_path_mismatch(path_str)
        if mismatch:
            break
    
    if not mismatch:
        return data, False, "No path migration needed"
    
    old_user, new_user = mismatch
    
    # Migrate all paths
    modified_count = 0
    
    if "local_mods_folder" in data:
        old_val = data["local_mods_folder"]
        new_val = migrate_path(old_val, old_user, new_user)
        if old_val != new_val:
            data["local_mods_folder"] = new_val
            modified_count += 1
    
    for mod in data.get("mods", []):
        if "path" in mod:
            old_val = mod["path"]
            new_val = migrate_path(old_val, old_user, new_user)
            if old_val != new_val:
                mod["path"] = new_val
                modified_count += 1
    
    if "vanilla" in data and "path" in data["vanilla"]:
        old_val = data["vanilla"]["path"]
        new_val = migrate_path(old_val, old_user, new_user)
        if old_val != new_val:
            data["vanilla"]["path"] = new_val
            modified_count += 1
    
    message = f"Migrated {modified_count} paths from user '{old_user}' to '{new_user}'"
    return data, modified_count > 0, message
