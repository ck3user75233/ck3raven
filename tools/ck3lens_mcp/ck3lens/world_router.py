"""
World Router - Single Canonical Injection Point for World Access

This module provides the WorldRouter, the ONLY entry point for obtaining
a WorldAdapter. All MCP tools must use WorldRouter to get the appropriate
adapter for the current agent mode.

Architecture:
- WorldAdapter handles resolution (path -> absolute_path + root_category)
- Enforcement.py handles permission (ALLOW/DENY based on root_category)
- WorldRouter builds the appropriate adapter based on mode

All MCP tools must:
1. Get WorldAdapter from WorldRouter
2. Resolve references through the adapter (returns root_category)
3. If mutation needed → call enforcement.py with root_category
4. Enforcement decides ALLOW/DENY via capability matrix
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from .agent_mode import get_agent_mode
from .world_adapter import WorldAdapter

if TYPE_CHECKING:
    from .db_queries import DBQueries


_logger = logging.getLogger(__name__)


class WorldRouter:
    """
    Central router for obtaining WorldAdapters.
    
    Responsible for:
    1. Detecting the current agent mode
    2. Building the WorldAdapter with proper root paths
    3. Caching adapters for performance
    """
    
    _instance: Optional["WorldRouter"] = None
    
    def __init__(self):
        self._cached_adapter: Optional[WorldAdapter] = None
        self._cached_mode: Optional[str] = None
    
    @classmethod
    def get_instance(cls) -> "WorldRouter":
        """Get the singleton router instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset(cls) -> None:
        """Reset the router (for testing or mode changes)."""
        cls._instance = None
    
    def get_adapter(
        self,
        db: Optional["DBQueries"] = None,
        local_mods_folder: Optional[Path] = None,
        mods: Optional[list] = None,
        force_mode: Optional[str] = None,
    ) -> WorldAdapter:
        """
        Get the WorldAdapter for the current mode.
        
        Args:
            db: Database queries instance
            local_mods_folder: Path to local mods folder
            mods: List of mod entries from session
            force_mode: Override detected mode (for testing)
        
        Returns:
            WorldAdapter appropriate for the current mode
        """
        mode = force_mode or get_agent_mode()
        
        if mode is None:
            raise RuntimeError(
                "Agent mode not initialized. "
                "Call ck3_get_mode_instructions() first to set mode."
            )
        
        # Check cache
        if self._cached_adapter is not None and self._cached_mode == mode:
            return self._cached_adapter
        
        # Detect paths
        ck3raven_root = self._detect_ck3raven_root()
        vanilla_root = self._get_vanilla_root()
        utility_roots = self._get_utility_roots()
        
        # Build adapter via factory
        if mode == "ck3lens":
            wip_root = Path.home() / ".ck3raven" / "wip"
            adapter = WorldAdapter.create(
                mode="ck3lens",
                db=db,
                mods=mods or [],
                local_mods_folder=local_mods_folder,
                vanilla_root=vanilla_root,
                ck3raven_root=ck3raven_root,
                wip_root=wip_root,
                utility_roots=utility_roots,
            )
        elif mode == "ck3raven-dev":
            if ck3raven_root is None:
                raise RuntimeError("Could not detect ck3raven root directory")
            wip_root = ck3raven_root / ".wip"
            adapter = WorldAdapter.create(
                mode="ck3raven-dev",
                db=db,
                ck3raven_root=ck3raven_root,
                wip_root=wip_root,
                vanilla_root=vanilla_root,
            )
        else:
            raise RuntimeError(f"Unknown agent mode: {mode}")
        
        self._cached_adapter = adapter
        self._cached_mode = mode
        return adapter
    
    def _detect_ck3raven_root(self) -> Optional[Path]:
        """Detect the ck3raven repository root."""
        current = Path(__file__).resolve()
        for parent in current.parents:
            pyproject = parent / "pyproject.toml"
            if pyproject.exists():
                try:
                    if "ck3raven" in pyproject.read_text():
                        return parent
                except:
                    pass
            if (parent / ".git").exists() and (parent / "tools" / "ck3lens_mcp").exists():
                return parent
        return None
    
    def _get_vanilla_root(self) -> Optional[Path]:
        """Get the vanilla CK3 game root."""
        common_paths = [
            Path("C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game"),
            Path("C:/Program Files/Steam/steamapps/common/Crusader Kings III/game"),
            Path.home() / ".steam/steam/steamapps/common/Crusader Kings III/game",
        ]
        for p in common_paths:
            if p.exists():
                return p
        return None
    
    def _get_utility_roots(self) -> dict[str, Path]:
        """Get utility file roots (logs, saves, etc.)."""
        roots = {}
        ck3_user = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III"
        for name, subdir in [("logs", "logs"), ("saves", "save games"), ("crashes", "crashes")]:
            path = ck3_user / subdir
            if path.exists():
                roots[name] = path
        return roots


# =============================================================================
# MODULE-LEVEL CONVENIENCE FUNCTIONS
# =============================================================================

def get_world(
    db: Optional["DBQueries"] = None,
    local_mods_folder: Optional[Path] = None,
    mods: Optional[list] = None,
    force_mode: Optional[str] = None,
) -> WorldAdapter:
    """Get the WorldAdapter for the current mode."""
    return WorldRouter.get_instance().get_adapter(
        db=db,
        local_mods_folder=local_mods_folder,
        mods=mods,
        force_mode=force_mode,
    )


def get_current_mode() -> Optional[str]:
    """Get the current agent mode without building an adapter."""
    return get_agent_mode()


def reset_world() -> None:
    """Reset the world router (for testing or session changes)."""
    WorldRouter.reset()
