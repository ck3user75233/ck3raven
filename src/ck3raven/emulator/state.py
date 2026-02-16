"""
Game State

The resolved game state from a playset - all definitions with provenance.
Works entirely from the database.
"""

import sqlite3
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from collections import OrderedDict

from ck3raven.db.models import FileRecord, ASTRecord
from ck3raven.db.ast_cache import deserialize_ast
from ck3raven.resolver.policies import MergePolicy


@dataclass
class DefinitionSource:
    """Provenance information for a definition."""
    content_version_id: int
    file_id: int
    relpath: str
    line: int
    load_order: int  # 0 = vanilla, 1+ = mods in order
    source_name: str  # "vanilla", mod name, etc.


@dataclass
class ResolvedDefinition:
    """A single resolved definition with its AST and provenance."""
    key: str
    ast_dict: Dict[str, Any]  # Deserialized AST node
    source: DefinitionSource
    
    def __repr__(self):
        return f"ResolvedDefinition({self.key} from {self.source.source_name})"


@dataclass
class ConflictRecord:
    """Record of a conflict where multiple sources defined the same key."""
    key: str
    folder: str
    policy: MergePolicy
    winner: DefinitionSource
    losers: List[DefinitionSource]
    
    def __repr__(self):
        return f"Conflict({self.key}: {self.winner.source_name} wins over {len(self.losers)})"


@dataclass
class FolderState:
    """Resolved state for a single content folder."""
    folder: str
    policy: MergePolicy
    definitions: OrderedDict[str, ResolvedDefinition] = field(default_factory=OrderedDict)
    conflicts: List[ConflictRecord] = field(default_factory=list)
    errors: List[Tuple[int, str]] = field(default_factory=list)  # (file_id, error_msg)
    
    @property
    def definition_count(self) -> int:
        return len(self.definitions)
    
    @property
    def conflict_count(self) -> int:
        return len(self.conflicts)
    
    def get_definition(self, key: str) -> Optional[ResolvedDefinition]:
        return self.definitions.get(key)
    
    def __repr__(self):
        return f"FolderState({self.folder}: {self.definition_count} defs, {self.conflict_count} conflicts)"


@dataclass
class GameState:
    """
    Complete resolved game state from a playset.
    
    Contains all folders with their resolved definitions and conflicts.
    """
    playset_id: int
    playset_name: str
    content_versions: List[int]  # In load order
    
    # Resolved state per folder
    folders: Dict[str, FolderState] = field(default_factory=dict)
    
    # Summary stats
    total_definitions: int = 0
    total_conflicts: int = 0
    total_errors: int = 0
    
    def get_folder(self, folder: str) -> Optional[FolderState]:
        return self.folders.get(folder)
    
    def get_definition(self, folder: str, key: str) -> Optional[ResolvedDefinition]:
        fs = self.folders.get(folder)
        return fs.get_definition(key) if fs else None
    
    def get_all_conflicts(self) -> List[ConflictRecord]:
        """Get all conflicts across all folders."""
        conflicts = []
        for fs in self.folders.values():
            conflicts.extend(fs.conflicts)
        return conflicts
    
    def get_conflicts_by_source(self, source_name: str) -> List[ConflictRecord]:
        """Get conflicts where a specific source lost."""
        result = []
        for conflict in self.get_all_conflicts():
            for loser in conflict.losers:
                if loser.source_name == source_name:
                    result.append(conflict)
                    break
        return result
    
    def update_stats(self):
        """Recalculate summary statistics."""
        self.total_definitions = sum(fs.definition_count for fs in self.folders.values())
        self.total_conflicts = sum(fs.conflict_count for fs in self.folders.values())
        self.total_errors = sum(len(fs.errors) for fs in self.folders.values())
    
    def __repr__(self):
        return (f"GameState({self.playset_name}: {len(self.folders)} folders, "
                f"{self.total_definitions} defs, {self.total_conflicts} conflicts)")


def get_source_name(conn: sqlite3.Connection, content_version_id: int) -> str:
    """Get human-readable name for a content version."""
    row = conn.execute("""
        SELECT cv.name
        FROM content_versions cv
        WHERE cv.content_version_id = ?
    """, (content_version_id,)).fetchone()
    
    return row['name'] if row else f"unknown_{content_version_id}"
