"""
arch_lint v2.35 — Pattern definitions.

This module contains PURE DATA: all banned terms, patterns, and rules.
Edit this file to add/remove architectural constraints.
No logic here — just definitions.

Organization:
1. BANNED_DIRECT_TERMS - Exact token matches
2. COMPOSITE_RULES - Token sequence patterns (a%b%c)
3. NEAR_WINDOW_RULES - Tokens within N positions
4. COMMENT_KEYWORDS - Suspicious comment markers
5. FORBIDDEN_FILENAMES - Banned file patterns
6. PATH_PATTERNS - Forbidden path APIs
7. ENFORCEMENT_PATTERNS - Call-site restrictions
8. IO_PATTERNS - Raw I/O detection
"""

from __future__ import annotations

# =============================================================================
# 1. BANNED DIRECT TERMS
# =============================================================================
# These are exact token matches. Case-insensitive scanning.
# Source: CANONICAL_ARCHITECTURE.md §6 Banned Terms

BANNED_PERMISSION_ORACLES = frozenset({
    # Permission/capability oracles
    "can_write",
    "can_edit",
    "can_delete",
    "is_writable",
    "is_editable",
    "is_allowed",
    "is_path_allowed",
    "is_path_writable",
    "is_permitted",
    "is_mutable",
    "writable_mod",
    "editable_mod",
    "mod_write",
    "mod_read",
    "mod_delete",
    "may_write",
})

BANNED_PARALLEL_AUTHORITY = frozenset({
    # Parallel authority structures
    "editable_mods",
    "editable_mods_list",
    "writable_mods",
    "live_mods",
    "live_mods_config",
    "default_live_mods",
    "active_mods",
    "enabled_mods",
    "mod_groups",
    "allowed_mods",
    "mutable_mods",
    "mod_whitelist",
    "whitelist",
    "blacklist",
    "mod_roots",
    "visible_cvids",
    "db_visibility",
    "write_mods",
})

BANNED_LENS_CONCEPTS = frozenset({
    # Lens concept explosion
    "playsetlens",
    "lensworld",
    "getlens",
    "get_lens",
    "lens_cache",
    "lensscope",
    "lenssession",
    "lensprovider",
    "lensfactory",
    "lensservice",
    "lensadapter",
    "lensresolver",
    "lenscontext",
    "lensmanager",
    "playsetworld",
    "playscope",
    "scopeworld",
    "worldscope",
})

BANNED_LEGACY_MARKERS = frozenset({
    # Legacy/drift markers
    "legacyvisibility",
    "legacy_visibility",
    "lens_enforcement",
    "legacy_enforcement",
    "invalidate_lens_cache",
    "legacy_file",
    # Bridge duplication (January 2026)
    "active_playset_data",
    "active_playset_file",
})

BANNED_PATH_ORACLES = frozenset({
    # Path oracles
    "mod_root",
    "local_mod_root",
    "mod_paths",
    "active_mod_paths",
})

BANNED_VISIBILITY_CACHING = frozenset({
    # Visibility/scope caching
    "_lens_cache",
    "_validate_visibility",
    "_build_cv_filter",
    "_derive_search_cvids",
})

BANNED_DECISION_LEAKS = frozenset({
    # Decision types that must not leak outside enforcement.py
    # REQUIRE_CONTRACT is not a decision type agents or tools may reference.
    # The need for a contract is communicated as info in a D (Deny) reply.
    # See: CANONICAL_CONTRACT_LAW.md §8, §13
    "require_contract",
})

# Combined set for quick lookup
BANNED_DIRECT_TERMS = (
    BANNED_PERMISSION_ORACLES |
    BANNED_PARALLEL_AUTHORITY |
    BANNED_LENS_CONCEPTS |
    BANNED_LEGACY_MARKERS |
    BANNED_PATH_ORACLES |
    BANNED_VISIBILITY_CACHING |
    BANNED_DECISION_LEAKS
)

# Contextually banned - only allowed in specific contexts
BANNED_CONTEXTUAL = {
    "local_mods": "local_mods_folder",  # Only allowed as part of local_mods_folder
}


# =============================================================================
# 2. COMPOSITE RULES (Token Sequence Patterns)
# =============================================================================
# Pattern format: "token1%token2%token3" - tokens must appear in order with gaps
# Tuple: (severity, rule_id, pattern, reason)

COMPOSITE_RULES: list[tuple[str, str, str, str]] = [
    # === ERROR: Definite violations ===
    # Parallel truth patterns
    ("ERROR", "BANNED_COMPOSITE", "live%mods", "Parallel truth: live mods"),
    ("ERROR", "BANNED_COMPOSITE", "active%mods", "Parallel truth: active mods"),
    ("ERROR", "BANNED_COMPOSITE", "enabled%mods", "Parallel truth: enabled mods"),
    
    # Path oracle patterns
    ("ERROR", "BANNED_COMPOSITE", "mod%root", "Path oracle: mod root"),
    ("ERROR", "BANNED_COMPOSITE", "mod%paths", "Path oracle: mod paths"),
    ("ERROR", "BANNED_COMPOSITE", "local%mod%root", "Path oracle: local mod root"),
    
    # Permission oracle patterns (v2.32)
    ("ERROR", "BANNED_ORACLE", "is%writable", "Oracle: is_writable pattern"),
    ("ERROR", "BANNED_ORACLE", "is%editable", "Oracle: is_editable pattern"),
    ("ERROR", "BANNED_ORACLE", "is%allowed", "Oracle: is_allowed pattern"),
    ("ERROR", "BANNED_ORACLE", "is%permitted", "Oracle: is_permitted pattern"),
    ("ERROR", "BANNED_ORACLE", "is%mutable", "Oracle: is_mutable pattern"),
    ("ERROR", "BANNED_ORACLE", "can%write", "Oracle: can_write pattern"),
    ("ERROR", "BANNED_ORACLE", "can%edit", "Oracle: can_edit pattern"),
    ("ERROR", "BANNED_ORACLE", "can%delete", "Oracle: can_delete pattern"),
    ("ERROR", "BANNED_ORACLE", "may%write", "Oracle: may_write pattern"),
    
    # Decision leak patterns (v2.36)
    ("ERROR", "BANNED_DECISION_LEAK", "require%contract", "Decision leak: REQUIRE_CONTRACT is not a reply type. Use D (Deny) with info."),
    
    # === WARN: Suspicious patterns ===
    ("WARN", "SUSPECT_COMPOSITE", "active%local%mods", "Likely drift: active local mods"),
    ("WARN", "SUSPECT_COMPOSITE", "live%local%mods", "Likely drift: live local mods"),
    ("WARN", "SUSPECT_COMPOSITE", "local%mods", "Suspicious: local mods (ensure not a parallel truth)"),
    ("WARN", "SUSPECT_COMPOSITE", "workspace%mods", "Suspicious: workspace mods registry"),
    
    # Exception/fallback patterns (v2.32)
    ("WARN", "SUSPECT_EXCEPTION", "except%permission", "Hiding permission errors (Oracle evasion)"),
    ("WARN", "SUSPECT_EXCEPTION", "except%access", "Hiding access errors (Oracle evasion)"),
    ("WARN", "SUSPECT_FALLBACK", "else%visibility", "Suspect fallback logic using visibility"),
    ("WARN", "SUSPECT_FALLBACK", "else%lens", "Suspect fallback logic using lens"),
]


# =============================================================================
# 3. NEAR WINDOW RULES
# =============================================================================
# Tokens that must NOT appear within N positions of each other
# Tuple: (severity, rule_id, required_tokens, window_size, reason)

NEAR_WINDOW_RULES: list[tuple[str, str, frozenset[str], int, str]] = [
    ("ERROR", "BANNED_NEAR", frozenset({"live", "mods"}), 6, "Parallel truth: live mods (near-match)"),
    ("ERROR", "BANNED_NEAR", frozenset({"active", "mods"}), 6, "Parallel truth: active mods (near-match)"),
    ("ERROR", "BANNED_NEAR", frozenset({"mod", "root"}), 6, "Path oracle: mod root (near-match)"),
    ("ERROR", "BANNED_NEAR", frozenset({"mod", "paths"}), 8, "Path oracle: mod paths (near-match)"),
    ("WARN", "SUSPECT_NEAR", frozenset({"local", "mods"}), 6, "Suspicious: local mods (near-match)"),
]


# =============================================================================
# 4. COMMENT KEYWORDS (v2.32 Comment Intelligence)
# =============================================================================
# Keywords in comments that suggest architectural debt
# Dict: keyword -> warning message

SUSPICIOUS_COMMENT_KEYWORDS: dict[str, str] = {
    "fallback": "Explicit fallback logic detected. Verify architectural compliance.",
    "legacy": "Legacy code marker detected. Schedule for removal.",
    "workaround": "Architectural workaround detected.",
    "hack": "Explicit hack marker detected.",
    "temporary": "Temporary fix marker detected.",
    "fixme": "FIXME marker detected.",
    "xxx": "XXX marker detected.",
    "kludge": "Kludge marker detected.",
}


# =============================================================================
# 5. FORBIDDEN FILENAME PATTERNS (from Phase 1)
# =============================================================================
# Glob patterns for filenames that indicate duplicate policy engines

FORBIDDEN_FILENAME_GLOBS: list[str] = [
    "*gates*.py",
    "*approval*.py",
    "file_policy.py",
    "*policy_engine*.py",
    "hard_gates.py",
]

# Paths where forbidden filenames are allowed (archived code)
FILENAME_ALLOWED_PATHS: list[str] = [
    "archive/",
    "deprecated/",
    "test_",
    "_test.py",
]


# =============================================================================
# 6. PATH PATTERNS (Forbidden Path APIs)
# =============================================================================
# APIs that should only be used in canonical path modules

FORBIDDEN_PATH_APIS_ALWAYS: list[str] = [
    ".relative_to(",
    "os.path.relpath(",
    "posixpath.relpath(",
    "ntpath.relpath(",
]

# Semantic path ops that require WorldAdapter
SEMANTIC_PATH_OPS: list[str] = [
    ".resolve(",
]

# Files allowed to use path APIs
PATH_API_ALLOWLIST_FILES: list[str] = [
    "world_adapter.py",
    "paths.py",
    "path_utils.py",
    "workspace.py",
    "local_mods.py",
    "playset_scope.py",
]

# Directories allowed to use path APIs
PATH_API_ALLOWLIST_DIRS: list[str] = [
    "src/ck3raven/",
    "builder/",
    "scripts/",
    "tests/",
    "tools/lint/",
    "tools/arch_lint/",
]

# Variable names that are allowed to call .resolve()
ALLOWED_RESOLVE_BASE_NAMES: frozenset[str] = frozenset({
    "world",
    "adapter",
    "world_adapter",
    "lens_world",
    "lensworld",
})


# =============================================================================
# 7. ENFORCEMENT PATTERNS (Call-site Restrictions from Phase 1)
# =============================================================================
# Enforcement functions that should only be called at boundaries

ENFORCEMENT_CALL_TOKENS: list[str] = [
    "enforce_policy(",
    "enforce_and_log(",
]

# Modules allowed to call enforcement functions
ENFORCEMENT_CALLER_ALLOWLIST: list[str] = [
    "policy/enforcement.py",
    "unified_tools.py",
    "server.py",
    # script_sandbox.py archived - was never completed
    "tests/",
    "test_",
    "tools/lint/",
    "tools/arch_lint/",
]


# =============================================================================
# 8. I/O PATTERNS (Raw I/O Detection)
# =============================================================================
# Raw I/O calls that should be routed through handles

RAW_IO_NAME_CALLS: frozenset[str] = frozenset({"open"})

RAW_IO_DOTTED_CALLS: frozenset[str] = frozenset({
    # pathlib reads/writes
    "Path.read_text",
    "Path.read_bytes",
    "Path.write_text",
    "Path.write_bytes",
    "Path.open",
    # os
    "os.listdir",
    "os.walk",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "os.mkdir",
    "os.makedirs",
    "os.rename",
    "os.replace",
    # shutil
    "shutil.copy",
    "shutil.copy2",
    "shutil.copytree",
    "shutil.move",
    "shutil.rmtree",
    # glob
    "glob.glob",
    "Path.rglob",
    "Path.glob",
    # subprocess
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
})

# Dangerous I/O only allowed in specific directories (v2.32)
DANGEROUS_IO_TOKENS: frozenset[str] = frozenset({
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "shutil.rmtree",
    "shutil.copy",
    "shutil.move",
    "os.remove",
    "os.unlink",
    "os.rmdir",
})

IO_SAFE_DIRS: frozenset[str] = frozenset({
    "builder",
    "qbuilder",  # The queue-based builder (replaces old builder/)
    "tools",
    "tests",
    "archive",
    "scripts",
    "proofs",  # Verification scripts
})

# Path arithmetic (not I/O, but must be centralized)
PATH_ARITH_DOTTED: frozenset[str] = frozenset({
    "Path.resolve",
    "Path.relative_to",
})

# Modules allowed raw I/O
IO_ALLOWLIST: list[str] = [
    "world_adapter.py",
    "handles/",
    "fs_handle",
    "db_handle",
    "qbuilder/",  # The queue-based builder
]

# Modules allowed mutators (SQL writes, file writes, subprocess)
MUTATOR_ALLOWLIST: list[str] = [
    "builder",
    "build/",
    "qbuilder/",  # The queue-based builder (replaces old builder/)
    "write_handle",
    "mutator_handle",
    "builder_handle",
]


# =============================================================================
# 9. CONTEXT SUPPRESSION
# =============================================================================
# Keywords that indicate we're in documentation/examples (suppress errors)

BANNED_CONTEXT_HINTS: list[str] = [
    "banned",
    "banlist",
    "banned_terms",
    "banned term",
    "banned pattern",
    "forbid",
    "forbidden",
    "do not use",
    "deprecated",
    "arch_lint",
    "example",
    "docs",
    "documentation",
    "readme",
    "anti-pattern",
    "bad example",
    "warning",
    "must not",
    "never do",
]

DEPRECATED_HINTS: list[str] = [
    "deprecated",
    "deprecate",
    "legacy",
    "remove soon",
    "todo: remove",
]


# =============================================================================
# 10. ALLOWLIST EXCEPTIONS
# =============================================================================
# Raw text substrings that are always allowed

RAW_ALLOWLIST_SUBSTRINGS: list[str] = [
    "local_mods_folder",  # canonical allowed
    "scan_playset_conflicts",  # canonical allowed
]

# Token sequences that are allowed
ALLOWLIST_TOKEN_SEQUENCES: list[tuple[str, ...]] = [
    ("local", "mods", "folder"),
]


# =============================================================================
# 11. WAIVER TAG
# =============================================================================
# Inline waiver to suppress specific findings

WAIVER_TAG = "CK3RAVEN_OS_PATH_OK"
