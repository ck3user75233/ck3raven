"""
ck3raven.tools - Analysis and Development Utilities

This module contains standalone tools for analyzing CK3 content:
- format: PDX script formatter/beautifier
- lint: Static analysis and style checking
- diff: AST-level diff between files
- query: Search/query AST structures
- merge: 3-way merge with conflict resolution
- conflicts: Conflict analysis and reporting
- trace: Track key provenance through mod stack
- schema: Learn schema patterns from files
- refdb: Reference database (cross-reference analysis)
"""

# Formatter
from .format import PDXFormatter, FormatOptions, FormatStyle

# Linter
from .lint import PDXLinter, LintIssue, Severity, LintRule

# Diff
from .diff import PDXDiffer, DiffResult, DiffItem, DiffType

# Query (function-based)
from .query import find_blocks_by_name, find_by_path, search_values

# Merge
from .merge import PDXMerger, MergeResult, MergeConflict, MergeStrategy

# Conflicts
from .conflicts import ConflictInfo, find_conflicts, analyze_conflict, generate_report

# Trace (function-based)
from .trace import trace_key_in_files

# Schema
from .schema import SchemaLearner, ContextSchema

# Reference Database
from .refdb import ReferenceDB, RefDBBuilder, Reference, Definition

__all__ = [
    # Format
    "PDXFormatter",
    "FormatOptions",
    "FormatStyle",
    # Lint
    "PDXLinter",
    "LintIssue",
    "Severity",
    "LintRule",
    # Diff
    "PDXDiffer",
    "DiffResult",
    "DiffItem",
    "DiffType",
    # Query
    "find_blocks_by_name",
    "find_by_path",
    "search_values",
    # Merge
    "PDXMerger",
    "MergeResult",
    "MergeConflict",
    "MergeStrategy",
    # Conflicts
    "ConflictInfo",
    "find_conflicts",
    "analyze_conflict",
    "generate_report",
    # Trace
    "trace_key_in_files",
    # Schema
    "SchemaLearner",
    "ContextSchema",
    # RefDB
    "ReferenceDB",
    "RefDBBuilder",
    "Reference",
    "Definition",
]
