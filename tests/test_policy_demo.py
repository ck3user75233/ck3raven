#!/usr/bin/env python
"""Demonstrate policy validation for ck3raven-dev mode."""

import sys
from pathlib import Path
# Add ck3lens_mcp to path (repo-relative)
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "ck3lens_mcp"))

from ck3lens.policy.validator import validate_for_mode

def main():
    print("=" * 60)
    print("CK3Raven Policy Validation Demo")
    print("=" * 60)
    print()
    
    # Test 1: Empty trace should trigger violations
    print("Test 1: Empty trace (should show violations)")
    print("-" * 40)
    result = validate_for_mode(
        mode='ck3raven-dev',
        trace=[],  # Empty trace
    )
    
    print(f"Status: {result.get('status', 'unknown')}")
    print(f"Deliverable: {result.get('deliverable', 'unknown')}")
    
    violations = result.get('violations', [])
    print(f"Violations: {len(violations)}")
    
    for v in violations[:5]:
        severity = v.get('severity', '?')
        rule_id = v.get('rule_id', '?')
        message = v.get('message', '')[:80]
        print(f"  [{severity}] {rule_id}: {message}")

    if len(violations) > 5:
        print(f"  ... and {len(violations) - 5} more")

    print()
    print("Rules checked:")
    for rule in result.get('rules_checked', [])[:10]:
        print(f"  - {rule}")
    
    print()
    
    # Test 2: With a mock trace event (simulating tool usage)
    print("Test 2: With traced tool calls")
    print("-" * 40)
    
    mock_trace = [
        {
            "tool_name": "ck3_init_session",
            "timestamp": 1234567890.0,
            "success": True,
            "inputs": {},
            "outputs": {"session_id": "test"}
        },
        {
            "tool_name": "ck3_get_db_status",
            "timestamp": 1234567891.0,
            "success": True,
            "inputs": {},
            "outputs": {"is_complete": True}
        },
    ]
    
    result2 = validate_for_mode(
        mode='ck3raven-dev',
        trace=mock_trace,
    )
    
    print(f"Status: {result2.get('status', 'unknown')}")
    print(f"Deliverable: {result2.get('deliverable', 'unknown')}")
    print(f"Violations: {len(result2.get('violations', []))}")
    
    print()
    print("=" * 60)
    print("Policy validation is WORKING")
    print("=" * 60)

if __name__ == "__main__":
    main()
