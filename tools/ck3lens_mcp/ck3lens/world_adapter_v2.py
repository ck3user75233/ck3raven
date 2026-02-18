"""
World Adapter v2 — Canonical Addressing with Opaque Token Registry.

Mode-agnostic: resolve() reads agent mode dynamically via get_agent_mode()
at call time. The WA instance never stores mode — if mode is None (agent
not initialized), resolve() fails with WA-MODE-I-001.

resolve() returns tuple[Reply, Optional[VisibilityRef]].
No VisibilityResolution in public API. No mod_paths dict.
Consults session.mods directly at resolution time.
Walks VISIBILITY_MATRIX for root category gating.

Canonical address syntax (locked):
    root:<key>/<relative_path>      e.g. root:repo/src/server.py
    mod:<mod_name>/<relative_path>  e.g. mod:Unofficial Patch/common/traits

Legacy input accepted, never emitted:
    ROOT_REPO:/src/server.py        → normalized to root:repo/src/server.py
    mod:Name:/common/traits         → normalized to mod:Name/common/traits

VisibilityRef holds an opaque UUID4 token. The host-absolute path lives
ONLY in the token registry on this instance. Agent never sees host paths.

Design brief: docs/Canonical address refactor/v2_enforcement_design_brief.md
Directive: Canonical Addressing Refactor Directive (Authoritative)
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from ck3raven.core.reply import Reply


# ============================================================================
# Constants
# ============================================================================

MAX_TOKENS = 10_000

# Root key mapping: RootCategory enum name → v2 canonical key
_ROOT_KEY_FROM_ENUM: dict[str, str] = {
    "ROOT_REPO": "repo",
    "ROOT_CK3RAVEN_DATA": "ck3raven_data",
    "ROOT_GAME": "game",
    "ROOT_STEAM": "steam",
    "ROOT_USER_DOCS": "user_docs",
    "ROOT_VSCODE": "vscode",
}
_ENUM_FROM_ROOT_KEY: dict[str, str] = {v: k for k, v in _ROOT_KEY_FROM_ENUM.items()}

# Valid v2 root keys (closed set) — re-exported from capability_matrix_v2
from .capability_matrix_v2 import VALID_ROOT_KEYS  # noqa: E402


def _is_host_absolute(s: str) -> bool:
    """Return True if s looks like a host-absolute path (not a canonical address)."""
    if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
        if len(s) == 2 or s[2] in "/\\":
            return True
    if s.startswith("\\\\"):
        return True
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


def _get_mode() -> Optional[str]:
    """
    Read agent mode dynamically. Returns None if not initialized.

    This is THE mode accessor for WA v2. Every call hits the persisted
    mode file (~/.ck3raven/agent_mode_{instance_id}.json). If it returns
    None, the agent has not called ck3_get_mode_instructions yet.
    """
    from ck3lens.agent_mode import get_agent_mode
    return get_agent_mode()


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


# ============================================================================
# WorldAdapterV2
# ============================================================================

class WorldAdapterV2:
    """
    World Adapter v2 — canonical addressing with opaque token registry.

    Mode-agnostic: does NOT store agent mode. resolve() reads mode
    dynamically via _get_mode() on every call. If mode is None (agent
    not initialized), resolve() returns WA-MODE-I-001.

    Construction: WorldAdapterV2(session=..., roots=...)
    - session: object with .mods list (each mod has .name and .path)
    - roots: dict of v2 root key → host-absolute Path

    resolve() returns tuple[Reply, Optional[VisibilityRef]].
    No VisibilityResolution. No mod_paths dict. Consults session.mods directly.
    Walks VISIBILITY_MATRIX for root category gating.
    """

    def __init__(self, *, session: Any, roots: dict[str, Path]):
        """
        Args:
            session: Session object — session.mods is the authoritative mod list.
                     Each mod has .name (str) and .path (Path).
            roots: Mapping of v2 root key → host-absolute Path.
                   Keys must be from VALID_ROOT_KEYS.
        """
        for key in roots:
            if key not in VALID_ROOT_KEYS:
                raise ValueError(f"Unknown root key: {key!r}. Valid: {sorted(VALID_ROOT_KEYS)}")
        self._session = session
        self._roots: dict[str, Path] = dict(roots)
        self._token_registry: Dict[str, Path] = {}
        self._registry_lock = Lock()

    @classmethod
    def create(cls, *, session: Any) -> WorldAdapterV2:
        """
        Factory using paths.py constants.

        Args:
            session: Session object with .mods
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

        return cls(session=session, roots=roots)

    # ========================================================================
    # Public API
    # ========================================================================

    def resolve(
        self, input_str: str, *, require_exists: bool = True, rb: Any = None,
    ) -> tuple[Reply, Optional[VisibilityRef]]:
        """
        Resolve a canonical address.

        Reads agent mode dynamically via _get_mode(). If mode is None
        (agent not initialized), returns WA-MODE-I-001 immediately.

        Returns:
            (Reply, VisibilityRef) on success — Reply.data["resolved"] is the
            session-absolute path preserving input namespace.
            (Reply, None) on failure — Reply is Invalid.

        Args:
            input_str: Canonical address (root:key/path, mod:name/path, or legacy).
            require_exists: If True, non-existent paths fail.
            rb: ReplyBuilder for constructing Reply. If None, creates a minimal Reply.
        """
        from .capability_matrix_v2 import check_visibility

        # Dynamic mode read — every resolve() checks current mode
        mode = _get_mode()
        if mode is None:
            return self._fail(rb, "WA-MODE-I-001",
                "Agent mode not initialized. Call ck3_get_mode_instructions first.", {
                    "input_path": input_str,
                })

        parsed = self._parse_and_compute(input_str)
        if parsed is None:
            return self._fail(rb, "WA-RES-I-001", "Invalid or unresolvable path", {
                "input_path": input_str,
                "mode": mode,
            })

        session_abs, host_abs, root_key, rel_path, is_mod = parsed

        # Existence check
        if require_exists and not host_abs.exists():
            return self._fail(rb, "WA-RES-I-001", "Path does not exist", {
                "input_path": input_str,
                "resolved": session_abs,
                "mode": mode,
            })

        # Derive subdirectory from first path component
        subdirectory = None
        rel_normalized = rel_path.replace("\\", "/").strip("/")
        if rel_normalized:
            parts = rel_normalized.split("/")
            subdirectory = parts[0] if parts[0] else None

        # Extract mod name for visibility context
        # mod:SomeName/path -> mod_name = "SomeName"
        # root:user_docs/mod/SomeName/... -> mod_name = "SomeName" (subfolder after subdirectory)
        mod_name = None
        if is_mod and session_abs.startswith("mod:"):
            mod_part = session_abs[4:]  # strip "mod:"
            slash_idx = mod_part.find("/")
            mod_name = mod_part[:slash_idx] if slash_idx >= 0 else mod_part
        elif not is_mod and rel_normalized:
            # For root paths like user_docs/mod/SomeName/..., the mod name is
            # the component AFTER subdirectory
            rparts = rel_normalized.split("/")
            if len(rparts) >= 2 and rparts[1]:
                mod_name = rparts[1]

        # Build session mods set for visibility conditions
        session_mods: set[str] = set()
        if self._session is not None and hasattr(self._session, "mods") and self._session.mods:
            session_mods = set(self._session.mods)

        # Visibility gate — conditions checked by check_visibility
        if not check_visibility(
            mode, root_key, subdirectory,
            mod_name=mod_name,
            session_mods=session_mods,
            relative_path=rel_normalized,
        ):
            return self._fail(rb, "WA-VIS-I-001", "Not visible in current mode", {
                "input_path": input_str,
                "root_key": root_key,
                "subdirectory": subdirectory,
                "mode": mode,
            })

        # Mint token
        token = str(uuid.uuid4())
        with self._registry_lock:
            if len(self._token_registry) >= MAX_TOKENS:
                return self._fail(rb, "WA-RES-E-001",
                    "Token registry full — restart server", {})
            self._token_registry[token] = host_abs

        ref = VisibilityRef(token=token, session_abs=session_abs)

        reply_data = {
            "resolved": session_abs,
            "root_key": root_key,
            "subdirectory": subdirectory,
            "relative_path": rel_normalized,
        }

        if rb is not None:
            reply = rb.success("WA-RES-S-001", reply_data)
        else:
            # Minimal Reply when no ReplyBuilder available
            from ck3raven.core.reply import TraceInfo, MetaInfo
            reply = Reply.success(
                code="WA-RES-S-001",
                message="Path resolved",
                data=reply_data,
                trace=TraceInfo(trace_id="", session_id=""),
                meta=MetaInfo(layer="WA", tool="world_adapter_v2"),
            )

        return (reply, ref)

    def host_path(self, ref: VisibilityRef) -> Optional[Path]:
        """
        Recover host-absolute Path from a VisibilityRef token.

        Only WA2 owns this — callers must go through WA2 to get a real path.
        Returns None if the token is unknown/expired.
        """
        with self._registry_lock:
            return self._token_registry.get(ref.token)

    @property
    def mode(self) -> str:
        """
        Read agent mode dynamically. Always current.

        Returns 'uninitiated' if agent has not called ck3_get_mode_instructions.
        """
        return _get_mode() or "uninitiated"

    @property
    def root_keys(self) -> frozenset[str]:
        """Return the set of configured root keys."""
        return frozenset(self._roots.keys())

    @property
    def mod_names(self) -> frozenset[str]:
        """Return mod names from session.mods."""
        if self._session and hasattr(self._session, 'mods') and self._session.mods:
            return frozenset(m.name for m in self._session.mods if hasattr(m, 'name'))
        return frozenset()

    # ========================================================================
    # Private: Reply helpers
    # ========================================================================

    def _fail(
        self, rb: Any, code: str, message: str, data: dict,
    ) -> tuple[Reply, None]:
        """Build a failure Reply (Invalid)."""
        if rb is not None:
            return (rb.invalid(code, data, message=message), None)
        from ck3raven.core.reply import TraceInfo, MetaInfo
        return (Reply.invalid(
            code=code, message=message, data=data,
            trace=TraceInfo(trace_id="", session_id=""),
            meta=MetaInfo(layer="WA", tool="world_adapter_v2"),
        ), None)

    # ========================================================================
    # Private: Parse + Compute
    # ========================================================================

    def _parse_and_compute(
        self, input_str: str,
    ) -> tuple[str, Path, str, str, bool] | None:
        """
        Parse input and compute (session_abs, host_abs, root_key, rel_path, is_mod).

        is_mod=True means this was a mod: address (root_key is the underlying
        infrastructure root, session_abs preserves mod:Name/... namespace).

        Returns None if the input is invalid or unresolvable.
        """
        input_str = input_str.strip()
        if not input_str:
            return None

        # Reject host-absolute paths
        if _is_host_absolute(input_str):
            return None

        # Canonical: root:key/path
        if input_str.startswith("root:"):
            return self._parse_root(input_str[5:])

        # Canonical: mod:name/path
        if input_str.startswith("mod:"):
            return self._parse_mod(input_str[4:])

        # Legacy: ROOT_X:/path
        if input_str.startswith("ROOT_"):
            return self._parse_legacy_root(input_str)

        # Unrecognized
        return None

    def _parse_root(self, rest: str) -> tuple[str, Path, str, str, bool] | None:
        """Parse after 'root:' prefix."""
        if "/" in rest:
            key, rel_path = rest.split("/", 1)
        else:
            key = rest
            rel_path = ""

        rel_path = rel_path.strip("/")

        if key not in self._roots:
            return None

        root_path = self._roots[key]
        host_abs = root_path / rel_path if rel_path else root_path

        if not _is_contained(host_abs, root_path):
            return None

        session_abs = f"root:{key}/{rel_path}" if rel_path else f"root:{key}"
        return (session_abs, host_abs, key, rel_path, False)

    def _parse_mod(self, rest: str) -> tuple[str, Path, str, str, bool] | None:
        """
        Parse after 'mod:' prefix. Consults session.mods directly.

        Output preserves mod: namespace in session_abs.
        root_key is the underlying infrastructure root (for enforcement).
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

        # Consult session.mods directly — no mod_paths dict
        mod_path = self._find_mod_path(mod_name)
        if mod_path is None:
            return None

        host_abs = mod_path / rel_path if rel_path else mod_path

        if not _is_contained(host_abs, mod_path):
            return None

        # Determine underlying root key for enforcement
        root_key = self._classify_host_path(host_abs)

        # Session-absolute preserves mod: namespace
        session_abs = f"mod:{mod_name}/{rel_path}" if rel_path else f"mod:{mod_name}"
        return (session_abs, host_abs, root_key, rel_path, True)

    def _parse_legacy_root(self, address: str) -> tuple[str, Path, str, str, bool] | None:
        """Parse legacy ROOT_X:/path syntax and normalize to root:key/path."""
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

                # Legacy input normalized to root: output
                session_abs = f"root:{key}/{rel_path}" if rel_path else f"root:{key}"
                return (session_abs, host_abs, key, rel_path, False)

        return None

    def _find_mod_path(self, mod_name: str) -> Path | None:
        """
        Find a mod's host root path by consulting session.mods directly.

        No mod_paths dict. session.mods IS the authoritative registry.
        """
        if not self._session or not hasattr(self._session, 'mods') or not self._session.mods:
            return None
        for mod in self._session.mods:
            if hasattr(mod, 'name') and mod.name == mod_name:
                if hasattr(mod, 'path'):
                    return Path(mod.path) if isinstance(mod.path, str) else mod.path
        return None

    def _classify_host_path(self, host_abs: Path) -> str:
        """
        Determine which root key a host-absolute path falls under.

        Used for mod: addresses to find the underlying infrastructure root
        (needed for enforcement matrix lookup).
        """
        try:
            resolved = host_abs.resolve()
        except (OSError, ValueError):
            return "user_docs"  # safe fallback

        # Check roots in specificity order
        priority = ["ck3raven_data", "repo", "user_docs", "game", "steam", "vscode"]
        for key in priority:
            if key in self._roots:
                try:
                    resolved.relative_to(self._roots[key].resolve())
                    return key
                except ValueError:
                    pass

        return "user_docs"  # most mods live under user_docs
