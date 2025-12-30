"""
World Adapter - Visibility Layer for CK3 Lens

This module provides the WorldAdapter interface and implementations that
determine what EXISTS and can be REFERENCED in each agent mode.

Architecture (NO-ORACLE REFACTOR - December 2025):
- WorldAdapter answers: "Does this reference EXIST in my world?"
- WorldAdapter returns FOUND or NOT_FOUND
- WorldAdapter does NOT determine writability (that's enforcement.py)
- Policy (enforcement.py) decides: "Is this operation ALLOWED?"

These are orthogonal layers:
- LensWorld: visibility (what exists)
- Enforcement: permission (what actions are permitted)

Two implementations:
- LensWorldAdapter: For ck3lens mode - visibility filtered to active playset
- DevWorldAdapter: For ck3raven-dev mode - full visibility to ck3raven source

Address Scheme:
- Agents may provide raw paths OR canonical addresses
- Raw paths are translated to canonical forms internally
- If translation fails → NOT_FOUND (not DENY)

Canonical address forms:
- mod:<mod_id>/<relative_path>     - Mod files
- vanilla:/<relative_path>         - Vanilla game files
- utility:/logs/<file>             - CK3 utility files (logs, saves, etc.)
- ck3raven:/<relative_path>        - ck3raven source code
- wip:/<relative_path>             - WIP workspace files
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from .db_queries import PlaysetLens, DBQueries


# =============================================================================
# CANONICAL PATH NORMALIZATION (shared utility)
# =============================================================================

def normalize_path_for_comparison(path: str) -> str:
    """
    Normalize a filesystem path for comparison purposes.
    
    This is the CANONICAL utility for path normalization across the codebase.
    Use this when you need to compare paths (e.g., database key matching).
    
    Normalization:
    - Resolves to absolute path
    - Lowercases (case-insensitive comparison on Windows)
    - Converts backslashes to forward slashes
    
    Args:
        path: Raw filesystem path
        
    Returns:
        Normalized path string suitable for comparison
    """
    return str(Path(path).resolve()).lower().replace("\\", "/")


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
    Enforcement.py makes all allow/deny decisions based on the enforcement target.
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
    Constructed from ResolutionResult by normalize_path_input().
    
    MCP tools should use this instead of building their own path strings.
    """
    mod_name: Optional[str]  # For LOCAL_MOD domain
    rel_path: Optional[str]  # For LOCAL_MOD domain
    canonical_address: str   # Full canonical form for non-mod domains
    domain: PathDomain       # Structural classification
    
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
    Policy is NEVER consulted for not-found references.
    
    NO-ORACLE RULE: This result contains NO writability information.
    Writability is determined by enforcement.py at the write boundary.
    
    Fields:
    - found: Whether the reference exists in this world
    - address: The canonical address (sole identity)
    - absolute_path: For filesystem execution only
    - domain: Structural classification (NOT for permission decisions)
    - file_id/content_version_id: For database operations
    - mod_name: Mod identifier if applicable
    - error_message: Reason for not_found
    - ui_hint_potentially_editable: Display only, NEVER control flow
    """
    found: bool
    address: Optional[CanonicalAddress] = None
    absolute_path: Optional[Path] = None  # For filesystem execution ONLY
    domain: Optional[PathDomain] = None   # Structural classification
    file_id: Optional[int] = None  # For database operations
    content_version_id: Optional[int] = None
    mod_name: Optional[str] = None
    error_message: Optional[str] = None
    
    # UI hint only - NOT for enforcement decisions
    # This is purely for display purposes (e.g., showing a lock icon)
    ui_hint_potentially_editable: bool = False
    
    @classmethod
    def not_found(cls, raw_input: str, reason: str = "Reference not found") -> "ResolutionResult":
        """Create a not-found result."""
        return cls(
            found=False,
            domain=PathDomain.UNKNOWN,
            error_message=f"{reason}: {raw_input}"
        )
    
    def get_enforcement_target(self) -> EnforcementTarget:
        """
        Get the enforcement target for this resolution.
        
        This is the ONLY way to derive an enforcement target from a resolution.
        MCP tools should call this instead of building their own path strings.
        """
        return EnforcementTarget.from_resolution(self)


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
    It handles all input forms and returns a unified ResolutionResult.
    
    Input forms (mutually exclusive):
    1. path: Raw filesystem path (C:/...) or canonical address (mod:xyz/...)
    2. mod_name + rel_path: Explicit mod addressing
    
    Returns:
        ResolutionResult with:
        - found: Whether the reference exists in this world
        - address: The canonical address (sole identity)
        - absolute_path: For filesystem execution ONLY
        - domain: Structural classification
        - get_enforcement_target(): Method to get EnforcementTarget
    
    Usage in MCP tools:
        result = normalize_path_input(world, path=path, mod_name=mod_name, rel_path=rel_path)
        if not result.found:
            return {"error": result.error_message}
        
        # Get enforcement target (for enforcement.py)
        target = result.get_enforcement_target()
        
        # Get execution path (for filesystem operations)
        abs_path = result.absolute_path
    
    This utility:
    - Parses user input
    - Calls WorldAdapter.resolve() exactly once
    - Exposes enforcement targets via get_enforcement_target()
    - Exposes execution paths via absolute_path
    - Does NOT perform permission checks or eligibility logic
    """
    # Determine input to resolve
    if path:
        # User provided a raw path or canonical address
        address_to_resolve = path
    elif mod_name and rel_path:
        # User provided mod_name + rel_path - convert to canonical form
        address_to_resolve = f"mod:{mod_name}/{rel_path}"
    elif mod_name:
        # Just mod_name without rel_path - use mod root
        address_to_resolve = f"mod:{mod_name}/"
    else:
        # No valid input
        return ResolutionResult.not_found(
            "<no input>",
            "Either 'path' or 'mod_name'+'rel_path' required"
        )
    
    # Call WorldAdapter.resolve() exactly once
    return world.resolve(address_to_resolve)


class WorldAdapter(ABC):
    """
    Abstract base for world visibility adapters.
    
    WorldAdapter determines what EXISTS and can be REFERENCED.
    It does NOT make permission decisions about what actions are allowed.
    
    All MCP tools should:
    1. Get the appropriate WorldAdapter from WorldRouter
    2. Resolve references through the adapter
    3. If found=True and mutation needed → call enforcement.py
    4. Enforcement decides ALLOW/DENY
    
    NO early denial based on resolution results.
    """
    
    @abstractmethod
    def resolve(self, path_or_address: str) -> ResolutionResult:
        """
        Resolve a path or address to a canonical reference.
        
        Args:
            path_or_address: Raw path (C:/...) or canonical address (mod:xyz/...)
        
        Returns:
            ResolutionResult - found=True if reference exists in this world
        """
        pass
    
    @abstractmethod
    def is_visible(self, path_or_address: str) -> bool:
        """Quick check if a reference is visible in this world."""
        pass
    
    @abstractmethod
    def get_search_scope(self) -> Set[int]:
        """
        Get content_version_ids to search.
        
        For database queries, this defines the scope.
        """
        pass
    
    @property
    @abstractmethod
    def mode(self) -> str:
        """Return the agent mode this adapter serves."""
        pass


class LensWorldAdapter(WorldAdapter):
    """
    WorldAdapter for ck3lens mode.
    
    Visibility is filtered to:
    - Active playset (vanilla + mods in load order)
    - CK3 utility files (logs, saves, crash dumps) - read-only
    - ck3raven source - read-only for bug reports
    - WIP workspace - full access for helper scripts
    
    Things NOT visible:
    - Inactive mods
    - Arbitrary filesystem
    - Other system files
    """
    
    def __init__(
        self,
        lens: "PlaysetLens",
        db: "DBQueries",
        local_mods_folder: Optional[Path] = None,
        vanilla_root: Optional[Path] = None,
        ck3raven_root: Optional[Path] = None,
        wip_root: Optional[Path] = None,
        utility_roots: Optional[dict[str, Path]] = None,
        mods: Optional[list] = None,  # List of mod entries from session
    ):
        self._lens = lens
        self._db = db
        self._local_mods_folder = local_mods_folder
        self._vanilla_root = vanilla_root
        self._ck3raven_root = ck3raven_root
        self._wip_root = wip_root
        self._utility_roots = utility_roots or {}
        self._mods = mods or []
        
        # Build mod path lookup from mods[]
        self._mod_paths: dict[str, Path] = {}
        for mod in self._mods:
            if hasattr(mod, 'name') and hasattr(mod, 'path'):
                self._mod_paths[mod.name] = Path(mod.path) if isinstance(mod.path, str) else mod.path
    
    @property
    def mode(self) -> str:
        return "ck3lens"
    
    @property
    def lens(self) -> "PlaysetLens":
        """Get the underlying PlaysetLens for direct DB query filtering."""
        return self._lens
    
    def get_search_scope(self) -> Set[int]:
        """Return content_version_ids for the active playset."""
        return self._lens.all_cv_ids
    
    def resolve(self, path_or_address: str) -> ResolutionResult:
        """
        Resolve a path or address within the lens world.
        
        Translation order:
        1. If canonical address (mod:, vanilla:, etc.) - parse directly
        2. If raw path - attempt to translate to canonical form
        3. Check if result is within lens scope
        4. Return NOT_FOUND if outside scope
        """
        # Parse canonical address or translate raw path
        address = self._parse_or_translate(path_or_address)
        
        if address.address_type == AddressType.UNKNOWN:
            return ResolutionResult.not_found(
                path_or_address,
                "Could not resolve reference"
            )
        
        # Check visibility based on address type
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
            return ResolutionResult.not_found(path_or_address)
    
    def is_visible(self, path_or_address: str) -> bool:
        """Quick visibility check."""
        result = self.resolve(path_or_address)
        return result.found
    
    def _parse_or_translate(self, input_str: str) -> CanonicalAddress:
        """Parse canonical address or translate raw path."""
        input_str = input_str.strip()
        
        # Check for canonical address format
        if ":" in input_str and not input_str[1:3] == ":\\":  # Not a Windows path
            return self._parse_canonical(input_str)
        
        # Raw path - translate based on location
        return self._translate_raw_path(input_str)
    
    def _parse_canonical(self, address: str) -> CanonicalAddress:
        """Parse a canonical address string."""
        if address.startswith("mod:"):
            # mod:<mod_id>/<path>
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
        """Translate a raw filesystem path to canonical address."""
        path = Path(raw_path).resolve()
        
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
        
        # Unknown - outside lens scope
        return CanonicalAddress(
            address_type=AddressType.UNKNOWN,
            identifier=None,
            relative_path="",
            raw_input=raw_path,
        )
    
    def _resolve_mod(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve a mod address - check if in active playset."""
        mod_name = address.identifier
        
        # Find the mod path from mods[]
        if mod_name in self._mod_paths:
            mod_path = self._mod_paths[mod_name]
            abs_path = mod_path / address.relative_path
            
            # Determine domain: LOCAL_MOD vs WORKSHOP_MOD
            # UI hint: potentially editable if mod is in local_mods_folder
            ui_hint = False
            domain = PathDomain.WORKSHOP_MOD  # Default to workshop
            if self._local_mods_folder:
                try:
                    mod_path.resolve().relative_to(self._local_mods_folder.resolve())
                    ui_hint = True
                    domain = PathDomain.LOCAL_MOD
                except ValueError:
                    pass
            
            return ResolutionResult(
                found=True,
                address=address,
                absolute_path=abs_path,
                domain=domain,
                mod_name=mod_name,
                ui_hint_potentially_editable=ui_hint,
            )
        
        return ResolutionResult.not_found(
            address.raw_input,
            f"Mod '{mod_name}' not in active playset"
        )
    
    def _resolve_vanilla(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve vanilla address - always visible."""
        if not self._vanilla_root:
            return ResolutionResult.not_found(address.raw_input, "Vanilla root not configured")
        
        abs_path = self._vanilla_root / address.relative_path
        return ResolutionResult(
            found=True,
            address=address,
            absolute_path=abs_path,
            domain=PathDomain.VANILLA,
            mod_name="vanilla",
            ui_hint_potentially_editable=False,
        )
    
    def _resolve_utility(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve utility address - visible."""
        parts = address.relative_path.split("/", 1)
        if len(parts) < 2:
            return ResolutionResult.not_found(address.raw_input, "Invalid utility path")
        
        util_type, rel_path = parts
        if util_type not in self._utility_roots:
            return ResolutionResult.not_found(
                address.raw_input,
                f"Unknown utility type: {util_type}"
            )
        
        abs_path = self._utility_roots[util_type] / rel_path
        return ResolutionResult(
            found=True,
            address=address,
            absolute_path=abs_path,
            domain=PathDomain.UTILITY,
            ui_hint_potentially_editable=False,
        )
    
    def _resolve_ck3raven(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve ck3raven source - visible for bug reports."""
        if not self._ck3raven_root:
            return ResolutionResult.not_found(address.raw_input, "ck3raven root not configured")
        
        abs_path = self._ck3raven_root / address.relative_path
        return ResolutionResult(
            found=True,
            address=address,
            absolute_path=abs_path,
            domain=PathDomain.CK3RAVEN,
            ui_hint_potentially_editable=False,
        )
    
    def _resolve_wip(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve WIP address - visible and potentially editable."""
        if not self._wip_root:
            return ResolutionResult.not_found(address.raw_input, "WIP root not configured")
        
        abs_path = self._wip_root / address.relative_path
        return ResolutionResult(
            found=True,
            address=address,
            absolute_path=abs_path,
            domain=PathDomain.WIP,
            ui_hint_potentially_editable=True,
        )


class DevWorldAdapter(WorldAdapter):
    """
    WorldAdapter for ck3raven-dev mode.
    
    Full visibility to:
    - ck3raven source code
    - All mod content (for parser/ingestion testing)
    - WIP workspace
    
    Writability is determined by enforcement.py, not here.
    """
    
    def __init__(
        self,
        db: "DBQueries",
        ck3raven_root: Path,
        wip_root: Path,
        vanilla_root: Optional[Path] = None,
        mod_paths: Optional[Set[Path]] = None,
    ):
        self._db = db
        self._ck3raven_root = ck3raven_root
        self._wip_root = wip_root
        self._vanilla_root = vanilla_root
        self._mod_paths = mod_paths or set()
    
    @property
    def mode(self) -> str:
        return "ck3raven-dev"
    
    def get_search_scope(self) -> Set[int]:
        """In dev mode, all content is searchable."""
        return set()
    
    def resolve(self, path_or_address: str) -> ResolutionResult:
        """
        Resolve a path in dev world.
        
        ck3raven source is the primary writable domain (per enforcement.py).
        Mods are visible but enforcement.py will deny writes.
        """
        path = Path(path_or_address).resolve()
        
        # Check ck3raven source first - this is the primary domain
        try:
            rel = path.relative_to(self._ck3raven_root.resolve())
            return ResolutionResult(
                found=True,
                address=CanonicalAddress(
                    address_type=AddressType.CK3RAVEN,
                    identifier=None,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=path_or_address,
                ),
                absolute_path=path,
                domain=PathDomain.CK3RAVEN,
                ui_hint_potentially_editable=True,
            )
        except ValueError:
            pass
        
        # Check WIP
        try:
            rel = path.relative_to(self._wip_root.resolve())
            return ResolutionResult(
                found=True,
                address=CanonicalAddress(
                    address_type=AddressType.WIP,
                    identifier=None,
                    relative_path=str(rel).replace("\\", "/"),
                    raw_input=path_or_address,
                ),
                absolute_path=path,
                domain=PathDomain.WIP,
                ui_hint_potentially_editable=True,
            )
        except ValueError:
            pass
        
        # Check vanilla - readable
        if self._vanilla_root:
            try:
                rel = path.relative_to(self._vanilla_root.resolve())
                return ResolutionResult(
                    found=True,
                    address=CanonicalAddress(
                        address_type=AddressType.VANILLA,
                        identifier=None,
                        relative_path=str(rel).replace("\\", "/"),
                        raw_input=path_or_address,
                    ),
                    absolute_path=path,
                    domain=PathDomain.VANILLA,
                    ui_hint_potentially_editable=False,
                )
            except ValueError:
                pass
        
        # Check mod paths - readable but NOT writable (enforcement handles this)
        # In dev mode, mods are always workshop (not editable)
        for mod_path in self._mod_paths:
            try:
                rel = path.relative_to(mod_path.resolve())
                return ResolutionResult(
                    found=True,
                    address=CanonicalAddress(
                        address_type=AddressType.MOD,
                        identifier=mod_path.name,
                        relative_path=str(rel).replace("\\", "/"),
                        raw_input=path_or_address,
                    ),
                    absolute_path=path,
                    domain=PathDomain.WORKSHOP_MOD,  # In dev mode, mods are read-only
                    ui_hint_potentially_editable=False,  # UI hint only
                )
            except ValueError:
                continue
        
        # Not found in any known location
        return ResolutionResult.not_found(path_or_address)
    
    def is_visible(self, path_or_address: str) -> bool:
        result = self.resolve(path_or_address)
        return result.found
