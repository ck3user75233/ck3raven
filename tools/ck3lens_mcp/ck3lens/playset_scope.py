"""
Playset Scope - Filesystem Path Visibility

This module provides PlaysetScope for describing filesystem path visibility
against the active playset boundaries.

ARCHITECTURAL INVARIANT (NO-ORACLE RULE):
- This module DESCRIBES visibility only
- This module MUST NOT deny execution
- This module MUST NOT answer permission questions
- Permission is enforced ONLY at the write boundary (mod_files.py)

See: docs/CANONICAL REFACTOR INSTRUCTIONS.md
See: docs/PLAYSET_ARCHITECTURE.md
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Set


@dataclass
class PlaysetScope:
    """
    Filesystem path scope for the active playset.
    
    Used to DESCRIBE what paths are within the playset scope.
    This is VISIBILITY, not permission.
    
    MUST NOT be used to deny operations - that happens at enforcement only.
    """
    vanilla_root: Optional[Path]           # Path to vanilla game folder
    mod_paths: Set[Path]                   # Paths to all active mod folders (derived from mods[].path)
    local_mods_folder: Optional[Path]      # The local mods folder boundary
    
    def is_path_in_scope(self, path: Path) -> bool:
        """
        Check if a path is within the playset scope (VISIBILITY).
        
        Returns True if path is under vanilla_root or any mod path.
        
        NOTE: This is a visibility check, NOT a permission check.
        """
        path = Path(path).resolve()
        
        # Check vanilla
        if self.vanilla_root:
            try:
                path.relative_to(self.vanilla_root.resolve())
                return True
            except ValueError:
                pass
        
        # Check all mod paths
        for mod_path in self.mod_paths:
            try:
                path.relative_to(mod_path.resolve())
                return True
            except ValueError:
                pass
        
        return False
    
    def path_under_local_mods(self, path: Path) -> bool:
        """
        Structural descriptor: Is this path under local_mods_folder?
        
        This is a STRUCTURAL FACT, not a permission oracle.
        Used for:
        - UI hints (lock icons, etc.)
        - Filtering in listings
        
        MUST NOT be used to deny execution.
        Permission is enforced ONLY at mod_files._enforce_write_boundary().
        """
        if not self.local_mods_folder:
            return False
        
        path = Path(path).resolve()
        local_folder = self.local_mods_folder.resolve()
        
        try:
            path.relative_to(local_folder)
            return True
        except ValueError:
            return False
    
    def get_path_location(self, path: Path) -> tuple[str, Optional[str]]:
        """
        Describe where a path is located (STRUCTURAL FACT).
        
        Returns:
            (location_type, mod_name or None)
            
            location_type: "vanilla", "local_mod", "workshop_mod", or "outside_scope"
        
        NOTE: This describes location, NOT permission.
        """
        path = Path(path).resolve()
        
        # Check vanilla first
        if self.vanilla_root:
            try:
                path.relative_to(self.vanilla_root.resolve())
                return ("vanilla", None)
            except ValueError:
                pass
        
        # Check each mod path
        for mod_path in self.mod_paths:
            try:
                path.relative_to(mod_path.resolve())
                # Determine if this mod is under local_mods_folder
                if self.path_under_local_mods(mod_path):
                    return ("local_mod", mod_path.name)
                else:
                    return ("workshop_mod", mod_path.name)
            except ValueError:
                pass
        
        return ("outside_scope", None)


def build_scope_from_session(session_scope: dict, local_mods_folder: Optional[Path] = None) -> PlaysetScope:
    """
    Build a PlaysetScope from session scope data.
    
    Args:
        session_scope: Dict from _get_session_scope() with active_roots, vanilla_root
        local_mods_folder: The local mods folder path (for structural checks)
    
    Returns:
        PlaysetScope configured for the active playset
    """
    vanilla_root = None
    if session_scope.get("vanilla_root"):
        vanilla_root = Path(session_scope["vanilla_root"])
    
    mod_paths = set()
    for root in session_scope.get("active_roots", set()):
        mod_paths.add(Path(root))
    
    return PlaysetScope(
        vanilla_root=vanilla_root,
        mod_paths=mod_paths,
        local_mods_folder=local_mods_folder,
    )
