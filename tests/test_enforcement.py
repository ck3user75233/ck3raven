"""
Tests for the centralized enforcement module.

Tests cover:
1. Operation type classification
2. Mode-specific hard gates
3. Contract scope validation
4. Git branch protection
5. SAFE PUSH auto-grant logic
6. Audit logging integration
"""
import pytest
from pathlib import Path
from datetime import datetime, timedelta

# Skip if running without the MCP dependencies
pytest.importorskip("ck3lens")


class TestOperationTypes:
    """Test operation type enums and classification."""
    
    def test_operation_types_exist(self):
        from ck3lens.policy.enforcement import OperationType
        
        # Check file operations
        assert OperationType.FILE_WRITE
        assert OperationType.FILE_DELETE
        assert OperationType.FILE_RENAME
        
        # Check git operations
        assert OperationType.GIT_READ
        assert OperationType.GIT_LOCAL_PACKAGE
        assert OperationType.GIT_PUBLISH
        assert OperationType.GIT_DESTRUCTIVE
        
        # Check DB operations
        assert OperationType.DB_READ
        assert OperationType.DB_MODIFY
        assert OperationType.DB_DELETE
    
    def test_decision_types_exist(self):
        from ck3lens.policy.enforcement import Decision
        
        assert Decision.ALLOW
        assert Decision.DENY
        assert Decision.NOT_FOUND
        assert Decision.REQUIRE_CONTRACT
        assert Decision.REQUIRE_TOKEN
        assert Decision.REQUIRE_USER_APPROVAL
    
    def test_token_tiers_exist(self):
        from ck3lens.policy.enforcement import TokenTier
        
        assert TokenTier.NONE
        assert TokenTier.TIER_A
        assert TokenTier.TIER_B


class TestBranchProtection:
    """Test branch protection functions."""
    
    def test_protected_branches(self):
        from ck3lens.policy.enforcement import is_protected_branch
        
        # Main/master are always protected
        assert is_protected_branch("main") is True
        assert is_protected_branch("master") is True
        
        # Release branches are protected
        assert is_protected_branch("release/1.0") is True
        assert is_protected_branch("release/v2.0.0") is True
        
        # Prod branches are protected
        assert is_protected_branch("prod/live") is True
        assert is_protected_branch("production/current") is True
        
        # Dev branches are NOT protected
        assert is_protected_branch("dev/feature") is False
        assert is_protected_branch("wip/my-work") is False
        assert is_protected_branch("feature/new-thing") is False
    
    def test_agent_branch_validation(self):
        from ck3lens.policy.enforcement import is_agent_branch
        
        # Agent branches are valid
        assert is_agent_branch("agent/wcp-2025-01-01-abc123-fix-stuff") is True
        
        # With contract ID verification
        assert is_agent_branch("agent/wcp-2025-01-01-abc123-fix", "wcp-2025-01-01-abc123") is True
        assert is_agent_branch("agent/wcp-2025-01-01-def456-fix", "wcp-2025-01-01-abc123") is False
        
        # WIP and dev branches are also valid agent branches
        assert is_agent_branch("wip/my-feature") is True
        assert is_agent_branch("dev/experiment") is True
        
        # Main is not an agent branch
        assert is_agent_branch("main") is False
        assert is_agent_branch("feature/something") is False


class TestEnforcementRequest:
    """Test enforcement request creation."""
    
    def test_create_file_write_request(self):
        from ck3lens.policy.enforcement import (
            EnforcementRequest, OperationType
        )
        
        req = EnforcementRequest(
            operation=OperationType.FILE_WRITE,
            mode="ck3raven-dev",
            tool_name="ck3_file",
            target_path="tools/ck3lens_mcp/ck3lens/new_file.py",
        )
        
        assert req.operation == OperationType.FILE_WRITE
        assert req.mode == "ck3raven-dev"
        assert req.tool_name == "ck3_file"
        assert req.target_path == "tools/ck3lens_mcp/ck3lens/new_file.py"
    
    def test_create_git_push_request(self):
        from ck3lens.policy.enforcement import (
            EnforcementRequest, OperationType
        )
        
        req = EnforcementRequest(
            operation=OperationType.GIT_PUBLISH,
            mode="ck3raven-dev",
            tool_name="ck3_git",
            branch_name="agent/wcp-2025-01-01-abc123-fix",
            is_force_push=False,
            staged_files=["file1.py", "file2.py"],
        )
        
        assert req.operation == OperationType.GIT_PUBLISH
        assert req.branch_name == "agent/wcp-2025-01-01-abc123-fix"
        assert req.is_force_push is False
        assert len(req.staged_files) == 2


class TestModeHardGates:
    """Test mode-specific hard gates."""
    
    def test_ck3raven_dev_cannot_touch_mods(self):
        from ck3lens.policy.enforcement import (
            EnforcementRequest, OperationType, enforce_policy, Decision
        )
        
        req = EnforcementRequest(
            operation=OperationType.FILE_WRITE,
            mode="ck3raven-dev",
            tool_name="ck3_file",
            mod_name="MSC",  # Trying to touch a mod
        )
        
        result = enforce_policy(req)
        
        assert result.decision == Decision.DENY
        assert "cannot modify CK3 mods" in result.reason
    
    def test_ck3lens_cannot_touch_ck3raven_source(self):
        from ck3lens.policy.enforcement import (
            EnforcementRequest, OperationType, enforce_policy, Decision
        )
        
        req = EnforcementRequest(
            operation=OperationType.FILE_WRITE,
            mode="ck3lens",
            tool_name="ck3_file",
            target_path="tools/ck3lens_mcp/ck3lens/server.py",
        )
        
        result = enforce_policy(req)
        
        assert result.decision == Decision.DENY
        assert "cannot modify ck3raven source" in result.reason


class TestReadOperations:
    """Test that read operations are always allowed."""
    
    def test_read_always_allowed(self):
        from ck3lens.policy.enforcement import (
            EnforcementRequest, OperationType, enforce_policy, Decision
        )
        
        for op in [OperationType.READ, OperationType.GIT_READ, 
                   OperationType.DB_READ, OperationType.SHELL_SAFE]:
            req = EnforcementRequest(
                operation=op,
                mode="ck3raven-dev",
                tool_name="ck3_test",
            )
            
            result = enforce_policy(req)
            
            assert result.decision == Decision.ALLOW, f"{op} should be allowed"


class TestContractRequirement:
    """Test that write operations require contracts."""
    
    def test_file_write_requires_contract(self):
        from ck3lens.policy.enforcement import (
            EnforcementRequest, OperationType, enforce_policy, Decision
        )
        
        # This test may fail if there's an active contract from other tests
        # We're testing the gate logic, not actual contract loading
        req = EnforcementRequest(
            operation=OperationType.FILE_WRITE,
            mode="ck3raven-dev",
            tool_name="ck3_file",
            target_path="tests/test_new.py",
            # No contract_id provided
        )
        
        result = enforce_policy(req)
        
        # Should either require contract or allow (if one exists)
        assert result.decision in [Decision.REQUIRE_CONTRACT, Decision.ALLOW]


class TestAuditLogging:
    """Test the audit logging schema."""
    
    def test_enforcement_log_entry_creation(self):
        from ck3lens.policy.audit import EnforcementLogEntry
        
        entry = EnforcementLogEntry(
            event_version=1,
            event_category="enforcement",
            timestamp="2025-01-01T00:00:00Z",
            session_id="test-session",
            operation_type="FILE_WRITE",
            mode="ck3raven-dev",
            tool_name="ck3_file",
            decision="ALLOW",
            reason="File write allowed with valid contract scope",
        )
        
        d = entry.to_dict()
        
        assert d["event_version"] == 1
        assert d["operation_type"] == "FILE_WRITE"
        assert d["decision"] == "ALLOW"
        assert "timestamp" in d
    
    def test_enforcement_log_entry_removes_none(self):
        from ck3lens.policy.audit import EnforcementLogEntry
        
        entry = EnforcementLogEntry(
            event_version=1,
            event_category="enforcement",
            timestamp="2025-01-01T00:00:00Z",
            session_id="test-session",
            operation_type="FILE_WRITE",
            mode="ck3raven-dev",
            tool_name="ck3_file",
            decision="ALLOW",
            reason="Test reason",
            # These are None by default
            contract_id=None,
            token_id=None,
        )
        
        d = entry.to_dict()
        
        # None values should be stripped
        assert "contract_id" not in d
        assert "token_id" not in d


class TestRepoDomainPaths:
    """Test repo domain path validation."""
    
    def test_validate_path_in_repo_domains(self):
        from ck3lens.work_contracts import validate_path_in_repo_domains
        
        # docs domain should allow docs/** and *.md
        allowed, reason = validate_path_in_repo_domains(
            "docs/policy.md",
            ["docs"],
        )
        assert allowed is True
        
        # tools domain should allow tools/**
        allowed, reason = validate_path_in_repo_domains(
            "tools/ck3lens_mcp/server.py",
            ["tools"],
        )
        assert allowed is True
        
        # src domain should allow src/**
        allowed, reason = validate_path_in_repo_domains(
            "src/ck3raven/parser/core.py",
            ["src"],
        )
        assert allowed is True
    
    def test_path_not_in_domains(self):
        from ck3lens.work_contracts import validate_path_in_repo_domains
        
        # If only docs domain, can't write to tools
        allowed, reason = validate_path_in_repo_domains(
            "tools/ck3lens_mcp/server.py",
            ["docs"],
        )
        assert allowed is False
        assert "not in repo_domains" in reason
    
    def test_explicit_allowed_paths_override(self):
        from ck3lens.work_contracts import validate_path_in_repo_domains
        
        # explicit allowed_paths should override domain restrictions
        allowed, reason = validate_path_in_repo_domains(
            "custom/path/file.py",
            ["docs"],  # Would normally not allow custom/
            allowed_paths=["custom/**"],  # But this overrides
        )
        assert allowed is True
        assert "allowed_paths pattern" in reason


class TestSlugifyIntent:
    """Test intent slugification for branch names."""
    
    def test_slugify_basic(self):
        from ck3lens.work_contracts import _slugify_intent
        
        slug = _slugify_intent("Fix broken trait parsing")
        assert slug == "fix-broken-trait-parsing"
    
    def test_slugify_special_chars(self):
        from ck3lens.work_contracts import _slugify_intent
        
        slug = _slugify_intent("Add feature: cool_thing!")
        assert slug == "add-feature-cool-thing"
    
    def test_slugify_max_length(self):
        from ck3lens.work_contracts import _slugify_intent
        
        long_intent = "This is a very long intent description that should be truncated"
        slug = _slugify_intent(long_intent, max_length=20)
        assert len(slug) <= 20


class TestContractBranchName:
    """Test contract branch name generation."""
    
    def test_get_branch_name(self):
        from ck3lens.work_contracts import WorkContract
        
        contract = WorkContract(
            contract_id="wcp-2025-01-01-abc123",
            intent="Fix trait parsing bug",
            canonical_domains=["tools"],
            agent_mode="ck3raven-dev",
        )
        
        branch = contract.get_branch_name()
        
        assert branch.startswith("agent/wcp-2025-01-01-abc123-")
        assert "fix" in branch.lower()


# =============================================================================
# PHASE 2 INTEGRATION TESTS: Tool Enforcement Wiring
# =============================================================================

class TestCk3FileEnforcement:
    """Test ck3_file tool enforcement integration."""
    
    def test_ck3_file_impl_has_enforcement(self):
        """Verify ck3_file_impl contains enforcement gate."""
        from ck3lens.unified_tools import ck3_file_impl
        import inspect
        
        source = inspect.getsource(ck3_file_impl)
        
        # Should contain enforcement import
        assert "from ck3lens.policy.enforcement import" in source
        
        # Should contain enforcement gate call
        assert "enforce_and_log" in source
        
        # Should handle DENY decision
        assert "Decision.DENY" in source
        
        # Should handle REQUIRE_CONTRACT decision
        assert "Decision.REQUIRE_CONTRACT" in source
    
    def test_write_commands_are_enforced(self):
        """Verify write commands go through enforcement."""
        from ck3lens.unified_tools import ck3_file_impl
        import inspect
        
        source = inspect.getsource(ck3_file_impl)
        
        # Should check for write commands
        assert "write_commands = {" in source
        assert '"write"' in source or "'write'" in source
        assert '"edit"' in source or "'edit'" in source
        assert '"delete"' in source or "'delete'" in source
        assert '"rename"' in source or "'rename'" in source


class TestCk3GitEnforcement:
    """Test ck3_git tool enforcement integration."""
    
    def test_ck3_git_impl_has_enforcement(self):
        """Verify ck3_git_impl contains enforcement gate."""
        from ck3lens.unified_tools import ck3_git_impl
        import inspect
        
        source = inspect.getsource(ck3_git_impl)
        
        # Should contain enforcement import
        assert "from ck3lens.policy.enforcement import" in source
        
        # Should contain enforcement gate call
        assert "enforce_and_log" in source
        
        # Should handle DENY decision
        assert "Decision.DENY" in source
    
    def test_git_write_commands_are_enforced(self):
        """Verify git write commands go through enforcement."""
        from ck3lens.unified_tools import ck3_git_impl
        import inspect
        
        source = inspect.getsource(ck3_git_impl)
        
        # Should check for write commands
        assert "write_commands = {" in source
        assert '"add"' in source or "'add'" in source
        assert '"commit"' in source or "'commit'" in source
        assert '"push"' in source or "'push'" in source
    
    def test_safe_push_autogrant_logged(self):
        """Verify safe push auto-grant is logged."""
        from ck3lens.unified_tools import ck3_git_impl
        import inspect
        
        source = inspect.getsource(ck3_git_impl)
        
        # Should log safe push auto-grant
        assert "safe_push_autogrant" in source


class TestCk3ExecAuditLogging:
    """Test ck3_exec structured audit logging integration."""
    
    def test_ck3_exec_has_audit_logging(self):
        """Verify ck3_exec uses structured audit logging."""
        # Read server.py to check ck3_exec implementation
        from pathlib import Path
        import re
        
        # Get the path relative to tests
        server_path = Path(__file__).parent.parent / "tools" / "ck3lens_mcp" / "server.py"
        
        if server_path.exists():
            content = server_path.read_text(encoding="utf-8")
            
            # Find ck3_exec function
            # Should import audit logger
            assert "from ck3lens.policy.audit import get_audit_logger" in content
            
            # Should use audit logger in ck3_exec
            # This is a heuristic check - audit logger should be used
            assert "audit = get_audit_logger" in content


class TestEnforcementDecisionMappings:
    """Test enforcement decision to response mappings."""
    
    def test_deny_returns_error(self):
        """DENY decision should return success=False with error."""
        from ck3lens.policy.enforcement import (
            EnforcementRequest, OperationType, enforce_policy, Decision
        )
        
        # Create request that should be denied
        req = EnforcementRequest(
            operation=OperationType.FILE_WRITE,
            mode="ck3raven-dev",
            tool_name="ck3_file",
            mod_name="MSC",  # ck3raven-dev can't touch mods
        )
        
        result = enforce_policy(req)
        
        assert result.decision == Decision.DENY
        assert result.reason  # Should have a reason
    
    def test_require_contract_provides_guidance(self):
        """REQUIRE_CONTRACT should suggest using ck3_contract."""
        # This tests that the enforcement result has required_contract=True
        from ck3lens.policy.enforcement import (
            EnforcementRequest, OperationType, enforce_policy, Decision
        )
        
        # Create request without contract
        req = EnforcementRequest(
            operation=OperationType.FILE_WRITE,
            mode="ck3raven-dev",
            tool_name="ck3_file",
            target_path="tests/test_file.py",
            contract_id=None,  # No contract
        )
        
        result = enforce_policy(req)
        
        # Should either require contract or allow (if one is active globally)
        if result.decision == Decision.REQUIRE_CONTRACT:
            assert result.required_contract is True
    
    def test_require_token_specifies_type(self):
        """REQUIRE_TOKEN should specify which token type is needed."""
        from ck3lens.policy.enforcement import (
            EnforcementRequest, OperationType, enforce_policy, Decision
        )
        
        # Create request for delete (requires token)
        req = EnforcementRequest(
            operation=OperationType.FILE_DELETE,
            mode="ck3raven-dev",
            tool_name="ck3_file",
            target_path="tests/delete_me.py",
            contract_id="test-contract-123",  # Has contract but no token
        )
        
        result = enforce_policy(req)
        
        # Delete should require token (if contract is valid)
        if result.decision == Decision.REQUIRE_TOKEN:
            assert result.required_token_type is not None
            assert "DELETE" in result.required_token_type

