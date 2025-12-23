"""
CK3 Lens MCP Server Launcher

This launcher script enables multiple independent MCP server instances.
Each VS Code window gets its own server instance with isolated state.

Usage:
    python launcher.py                     # Auto-generates instance ID
    python launcher.py --instance-id abc   # Uses specific instance ID
    python launcher.py --list              # Lists running instances
"""
import sys
import os
import uuid
import argparse
import subprocess
from pathlib import Path
import json
import tempfile

# Instance tracking file
INSTANCES_FILE = Path(tempfile.gettempdir()) / "ck3lens_instances.json"


def get_running_instances() -> dict:
    """Load the running instances registry."""
    if INSTANCES_FILE.exists():
        try:
            return json.loads(INSTANCES_FILE.read_text())
        except Exception:
            return {}
    return {}


def register_instance(instance_id: str, pid: int) -> None:
    """Register a new instance."""
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
    """Print all registered instances."""
    instances = get_running_instances()
    if not instances:
        print("No running instances found.")
        return
    
    print(f"Running CK3 Lens instances ({len(instances)}):")
    for iid, info in instances.items():
        print(f"  {iid}: PID {info.get('pid')} started {info.get('started_at', 'unknown')}")


def main():
    parser = argparse.ArgumentParser(description="CK3 Lens MCP Server Launcher")
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
        "--config",
        help="Path to ck3lens_config.yaml (optional)",
        default=None,
    )
    
    args = parser.parse_args()
    
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
