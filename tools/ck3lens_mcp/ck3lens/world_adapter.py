"""
World Adapter - Visibility Layer for CK3 Lens

This module provides the WorldAdapter interface and implementations that
determine what exists and can be referenced in each agent mode.

Architecture:
- WorldAdapter is a FACADE over existing infrastructure (PlaysetLens, PlaysetScope, DBQueries)
- WorldAdapter decides WHAT EXISTS (visibility)
- Policy decides WHAT MAY BE DONE (mutation control)

These are orthogonal layers:
- LensWorld answers: what exists and can be referenced?
- Policy answers: what actions are permitted on those references?

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
    from .playset_scope import PlaysetScope


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


@dataclass
class ResolutionResult:
    """
    Result of resolving an address through the WorldAdapter.
    
    If found=False, the reference does not exist in this world.
    Policy is NEVER consulted for not-found references.
    """
    found: bool
    address: Optional[CanonicalAddress] = None
    absolute_path: Optional[Path] = None  # For filesystem operations
    file_id: Optional[int] = None  # For database operations
    content_version_id: Optional[int] = None
    mod_name: Optional[str] = None
    is_writable: bool = False  # For policy - can this be mutated?
    error_message: Optional[str] = None
    
    @classmethod
    def not_found(cls, raw_input: str, reason: str = "Reference not found") -> "ResolutionResult":
        """Create a not-found result."""
        return cls(
            found=False,
            error_message=f"{reason}: {raw_input}"
        )


class WorldAdapter(ABC):
    """
    Abstract base for world visibility adapters.
    
    WorldAdapter determines what exists and can be referenced.
    It does NOT make policy decisions about what actions are allowed.
    
    All MCP tools should:
    1. Get the appropriate WorldAdapter from WorldRouter
    2. Resolve references through the adapter
    3. Only then apply policy (if the reference was found)
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
        scope: "PlaysetScope",
        db: "DBQueries",
        vanilla_root: Optional[Path] = None,
        ck3raven_root: Optional[Path] = None,
        wip_root: Optional[Path] = None,
        utility_roots: Optional[dict[str, Path]] = None,
    ):
        self._lens = lens
        self._scope = scope
        self._db = db
        self._vanilla_root = vanilla_root
        self._ck3raven_root = ck3raven_root
        self._wip_root = wip_root
        self._utility_roots = utility_roots or {}
    
    @property
    def mode(self) -> str:
        return "ck3lens"
    
    @property
    def lens(self) -> "PlaysetLens":
        """Get the underlying PlaysetLens for direct DB query filtering."""
        return self._lens
    
    @property
    def scope(self) -> "PlaysetScope":
        """Get the underlying PlaysetScope for filesystem path validation."""
        return self._scope
    
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
        
        # Check mod roots via scope
        location_type, mod_name = self._scope.get_path_location(path)
        if location_type in ("local_mod", "workshop_mod") and mod_name:
            # Find the mod root to get relative path
            for mod_root in self._scope.mod_roots:
                try:
                    rel = path.relative_to(mod_root.resolve())
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
                return CanonicalAddress(
                    address_type=AddressType.UTILITY,
                    identifier=None,
                    relative_path=f"{util_name}/{str(rel).replace('\\', '/')}",
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
        # TODO: Look up mod by identifier, check if in lens.mod_cv_ids
        # For now, use scope to check path validity
        mod_name = address.identifier
        
        # Find the mod root
        for mod_root in self._scope.mod_roots:
            if mod_root.name == mod_name:
                abs_path = mod_root / address.relative_path
                is_writable = mod_root in self._scope.local_mod_roots
                return ResolutionResult(
                    found=True,
                    address=address,
                    absolute_path=abs_path,
                    mod_name=mod_name,
                    is_writable=is_writable,
                )
        
        return ResolutionResult.not_found(
            address.raw_input,
            f"Mod '{mod_name}' not in active playset"
        )
    
    def _resolve_vanilla(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve vanilla address - always visible, never writable."""
        if not self._vanilla_root:
            return ResolutionResult.not_found(address.raw_input, "Vanilla root not configured")
        
        abs_path = self._vanilla_root / address.relative_path
        return ResolutionResult(
            found=True,
            address=address,
            absolute_path=abs_path,
            mod_name="vanilla",
            is_writable=False,
        )
    
    def _resolve_utility(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve utility address - visible, never writable in ck3lens."""
        # Parse utility type from relative path (e.g., "logs/error.log")
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
            is_writable=False,
        )
    
    def _resolve_ck3raven(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve ck3raven source - visible for bug reports, never writable."""
        if not self._ck3raven_root:
            return ResolutionResult.not_found(address.raw_input, "ck3raven root not configured")
        
        abs_path = self._ck3raven_root / address.relative_path
        return ResolutionResult(
            found=True,
            address=address,
            absolute_path=abs_path,
            is_writable=False,  # Always read-only in ck3lens
        )
    
    def _resolve_wip(self, address: CanonicalAddress) -> ResolutionResult:
        """Resolve WIP address - visible and writable."""
        if not self._wip_root:
            return ResolutionResult.not_found(address.raw_input, "WIP root not configured")
        
        abs_path = self._wip_root / address.relative_path
        return ResolutionResult(
            found=True,
            address=address,
            absolute_path=abs_path,
            is_writable=True,
        )


class DevWorldAdapter(WorldAdapter):
    """
    WorldAdapter for ck3raven-dev mode.
    
    Full visibility to:
    - ck3raven source code (writable)
    - All mod content (read-only - for parser/ingestion testing)
    - WIP workspace (writable)
    
    NOT visible/writable:
    - Mod files for editing (absolute prohibition)
    """
    
    def __init__(
        self,
        db: "DBQueries",
        ck3raven_root: Path,
        wip_root: Path,
        vanilla_root: Optional[Path] = None,
        mod_roots: Optional[Set[Path]] = None,
    ):
        self._db = db
        self._ck3raven_root = ck3raven_root
        self._wip_root = wip_root
        self._vanilla_root = vanilla_root
        self._mod_roots = mod_roots or set()
    
    @property
    def mode(self) -> str:
        return "ck3raven-dev"
    
    def get_search_scope(self) -> Set[int]:
        """In dev mode, all content is searchable."""
        # Return all content_version_ids
        # TODO: Query database for all cv_ids
        return set()
    
    def resolve(self, path_or_address: str) -> ResolutionResult:
        """
        Resolve a path in dev world.
        
        ck3raven source is the primary writable domain.
        Mods are visible but NOT writable.
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
                is_writable=True,  # Writable in dev mode
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
                is_writable=True,
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
                    is_writable=False,
                )
            except ValueError:
                pass
        
        # Check mod roots - readable but NOT writable
        for mod_root in self._mod_roots:
            try:
                rel = path.relative_to(mod_root.resolve())
                return ResolutionResult(
                    found=True,
                    address=CanonicalAddress(
                        address_type=AddressType.MOD,
                        identifier=mod_root.name,
                        relative_path=str(rel).replace("\\", "/"),
                        raw_input=path_or_address,
                    ),
                    absolute_path=path,
                    is_writable=False,  # NEVER writable in dev mode
                )
            except ValueError:
                continue
        
        # Not found in any known location
        return ResolutionResult.not_found(path_or_address)
    
    def is_visible(self, path_or_address: str) -> bool:
        result = self.resolve(path_or_address)
        return result.found
