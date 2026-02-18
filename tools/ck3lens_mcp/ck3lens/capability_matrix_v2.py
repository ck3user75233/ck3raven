"""
Capability Matrix v2 — pure data, maximum transparency.

Two matrices, both with conditions:

1. VISIBILITY_MATRIX — can this mode see this (root_key, subdirectory)?
   Consulted by WA v2 on every resolve(). Entry exists = visible, subject to conditions.
   No entry = not visible. Conditions are evaluated with context from WA.

2. MUTATIONS_MATRIX — what mutations are allowed at this (root_key, subdirectory)?
   Each rule carries the exact (tool, command) pairs it governs, plus conditions.
   No entry = mutation denied. Enforcement finds the matching rule and checks conditions.

Plus:

- READ_COMMANDS — explicit list of (tool, command) pairs that are reads.
  Reads need only visibility (WA). No enforcement needed.

- Conditions — standalone named predicates returning True/False, built via factories.
  No denial codes. WA and EN produce their own response codes.
  Modular: swap/add conditions without touching WA or EN.

Enforcement (enforcement_v2.py) walks MUTATIONS_MATRIX.
WA (world_adapter_v2.py) walks VISIBILITY_MATRIX.
This module is data only.

Design brief: docs/Canonical address refactor/v2_enforcement_design_brief.md
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Sequence


# =============================================================================
# CONDITION — frozen named predicate: check(**context) -> bool
# =============================================================================

@dataclass(frozen=True)
class Condition:
    """A named predicate: check(**context) -> bool."""
    name: str
    check: Callable[..., bool]


# =============================================================================
# PATH UTILITIES — used by condition predicates
# =============================================================================

def _as_pure_posix_path(value: str | None) -> PurePosixPath | None:
    """Normalize a path string to PurePosixPath for depth/component checks.

    Strips leading/trailing slashes, normalises backslashes.
    Returns None if value is None or empty after stripping.
    """
    if value is None:
        return None
    cleaned = value.replace("\\", "/").strip("/")
    if not cleaned:
        return None
    return PurePosixPath(cleaned)


def _path_is_safe_relative(p: PurePosixPath) -> bool:
    """Reject absolute or traversal paths.

    Returns False if:
      - The path is absolute
      - Any component is '..'
    """
    if p.is_absolute():
        return False
    if ".." in p.parts:
        return False
    return True


# =============================================================================
# CONDITION FACTORIES
#
# Each factory returns a Condition instance. Conditions are pure bool predicates.
# They receive context kwargs at evaluation time. No side effects, no denial codes.
# WA and EN own their own response codes.
# =============================================================================

def is_subfolder(*, min_depth: int = 1) -> Condition:
    """True if relative_path has at least min_depth path components.

    Uses PurePosixPath for cross-platform depth counting.
    Rejects absolute or traversal paths.

    Context keys:
        relative_path: str | None — the relative path from root
    """
    def _check(*, relative_path: str | None = None, **_: object) -> bool:
        pp = _as_pure_posix_path(relative_path)
        if pp is None:
            return False
        if not _path_is_safe_relative(pp):
            return False
        return len(pp.parts) >= min_depth
    return Condition(name=f"is_subfolder(min_depth={min_depth})", check=_check)


def path_in_session_mods() -> Condition:
    """True if the resolved host path is within (or equal to) any session mod path.

    For mod: addresses (is_mod_address=True), returns True immediately — WA
    already resolved the mod name from session.mods, so it is in-session by
    definition.

    For root: addresses in steam or user_docs/mod, checks host_abs
    containment against session_mod_paths. This naturally excludes:
      - .mod registry files (siblings of mod dirs, not inside them)
      - The mod/ directory itself (parent of mod dirs, not inside them)
      - Mods not in the active session/playset

    Context keys:
        host_abs: Path | None — resolved host-absolute path (from WA)
        session_mod_paths: Sequence[Path] | None — mod paths from session.mods
        is_mod_address: bool — True if input was a mod:Name address
    """
    def _check(
        *,
        host_abs: Path | None = None,
        session_mod_paths: Sequence[Path] | None = None,
        is_mod_address: bool = False,
        **_: object,
    ) -> bool:
        # mod: addresses are in-session by definition
        # (WA already validated mod name against session.mods)
        if is_mod_address:
            return True

        # Path-based check: host_abs must be within a session mod directory
        if host_abs is None or not session_mod_paths:
            return False

        try:
            resolved = host_abs.resolve()
        except (OSError, ValueError):
            return False

        for mod_path in session_mod_paths:
            try:
                resolved.relative_to(mod_path.resolve())
                return True
            except (ValueError, OSError):
                continue
        return False

    return Condition(name="path_in_session_mods", check=_check)


def has_contract() -> Condition:
    """True if has_contract is truthy in context.

    Context keys:
        has_contract: bool
    """
    def _check(*, has_contract: bool = False, **_: object) -> bool:  # noqa: E501
        return bool(has_contract)
    return Condition(name="has_contract", check=_check)


def exec_signed() -> Condition:
    """True if exec_signature_valid is truthy in context.

    Context keys:
        exec_signature_valid: bool
    """
    def _check(*, exec_signature_valid: bool = False, **_: object) -> bool:
        return bool(exec_signature_valid)
    return Condition(name="exec_signed", check=_check)


# =============================================================================
# VISIBILITY RULE — entry exists = visible, conditions must all pass
# =============================================================================

@dataclass(frozen=True)
class VisibilityRule:
    """Conditions that must pass for this location to be visible. Data only."""
    conditions: tuple[Condition, ...] = ()


# =============================================================================
# MUTATION RULE — commands this rule governs + conditions
# =============================================================================

@dataclass(frozen=True)
class MutationRule:
    """
    Exact (tool, command) pairs this rule governs, plus conditions.
    Enforcement finds the rule whose commands contain the (tool, command),
    then checks conditions. Data only.
    """
    commands: frozenset[tuple[str, str]]
    conditions: tuple[Condition, ...] = ()


# =============================================================================
# VALID ROOT KEYS (closed set)
# =============================================================================

VALID_ROOT_KEYS: frozenset[str] = frozenset({
    "repo", "game", "steam", "user_docs", "ck3raven_data", "vscode",
})


# =============================================================================
# VISIBILITY_MATRIX
#
# Key: (mode, root_key, subdirectory | None)
# Entry exists -> visible (subject to conditions). No entry -> not visible.
# WA calls check_visibility() which evaluates conditions with context.
#
# path_in_session_mods() checks host path containment against session.mod.paths:
#   - mod: addresses -> True (WA already validated name against session.mods)
#   - root: addresses -> checks host_abs is within a session mod directory
# =============================================================================

VisibilityKey = tuple[str, str, str | None]

_V = VisibilityRule  # shorthand

# Shared condition instances (created once from factories)
_PATH_IN_SESSION = path_in_session_mods()

VISIBILITY_MATRIX: dict[VisibilityKey, VisibilityRule] = {

    # =================================================================
    # ck3lens mode
    # =================================================================

    # Game and steam root: visible unconditionally
    ("ck3lens", "game", None):              _V(),
    ("ck3lens", "steam", None):             _V(),

    # Steam mod folders: path must be inside a session mod directory
    ("ck3lens", "steam", "mod"):            _V((_PATH_IN_SESSION,)),

    # User docs root: NOT visible (contains .mod registry files)
    # User docs / mod: path must be inside a session mod directory
    # (path_in_session_mods naturally excludes .mod files and the mod/ dir itself)
    ("ck3lens", "user_docs", "mod"):        _V((_PATH_IN_SESSION,)),

    # ck3raven_data: visible unconditionally
    ("ck3lens", "ck3raven_data", None):     _V(),

    # VS Code: visible unconditionally
    ("ck3lens", "vscode", None):            _V(),

    # Repo: visible unconditionally (read-only — no mutation rules)
    ("ck3lens", "repo", None):              _V(),

    # =================================================================
    # ck3raven-dev mode
    # =================================================================

    ("ck3raven-dev", "game", None):             _V(),
    ("ck3raven-dev", "steam", None):            _V(),
    ("ck3raven-dev", "steam", "mod"):           _V((_PATH_IN_SESSION,)),
    ("ck3raven-dev", "user_docs", "mod"):       _V((_PATH_IN_SESSION,)),
    ("ck3raven-dev", "ck3raven_data", None):    _V(),
    ("ck3raven-dev", "vscode", None):           _V(),
    ("ck3raven-dev", "repo", None):             _V(),
}


def check_visibility(
    mode: str,
    root_key: str,
    subdirectory: str | None,
    **context: object,
) -> tuple[bool, list[str]]:
    """
    Check if a location is visible.

    Looks up (mode, root_key, subdirectory) first, then falls back to
    (mode, root_key, None). Returns (False, ["no_entry"]) if no entry.
    Evaluates all conditions with **context — all must pass.

    Returns:
        (True, []) if visible.
        (False, [name, ...]) with names of failed conditions (or ["no_entry"]).
    """
    # Subdirectory-specific lookup first
    if subdirectory:
        rule = VISIBILITY_MATRIX.get((mode, root_key, subdirectory))
        if rule is not None:
            failed = [c.name for c in rule.conditions if not c.check(**context)]
            return (not bool(failed), failed)

    # Fall back to root-level
    rule = VISIBILITY_MATRIX.get((mode, root_key, None))
    if rule is None:
        return (False, ["no_entry"])

    failed = [c.name for c in rule.conditions if not c.check(**context)]
    return (not bool(failed), failed)


# =============================================================================
# READ COMMANDS — explicit (tool, command) pairs that are reads.
# If visible -> allowed. No enforcement needed.
# =============================================================================

READ_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    # ck3_file reads
    ("ck3_file", "read"),
    ("ck3_file", "get"),
    ("ck3_file", "list"),
    ("ck3_file", "refresh"),
    # ck3_dir (all commands are reads)
    ("ck3_dir", "pwd"),
    ("ck3_dir", "cd"),
    ("ck3_dir", "list"),
    ("ck3_dir", "tree"),
    # ck3_git reads
    ("ck3_git", "status"),
    ("ck3_git", "diff"),
    ("ck3_git", "log"),
    # ck3_folder reads
    ("ck3_folder", "list"),
    ("ck3_folder", "contents"),
    ("ck3_folder", "top_level"),
    ("ck3_folder", "mod_folders"),
})


def is_read_command(tool: str, command: str) -> bool:
    """True if this (tool, command) is a read. Reads need only visibility."""
    return (tool, command) in READ_COMMANDS


# =============================================================================
# MUTATIONS_MATRIX
#
# Key: (mode, root_key, subdirectory | None)
# Value: tuple of MutationRules. Each rule carries its command set + conditions.
# Enforcement looks up key, scans rules for matching (tool, command), checks
# conditions. No entry -> mutation denied. No matching command in any rule -> denied.
# =============================================================================

MutationKey = tuple[str, str, str | None]

# --- Shared command sets (avoid repetition in matrix) ---

FILE_WRITE_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    ("ck3_file", "write"),
    ("ck3_file", "edit"),
    ("ck3_file", "rename"),
    ("ck3_file", "create_patch"),
})

FILE_DELETE_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    ("ck3_file", "delete"),
})

FILE_ALL_COMMANDS: frozenset[tuple[str, str]] = FILE_WRITE_COMMANDS | FILE_DELETE_COMMANDS

GIT_MUTATE_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    ("ck3_git", "add"),
    ("ck3_git", "commit"),
    ("ck3_git", "push"),
    ("ck3_git", "pull"),
})

EXEC_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    # ck3_exec has no sub-command; the "command" param is the shell string.
    # find_mutation_rule() special-cases tool="ck3_exec".
})

# Shared condition instances for mutations (created once from factories)
_HAS_CONTRACT = has_contract()
_EXEC_SIGNED = exec_signed()

_R = MutationRule  # shorthand

MUTATIONS_MATRIX: dict[MutationKey, tuple[MutationRule, ...]] = {

    # =================================================================
    # ck3lens mode
    # =================================================================

    # user_docs / mod subfolders: write + delete + git, all need contract
    ("ck3lens", "user_docs", "mod"): (
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
        _R(GIT_MUTATE_COMMANDS, (_HAS_CONTRACT,)),
    ),

    # ck3raven_data / wip: write + delete + exec, NO contract for files
    ("ck3lens", "ck3raven_data", "wip"): (
        _R(FILE_ALL_COMMANDS),          # no contract needed
        _R(EXEC_COMMANDS, (_EXEC_SIGNED,)),
    ),

    # ck3raven_data per-subdirectory: write only, with contract
    ("ck3lens", "ck3raven_data", "config"): (
        _R(FILE_WRITE_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3lens", "ck3raven_data", "playsets"): (
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3lens", "ck3raven_data", "logs"): (
        _R(FILE_WRITE_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3lens", "ck3raven_data", "journal"): (
        _R(FILE_WRITE_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3lens", "ck3raven_data", "cache"): (
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3lens", "ck3raven_data", "artifacts"): (
        _R(FILE_WRITE_COMMANDS, (_HAS_CONTRACT,)),
    ),
    # NOTE: ck3raven_data/db, ck3raven_data/daemon — no mutations in ck3lens

    # =================================================================
    # ck3raven-dev mode
    # =================================================================

    # Repo: full file + git, all with contract
    ("ck3raven-dev", "repo", None): (
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
        _R(GIT_MUTATE_COMMANDS, (_HAS_CONTRACT,)),
    ),

    # ck3raven_data / wip: same as ck3lens
    ("ck3raven-dev", "ck3raven_data", "wip"): (
        _R(FILE_ALL_COMMANDS),
        _R(EXEC_COMMANDS, (_EXEC_SIGNED,)),
    ),

    # ck3raven_data per-subdirectory: full access with contract
    ("ck3raven-dev", "ck3raven_data", "config"): (
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "playsets"): (
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "logs"): (
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "journal"): (
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "cache"): (
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "artifacts"): (
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),

    # VS Code settings: write with contract (no delete)
    ("ck3raven-dev", "vscode", None): (
        _R(FILE_WRITE_COMMANDS, (_HAS_CONTRACT,)),
    ),
}


def find_mutation_rule(
    mode: str,
    root_key: str,
    subdirectory: str | None,
    tool: str,
    command: str,
) -> MutationRule | None:
    """
    Find the MutationRule governing this (tool, command) at this location.

    Looks up (mode, root_key, subdirectory) first, then (mode, root_key, None).
    Scans rules for one whose commands contain (tool, command).
    Returns None if no match -> enforcement should deny.

    Special case: tool="ck3_exec" matches any rule with EXEC_COMMANDS
    (since ck3_exec's "command" param is the shell string, not a subcommand).
    """
    for key in _mutation_keys(mode, root_key, subdirectory):
        rules = MUTATIONS_MATRIX.get(key)
        if rules is None:
            continue
        for rule in rules:
            if tool == "ck3_exec" and rule.commands is EXEC_COMMANDS:
                return rule
            if (tool, command) in rule.commands:
                return rule
    return None


def _mutation_keys(mode: str, root_key: str, subdirectory: str | None):
    """Yield lookup keys: subdirectory-specific first, then root-level."""
    if subdirectory:
        yield (mode, root_key, subdirectory)
    yield (mode, root_key, None)
