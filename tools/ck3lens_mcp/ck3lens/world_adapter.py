"""
World Adapter - Path Resolution and Classification for CK3 Lens

This module provides the WorldAdapter interface that:
1. RESOLVES inputs to absolute paths (mod:Name/path -> C:/mods/Name/path)
2. CLASSIFIES absolute paths to RootCategory by containment

WorldAdapter does NOT make permission decisions - enforcement.py does that
using the RootCategory returned by classify_path.

Address Scheme:
- mod:<mod_id>/<relative_path>     - Mod files (ck3lens mode)
- vanilla:/<relative_path>         - Vanilla game files
- utility:/logs/<file>             - CK3 utility files (logs, saves, etc.)
- ck3raven:/<relative_path>        - ck3raven source code (dev mode)
- wip:/<relative_path>             - WIP workspace files

BANNED CONCEPTS (January 2026):
- DbHandle, FsHandle (dead code, never called)
- _CAP_TOKEN (dead code)
- CapabilityError (dead code)
- self._vanilla_root, self._ck3raven_root, self._wip_root (use paths.py constants)
- vanilla_root, ck3raven_root, wip_root parameters (use paths.py constants)
- world_router module (all routing is via WorldAdapter.resolve())
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, FrozenSet, TYPE_CHECKING

if TYPE_CHECKING:
    from .db_queries import DBQueries


# =============================================================================
# ADDRESS AND PATH TYPES
# =============================================================================

class AddressType(Enum):
    """Types of canonical addresses."""
    MOD = "mod"
    VANILLA = "vanilla"
    UTILITY = "utility"
    CK3RAVEN = "ck3raven"
    WIP = "wip"
    DATA = "data"  # ~/.ck3raven/ (playsets, db, config)
    UNKNOWN = "unknown"


@dataclass
class CanonicalAddress:
    """
    A resolved canonical address.
    
    All MCP tool operations should work with CanonicalAddress, not raw paths.
    """
    address_type: AddressType
    identifier: Optional[str]  # mod_id for MOD type, None for others
    relative_path: str
    raw_input: str  # Original input for error messages
    
    @property
    def canonical_form(self) -> str:
        """Return the canonical string form of this address."""
        if self.address_type == AddressType.MOD:
            return f"mod:{self.identifier}/{self.relative_path}"
        elif self.address_type == AddressType.VANILLA:
            return f"vanilla:/{self.relative_path}"
        elif self.address_type == AddressType.UTILITY:
            return f"utility:/{self.relative_path}"
        elif self.address_type == AddressType.CK3RAVEN:
            return f"ck3raven:/{self.relative_path}"
        elif self.address_type == AddressType.WIP:
            return f"wip:/{self.relative_path}"
        elif self.address_type == AddressType.DATA:
            return f"data:/{self.relative_path}"
        else:
            return f"unknown:{self.raw_input}"
    
    def __str__(self) -> str:
        return self.canonical_form


@dataclass
class ResolutionResult:
    """
    Result of resolving an address through the WorldAdapter.
    
    If found=False, the reference does not exist in this world.
    
    The root_category and subdirectory are used by enforcement.py to check
    the capability matrix. This is STRUCTURAL classification only - 
    enforcement.py makes all permission decisions.
    """
    found: bool
    address: Optional[CanonicalAddress] = None
    absolute_path: Optional[Path] = None
    root_category: Optional["RootCategory"] = None  # From paths.RootCategory
    subdirectory: Optional[str] = None  # First path component under root (e.g., "wip", "mod")
    relative_path: Optional[str] = None  # Full relative path from root (for subfolders_writable check)
    file_id: Optional[int] = None
    content_version_id: Optional[int] = None
    mod_name: Optional[str] = None
    error_message: Optional[str] = None
    
    @classmethod
    def not_found(cls, raw_input: str, reason: str = "Reference not found") -> "ResolutionResult":
        """Create a not-found result."""
        from ck3lens.paths import RootCategory
        return cls(
            found=False,
            root_category=RootCategory.ROOT_EXTERNAL,
            error_message=f"{reason}: {raw_input}"
        )


# =============================================================================
# PATH NORMALIZATION UTILITY
# =============================================================================

def normalize_path_input(
    world: "WorldAdapter",
    *,
    path: Optional[str] = None,
    mod_name: Optional[str] = None,
    rel_path: Optional[str] = None,
) -> ResolutionResult:
    """
    CANONICAL PATH NORMALIZATION UTILITY
    
    This is THE single entry point for path resolution in MCP tools.
    
    Special handling:
    - mod_name="wip" -> routes to WIP workspace (wip:/<rel_path>)
    - mod_name="vanilla" -> routes to vanilla game (vanilla:/<rel_path>)
    - Other mod_name values -> routes to mod files (mod:<mod_name>/<rel_path>)
    """
    if path:
        address_to_resolve = path
    elif mod_name and rel_path:
        # Handle special pseudo-mod names that map to other domains
        if mod_name.lower() == "wip":
            address_to_resolve = f"wip:/{rel_path}"
        elif mod_name.lower() == "vanilla":
            address_to_resolve = f"vanilla:/{rel_path}"
        else:
            address_to_resolve = f"mod:{mod_name}/{rel_path}"
    elif mod_name:
        if mod_name.lower() == "wip":
            address_to_resolve = "wip:/"
        elif mod_name.lower() == "vanilla":
            address_to_resolve = "vanilla:/"
        else:
            address_to_resolve = f"mod:{mod_name}/"
    else:
        return ResolutionResult.not_found(
            "<no input>",
            "Either 'path' or 'mod_name'+'rel_path' required"
        )
    
    return world.resolve(address_to_resolve)


# =============================================================================
# WORLD ADAPTER - SINGLE MODE-AWARE CLASS
# =============================================================================

class WorldAdapterNotAvailableError(Exception):
    """Raised when WorldAdapter cannot be instantiated with given parameters."""
    pass


class WorldAdapter:
    """
    Single mode-aware WorldAdapter using CANONICAL RootCategory domains.
    
    Root paths are organized by RootCategory (the ONLY domain classification):
    - ROOT_REPO: ck3raven source
    - ROOT_GAME: Vanilla CK3 installation
    - ROOT_CK3RAVEN_DATA: ~/.ck3raven/ (contains WIP, playsets, db, config)
    - ROOT_USER_DOCS: User data folder (local mods, launcher-v2.sqlite, saves)
    - ROOT_STEAM: Steam Workshop content
    - ROOT_VSCODE: VS Code user data
    
    WorldAdapter determines:
    1. What EXISTS and can be REFERENCED (resolve, is_visible)
    2. What RootCategory a path belongs to (classify_path)
    
    WorldAdapter does NOT make permission decisions - enforcement.py does that
    using the RootCategory returned by classify_path.
    
    NOTE: WIP is NOT a separate root - it's ROOT_CK3RAVEN_DATA with subdirectory="wip"
    """
    
    def __init__(
        self,
        mode: str,
        db: Optional["DBQueries"] = None,
        *,
        # Root paths by canonical domain
        roots: Optional[dict["RootCategory", list[Path]]] = None,
        # Mod name → path mapping (for mod: address resolution)
        mod_paths: Optional[dict[str, Path]] = None,
        # DB visibility filter (ck3lens only)
        visible_cvids: Optional[FrozenSet[int]] = None,
    ):
        """
        Initialize WorldAdapter with canonical root paths.
        
        Args:
            mode: Agent mode ("ck3lens", "ck3raven-dev", or "uninitiated")
            db: DBQueries instance (optional)
            roots: Dict mapping RootCategory to list of paths for that domain
            mod_paths: Dict mapping mod names to their filesystem paths
            visible_cvids: Set of content_version_ids visible in ck3lens mode
        """
        from ck3lens.paths import RootCategory
        
        self._mode = mode
        self._db = db
        self._roots: dict[RootCategory, list[Path]] = roots or {}
        self._mod_paths: dict[str, Path] = mod_paths or {}
        self._visible_cvids = visible_cvids
    
    @classmethod
    def create(
        cls,
        mode: str = "uninitiated",
        db: Optional["DBQueries"] = None,
        *,
        mods: Optional[list] = None,
    ) -> "WorldAdapter":
        """
        Factory method using paths.py constants for all roots.
        
        All paths come from paths.py ROOT_* constants (config-driven).
        
        Args:
            mode: Agent mode ("ck3lens", "ck3raven-dev", or "uninitiated")
            db: DBQueries instance (optional)
            mods: List of mod objects with .name and .path attributes (ck3lens mode)
        """
        from ck3lens.paths import (
            RootCategory,
            ROOT_REPO,
            ROOT_CK3RAVEN_DATA,
            ROOT_GAME,
            ROOT_STEAM,
            ROOT_USER_DOCS,
            ROOT_VSCODE,
        )
        
        roots: dict[RootCategory, list[Path]] = {}
        mod_paths: dict[str, Path] = {}
        visible_cvids: Optional[FrozenSet[int]] = None
        
        # ROOT_CK3RAVEN_DATA - always set (constant is never None)
        roots[RootCategory.ROOT_CK3RAVEN_DATA] = [ROOT_CK3RAVEN_DATA]
        
        if ROOT_REPO and ROOT_REPO.exists():
            roots[RootCategory.ROOT_REPO] = [ROOT_REPO]
        if ROOT_GAME and ROOT_GAME.exists():
            roots[RootCategory.ROOT_GAME] = [ROOT_GAME]
        if ROOT_STEAM and ROOT_STEAM.exists():
            roots[RootCategory.ROOT_STEAM] = [ROOT_STEAM]
        if ROOT_USER_DOCS and ROOT_USER_DOCS.exists():
            roots[RootCategory.ROOT_USER_DOCS] = [ROOT_USER_DOCS]
        if ROOT_VSCODE and ROOT_VSCODE.exists():
            roots[RootCategory.ROOT_VSCODE] = [ROOT_VSCODE]
        
        # Process mods - build mod_paths lookup
        if mods:
            for mod in mods:
                if hasattr(mod, 'name') and hasattr(mod, 'path'):
                    mod_path = Path(mod.path) if isinstance(mod.path, str) else mod.path
                    mod_paths[mod.name] = mod_path
            
            # Extract CVIDs for visibility filter
            cvids = frozenset(
                m.cvid for m in mods 
                if hasattr(m, 'cvid') and m.cvid is not None
            )
            if cvids:
                visible_cvids = cvids
        
        return cls(
            mode=mode,
            db=db,
            roots=roots,
            mod_paths=mod_paths,
            visible_cvids=visible_cvids,
        )
    
    @property
    def mode(self) -> str:
        """Return the agent mode this adapter serves."""
        return self._mode
    
    # =========================================================================
    # HELPER: Get root path for a category (single path, first in list)
    # =========================================================================
    
    def _get_root(self, category: "RootCategory") -> Optional[Path]:
        """Get first root path for a category, or None if not configured."""
        paths = self._roots.get(category)
        return paths[0] if paths else None
    
    # =========================================================================
    # PATH CLASSIFICATION (THE single source of truth for root_category)
    # =========================================================================
    
    def classify_path(self, absolute_path: Path) -> "RootCategory":
        """
        Classify an absolute path into a RootCategory by containment.
        
        This is THE SINGLE source of truth for determining which geographic
        root a path belongs to. Checks configured roots in priority order.
        """
        from ck3lens.paths import RootCategory
        
        try:
            resolved = absolute_path.resolve()
        except (OSError, ValueError):
            return RootCategory.ROOT_EXTERNAL
        
        # Check roots in priority order (more specific first)
        priority_order = [
            RootCategory.ROOT_CK3RAVEN_DATA,  # Most specific (contains WIP)
            RootCategory.ROOT_REPO,
            RootCategory.ROOT_USER_DOCS,
            RootCategory.ROOT_GAME,
            RootCategory.ROOT_STEAM,
            RootCategory.ROOT_VSCODE,
        ]
        
        for category in priority_order:
            if category in self._roots:
                for root_path in self._roots[category]:
                    try:
                        resolved.relative_to(root_path.resolve())
                        return category
                    except ValueError:
                        pass
        
        return RootCategory.ROOT_EXTERNAL
    
    # =========================================================================
    # RESOLUTION
    # =========================================================================
    
    def resolve(self, path_or_address: str) -> ResolutionResult:
        """Resolve a path or address to absolute filesystem path.
        
        Resolution is MODE-AGNOSTIC - it determines structural identity only:
        - What canonical domain does this path belong to?
        - What is the absolute filesystem path?
        
        Enforcement (not resolution) determines what operations are allowed
        on the resolved path based on mode + domain.
        """
        if self._mode == "uninitiated":
            return ResolutionResult.not_found(
                path_or_address,
                "WorldAdapter not initialized - call ck3_get_mode_instructions first"
            )
        
        address = self._parse_or_translate(path_or_address)
        
        if address.address_type == AddressType.UNKNOWN:
            return ResolutionResult.not_found(
                path_or_address,
                "Could not resolve reference"
            )
        
        # Resolve address to absolute path based on address_type
        return self._resolve_to_absolute(address)
    
    def _resolve_to_absolute(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve CanonicalAddress to absolute path.
        
        Simple dispatch: look up root for address_type, join with relative_path.
        
        IMPORTANT: This method MUST set subdirectory and relative_path fields
        for proper capability matrix lookup. The capability matrix uses:
        - subdirectory: first path component under root (e.g., "mod", "wip")
        - relative_path: full path from root (for subfolders_writable check)
        """
        from ck3lens.paths import RootCategory, ROOT_USER_DOCS, ROOT_CK3RAVEN_DATA
        
        abs_path: Optional[Path] = None
        root_category: Optional[RootCategory] = None
        mod_name: Optional[str] = None
        subdirectory: Optional[str] = None
        relative_path_for_cap: Optional[str] = None  # For capability matrix lookup
        
        if address.address_type == AddressType.MOD:
            # Mod addresses use _mod_paths lookup
            mod_id = address.identifier
            if mod_id in self._mod_paths:
                mod_path = self._mod_paths[mod_id]
                abs_path = mod_path / address.relative_path
                root_category = self.classify_path(abs_path)
                mod_name = mod_id
                
                # For mods in ROOT_USER_DOCS, set subdirectory="mod" and compute
                # relative_path from ROOT_USER_DOCS for subfolders_writable check
                if root_category == RootCategory.ROOT_USER_DOCS and ROOT_USER_DOCS:
                    subdirectory = "mod"
                    # Relative path from ROOT_USER_DOCS should be like:
                    # "mod/ModName/common/traits/file.txt"
                    try:
                        rel_from_docs = abs_path.resolve().relative_to(ROOT_USER_DOCS.resolve())
                        relative_path_for_cap = str(rel_from_docs).replace("\\", "/")
                    except ValueError:
                        # Fallback: construct the path manually
                        relative_path_for_cap = f"mod/{mod_id}/{address.relative_path}"
            else:
                return ResolutionResult.not_found(
                    address.raw_input,
                    f"Mod '{mod_id}' not in active playset"
                )
        
        elif address.address_type == AddressType.VANILLA:
            root = self._get_root(RootCategory.ROOT_GAME)
            if root:
                abs_path = root / address.relative_path
                root_category = RootCategory.ROOT_GAME
                mod_name = "vanilla"
        
        elif address.address_type == AddressType.WIP:
            # WIP is a subdirectory of ROOT_CK3RAVEN_DATA
            # Use paths.py constant directly for consistency
            abs_path = ROOT_CK3RAVEN_DATA / "wip" / address.relative_path
            root_category = RootCategory.ROOT_CK3RAVEN_DATA
            subdirectory = "wip"  # CRITICAL: enforcement.py checks this
            relative_path_for_cap = f"wip/{address.relative_path}"
        
        elif address.address_type == AddressType.CK3RAVEN:
            root = self._get_root(RootCategory.ROOT_REPO)
            if root:
                abs_path = root / address.relative_path
                root_category = RootCategory.ROOT_REPO
        
        elif address.address_type == AddressType.DATA:
            # DATA addresses target ~/.ck3raven/ subdirectories
            # Use paths.py constant directly
            abs_path = ROOT_CK3RAVEN_DATA / address.relative_path
            root_category = RootCategory.ROOT_CK3RAVEN_DATA
            # Extract subdirectory from first component of relative_path
            parts = address.relative_path.replace("\\", "/").strip("/").split("/")
            if parts and parts[0]:
                subdirectory = parts[0]
                relative_path_for_cap = address.relative_path.replace("\\", "/")
        
        elif address.address_type == AddressType.UTILITY:
            # UTILITY addresses are deprecated - ROOT_UTILITIES was removed
            # Return not found for any utility:/ addresses
            return ResolutionResult.not_found(
                address.raw_input,
                "utility:/ addresses are no longer supported (ROOT_UTILITIES removed)"
            )
        
        if abs_path is None:
            return ResolutionResult.not_found(
                address.raw_input,
                f"No root configured for {address.address_type.value}"
            )
        
        return ResolutionResult(
            found=True,
            address=address,
            absolute_path=abs_path,
            root_category=root_category,
            subdirectory=subdirectory,
            relative_path=relative_path_for_cap,
            mod_name=mod_name,
        )
    
    def is_visible(self, path_or_address: str) -> bool:
        """Quick check if path can be resolved (exists in configured roots)."""
        result = self.resolve(path_or_address)
        return result.found
    
    # =========================================================================
    # ADDRESS PARSING (shared)
    # =========================================================================
    
    def _parse_or_translate(self, input_str: str) -> CanonicalAddress:
        """Parse canonical address or translate raw path."""
        input_str = input_str.strip()
        
        # Check for canonical address format vs Windows paths
        # Windows paths: C:\ or C:/ should be treated as raw paths, not canonical
        if ":" in input_str:
            # Check if this looks like a Windows drive letter path (e.g., C:/, D:\)
            if len(input_str) >= 2 and input_str[1] == ":" and (
                len(input_str) == 2 or input_str[2] in "\\/"
            ):
                return self._translate_raw_path(input_str)
            # Otherwise it's a canonical address like "mod:Name/path" or "wip:/file"
            return self._parse_canonical(input_str)
        
        return self._translate_raw_path(input_str)
    
    def _parse_canonical(self, address: str) -> CanonicalAddress:
        """Parse a canonical address string."""
        if address.startswith("mod:"):
            rest = address[4:]
            if "/" in rest:
                mod_id, rel_path = rest.split("/", 1)
                return CanonicalAddress(
                    address_type=AddressType.MOD,
                    identifier=mod_id,
                    relative_path=rel_path,
                    raw_input=address,
                )
        elif address.startswith("vanilla:/"):
            return CanonicalAddress(
                address_type=AddressType.VANILLA,
                identifier=None,
                relative_path=address[9:],
                raw_input=address,
            )
        elif address.startswith("utility:/"):
            return CanonicalAddress(
                address_type=AddressType.UTILITY,
                identifier=None,
                relative_path=address[9:],
                raw_input=address,
            )
        elif address.startswith("ck3raven:/"):
            return CanonicalAddress(
                address_type=AddressType.CK3RAVEN,
                identifier=None,
                relative_path=address[10:],
                raw_input=address,
            )
        elif address.startswith("wip:/"):
            return CanonicalAddress(
                address_type=AddressType.WIP,
                identifier=None,
                relative_path=address[5:],
                raw_input=address,
            )
        elif address.startswith("data:/"):
            return CanonicalAddress(
                address_type=AddressType.DATA,
                identifier=None,
                relative_path=address[6:],
                raw_input=address,
            )
        
        return CanonicalAddress(
            address_type=AddressType.UNKNOWN,
            identifier=None,
            relative_path="",
            raw_input=address,
        )
    
    def _translate_raw_path(self, raw_path: str) -> CanonicalAddress:
        """Translate a raw filesystem path to canonical address (mode-agnostic).
        
        Path classification is structural - determines which domain a path
        belongs to. This is the same regardless of agent mode.
        """
        from ck3lens.paths import RootCategory, ROOT_CK3RAVEN_DATA, WIP_DIR
        
        raw = Path(raw_path)
        
        # Handle relative paths: try to resolve against repo root first
        if not raw.is_absolute():
            repo_root = self._get_root(RootCategory.ROOT_REPO)
            if repo_root:
                candidate = repo_root / raw_path
                if candidate.exists():
                    return CanonicalAddress(
                        address_type=AddressType.CK3RAVEN,
                        identifier=None,
                        relative_path=str(raw).replace("\\", "/"),
                        raw_input=raw_path,
                    )
        
        path = raw.resolve()
        
        # Check all roots in priority order (more specific first)
        # This is mode-agnostic - any path can be classified
        
        # Check WIP first (most specific user workspace)
        # WIP is always ROOT_CK3RAVEN_DATA/wip - use paths.py constant
        try:
            rel = path.relative_to(WIP_DIR.resolve())
            return CanonicalAddress(
                address_type=AddressType.WIP,
                identifier=None,
                relative_path=str(rel).replace("\\", "/"),
                raw_input=raw_path,
            )
        except ValueError:
            pass
        
        # Check ck3raven source (ROOT_REPO)
        repo_root = self._get_root(RootCategory.ROOT_REPO)
        if repo_root:
            try:
                rel = path.relative_to(repo_root.resolve())
                return CanonicalAddress(
                    address_type=AddressType.CK3RAVEN,
                    identifier=None,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=raw_path,
                )
            except ValueError:
                pass
        
        # Check ck3raven data folder (~/.ck3raven/) - playsets, db, config
        # Use paths.py constant directly
        try:
            rel = path.relative_to(ROOT_CK3RAVEN_DATA.resolve())
            return CanonicalAddress(
                address_type=AddressType.DATA,
                identifier=None,
                relative_path=str(rel).replace("\\", "/"),
                raw_input=raw_path,
            )
        except ValueError:
            pass
        
        # Check vanilla (ROOT_GAME)
        game_root = self._get_root(RootCategory.ROOT_GAME)
        if game_root:
            try:
                rel = path.relative_to(game_root.resolve())
                return CanonicalAddress(
                    address_type=AddressType.VANILLA,
                    identifier=None,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=raw_path,
                )
            except ValueError:
                pass
        
        # Check mod paths from mods[]
        for mod_name, mod_path in self._mod_paths.items():
            try:
                rel = path.relative_to(mod_path.resolve())
                return CanonicalAddress(
                    address_type=AddressType.MOD,
                    identifier=mod_name,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=raw_path,
                )
            except ValueError:
                continue
        
        return CanonicalAddress(
            address_type=AddressType.UNKNOWN,
            identifier=None,
            relative_path="",
            raw_input=raw_path,
        )
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def normalize(self, path: str) -> str:
        """Normalize a filesystem path for comparison."""
        try:
            resolved = Path(path).expanduser().resolve()
            return str(resolved).lower().replace("\\", "/").rstrip("/")
        except Exception:
            return path.lower().replace("\\", "/").rstrip("/")


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def get_world_adapter(
    mode: str = "uninitiated",
    db: Optional["DBQueries"] = None,
    *,
    mods: Optional[list] = None,
) -> WorldAdapter:
    """
    Factory function to create a WorldAdapter.
    
    This is a convenience wrapper around WorldAdapter.create().
    All paths come from paths.py ROOT_* constants (config-driven).
    
    Args:
        mode: Agent mode ("ck3lens", "ck3raven-dev", or "uninitiated")
        db: DBQueries instance (optional)
        mods: List of mod objects (for ck3lens mode)
    """
    return WorldAdapter.create(
        mode=mode,
        db=db,
        mods=mods,
    )
