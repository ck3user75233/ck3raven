"""
Sprint 0 shared fixtures — canonical addressing tests.

Provides tmp_roots, tmp_mods, wa2 fixtures for all Sprint 0 tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure ck3lens package is importable from the MCP tools directory.
_MCP_ROOT = Path(__file__).resolve().parent.parent.parent / "tools" / "ck3lens_mcp"
if str(_MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MCP_ROOT))

from ck3lens.world_adapter_v2 import WorldAdapterV2, VisibilityRef, VisibilityResolution


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

    return {
        "repo": repo,
        "ck3raven_data": data,
        "game": game,
    }


@pytest.fixture
def tmp_mods(tmp_path: Path) -> dict[str, Path]:
    """Create mock mod directories."""
    mod_a = tmp_path / "mods" / "TestModA"
    mod_a.mkdir(parents=True)
    (mod_a / "common" / "traits").mkdir(parents=True)
    (mod_a / "common" / "traits" / "zzz_patch.txt").write_text("# patch")

    return {"TestModA": mod_a}


@pytest.fixture
def wa2(tmp_roots: dict[str, Path], tmp_mods: dict[str, Path]) -> WorldAdapterV2:
    """WorldAdapterV2 instance with test roots and mods."""
    return WorldAdapterV2(
        roots={
            "repo": tmp_roots["repo"],
            "ck3raven_data": tmp_roots["ck3raven_data"],
            "game": tmp_roots["game"],
        },
        mod_paths=tmp_mods,
    )
