"""
CK3 Lens MCP Server Launcher

This launcher script enables multiple independent MCP server instances.
Each VS Code window gets its own server instance with isolated state.

Usage:
    python launcher.py                     # Auto-generates instance ID
    python launcher.py --instance-id abc   # Uses specific instance ID
    python launcher.py --list              # Lists running instances
    python launcher.py --cleanup           # Remove stale instances
"""
import sys
import os
import uuid
import argparse
from pathlib import Path
import json
import tempfile

# Instance tracking file
INSTANCES_FILE = Path(tempfile.gettempdir()) / "ck3lens_instances.json"


def is_pid_running(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if process:
            kernel32.CloseHandle(process)
            return True
        return False
    else:
        # Unix-like systems
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def get_running_instances() -> dict:
    """Load the running instances registry."""
    if INSTANCES_FILE.exists():
        try:
            return json.loads(INSTANCES_FILE.read_text())
        except Exception:
            return {}
    return {}


def cleanup_stale_instances() -> int:
    """Remove instances where the PID is no longer running. Returns count removed."""
    instances = get_running_instances()
    if not instances:
        return 0
    
    stale = []
    for iid, info in instances.items():
        pid = info.get("pid")
        if pid and not is_pid_running(pid):
            stale.append(iid)
    
    if stale:
        for iid in stale:
            del instances[iid]
        INSTANCES_FILE.write_text(json.dumps(instances, indent=2))
    
    return len(stale)


def register_instance(instance_id: str, pid: int) -> None:
    """Register a new instance."""
    # First cleanup stale instances
    cleanup_stale_instances()
    
    instances = get_running_instances()
    instances[instance_id] = {
        "pid": pid,
        "started_at": __import__("datetime").datetime.now().isoformat(),
    }
    INSTANCES_FILE.write_text(json.dumps(instances, indent=2))


def unregister_instance(instance_id: str) -> None:
    """Remove an instance from registry."""
    instances = get_running_instances()
    if instance_id in instances:
        del instances[instance_id]
        INSTANCES_FILE.write_text(json.dumps(instances, indent=2))


def list_instances() -> None:
    """Print all registered instances with live status."""
    # Cleanup first
    removed = cleanup_stale_instances()
    if removed:
        print(f"Cleaned up {removed} stale instance(s).")
    
    instances = get_running_instances()
    if not instances:
        print("No running instances found.")
        return

    print(f"Running CK3 Lens instances ({len(instances)}):")
    for iid, info in instances.items():
        pid = info.get('pid')
        status = "RUNNING" if is_pid_running(pid) else "STALE"
        print(f"  {iid}: PID {pid} [{status}] started {info.get('started_at', 'unknown')}")


def main():
    parser = argparse.ArgumentParser(
        description="""CK3 Lens MCP Server Launcher

CK3 Lens is the MCP (Model Context Protocol) server for ck3raven that provides
AI agents with safe, structured access to CK3 mod content.

UNIFIED POWER TOOLS (NEW):
  ck3_logs       - All log operations (errors, crashes, game.log)
  ck3_conflicts  - All conflict operations (scan, list, resolve)
  ck3_contract   - Work contract management (CLW)
  ck3_exec       - Policy-enforced command execution
  ck3_token      - Approval token management

CLI WRAPPING LAYER (CLW):
  Safe commands (cat, git status)     → ALLOW automatically
  Risky commands (rm *.py, git push)  → REQUIRE_CONTRACT
  Blocked commands (rm -rf /)         → DENY always

USAGE:
  Start server:     python -m tools.ck3lens_mcp.launcher
  List instances:   python -m tools.ck3lens_mcp.launcher --list
  Clean up stale:   python -m tools.ck3lens_mcp.launcher --cleanup

DOCUMENTATION:
  Full tool reference: tools/ck3lens_mcp/docs/TOOLS.md
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--instance-id", "-i",
        help="Unique instance identifier. Auto-generated if not provided.",
        default=None,
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List running instances and exit.",
    )
    parser.add_argument(
        "--cleanup", "-c",
        action="store_true",
        help="Clean up stale instances and exit.",
    )
    parser.add_argument(
        "--config",
        help="Path to ck3lens_config.yaml (optional)",
        default=None,
    )

    args = parser.parse_args()

    if args.cleanup:
        removed = cleanup_stale_instances()
        print(f"Removed {removed} stale instance(s).")
        list_instances()
        return

    if args.list:
        list_instances()
        return

    # Generate instance ID if not provided
    instance_id = args.instance_id or f"ck3lens-{uuid.uuid4().hex[:8]}"

    # Set environment variable for the server to pick up
    os.environ["CK3LENS_INSTANCE_ID"] = instance_id

    if args.config:
        os.environ["CK3LENS_CONFIG"] = args.config

    # Register this instance
    register_instance(instance_id, os.getpid())

    print(f"Starting CK3 Lens MCP Server (instance: {instance_id})", file=sys.stderr)
    try:
        # Ensure the ck3lens package is importable
        # The package is in the same directory as this launcher
        package_dir = Path(__file__).parent
        if str(package_dir) not in sys.path:
            sys.path.insert(0, str(package_dir))

        # Import and run the server module properly
        # Using runpy.run_path preserves proper module semantics
        import runpy
        server_path = package_dir / "server.py"
        runpy.run_path(str(server_path), run_name="__main__")
    finally:
        unregister_instance(instance_id)


if __name__ == "__main__":
    main()
