"""
LEAK-* — Leak detector tests.

Tests: LEAK-01 through LEAK-08 — all host-path pattern detection and
false-positive avoidance.
"""
from __future__ import annotations

import pytest

from ck3lens.leak_detector import HostPathLeakError, check_no_host_paths


# =========================================================================
# LEAK-01: Detects Windows Drive Path
# =========================================================================

class TestLEAK01WindowsDrive:
    def test_windows_drive(self) -> None:
        with pytest.raises(HostPathLeakError):
            check_no_host_paths({"path": "C:\\Users\\nate\\file.txt"})


# =========================================================================
# LEAK-02: Detects UNC Path
# =========================================================================

class TestLEAK02UNC:
    def test_unc_path(self) -> None:
        with pytest.raises(HostPathLeakError):
            check_no_host_paths({"path": "\\\\server\\share"})


# =========================================================================
# LEAK-03: Detects macOS Home Path
# =========================================================================

class TestLEAK03MacOS:
    def test_macos_home(self) -> None:
        with pytest.raises(HostPathLeakError):
            check_no_host_paths({"path": "/Users/nate/Documents"})


# =========================================================================
# LEAK-04: Detects Linux Home Path
# =========================================================================

class TestLEAK04Linux:
    def test_linux_home(self) -> None:
        with pytest.raises(HostPathLeakError):
            check_no_host_paths({"path": "/home/nate/code"})


# =========================================================================
# LEAK-05: Detects WSL/Mount Path
# =========================================================================

class TestLEAK05WSL:
    def test_wsl_mount(self) -> None:
        with pytest.raises(HostPathLeakError):
            check_no_host_paths({"path": "/mnt/c/Users/nate"})


# =========================================================================
# LEAK-06: Nested Detection
# =========================================================================

class TestLEAK06Nested:
    """Host paths buried in nested structures are found."""

    def test_nested_in_list(self) -> None:
        with pytest.raises(HostPathLeakError):
            check_no_host_paths({"entries": [{"name": "x", "path": "C:\\bad"}]})

    def test_deeply_nested_dict(self) -> None:
        with pytest.raises(HostPathLeakError):
            check_no_host_paths({"a": {"b": {"c": "/home/nate/x"}}})

    def test_nested_in_tuple(self) -> None:
        with pytest.raises(HostPathLeakError):
            check_no_host_paths({"items": ("safe", "/Users/leaked/path")})


# =========================================================================
# LEAK-07: Session-Absolute Addresses Pass
# =========================================================================

class TestLEAK07SessionAbsPass:
    """Canonical addresses do NOT trigger false positives."""

    def test_root_address(self) -> None:
        # Must NOT raise
        check_no_host_paths({"path": "root:repo/src/server.py"})

    def test_mod_address(self) -> None:
        check_no_host_paths({"path": "mod:TestMod/common/traits"})

    def test_nested_addresses(self) -> None:
        check_no_host_paths({
            "entries": [{"path": "root:game/common/"}],
        })


# =========================================================================
# LEAK-08: Empty and None Values Pass
# =========================================================================

class TestLEAK08EmptyNone:
    """Empty dicts/strings and None values pass safely."""

    def test_empty_dict(self) -> None:
        check_no_host_paths({})

    def test_none_value(self) -> None:
        check_no_host_paths({"x": None})

    def test_empty_string(self) -> None:
        check_no_host_paths({"x": ""})

    def test_int_value(self) -> None:
        check_no_host_paths({"count": 42})

    def test_bool_value(self) -> None:
        check_no_host_paths({"ok": True})
