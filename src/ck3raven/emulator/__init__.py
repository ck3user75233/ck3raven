"""
ck3raven.emulator - Game State Building

Builds the complete game state from vanilla + mods by:
1. Loading playsets from the database
2. Fetching cached ASTs for all files
3. Applying merge policies per content folder
4. Tracking provenance (which mod contributed each definition)
"""

from .loader import LoadedPlayset, load_playset_from_db, get_files_for_folder
from .state import (
    GameState, FolderState, ResolvedDefinition, 
    DefinitionSource, ConflictRecord, get_source_name
)
from .builder import (
    build_game_state, build_folder_state, 
    resolve_folder_from_db, extract_definitions_from_ast
)
from .exporter import GameStateExporter, ExportOptions

__all__ = [
    # Loader
    "LoadedPlayset",
    "load_playset_from_db",
    "get_files_for_folder",
    # State
    "GameState",
    "FolderState",
    "ResolvedDefinition",
    "DefinitionSource", 
    "ConflictRecord",
    "get_source_name",
    # Builder
    "build_game_state",
    "build_folder_state",
    "resolve_folder_from_db",
    "extract_definitions_from_ast",
    # Exporter
    "GameStateExporter",
    "ExportOptions",
]
