"""
REG-* — Token registry tests.

Tests: REG-01 (host_path recovery), REG-02 (invalid token → None),
       REG-03 (MAX_TOKENS hard cap, synthetic paths), REG-04 (token uniqueness under volume)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ck3lens.world_adapter_v2 import (
    MAX_TOKENS,
    VisibilityRef,
    WorldAdapterV2,
)


# =========================================================================
# REG-01: host_path Recovery
# =========================================================================

class TestREG01HostPathRecovery:
    """wa2.host_path(ref) recovers the correct host-absolute Path."""

    def test_basic_recovery(self, wa2: WorldAdapterV2) -> None:
        reply, ref = wa2.resolve("root:repo/src/server.py")
        assert reply.reply_type == "S"
        assert ref is not None
        host = wa2.host_path(ref)
        assert isinstance(host, Path)
        assert host.exists()
        assert host.name == "server.py"

    def test_directory_recovery(self, wa2: WorldAdapterV2) -> None:
        reply, ref = wa2.resolve("root:repo/src")
        assert ref is not None
        host = wa2.host_path(ref)
        assert host is not None
        assert host.is_dir()


# =========================================================================
# REG-02: Invalid Token → None
# =========================================================================

class TestREG02InvalidToken:
    """A fabricated VisibilityRef returns None from host_path."""

    def test_fabricated_token(self, wa2: WorldAdapterV2) -> None:
        fake_ref = VisibilityRef(token="not-a-real-token", session_abs="root:repo/x")
        assert wa2.host_path(fake_ref) is None


# =========================================================================
# REG-03: MAX_TOKENS Hard Cap  (synthetic paths)
# =========================================================================

class TestREG03MaxTokensCap:
    """Registry returns deterministic error at 10,000 tokens.

    Uses synthetic unique paths with require_exists=False to avoid
    needing 10,000 real filesystem entries.
    """

    def test_hard_cap(self, wa2: WorldAdapterV2) -> None:
        # Fill registry to capacity with synthetic paths
        for i in range(MAX_TOKENS):
            reply, ref = wa2.resolve(f"root:repo/src/synthetic_{i}.py", require_exists=False)
            assert reply.reply_type == "S", f"Failed at token #{i}: {reply.message}"

        # The 10,001st must fail deterministically
        reply, ref = wa2.resolve("root:repo/src/overflow.py", require_exists=False)
        assert reply.reply_type != "S"
        assert ref is None
        assert "registry full" in (reply.message or "").lower()


# =========================================================================
# REG-04: Token Uniqueness Under Volume
# =========================================================================

class TestREG04TokenUniquenessVolume:
    """1,000 resolves of the same input produce 1,000 unique tokens."""

    def test_1000_unique_tokens(self, wa2: WorldAdapterV2) -> None:
        tokens = []
        for _ in range(1000):
            reply, ref = wa2.resolve("root:repo/src", require_exists=False)
            assert ref is not None
            tokens.append(ref.token)
        assert len(set(tokens)) == 1000
