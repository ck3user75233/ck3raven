"""
Live Mod File Operations - DEPRECATED

This module is deprecated. Use local_mods instead.
All symbols are re-exported from local_mods for backwards compatibility.

Migration guide:
  - live_mods → local_mods
  - LiveMod → LocalMod
  - list_live_mods → list_local_mods
  - read_live_file → read_local_file
  - list_live_files → list_local_files
  
Session.live_mods property still works (forwards to local_mods).
"""
from __future__ import annotations
import warnings

# Re-export everything from local_mods
from .local_mods import (
    list_local_mods,
    list_live_mods,  # backwards compat alias
    read_local_file,
    read_live_file,  # backwards compat alias
    write_file,
    edit_file,
    delete_file,
    rename_file,
    list_local_files,
    list_live_files,  # backwards compat alias
)

# Issue deprecation warning on import
warnings.warn(
    "live_mods module is deprecated, use local_mods instead",
    DeprecationWarning,
    stacklevel=2
)

__all__ = [
    # New names
    "list_local_mods",
    "read_local_file",
    "list_local_files",
    # Old names (backwards compat)
    "list_live_mods",
    "read_live_file",
    "list_live_files",
    # Unchanged names
    "write_file",
    "edit_file",
    "delete_file",
    "rename_file",
]
