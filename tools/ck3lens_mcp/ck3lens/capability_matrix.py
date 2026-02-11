"""
Capability matrix for path enforcement.

THE matrix is THE sole enforcement driver.
No per-domain enforcement functions.

Matrix key: (mode, root, subdirectory)
- For ROOT_CK3RAVEN_DATA, subdirectory is significant
- For ROOT_USER_DOCS, mod/ uses subfolders_writable (contents of mod subfolders are writable)
- For all other roots, subdirectory is None

Global invariants OVERRIDE the matrix (enforced in enforcement.py):
1. Contract required for write/delete
2. db/ and daemon/ subdirs are NEVER writable
3. ROOT_EXTERNAL is always denied
"""

from dataclasses import dataclass

from ck3lens.paths import RootCategory


@dataclass(frozen=True)
class Capability:
    """Capability flags for a (mode, root, subdir) combination."""

    read: bool = False
    write: bool = False
    delete: bool = False
    subfolders_writable: bool = False  # Write/delete granted to nested paths only
    contract_required: bool = True  # Writes/deletes require active contract


# Type alias for matrix key
MatrixKey = tuple[str, RootCategory, str | None]

# ─────────────────────────────────────────────────────────────────────
# THE CAPABILITY MATRIX
# ─────────────────────────────────────────────────────────────────────

CAPABILITY_MATRIX: dict[MatrixKey, Capability] = {
    # =================================================================
    # ck3lens mode
    # =================================================================
    #
    # Game content (read-only)
    ("ck3lens", RootCategory.ROOT_GAME, None): Capability(read=True),
    ("ck3lens", RootCategory.ROOT_STEAM, None): Capability(read=True),
    #
    # User docs - READ-ONLY by default
    # mod/ subdirectory: subfolders are writable (files directly in mod/ are not)
    ("ck3lens", RootCategory.ROOT_USER_DOCS, None): Capability(read=True),
    ("ck3lens", RootCategory.ROOT_USER_DOCS, "mod"): Capability(
        read=True, subfolders_writable=True
    ),
    #
    # CK3RAVEN_DATA - explicit root-level entry + per-subdirectory rules
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, None): Capability(
        read=True
    ),  # Root level: read-only
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "config"): Capability(
        read=True, write=True
    ),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "playsets"): Capability(
        read=True, write=True, delete=True
    ),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "wip"): Capability(
        read=True, write=True, delete=True, contract_required=False
    ),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "logs"): Capability(
        read=True, write=True
    ),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "journal"): Capability(
        read=True, write=True
    ),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "cache"): Capability(
        read=True, write=True, delete=True
    ),
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "db"): Capability(
        read=True
    ),  # Daemon only
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "daemon"): Capability(
        read=True
    ),  # Daemon only
    ("ck3lens", RootCategory.ROOT_CK3RAVEN_DATA, "artifacts"): Capability(
        read=True, write=True
    ),
    #
    # VS Code (read-only)
    ("ck3lens", RootCategory.ROOT_VSCODE, None): Capability(read=True),
    #
    # Repo not visible in ck3lens mode
    ("ck3lens", RootCategory.ROOT_REPO, None): Capability(),
    #
    # External always denied
    ("ck3lens", RootCategory.ROOT_EXTERNAL, None): Capability(),
    #
    # =================================================================
    # ck3raven-dev mode
    # =================================================================
    #
    # Repo - full access
    ("ck3raven-dev", RootCategory.ROOT_REPO, None): Capability(
        read=True, write=True, delete=True
    ),
    #
    # Game content (read-only for testing/reference)
    ("ck3raven-dev", RootCategory.ROOT_GAME, None): Capability(read=True),
    ("ck3raven-dev", RootCategory.ROOT_STEAM, None): Capability(read=True),
    #
    # User docs - read-only (not modding in dev mode)
    ("ck3raven-dev", RootCategory.ROOT_USER_DOCS, None): Capability(read=True),
    ("ck3raven-dev", RootCategory.ROOT_USER_DOCS, "mod"): Capability(
        read=True
    ),  # Read-only in dev mode
    #
    # CK3RAVEN_DATA - explicit root-level entry + per-subdirectory rules
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, None): Capability(
        read=True
    ),  # Root level: read-only
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "config"): Capability(
        read=True, write=True, delete=True
    ),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "playsets"): Capability(
        read=True, write=True, delete=True
    ),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "wip"): Capability(
        read=True, write=True, delete=True, contract_required=False
    ),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "logs"): Capability(
        read=True, write=True, delete=True
    ),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "journal"): Capability(
        read=True, write=True, delete=True
    ),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "cache"): Capability(
        read=True, write=True, delete=True
    ),
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "db"): Capability(
        read=True
    ),  # Daemon only
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "daemon"): Capability(
        read=True
    ),  # Daemon only
    ("ck3raven-dev", RootCategory.ROOT_CK3RAVEN_DATA, "artifacts"): Capability(
        read=True, write=True, delete=True
    ),
    #
    # VS Code - write settings (no delete)
    ("ck3raven-dev", RootCategory.ROOT_VSCODE, None): Capability(read=True, write=True),
    #
    # External always denied
    ("ck3raven-dev", RootCategory.ROOT_EXTERNAL, None): Capability(),
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
    - If relative_path is nested (e.g., mod/MyMod/file.txt), grants write/delete
    - If relative_path is shallow (e.g., mod/MyMod.mod), returns base capability

    Returns empty Capability() if no entry found (default deny).
    """
    # Roots that use subdirectory-level lookup
    subdir_roots = (RootCategory.ROOT_CK3RAVEN_DATA, RootCategory.ROOT_USER_DOCS)

    if root in subdir_roots and subdirectory:
        key = (mode, root, subdirectory)
        if key in CAPABILITY_MATRIX:
            cap = CAPABILITY_MATRIX[key]

            # Handle subfolders_writable: grant write/delete if path is nested
            if cap.subfolders_writable and relative_path:
                # Normalize and split path
                parts = relative_path.replace("\\", "/").strip("/").split("/")
                # Need at least 3 parts to be inside a subfolder:
                # e.g., "mod/MyMod/file.txt" = ["mod", "MyMod", "file.txt"]
                # vs "mod/MyMod.mod" = ["mod", "MyMod.mod"] (only 2 parts)
                if len(parts) >= 3:
                    return Capability(read=cap.read, write=True, delete=True)

            return cap

    # Fall back to root-level lookup (also handles subdirectory=None)
    key = (mode, root, None)
    return CAPABILITY_MATRIX.get(key, Capability())
