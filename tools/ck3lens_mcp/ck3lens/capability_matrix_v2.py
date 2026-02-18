"""
Capability Matrix v2 — pure data, maximum transparency.

Two matrices, both with conditions:

1. VISIBILITY_MATRIX — can this mode see this (root_key, subdirectory)?
   Consulted by WA v2 on every resolve(). Entry exists = visible, subject to conditions.
   No entry = not visible. Conditions are checked by WA at resolve time.

2. MUTATIONS_MATRIX — what mutations are allowed at this (root_key, subdirectory)?
   Each rule carries the exact (tool, command) pairs it governs, plus conditions.
   No entry = mutation denied. Enforcement finds the matching rule and checks conditions.

Plus:

- READ_COMMANDS — explicit list of (tool, command) pairs that are reads.
  Reads need only visibility (WA). No enforcement needed.

- Conditions — standalone named predicates returning True/False.
  No denial codes. WA and EN produce their own response codes.
  Modular: swap/add conditions without touching WA or EN.

Enforcement (enforcement_v2.py) walks MUTATIONS_MATRIX.
WA (world_adapter_v2.py) walks VISIBILITY_MATRIX.
This module is data only.

Design brief: docs/Canonical address refactor/v2_enforcement_design_brief.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


# =============================================================================
# CONDITIONS — standalone predicates, return True/False
#
# Each condition is a named function. WA and EN decide their own response
# codes when a condition fails. Conditions don't know about denial codes.
# =============================================================================

@dataclass(frozen=True)
class Condition:
    """A named predicate: check(**context) -> bool."""
    name: str
    check: Callable[..., bool]


# --- Visibility conditions ---

MOD_IN_SESSION = Condition(
    name="mod_in_session",
    check=lambda mod_name=None, session_mods=None, **_: (
        mod_name is not None
        and session_mods is not None
        and mod_name in session_mods
    ),
)

IS_SUBFOLDER = Condition(
    name="is_subfolder",
    check=lambda relative_path=None, **_: (
        relative_path is not None
        and "/" in relative_path.strip("/")
    ),
)

# --- Mutation conditions ---

HAS_CONTRACT = Condition(
    name="has_contract",
    check=lambda has_contract=False, **_: has_contract,
)

EXEC_SIGNED = Condition(
    name="exec_signed",
    check=lambda exec_signature_valid=False, **_: exec_signature_valid,
)


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
# =============================================================================

VisibilityKey = tuple[str, str, str | None]

_V = VisibilityRule  # shorthand

VISIBILITY_MATRIX: dict[VisibilityKey, VisibilityRule] = {

    # =================================================================
    # ck3lens mode
    # =================================================================

    # Game and steam: visible unconditionally
    ("ck3lens", "game", None):              _V(),
    ("ck3lens", "steam", None):             _V(),

    # Steam mod folders: only mods in session.mods are visible
    ("ck3lens", "steam", "mod"):            _V((MOD_IN_SESSION,)),

    # User docs root: NOT visible (contains .mod registry files)
    # User docs / mod subfolders: visible if mod in session AND path is a subfolder
    ("ck3lens", "user_docs", "mod"):        _V((IS_SUBFOLDER, MOD_IN_SESSION)),

    # ck3raven_data: visible unconditionally
    ("ck3lens", "ck3raven_data", None):     _V(),

    # VS Code: visible unconditionally
    ("ck3lens", "vscode", None):            _V(),

    # Repo: visible unconditionally (read-only -- no mutation rules)
    ("ck3lens", "repo", None):              _V(),

    # =================================================================
    # ck3raven-dev mode
    # =================================================================

    ("ck3raven-dev", "game", None):             _V(),
    ("ck3raven-dev", "steam", None):            _V(),
    ("ck3raven-dev", "steam", "mod"):           _V((MOD_IN_SESSION,)),
    ("ck3raven-dev", "user_docs", "mod"):       _V((IS_SUBFOLDER, MOD_IN_SESSION)),
    ("ck3raven-dev", "ck3raven_data", None):    _V(),
    ("ck3raven-dev", "vscode", None):           _V(),
    ("ck3raven-dev", "repo", None):             _V(),
}


def check_visibility(mode: str, root_key: str, subdirectory: str | None, **context) -> bool:
    """
    Check if a location is visible.

    Looks up (mode, root_key, subdirectory) first, then falls back to
    (mode, root_key, None). Returns False if no entry.
    Evaluates all conditions with **context -- all must pass.
    """
    # Subdirectory-specific lookup first
    if subdirectory:
        rule = VISIBILITY_MATRIX.get((mode, root_key, subdirectory))
        if rule is not None:
            return all(c.check(**context) for c in rule.conditions)

    # Fall back to root-level
    rule = VISIBILITY_MATRIX.get((mode, root_key, None))
    if rule is None:
        return False

    return all(c.check(**context) for c in rule.conditions)


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
# Enforcement looks up key, scans rules for matching (tool, command), checks conditions.
# No entry -> mutation denied. No matching command in any rule -> denied.
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

_R = MutationRule  # shorthand

MUTATIONS_MATRIX: dict[MutationKey, tuple[MutationRule, ...]] = {

    # =================================================================
    # ck3lens mode
    # =================================================================

    # user_docs / mod subfolders: write + delete + git, all need contract
    ("ck3lens", "user_docs", "mod"): (
        _R(FILE_ALL_COMMANDS, (HAS_CONTRACT,)),
        _R(GIT_MUTATE_COMMANDS, (HAS_CONTRACT,)),
    ),

    # ck3raven_data / wip: write + delete + exec, NO contract for files
    ("ck3lens", "ck3raven_data", "wip"): (
        _R(FILE_ALL_COMMANDS),          # no contract needed
        _R(EXEC_COMMANDS, (EXEC_SIGNED,)),
    ),

    # ck3raven_data per-subdirectory: write only, with contract
    ("ck3lens", "ck3raven_data", "config"): (
        _R(FILE_WRITE_COMMANDS, (HAS_CONTRACT,)),
    ),
    ("ck3lens", "ck3raven_data", "playsets"): (
        _R(FILE_ALL_COMMANDS, (HAS_CONTRACT,)),
    ),
    ("ck3lens", "ck3raven_data", "logs"): (
        _R(FILE_WRITE_COMMANDS, (HAS_CONTRACT,)),
    ),
    ("ck3lens", "ck3raven_data", "journal"): (
        _R(FILE_WRITE_COMMANDS, (HAS_CONTRACT,)),
    ),
    ("ck3lens", "ck3raven_data", "cache"): (
        _R(FILE_ALL_COMMANDS, (HAS_CONTRACT,)),
    ),
    ("ck3lens", "ck3raven_data", "artifacts"): (
        _R(FILE_WRITE_COMMANDS, (HAS_CONTRACT,)),
    ),
    # NOTE: ck3raven_data/db, ck3raven_data/daemon -- no mutations in ck3lens

    # =================================================================
    # ck3raven-dev mode
    # =================================================================

    # Repo: full file + git, all with contract
    ("ck3raven-dev", "repo", None): (
        _R(FILE_ALL_COMMANDS, (HAS_CONTRACT,)),
        _R(GIT_MUTATE_COMMANDS, (HAS_CONTRACT,)),
    ),

    # ck3raven_data / wip: same as ck3lens
    ("ck3raven-dev", "ck3raven_data", "wip"): (
        _R(FILE_ALL_COMMANDS),
        _R(EXEC_COMMANDS, (EXEC_SIGNED,)),
    ),

    # ck3raven_data per-subdirectory: full access with contract
    ("ck3raven-dev", "ck3raven_data", "config"): (
        _R(FILE_ALL_COMMANDS, (HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "playsets"): (
        _R(FILE_ALL_COMMANDS, (HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "logs"): (
        _R(FILE_ALL_COMMANDS, (HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "journal"): (
        _R(FILE_ALL_COMMANDS, (HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "cache"): (
        _R(FILE_ALL_COMMANDS, (HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "artifacts"): (
        _R(FILE_ALL_COMMANDS, (HAS_CONTRACT,)),
    ),

    # VS Code settings: write with contract (no delete)
    ("ck3raven-dev", "vscode", None): (
        _R(FILE_WRITE_COMMANDS, (HAS_CONTRACT,)),
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
