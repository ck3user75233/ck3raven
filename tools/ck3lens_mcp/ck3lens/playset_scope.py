"""
Playset Scope - Filesystem Path Validation

This module provides PlaysetScope for validating filesystem paths
against the active playset boundaries.

For ck3lens mode, this enforces the "database-projected view" policy
by restricting what paths can be accessed via filesystem operations.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Set


@dataclass
class PlaysetScope:
    """
    Filesystem path scope for the active playset.
    
    Used to restrict filesystem operations (reads, greps, etc.) to only
    paths within the active playset - vanilla game and active mods.
    """
    vanilla_root: Optional[Path]  # Path to vanilla game folder
    mod_roots: Set[Path]          # Paths to all active mod folders
    local_mod_roots: Set[Path]    # Subset of mod_roots that are writable (local mods)
    
    def is_path_in_scope(self, path: Path) -> bool:
        """
        Check if a path is within the playset scope.
        
        Returns True if path is under vanilla_root or any mod_root.
        """
        path = Path(path).resolve()
        
        # Check vanilla
        if self.vanilla_root:
            try:
                path.relative_to(self.vanilla_root.resolve())
                return True
            except ValueError:
                pass
        
        # Check all mod roots
        for mod_root in self.mod_roots:
            try:
                path.relative_to(mod_root.resolve())
                return True
            except ValueError:
                pass
        
        return False
    
    def is_path_writable(self, path: Path) -> bool:
        """
        Check if a path is within a writable (local mod) folder.
        
        Returns True if path is under any local_mod_root.
        Only local mods can be written to.
        """
        path = Path(path).resolve()
        
        for mod_root in self.local_mod_roots:
            try:
                path.relative_to(mod_root.resolve())
                return True
            except ValueError:
                pass
        
        return False
    
    def get_path_location(self, path: Path) -> tuple[str, Optional[str]]:
        """
        Determine where a path is located.
        
        Returns:
            (location_type, mod_name or None)
            
            location_type: "vanilla", "local_mod", "workshop_mod", or "outside_scope"
        """
        path = Path(path).resolve()
        
        # Check vanilla first
        if self.vanilla_root:
            try:
                path.relative_to(self.vanilla_root.resolve())
                return ("vanilla", None)
            except ValueError:
                pass
        
        # Check local mods
        for mod_root in self.local_mod_roots:
            try:
                path.relative_to(mod_root.resolve())
                return ("local_mod", mod_root.name)
            except ValueError:
                pass
        
        # Check workshop mods (non-local mod roots)
        workshop_roots = self.mod_roots - self.local_mod_roots
        for mod_root in workshop_roots:
            try:
                path.relative_to(mod_root.resolve())
                return ("workshop_mod", mod_root.name)
            except ValueError:
                pass
        
        return ("outside_scope", None)


def build_scope_from_session(session_scope: dict, local_mods: list) -> PlaysetScope:
    """
    Build a PlaysetScope from session scope data.
    
    Args:
        session_scope: Dict from _get_session_scope() with active_roots, vanilla_root
        local_mods: List of LocalMod objects (whitelisted editable mods)
    
    Returns:
        PlaysetScope configured for the active playset
    """
    vanilla_root = None
    if session_scope.get("vanilla_root"):
        vanilla_root = Path(session_scope["vanilla_root"])
    
    mod_roots = set()
    for root in session_scope.get("active_roots", set()):
        mod_roots.add(Path(root))
    
    local_mod_roots = set()
    for mod in local_mods:
        local_mod_roots.add(Path(mod.path))
    
    return PlaysetScope(
        vanilla_root=vanilla_root,
        mod_roots=mod_roots,
        local_mod_roots=local_mod_roots,
    )
