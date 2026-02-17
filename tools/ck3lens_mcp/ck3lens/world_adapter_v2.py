"""
World Adapter v2 — Canonical Addressing with Opaque Token Registry.

Sprint 0 vertical slice. Isolated from v1 WorldAdapter (no imports, no shared state).

Canonical address syntax (locked):
    root:<key>/<relative_path>      e.g. root:repo/src/server.py
    mod:<mod_name>/<relative_path>  e.g. mod:Unofficial Patch/common/traits

Legacy input accepted (Sprint 0 compatibility), never emitted:
    ROOT_REPO:/src/server.py        → normalized to root:repo/src/server.py
    mod:Name:/common/traits         → normalized to mod:Name/common/traits

VisibilityRef holds an opaque UUID4 token. The host-absolute path lives
ONLY in the token registry on this WorldAdapterV2 instance. The agent
never sees host paths.

Directive: Canonical Addressing Refactor Directive (Authoritative)
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Dict, Optional

# ============================================================================
# Constants
# ============================================================================

MAX_TOKENS = 10_000

# Root key mapping: RootCategory enum name → v2 canonical key
# This is the ONLY place that defines the v2 key set.
_ROOT_KEY_FROM_ENUM: dict[str, str] = {
    "ROOT_REPO": "repo",
    "ROOT_CK3RAVEN_DATA": "ck3raven_data",
    "ROOT_GAME": "game",
    "ROOT_STEAM": "steam",
    "ROOT_USER_DOCS": "user_docs",
    "ROOT_VSCODE": "vscode",
}
_ENUM_FROM_ROOT_KEY: dict[str, str] = {v: k for k, v in _ROOT_KEY_FROM_ENUM.items()}

# Valid v2 root keys (closed set)
VALID_ROOT_KEYS: frozenset[str] = frozenset(_ROOT_KEY_FROM_ENUM.values())

# Host-absolute path detection patterns
_HOST_ABS_PATTERNS = [
    re.compile(r"^[A-Za-z]:[/\\]"),   # Windows drive (C:\, D:/)
    re.compile(r"^\\\\"),              # UNC path
]


def _is_host_absolute(s: str) -> bool:
    """Return True if s looks like a host-absolute path (not a canonical address)."""
    # Windows drive letter: C:\ or C:/
    if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
        if len(s) == 2 or s[2] in "/\\":
            return True
    # UNC
    if s.startswith("\\\\"):
        return True
    # Unix absolute — but NOT our canonical schemes
    if s.startswith("/"):
        return True
    return False


def _is_contained(child: Path, parent: Path) -> bool:
    """Check that child is contained within parent (no traversal escape)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


# ============================================================================
# Data Models
# ============================================================================

@dataclass(frozen=True, slots=True)
class VisibilityRef:
    """
    Opaque reference to a resolved path. Agent-safe.

    - token: UUID4 string (opaque, registry key)
    - session_abs: canonical address (root:key/path or mod:name/path)

    The host-absolute path is NOT on this object. It lives only in
    WorldAdapterV2._token_registry, keyed by token.
    """
    token: str
    session_abs: str

    def __str__(self) -> str:
        return self.session_abs

    def __repr__(self) -> str:
        return f"VisibilityRef({self.session_abs})"


@dataclass(frozen=True, slots=True)
class VisibilityResolution:
    """
    Result of WorldAdapterV2.resolve().

    ok=True  → ref is set, root_category/relative_path populated, exists is bool
    ok=False → error_message explains why
    """
    ok: bool
    ref: Optional[VisibilityRef] = None
    root_category: Optional[str] = None   # v2 key: "repo", "game", etc. None for mod
    relative_path: Optional[str] = None
    exists: Optional[bool] = None         # Advisory (TOCTOU caveat)
    error_message: Optional[str] = None


# ============================================================================
# WorldAdapterV2
# ============================================================================

class WorldAdapterV2:
    """
    World Adapter v2 — canonical addressing with opaque token registry.

    Differences from v1 WorldAdapter:
    - resolve() returns VisibilityResolution (not ResolutionResult)
    - Host paths live only in token registry, never in output
    - Only accepts canonical address forms (host paths rejected)
    - Uses root:key/path syntax (not ROOT_X:/ or ck3raven:/)
    - Single entry point: resolve(input_str, *, require_exists=True)
    """

    def __init__(self, *, roots: dict[str, Path], mod_paths: dict[str, Path]):
        """
        Args:
            roots: Mapping of v2 root key → host-absolute Path.
                   Keys must be from VALID_ROOT_KEYS.
            mod_paths: Mapping of mod name → host-absolute Path.
        """
        # Validate root keys
        for key in roots:
            if key not in VALID_ROOT_KEYS:
                raise ValueError(f"Unknown root key: {key!r}. Valid: {sorted(VALID_ROOT_KEYS)}")
        self._roots: dict[str, Path] = dict(roots)
        self._mod_paths: dict[str, Path] = dict(mod_paths)
        self._token_registry: Dict[str, Path] = {}
        self._registry_lock = Lock()

    @classmethod
    def create(cls, *, mods: list | None = None) -> WorldAdapterV2:
        """
        Factory using paths.py constants — same data source as v1.

        Imports from ck3lens.paths at call time (deferred import).
        """
        from ck3lens.paths import (
            ROOT_REPO,
            ROOT_CK3RAVEN_DATA,
            ROOT_GAME,
            ROOT_STEAM,
            ROOT_USER_DOCS,
            ROOT_VSCODE,
        )

        roots: dict[str, Path] = {}
        mod_paths: dict[str, Path] = {}

        # ROOT_CK3RAVEN_DATA is always set (never None)
        roots["ck3raven_data"] = ROOT_CK3RAVEN_DATA

        if ROOT_REPO and ROOT_REPO.exists():
            roots["repo"] = ROOT_REPO
        if ROOT_GAME and ROOT_GAME.exists():
            roots["game"] = ROOT_GAME
        if ROOT_STEAM and ROOT_STEAM.exists():
            roots["steam"] = ROOT_STEAM
        if ROOT_USER_DOCS and ROOT_USER_DOCS.exists():
            roots["user_docs"] = ROOT_USER_DOCS
        if ROOT_VSCODE and ROOT_VSCODE.exists():
            roots["vscode"] = ROOT_VSCODE

        if mods:
            for mod in mods:
                if hasattr(mod, "name") and hasattr(mod, "path"):
                    mod_path = Path(mod.path) if isinstance(mod.path, str) else mod.path
                    mod_paths[mod.name] = mod_path

        return cls(roots=roots, mod_paths=mod_paths)

    # ========================================================================
    # Public API
    # ========================================================================

    def resolve(
        self, input_str: str, *, require_exists: bool = True
    ) -> VisibilityResolution:
        """
        Resolve a canonical address to a VisibilityResolution.

        Single entry point — no resolve_agent_path, resolve_tool_path, etc.

        Args:
            input_str: Canonical address (root:key/path or mod:name/path).
                       Legacy forms (ROOT_X:/... and mod:Name:/...) accepted.
            require_exists: If True (default), non-existent paths return Invalid.
                           If False, structurally valid but missing paths succeed
                           with exists=False.

        Returns:
            VisibilityResolution with ok=True on success, ok=False on failure.
        """
        parsed = self._parse_and_compute(input_str)
        if parsed is None:
            return VisibilityResolution(
                ok=False, error_message="Invalid path / not found"
            )

        session_abs, host_abs, root_key, rel_path = parsed

        # TOCTOU Note: exists_now is advisory; file may change after check.
        exists_now = host_abs.exists()

        if require_exists and not exists_now:
            return VisibilityResolution(
                ok=False, error_message="Invalid path / not found"
            )

        # Mint token
        token = str(uuid.uuid4())

        with self._registry_lock:
            if len(self._token_registry) >= MAX_TOKENS:
                return VisibilityResolution(
                    ok=False,
                    error_message="Visibility registry capacity exceeded — restart server",
                )
            self._token_registry[token] = host_abs

        return VisibilityResolution(
            ok=True,
            ref=VisibilityRef(token=token, session_abs=session_abs),
            root_category=root_key if not root_key.startswith("mod:") else None,
            relative_path=rel_path,
            exists=exists_now,
        )

    def host_path(self, ref: VisibilityRef) -> Optional[Path]:
        """
        Recover host-absolute Path from a VisibilityRef token.

        Only WA2 owns this — callers must go through WA2 to get a real path.
        Returns None if the token is unknown/expired.
        """
        with self._registry_lock:
            return self._token_registry.get(ref.token)

    @property
    def root_keys(self) -> frozenset[str]:
        """Return the set of configured root keys."""
        return frozenset(self._roots.keys())

    @property
    def mod_names(self) -> frozenset[str]:
        """Return the set of configured mod names."""
        return frozenset(self._mod_paths.keys())

    # ========================================================================
    # Internal: Parse + Compute
    # ========================================================================

    def _parse_and_compute(
        self, input_str: str
    ) -> tuple[str, Path, str, str] | None:
        """
        Parse input and compute (session_abs, host_abs, root_key, rel_path).

        Returns None if the input is invalid or unresolvable.

        root_key is the v2 key ("repo", "game", ...) for root: addresses,
        or "mod:<name>" for mod: addresses.
        """
        input_str = input_str.strip()
        if not input_str:
            return None

        # --- Reject host-absolute paths (Invariant A) ---
        if _is_host_absolute(input_str):
            return None

        # --- Canonical: root:key/path ---
        if input_str.startswith("root:"):
            return self._parse_root(input_str[5:])

        # --- Canonical: mod:name/path ---
        if input_str.startswith("mod:"):
            return self._parse_mod(input_str[4:])

        # --- Legacy: ROOT_X:/path ---
        if input_str.startswith("ROOT_"):
            return self._parse_legacy_root(input_str)

        # Unrecognized → invalid
        return None

    def _parse_root(self, rest: str) -> tuple[str, Path, str, str] | None:
        """
        Parse after 'root:' prefix.

        rest = 'repo/src/server.py' or 'repo' (no path)
        """
        if "/" in rest:
            key, rel_path = rest.split("/", 1)
        else:
            key = rest
            rel_path = ""

        # Normalize: strip trailing slashes from rel_path
        rel_path = rel_path.strip("/")

        if key not in self._roots:
            return None

        root_path = self._roots[key]
        host_abs = root_path / rel_path if rel_path else root_path

        # Containment check
        if not _is_contained(host_abs, root_path):
            return None

        session_abs = f"root:{key}/{rel_path}" if rel_path else f"root:{key}"
        return (session_abs, host_abs, key, rel_path)

    def _parse_mod(self, rest: str) -> tuple[str, Path, str, str] | None:
        """
        Parse after 'mod:' prefix.

        Accepts both canonical and legacy forms:
            Name/common/traits      (canonical)
            Name:/common/traits     (legacy — colon-slash stripped)
        """
        # Handle legacy mod:Name:/path (strip the extra colon)
        if ":/" in rest:
            mod_name, rel_path = rest.split(":/", 1)
        elif "/" in rest:
            mod_name, rel_path = rest.split("/", 1)
        else:
            mod_name = rest
            rel_path = ""

        rel_path = rel_path.strip("/")

        if mod_name not in self._mod_paths:
            return None

        mod_root = self._mod_paths[mod_name]
        host_abs = mod_root / rel_path if rel_path else mod_root

        # Containment check
        if not _is_contained(host_abs, mod_root):
            return None

        session_abs = f"mod:{mod_name}/{rel_path}" if rel_path else f"mod:{mod_name}"
        root_key = f"mod:{mod_name}"
        return (session_abs, host_abs, root_key, rel_path)

    def _parse_legacy_root(self, address: str) -> tuple[str, Path, str, str] | None:
        """
        Parse legacy ROOT_X:/path syntax and normalize to root:key/path.
        """
        for enum_name, key in _ROOT_KEY_FROM_ENUM.items():
            prefix = f"{enum_name}:/"
            if address.startswith(prefix):
                rel_path = address[len(prefix):].strip("/")

                if key not in self._roots:
                    return None

                root_path = self._roots[key]
                host_abs = root_path / rel_path if rel_path else root_path

                if not _is_contained(host_abs, root_path):
                    return None

                session_abs = f"root:{key}/{rel_path}" if rel_path else f"root:{key}"
                return (session_abs, host_abs, key, rel_path)

        return None
