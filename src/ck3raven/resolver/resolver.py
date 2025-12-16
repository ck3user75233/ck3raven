"""
CK3 Content Resolver (DEPRECATED - File-Based)

.. deprecated::
    This module reads files directly and is deprecated.
    Use :class:`ck3raven.resolver.sql_resolver.SQLResolver` instead,
    which operates entirely on the database.

This file-based resolver is kept for:
- Legacy compatibility
- Testing individual file resolution without a database
- Reference implementation

For production use, always use SQLResolver which queries the ingested
database and respects playset load order.
"""

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from collections import OrderedDict

from ck3raven.parser import parse_file
from ck3raven.parser.parser import RootNode, BlockNode, AssignmentNode
from ck3raven.resolver.policies import MergePolicy, get_policy_for_folder

# Emit deprecation warning on import
warnings.warn(
    "ck3raven.resolver.resolver is deprecated. Use SQLResolver from "
    "ck3raven.resolver.sql_resolver instead.",
    DeprecationWarning,
    stacklevel=2
)


# =============================================================================
# CONTAINER_MERGE CONSTANTS
# =============================================================================

# Sub-blocks that get appended (list merging)
APPEND_BLOCKS: Set[str] = {
    'events', 'on_actions', 'random_events', 'random_on_actions',
    'first_valid', 'first_valid_on_action'
}

# Sub-blocks where only one can exist (last wins if conflict)
SINGLE_SLOT_BLOCKS: Set[str] = {
    'effect', 'trigger', 'weight_multiplier', 'fallback'
}


@dataclass
class SourceFile:
    """Represents a single source file from vanilla or a mod."""
    path: Path
    source_name: str  # "vanilla", "mod_name", etc.
    load_order: int  # Lower = loaded first, higher = wins in OVERRIDE


@dataclass
class Definition:
    """A single definition (key = { ... }) from a source file."""
    key: str
    node: BlockNode
    source: SourceFile
    file_path: Path
    line: int


@dataclass
class ConflictInfo:
    """Information about a conflict between definitions."""
    key: str
    winner: Definition
    losers: List[Definition]
    policy: MergePolicy


@dataclass
class MergedContainer:
    """
    Result of merging a container (like on_action) across multiple sources.
    
    Used for CONTAINER_MERGE policy where list sub-blocks are appended
    and single-slot blocks use last-wins.
    """
    key: str
    sources: List[SourceFile] = field(default_factory=list)
    
    # Appended lists (events, on_actions, random_events, etc.)
    events: List[str] = field(default_factory=list)
    on_actions: List[str] = field(default_factory=list)
    random_events: List[str] = field(default_factory=list)
    
    # Single-slot blocks - track all sources that defined them
    trigger_sources: List[SourceFile] = field(default_factory=list)
    effect_sources: List[SourceFile] = field(default_factory=list)
    
    # The winning blocks (last definition)
    trigger_block: Optional[BlockNode] = None
    effect_block: Optional[BlockNode] = None
    
    @property
    def has_trigger_conflict(self) -> bool:
        """True if multiple sources defined a trigger block."""
        return len(self.trigger_sources) > 1
    
    @property
    def has_effect_conflict(self) -> bool:
        """True if multiple sources defined an effect block."""
        return len(self.effect_sources) > 1
    
    @property
    def trigger_winner(self) -> Optional[SourceFile]:
        """The source that won the trigger slot."""
        return self.trigger_sources[-1] if self.trigger_sources else None
    
    @property
    def effect_winner(self) -> Optional[SourceFile]:
        """The source that won the effect slot."""
        return self.effect_sources[-1] if self.effect_sources else None


@dataclass
class MergedState:
    """The resolved state for a CONTAINER_MERGE folder."""
    folder_path: str
    policy: MergePolicy = MergePolicy.CONTAINER_MERGE
    
    # Merged containers (key -> MergedContainer)
    containers: OrderedDict[str, MergedContainer] = field(default_factory=OrderedDict)
    
    # Parse errors encountered
    errors: List[Tuple[Path, str]] = field(default_factory=list)
    
    def get_keys(self) -> List[str]:
        """Get all merged container keys."""
        return list(self.containers.keys())
    
    def get_container(self, key: str) -> Optional[MergedContainer]:
        """Get the merged container for a key."""
        return self.containers.get(key)
    
    def get_conflicts(self) -> List[MergedContainer]:
        """Get all containers that have trigger or effect conflicts."""
        return [c for c in self.containers.values() 
                if c.has_trigger_conflict or c.has_effect_conflict]


@dataclass
class ResolvedState:
    """The resolved state for a content folder."""
    folder_path: str
    policy: MergePolicy
    
    # Final resolved definitions (key -> Definition)
    definitions: OrderedDict[str, Definition] = field(default_factory=OrderedDict)
    
    # All conflicts that occurred during resolution
    conflicts: List[ConflictInfo] = field(default_factory=list)
    
    # Parse errors encountered
    errors: List[Tuple[Path, str]] = field(default_factory=list)
    
    def get_keys(self) -> List[str]:
        """Get all resolved definition keys."""
        return list(self.definitions.keys())
    
    def get_definition(self, key: str) -> Optional[Definition]:
        """Get the resolved definition for a key."""
        return self.definitions.get(key)
    
    def get_conflicts_for_key(self, key: str) -> Optional[ConflictInfo]:
        """Get conflict info for a specific key, if any."""
        for conflict in self.conflicts:
            if conflict.key == key:
                return conflict
        return None


def collect_definitions_from_file(source: SourceFile) -> List[Definition]:
    """
    Parse a source file and collect all top-level block definitions.
    
    Returns a list of Definition objects for each top-level block.
    """
    definitions = []
    
    try:
        ast = parse_file(str(source.path))
        
        for child in ast.children:
            if isinstance(child, BlockNode):
                definitions.append(Definition(
                    key=child.name,
                    node=child,
                    source=source,
                    file_path=source.path,
                    line=child.line
                ))
    except Exception as e:
        # Return empty list on parse error - caller should handle errors
        raise
    
    return definitions


def resolve_override(
    sources: List[SourceFile],
    folder_rel_path: str
) -> ResolvedState:
    """
    Resolve a folder using OVERRIDE policy.
    
    For each key, the last definition (highest load_order) wins completely.
    Files with the same path+name: later source replaces entire file content.
    
    Args:
        sources: List of source files in load order (vanilla first, mods in order)
        folder_rel_path: Relative path of the folder being resolved
    
    Returns:
        ResolvedState with final definitions and conflict info
    """
    result = ResolvedState(
        folder_path=folder_rel_path,
        policy=MergePolicy.OVERRIDE
    )
    
    # Group sources by relative file path (within the folder)
    # Files with same relative path = later replaces completely
    file_groups: Dict[str, List[SourceFile]] = {}
    
    for source in sources:
        # Get relative path within the content folder
        rel_file_path = source.path.name  # Just filename for now
        if rel_file_path not in file_groups:
            file_groups[rel_file_path] = []
        file_groups[rel_file_path].append(source)
    
    # Track all definitions by key (key -> list of definitions in load order)
    all_defs: Dict[str, List[Definition]] = {}
    
    # Process files in load order
    # Sort sources by load_order to ensure correct processing
    sorted_sources = sorted(sources, key=lambda s: s.load_order)
    
    for source in sorted_sources:
        try:
            defs = collect_definitions_from_file(source)
            
            for d in defs:
                if d.key not in all_defs:
                    all_defs[d.key] = []
                all_defs[d.key].append(d)
                
        except Exception as e:
            result.errors.append((source.path, str(e)))
    
    # Resolve each key: last definition wins
    for key, defs in all_defs.items():
        if len(defs) == 0:
            continue
        
        # Sort by load_order to find winner
        sorted_defs = sorted(defs, key=lambda d: d.source.load_order)
        winner = sorted_defs[-1]  # Last in load order wins
        
        result.definitions[key] = winner
        
        # Record conflict if there were multiple definitions
        if len(defs) > 1:
            result.conflicts.append(ConflictInfo(
                key=key,
                winner=winner,
                losers=sorted_defs[:-1],  # All but the last
                policy=MergePolicy.OVERRIDE
            ))
    
    return result


def _extract_list_items(block: BlockNode) -> List[str]:
    """
    Extract items from a list block like events = { evt.1 evt.2 }.
    
    Handles both simple values and weighted format (100 = event_name).
    """
    items = []
    for child in block.children:
        if isinstance(child, AssignmentNode):
            # Weighted format: 100 = event_name
            items.append(f"{child.key}={child.value}")
        elif hasattr(child, 'value'):
            items.append(str(child.value))
        elif hasattr(child, 'name'):
            items.append(child.name)
    return items


def resolve_container_merge(
    sources: List[SourceFile],
    folder_rel_path: str
) -> MergedState:
    """
    Resolve a folder using CONTAINER_MERGE policy.
    
    For on_actions and similar containers:
    - List sub-blocks (events, on_actions, random_events) are APPENDED
    - Single-slot blocks (trigger, effect) use LAST WINS if conflict
    
    Args:
        sources: List of source files in load order (vanilla first, mods in order)
        folder_rel_path: Relative path of the folder being resolved
    
    Returns:
        MergedState with merged containers
    """
    result = MergedState(folder_path=folder_rel_path)
    
    # Collect all containers by key
    all_containers: Dict[str, List[Tuple[SourceFile, BlockNode]]] = {}
    
    # Sort sources by load_order
    sorted_sources = sorted(sources, key=lambda s: s.load_order)
    
    for source in sorted_sources:
        try:
            ast = parse_file(str(source.path))
            
            for child in ast.children:
                if isinstance(child, BlockNode):
                    key = child.name
                    if key not in all_containers:
                        all_containers[key] = []
                    all_containers[key].append((source, child))
                    
        except Exception as e:
            result.errors.append((source.path, str(e)))
    
    # Merge each container
    for key, definitions in all_containers.items():
        merged = MergedContainer(key=key)
        
        for source, block in definitions:
            merged.sources.append(source)
            
            for child in block.children:
                if isinstance(child, BlockNode):
                    name = child.name
                    
                    if name == "events":
                        items = _extract_list_items(child)
                        merged.events.extend(items)
                    elif name == "on_actions":
                        items = _extract_list_items(child)
                        merged.on_actions.extend(items)
                    elif name == "random_events":
                        items = _extract_list_items(child)
                        merged.random_events.extend(items)
                    elif name == "trigger":
                        merged.trigger_sources.append(source)
                        merged.trigger_block = child
                    elif name == "effect":
                        merged.effect_sources.append(source)
                        merged.effect_block = child
        
        result.containers[key] = merged
    
    return result


def resolve_folder(
    sources: List[SourceFile],
    folder_rel_path: str,
    policy: Optional[MergePolicy] = None
) -> ResolvedState:
    """
    Resolve a content folder from multiple sources.
    
    Args:
        sources: List of source files in load order (vanilla first, mods in order)
        folder_rel_path: Relative path like "common/culture/traditions"
        policy: Override the auto-detected policy (optional)
    
    Returns:
        ResolvedState with final definitions and conflict info
    """
    # Determine policy if not specified
    if policy is None:
        policy = get_policy_for_folder(folder_rel_path)
    
    # Route to appropriate resolver
    if policy == MergePolicy.OVERRIDE:
        return resolve_override(sources, folder_rel_path)
    elif policy == MergePolicy.CONTAINER_MERGE:
        return resolve_container_merge(sources, folder_rel_path)
    elif policy == MergePolicy.PER_KEY_OVERRIDE:
        # TODO: Implement per-key override
        raise NotImplementedError("PER_KEY_OVERRIDE policy not yet implemented")
    elif policy == MergePolicy.FIOS:
        # TODO: Implement FIOS
        raise NotImplementedError("FIOS policy not yet implemented")
    else:
        raise ValueError(f"Unknown policy: {policy}")


def collect_folder_sources(
    base_paths: List[Tuple[Path, str, int]],
    folder_rel_path: str
) -> List[SourceFile]:
    """
    Collect all source files for a folder from multiple base paths.
    
    Args:
        base_paths: List of (path, name, load_order) tuples
                   e.g., [(vanilla_path, "vanilla", 0), (mod_path, "my_mod", 1)]
        folder_rel_path: Relative path like "common/culture/traditions"
    
    Returns:
        List of SourceFile objects for all .txt files found
    """
    sources = []
    
    for base_path, name, load_order in base_paths:
        folder = base_path / folder_rel_path
        if folder.exists():
            for txt_file in folder.glob("*.txt"):
                sources.append(SourceFile(
                    path=txt_file,
                    source_name=name,
                    load_order=load_order
                ))
    
    return sources


# =============================================================================
# RESOLVER CLASS
# =============================================================================

@dataclass
class PlaysetEntry:
    """A single entry in a playset (vanilla or mod)."""
    path: Path
    name: str
    load_order: int
    
    @classmethod
    def from_path(cls, path: Path, name: str = None, load_order: int = 0) -> 'PlaysetEntry':
        """Create from path, auto-detecting name if not provided."""
        if name is None:
            name = path.name
        return cls(path=Path(path), name=name, load_order=load_order)


class Resolver:
    """
    High-level resolver for CK3 content.
    
    Takes a playset (ordered list of vanilla + mods) and resolves
    all content according to CK3's merge policies.
    
    Usage:
        resolver = Resolver()
        resolver.add_source(vanilla_path, "vanilla", 0)
        resolver.add_source(mod_path, "my_mod", 1)
        
        # Resolve a specific folder
        result = resolver.resolve_folder("common/culture/traditions")
        
        # Resolve all folders
        all_results = resolver.resolve_all()
    """
    
    def __init__(self):
        self.sources: List[PlaysetEntry] = []
        self._results: Dict[str, Any] = {}  # folder -> result cache
    
    def add_source(self, path: Path, name: str = None, load_order: int = None) -> 'Resolver':
        """
        Add a source (vanilla or mod) to the playset.
        
        Args:
            path: Path to the source root (game folder or mod folder)
            name: Display name for the source (defaults to folder name)
            load_order: Order in load sequence (auto-increments if not provided)
        
        Returns:
            self for chaining
        """
        if load_order is None:
            load_order = len(self.sources)
        if name is None:
            name = Path(path).name
            
        self.sources.append(PlaysetEntry(
            path=Path(path),
            name=name,
            load_order=load_order
        ))
        return self
    
    def clear(self) -> 'Resolver':
        """Clear all sources and cached results."""
        self.sources.clear()
        self._results.clear()
        return self
    
    def get_base_paths(self) -> List[Tuple[Path, str, int]]:
        """Get sources as (path, name, load_order) tuples for resolution functions."""
        return [(s.path, s.name, s.load_order) for s in sorted(self.sources, key=lambda x: x.load_order)]
    
    def resolve_folder(self, folder_rel_path: str, policy: MergePolicy = None):
        """
        Resolve a specific content folder.
        
        Args:
            folder_rel_path: Relative path like "common/culture/traditions"
            policy: Override auto-detected policy (optional)
        
        Returns:
            ResolvedState or MergedState depending on policy
        """
        sources = collect_folder_sources(self.get_base_paths(), folder_rel_path)
        
        if not sources:
            # Return empty result
            return ResolvedState(folder_path=folder_rel_path, policy=policy or MergePolicy.OVERRIDE)
        
        result = resolve_folder(sources, folder_rel_path, policy)
        self._results[folder_rel_path] = result
        return result
    
    def get_all_content_folders(self) -> List[str]:
        """
        Scan all sources and return list of content folder relative paths.
        
        Returns:
            List of folder paths like ["common/culture/traditions", "events", ...]
        """
        folders = set()
        
        for source in self.sources:
            # Scan common/ and events/ folders
            common = source.path / "common"
            if common.exists():
                for subfolder in common.rglob("*"):
                    if subfolder.is_dir() and list(subfolder.glob("*.txt")):
                        rel = subfolder.relative_to(source.path)
                        folders.add(str(rel).replace("\\", "/"))
            
            events = source.path / "events"
            if events.exists() and list(events.glob("*.txt")):
                folders.add("events")
        
        return sorted(folders)
    
    def resolve_all(self, progress_callback=None) -> Dict[str, Any]:
        """
        Resolve all content folders.
        
        Args:
            progress_callback: Optional callback(folder_path, index, total)
        
        Returns:
            Dict of {folder_path: result}
        """
        folders = self.get_all_content_folders()
        results = {}
        
        for i, folder in enumerate(folders):
            if progress_callback:
                progress_callback(folder, i, len(folders))
            
            try:
                results[folder] = self.resolve_folder(folder)
            except Exception as e:
                results[folder] = {"error": str(e)}
        
        return results
    
    def get_conflict_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all conflicts across resolved folders.
        
        Returns:
            Dict with conflict statistics and details
        """
        summary = {
            "total_folders": len(self._results),
            "folders_with_conflicts": 0,
            "total_override_conflicts": 0,
            "total_merge_conflicts": 0,
            "conflicts_by_folder": {}
        }
        
        for folder, result in self._results.items():
            folder_conflicts = []
            
            if isinstance(result, ResolvedState):
                # OVERRIDE conflicts
                for conflict in result.conflicts:
                    folder_conflicts.append({
                        "key": conflict.key,
                        "policy": "OVERRIDE",
                        "winner": conflict.winner.source.source_name,
                        "losers": [d.source.source_name for d in conflict.losers]
                    })
                    summary["total_override_conflicts"] += 1
                    
            elif isinstance(result, MergedState):
                # CONTAINER_MERGE conflicts (trigger/effect)
                for container in result.containers.values():
                    if container.has_trigger_conflict or container.has_effect_conflict:
                        conflict_info = {
                            "key": container.key,
                            "policy": "CONTAINER_MERGE"
                        }
                        if container.has_trigger_conflict:
                            conflict_info["trigger_winner"] = container.trigger_winner.source_name
                            conflict_info["trigger_losers"] = [s.source_name for s in container.trigger_sources[:-1]]
                        if container.has_effect_conflict:
                            conflict_info["effect_winner"] = container.effect_winner.source_name
                            conflict_info["effect_losers"] = [s.source_name for s in container.effect_sources[:-1]]
                        
                        folder_conflicts.append(conflict_info)
                        summary["total_merge_conflicts"] += 1
            
            if folder_conflicts:
                summary["folders_with_conflicts"] += 1
                summary["conflicts_by_folder"][folder] = folder_conflicts
        
        return summary
