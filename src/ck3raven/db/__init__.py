"""
ck3raven.db - Database Storage Layer

Content-addressed storage with versioning for vanilla, mods, AST, and references.
"""

from ck3raven.db.schema import (
    init_database,
    get_connection,
    close_all_connections,
    DATABASE_VERSION,
)
from ck3raven.db.models import (
    VanillaVersion,
    ModPackage,
    ContentVersion,
    FileRecord,
    FileContent,
    ParserVersion,
    ASTRecord,
    Symbol,
    Reference,
    # EXPUNGED: Playset, PlaysetMod models removed (now file-based JSON)
    Snapshot,
    ExemplarMod,
)
from ck3raven.db.content import (
    compute_content_hash,
    compute_root_hash,
    normalize_relpath,
    detect_encoding,
    classify_file_type,
    scan_directory,
    store_file_content,
    store_file_record,
)
from ck3raven.db.ingest import (
    ingest_vanilla,
    ingest_mod,
    ingest_directory,
    incremental_update,
    compare_manifests,
)
from ck3raven.db.parser_version import (
    PARSER_VERSION,
    get_or_create_parser_version,
    get_current_parser_version,
    get_parser_source_hash,
    invalidate_ast_cache_for_old_parsers,
)
from ck3raven.db.ast_cache import (
    serialize_ast,
    deserialize_ast,
    get_cached_ast,
    store_ast,
    store_parse_failure,
    parse_and_cache,
    parse_file_cached,
    get_ast_stats,
    clear_ast_cache_for_parser,
)
from ck3raven.db.symbols import (
    extract_symbols_from_ast,
    extract_refs_from_ast,
    store_symbols_batch,
    store_refs_batch,
    extract_and_store,
    find_symbol_by_name,
    find_symbols_fts,
    find_refs_to_symbol,
    find_refs_fts,
    get_symbol_stats,
    find_unused_symbols,
    find_undefined_refs,
)
from ck3raven.db.search import (
    SearchScope,
    SearchResult,
    search_symbols,
    search_refs,
    search_content,
    search_all,
    find_definition,
    find_references,
    get_search_stats,
)
# EXPUNGED 2025-01-02: Database-based playset functions removed.
# Playsets are now file-based JSON. See playsets/*.json and server.py ck3_playset.
from ck3raven.db.cryo import (
    CryoManifest,
    create_snapshot,
    get_snapshot,
    list_snapshots,
    add_content_to_snapshot,
    get_snapshot_contents,
    delete_snapshot,
    export_snapshot_to_file,
    import_snapshot_from_file,
    get_snapshot_stats,
)

__all__ = [
    # Schema
    "init_database",
    "get_connection",
    "close_all_connections",
    "DATABASE_VERSION",
    # Models
    "VanillaVersion",
    "ModPackage",
    "ContentVersion",
    "FileRecord",
    "FileContent",
    "ParserVersion",
    "ASTRecord",
    "Symbol",
    "Reference",
    "Snapshot",
    "ExemplarMod",
    # Content
    "compute_content_hash",
    "compute_root_hash",
    "normalize_relpath",
    "detect_encoding",
    "classify_file_type",
    "scan_directory",
    "store_file_content",
    "store_file_record",
    # Ingest
    "ingest_vanilla",
    "ingest_mod",
    "ingest_directory",
    "incremental_update",
    "compare_manifests",
    # Parser Version
    "PARSER_VERSION",
    "get_or_create_parser_version",
    "get_current_parser_version",
    "get_parser_source_hash",
    "invalidate_ast_cache_for_old_parsers",
    # AST Cache
    "serialize_ast",
    "deserialize_ast",
    "get_cached_ast",
    "store_ast",
    "store_parse_failure",
    "parse_and_cache",
    "parse_file_cached",
    "get_ast_stats",
    "clear_ast_cache_for_parser",
    # Symbols
    "extract_symbols_from_ast",
    "extract_refs_from_ast",
    "store_symbols_batch",
    "store_refs_batch",
    "extract_and_store",
    "find_symbol_by_name",
    "find_symbols_fts",
    "find_refs_to_symbol",
    "find_refs_fts",
    "get_symbol_stats",
    "find_unused_symbols",
    "find_undefined_refs",
    # Search
    "SearchScope",
    "SearchResult",
    "search_symbols",
    "search_refs",
    "search_content",
    "search_all",
    "find_definition",
    "find_references",
    "get_search_stats",
    # EXPUNGED: Playsets functions removed (now file-based JSON)
    # Cryo
    "CryoManifest",
    "create_snapshot",
    "get_snapshot",
    "list_snapshots",
    "add_content_to_snapshot",
    "get_snapshot_contents",
    "delete_snapshot",
    "export_snapshot_to_file",
    "import_snapshot_from_file",
    "get_snapshot_stats",
]
