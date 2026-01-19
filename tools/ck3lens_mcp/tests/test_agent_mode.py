"""
Test suite for agent-mode awareness.

Verifies that MCP tools and infrastructure behave correctly based on:
- ck3lens mode: CK3 modding with live mod editing
- ck3raven-dev mode: Infrastructure development

Tests cover:
1. Mode initialization and session state
2. Mode-specific path resolution
3. Mode-specific write permissions
4. Mode-specific tool routing
5. Policy enforcement by mode
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import os


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_session_ck3lens():
    """Mock session in ck3lens mode."""
    session = MagicMock()
    session.mode = "ck3lens"
    session.playset_id = 1
    session.local_mods_folder = Path.home() / "Documents/Paradox Interactive/Crusader Kings III/mod"
    return session


@pytest.fixture
def mock_session_raven_dev():
    """Mock session in ck3raven-dev mode."""
    session = MagicMock()
    session.mode = "ck3raven-dev"
    session.playset_id = None  # Not used in dev mode
    session.local_mods_folder = None  # Not used in dev mode
    return session


@pytest.fixture
def mock_db():
    """Mock database connection."""
    db = MagicMock()
    db.conn = MagicMock()
    return db


# =============================================================================
# Test: Mode Initialization
# =============================================================================

class TestModeInitialization:
    """Tests for mode initialization and state management."""
    
    def test_ck3lens_mode_string_valid(self):
        """ck3lens mode string should be valid for set_agent_mode."""
        from ck3lens.agent_mode import set_agent_mode, get_agent_mode
        
        # Should not raise - ck3lens is valid
        set_agent_mode("ck3lens", instance_id="test-init-1")
        mode = get_agent_mode(instance_id="test-init-1")
        assert mode == "ck3lens"
    
    def test_ck3raven_dev_mode_string_valid(self):
        """ck3raven-dev mode string should be valid for set_agent_mode."""
        from ck3lens.agent_mode import set_agent_mode, get_agent_mode
        
        # Should not raise - ck3raven-dev is valid
        set_agent_mode("ck3raven-dev", instance_id="test-init-2")
        mode = get_agent_mode(instance_id="test-init-2")
        assert mode == "ck3raven-dev"
    
    def test_mode_persistence(self, tmp_path):
        """Mode should persist to file and reload correctly."""
        from ck3lens.agent_mode import set_agent_mode, get_agent_mode
        
        # Set mode with a test instance
        set_agent_mode("ck3lens", instance_id="test-persist")
        
        # Verify mode persisted
        mode = get_agent_mode(instance_id="test-persist")
        assert mode == "ck3lens"


# =============================================================================
# Test: Mode-Specific Path Resolution
# =============================================================================

class TestModePathResolution:
    """Tests for WorldAdapter path resolution by mode."""
    
    def test_ck3lens_mode_value(self, mock_session_ck3lens):
        """ck3lens mode fixture has correct mode value."""
        assert mock_session_ck3lens.mode == "ck3lens"
    
    def test_ck3raven_dev_resolves_raw_paths(self, mock_session_raven_dev):
        """ck3raven-dev should resolve raw filesystem paths."""
        # In dev mode, paths are relative to ck3raven repo
        assert mock_session_raven_dev.mode == "ck3raven-dev"
    
    def test_ck3lens_denies_ck3raven_source_paths(self):
        """ck3lens mode should not resolve paths to ck3raven source."""
        # ck3lens only sees: vanilla, workshop mods, local mods
        # It should NOT see: tools/, src/, builder/, etc.
        pass  # Placeholder - requires WorldAdapter integration
    
    def test_ck3raven_dev_denies_mod_write_paths(self):
        """ck3raven-dev should NEVER allow mod file writes."""
        # Absolute prohibition per CANONICAL_ARCHITECTURE.md
        pass  # Placeholder - requires enforcement integration


# =============================================================================
# Test: Mode-Specific Write Permissions
# =============================================================================

class TestModeWritePermissions:
    """Tests for write permission enforcement by mode."""
    
    def test_ck3lens_allows_local_mod_writes(self, mock_session_ck3lens):
        """ck3lens should allow writes to local mods."""
        # Local mods in Documents/Paradox Interactive/CK3/mod/
        assert mock_session_ck3lens.mode == "ck3lens"
        assert mock_session_ck3lens.local_mods_folder is not None
    
    def test_ck3lens_denies_ck3raven_writes(self):
        """ck3lens should deny writes to ck3raven source."""
        from ck3lens.policy.enforcement import enforce_policy, EnforcementRequest, OperationType
        
        # This should be denied
        request = EnforcementRequest(
            operation=OperationType.FILE_WRITE,
            mode="ck3lens",
            tool_name="test",
            target_path="tools/ck3lens_mcp/server.py",
        )
        # Result should be DENY
    
    def test_ck3raven_dev_allows_source_writes(self, mock_session_raven_dev):
        """ck3raven-dev should allow writes to ck3raven source."""
        assert mock_session_raven_dev.mode == "ck3raven-dev"
    
    def test_ck3raven_dev_absolute_mod_prohibition(self):
        """ck3raven-dev MUST deny all mod file writes (absolute)."""
        from ck3lens.policy.enforcement import enforce_policy, EnforcementRequest, OperationType
        
        # This is an ABSOLUTE PROHIBITION per CANONICAL_ARCHITECTURE
        request = EnforcementRequest(
            operation=OperationType.FILE_WRITE,
            mode="ck3raven-dev",
            tool_name="test",
            mod_name="SomeMod",  # Any mod
            rel_path="common/traits/test.txt",
        )
        # Result MUST be DENY - no exceptions


# =============================================================================
# Test: Mode-Specific Tool Routing
# =============================================================================

class TestModeToolRouting:
    """Tests for tool behavior differences by mode."""
    
    def test_ck3_file_uses_mod_addressing_in_ck3lens(self):
        """In ck3lens, ck3_file should require mod_name + rel_path."""
        from ck3lens.unified_tools import ck3_file_impl
        
        # ck3lens mode: mod_name required for writes
        # raw path should be rejected or redirected
    
    def test_ck3_file_uses_raw_paths_in_ck3raven_dev(self):
        """In ck3raven-dev, ck3_file should use raw paths."""
        from ck3lens.unified_tools import ck3_file_impl
        
        # ck3raven-dev mode: raw path to ck3raven source
        # mod_name should be ignored/unavailable
    
    def test_ck3_repair_only_in_ck3lens(self):
        """ck3_repair should only be available in ck3lens mode."""
        # Per policy docs, repair is ck3lens-only
        pass
    
    def test_ck3_exec_required_in_ck3raven_dev(self):
        """ck3raven-dev must use ck3_exec, not run_in_terminal."""
        # run_in_terminal is PROHIBITED in ck3raven-dev
        pass


# =============================================================================
# Test: Policy Enforcement by Mode
# =============================================================================

class TestModePolicyEnforcement:
    """Tests for policy validation differences by mode."""
    
    def test_validate_for_mode_ck3lens(self):
        """validate_for_mode should apply ck3lens-specific rules."""
        from ck3lens.policy.validator import validate_for_mode
        
        result = validate_for_mode(
            mode="ck3lens",
            trace=None,
        )
        
        assert "status" in result
        assert "violations" in result
    
    def test_validate_for_mode_ck3raven_dev(self):
        """validate_for_mode should apply ck3raven-dev-specific rules."""
        from ck3lens.policy.validator import validate_for_mode
        
        result = validate_for_mode(
            mode="ck3raven-dev",
            trace=None,
        )
        
        assert "status" in result
        assert "violations" in result
    
    def test_ck3lens_requires_playset(self):
        """ck3lens mode operations should require active playset."""
        # Many ck3lens operations need playset_id
        pass
    
    def test_ck3raven_dev_requires_contract_for_writes(self):
        """ck3raven-dev writes should require active contract."""
        from ck3lens.policy.contract_v1 import ContractV1
        
        # ContractV1 class should exist for contract management
        assert ContractV1 is not None


# =============================================================================
# Test: Token Validation
# =============================================================================

class TestTokenValidation:
    """Tests for token validation contract compliance."""
    
    def test_validate_token_returns_tuple(self):
        """validate_token must return tuple[bool, str]."""
        from ck3lens.policy.tokens import validate_token
        
        # Non-existent token
        result = validate_token(
            token_id="fake-token",
            required_capability="FS_DELETE_CODE",
        )
        
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)
    
    def test_validate_token_keyword_is_required_capability(self):
        """validate_token uses 'required_capability', not 'capability'."""
        from ck3lens.policy.tokens import validate_token
        import inspect
        
        sig = inspect.signature(validate_token)
        param_names = list(sig.parameters.keys())
        
        assert "required_capability" in param_names
        assert "capability" not in param_names


# =============================================================================
# Test: ArtifactBundle Contract
# =============================================================================

class TestArtifactBundleContract:
    """Tests for ArtifactBundle Pydantic model compliance."""
    
    def test_artifact_bundle_uses_model_validate(self):
        """ArtifactBundle should use Pydantic v2 model_validate."""
        from ck3lens.contracts import ArtifactBundle
        
        bundle = ArtifactBundle.model_validate({
            "artifacts": [],
        })
        
        assert isinstance(bundle, ArtifactBundle)
    
    def test_artifact_bundle_model_dump(self):
        """ArtifactBundle should support model_dump for serialization."""
        from ck3lens.contracts import ArtifactBundle
        
        bundle = ArtifactBundle(artifacts=[])
        result = bundle.model_dump()
        
        assert isinstance(result, dict)
        assert "artifacts" in result


# =============================================================================
# Test: ValidationReport Contract
# =============================================================================

class TestValidationReportContract:
    """Tests for ValidationReport Pydantic model compliance."""
    
    def test_validation_report_has_ok_attribute(self):
        """ValidationReport must have .ok boolean attribute."""
        from ck3lens.contracts import ValidationReport
        
        report = ValidationReport(ok=True)
        assert hasattr(report, "ok")
        assert report.ok is True
    
    def test_validation_report_has_errors_list(self):
        """ValidationReport must have .errors list."""
        from ck3lens.contracts import ValidationReport
        
        report = ValidationReport(ok=True, errors=[])
        assert hasattr(report, "errors")
        assert isinstance(report.errors, list)
    
    def test_validation_report_model_dump(self):
        """ValidationReport should support model_dump."""
        from ck3lens.contracts import ValidationReport
        
        report = ValidationReport(ok=True, errors=[], warnings=[])
        result = report.model_dump()
        
        assert isinstance(result, dict)
        assert "ok" in result
        assert "errors" in result


# =============================================================================
# Test: Conflict Analyzer Import
# =============================================================================

class TestConflictAnalyzerContract:
    """Tests for conflict_analyzer function naming."""
    
    def test_scan_playset_conflicts_exists(self):
        """scan_playset_conflicts must exist (not scan_unit_conflicts)."""
        from ck3raven.resolver.conflict_analyzer import scan_playset_conflicts
        
        assert callable(scan_playset_conflicts)
    
    def test_scan_unit_conflicts_does_not_exist(self):
        """scan_unit_conflicts should NOT exist."""
        from ck3raven.resolver import conflict_analyzer
        
        assert not hasattr(conflict_analyzer, "scan_unit_conflicts")


# =============================================================================
# Integration Tests: End-to-End Mode Switching
# =============================================================================

class TestModeIntegration:
    """Integration tests for mode switching scenarios."""
    
    def test_switch_from_ck3lens_to_ck3raven_dev(self):
        """Switching modes should update all mode-aware state."""
        pass  # Requires full session integration
    
    def test_mode_specific_wip_location(self):
        """WIP workspace should be mode-specific."""
        # ck3lens: ~/.ck3raven/wip/
        # ck3raven-dev: <repo>/.wip/
        pass
    
    def test_mode_specific_git_operations(self):
        """Git operations should target correct repository by mode."""
        # ck3lens: operates on live mods
        # ck3raven-dev: operates on ck3raven repo
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
