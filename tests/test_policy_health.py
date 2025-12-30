#!/usr/bin/env python
"""Test policy health check and import."""

import sys
from pathlib import Path
# Add ck3lens_mcp to path (repo-relative)
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "ck3lens_mcp"))

import importlib
from ck3lens import policy

# Force reload
importlib.reload(policy)

# Check what's available
print("Policy module exports:")
for name in dir(policy):
    if not name.startswith('_'):
        print(f"  - {name}")

# Test validate_for_mode exists
print()
if hasattr(policy, 'validate_for_mode'):
    print("✅ validate_for_mode is exported")
    
    # Test it
    result = policy.validate_for_mode(mode='ck3raven-dev', trace=[])
    print(f"  Status: {result.get('status')}")
    print(f"  Deliverable: {result.get('deliverable')}")
    print()
    print("✅ Policy health check PASSED")
else:
    print("❌ validate_for_mode NOT exported - BROKEN!")
    sys.exit(1)
