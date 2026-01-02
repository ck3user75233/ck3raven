"""
World Router - Single Canonical Injection Point for World Access

This module provides the WorldRouter, the ONLY entry point for obtaining
a WorldAdapter. All MCP tools must use WorldRouter to get the appropriate
adapter for the current agent mode.

Architecture (NO-ORACLE REFACTOR - December 2025):
- WorldAdapter handles visibility (FOUND/NOT_FOUND)
- Enforcement.py handles permission (ALLOW/DENY)
- WorldRouter builds the appropriate adapter based on mode

All MCP tools must:
1. Get WorldAdapter from WorldRouter
2. Resolve references through the adapter
3. If mutation needed → call enforcement.py
4. Enforcement decides ALLOW/DENY

Forbidden patterns:
- Tool-local agent mode checks
- Tool-local visibility logic  
- Policy checks on unresolved paths
- is_writable checks (enforcement.py decides)

BANNED CONCEPTS (December 2025 purge):
- lens (parameter or variable)
- PlaysetLens (class - use mods[] instead)
- cvids as parameter (derive at DB boundary from mods[])
- LensWorldAdapter, DevWorldAdapter, UninitiatedWorldAdapter (use single WorldAdapter)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, TYPE_CHECKING

from .agent_mode import get_agent_mode
from .world_adapter import WorldAdapter  # Single class now handles all modes

if TYPE_CHECKING:
    from .db_queries import DBQueries


class WorldRouter:
    """
    Central router for obtaining WorldAdapters.
    
    The router is responsible for:
    1. Detecting the current agent mode
    2. Building the appropriate WorldAdapter with proper configuration
    3. Caching adapters for performance (per-session)
    
    This is the ONLY place where mode detection and adapter construction happen.
    
    December 2025 consolidation: Uses single WorldAdapter class with mode parameter
    instead of separate LensWorldAdapter/DevWorldAdapter classes.
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
        Get the WorldAdapter for the current (or specified) mode.
        
        Args:
            db: Database queries instance (required for full functionality)
            local_mods_folder: Path to local mods folder (for ck3lens write enforcement)
            mods: List of mod entries from session (for ck3lens visibility)
                  Each mod should have .name, .path, and optionally .cvid
            force_mode: Override detected mode (for testing)
        
        Returns:
            WorldAdapter appropriate for the current mode
        
        Raises:
            RuntimeError: If mode is not initialized
        """
        mode = force_mode or get_agent_mode()
        
        if mode is None:
            raise RuntimeError(
                "Agent mode not initialized. "
                "Call ck3_get_mode_instructions() first to set mode."
            )
        
        # Check cache
        if (
            self._cached_adapter is not None
            and self._cached_mode == mode
        ):
            return self._cached_adapter
        
        # Build new adapter using single WorldAdapter class
        if mode == "ck3lens":
            adapter = self._build_lens_adapter(db, local_mods_folder, mods)
        elif mode == "ck3raven-dev":
            adapter = self._build_dev_adapter(db)
        else:
            raise RuntimeError(f"Unknown agent mode: {mode}")
        
        self._cached_adapter = adapter
        self._cached_mode = mode
        return adapter
    
    def _build_lens_adapter(
        self,
        db: Optional["DBQueries"],
        local_mods_folder: Optional[Path],
        mods: Optional[list],
    ) -> WorldAdapter:
        """Build a WorldAdapter for ck3lens mode."""
        if db is None:
            raise RuntimeError("DBQueries required for ck3lens mode")
        
        if not mods:
            raise RuntimeError(
                "ck3lens mode requires mods list. "
                "Ensure a playset is active with session.mods populated."
            )
        
        # Get path configurations
        vanilla_root = self._get_vanilla_root()
        
        # WIP workspace for ck3lens is ~/.ck3raven/wip/
        wip_root = Path.home() / ".ck3raven" / "wip"
        
        # ck3raven source root (for bug report context)
        ck3raven_root = self._detect_ck3raven_root()
        
        # Utility roots (logs, saves, etc.)
        utility_roots = self._get_utility_roots()
        
        # Use single WorldAdapter class with mode="ck3lens"
        return WorldAdapter(
            mode="ck3lens",
            db=db,
            mods=mods,
            local_mods_folder=local_mods_folder,
            vanilla_root=vanilla_root,
            ck3raven_root=ck3raven_root,
            wip_root=wip_root,
            utility_roots=utility_roots,
        )
    
    def _build_dev_adapter(
        self,
        db: Optional["DBQueries"],
    ) -> WorldAdapter:
        """Build a WorldAdapter for ck3raven-dev mode.
        
        NOTE: ck3raven-dev mode does NOT use mod-related parameters.
        Mods are NOT part of the execution model for dev mode.
        """
        if db is None:
            raise RuntimeError("DBQueries required for ck3raven-dev mode")
        
        # ck3raven source root
        ck3raven_root = self._detect_ck3raven_root()
        if ck3raven_root is None:
            raise RuntimeError("Could not detect ck3raven root directory")
        
        # WIP workspace for dev mode is <repo>/.wip/
        wip_root = ck3raven_root / ".wip"
        
        # Get vanilla root for read access (parser testing only)
        vanilla_root = self._get_vanilla_root()
        
        # Use single WorldAdapter class with mode="ck3raven-dev"
        # NOTE: No mods, mod_paths, or mods_roots - these are banned for dev mode
        return WorldAdapter(
            mode="ck3raven-dev",
            db=db,
            ck3raven_root=ck3raven_root,
            wip_root=wip_root,
            vanilla_root=vanilla_root,
        )
    
    def _detect_ck3raven_root(self) -> Optional[Path]:
        """Detect the ck3raven repository root."""
        # Start from this file's location and walk up
        current = Path(__file__).resolve()
        
        # Walk up looking for markers
        for parent in current.parents:
            # Check for pyproject.toml with ck3raven
            pyproject = parent / "pyproject.toml"
            if pyproject.exists():
                try:
                    content = pyproject.read_text()
                    if "ck3raven" in content:
                        return parent
                except:
                    pass
            
            # Check for .git and tools/ck3lens_mcp
            if (parent / ".git").exists() and (parent / "tools" / "ck3lens_mcp").exists():
                return parent
        
        return None
    
    def _get_vanilla_root(self) -> Optional[Path]:
        """Get the vanilla CK3 game root."""
        # Try common Steam paths
        common_paths = [
            Path("C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game"),
            Path("C:/Program Files/Steam/steamapps/common/Crusader Kings III/game"),
            Path.home() / ".steam/steam/steamapps/common/Crusader Kings III/game",
        ]
        
        for p in common_paths:
            if p.exists():
                return p
        
        return None
    
    # NOTE: _get_mod_paths() REMOVED - banned concept for ck3raven-dev mode
    # ck3raven-dev does NOT use mod visibility filtering. Mods are not part of
    # the execution model for dev mode. See CANONICAL_ARCHITECTURE.md Section 9.
    
    def _get_utility_roots(self) -> dict[str, Path]:
        """Get utility file roots (logs, saves, etc.)."""
        roots = {}
        
        ck3_user = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III"
        
        # Logs
        logs_dir = ck3_user / "logs"
        if logs_dir.exists():
            roots["logs"] = logs_dir
        
        # Save games
        saves_dir = ck3_user / "save games"
        if saves_dir.exists():
            roots["saves"] = saves_dir
        
        # Crash dumps
        crashes_dir = ck3_user / "crashes"
        if crashes_dir.exists():
            roots["crashes"] = crashes_dir
        
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
    """
    Get the WorldAdapter for the current mode.
    
    This is the canonical entry point for all MCP tools.
    
    Args:
        db: Database queries instance
        local_mods_folder: Path to local mods folder
        mods: List of mod entries from session. Each mod should have:
              - .name: mod name
              - .path: filesystem path
              - .cvid: content_version_id (optional, for DB filtering)
        force_mode: Override detected mode (for testing)
    
    Example:
        world = get_world(db=db, mods=session.mods, local_mods_folder=session.local_mods_folder)
        result = world.resolve("mod:MSC/common/traits/test.txt")
        
        if not result.found:
            return {"error": result.error_message}
        
        # For writes, call enforcement.py - do NOT check result.is_writable
    """
    router = WorldRouter.get_instance()
    return router.get_adapter(
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
