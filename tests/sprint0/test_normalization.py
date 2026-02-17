"""
NORM-* — Input normalization tests.

Tests: NORM-01 (Legacy ROOT_X:/ accepted), NORM-02 (Legacy mod:Name:/),
       NORM-03 (Emitter never produces legacy forms)
"""
from __future__ import annotations

import re

import pytest

from ck3lens.world_adapter_v2 import WorldAdapterV2


# =========================================================================
# NORM-01: Legacy ROOT_X:/ Accepted
# =========================================================================

class TestNORM01LegacyRootAccepted:
    """Sprint 0 accepts legacy ROOT_REPO:/... syntax and normalizes to root:repo/..."""

    def test_legacy_root_repo(self, wa2: WorldAdapterV2) -> None:
        res = wa2.resolve("ROOT_REPO:/src/server.py")
        assert res.ok
        assert res.ref.session_abs == "root:repo/src/server.py"

    def test_legacy_root_game(self, wa2: WorldAdapterV2) -> None:
        res = wa2.resolve("ROOT_GAME:/common/traits/00_traits.txt")
        assert res.ok
        assert res.ref.session_abs == "root:game/common/traits/00_traits.txt"

    def test_legacy_root_ck3raven_data(self, wa2: WorldAdapterV2) -> None:
        res = wa2.resolve("ROOT_CK3RAVEN_DATA:/wip/analysis.py")
        assert res.ok
        assert res.ref.session_abs == "root:ck3raven_data/wip/analysis.py"


# =========================================================================
# NORM-02: Legacy mod:Name:/ Accepted
# =========================================================================

class TestNORM02LegacyModAccepted:
    """Sprint 0 accepts mod:Name:/path (colon-slash separator) and normalizes."""

    def test_legacy_mod_colon_slash(self, wa2: WorldAdapterV2) -> None:
        res = wa2.resolve("mod:TestModA:/common/traits")
        assert res.ok
        assert res.ref.session_abs == "mod:TestModA/common/traits"


# =========================================================================
# NORM-03: Emitter Never Produces Legacy Forms
# =========================================================================

class TestNORM03NeverEmitsLegacy:
    """No VisibilityResolution or VisibilityRef contains ROOT_ prefix or :/ separator."""

    _LEGACY_ROOT_RE = re.compile(r"ROOT_")
    _LEGACY_MOD_COLON_SLASH_RE = re.compile(r"mod:.*:/")

    @pytest.mark.parametrize(
        "input_str",
        [
            "root:repo/src/server.py",
            "ROOT_REPO:/src/server.py",
            "mod:TestModA/common",
            "mod:TestModA:/common",
            "root:game/common/traits/00_traits.txt",
        ],
    )
    def test_session_abs_no_legacy_root(self, wa2: WorldAdapterV2, input_str: str) -> None:
        res = wa2.resolve(input_str)
        if res.ok:
            assert not self._LEGACY_ROOT_RE.search(res.ref.session_abs), (
                f"Legacy ROOT_ found in session_abs: {res.ref.session_abs}"
            )

    @pytest.mark.parametrize(
        "input_str",
        [
            "mod:TestModA/common",
            "mod:TestModA:/common",
        ],
    )
    def test_session_abs_no_legacy_mod(self, wa2: WorldAdapterV2, input_str: str) -> None:
        res = wa2.resolve(input_str)
        if res.ok:
            assert not self._LEGACY_MOD_COLON_SLASH_RE.search(res.ref.session_abs), (
                f"Legacy mod colon-slash found in session_abs: {res.ref.session_abs}"
            )

    @pytest.mark.parametrize(
        "input_str",
        [
            "root:repo/src/server.py",
            "ROOT_REPO:/src/server.py",
        ],
    )
    def test_root_category_lowercase(self, wa2: WorldAdapterV2, input_str: str) -> None:
        res = wa2.resolve(input_str)
        if res.ok and res.root_category:
            assert res.root_category == res.root_category.lower(), (
                f"root_category not lowercase: {res.root_category}"
            )
            assert not res.root_category.startswith("ROOT_"), (
                f"root_category uses enum form: {res.root_category}"
            )
