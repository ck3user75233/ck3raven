"""
ck3raven.resolver - Merge/Override Resolution

Implements CK3's merge policies for resolving conflicts between mods.

Two resolver implementations:
- SQLResolver: Production resolver, operates on database (symbols/files tables)
- Resolver: Legacy file-based resolver for testing only

Contribution/Conflict Analysis:
- ContributionsManager: Lifecycle-aware conflict analysis
- ConflictAnalyzer: Unit-level extraction and grouping
"""

from ck3raven.resolver.policies import MergePolicy, SubBlockPolicy, ContentTypeConfig
from ck3raven.resolver.content_types import (
    CONTENT_TYPES,
    ContentType,
    get_content_type,
    get_content_type_for_path,
    get_policy_for_path,
    FOLDER_POLICIES,
)

# SQL-based resolver (PRODUCTION - use this)
from ck3raven.resolver.sql_resolver import (
    SQLResolver,
    ResolvedSymbol,
    OverriddenSymbol,
    FileOverride,
    ResolutionResult,
)

# Contributions Manager (LIFECYCLE-AWARE)
from ck3raven.resolver.manager import (
    ContributionsManager,
    RefreshResult,
    ConflictSummary,
)

# Legacy file-based resolver (DEPRECATED - for tests only)
from ck3raven.resolver.resolver import (
    SourceFile,
    Definition,
    ConflictInfo,
    ResolvedState,
    MergedContainer,
    MergedState,
    APPEND_BLOCKS,
    SINGLE_SLOT_BLOCKS,
    PlaysetEntry,
    Resolver,
    resolve_override,
    resolve_container_merge,
    resolve_folder,
    collect_folder_sources,
)

__all__ = [
    # Policies
    "MergePolicy",
    "SubBlockPolicy",
    "ContentTypeConfig",
    # Content Types
    "CONTENT_TYPES",
    "ContentType",
    "get_content_type",
    "get_content_type_for_path",
    "get_policy_for_path",
    "FOLDER_POLICIES",
    # SQL Resolver (PRODUCTION)
    "SQLResolver",
    "ResolvedSymbol",
    "OverriddenSymbol",
    "FileOverride",
    "ResolutionResult",
    # Contributions Manager (LIFECYCLE-AWARE)
    "ContributionsManager",
    "RefreshResult",
    "ConflictSummary",
    # Legacy file-based (DEPRECATED)
    "SourceFile",
    "Definition",
    "ConflictInfo",
    "ResolvedState",
    "resolve_override",
    "MergedContainer",
    "MergedState",
    "APPEND_BLOCKS",
    "SINGLE_SLOT_BLOCKS",
    "resolve_container_merge",
    "PlaysetEntry",
    "Resolver",
    "resolve_folder",
    "collect_folder_sources",
]
