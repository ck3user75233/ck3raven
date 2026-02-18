"""
Capability Matrix v2 — pure data, maximum transparency.

Three data structures:

1. VISIBILITY_MATRIX — binary: can this mode see this root key?
   Consulted by WA v2 on every resolve(). If visible, any read command works.

2. COMMAND CLASSIFICATION — explicit (tool, command) → category.
   Declares exactly which tool+command combos are reads vs mutations.
   Read commands need only visibility. Mutation commands need MUTATIONS_MATRIX.

3. MUTATIONS_MATRIX — what mutations are allowed, with what conditions?
   Only mutation entries. No read-only entries. Keyed by (mode, category, root_key, subdirectory).
   Category labels map 1:1 to explicit command membership defined in MUTATION_CATEGORIES.

Enforcement (enforcement_v2.py) walks these structures. This module is data only.

Design brief: docs/Canonical address refactor/v2_enforcement_design_brief.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


# =============================================================================
# CONDITIONS — standalone predicates
# =============================================================================

@dataclass(frozen=True)
class Condition:
    """A named predicate: check(**context) must return True, else denial code applies."""
    name: str
    check: Callable[..., bool]
    denial: str


VALID_CONTRACT = Condition(
    name="contract",
    check=lambda has_contract=False, **_: has_contract,
    denial="EN-WRITE-D-002",
)

EXEC_SIGNED = Condition(
    name="exec_signed",
    check=lambda exec_signature_valid=False, **_: exec_signature_valid,
    denial="EN-EXEC-D-001",
)


# =============================================================================
# MUTATION RULE — conditions only (if entry exists, mutation is known)
# =============================================================================

@dataclass(frozen=True)
class MutationRule:
    """Conditions required for a mutation to proceed. Data only."""
    conditions: tuple[Condition, ...] = ()


# =============================================================================
# VISIBILITY_MATRIX — binary: can this mode see this root key?
# =============================================================================

# Valid v2 root keys (closed set)
VALID_ROOT_KEYS: frozenset[str] = frozenset({
    "repo", "game", "steam", "user_docs", "ck3raven_data", "vscode",
})

VISIBILITY_MATRIX: dict[tuple[str, str], bool] = {
    # ck3lens — sees everything
    ("ck3lens", "game"):           True,
    ("ck3lens", "steam"):          True,
    ("ck3lens", "user_docs"):      True,
    ("ck3lens", "ck3raven_data"):  True,
    ("ck3lens", "vscode"):         True,
    ("ck3lens", "repo"):           True,

    # ck3raven-dev — sees everything
    ("ck3raven-dev", "game"):           True,
    ("ck3raven-dev", "steam"):          True,
    ("ck3raven-dev", "user_docs"):      True,
    ("ck3raven-dev", "ck3raven_data"):  True,
    ("ck3raven-dev", "vscode"):         True,
    ("ck3raven-dev", "repo"):           True,
}


def is_visible(mode: str, root_key: str) -> bool:
    """Pure lookup. False for unknown combinations."""
    return VISIBILITY_MATRIX.get((mode, root_key), False)


# =============================================================================
# COMMAND CLASSIFICATION — explicit (tool, command) membership
# =============================================================================

# Read-only commands. If visible → allowed. No enforcement needed.
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

# Mutation categories — each label maps to exact (tool, command) pairs.
# The label is the MUTATIONS_MATRIX key dimension.
MUTATION_CATEGORIES: dict[str, frozenset[tuple[str, str]]] = {
    "file_write": frozenset({
        ("ck3_file", "write"),
        ("ck3_file", "edit"),
        ("ck3_file", "rename"),
        ("ck3_file", "create_patch"),
    }),
    "file_delete": frozenset({
        ("ck3_file", "delete"),
    }),
    "git_mutate": frozenset({
        ("ck3_git", "add"),
        ("ck3_git", "commit"),
        ("ck3_git", "push"),
        ("ck3_git", "pull"),
    }),
    "exec": frozenset({
        # ck3_exec has no sub-command; the "command" param is the shell string.
        # classify_command() special-cases tool="ck3_exec" → "exec".
    }),
}

# Reverse lookup: (tool, command) → category label
_COMMAND_TO_CATEGORY: dict[tuple[str, str], str] = {}
for _cat, _cmds in MUTATION_CATEGORIES.items():
    for _cmd in _cmds:
        _COMMAND_TO_CATEGORY[_cmd] = _cat


def classify_command(tool: str, command: str) -> str | None:
    """
    Classify a (tool, command) pair.

    Returns:
        "read"          — handled by visibility, no enforcement needed
        category label  — look up in MUTATIONS_MATRIX
        None            — unknown command, enforcement should deny
    """
    if (tool, command) in READ_COMMANDS:
        return "read"
    # ck3_exec is always "exec" regardless of command string
    if tool == "ck3_exec":
        return "exec"
    return _COMMAND_TO_CATEGORY.get((tool, command))


# =============================================================================
# MUTATIONS_MATRIX — what mutations are allowed, with what conditions?
#
# Key: (mode, category, root_key, subdirectory | None)
# Only mutation entries. Reads are NOT here — visibility handles them.
# If no entry → mutation is DENIED.
# =============================================================================

MutationKey = tuple[str, str, str, str | None]

_C = MutationRule  # shorthand for readability

MUTATIONS_MATRIX: dict[MutationKey, MutationRule] = {

    # =================================================================
    # ck3lens mode — file writes
    # =================================================================
    ("ck3lens", "file_write", "user_docs", "mod"):              _C((VALID_CONTRACT,)),
    ("ck3lens", "file_write", "ck3raven_data", "wip"):          _C(),  # no contract needed
    ("ck3lens", "file_write", "ck3raven_data", "config"):       _C((VALID_CONTRACT,)),
    ("ck3lens", "file_write", "ck3raven_data", "playsets"):     _C((VALID_CONTRACT,)),
    ("ck3lens", "file_write", "ck3raven_data", "logs"):         _C((VALID_CONTRACT,)),
    ("ck3lens", "file_write", "ck3raven_data", "journal"):      _C((VALID_CONTRACT,)),
    ("ck3lens", "file_write", "ck3raven_data", "cache"):        _C((VALID_CONTRACT,)),
    ("ck3lens", "file_write", "ck3raven_data", "artifacts"):    _C((VALID_CONTRACT,)),

    # ck3lens — file deletes
    ("ck3lens", "file_delete", "user_docs", "mod"):             _C((VALID_CONTRACT,)),
    ("ck3lens", "file_delete", "ck3raven_data", "wip"):         _C(),
    ("ck3lens", "file_delete", "ck3raven_data", "playsets"):    _C((VALID_CONTRACT,)),
    ("ck3lens", "file_delete", "ck3raven_data", "cache"):       _C((VALID_CONTRACT,)),
    # NOTE: config, logs, journal, artifacts, db, daemon — no delete in ck3lens

    # ck3lens — exec
    ("ck3lens", "exec", "ck3raven_data", "wip"):                _C((EXEC_SIGNED,)),

    # ck3lens — git mutations
    ("ck3lens", "git_mutate", "user_docs", "mod"):              _C((VALID_CONTRACT,)),

    # =================================================================
    # ck3raven-dev mode — file writes
    # =================================================================
    ("ck3raven-dev", "file_write", "repo", None):               _C((VALID_CONTRACT,)),
    ("ck3raven-dev", "file_write", "ck3raven_data", "wip"):     _C(),
    ("ck3raven-dev", "file_write", "ck3raven_data", "config"):  _C((VALID_CONTRACT,)),
    ("ck3raven-dev", "file_write", "ck3raven_data", "playsets"):_C((VALID_CONTRACT,)),
    ("ck3raven-dev", "file_write", "ck3raven_data", "logs"):    _C((VALID_CONTRACT,)),
    ("ck3raven-dev", "file_write", "ck3raven_data", "journal"): _C((VALID_CONTRACT,)),
    ("ck3raven-dev", "file_write", "ck3raven_data", "cache"):   _C((VALID_CONTRACT,)),
    ("ck3raven-dev", "file_write", "ck3raven_data", "artifacts"):_C((VALID_CONTRACT,)),
    ("ck3raven-dev", "file_write", "vscode", None):             _C((VALID_CONTRACT,)),

    # ck3raven-dev — file deletes
    ("ck3raven-dev", "file_delete", "repo", None):              _C((VALID_CONTRACT,)),
    ("ck3raven-dev", "file_delete", "ck3raven_data", "wip"):    _C(),
    ("ck3raven-dev", "file_delete", "ck3raven_data", "config"): _C((VALID_CONTRACT,)),
    ("ck3raven-dev", "file_delete", "ck3raven_data", "playsets"):_C((VALID_CONTRACT,)),
    ("ck3raven-dev", "file_delete", "ck3raven_data", "logs"):   _C((VALID_CONTRACT,)),
    ("ck3raven-dev", "file_delete", "ck3raven_data", "journal"):_C((VALID_CONTRACT,)),
    ("ck3raven-dev", "file_delete", "ck3raven_data", "cache"):  _C((VALID_CONTRACT,)),
    ("ck3raven-dev", "file_delete", "ck3raven_data", "artifacts"):_C((VALID_CONTRACT,)),

    # ck3raven-dev — exec
    ("ck3raven-dev", "exec", "ck3raven_data", "wip"):           _C((EXEC_SIGNED,)),

    # ck3raven-dev — git mutations
    ("ck3raven-dev", "git_mutate", "repo", None):               _C((VALID_CONTRACT,)),
}
