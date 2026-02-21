"""
Capability Matrix v2 — pure data, maximum transparency.

Two matrices, both with conditions:

1. VISIBILITY_MATRIX — can this mode see this (root_key, subdirectory)?
   Consulted by WA v2 on every resolve(). Entry exists = visible, subject to conditions.
   No entry = not visible. Conditions are evaluated with context from WA.

2. OPERATIONS_MATRIX — what operations are allowed at this (root_key, subdirectory)?
   Each rule carries the exact (tool, command) pairs it governs, plus conditions.
   No entry = operation denied. Enforcement finds the matching rule and checks conditions.
   Reads are rules with no conditions (always allowed if visible).
   Mutations carry conditions (e.g. has_contract, exec_signed).

Plus:

- Conditions — standalone named predicates returning True/False, built via factories.
  No denial codes. WA and EN produce their own response codes.
  Modular: swap/add conditions without touching WA or EN.
  Session-level: conditions check session.mods, not host paths.

Enforcement (enforcement_v2.py) walks OPERATIONS_MATRIX for ALL operations (reads and mutations).
WA (world_adapter_v2.py) walks VISIBILITY_MATRIX.
This module is data only (conditions may call sigil_verify for cryptographic checks).

Design brief: docs/Canonical address refactor/v2_enforcement_design_brief.md
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


# =============================================================================
# CONDITION — frozen named predicate: check(**context) -> bool
# =============================================================================

@dataclass(frozen=True)
class Condition:
    """A named predicate: check(**context) -> bool."""
    name: str
    check: Callable[..., bool]


# =============================================================================
# CONDITION FACTORIES
#
# Each factory returns a Condition instance. Conditions are pure bool predicates.
# They receive context kwargs at evaluation time. No side effects, no denial codes.
# WA and EN own their own response codes.
# =============================================================================

def mod_in_session() -> Condition:
    """True if the addressed mod is in session.mods.

    Pure session-level check — no host path containment.
    WA passes mod_name (display name) from the mod: address.
    Checked via session.get_mod(mod_name).

    Context keys:
        session: Session | None — the session object (has .mods, .get_mod())
        mod_name: str | None — mod display name (from mod: address)
    """
    def _check(
        *,
        session: object | None = None,
        mod_name: str | None = None,
        **_: object,
    ) -> bool:
        if session is None or not mod_name:
            return False
        mods = getattr(session, 'mods', None)
        if not mods:
            return False

        get_mod = getattr(session, 'get_mod', None)
        if get_mod:
            return get_mod(mod_name) is not None
        return any(getattr(m, 'name', None) == mod_name for m in mods)

    return Condition(name="mod_in_session", check=_check)


def has_contract() -> Condition:
    """True if has_contract is truthy in context.

    Context keys:
        has_contract: bool
    """
    def _check(*, has_contract: bool = False, **_: object) -> bool:  # noqa: E501
        return bool(has_contract)
    return Condition(name="has_contract", check=_check)


def path_in_session_mods() -> Condition:
    """True if host_abs is inside or equal to any session.mods entry's path.

    For ck3lens mode: gates root:steam and root:user_docs/mod visibility
    so only paths within active playset mods are visible — not arbitrary
    paths under those roots.

    WA already converted the session_abs to host_abs during parsing.
    This condition compares that host_abs against session.mods[*].path
    (which are host-absolute).

    Context keys:
        session: Session | None — the session object (has .mods)
        host_abs: Path | None — resolved host-absolute path from WA
    """
    def _check(
        *,
        session: object | None = None,
        host_abs: object | None = None,
        **_: object,
    ) -> bool:
        if session is None or host_abs is None:
            return False
        mods = getattr(session, 'mods', None)
        if not mods:
            return False

        resolved = Path(str(host_abs)).resolve() if not isinstance(host_abs, Path) else host_abs.resolve()

        for mod in mods:
            mod_path = getattr(mod, 'path', None)
            if mod_path is None:
                continue
            mp = Path(str(mod_path)).resolve() if not isinstance(mod_path, Path) else mod_path.resolve()
            try:
                resolved.relative_to(mp)
                return True
            except (ValueError, OSError):
                continue
        return False

    return Condition(name="path_in_session_mods", check=_check)


def exec_signed() -> Condition:
    """True if the active contract has a valid script signature for this script.

    Inline cryptographic validation:
    1. Loads the active contract (get_active_contract)
    2. Checks contract.script_signature exists
    3. Validates script_path, content_sha256, and HMAC signature match

    NOT a permission oracle — this is a predicate called BY enforcement
    as part of walking the capability matrix. Enforcement makes the
    allow/deny decision based on this predicate's True/False return.

    Context keys:
        script_host_path: str | None — absolute host path to the script
        content_sha256: str | None — current SHA-256 of script content
    """
    def _check(
        *,
        script_host_path: str | None = None,
        content_sha256: str | None = None,
        **_: object,
    ) -> bool:
        if not script_host_path or not content_sha256:
            return False

        from ck3lens.policy.contract_v1 import get_active_contract, validate_script_signature

        contract = get_active_contract()
        if contract is None:
            return False

        return validate_script_signature(contract, script_host_path, content_sha256)

    return Condition(name="exec_signed", check=_check)


# =============================================================================
# VISIBILITY RULE — entry exists = visible, conditions must all pass
# =============================================================================

@dataclass(frozen=True)
class VisibilityRule:
    """Conditions that must pass for this location to be visible. Data only."""
    conditions: tuple[Condition, ...] = ()


# =============================================================================
# OPERATION RULE — commands this rule governs + conditions
# =============================================================================

@dataclass(frozen=True)
class OperationRule:
    """
    Exact (tool, command) pairs this rule governs, plus conditions.
    Enforcement finds the rule whose commands contain the (tool, command),
    then checks conditions. Data only.

    Reads: rules with no conditions (always allowed if visible).
    Mutations: rules with conditions (e.g. has_contract, exec_signed).
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
# Conditions on individual entries can further restrict visibility
# (e.g., requiring a mod to be in session.mods). WA passes context
# kwargs that conditions can inspect.
# =============================================================================

VisibilityKey = tuple[str, str, str | None]

_V = VisibilityRule  # shorthand

# Shared condition instance for mod path gating
_PATH_IN_MODS = path_in_session_mods()

VISIBILITY_MATRIX: dict[VisibilityKey, VisibilityRule] = {

    # =================================================================
    # ck3lens mode
    #
    # steam and user_docs/mod carry a path_in_session_mods condition:
    # the resolved path must fall within a session.mods entry.
    # Bare root:steam or root:user_docs → invisible (no entry / no match).
    # root:user_docs without "mod" subdirectory → no entry → invisible.
    # =================================================================

    ("ck3lens", "game", None):              _V(),
    ("ck3lens", "steam", None):             _V((_PATH_IN_MODS,)),
    ("ck3lens", "user_docs", "mod"):        _V((_PATH_IN_MODS,)),
    ("ck3lens", "ck3raven_data", None):     _V(),
    ("ck3lens", "vscode", None):            _V(),
    ("ck3lens", "repo", None):              _V(),

    # =================================================================
    # ck3raven-dev mode
    # =================================================================

    ("ck3raven-dev", "game", None):             _V(),
    ("ck3raven-dev", "steam", None):            _V(),
    ("ck3raven-dev", "user_docs", None):        _V(),
    ("ck3raven-dev", "ck3raven_data", None):    _V(),
    ("ck3raven-dev", "vscode", None):           _V(),
    ("ck3raven-dev", "repo", None):             _V(),
}


def check_visibility(
    mode: str,
    root_key: str,
    subdirectory: str | None,
    *,
    session: object | None = None,
    host_abs: Path | None = None,
) -> tuple[bool, list[str]]:
    """
    Check if a location is visible.

    Matrix lookup:
        (mode, root_key, subdirectory) first, falls back to
        (mode, root_key, None). No entry → not visible.
        If entry has conditions, they must all pass.

    Args:
        host_abs: Resolved host-absolute path. Passed to conditions
                  that need path comparison (e.g. path_in_session_mods).

    Returns:
        (True, []) if visible.
        (False, [reason, ...]) with failure reasons.
    """
    context: dict[str, object] = {"session": session, "host_abs": host_abs}

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
# OPERATIONS_MATRIX
#
# Key: (mode, root_key, subdirectory | None)
# Value: tuple of OperationRules. Each rule carries its command set + conditions.
# Enforcement looks up key, scans rules for matching (tool, command), checks
# conditions. No entry -> operation denied. No matching command in any rule -> denied.
#
# ALL operations go through this matrix — reads AND mutations. No bypass branches.
# =============================================================================

OperationKey = tuple[str, str, str | None]


# --- Read command sets (no conditions — always allowed if visible) ---

FILE_READ_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    ("ck3_file", "read"),
    ("ck3_file", "get"),
    ("ck3_file", "list"),
    ("ck3_file", "refresh"),
})

DIR_READ_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    ("ck3_dir", "pwd"),
    ("ck3_dir", "cd"),
    ("ck3_dir", "list"),
    ("ck3_dir", "tree"),
})

GIT_READ_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    ("ck3_git", "status"),
    ("ck3_git", "diff"),
    ("ck3_git", "log"),
})

FOLDER_READ_COMMANDS: frozenset[tuple[str, str]] = frozenset({
    ("ck3_folder", "list"),
    ("ck3_folder", "contents"),
    ("ck3_folder", "top_level"),
    ("ck3_folder", "mod_folders"),
})

ALL_READ_COMMANDS: frozenset[tuple[str, str]] = (
    FILE_READ_COMMANDS | DIR_READ_COMMANDS | GIT_READ_COMMANDS | FOLDER_READ_COMMANDS
)

# --- Mutation command sets ---

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
    # find_operation_rule() special-cases tool="ck3_exec".
})

# Shared condition instances (created once from factories)
_HAS_CONTRACT = has_contract()
_EXEC_SIGNED = exec_signed()

# Shared read rule — no conditions, always allowed if visible
_READS = OperationRule(ALL_READ_COMMANDS)

_R = OperationRule  # shorthand

OPERATIONS_MATRIX: dict[OperationKey, tuple[OperationRule, ...]] = {

    # =================================================================
    # ck3lens mode
    # =================================================================

    # Game: read-only
    ("ck3lens", "game", None): (
        _READS,
    ),

    # Steam root: read-only
    ("ck3lens", "steam", None): (
        _READS,
    ),

    # Steam mod folders: read-only (visibility already checks session mod roots)
    ("ck3lens", "steam", "mod"): (
        _READS,
    ),

    # User docs / mod: reads + writes + git, mutations need contract
    ("ck3lens", "user_docs", "mod"): (
        _READS,
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
        _R(GIT_MUTATE_COMMANDS, (_HAS_CONTRACT,)),
    ),

    # ck3raven_data root: read-only
    ("ck3lens", "ck3raven_data", None): (
        _READS,
    ),

    # ck3raven_data / wip: reads + writes + exec
    ("ck3lens", "ck3raven_data", "wip"): (
        _READS,
        _R(FILE_ALL_COMMANDS),          # no contract needed
        _R(EXEC_COMMANDS, (_EXEC_SIGNED,)),
    ),

    # ck3raven_data / playsets: reads + writes with contract
    ("ck3lens", "ck3raven_data", "playsets"): (
        _READS,
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),

    # VS Code: read-only
    ("ck3lens", "vscode", None): (
        _READS,
    ),

    # Repo: read-only
    ("ck3lens", "repo", None): (
        _READS,
    ),

    # =================================================================
    # ck3raven-dev mode
    # =================================================================

    # Game: read-only
    ("ck3raven-dev", "game", None): (
        _READS,
    ),

    # Steam root: read-only
    ("ck3raven-dev", "steam", None): (
        _READS,
    ),

    # Steam mod folders: read-only
    ("ck3raven-dev", "steam", "mod"): (
        _READS,
    ),

    # User docs / mod: reads + writes + git
    ("ck3raven-dev", "user_docs", "mod"): (
        _READS,
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
        _R(GIT_MUTATE_COMMANDS, (_HAS_CONTRACT,)),
    ),

    # ck3raven_data root: read-only
    ("ck3raven-dev", "ck3raven_data", None): (
        _READS,
    ),

    # Repo: full file + git, all with contract
    ("ck3raven-dev", "repo", None): (
        _READS,
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
        _R(GIT_MUTATE_COMMANDS, (_HAS_CONTRACT,)),
    ),

    # ck3raven_data / wip: same as ck3lens
    ("ck3raven-dev", "ck3raven_data", "wip"): (
        _READS,
        _R(FILE_ALL_COMMANDS),
        _R(EXEC_COMMANDS, (_EXEC_SIGNED,)),
    ),

    # ck3raven_data per-subdirectory: full access with contract
    ("ck3raven-dev", "ck3raven_data", "config"): (
        _READS,
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "playsets"): (
        _READS,
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "logs"): (
        _READS,
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "journal"): (
        _READS,
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "cache"): (
        _READS,
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),
    ("ck3raven-dev", "ck3raven_data", "artifacts"): (
        _READS,
        _R(FILE_ALL_COMMANDS, (_HAS_CONTRACT,)),
    ),

    # VS Code settings: reads + write with contract (no delete)
    ("ck3raven-dev", "vscode", None): (
        _READS,
        _R(FILE_WRITE_COMMANDS, (_HAS_CONTRACT,)),
    ),
}


def find_operation_rule(
    mode: str,
    root_key: str,
    subdirectory: str | None,
    tool: str,
    command: str,
) -> OperationRule | None:
    """
    Find the OperationRule governing this (tool, command) at this location.

    Looks up (mode, root_key, subdirectory) first, then (mode, root_key, None).
    Scans rules for one whose commands contain (tool, command).
    Returns None if no match -> enforcement should deny.

    Special case: tool="ck3_exec" matches any rule with EXEC_COMMANDS
    (since ck3_exec's "command" param is the shell string, not a subcommand).
    """
    for key in _operation_keys(mode, root_key, subdirectory):
        rules = OPERATIONS_MATRIX.get(key)
        if rules is None:
            continue
        for rule in rules:
            if tool == "ck3_exec" and rule.commands is EXEC_COMMANDS:
                return rule
            if (tool, command) in rule.commands:
                return rule
    return None


def _operation_keys(mode: str, root_key: str, subdirectory: str | None):
    """Yield lookup keys: subdirectory-specific first, then root-level."""
    if subdirectory:
        yield (mode, root_key, subdirectory)
    yield (mode, root_key, None)

