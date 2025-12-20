"""CK3 Lens MCP Server - Kernel Package

Modules:
- workspace: Session management and configuration
- db_queries: Symbol database access
- validate: Parse and validate CK3 script
- semantic: Reference validation, autocomplete, hover
- live_mods: Sandboxed live mod operations
- git_ops: Git integration for mods
- contracts: Pydantic data models
- trace: Tool call tracing
"""

from ck3lens.validate import parse_content, validate_patchdraft
from ck3lens.semantic import (
    SemanticAnalyzer,
    validate_content,
    get_completions,
    get_hover,
    Diagnostic,
    CompletionItem,
    HoverInfo,
)

__all__ = [
    "parse_content",
    "validate_patchdraft",
    "SemanticAnalyzer",
    "validate_content",
    "get_completions",
    "get_hover",
    "Diagnostic",
    "CompletionItem",
    "HoverInfo",
]
