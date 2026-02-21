"""
Sprint 0 shared fixtures — canonical addressing tests.

Provides make_wa2 factory, wa2 (ck3raven-dev), wa2_ck3lens fixtures.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

# Ensure ck3lens package is importable from the MCP tools directory.
_MCP_ROOT = Path(__file__).resolve().parent.parent.parent / "tools" / "ck3lens_mcp"
if str(_MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MCP_ROOT))

from ck3lens.world_adapter_v2 import WorldAdapterV2, VisibilityRef


# =============================================================================
# Mock Session — mimics session.mods and session.get_mod()
# =============================================================================

@dataclass
class MockMod:
    name: str
    path: Path


class MockSession:
    def __init__(self, mods: list[MockMod]):
        self.mods = mods
        self._by_name = {m.name: m for m in mods}

    def get_mod(self, name: str) -> Optional[MockMod]:
        return self._by_name.get(name)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def tmp_roots(tmp_path: Path) -> dict[str, Path]:
    """Create a minimal root structure for WA2 testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "server.py").write_text("# server")
    (repo / "docs").mkdir()
    (repo / "pyproject.toml").write_text("[project]")

    data = tmp_path / "ck3raven_data"
    data.mkdir()
    (data / "wip").mkdir()
    (data / "wip" / "analysis.py").write_text("# wip")

    game = tmp_path / "game"
    game.mkdir()
    (game / "common" / "traits").mkdir(parents=True)
    (game / "common" / "traits" / "00_traits.txt").write_text("# traits")

    # user_docs root with mod subdirectory
    user_docs = tmp_path / "user_docs"
    user_docs.mkdir()
    (user_docs / "mod").mkdir()

    return {
        "repo": repo,
        "ck3raven_data": data,
        "game": game,
        "user_docs": user_docs,
    }


@pytest.fixture
def tmp_mods(tmp_roots: dict[str, Path]) -> list[MockMod]:
    """Create mock mod directories under user_docs/mod/."""
    mod_a_path = tmp_roots["user_docs"] / "mod" / "TestModA"
    mod_a_path.mkdir(parents=True)
    (mod_a_path / "common" / "traits").mkdir(parents=True)
    (mod_a_path / "common" / "traits" / "zzz_patch.txt").write_text("# patch")

    return [MockMod(name="TestModA", path=mod_a_path)]


@pytest.fixture
def make_wa2(tmp_roots: dict[str, Path], tmp_mods: list[MockMod]):
    """Factory: returns (wa2_instance, context_manager) for any mode."""
    def _make(mode: str = "ck3raven-dev"):
        session = MockSession(tmp_mods)
        wa = WorldAdapterV2(
            session=session,
            roots={
                "repo": tmp_roots["repo"],
                "ck3raven_data": tmp_roots["ck3raven_data"],
                "game": tmp_roots["game"],
                "user_docs": tmp_roots["user_docs"],
            },
        )
        return wa, patch("ck3lens.world_adapter_v2._get_mode", return_value=mode)
    return _make


@pytest.fixture
def wa2(make_wa2):
    """WA2 in ck3raven-dev mode (unconditional visibility for all roots)."""
    wa, ctx = make_wa2("ck3raven-dev")
    with ctx:
        yield wa


@pytest.fixture
def wa2_ck3lens(make_wa2):
    """WA2 in ck3lens mode (path_in_session_mods conditions active on steam/user_docs)."""
    wa, ctx = make_wa2("ck3lens")
    with ctx:
        yield wa
