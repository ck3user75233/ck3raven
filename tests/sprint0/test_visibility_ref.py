"""
VR-* — VisibilityRef tests.

Tests: VR-01 (Immutability), VR-02 (No Host Path), VR-03 (UUID4 Token),
       VR-04 (Unique Tokens per Resolve)
"""
from __future__ import annotations

import uuid

import pytest

from ck3lens.world_adapter_v2 import VisibilityRef, WorldAdapterV2


# =========================================================================
# VR-01: Immutability
# =========================================================================

class TestVR01Immutability:
    """VisibilityRef is frozen — attributes cannot be set or deleted."""

    def test_token_readable(self, wa2: WorldAdapterV2) -> None:
        reply, ref = wa2.resolve("root:repo/src/server.py")
        assert reply.reply_type == "S"
        assert ref is not None
        assert isinstance(ref.token, str)

    def test_session_abs_readable(self, wa2: WorldAdapterV2) -> None:
        reply, ref = wa2.resolve("root:repo/src/server.py")
        assert ref is not None
        assert ref.session_abs == "root:repo/src/server.py"

    def test_frozen_token(self, wa2: WorldAdapterV2) -> None:
        reply, ref = wa2.resolve("root:repo/src/server.py")
        assert ref is not None
        with pytest.raises((AttributeError, TypeError)):
            ref.token = "x"  # type: ignore[misc]

    def test_frozen_session_abs(self, wa2: WorldAdapterV2) -> None:
        reply, ref = wa2.resolve("root:repo/src/server.py")
        assert ref is not None
        with pytest.raises((AttributeError, TypeError)):
            ref.session_abs = "y"  # type: ignore[misc]

    def test_str_returns_session_abs(self, wa2: WorldAdapterV2) -> None:
        reply, ref = wa2.resolve("root:repo/src/server.py")
        assert ref is not None
        assert str(ref) == ref.session_abs

    def test_repr_format(self, wa2: WorldAdapterV2) -> None:
        reply, ref = wa2.resolve("root:repo/src/server.py")
        assert ref is not None
        assert repr(ref) == f"VisibilityRef({ref.session_abs})"


# =========================================================================
# VR-02: No Host Path on Object
# =========================================================================

class TestVR02NoHostPath:
    """VisibilityRef must contain no host-absolute path in any attribute."""

    _HOST_PREFIXES = ("C:\\", "D:\\", "/home/", "/Users/", "/mnt/", "\\\\")

    def test_token_is_not_path(self, wa2: WorldAdapterV2) -> None:
        reply, ref = wa2.resolve("root:repo/src/server.py")
        assert ref is not None
        for prefix in self._HOST_PREFIXES:
            assert not ref.token.startswith(prefix)

    def test_session_abs_is_canonical(self, wa2: WorldAdapterV2) -> None:
        reply, ref = wa2.resolve("root:repo/src/server.py")
        assert ref is not None
        assert ref.session_abs.startswith("root:") or ref.session_abs.startswith("mod:")
        for prefix in self._HOST_PREFIXES:
            assert prefix not in ref.session_abs


# =========================================================================
# VR-03: Token is UUID4
# =========================================================================

class TestVR03TokenUUID4:
    """Each VisibilityRef has a valid UUID4 token."""

    def test_valid_uuid4(self, wa2: WorldAdapterV2) -> None:
        reply, ref = wa2.resolve("root:repo/src/server.py")
        assert ref is not None
        parsed = uuid.UUID(ref.token, version=4)
        assert parsed.version == 4


# =========================================================================
# VR-04: Unique Tokens per Resolve
# =========================================================================

class TestVR04UniqueTokens:
    """Every resolve() call mints a fresh token, even for the same input."""

    def test_two_resolves_different_tokens(self, wa2: WorldAdapterV2) -> None:
        reply1, ref1 = wa2.resolve("root:repo/src")
        reply2, ref2 = wa2.resolve("root:repo/src")
        assert ref1 is not None and ref2 is not None
        assert ref1.token != ref2.token

    def test_same_session_abs(self, wa2: WorldAdapterV2) -> None:
        reply1, ref1 = wa2.resolve("root:repo/src")
        reply2, ref2 = wa2.resolve("root:repo/src")
        assert ref1 is not None and ref2 is not None
        assert ref1.session_abs == ref2.session_abs
