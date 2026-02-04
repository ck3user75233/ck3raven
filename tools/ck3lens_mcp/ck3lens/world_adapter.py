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
- self._vanilla_root, self._ck3raven_root, self._wip_root (parallel constructs)
- self._utility_roots (parallel construct)
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
    
    The root_category is used by enforcement.py to check capability matrix.
    This is STRUCTURAL classification only - enforcement makes all decisions.
    """
    found: bool
    address: Optional[CanonicalAddress] = None
    absolute_path: Optional[Path] = None
    root_category: Optional["RootCategory"] = None  # From capability_matrix
    file_id: Optional[int] = None
    content_version_id: Optional[int] = None
    mod_name: Optional[str] = None
    error_message: Optional[str] = None
    
    @classmethod
    def not_found(cls, raw_input: str, reason: str = "Reference not found") -> "ResolutionResult":
        """Create a not-found result."""
        from ck3lens.policy.capability_matrix import RootCategory
        return cls(
            found=False,
            root_category=RootCategory.ROOT_OTHER,
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
    - ROOT_WIP: Scratch/experimental workspace
    - ROOT_USER_DOCS: User-authored mod content (local mods)
    - ROOT_STEAM: Steam Workshop content
    - ROOT_UTILITIES: Runtime logs & diagnostics
    - ROOT_CK3RAVEN_DATA: ~/.ck3raven/ (playsets, db, config)
    
    WorldAdapter determines:
    1. What EXISTS and can be REFERENCED (resolve, is_visible)
    2. What RootCategory a path belongs to (classify_path)
    
    WorldAdapter does NOT make permission decisions - enforcement.py does that
    using the RootCategory returned by classify_path.
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
        from ck3lens.policy.capability_matrix import RootCategory
        
        self._mode = mode
        self._db = db
        self._roots: dict[RootCategory, list[Path]] = roots or {}
        self._mod_paths: dict[str, Path] = mod_paths or {}
        self._visible_cvids = visible_cvids
    
    @classmethod
    def create(
        cls,
        mode: str,
        db: Optional["DBQueries"] = None,
        *,
        # Legacy parameters for backward compatibility during migration
        mods: Optional[list] = None,
        local_mods_folder: Optional[Path] = None,
        utility_roots: Optional[dict[str, Path]] = None,
        vanilla_root: Optional[Path] = None,
        ck3raven_root: Optional[Path] = None,
        wip_root: Optional[Path] = None,
    ) -> "WorldAdapter":
        """
        Factory method that converts legacy parameters to canonical roots.
        
        This is the migration path - callers use legacy parameter names,
        this method converts to canonical RootCategory structure.
        """
        from ck3lens.policy.capability_matrix import RootCategory
        
        roots: dict[RootCategory, list[Path]] = {}
        mod_paths: dict[str, Path] = {}
        visible_cvids: Optional[FrozenSet[int]] = None
        
        # ROOT_REPO
        if ck3raven_root:
            roots[RootCategory.ROOT_REPO] = [ck3raven_root]
        
        # ROOT_GAME
        if vanilla_root:
            roots[RootCategory.ROOT_GAME] = [vanilla_root]
        
        # ROOT_WIP
        if wip_root:
            roots[RootCategory.ROOT_WIP] = [wip_root]
        elif mode == "ck3raven-dev" and ck3raven_root:
            roots[RootCategory.ROOT_WIP] = [ck3raven_root / ".wip"]
        
        # ROOT_UTILITIES
        if utility_roots:
            roots[RootCategory.ROOT_UTILITIES] = list(utility_roots.values())
        
        # ROOT_CK3RAVEN_DATA
        ck3raven_data = Path.home() / ".ck3raven"
        roots[RootCategory.ROOT_CK3RAVEN_DATA] = [ck3raven_data]
        
        # Process mods - classify as ROOT_USER_DOCS or ROOT_STEAM
        if mods:
            user_docs_paths: list[Path] = []
            steam_paths: list[Path] = []
            
            for mod in mods:
                if hasattr(mod, 'name') and hasattr(mod, 'path'):
                    mod_path = Path(mod.path) if isinstance(mod.path, str) else mod.path
                    mod_paths[mod.name] = mod_path
                    
                    # Classify by containment in local_mods_folder
                    if local_mods_folder:
                        try:
                            mod_path.resolve().relative_to(local_mods_folder.resolve())
                            user_docs_paths.append(mod_path)
                        except ValueError:
                            steam_paths.append(mod_path)
                    else:
                        steam_paths.append(mod_path)
            
            if user_docs_paths:
                roots[RootCategory.ROOT_USER_DOCS] = user_docs_paths
            if steam_paths:
                roots[RootCategory.ROOT_STEAM] = steam_paths
            
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
        from ck3lens.policy.capability_matrix import RootCategory
        
        try:
            resolved = absolute_path.resolve()
        except (OSError, ValueError):
            return RootCategory.ROOT_OTHER
        
        # Check roots in priority order (more specific first)
        priority_order = [
            RootCategory.ROOT_WIP,          # Most specific
            RootCategory.ROOT_REPO,
            RootCategory.ROOT_USER_DOCS,
            RootCategory.ROOT_GAME,
            RootCategory.ROOT_STEAM,
            RootCategory.ROOT_UTILITIES,
            RootCategory.ROOT_CK3RAVEN_DATA,
        ]
        
        for category in priority_order:
            if category in self._roots:
                for root_path in self._roots[category]:
                    try:
                        resolved.relative_to(root_path.resolve())
                        return category
                    except ValueError:
                        pass
        
        return RootCategory.ROOT_OTHER
    
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
        """
        from ck3lens.policy.capability_matrix import RootCategory
        
        abs_path: Optional[Path] = None
        root_category: Optional[RootCategory] = None
        mod_name: Optional[str] = None
        
        if address.address_type == AddressType.MOD:
            # Mod addresses use _mod_paths lookup
            mod_id = address.identifier
            if mod_id in self._mod_paths:
                abs_path = self._mod_paths[mod_id] / address.relative_path
                root_category = self.classify_path(abs_path)
                mod_name = mod_id
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
            root = self._get_root(RootCategory.ROOT_WIP)
            if root:
                abs_path = root / address.relative_path
                root_category = RootCategory.ROOT_WIP
        
        elif address.address_type == AddressType.CK3RAVEN:
            root = self._get_root(RootCategory.ROOT_REPO)
            if root:
                abs_path = root / address.relative_path
                root_category = RootCategory.ROOT_REPO
        
        elif address.address_type == AddressType.DATA:
            root = self._get_root(RootCategory.ROOT_CK3RAVEN_DATA)
            if root:
                abs_path = root / address.relative_path
                root_category = RootCategory.ROOT_CK3RAVEN_DATA
        
        elif address.address_type == AddressType.UTILITY:
            utility_paths = self._roots.get(RootCategory.ROOT_UTILITIES, [])
            if utility_paths:
                abs_path = utility_paths[0] / address.relative_path
                root_category = RootCategory.ROOT_UTILITIES
        
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
        from ck3lens.policy.capability_matrix import RootCategory
        
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
        wip_root = self._get_root(RootCategory.ROOT_WIP)
        if wip_root:
            try:
                rel = path.relative_to(wip_root.resolve())
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
        data_root = self._get_root(RootCategory.ROOT_CK3RAVEN_DATA)
        if data_root:
            try:
                rel = path.relative_to(data_root.resolve())
                return CanonicalAddress(
                    address_type=AddressType.DATA,
                    identifier=None,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=raw_path,
                )
            except ValueError:
                pass
        
        # Check vanilla (ROOT_GAME)
        vanilla_root = self._get_root(RootCategory.ROOT_GAME)
        if vanilla_root:
            try:
                rel = path.relative_to(vanilla_root.resolve())
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
        
        # Check utility roots (ROOT_UTILITIES) - check each path
        utility_paths = self._roots.get(RootCategory.ROOT_UTILITIES, [])
        for util_root in utility_paths:
            try:
                rel = path.relative_to(util_root.resolve())
                rel_str = str(rel).replace("\\", "/")
                return CanonicalAddress(
                    address_type=AddressType.UTILITY,
                    identifier=None,
                    relative_path=rel_str,
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
# FACTORY FUNCTION (for backward compatibility)
# =============================================================================

def get_world_adapter(
    mode: str,
    db: "DBQueries",
    *,
    mods: Optional[list] = None,
    local_mods_folder: Optional[Path] = None,
    vanilla_root: Optional[Path] = None,
    ck3raven_root: Optional[Path] = None,
    wip_root: Optional[Path] = None,
    utility_roots: Optional[dict[str, Path]] = None,
) -> WorldAdapter:
    """
    Factory function to create a WorldAdapter.
    
    This is a convenience wrapper around WorldAdapter.create().
    """
    return WorldAdapter.create(
        mode=mode,
        db=db,
        mods=mods,
        local_mods_folder=local_mods_folder,
        vanilla_root=vanilla_root,
        ck3raven_root=ck3raven_root,
        wip_root=wip_root,
        utility_roots=utility_roots,
    )
