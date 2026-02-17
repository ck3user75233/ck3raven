"""
DIR-* — ck3_dir command tests.

Tests: DIR-01 through DIR-11 — pwd, cd, list, tree, and leak detection
on all outputs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ck3lens.world_adapter_v2 import WorldAdapterV2, VALID_ROOT_KEYS
from ck3lens.impl.dir_ops import (
    ck3_dir_impl,
    get_session_home_root,
    set_session_home_root,
)
from ck3lens.leak_detector import check_no_host_paths


# =========================================================================
# Helper: reset session home root around each test
# =========================================================================

@pytest.fixture(autouse=True)
def _reset_home():
    """Reset session home root to default before each test."""
    set_session_home_root("ck3raven_data")
    yield
    set_session_home_root("ck3raven_data")


# =========================================================================
# DIR-01: pwd Returns Default Home
# =========================================================================

class TestDIR01PwdDefault:
    """Initial pwd returns ck3raven_data."""

    def test_pwd_default(self, wa2: WorldAdapterV2) -> None:
        data = ck3_dir_impl("pwd", wa2=wa2)
        assert data["home"] == "root:ck3raven_data/"
        assert data["root_category"] == "ck3raven_data"


# =========================================================================
# DIR-02: cd Changes Home
# =========================================================================

class TestDIR02CdChangesHome:
    """cd root:repo changes the home root."""

    def test_cd_then_pwd(self, wa2: WorldAdapterV2) -> None:
        result = ck3_dir_impl("cd", path="root:repo", wa2=wa2)
        assert result["home"] == "root:repo/"

        pwd = ck3_dir_impl("pwd", wa2=wa2)
        assert pwd["home"] == "root:repo/"

    def test_cd_bare_key(self, wa2: WorldAdapterV2) -> None:
        result = ck3_dir_impl("cd", path="game", wa2=wa2)
        assert result["home"] == "root:game/"


# =========================================================================
# DIR-03: cd Invalid Root → ValueError
# =========================================================================

class TestDIR03CdInvalid:
    """cd with invalid root or subdirectory fails."""

    def test_cd_bogus_root(self, wa2: WorldAdapterV2) -> None:
        with pytest.raises(ValueError):
            ck3_dir_impl("cd", path="root:bogus", wa2=wa2)

    def test_cd_subdirectory_rejected(self, wa2: WorldAdapterV2) -> None:
        with pytest.raises(ValueError, match="Subdirectory homing"):
            ck3_dir_impl("cd", path="root:repo/some/subdir", wa2=wa2)


# =========================================================================
# DIR-04: list Home Directory
# =========================================================================

class TestDIR04ListHome:
    """list with no path lists the current home directory."""

    def test_list_default_home(self, wa2: WorldAdapterV2) -> None:
        data = ck3_dir_impl("list", wa2=wa2)
        assert "entries" in data
        assert isinstance(data["entries"], list)
        for entry in data["entries"]:
            assert "name" in entry
            assert "path" in entry
            assert "type" in entry
            # All paths must be session-absolute
            assert entry["path"].startswith("root:") or entry["path"].startswith("mod:")


# =========================================================================
# DIR-05: list Explicit Path
# =========================================================================

class TestDIR05ListExplicit:
    """list root:repo/src lists contents of the src directory."""

    def test_list_repo_src(self, wa2: WorldAdapterV2) -> None:
        data = ck3_dir_impl("list", path="root:repo/src", wa2=wa2)
        names = [e["name"] for e in data["entries"]]
        assert "server.py" in names
        # Check the server.py entry is a file
        server_entry = [e for e in data["entries"] if e["name"] == "server.py"][0]
        assert server_entry["type"] == "file"


# =========================================================================
# DIR-06: list Non-Directory → ValueError
# =========================================================================

class TestDIR06ListNonDir:
    """Listing a file (not directory) fails."""

    def test_list_file_raises(self, wa2: WorldAdapterV2) -> None:
        with pytest.raises(ValueError, match="Not a directory"):
            ck3_dir_impl("list", path="root:repo/pyproject.toml", wa2=wa2)


# =========================================================================
# DIR-07: list Non-Existent → ValueError
# =========================================================================

class TestDIR07ListNonExistent:
    """Listing a non-existent path fails."""

    def test_list_nonexistent_raises(self, wa2: WorldAdapterV2) -> None:
        with pytest.raises(ValueError):
            ck3_dir_impl("list", path="root:repo/nonexistent_dir", wa2=wa2)


# =========================================================================
# DIR-08: list Host Path Input → ValueError
# =========================================================================

class TestDIR08ListHostPath:
    """Host-absolute paths are rejected by resolve (Invariant A)."""

    def test_host_path_rejected(self, wa2: WorldAdapterV2) -> None:
        with pytest.raises(ValueError):
            ck3_dir_impl("list", path=r"C:\Users\nate\Documents", wa2=wa2)


# =========================================================================
# DIR-09: tree Default Depth
# =========================================================================

class TestDIR09TreeDefault:
    """tree returns directory structure with default depth=3."""

    def test_tree_repo(self, wa2: WorldAdapterV2) -> None:
        # cd to repo first since ck3raven_data may be minimal
        ck3_dir_impl("cd", path="root:repo", wa2=wa2)
        data = ck3_dir_impl("tree", wa2=wa2)
        assert data["depth"] == 3
        assert "directories" in data
        # All path values must be session-absolute
        for d in data["directories"]:
            assert d["path"].startswith("root:")


# =========================================================================
# DIR-10: tree Custom Depth
# =========================================================================

class TestDIR10TreeCustomDepth:
    """tree with depth=1 returns only one level."""

    def test_tree_depth_1(self, wa2: WorldAdapterV2) -> None:
        data = ck3_dir_impl("tree", path="root:repo", depth=1, wa2=wa2)
        assert data["depth"] == 1
        for d in data["directories"]:
            # At depth=1, children lists should all be empty
            assert d["children"] == []


# =========================================================================
# DIR-11: No Host Paths in Any Output
# =========================================================================

class TestDIR11NoHostPathsInOutput:
    """Run leak detector on Reply.data for every successful dir command."""

    def test_pwd_no_leak(self, wa2: WorldAdapterV2) -> None:
        data = ck3_dir_impl("pwd", wa2=wa2)
        check_no_host_paths(data, context="DIR-11.pwd")

    def test_cd_no_leak(self, wa2: WorldAdapterV2) -> None:
        data = ck3_dir_impl("cd", path="root:repo", wa2=wa2)
        check_no_host_paths(data, context="DIR-11.cd")

    def test_list_no_leak(self, wa2: WorldAdapterV2) -> None:
        data = ck3_dir_impl("list", path="root:repo/src", wa2=wa2)
        check_no_host_paths(data, context="DIR-11.list")

    def test_tree_no_leak(self, wa2: WorldAdapterV2) -> None:
        data = ck3_dir_impl("tree", path="root:repo", depth=2, wa2=wa2)
        check_no_host_paths(data, context="DIR-11.tree")
