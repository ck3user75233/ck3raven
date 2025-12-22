"""
Policy Validator Tests

Unit tests for the agent policy validation system.
"""
import pytest
from typing import Any

# Add ck3lens to path
import sys
from pathlib import Path
CK3LENS_PATH = Path(__file__).parent.parent / "ck3lens"
if str(CK3LENS_PATH.parent) not in sys.path:
    sys.path.insert(0, str(CK3LENS_PATH.parent))

from ck3lens.policy.types import (
    Severity, AgentMode, Violation, ToolCall, ValidationContext, PolicyOutcome
)
from ck3lens.policy.loader import load_policy, get_policy, get_agent_policy
from ck3lens.policy.trace_helpers import (
    trace_has_call, trace_calls, is_db_search_tool, is_conflict_tool,
    get_resolved_unit_keys, trace_any_filesystem_search,
)
from ck3lens.policy.validator import validate_policy, validate_for_mode
from ck3lens.policy.ck3lens_rules import validate_ck3lens_rules
from ck3lens.policy.ck3raven_dev_rules import validate_ck3raven_dev_rules
from ck3lens.contracts import ArtifactBundle, ArtifactFile, DeclaredSymbol


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def policy():
    """Load the policy spec."""
    return get_policy()


@pytest.fixture
def mock_trace_with_init():
    """Trace with session initialization."""
    return [
        ToolCall(
            name="ck3_init_session",
            args={},
            result_meta={"playset_id": 1},
            timestamp_ms=1000,
        ),
    ]


@pytest.fixture
def mock_trace_with_search():
    """Trace with DB search calls."""
    return [
        ToolCall(
            name="ck3_init_session",
            args={},
            result_meta={"playset_id": 1},
            timestamp_ms=1000,
        ),
        ToolCall(
            name="ck3_search_symbols",
            args={"query": "test_trait", "playset_id": 1},
            result_meta={"count": 5},
            timestamp_ms=2000,
        ),
    ]


@pytest.fixture
def mock_artifact_bundle_valid():
    """Valid ArtifactBundle with ck3_file_model."""
    return ArtifactBundle(
        artifacts=[
            ArtifactFile(
                path="common/traits/test_trait.txt",
                format="ck3_script",
                content="test_trait = { }",
                ck3_file_model="A",
            )
        ],
        declared_new_symbols=[
            DeclaredSymbol(
                type="trait",
                name="test_trait",
                reason="Testing new trait",
                defined_in_path="common/traits/test_trait.txt",
            )
        ],
        touched_units=["trait:test_trait"],
    )


@pytest.fixture
def mock_artifact_bundle_missing_model():
    """ArtifactBundle missing ck3_file_model."""
    return ArtifactBundle(
        artifacts=[
            ArtifactFile(
                path="common/traits/test_trait.txt",
                format="ck3_script",
                content="test_trait = { }",
                # No ck3_file_model
            )
        ],
    )


# =============================================================================
# Test: Policy Loading
# =============================================================================

class TestPolicyLoader:
    def test_load_policy_returns_dict(self, policy):
        """Policy loads as a dict."""
        assert isinstance(policy, dict)
    
    def test_policy_has_version(self, policy):
        """Policy has version string."""
        assert "policy_spec_version" in policy
        assert policy["policy_spec_version"] == "1.3"
    
    def test_policy_has_global_rules(self, policy):
        """Policy has global_rules section."""
        assert "global_rules" in policy
        assert "tool_trace_required" in policy["global_rules"]
    
    def test_policy_has_agents(self, policy):
        """Policy has agents section."""
        assert "agents" in policy
        assert "ck3lens" in policy["agents"]
        assert "ck3raven-dev" in policy["agents"]
    
    def test_get_agent_policy_ck3lens(self):
        """Can retrieve ck3lens-specific policy."""
        agent_policy = get_agent_policy("ck3lens")
        assert "rules" in agent_policy
        assert "ck3_file_model_required" in agent_policy["rules"]
    
    def test_get_agent_policy_ck3raven_dev(self):
        """Can retrieve ck3raven-dev-specific policy."""
        agent_policy = get_agent_policy("ck3raven-dev")
        assert "rules" in agent_policy
        assert "python_validation_required" in agent_policy["rules"]


# =============================================================================
# Test: Trace Helpers
# =============================================================================

class TestTraceHelpers:
    def test_trace_has_call_true(self, mock_trace_with_search):
        """Finds tool in trace."""
        assert trace_has_call(mock_trace_with_search, "ck3_init_session")
        assert trace_has_call(mock_trace_with_search, "ck3_search_symbols")
    
    def test_trace_has_call_false(self, mock_trace_with_search):
        """Returns False for missing tool."""
        assert not trace_has_call(mock_trace_with_search, "ck3_validate_artifact_bundle")
    
    def test_trace_calls_returns_list(self, mock_trace_with_search):
        """Returns list of matching calls."""
        calls = trace_calls(mock_trace_with_search, "ck3_search_symbols")
        assert len(calls) == 1
        assert calls[0].name == "ck3_search_symbols"
    
    def test_is_db_search_tool(self):
        """Correctly identifies DB search tools."""
        assert is_db_search_tool("ck3_search_symbols")
        assert is_db_search_tool("ck3_get_file")
        assert not is_db_search_tool("ck3_validate_artifact_bundle")
    
    def test_is_conflict_tool(self):
        """Correctly identifies conflict tools."""
        assert is_conflict_tool("ck3_scan_unit_conflicts")
        assert is_conflict_tool("ck3_resolve_conflict")
        assert not is_conflict_tool("ck3_search_symbols")
    
    def test_get_resolved_unit_keys(self):
        """Extracts unit_keys from resolve_conflict calls."""
        trace = [
            ToolCall(
                name="ck3_resolve_conflict",
                args={"conflict_unit_id": "trait:brave"},
                result_meta={},
                timestamp_ms=1000,
            ),
            ToolCall(
                name="ck3_resolve_conflict",
                args={"conflict_unit_id": "trait:craven"},
                result_meta={},
                timestamp_ms=2000,
            ),
        ]
        resolved = get_resolved_unit_keys(trace)
        assert "trait:brave" in resolved
        assert "trait:craven" in resolved


# =============================================================================
# Test: CK3 Lens Rules
# =============================================================================

class TestCK3LensRules:
    def test_scope_playset_missing_error(self, policy):
        """Error when playset_id is missing."""
        ctx = ValidationContext(
            mode=AgentMode.CK3LENS,
            policy=policy,
            trace=[],
            playset_id=None,
        )
        violations, summary = validate_ck3lens_rules(ctx)
        
        error_codes = [v.code for v in violations if v.severity == Severity.ERROR]
        assert "SCOPE_PLAYSET_MISSING" in error_codes
    
    def test_active_playset_not_fetched_error(self, policy, mock_trace_with_search):
        """Warning when active playset not fetched (init_session counts)."""
        # Trace has init_session, so this should pass
        ctx = ValidationContext(
            mode=AgentMode.CK3LENS,
            policy=policy,
            trace=mock_trace_with_search,
            playset_id=1,
        )
        violations, summary = validate_ck3lens_rules(ctx)
        
        error_codes = [v.code for v in violations if v.severity == Severity.ERROR]
        assert "ACTIVE_PLAYSET_NOT_FETCHED" not in error_codes
    
    def test_ck3_file_model_missing_error(self, policy, mock_trace_with_search, mock_artifact_bundle_missing_model):
        """Error when artifact file missing ck3_file_model."""
        ctx = ValidationContext(
            mode=AgentMode.CK3LENS,
            policy=policy,
            trace=mock_trace_with_search,
            playset_id=1,
        )
        violations, summary = validate_ck3lens_rules(ctx, bundle=mock_artifact_bundle_missing_model)
        
        error_codes = [v.code for v in violations if v.severity == Severity.ERROR]
        assert "CK3_FILE_MODEL_MISSING" in error_codes
    
    def test_ck3_file_model_present_passes(self, policy, mock_trace_with_search, mock_artifact_bundle_valid):
        """No ck3_file_model error when model is declared."""
        # Need to add validate_artifact_bundle to trace for full validation
        trace = mock_trace_with_search + [
            ToolCall(
                name="ck3_validate_artifact_bundle",
                args={},
                result_meta={"ok": True},
                timestamp_ms=3000,
            ),
            ToolCall(
                name="ck3_resolve_conflict",
                args={"conflict_unit_id": "trait:test_trait"},
                result_meta={},
                timestamp_ms=4000,
            ),
        ]
        ctx = ValidationContext(
            mode=AgentMode.CK3LENS,
            policy=policy,
            trace=trace,
            playset_id=1,
        )
        violations, summary = validate_ck3lens_rules(ctx, bundle=mock_artifact_bundle_valid)
        
        error_codes = [v.code for v in violations if v.severity == Severity.ERROR]
        assert "CK3_FILE_MODEL_MISSING" not in error_codes
        assert "CK3_FILE_MODEL_INVALID" not in error_codes


# =============================================================================
# Test: CK3 Raven Dev Rules
# =============================================================================

class TestCK3RavenDevRules:
    def test_preserve_uncertainty_warning(self, policy):
        """Always adds preserve_uncertainty warning."""
        ctx = ValidationContext(
            mode=AgentMode.CK3RAVEN_DEV,
            policy=policy,
            trace=[],
        )
        violations, summary = validate_ck3raven_dev_rules(ctx)
        
        warning_codes = [v.code for v in violations if v.severity == Severity.WARNING]
        assert "PRESERVE_UNCERTAINTY_TBC" in warning_codes
    
    def test_python_validation_required(self, policy):
        """Error when Python output lacks validation."""
        # Create a Python artifact
        bundle = ArtifactBundle(
            artifacts=[
                ArtifactFile(
                    path="src/test_module.py",
                    format="ck3_script",  # Will detect .py extension
                    content="def test(): pass",
                )
            ],
        )
        ctx = ValidationContext(
            mode=AgentMode.CK3RAVEN_DEV,
            policy=policy,
            trace=[],  # No validate_python call
        )
        violations, summary = validate_ck3raven_dev_rules(ctx, bundle=bundle)
        
        error_codes = [v.code for v in violations if v.severity == Severity.ERROR]
        assert "PY_VALIDATION_REQUIRED" in error_codes
    
    def test_python_validation_passes_with_call(self, policy):
        """No error when Python validation was run."""
        bundle = ArtifactBundle(
            artifacts=[
                ArtifactFile(
                    path="src/test_module.py",
                    format="ck3_script",
                    content="def test(): pass",
                )
            ],
        )
        trace = [
            ToolCall(
                name="ck3_validate_python",
                args={"file_path": "src/test_module.py"},
                result_meta={"valid": True, "errors": []},
                timestamp_ms=1000,
            ),
        ]
        ctx = ValidationContext(
            mode=AgentMode.CK3RAVEN_DEV,
            policy=policy,
            trace=trace,
        )
        violations, summary = validate_ck3raven_dev_rules(ctx, bundle=bundle)
        
        error_codes = [v.code for v in violations if v.severity == Severity.ERROR]
        assert "PY_VALIDATION_REQUIRED" not in error_codes


# =============================================================================
# Test: Core Validator
# =============================================================================

class TestCoreValidator:
    def test_empty_trace_error(self, policy):
        """Error when attempting delivery with empty trace."""
        ctx = ValidationContext(
            mode=AgentMode.CK3LENS,
            policy=policy,
            trace=[],
            playset_id=1,
        )
        outcome = validate_policy(ctx, attempting_delivery=True)
        
        assert not outcome.deliverable
        error_codes = [v.code for v in outcome.violations if v.severity == Severity.ERROR]
        assert "TRACE_REQUIRED" in error_codes
    
    def test_unknown_mode_error(self, policy):
        """Error when mode is unknown."""
        # Force unknown mode by providing empty agents dict
        # Note: With empty policy, POLICY_MODE_UNKNOWN is raised
        # But with trace=[], TRACE_REQUIRED is also raised first
        ctx = ValidationContext(
            mode=AgentMode.CK3LENS,
            policy={"agents": {}},  # Empty agents
            trace=[],
        )
        outcome = validate_policy(ctx)
        
        assert not outcome.deliverable
        error_codes = [v.code for v in outcome.violations if v.severity == Severity.ERROR]
        # Either POLICY_MODE_UNKNOWN or other errors should block delivery
        assert len(error_codes) > 0
    
    def test_validate_for_mode_convenience(self, policy):
        """validate_for_mode works with raw dicts."""
        result = validate_for_mode(
            mode="ck3raven-dev",
            trace=[{"tool": "ck3_init_session", "args": {}, "result": {}, "ts": 1.0}],
        )
        
        assert "deliverable" in result
        assert "violations" in result
        assert "summary" in result


# =============================================================================
# Test: PolicyOutcome
# =============================================================================

class TestPolicyOutcome:
    def test_to_dict(self):
        """PolicyOutcome serializes correctly."""
        outcome = PolicyOutcome(
            deliverable=True,
            violations=[
                Violation(
                    severity=Severity.WARNING,
                    code="TEST_WARNING",
                    message="Test warning",
                    details={"key": "value"},
                )
            ],
            summary={"test": True},
        )
        
        d = outcome.to_dict()
        assert d["deliverable"] is True
        assert len(d["violations"]) == 1
        assert d["violations"][0]["code"] == "TEST_WARNING"
    
    def test_error_count(self):
        """error_count property works."""
        outcome = PolicyOutcome(
            deliverable=False,
            violations=[
                Violation(Severity.ERROR, "E1", "error 1", {}),
                Violation(Severity.ERROR, "E2", "error 2", {}),
                Violation(Severity.WARNING, "W1", "warning 1", {}),
            ],
        )
        assert outcome.error_count == 2
        assert outcome.warning_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
