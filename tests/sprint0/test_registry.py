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
        res = wa2.resolve("root:repo/src/server.py")
        assert res.ok
        host = wa2.host_path(res.ref)
        assert isinstance(host, Path)
        assert host.exists()
        assert host.name == "server.py"

    def test_directory_recovery(self, wa2: WorldAdapterV2) -> None:
        res = wa2.resolve("root:repo/src")
        host = wa2.host_path(res.ref)
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
# REG-03: MAX_TOKENS Hard Cap  (Adjustment 3 — synthetic paths)
# =========================================================================

class TestREG03MaxTokensCap:
    """Registry raises deterministic error at 10,000 tokens.
    
    Uses synthetic unique paths with require_exists=False to avoid
    needing 10,000 real filesystem entries.
    """

    def test_hard_cap(self, wa2: WorldAdapterV2) -> None:
        # Fill registry to capacity with synthetic paths
        for i in range(MAX_TOKENS):
            res = wa2.resolve(f"root:repo/src/synthetic_{i}.py", require_exists=False)
            assert res.ok, f"Failed at token #{i}: {res.error_message}"

        # The 10,001st must fail deterministically
        overflow = wa2.resolve("root:repo/src/overflow.py", require_exists=False)
        assert not overflow.ok
        assert "capacity exceeded" in (overflow.error_message or "").lower()


# =========================================================================
# REG-04: Token Uniqueness Under Volume
# =========================================================================

class TestREG04TokenUniquenessVolume:
    """1,000 resolves of the same input produce 1,000 unique tokens."""

    def test_1000_unique_tokens(self, wa2: WorldAdapterV2) -> None:
        tokens = [
            wa2.resolve("root:repo/src", require_exists=False).ref.token
            for _ in range(1000)
        ]
        assert len(set(tokens)) == 1000
