"""CK3 Lens MCP Server - Kernel Package

Modules:
- workspace: Session management and configuration
- db_queries: Symbol database access
- validate: Parse and validate CK3 script
- semantic: Syntax validation (CK3SyntaxValidator)
- local_mods: Sandboxed local mod operations (user-configured mods)
- git_ops: Git integration for mods
- contracts: Pydantic data models (ArtifactFile, ArtifactBundle)
- trace: Tool call tracing
"""

from ck3lens.validate import parse_content, validate_artifact_bundle

# Backwards compatibility aliases
validate_patchdraft = validate_artifact_bundle

__all__ = [
    "parse_content",
    "validate_artifact_bundle",
    "validate_patchdraft",  # Backwards compatibility alias
]
