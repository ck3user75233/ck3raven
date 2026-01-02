"""
World Adapter - Capability-Gated Visibility Layer for CK3 Lens

This module provides the WorldAdapter interface and implementations that
determine what EXISTS and can be REFERENCED in each agent mode.

CAPABILITY-GATED ARCHITECTURE (December 2025):
- WorldAdapter is THE ONLY source of visibility and access handles
- WorldAdapter.db_handle() -> DbHandle (carries capability + visible_cvids)
- WorldAdapter.fs_handle() -> FsHandle (carries capability + allowed_roots)
- Call sites MUST use handles for all DB/FS operations
- Handles carry an unforgeable capability token (_CAP_TOKEN)
- DB/FS layers REFUSE calls without valid capability

CRITICAL: If WorldAdapter cannot be instantiated, tools MUST fail.
The underlying error is sufficient - no special wrapper needed.

BANNED CONCEPTS (December 2025 purge):
- lens (parameter or variable)
- PlaysetLens (class)
- cvids as parameter to DB methods (use handle instead)
- _derive_*cvid*() helpers
- _build_cv_filter() helpers
- _validate_visibility() helpers
- _lens_cache or any cache of lens/scope/cvids
- db_visibility() method (replaced by db_handle())
- VisibilityScope (replaced by DbHandle)
- _VISIBILITY_TOKEN (replaced by _CAP_TOKEN)

Address Scheme:
- mod:<mod_id>/<relative_path>     - Mod files (ck3lens mode)
- vanilla:/<relative_path>         - Vanilla game files
- utility:/logs/<file>             - CK3 utility files (logs, saves, etc.)
- ck3raven:/<relative_path>        - ck3raven source code (dev mode)
- wip:/<relative_path>             - WIP workspace files
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, FrozenSet, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .db_queries import DBQueries


# =============================================================================
# CAPABILITY TOKEN - UNFORGEABLE HANDLE MINTING
# =============================================================================

# Private token for capability validation - ONLY WorldAdapter can use this
# This is a module-private object() - impossible to forge from outside
_CAP_TOKEN = object()


class CapabilityError(Exception):
    """Raised when an operation is attempted without valid capability."""
    pass


# NOTE: WorldAdapterNotAvailableError REMOVED (December 2025)
# If WorldAdapter cannot be instantiated, the underlying error is sufficient.
# No special wrapper error is needed - the root cause should be clear.


# =============================================================================
# DB HANDLE - CAPABILITY-GATED DB ACCESS
# =============================================================================

@dataclass(frozen=True)
class DbHandle:
    """
    Capability-gated database access handle.
    
    This is THE ONLY legal way to access the database.
    Minted ONLY by WorldAdapter.db_handle() - cannot be fabricated.
    
    Fields:
    - visible_cvids: Frozenset of content_version_ids for queries.
                     None means NO RESTRICTION (full DB access).
    - purpose: Why this handle was requested (for audit/debug)
    - _cap: Internal capability token (must be _CAP_TOKEN)
    - _db: Reference to DBQueries for executing operations
    
    Usage:
        dbh = world.db_handle(purpose="search")
        results = dbh.search_symbols(query="brave")
    """
    visible_cvids: Optional[FrozenSet[int]]
    purpose: str
    _cap: object = field(repr=False, compare=False)
    _db: Any = field(repr=False, compare=False)
    
    @property
    def is_unrestricted(self) -> bool:
        """True if this handle allows querying the entire DB."""
        return self.visible_cvids is None
    
    def _validate_cap(self) -> None:
        """Validate capability token. Raises CapabilityError if invalid."""
        if self._cap is not _CAP_TOKEN:
            raise CapabilityError(
                "DbHandle was not minted by WorldAdapter. "
                "Use world.db_handle() to get a valid handle."
            )
    
    # -------------------------------------------------------------------------
    # DB Query Methods (wrapping internal DB methods)
    # These call _*_internal methods on DBQueries which require visible_cvids
    # -------------------------------------------------------------------------
    
    def search_symbols(self, query: str, **kwargs) -> list:
        """Search symbols with capability validation."""
        self._validate_cap()
        return self._db._search_symbols_internal(
            query, visible_cvids=self.visible_cvids, **kwargs
        )
    
    def search_files(self, query: str, **kwargs) -> list:
        """Search files with capability validation."""
        self._validate_cap()
        return self._db._search_files_internal(
            query, visible_cvids=self.visible_cvids, **kwargs
        )
    
    def search_content(self, query: str, **kwargs) -> list:
        """Search content with capability validation."""
        self._validate_cap()
        return self._db._search_content_internal(
            query, visible_cvids=self.visible_cvids, **kwargs
        )
    
    def get_file(self, relpath: str, **kwargs) -> Optional[dict]:
        """Get file by path with capability validation."""
        self._validate_cap()
        return self._db._get_file_internal(
            relpath, visible_cvids=self.visible_cvids, **kwargs
        )
    
    def get_symbol(self, name: str, symbol_type: str = None) -> Optional[dict]:
        """Get symbol by name with capability validation."""
        self._validate_cap()
        return self._db._get_symbol_internal(
            name, symbol_type, visible_cvids=self.visible_cvids
        )
    
    def get_symbols_by_file(self, file_id: int) -> list:
        """Get symbols in a file with capability validation."""
        self._validate_cap()
        return self._db._get_symbols_by_file_internal(
            file_id, visible_cvids=self.visible_cvids
        )
    
    def get_refs(self, symbol_name: str, **kwargs) -> list:
        """Get references to a symbol with capability validation."""
        self._validate_cap()
        return self._db._get_refs_internal(
            symbol_name, visible_cvids=self.visible_cvids, **kwargs
        )
    
    def confirm_not_exists(self, query: str, symbol_type: str = None) -> dict:
        """Exhaustive search to confirm something truly doesn't exist."""
        self._validate_cap()
        return self._db._confirm_not_exists_internal(
            query, symbol_type, visible_cvids=self.visible_cvids
        )
    
    def unified_search(self, query: str, **kwargs) -> dict:
        """Unified search across symbols and content with capability validation."""
        self._validate_cap()
        return self._db._unified_search_internal(
            query, visible_cvids=self.visible_cvids, **kwargs
        )
    
    def get_symbol_conflicts(self, **kwargs) -> dict:
        """Get symbol conflicts with capability validation."""
        self._validate_cap()
        return self._db._get_symbol_conflicts_internal(
            visible_cvids=self.visible_cvids, **kwargs
        )


# =============================================================================
# FS HANDLE - CAPABILITY-GATED FILESYSTEM ACCESS
# =============================================================================

@dataclass(frozen=True)
class FsHandle:
    """
    Capability-gated filesystem access handle.
    
    This is THE ONLY legal way to access the filesystem.
    Minted ONLY by WorldAdapter.fs_handle() - cannot be fabricated.
    
    Fields:
    - allowed_roots: Set of Path roots where operations are allowed.
    - purpose: Why this handle was requested (for audit/debug)
    - read_only: If True, only read operations are permitted
    - _cap: Internal capability token (must be _CAP_TOKEN)
    
    Usage:
        fsh = world.fs_handle(purpose="read_mod")
        content = fsh.read_text(path)
    """
    allowed_roots: FrozenSet[Path]
    purpose: str
    read_only: bool
    _cap: object = field(repr=False, compare=False)
    
    def _validate_cap(self) -> None:
        """Validate capability token. Raises CapabilityError if invalid."""
        if self._cap is not _CAP_TOKEN:
            raise CapabilityError(
                "FsHandle was not minted by WorldAdapter. "
                "Use world.fs_handle() to get a valid handle."
            )
    
    def _validate_path(self, path: Path) -> None:
        """Validate path is within allowed roots."""
        resolved = path.resolve()
        for root in self.allowed_roots:
            try:
                resolved.relative_to(root.resolve())
                return
            except ValueError:
                continue
        raise CapabilityError(
            f"Path {path} is outside allowed roots for this handle"
        )
    
    # -------------------------------------------------------------------------
    # FS Operation Methods
    # -------------------------------------------------------------------------
    
    def read_text(self, path: Path, encoding: str = "utf-8") -> str:
        """Read text file with capability validation."""
        self._validate_cap()
        self._validate_path(path)
        return path.read_text(encoding=encoding)
    
    def read_bytes(self, path: Path) -> bytes:
        """Read binary file with capability validation."""
        self._validate_cap()
        self._validate_path(path)
        return path.read_bytes()
    
    def write_text(self, path: Path, content: str, encoding: str = "utf-8") -> None:
        """Write text file with capability validation."""
        self._validate_cap()
        if self.read_only:
            raise CapabilityError("This FsHandle is read-only")
        self._validate_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
    
    def write_bytes(self, path: Path, content: bytes) -> None:
        """Write binary file with capability validation."""
        self._validate_cap()
        if self.read_only:
            raise CapabilityError("This FsHandle is read-only")
        self._validate_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    
    def exists(self, path: Path) -> bool:
        """Check if path exists with capability validation."""
        self._validate_cap()
        self._validate_path(path)
        return path.exists()
    
    def is_file(self, path: Path) -> bool:
        """Check if path is file with capability validation."""
        self._validate_cap()
        self._validate_path(path)
        return path.is_file()
    
    def is_dir(self, path: Path) -> bool:
        """Check if path is directory with capability validation."""
        self._validate_cap()
        self._validate_path(path)
        return path.is_dir()
    
    def iterdir(self, path: Path):
        """Iterate directory with capability validation."""
        self._validate_cap()
        self._validate_path(path)
        return path.iterdir()
    
    def glob(self, path: Path, pattern: str):
        """Glob pattern match with capability validation."""
        self._validate_cap()
        self._validate_path(path)
        return path.glob(pattern)


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
        else:
            return f"unknown:{self.raw_input}"
    
    def __str__(self) -> str:
        return self.canonical_form


class PathDomain(Enum):
    """
    Structural classification of a resolved path.
    
    This is for STRUCTURAL identification only, NOT permission decisions.
    Enforcement.py makes all allow/deny decisions.
    """
    WIP = "wip"
    LOCAL_MOD = "local_mod"
    WORKSHOP_MOD = "workshop_mod"
    VANILLA = "vanilla"
    CK3RAVEN = "ck3raven"
    UTILITY = "utility"
    LAUNCHER_REGISTRY = "launcher_registry"
    UNKNOWN = "unknown"


@dataclass
class EnforcementTarget:
    """
    The enforcement target derived from a canonical address.
    
    This is what gets passed to enforcement.py for allow/deny decisions.
    """
    mod_name: Optional[str]
    rel_path: Optional[str]
    canonical_address: str
    domain: PathDomain
    
    @classmethod
    def from_resolution(cls, result: "ResolutionResult") -> "EnforcementTarget":
        """Create enforcement target from resolution result."""
        if not result.found or not result.address:
            return cls(
                mod_name=None,
                rel_path=None,
                canonical_address=result.address.canonical_form if result.address else "",
                domain=PathDomain.UNKNOWN,
            )
        
        addr = result.address
        domain = result.domain or PathDomain.UNKNOWN
        
        if addr.address_type == AddressType.MOD:
            return cls(
                mod_name=addr.identifier,
                rel_path=addr.relative_path,
                canonical_address=addr.canonical_form,
                domain=domain,
            )
        else:
            return cls(
                mod_name=None,
                rel_path=None,
                canonical_address=addr.canonical_form,
                domain=domain,
            )


@dataclass
class ResolutionResult:
    """
    Result of resolving an address through the WorldAdapter.
    
    If found=False, the reference does not exist in this world.
    
    NO-ORACLE RULE: This result contains NO writability information.
    Writability is determined by enforcement.py at the write boundary.
    """
    found: bool
    address: Optional[CanonicalAddress] = None
    absolute_path: Optional[Path] = None
    domain: Optional[PathDomain] = None
    file_id: Optional[int] = None
    content_version_id: Optional[int] = None
    mod_name: Optional[str] = None
    error_message: Optional[str] = None
    
    @classmethod
    def not_found(cls, raw_input: str, reason: str = "Reference not found") -> "ResolutionResult":
        """Create a not-found result."""
        return cls(
            found=False,
            domain=PathDomain.UNKNOWN,
            error_message=f"{reason}: {raw_input}"
        )
    
    def get_enforcement_target(self) -> EnforcementTarget:
        """Get the enforcement target for this resolution."""
        return EnforcementTarget.from_resolution(self)


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
    """
    if path:
        address_to_resolve = path
    elif mod_name and rel_path:
        address_to_resolve = f"mod:{mod_name}/{rel_path}"
    elif mod_name:
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
    Single mode-aware WorldAdapter (December 2025 consolidation).
    
    This replaces the previous LensWorldAdapter, DevWorldAdapter, and
    UninitiatedWorldAdapter classes. Mode is checked at runtime.
    
    Modes:
    - ck3lens: Filtered to active playset, uses mod_name+rel_path addressing
    - ck3raven-dev: Raw path addressing, ck3raven source + WIP only
    - uninitiated: Limited access before mode is set
    
    WorldAdapter determines:
    1. What EXISTS and can be REFERENCED (resolve, is_visible)
    2. Provides capability-gated handles for DB/FS access
    
    WorldAdapter does NOT make permission decisions about what actions are allowed.
    That is enforcement.py's job.
    
    Handle Contract:
    - All DB queries MUST use DbHandle from db_handle()
    - All FS operations MUST use FsHandle from fs_handle()
    - Handles are the ONLY legal way to access DB/FS
    
    BANNED (December 2025): LensWorldAdapter, DevWorldAdapter, UninitiatedWorldAdapter
    These separate classes are now consolidated here with mode-aware behavior.
    """
    
    def __init__(
        self,
        mode: str,
        db: "DBQueries",
        *,
        # ck3lens mode parameters
        mods: Optional[list] = None,  # List of mod entries from session
        local_mods_folder: Optional[Path] = None,
        utility_roots: Optional[dict[str, Path]] = None,
        # Shared parameters
        vanilla_root: Optional[Path] = None,
        ck3raven_root: Optional[Path] = None,
        wip_root: Optional[Path] = None,
    ):
        """
        Initialize WorldAdapter for a specific mode.
        
        Args:
            mode: Agent mode ("ck3lens", "ck3raven-dev", or "uninitiated")
            db: DBQueries instance
            mods: List of mod entries (REQUIRED for ck3lens mode)
            local_mods_folder: Path to local mods folder (ck3lens)
            utility_roots: Dict of utility type to path (ck3lens)
            vanilla_root: Path to vanilla game folder
            ck3raven_root: Path to ck3raven source
            wip_root: Path to WIP workspace
        
        Raises:
            WorldAdapterNotAvailableError: If required parameters are missing
        """
        self._mode = mode
        self._db = db
        self._vanilla_root = vanilla_root
        self._ck3raven_root = ck3raven_root
        
        # Mode-specific initialization
        if mode == "ck3lens":
            if mods is None:
                raise WorldAdapterNotAvailableError(
                    "ck3lens mode requires mods[] from session"
                )
            self._init_lens_mode(mods, local_mods_folder, utility_roots, wip_root)
        elif mode == "ck3raven-dev":
            if ck3raven_root is None:
                raise WorldAdapterNotAvailableError(
                    "ck3raven-dev mode requires ck3raven_root"
                )
            self._init_dev_mode(wip_root)
        else:
            # Uninitiated mode - minimal setup
            self._init_uninitiated_mode()
    
    def _init_lens_mode(
        self,
        mods: list,
        local_mods_folder: Optional[Path],
        utility_roots: Optional[dict[str, Path]],
        wip_root: Optional[Path],
    ) -> None:
        """Initialize for ck3lens mode."""
        self._mods = mods
        self._local_mods_folder = local_mods_folder
        self._wip_root = wip_root
        self._utility_roots = utility_roots or {}
        
        # Build mod path lookup from mods[]
        self._mod_paths: dict[str, Path] = {}
        for mod in self._mods:
            if hasattr(mod, 'name') and hasattr(mod, 'path'):
                self._mod_paths[mod.name] = Path(mod.path) if isinstance(mod.path, str) else mod.path
        
        # Pre-compute visibility CVIDs from mods[] (immutable)
        self._visible_cvids: Optional[FrozenSet[int]] = frozenset(
            m.cvid for m in self._mods 
            if hasattr(m, 'cvid') and m.cvid is not None
        )
        if not self._visible_cvids:
            self._visible_cvids = None  # Treat empty as unrestricted
        
        # Pre-compute allowed FS roots
        self._read_roots: set[Path] = set()
        self._write_roots: set[Path] = set()
        
        if self._vanilla_root:
            self._read_roots.add(self._vanilla_root)
        if self._ck3raven_root:
            self._read_roots.add(self._ck3raven_root)
        if wip_root:
            self._read_roots.add(wip_root)
            self._write_roots.add(wip_root)
        for mod_path in self._mod_paths.values():
            self._read_roots.add(mod_path)
        for util_root in self._utility_roots.values():
            self._read_roots.add(util_root)
        
        # Write access - local mods only
        if local_mods_folder:
            for mod_path in self._mod_paths.values():
                try:
                    mod_path.resolve().relative_to(local_mods_folder.resolve())
                    self._write_roots.add(mod_path)
                except ValueError:
                    pass
    
    def _init_dev_mode(self, wip_root: Optional[Path]) -> None:
        """Initialize for ck3raven-dev mode."""
        # Dev mode does NOT use mods[] - they are not part of the execution model
        self._mods = []
        self._local_mods_folder = None
        self._utility_roots = {}
        self._mod_paths = {}
        self._visible_cvids = None  # UNRESTRICTED DB access
        
        # WIP is in the repo for dev mode
        self._wip_root = wip_root or (self._ck3raven_root / ".wip")
        
        # Pre-compute allowed FS roots - NO mod roots for dev mode
        self._read_roots = {self._ck3raven_root, self._wip_root}
        self._write_roots = {self._ck3raven_root, self._wip_root}
        
        if self._vanilla_root:
            self._read_roots.add(self._vanilla_root)
    
    def _init_uninitiated_mode(self) -> None:
        """Initialize for uninitiated mode (pre-initialization)."""
        self._mods = []
        self._local_mods_folder = None
        self._utility_roots = {}
        self._mod_paths = {}
        self._visible_cvids = None  # UNRESTRICTED during init
        self._wip_root = None
        
        # Limited FS access
        self._read_roots = set()
        self._write_roots = set()
        if self._ck3raven_root:
            self._read_roots.add(self._ck3raven_root)
    
    @property
    def mode(self) -> str:
        """Return the agent mode this adapter serves."""
        return self._mode
    
    # =========================================================================
    # HANDLE MINTING (Capability-gated access)
    # =========================================================================
    
    def db_handle(self, purpose: str = "db_read") -> DbHandle:
        """
        Get capability-gated DB access handle.
        
        This is THE ONLY legal way to obtain a DbHandle.
        
        For ck3lens: Returns handle limited to session.mods CVIDs.
        For ck3raven-dev: Returns handle with full DB access.
        For uninitiated: Returns handle with full DB access.
        """
        return DbHandle(
            visible_cvids=self._visible_cvids,
            purpose=purpose,
            _cap=_CAP_TOKEN,
            _db=self._db,
        )
    
    def fs_handle(self, purpose: str = "fs_read", read_only: bool = True) -> FsHandle:
        """
        Get capability-gated filesystem access handle.
        
        This is THE ONLY legal way to obtain a FsHandle.
        
        Read-only handles get access to all visible roots.
        Write handles get access only to writable roots (local mods + WIP for ck3lens,
        ck3raven source + WIP for ck3raven-dev).
        """
        if read_only:
            roots = frozenset(self._read_roots)
        else:
            roots = frozenset(self._write_roots)
        
        # Uninitiated mode is always read-only
        if self._mode == "uninitiated":
            read_only = True
        
        return FsHandle(
            allowed_roots=roots,
            purpose=purpose,
            read_only=read_only,
            _cap=_CAP_TOKEN,
        )
    
    # =========================================================================
    # RESOLUTION (mode-aware)
    # =========================================================================
    
    def resolve(self, path_or_address: str) -> ResolutionResult:
        """Resolve a path or address within this world (mode-aware)."""
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
        
        # Mode-specific resolution
        if self._mode == "ck3lens":
            return self._resolve_lens(address)
        elif self._mode == "ck3raven-dev":
            return self._resolve_dev(address)
        else:
            return ResolutionResult.not_found(path_or_address)
    
    def _resolve_lens(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve address in ck3lens mode (full playset visibility)."""
        if address.address_type == AddressType.MOD:
            return self._resolve_mod(address)
        elif address.address_type == AddressType.VANILLA:
            return self._resolve_vanilla(address)
        elif address.address_type == AddressType.UTILITY:
            return self._resolve_utility(address)
        elif address.address_type == AddressType.CK3RAVEN:
            return self._resolve_ck3raven(address)
        elif address.address_type == AddressType.WIP:
            return self._resolve_wip(address)
        else:
            return ResolutionResult.not_found(address.raw_input)
    
    def _resolve_dev(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve address in ck3raven-dev mode (source + WIP only)."""
        # Dev mode: only ck3raven source, WIP, and vanilla (read-only)
        if address.address_type == AddressType.CK3RAVEN:
            return self._resolve_ck3raven(address)
        elif address.address_type == AddressType.WIP:
            return self._resolve_wip(address)
        elif address.address_type == AddressType.VANILLA:
            return self._resolve_vanilla(address)
        else:
            # MOD and UTILITY not resolved in dev mode
            return ResolutionResult.not_found(address.raw_input)
    
    def is_visible(self, path_or_address: str) -> bool:
        """Quick visibility check."""
        result = self.resolve(path_or_address)
        return result.found
    
    # =========================================================================
    # ADDRESS PARSING (shared)
    # =========================================================================
    
    def _parse_or_translate(self, input_str: str) -> CanonicalAddress:
        """Parse canonical address or translate raw path."""
        input_str = input_str.strip()
        
        # Check for canonical address format
        if ":" in input_str and not input_str[1:3] == ":\\":  # Not a Windows path
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
        """Translate a raw filesystem path to canonical address (mode-aware)."""
        path = Path(raw_path).resolve()
        
        if self._mode == "ck3raven-dev":
            # Dev mode: prioritize ck3raven source
            return self._translate_raw_path_dev(path, raw_path)
        else:
            # Lens mode: full translation
            return self._translate_raw_path_lens(path, raw_path)
    
    def _translate_raw_path_lens(self, path: Path, raw_path: str) -> CanonicalAddress:
        """Translate raw path in ck3lens mode."""
        # Check vanilla
        if self._vanilla_root:
            try:
                rel = path.relative_to(self._vanilla_root.resolve())
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
        
        # Check WIP
        if self._wip_root:
            try:
                rel = path.relative_to(self._wip_root.resolve())
                return CanonicalAddress(
                    address_type=AddressType.WIP,
                    identifier=None,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=raw_path,
                )
            except ValueError:
                pass
        
        # Check ck3raven source
        if self._ck3raven_root:
            try:
                rel = path.relative_to(self._ck3raven_root.resolve())
                return CanonicalAddress(
                    address_type=AddressType.CK3RAVEN,
                    identifier=None,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=raw_path,
                )
            except ValueError:
                pass
        
        # Check utility roots
        for util_name, util_root in self._utility_roots.items():
            try:
                rel = path.relative_to(util_root.resolve())
                rel_str = str(rel).replace("\\", "/")
                return CanonicalAddress(
                    address_type=AddressType.UTILITY,
                    identifier=None,
                    relative_path=f"{util_name}/{rel_str}",
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
    
    def _translate_raw_path_dev(self, path: Path, raw_path: str) -> CanonicalAddress:
        """Translate raw path in ck3raven-dev mode."""
        # Check ck3raven source first (priority in dev mode)
        if self._ck3raven_root:
            try:
                rel = path.relative_to(self._ck3raven_root.resolve())
                return CanonicalAddress(
                    address_type=AddressType.CK3RAVEN,
                    identifier=None,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=raw_path,
                )
            except ValueError:
                pass
        
        # Check WIP
        if self._wip_root:
            try:
                rel = path.relative_to(self._wip_root.resolve())
                return CanonicalAddress(
                    address_type=AddressType.WIP,
                    identifier=None,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=raw_path,
                )
            except ValueError:
                pass
        
        # Check vanilla (read-only in dev mode)
        if self._vanilla_root:
            try:
                rel = path.relative_to(self._vanilla_root.resolve())
                return CanonicalAddress(
                    address_type=AddressType.VANILLA,
                    identifier=None,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=raw_path,
                )
            except ValueError:
                pass
        
        return CanonicalAddress(
            address_type=AddressType.UNKNOWN,
            identifier=None,
            relative_path="",
            raw_input=raw_path,
        )
    
    # =========================================================================
    # RESOLUTION HELPERS (shared)
    # =========================================================================
    
    def _resolve_mod(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve a mod address - check if in active playset."""
        mod_name = address.identifier
        
        if mod_name in self._mod_paths:
            mod_path = self._mod_paths[mod_name]
            abs_path = mod_path / address.relative_path
            
            # Determine domain (local vs workshop)
            domain = PathDomain.WORKSHOP_MOD
            if self._local_mods_folder:
                try:
                    mod_path.resolve().relative_to(self._local_mods_folder.resolve())
                    domain = PathDomain.LOCAL_MOD
                except ValueError:
                    pass
            
            return ResolutionResult(
                found=True,
                address=address,
                absolute_path=abs_path,
                domain=domain,
                mod_name=mod_name,
            )
        
        return ResolutionResult.not_found(
            address.raw_input,
            f"Mod '{mod_name}' not in active playset"
        )
    
    def _resolve_vanilla(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve a vanilla address."""
        if not self._vanilla_root:
            return ResolutionResult.not_found(address.raw_input, "Vanilla root not configured")
        
        abs_path = self._vanilla_root / address.relative_path
        return ResolutionResult(
            found=True,
            address=address,
            absolute_path=abs_path,
            domain=PathDomain.VANILLA,
            mod_name="vanilla",
        )
    
    def _resolve_utility(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve a utility address."""
        # Parse utility type from path: utility:/logs/file.log
        parts = address.relative_path.split("/", 1)
        if len(parts) >= 1:
            util_type = parts[0]
            if util_type in self._utility_roots:
                util_root = self._utility_roots[util_type]
                rel = parts[1] if len(parts) > 1 else ""
                abs_path = util_root / rel
                return ResolutionResult(
                    found=True,
                    address=address,
                    absolute_path=abs_path,
                    domain=PathDomain.UTILITY,
                )
        
        return ResolutionResult.not_found(address.raw_input, "Utility path not configured")
    
    def _resolve_ck3raven(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve a ck3raven source address."""
        if not self._ck3raven_root:
            return ResolutionResult.not_found(address.raw_input, "CK3Raven root not configured")
        
        abs_path = self._ck3raven_root / address.relative_path
        return ResolutionResult(
            found=True,
            address=address,
            absolute_path=abs_path,
            domain=PathDomain.CK3RAVEN,
        )
    
    def _resolve_wip(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve a WIP workspace address."""
        if not self._wip_root:
            return ResolutionResult.not_found(address.raw_input, "WIP root not configured")
        
        abs_path = self._wip_root / address.relative_path
        return ResolutionResult(
            found=True,
            address=address,
            absolute_path=abs_path,
            domain=PathDomain.WIP,
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
    
    def db_visibility(self, purpose: str = "db_read"):
        """
        DEPRECATED: Returns a legacy visibility wrapper for backward compatibility.
        
        New code MUST use db_handle() instead.
        """
        dbh = self.db_handle(purpose=purpose)
        
        class _LegacyVisibility:
            def __init__(self, cvids):
                self.visible_cvids = cvids
        
        return _LegacyVisibility(dbh.visible_cvids)


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
    
    This is a convenience wrapper around WorldAdapter() constructor.
    
    Args:
        mode: Agent mode ("ck3lens", "ck3raven-dev", or "uninitiated")
        db: DBQueries instance
        mods: List of mod entries (required for ck3lens mode)
        local_mods_folder: Path to local mods folder (for ck3lens)
        vanilla_root: Path to vanilla game folder
        ck3raven_root: Path to ck3raven source
        wip_root: Path to WIP workspace
        utility_roots: Dict of utility type to path (logs, saves, etc.)
    
    Returns:
        WorldAdapter configured for the specified mode
    
    Raises:
        WorldAdapterNotAvailableError: If required parameters are missing
    """
    return WorldAdapter(
        mode=mode,
        db=db,
        mods=mods,
        local_mods_folder=local_mods_folder,
        vanilla_root=vanilla_root,
        ck3raven_root=ck3raven_root,
        wip_root=wip_root,
        utility_roots=utility_roots,
    )


# =============================================================================
# BANNED ALIASES (December 2025 - DELETED)
# =============================================================================
# The following classes have been DELETED as per canonical architecture:
# - LensWorldAdapter (use WorldAdapter(mode="ck3lens", ...))
# - DevWorldAdapter (use WorldAdapter(mode="ck3raven-dev", ...))  
# - UninitiatedWorldAdapter (use WorldAdapter(mode="uninitiated", ...))
#
# See CANONICAL_ARCHITECTURE.md Section 10 for details.
