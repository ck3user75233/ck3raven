"""
World Adapter - Path Resolution and Classification for CK3 Lens

This module provides the WorldAdapter interface that:
1. RESOLVES inputs to absolute paths (mod:Name/path -> C:/mods/Name/path)
2. CLASSIFIES absolute paths to RootCategory by containment

WorldAdapter does NOT make permission decisions - enforcement.py does that
using the RootCategory returned by classify_path.

Address Scheme (maps directly to RootCategory):
- mod:<mod_id>/<relative_path>     - Mod files → ROOT_STEAM or ROOT_USER_DOCS
- vanilla:/<relative_path>         - Vanilla game files → ROOT_GAME
- ck3raven:/<relative_path>        - ck3raven source code → ROOT_REPO
- wip:/<relative_path>             - WIP workspace files → ROOT_CK3RAVEN_DATA/wip
- data:/<relative_path>            - CK3Raven data files → ROOT_CK3RAVEN_DATA

BANNED CONCEPTS:
- AddressType enum (February 2026) — use RootCategory directly
- CanonicalAddress dataclass (February 2026) — replaced by _ParsedRef (internal)
- utility:/ scheme (February 2026) — ROOT_UTILITIES removed
- DbHandle, FsHandle (dead code, never called)
- _CAP_TOKEN (dead code)
- CapabilityError (dead code)
- self._vanilla_root, self._ck3raven_root, self._wip_root (use paths.py constants)
- vanilla_root, ck3raven_root, wip_root parameters (use paths.py constants)
- world_router module (all routing is via WorldAdapter.resolve())
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .db_queries import DBQueries


# =============================================================================
# INTERNAL PARSED REFERENCE (private intermediate between parsing and resolution)
# =============================================================================

@dataclass
class _ParsedRef:
    """
    Internal: result of parsing a canonical address string or raw path.
    
    This is the intermediate between input parsing and path resolution.
    Uses RootCategory directly — no parallel classification system.
    
    For mod: addresses, root_category is None (determined during resolution
    when the mod's actual filesystem path is looked up and classified).
    For unresolvable inputs, root_category is ROOT_EXTERNAL.
    """
    root_category: Optional["RootCategory"]  # None = mod reference (needs path lookup)
    mod_name: Optional[str]  # Non-None for mod: addresses
    relative_path: str
    raw_input: str
    subdirectory: Optional[str] = None  # Pre-known for wip:, data: schemes


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
    ):
        """
        Initialize WorldAdapter with canonical root paths.
        
        Args:
            mode: Agent mode ("ck3lens", "ck3raven-dev", or "uninitiated")
            db: DBQueries instance (optional)
            roots: Dict mapping RootCategory to list of paths for that domain
            mod_paths: Dict mapping mod names to their filesystem paths
        """
        from ck3lens.paths import RootCategory
        
        self._mode = mode
        self._db = db
        self._roots: dict[RootCategory, list[Path]] = roots or {}
        self._mod_paths: dict[str, Path] = mod_paths or {}
    
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
        
        return cls(
            mode=mode,
            db=db,
            roots=roots,
            mod_paths=mod_paths,
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
        
        ref = self._parse_or_translate(path_or_address)
        
        from ck3lens.paths import RootCategory
        if ref.root_category == RootCategory.ROOT_EXTERNAL and ref.mod_name is None:
            return ResolutionResult.not_found(
                path_or_address,
                "Could not resolve reference"
            )
        
        return self._resolve_to_absolute(ref)
    
    def _resolve_to_absolute(self, ref: _ParsedRef) -> ResolutionResult:
        """Resolve _ParsedRef to absolute path.
        
        Dispatches on ref.root_category (or mod_name for mod references).
        
        IMPORTANT: This method MUST set subdirectory and relative_path fields
        for proper capability matrix lookup. The capability matrix uses:
        - subdirectory: first path component under root (e.g., "mod", "wip")
        - relative_path: full path from root (for subfolders_writable check)
        """
        from ck3lens.paths import RootCategory, ROOT_USER_DOCS, ROOT_CK3RAVEN_DATA
        
        abs_path: Optional[Path] = None
        root_category: Optional[RootCategory] = None
        mod_name: Optional[str] = None
        subdirectory: Optional[str] = ref.subdirectory
        relative_path_for_cap: Optional[str] = None
        
        if ref.mod_name is not None:
            # Mod reference: look up path from _mod_paths
            mod_id = ref.mod_name
            if mod_id in self._mod_paths:
                mod_path = self._mod_paths[mod_id]
                abs_path = mod_path / ref.relative_path
                root_category = self.classify_path(abs_path)
                mod_name = mod_id
                
                if root_category == RootCategory.ROOT_USER_DOCS and ROOT_USER_DOCS:
                    subdirectory = "mod"
                    try:
                        rel_from_docs = abs_path.resolve().relative_to(ROOT_USER_DOCS.resolve())
                        relative_path_for_cap = str(rel_from_docs).replace("\\", "/")
                    except ValueError:
                        relative_path_for_cap = f"mod/{mod_id}/{ref.relative_path}"
            else:
                return ResolutionResult.not_found(
                    ref.raw_input,
                    f"Mod '{mod_id}' not in active playset"
                )
        
        elif ref.root_category == RootCategory.ROOT_GAME:
            root = self._get_root(RootCategory.ROOT_GAME)
            if root:
                abs_path = root / ref.relative_path
                root_category = RootCategory.ROOT_GAME
                mod_name = "vanilla"
        
        elif ref.root_category == RootCategory.ROOT_CK3RAVEN_DATA:
            # Could be wip: or data: — subdirectory distinguishes them
            if ref.subdirectory == "wip":
                abs_path = ROOT_CK3RAVEN_DATA / "wip" / ref.relative_path
                relative_path_for_cap = f"wip/{ref.relative_path}"
            else:
                abs_path = ROOT_CK3RAVEN_DATA / ref.relative_path
                parts = ref.relative_path.replace("\\", "/").strip("/").split("/")
                if parts and parts[0]:
                    subdirectory = parts[0]
                    relative_path_for_cap = ref.relative_path.replace("\\", "/")
            root_category = RootCategory.ROOT_CK3RAVEN_DATA
        
        elif ref.root_category == RootCategory.ROOT_REPO:
            root = self._get_root(RootCategory.ROOT_REPO)
            if root:
                abs_path = root / ref.relative_path
                root_category = RootCategory.ROOT_REPO
        
        if abs_path is None:
            return ResolutionResult.not_found(
                ref.raw_input,
                f"No root configured for {ref.root_category.name if ref.root_category else 'unknown'}"
            )
        
        return ResolutionResult(
            found=True,
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
    
    def _parse_or_translate(self, input_str: str) -> _ParsedRef:
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
    
    def _parse_canonical(self, address: str) -> _ParsedRef:
        """Parse a canonical address string into _ParsedRef."""
        from ck3lens.paths import RootCategory
        
        if address.startswith("mod:"):
            rest = address[4:]
            if "/" in rest:
                mod_id, rel_path = rest.split("/", 1)
                return _ParsedRef(
                    root_category=None,  # Determined during resolution via classify_path
                    mod_name=mod_id,
                    relative_path=rel_path,
                    raw_input=address,
                )
        elif address.startswith("vanilla:/"):
            return _ParsedRef(
                root_category=RootCategory.ROOT_GAME,
                mod_name=None,
                relative_path=address[9:],
                raw_input=address,
            )
        elif address.startswith("ck3raven:/"):
            return _ParsedRef(
                root_category=RootCategory.ROOT_REPO,
                mod_name=None,
                relative_path=address[10:],
                raw_input=address,
            )
        elif address.startswith("wip:/"):
            return _ParsedRef(
                root_category=RootCategory.ROOT_CK3RAVEN_DATA,
                mod_name=None,
                relative_path=address[5:],
                raw_input=address,
                subdirectory="wip",
            )
        elif address.startswith("data:/"):
            return _ParsedRef(
                root_category=RootCategory.ROOT_CK3RAVEN_DATA,
                mod_name=None,
                relative_path=address[6:],
                raw_input=address,
            )
        elif address.startswith("utility:/"):
            # utility: scheme is deprecated (ROOT_UTILITIES removed)
            return _ParsedRef(
                root_category=RootCategory.ROOT_EXTERNAL,
                mod_name=None,
                relative_path="",
                raw_input=address,
            )
        
        # Unrecognized scheme
        return _ParsedRef(
            root_category=RootCategory.ROOT_EXTERNAL,
            mod_name=None,
            relative_path="",
            raw_input=address,
        )
    
    def _translate_raw_path(self, raw_path: str) -> _ParsedRef:
        """Translate a raw filesystem path to _ParsedRef (mode-agnostic).
        
        Path classification is structural — determines which RootCategory a path
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
                    return _ParsedRef(
                        root_category=RootCategory.ROOT_REPO,
                        mod_name=None,
                        relative_path=str(raw).replace("\\", "/"),
                        raw_input=raw_path,
                    )
        
        path = raw.resolve()
        
        # Check all roots in priority order (more specific first)
        
        # Check WIP first (most specific — subdirectory of ROOT_CK3RAVEN_DATA)
        try:
            rel = path.relative_to(WIP_DIR.resolve())
            return _ParsedRef(
                root_category=RootCategory.ROOT_CK3RAVEN_DATA,
                mod_name=None,
                relative_path=str(rel).replace("\\", "/"),
                raw_input=raw_path,
                subdirectory="wip",
            )
        except ValueError:
            pass
        
        # Check ck3raven source (ROOT_REPO)
        repo_root = self._get_root(RootCategory.ROOT_REPO)
        if repo_root:
            try:
                rel = path.relative_to(repo_root.resolve())
                return _ParsedRef(
                    root_category=RootCategory.ROOT_REPO,
                    mod_name=None,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=raw_path,
                )
            except ValueError:
                pass
        
        # Check ck3raven data folder (~/.ck3raven/)
        try:
            rel = path.relative_to(ROOT_CK3RAVEN_DATA.resolve())
            return _ParsedRef(
                root_category=RootCategory.ROOT_CK3RAVEN_DATA,
                mod_name=None,
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
                return _ParsedRef(
                    root_category=RootCategory.ROOT_GAME,
                    mod_name=None,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=raw_path,
                )
            except ValueError:
                pass
        
        # Check mod paths from mods[]
        for mod_name, mod_path in self._mod_paths.items():
            try:
                rel = path.relative_to(mod_path.resolve())
                return _ParsedRef(
                    root_category=None,  # Will be classified during resolution
                    mod_name=mod_name,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=raw_path,
                )
            except ValueError:
                continue
        
        return _ParsedRef(
            root_category=RootCategory.ROOT_EXTERNAL,
            mod_name=None,
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
