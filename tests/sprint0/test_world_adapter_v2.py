"""
WA2-* — WorldAdapterV2 resolution tests.

Tests: WA2-01 through WA2-10, including the non-truncation guarantee.
"""
from __future__ import annotations

import pytest

from ck3lens.world_adapter_v2 import WorldAdapterV2


# =========================================================================
# WA2-01: Root Address Resolution
# =========================================================================

class TestWA201RootResolution:
    """Canonical root:<key>/<path> addresses resolve correctly."""

    @pytest.mark.parametrize(
        "input_str, expected_abs",
        [
            ("root:repo/src/server.py", "root:repo/src/server.py"),
            ("root:repo/src", "root:repo/src"),
            ("root:ck3raven_data/wip/analysis.py", "root:ck3raven_data/wip/analysis.py"),
            ("root:game/common/traits/00_traits.txt", "root:game/common/traits/00_traits.txt"),
        ],
    )
    def test_resolves_ok(self, wa2: WorldAdapterV2, input_str: str, expected_abs: str) -> None:
        res = wa2.resolve(input_str)
        assert res.ok, f"Expected ok=True for {input_str}, got: {res.error_message}"
        assert res.ref is not None
        assert res.ref.session_abs == expected_abs
        assert res.exists is True  # Adjustment 1


# =========================================================================
# WA2-02: Mod Address Resolution
# =========================================================================

class TestWA202ModResolution:
    """Canonical mod:<Name>/<path> addresses resolve correctly."""

    @pytest.mark.parametrize(
        "input_str, expected_abs",
        [
            ("mod:TestModA/common/traits/zzz_patch.txt", "mod:TestModA/common/traits/zzz_patch.txt"),
            ("mod:TestModA/common", "mod:TestModA/common"),
        ],
    )
    def test_resolves_ok(self, wa2: WorldAdapterV2, input_str: str, expected_abs: str) -> None:
        res = wa2.resolve(input_str)
        assert res.ok, f"Expected ok=True for {input_str}, got: {res.error_message}"
        assert res.ref is not None
        assert res.ref.session_abs == expected_abs
        assert res.exists is True  # Adjustment 1


# =========================================================================
# WA2-03: Unknown Root Key → Invalid
# =========================================================================

class TestWA203UnknownRootKey:
    """Using an invalid root key fails."""

    def test_bogus_key(self, wa2: WorldAdapterV2) -> None:
        res = wa2.resolve("root:bogus/foo")
        assert not res.ok
        assert res.error_message is not None


# =========================================================================
# WA2-04: Unknown Mod → Invalid
# =========================================================================

class TestWA204UnknownMod:
    """Referencing a mod not in mod_paths fails."""

    def test_nonexistent_mod(self, wa2: WorldAdapterV2) -> None:
        res = wa2.resolve("mod:NonexistentMod/foo")
        assert not res.ok


# =========================================================================
# WA2-05: Host-Absolute Path → Invalid
# =========================================================================

class TestWA205HostAbsoluteRejected:
    """Raw host paths are rejected (Invariant A)."""

    @pytest.mark.parametrize(
        "input_str",
        [
            r"C:\Users\test\file.txt",
            "/home/test/file.txt",
            "/Users/nate/Documents/foo",
        ],
    )
    def test_host_path_rejected(self, wa2: WorldAdapterV2, input_str: str) -> None:
        res = wa2.resolve(input_str)
        assert not res.ok


# =========================================================================
# WA2-06: Path Traversal Rejected
# =========================================================================

class TestWA206PathTraversal:
    """.. components that escape a root are rejected."""

    @pytest.mark.parametrize(
        "input_str",
        [
            "root:repo/../../../etc/passwd",
            "mod:TestModA/../../secret",
        ],
    )
    def test_traversal_rejected(self, wa2: WorldAdapterV2, input_str: str) -> None:
        res = wa2.resolve(input_str)
        assert not res.ok


# =========================================================================
# WA2-07: require_exists=True, Path Missing → Invalid
# =========================================================================

class TestWA207RequireExistsMissing:
    """When require_exists=True (default), non-existent paths fail."""

    def test_missing_file(self, wa2: WorldAdapterV2) -> None:
        res = wa2.resolve("root:repo/nonexistent.py")
        assert not res.ok


# =========================================================================
# WA2-08: require_exists=False, Path Missing → Success with exists=False
# =========================================================================

class TestWA208RequireExistsFalse:
    """When require_exists=False, structurally valid but missing paths succeed."""

    def test_missing_ok(self, wa2: WorldAdapterV2) -> None:
        res = wa2.resolve("root:repo/nonexistent.py", require_exists=False)
        assert res.ok
        assert res.exists is False  # Adjustment 1
        assert res.ref is not None

    def test_host_path_recovery(self, wa2: WorldAdapterV2, tmp_roots: dict) -> None:
        res = wa2.resolve("root:repo/nonexistent.py", require_exists=False)
        host = wa2.host_path(res.ref)
        assert host is not None
        assert host.parent == tmp_roots["repo"]


# =========================================================================
# WA2-09: require_exists=False, Root Still Validated
# =========================================================================

class TestWA209RequireExistsFalseStillValidated:
    """Even with require_exists=False, invalid root keys or path escapes still fail."""

    def test_bogus_key(self, wa2: WorldAdapterV2) -> None:
        res = wa2.resolve("root:bogus/foo", require_exists=False)
        assert not res.ok

    def test_traversal_escape(self, wa2: WorldAdapterV2) -> None:
        res = wa2.resolve("root:repo/../../escape", require_exists=False)
        assert not res.ok


# =========================================================================
# WA2-10: Non-Truncation Guarantee  (Adjustment 2)
# =========================================================================

class TestWA210NonTruncation:
    """require_exists=False must NOT truncate to the last existing ancestor."""

    def test_full_path_preserved(self, wa2: WorldAdapterV2) -> None:
        res = wa2.resolve("root:repo/src/does_not_exist/file.py", require_exists=False)
        assert res.ok is True
        assert res.relative_path == "src/does_not_exist/file.py"
        assert res.ref.session_abs == "root:repo/src/does_not_exist/file.py"
        assert res.exists is False
