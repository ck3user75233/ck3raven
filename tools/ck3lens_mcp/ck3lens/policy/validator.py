"""
Policy Validator

Core validation orchestrator that applies global and agent-specific rules.
"""
from __future__ import annotations
from typing import Any, TYPE_CHECKING

from .types import Severity, AgentMode, Violation, ToolCall, ValidationContext, PolicyOutcome
from .loader import get_policy, get_agent_policy
from .trace_helpers import trace_has_call
from .ck3lens_rules import validate_ck3lens_rules
from .ck3raven_dev_rules import validate_ck3raven_dev_rules

if TYPE_CHECKING:
    from ..contracts import ArtifactBundle


def validate_policy(
    ctx: ValidationContext,
    artifact_bundle: "ArtifactBundle | None" = None,
    attempting_delivery: bool = True,
) -> PolicyOutcome:
    """
    Validate agent behavior against the policy specification.
    
    This is the main entry point for policy validation. It:
    1. Checks global rules (tool trace required, no silent assumptions)
    2. Applies mode-specific rules (ck3lens or ck3raven-dev)
    3. Returns a PolicyOutcome indicating deliverability
    
    Args:
        ctx: Validation context with mode, policy, trace, and session info
        artifact_bundle: Optional ArtifactBundle being delivered
        attempting_delivery: If True, this is a delivery gate check
    
    Returns:
        PolicyOutcome with deliverable status, violations, and summary
    """
    violations: list[Violation] = []
    summary: dict[str, Any] = {"mode": ctx.mode.value}
    
    # 1) Validate mode is known
    agent_policy = get_agent_policy(ctx.mode.value)
    if not agent_policy:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="POLICY_MODE_UNKNOWN",
            message=f"No policy block found for agent mode: {ctx.mode.value}",
            details={"mode": ctx.mode.value},
        ))
        return PolicyOutcome(
            deliverable=False,
            violations=violations,
            summary=summary,
        )
    
    # 2) Global rules: tool trace required
    if attempting_delivery:
        _validate_global_trace_required(ctx, violations, summary)
    
    # 3) Mode-specific validation
    if ctx.mode == AgentMode.CK3LENS:
        validate_ck3lens_rules(ctx, artifact_bundle, violations, summary)
    elif ctx.mode == AgentMode.CK3RAVEN_DEV:
        validate_ck3raven_dev_rules(ctx, artifact_bundle, violations, summary)
    
    # 4) Compute deliverability
    error_count = sum(1 for v in violations if v.severity == Severity.ERROR)
    warning_count = sum(1 for v in violations if v.severity == Severity.WARNING)
    
    deliverable = attempting_delivery and error_count == 0
    
    summary["deliverable"] = deliverable
    summary["violations_error_count"] = error_count
    summary["violations_warning_count"] = warning_count
    summary["attempting_delivery"] = attempting_delivery
    
    return PolicyOutcome(
        deliverable=deliverable,
        violations=violations,
        summary=summary,
    )


def server_delivery_gate(
    ctx: ValidationContext,
    artifact_bundle: "ArtifactBundle",
) -> dict[str, Any]:
    """
    Server-side delivery gate wrapper.
    
    Call this whenever the agent wants to 'deliver' an artifact bundle.
    Returns a dict suitable for MCP tool response.
    
    Args:
        ctx: Validation context
        artifact_bundle: The ArtifactBundle being delivered
    
    Returns:
        Dict with status, deliverable, violations, and summary
    """
    outcome = validate_policy(ctx, artifact_bundle=artifact_bundle, attempting_delivery=True)
    
    if not outcome.deliverable:
        return {
            "status": "blocked",
            "deliverable": False,
            "violations": [v.to_dict() for v in outcome.violations],
            "summary": outcome.summary,
            "message": f"Delivery blocked: {outcome.error_count} error(s), {outcome.warning_count} warning(s)",
        }
    
    return {
        "status": "deliverable",
        "deliverable": True,
        "violations": [v.to_dict() for v in outcome.violations],
        "summary": outcome.summary,
        "message": f"Delivery approved with {outcome.warning_count} warning(s)",
    }


def validate_for_mode(
    mode: str,
    trace: list[dict[str, Any]] | None = None,
    artifact_bundle_dict: dict[str, Any] | None = None,
    session_scope: dict[str, Any] | None = None,
    playset_id: int | None = None,
    vanilla_version_id: str | None = None,
) -> dict[str, Any]:
    """
    Convenience function to validate from raw inputs.
    
    This is useful for MCP tool integration where inputs are dicts.
    
    Args:
        mode: Agent mode name ("ck3lens" or "ck3raven-dev")
        trace: List of trace event dicts
        artifact_bundle_dict: ArtifactBundle as dict
        session_scope: Complete scope from _get_session_scope() (preferred)
        playset_id: Active playset ID (deprecated, use session_scope)
        vanilla_version_id: Selected vanilla version (deprecated, use session_scope)
    
    Returns:
        Validation result dict
    """
    # Load policy
    policy = get_policy()
    
    # Convert trace events to ToolCall objects
    tool_trace = []
    if trace:
        for event in trace:
            tool_trace.append(ToolCall.from_trace_event(event))
    
    # Create context and populate scope
    ctx = ValidationContext.for_mode(mode, policy, tool_trace)
    
    if session_scope:
        # Preferred: auto-populate all scope fields from session
        ctx.with_session_scope(session_scope)
    else:
        # Deprecated: manual field setting (backward compat)
        ctx.playset_id = playset_id
        ctx.vanilla_version_id = vanilla_version_id
    
    # Convert artifact_bundle if provided
    artifact_bundle = None
    if artifact_bundle_dict:
        try:
            from ..contracts import ArtifactBundle
            artifact_bundle = ArtifactBundle.model_validate(artifact_bundle_dict)
        except Exception as e:
            return {
                "status": "error",
                "deliverable": False,
                "violations": [{
                    "severity": "error",
                    "code": "ARTIFACT_BUNDLE_INVALID",
                    "message": f"Failed to parse ArtifactBundle: {e}",
                    "details": {},
                }],
                "summary": {"mode": mode},
            }
    
    # Run validation
    outcome = validate_policy(ctx, artifact_bundle=artifact_bundle, attempting_delivery=True)
    
    return {
        "status": "deliverable" if outcome.deliverable else "blocked",
        "deliverable": outcome.deliverable,
        "violations": [v.to_dict() for v in outcome.violations],
        "summary": outcome.summary,
    }


# -----------------------------
# Global Rule Validators
# -----------------------------

def _validate_global_trace_required(
    ctx: ValidationContext,
    violations: list[Violation],
    summary: dict[str, Any],
) -> None:
    """
    Validate: tool trace required for deliverable output.
    
    Global rule: tool_trace_required
    """
    if not ctx.trace or len(ctx.trace) == 0:
        violations.append(Violation(
            severity=Severity.ERROR,
            code="TRACE_REQUIRED",
            message="Tool trace required for deliverable output. No MCP tool calls recorded.",
            details={"mode": ctx.mode.value},
        ))
    
    summary["trace_event_count"] = len(ctx.trace) if ctx.trace else 0
