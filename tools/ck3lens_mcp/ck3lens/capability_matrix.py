"""
Capability matrix for path enforcement.

THE matrix is THE sole enforcement driver.
No per-domain enforcement functions.

Matrix key: (mode, root, subdirectory)
Capability: set of permitted operations + conditions that must all pass.

Enforcement walks the matrix:
  cap = get_capability(mode, root, subdir, relpath)
  denial = cap.gate(operation, has_contract=...)
  denial is None → allowed, str → denial code
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable

from ck3lens.paths import RootCategory


# =============================================================================
# OPERATION TYPES (the matrix's vocabulary)
# =============================================================================

class OperationType(Enum):
    """Canonical operation types for capability matrix lookup."""
    READ = auto()
    WRITE = auto()
    DELETE = auto()


# Shorthand for matrix entries
R, W, D = OperationType.READ, OperationType.WRITE, OperationType.DELETE


# =============================================================================
# CONDITIONS — extensible predicates that must all hold
# =============================================================================

@dataclass(frozen=True)
class Condition:
    """A named predicate that must hold for an operation to proceed."""
    check: Callable[..., bool]
    denial: str  # code returned if check fails


REQUIRE_CONTRACT = Condition(
    check=lambda has_contract=False, **_: has_contract,
    denial="EN-WRITE-D-002",
)


# =============================================================================
# CAPABILITY
# =============================================================================

@dataclass(frozen=True)
class Capability:
    """
    Set of permitted operations with conditions.

    gate() is the single entry point:
      - operation not in set → EN-WRITE-D-001
      - first failing condition → its denial code
      - all pass → None (allowed)
    """
    operations: frozenset[OperationType] = frozenset()
    conditions: tuple[Condition, ...] = (REQUIRE_CONTRACT,)
    subfolders_writable: bool = False  # get_capability() upgrades ops for nested paths

    def gate(self, operation: OperationType, **context: Any) -> str | None:
        """Returns None if allowed, or the first applicable denial code."""
        if operation not in self.operations:
            return "EN-WRITE-D-001"
        return next(
            (c.denial for c in self.conditions if not c.check(**context)),
            None,
        )


# Type alias for matrix key
MatrixKey = tuple[str, RootCategory, str | None]

# Shorthand capabilities
_RO = Capability(frozenset({R}))   # read-only
_DENY = Capability()               # all denied


# ─────────────────────────────────────────────────────────────────────
# THE CAPABILITY MATRIX
# ─────────────────────────────────────────────────────────────────────

CAPABILITY_MATRIX: dict[MatrixKey, Capability] = {
    # =================================================================
    # ck3lens mode
    # =================================================================
    #
    # Game content (read-only)
    ("ck3lens", RootCategory.ROOT_GAME, None): _RO,
    ("ck3lens", RootCategory.ROOT_STEAM, None): _RO,
    #
    # User docs - read-only by default
    # mod/ subdirectory: subfolders are writable
    ("ck3lens", RootCategory.ROOT_USER_DOCS, None): _RO,
    ("ck3lens", RootCategory.ROOT_USER_DOCS, "mod"): Capability(
        frozenset({R}), subfolders_writable=True,
    ),
    #
    # CK3RAVEN_DATA - per-subdirectory rules
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, None): _RO,
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "config"): Capability(frozenset({R, W})),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "playsets"): Capability(frozenset({R, W, D})),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "wip"): Capability(
        frozenset({R, W, D}), conditions=(),
    ),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "logs"): Capability(frozenset({R, W})),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "journal"): Capability(frozenset({R, W})),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "cache"): Capability(frozenset({R, W, D})),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "db"): _RO,
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "daemon"): _RO,
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "artifacts"): Capability(frozenset({R, W})),
    #
    # VS Code (read-only)
    ("ck3lens", RootCategory.ROOT_VSCODE, None): _RO,
    #
    # Repo / External: denied
    ("ck3lens", RootCategory.ROOT_REPO, None): _DENY,
    ("ck3lens", RootCategory.ROOT_EXTERNAL, None): _DENY,
    #
    # =================================================================
    # ck3raven-dev mode
    # =================================================================
    #
    # Repo - full access
    ("ck3raven-dev", RootCategory.ROOT_REPO, None): Capability(frozenset({R, W, D})),
    #
    # Game content (read-only)
    ("ck3raven-dev", RootCategory.ROOT_GAME, None): _RO,
    ("ck3raven-dev", RootCategory.ROOT_STEAM, None): _RO,
    #
    # User docs - read-only in dev mode
    ("ck3raven-dev", RootCategory.ROOT_USER_DOCS, None): _RO,
    ("ck3raven-dev", RootCategory.ROOT_USER_DOCS, "mod"): _RO,
    #
    # CK3RAVEN_DATA - per-subdirectory rules
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, None): _RO,
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "config"): Capability(frozenset({R, W, D})),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "playsets"): Capability(frozenset({R, W, D})),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "wip"): Capability(
        frozenset({R, W, D}), conditions=(),
    ),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "logs"): Capability(frozenset({R, W, D})),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "journal"): Capability(frozenset({R, W, D})),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "cache"): Capability(frozenset({R, W, D})),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "db"): _RO,
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "daemon"): _RO,
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "artifacts"): Capability(frozenset({R, W, D})),
    #
    # VS Code - write settings (no delete)
    ("ck3raven-dev", RootCategory.ROOT_VSCODE, None): Capability(frozenset({R, W})),
    #
    # External always denied
    ("ck3raven-dev", RootCategory.ROOT_EXTERNAL, None): _DENY,
}


def get_capability(
    mode: str,
    root: RootCategory,
    subdirectory: str | None = None,
    relative_path: str | None = None,
) -> Capability:
    """
    Look up capability from matrix.

    For ROOT_CK3RAVEN_DATA and ROOT_USER_DOCS:
    - Checks (mode, root, subdirectory) first
    - Falls back to (mode, root, None) for root-level default

    For entries with subfolders_writable=True:
    - Nested path → upgrades operations to include W+D
    - Shallow path → base capability (read-only)

    Returns _DENY if no entry found (default deny).
    """
    subdir_roots = (RootCategory.ROOT_CK3RAVEN_DATA, RootCategory.ROOT_USER_DOCS)

    if root in subdir_roots and subdirectory:
        key = (mode, root, subdirectory)
        if key in CAPABILITY_MATRIX:
            cap = CAPABILITY_MATRIX[key]

            # Upgrade operations for nested paths when subfolders_writable
            if cap.subfolders_writable and relative_path:
                parts = relative_path.replace("\\", "/").strip("/").split("/")
                if len(parts) >= 3:
                    return Capability(
                        operations=cap.operations | frozenset({W, D}),
                        conditions=cap.conditions,
                    )

            return cap

    key = (mode, root, None)
    return CAPABILITY_MATRIX.get(key, _DENY)
