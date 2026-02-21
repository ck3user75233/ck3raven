"""
Script Signing — sign/verify round-trip and content-hash-mismatch tests.

Tests cover:
    1. Happy path: sign → validate → True
    2. Content hash mismatch: sign → tamper hash → validate → False
    3. Path mismatch: sign → change path → validate → False
    4. Missing signature: no script_signature → validate → False
    5. Expired contract rejected by signer
    6. Closed contract rejected by signer
    7. Sigil unavailable → signer raises, verifier returns False
    8. Cross-contract forgery rejected
    9. exec_gate integration: whitelisted, valid script, invalid script, no contract
"""
from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure ck3lens package is importable
_MCP_ROOT = Path(__file__).resolve().parent.parent.parent / "tools" / "ck3lens_mcp"
if str(_MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MCP_ROOT))

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ck3lens.policy.contract_v1 import (
    ContractV1,
    ContractTarget,
    WorkDeclaration,
    sign_script_for_contract,
    validate_script_signature,
)


# =============================================================================
# Fixtures
# =============================================================================

# Fixed "secret" for deterministic testing
_TEST_SECRET_HEX = "deadbeefcafebabe1234567890abcdef"


@pytest.fixture(autouse=True)
def _set_sigil_secret(monkeypatch):
    """Inject a test Sigil secret so sign/verify work without the extension."""
    monkeypatch.setenv("CK3LENS_SIGIL_SECRET", _TEST_SECRET_HEX)


def _make_contract(
    *,
    contract_id: str = "v1-2026-01-01-aaaaaa",
    status: str = "open",
    expires_at: str | None = None,
) -> ContractV1:
    """Build a minimal valid contract for testing."""
    if expires_at is None:
        expires_at = (datetime.now() + timedelta(hours=8)).isoformat()

    return ContractV1(
        contract_id=contract_id,
        mode="ck3raven-dev",
        root_category="ROOT_REPO",
        intent="test script signing",
        operations=["EXEC_COMMANDS"],
        targets=[ContractTarget(path="wip:/test.py", description="test script")],
        work_declaration=WorkDeclaration(
            work_summary="Execute test script",
            work_plan=["Run test.py"],
            edits=["wip:/test.py"],
        ),
        created_at=datetime.now().isoformat(),
        author="test",
        expires_at=expires_at,
        status=status,
    )


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# =============================================================================
# 1. Happy path — sign then validate
# =============================================================================


class TestSignVerifyRoundTrip:
    """Sign a script, then validate — should pass."""

    def test_round_trip_succeeds(self):
        contract = _make_contract()
        script_path = "/home/user/.ck3raven/wip/analysis.py"
        content = "print('hello world')"
        content_hash = _sha256(content)

        sig_dict = sign_script_for_contract(contract, script_path, content_hash)

        # Signature dict has expected keys
        assert "script_path" in sig_dict
        assert "content_sha256" in sig_dict
        assert "signature" in sig_dict
        assert "signed_at" in sig_dict

        # Values match inputs
        assert sig_dict["script_path"] == script_path
        assert sig_dict["content_sha256"] == content_hash

        # Signature is a hex string (HMAC-SHA256 = 64 hex chars)
        assert len(sig_dict["signature"]) == 64

        # Contract now has script_signature set
        assert contract.script_signature is sig_dict

        # Validate passes with same inputs
        assert validate_script_signature(contract, script_path, content_hash) is True

    def test_round_trip_different_scripts(self):
        """Two different scripts get different signatures."""
        contract = _make_contract()
        path_a = "/home/user/.ck3raven/wip/a.py"
        path_b = "/home/user/.ck3raven/wip/b.py"
        hash_a = _sha256("script a")
        hash_b = _sha256("script b")

        sig_a = sign_script_for_contract(contract, path_a, hash_a)

        # Re-sign for different script (overwrites)
        sig_b = sign_script_for_contract(contract, path_b, hash_b)

        assert sig_a["signature"] != sig_b["signature"]

        # Only the LAST signature validates
        assert validate_script_signature(contract, path_b, hash_b) is True
        assert validate_script_signature(contract, path_a, hash_a) is False


# =============================================================================
# 2. Content hash mismatch — THE key test
# =============================================================================


class TestContentHashMismatch:
    """Sign with one hash, validate with different content → MUST fail."""

    def test_changed_content_rejected(self):
        """User's priority: 'stop files with changed content hashes'."""
        contract = _make_contract()
        script_path = "/home/user/.ck3raven/wip/analysis.py"

        original_content = "import pandas\ndf = pd.read_csv('data.csv')"
        original_hash = _sha256(original_content)

        # Sign with original content
        sign_script_for_contract(contract, script_path, original_hash)

        # Tamper: someone modifies the script after signing
        tampered_content = "import os\nos.system('rm -rf /')"
        tampered_hash = _sha256(tampered_content)

        # Validation MUST reject
        assert validate_script_signature(contract, script_path, tampered_hash) is False

    def test_single_byte_change_rejected(self):
        """Even a single byte change invalidates the signature."""
        contract = _make_contract()
        script_path = "/home/user/.ck3raven/wip/test.py"

        original = "x = 1"
        changed = "x = 2"

        sign_script_for_contract(contract, script_path, _sha256(original))
        assert validate_script_signature(contract, script_path, _sha256(changed)) is False

    def test_whitespace_change_rejected(self):
        """Even whitespace changes are caught (SHA-256 is content-exact)."""
        contract = _make_contract()
        script_path = "/home/user/.ck3raven/wip/test.py"

        original = "x = 1\n"
        changed = "x = 1\n\n"  # extra newline

        sign_script_for_contract(contract, script_path, _sha256(original))
        assert validate_script_signature(contract, script_path, _sha256(changed)) is False

    def test_original_still_valid_after_tamper_attempt(self):
        """Original hash still validates (signature wasn't corrupted)."""
        contract = _make_contract()
        script_path = "/home/user/.ck3raven/wip/test.py"
        original_hash = _sha256("original content")

        sign_script_for_contract(contract, script_path, original_hash)

        # Failed tamper check doesn't corrupt signature
        tampered_hash = _sha256("tampered")
        assert validate_script_signature(contract, script_path, tampered_hash) is False

        # Original still works
        assert validate_script_signature(contract, script_path, original_hash) is True


# =============================================================================
# 3. Path mismatch
# =============================================================================


class TestPathMismatch:
    """Sign for path A, validate for path B → MUST fail."""

    def test_different_path_rejected(self):
        contract = _make_contract()
        path_signed = "/home/user/.ck3raven/wip/safe.py"
        path_check = "/home/user/.ck3raven/wip/evil.py"
        content_hash = _sha256("x = 1")

        sign_script_for_contract(contract, path_signed, content_hash)
        assert validate_script_signature(contract, path_check, content_hash) is False

    def test_similar_path_rejected(self):
        """Paths that are substrings of each other still fail."""
        contract = _make_contract()
        content_hash = _sha256("x = 1")

        sign_script_for_contract(contract, "/wip/test.py", content_hash)
        assert validate_script_signature(contract, "/wip/test.py2", content_hash) is False
        assert validate_script_signature(contract, "/wip/test.p", content_hash) is False


# =============================================================================
# 4. Missing signature
# =============================================================================


class TestMissingSignature:
    """No script_signature on contract → validate returns False."""

    def test_no_signature_returns_false(self):
        contract = _make_contract()
        assert contract.script_signature is None
        assert validate_script_signature(contract, "/any/path.py", _sha256("x")) is False

    def test_empty_dict_returns_false(self):
        contract = _make_contract()
        contract.script_signature = {}
        assert validate_script_signature(contract, "/any/path.py", _sha256("x")) is False

    def test_partial_dict_returns_false(self):
        """Signature dict missing required keys."""
        contract = _make_contract()
        contract.script_signature = {"script_path": "/x.py"}
        assert validate_script_signature(contract, "/x.py", _sha256("x")) is False


# =============================================================================
# 5. Expired / closed contract rejected by signer
# =============================================================================


class TestContractStateGuards:
    """Signer refuses to sign for inactive contracts."""

    def test_expired_contract_raises(self):
        expired_at = (datetime.now() - timedelta(hours=1)).isoformat()
        contract = _make_contract(expires_at=expired_at)

        with pytest.raises(ValueError, match="not active"):
            sign_script_for_contract(contract, "/wip/x.py", _sha256("x"))

    def test_closed_contract_raises(self):
        contract = _make_contract(status="closed")

        with pytest.raises(ValueError, match="not active"):
            sign_script_for_contract(contract, "/wip/x.py", _sha256("x"))


# =============================================================================
# 6. Sigil unavailable
# =============================================================================


class TestSigilUnavailable:
    """Without Sigil secret, signer raises and verifier returns False."""

    def test_signer_raises_without_sigil(self, monkeypatch):
        monkeypatch.delenv("CK3LENS_SIGIL_SECRET", raising=False)
        contract = _make_contract()

        with pytest.raises(RuntimeError, match="Sigil not available"):
            sign_script_for_contract(contract, "/wip/x.py", _sha256("x"))

    def test_verifier_returns_false_without_sigil(self, monkeypatch):
        # Sign with secret present
        contract = _make_contract()
        sign_script_for_contract(contract, "/wip/x.py", _sha256("x"))

        # Remove secret — verifier should return False, not raise
        monkeypatch.delenv("CK3LENS_SIGIL_SECRET", raising=False)
        assert validate_script_signature(contract, "/wip/x.py", _sha256("x")) is False


# =============================================================================
# 7. Cross-contract forgery
# =============================================================================


class TestCrossContractForgery:
    """Signature from contract A cannot be used on contract B."""

    def test_different_contract_id_rejected(self):
        contract_a = _make_contract(contract_id="v1-2026-01-01-aaaaaa")
        contract_b = _make_contract(contract_id="v1-2026-01-01-bbbbbb")

        script_path = "/home/user/.ck3raven/wip/test.py"
        content_hash = _sha256("x = 1")

        # Sign under contract A
        sig = sign_script_for_contract(contract_a, script_path, content_hash)

        # Copy signature to contract B
        contract_b.script_signature = dict(sig)

        # Must fail — contract_id is part of the HMAC payload
        assert validate_script_signature(contract_b, script_path, content_hash) is False


# =============================================================================
# 8. exec_gate integration
# =============================================================================


class TestExecGateIntegration:
    """Test exec_gate predicate with signing pipeline."""

    def test_valid_signed_script_passes_exec_gate(self):
        """Full pipeline: sign script → exec_gate returns True."""
        from ck3lens.capability_matrix_v2 import exec_gate

        contract = _make_contract()
        script_path = "/home/user/.ck3raven/wip/analysis.py"
        content = "print('analysis')"
        content_hash = _sha256(content)

        # Sign the script
        sign_script_for_contract(contract, script_path, content_hash)

        gate = exec_gate()

        # Mock get_active_contract to return our test contract
        with patch(
            "ck3lens.policy.contract_v1.get_active_contract",
            return_value=contract,
        ):
            result = gate.check(
                exec_command=f"python {script_path}",
                exec_subdirectory="wip",
                has_contract=True,
                script_host_path=script_path,
                content_sha256=content_hash,
            )
            assert result is True

    def test_tampered_script_fails_exec_gate(self):
        """Sign then tamper → exec_gate returns False."""
        from ck3lens.capability_matrix_v2 import exec_gate

        contract = _make_contract()
        script_path = "/home/user/.ck3raven/wip/analysis.py"
        original_hash = _sha256("safe code")
        tampered_hash = _sha256("malicious code")

        # Sign with original
        sign_script_for_contract(contract, script_path, original_hash)

        gate = exec_gate()

        with patch(
            "ck3lens.policy.contract_v1.get_active_contract",
            return_value=contract,
        ):
            result = gate.check(
                exec_command=f"python {script_path}",
                exec_subdirectory="wip",
                has_contract=True,
                script_host_path=script_path,
                content_sha256=tampered_hash,
            )
            assert result is False

    def test_no_contract_fails_exec_gate(self):
        """Without contract, non-whitelisted exec → False."""
        from ck3lens.capability_matrix_v2 import exec_gate

        gate = exec_gate()
        result = gate.check(
            exec_command="python /wip/x.py",
            exec_subdirectory="wip",
            has_contract=False,
            script_host_path="/wip/x.py",
            content_sha256=_sha256("x"),
        )
        assert result is False

    def test_script_outside_wip_fails(self):
        """Script not in wip subdirectory → False."""
        from ck3lens.capability_matrix_v2 import exec_gate

        contract = _make_contract()
        script_path = "/home/user/.ck3raven/scripts/test.py"
        content_hash = _sha256("x = 1")
        sign_script_for_contract(contract, script_path, content_hash)

        gate = exec_gate()

        with patch(
            "ck3lens.policy.contract_v1.get_active_contract",
            return_value=contract,
        ):
            result = gate.check(
                exec_command=f"python {script_path}",
                exec_subdirectory="scripts",  # NOT wip
                has_contract=True,
                script_host_path=script_path,
                content_sha256=content_hash,
            )
            assert result is False

    def test_whitelisted_command_bypasses_signing(self):
        """Whitelisted commands pass without any signing."""
        from ck3lens.capability_matrix_v2 import exec_gate

        gate = exec_gate()

        # Temporarily inject a whitelisted command
        import ck3lens.capability_matrix_v2 as cm

        old_cache = cm._WHITELIST_CACHE
        try:
            cm._WHITELIST_CACHE = ["git status"]
            result = gate.check(
                exec_command="git status --short",
                exec_subdirectory=None,
                has_contract=False,
            )
            assert result is True
        finally:
            cm._WHITELIST_CACHE = old_cache

    def test_empty_command_rejected(self):
        """Empty command string → False."""
        from ck3lens.capability_matrix_v2 import exec_gate

        gate = exec_gate()
        assert gate.check(exec_command="") is False
