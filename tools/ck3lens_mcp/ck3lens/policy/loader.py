"""
Policy Loader

Loads and caches the agent policy YAML specification.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional
import yaml

# Path to the policy file
POLICY_FILE = Path(__file__).parent / "agent_policy.yaml"

# Cached policy
_policy_cache: Optional[dict[str, Any]] = None


def load_policy(policy_path: Path | str | None = None) -> dict[str, Any]:
    """
    Load the agent policy from YAML.
    
    Args:
        policy_path: Optional path to policy file. Defaults to agent_policy.yaml.
    
    Returns:
        Parsed policy dictionary.
    
    Raises:
        FileNotFoundError: If policy file doesn't exist.
        yaml.YAMLError: If policy file is invalid YAML.
    """
    path = Path(policy_path) if policy_path else POLICY_FILE
    
    if not path.exists():
        raise FileNotFoundError(f"Policy file not found: {path}")
    
    with path.open("r", encoding="utf-8") as f:
        policy = yaml.safe_load(f)
    
    if not isinstance(policy, dict):
        raise ValueError(f"Policy must be a YAML mapping, got {type(policy)}")
    
    return policy


def get_policy() -> dict[str, Any]:
    """
    Get the cached policy, loading it if needed.
    
    Returns:
        The parsed policy dictionary.
    """
    global _policy_cache
    
    if _policy_cache is None:
        _policy_cache = load_policy()
    
    return _policy_cache


def reload_policy() -> dict[str, Any]:
    """
    Force reload the policy from disk.
    
    Returns:
        The freshly parsed policy dictionary.
    """
    global _policy_cache
    _policy_cache = load_policy()
    return _policy_cache


def get_agent_policy(mode: str) -> dict[str, Any]:
    """
    Get the policy block for a specific agent mode.
    
    Args:
        mode: Agent mode name (e.g., "ck3lens", "ck3raven-dev")
    
    Returns:
        The agent-specific policy block, or empty dict if not found.
    """
    policy = get_policy()
    agents = policy.get("agents", {})
    return agents.get(mode, {})


def get_global_rules() -> dict[str, Any]:
    """
    Get global rules that apply to all agents.
    
    Returns:
        The global_rules block from policy.
    """
    policy = get_policy()
    return policy.get("global_rules", {})


def get_validation_domains() -> dict[str, Any]:
    """
    Get validation domain configurations.
    
    Returns:
        The validation_domains block from policy.
    """
    policy = get_policy()
    return policy.get("validation_domains", {})


def is_rule_applicable(mode: str, rule_name: str) -> bool:
    """
    Check if a rule is applicable to an agent mode.
    
    Args:
        mode: Agent mode name
        rule_name: Name of the rule to check
    
    Returns:
        True if the rule applies to this mode.
    """
    # Check global rules first
    global_rules = get_global_rules()
    if rule_name in global_rules:
        applies_to = global_rules[rule_name].get("applies_to", [])
        return mode in applies_to
    
    # Check agent-specific rules
    agent_policy = get_agent_policy(mode)
    rules = agent_policy.get("rules", {})
    return rule_name in rules
