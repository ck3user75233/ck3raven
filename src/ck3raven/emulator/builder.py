"""
Game State Builder

Builds complete game state from a playset by:
1. Loading all files from the database for each content version
2. Fetching cached ASTs
3. Applying merge policies per folder
4. Tracking provenance (which mod contributed each definition)
"""

import sqlite3
from typing import List, Optional, Dict, Any, Tuple
from collections import OrderedDict
import logging

from ck3raven.db.models import FileRecord, ASTRecord
from ck3raven.db.ast_cache import get_cached_ast, deserialize_ast
from ck3raven.db.parser_version import get_current_parser_version
from ck3raven.resolver.policies import MergePolicy, get_policy_for_folder

from ck3raven.emulator.loader import LoadedPlayset, get_files_for_folder
from ck3raven.emulator.state import (
    GameState, FolderState, ResolvedDefinition, DefinitionSource, 
    ConflictRecord, get_source_name
)

logger = logging.getLogger(__name__)


def extract_definitions_from_ast(
    ast_dict: Dict[str, Any]
) -> List[Tuple[str, Dict[str, Any], int]]:
    """
    Extract top-level block definitions from a deserialized AST.
    
    Returns list of (key, node_dict, line) tuples.
    """
    definitions = []
    
    if ast_dict.get('_type') != 'root':
        return definitions
    
    for child in ast_dict.get('children', []):
        if child.get('_type') == 'block':
            key = child.get('name', '')
            line = child.get('line', 0)
            if key:
                definitions.append((key, child, line))
    
    return definitions


def resolve_folder_from_db(
    conn: sqlite3.Connection,
    folder: str,
    content_versions: List[int],
    policy: Optional[MergePolicy] = None
) -> FolderState:
    """
    Resolve a single folder using cached ASTs from the database.
    
    Args:
        conn: Database connection
        folder: Folder path like "common/culture/traditions"
        content_versions: List of content_version_ids in load order
        policy: Override merge policy (auto-detected if None)
    
    Returns:
        FolderState with resolved definitions and conflicts
    """
    if policy is None:
        policy = get_policy_for_folder(folder)
    
    result = FolderState(folder=folder, policy=policy)
    
    # Get current parser version for AST lookup
    parser_version = get_current_parser_version(conn)
    
    # Track all definitions by key: key -> list of (source, node_dict) in load order
    all_defs: Dict[str, List[Tuple[DefinitionSource, Dict[str, Any]]]] = {}
    
    # Process each content version in load order
    for load_order, cv_id in enumerate(content_versions):
        source_name = get_source_name(conn, cv_id)
        
        # Get all files in this folder for this content version
        files = get_files_for_folder(conn, cv_id, folder)
        
        for file_rec in files:
            # Get cached AST
            ast_record = get_cached_ast(conn, file_rec.content_hash, parser_version.parser_version_id)
            
            if not ast_record:
                result.errors.append((file_rec.file_id, f"No cached AST for {file_rec.relpath}"))
                continue
            
            if not ast_record.parse_ok:
                result.errors.append((file_rec.file_id, f"Parse failed for {file_rec.relpath}"))
                continue
            
            # Deserialize AST
            try:
                ast_dict = deserialize_ast(ast_record.ast_blob)
            except Exception as e:
                result.errors.append((file_rec.file_id, f"AST deserialize failed: {e}"))
                continue
            
            # Extract definitions
            defs = extract_definitions_from_ast(ast_dict)
            
            for key, node_dict, line in defs:
                source = DefinitionSource(
                    content_version_id=cv_id,
                    file_id=file_rec.file_id,
                    relpath=file_rec.relpath,
                    line=line,
                    load_order=load_order,
                    source_name=source_name
                )
                
                if key not in all_defs:
                    all_defs[key] = []
                all_defs[key].append((source, node_dict))
    
    # Apply merge policy
    if policy == MergePolicy.OVERRIDE:
        # Last definition wins
        for key, sources in all_defs.items():
            if not sources:
                continue
            
            # Sort by load order, last wins
            sorted_sources = sorted(sources, key=lambda x: x[0].load_order)
            winner_source, winner_ast = sorted_sources[-1]
            
            result.definitions[key] = ResolvedDefinition(
                key=key,
                ast_dict=winner_ast,
                source=winner_source
            )
            
            # Record conflict if multiple sources
            if len(sources) > 1:
                loser_sources = [s for s, _ in sorted_sources[:-1]]
                result.conflicts.append(ConflictRecord(
                    key=key,
                    folder=folder,
                    policy=policy,
                    winner=winner_source,
                    losers=loser_sources
                ))
    
    elif policy == MergePolicy.FIOS:
        # First definition wins
        for key, sources in all_defs.items():
            if not sources:
                continue
            
            sorted_sources = sorted(sources, key=lambda x: x[0].load_order)
            winner_source, winner_ast = sorted_sources[0]
            
            result.definitions[key] = ResolvedDefinition(
                key=key,
                ast_dict=winner_ast,
                source=winner_source
            )
            
            if len(sources) > 1:
                loser_sources = [s for s, _ in sorted_sources[1:]]
                result.conflicts.append(ConflictRecord(
                    key=key,
                    folder=folder,
                    policy=policy,
                    winner=winner_source,
                    losers=loser_sources
                ))
    
    elif policy == MergePolicy.CONTAINER_MERGE:
        # TODO: Implement container merge (on_actions)
        # For now, fall back to OVERRIDE
        logger.warning(f"CONTAINER_MERGE not yet implemented for {folder}, using OVERRIDE")
        return resolve_folder_from_db(conn, folder, content_versions, MergePolicy.OVERRIDE)
    
    elif policy == MergePolicy.PER_KEY_OVERRIDE:
        # Same as OVERRIDE for now (defines, localization)
        return resolve_folder_from_db(conn, folder, content_versions, MergePolicy.OVERRIDE)
    
    return result


def build_game_state(
    conn: sqlite3.Connection,
    loaded_playset: LoadedPlayset,
    folders: Optional[List[str]] = None
) -> GameState:
    """
    Build complete game state from a loaded playset.
    
    Args:
        conn: Database connection
        loaded_playset: Playset loaded from database
        folders: Specific folders to resolve (all if None)
    
    Returns:
        GameState with all resolved definitions
    """
    state = GameState(
        playset_id=loaded_playset.playset_id,
        playset_name=loaded_playset.name,
        content_versions=loaded_playset.content_versions
    )
    
    # Get folders to process
    if folders is None:
        # Query all folders from database
        all_folders = set()
        for cv_id in loaded_playset.content_versions:
            rows = conn.execute("""
                SELECT DISTINCT 
                    substr(relpath, 1, length(relpath) - length(replace(relpath, '/', '')) 
                           - (length(relpath) - length(replace(relpath, '/', '')) - 
                              instr(substr(relpath || '/', 1), '/'))) as folder
                FROM files
                WHERE content_version_id = ?
                  AND file_type = 'script'
                  AND deleted = 0
                  AND relpath LIKE '%/%'
            """, (cv_id,)).fetchall()
            
            for row in rows:
                folder = row['folder'].rstrip('/')
                if folder:
                    all_folders.add(folder)
        
        folders = sorted(all_folders)
    
    logger.info(f"Building game state for {len(folders)} folders")
    
    for folder in folders:
        logger.debug(f"Resolving {folder}")
        folder_state = resolve_folder_from_db(
            conn, folder, loaded_playset.content_versions
        )
        state.folders[folder] = folder_state
    
    state.update_stats()
    
    logger.info(f"Game state built: {state.total_definitions} definitions, "
                f"{state.total_conflicts} conflicts, {state.total_errors} errors")
    
    return state


def build_folder_state(
    conn: sqlite3.Connection,
    loaded_playset: LoadedPlayset,
    folder: str
) -> FolderState:
    """
    Build state for a single folder.
    
    Convenience function for resolving just one folder.
    """
    return resolve_folder_from_db(
        conn, folder, loaded_playset.content_versions
    )
