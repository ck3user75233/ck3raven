#!/usr/bin/env python3
"""
Pre-Commit Policy Validation Hook

This script validates agent behavior before allowing a git commit.
It reads the trace log and runs policy validation to ensure all
rules were followed during the session.

Install:
    Copy or symlink to .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit  (Unix)

Exit codes:
    0 = Validation passed, commit allowed
    1 = Validation failed, commit blocked
"""
from __future__ import annotations
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

# Configure stdout for UTF-8 on Windows (fixes emoji encoding errors)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Determine mode from environment or default
MODE = os.environ.get("CK3LENS_MODE", "ck3raven-dev")

# Add ck3raven to path (must be before trace file)
SCRIPT_DIR = Path(__file__).parent
CK3RAVEN_ROOT = SCRIPT_DIR.parent
MCP_ROOT = CK3RAVEN_ROOT / "tools" / "ck3lens_mcp"
SRC_ROOT = CK3RAVEN_ROOT / "src"

# Trace file location (mode-aware)
def _get_trace_file() -> Path:
    """Get trace file path based on mode."""
    if MODE == "ck3raven-dev":
        # Dev mode: traces in repo .wip directory
        return CK3RAVEN_ROOT / ".wip" / "traces" / "ck3lens_trace.jsonl"
    else:
        # Lens mode: traces in ~/.ck3raven
        return Path.home() / ".ck3raven" / "traces" / "ck3lens_trace.jsonl"

TRACE_FILE = _get_trace_file()

sys.path.insert(0, str(MCP_ROOT))
sys.path.insert(0, str(SRC_ROOT))


def read_trace(max_events: int = 200) -> list[dict[str, Any]]:
    """Read recent trace events from the trace file."""
    if not TRACE_FILE.exists():
        return []
    
    events = []
    with TRACE_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    
    # Return most recent events
    return events[-max_events:]


def validate_session(mode: str, trace_events: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Run policy validation on the trace events.
    
    This is a PURE function - no side effects, deterministic output.
    """
    from ck3lens.policy import validate_for_mode
    
    return validate_for_mode(
        mode=mode,
        trace=trace_events,
        artifact_bundle_dict=None,
        session_scope=None,
    )


def main() -> int:
    """
    Pre-commit validation entry point.
    
    Returns:
        0 if validation passed
        1 if validation failed
    """
    print(f"[POLICY] Validation ({MODE} mode)...")
    
    # Read trace
    trace_events = read_trace()
    if not trace_events:
        print("[WARN] No trace events found. Skipping validation.")
        print("   (If you're not using MCP tools, this is expected)")
        return 0
    
    print(f"   Found {len(trace_events)} trace events")
    
    # Run validation
    try:
        result = validate_session(MODE, trace_events)
    except ImportError as e:
        print(f"[ERROR] Failed to import policy module: {e}")
        print("   Run from ck3raven virtualenv or install dependencies")
        return 1
    except Exception as e:
        print(f"[ERROR] Validation error: {e}")
        return 1
    
    # Check result
    deliverable = result.get("deliverable", False)
    violations = result.get("violations", [])
    summary = result.get("summary", {})
    
    error_count = summary.get("violations_error_count", 0)
    warning_count = summary.get("violations_warning_count", 0)
    
    if deliverable:
        if warning_count > 0:
            print(f"[OK] Validation passed with {warning_count} warning(s)")
            for v in violations:
                if v.get("severity") == "warning":
                    print(f"   [WARN] {v.get('code')}: {v.get('message')}")
        else:
            print("[OK] Validation passed")
        return 0
    else:
        print(f"[FAIL] Validation FAILED: {error_count} error(s), {warning_count} warning(s)")
        print()
        for v in violations:
            severity = v.get("severity", "error")
            tag = "[ERR]" if severity == "error" else "[WARN]"
            print(f"   {tag} [{v.get('code')}] {v.get('message')}")
        print()
        print("Commit blocked. Fix violations and try again.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
